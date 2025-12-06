import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
from PIL import Image

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
SCENE_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def create_app(data_root: Path) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    resolved_root = data_root.expanduser().resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"Dataset root '{resolved_root}' does not exist or is not a directory.")

    app.config["DATA_ROOT"] = resolved_root
    app.config["DATA_ROOT_STR"] = str(resolved_root)

    def _scene_directory(scene_id: str) -> Path:
        candidate = (resolved_root / scene_id).resolve()
        if not candidate.is_dir() or not str(candidate).startswith(str(resolved_root)):
            abort(404, description="Scene not found")
        return candidate

    def _find_image(scene_dir: Path, prefix: str) -> Optional[Path]:
        prefix_lower = prefix.lower()
        for entry in sorted(scene_dir.iterdir()):
            if not entry.is_file():
                continue
            name_lower = entry.name.lower()
            if not name_lower.startswith(prefix_lower):
                continue
            if entry.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                return entry
        return None

    def _annotation_path(scene_dir: Path) -> Path:
        return scene_dir / "annotation.json"

    def _image_size(path: Path) -> Optional[Tuple[int, int]]:
        try:
            with Image.open(path) as img:
                return img.width, img.height
        except (OSError, FileNotFoundError):
            return None

    def _read_annotation(scene_dir: Path) -> Optional[Dict]:
        path = _annotation_path(scene_dir)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return None
        payload = data.get("annotation") if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            return None
        point = payload.get("point")
        label = payload.get("label")
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            return None
        if not isinstance(label, str):
            return None
        image_size = payload.get("image_size") if isinstance(payload, dict) else None
        size_payload = None
        if isinstance(image_size, dict):
            width = image_size.get("width")
            height = image_size.get("height")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                size_payload = {"width": float(width), "height": float(height)}

        return {
            "x": point["x"],
            "y": point["y"],
            "label": label,
            "updated_at": payload.get("updated_at"),
            "image_size": size_payload,
        }

    def _normalize_scene_id(raw_value: str) -> Optional[str]:
        cleaned = SCENE_ID_SAFE_PATTERN.sub("_", raw_value)
        cleaned = cleaned.strip("_")
        if not cleaned:
            return None
        return cleaned[:80]

    def _generate_scene_id() -> str:
        base = datetime.now().strftime("scene_%Y%m%d_%H%M%S")
        candidate = base
        counter = 1
        while (resolved_root / candidate).exists():
            candidate = f"{base}_{counter:03d}"
            counter += 1
        return candidate

    def _validate_image_file(file_storage, label: str) -> str:
        if file_storage is None or not file_storage.filename:
            abort(400, description=f"{label} file is required.")
        suffix = Path(file_storage.filename).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            abort(400, description=f"{label} must be one of: {', '.join(SUPPORTED_IMAGE_EXTENSIONS)}")
        return suffix

    def _scene_payload(scene_dir: Path) -> Dict:
        name = scene_dir.name
        image_a = _find_image(scene_dir, "image_a")
        image_b = _find_image(scene_dir, "image_b")
        annotation = _read_annotation(scene_dir)
        return {
            "id": name,
            "name": name,
            "annotated": annotation is not None,
            "images": {
                "a": url_for("serve_image", scene_id=name, image_kind="a") if image_a else None,
                "b": url_for("serve_image", scene_id=name, image_kind="b") if image_b else None,
            },
            "annotation": annotation,
        }

    @app.route("/")
    def index():
        return render_template("index.html", dataset_root=str(resolved_root))

    @app.route("/api/scenes", methods=["GET"])
    def list_scenes():
        scenes = []
        for entry in sorted(resolved_root.iterdir()):
            if entry.is_dir():
                scenes.append(_scene_payload(entry))
        return jsonify(scenes)

    @app.route("/api/scenes/<scene_id>", methods=["GET"])
    def get_scene(scene_id: str):
        scene_dir = _scene_directory(scene_id)
        return jsonify(_scene_payload(scene_dir))

    @app.route("/api/scenes/<scene_id>/images/<image_kind>", methods=["GET"])
    def serve_image(scene_id: str, image_kind: str):
        if image_kind not in {"a", "b"}:
            abort(404)
        scene_dir = _scene_directory(scene_id)
        prefix = f"image_{image_kind}"
        image = _find_image(scene_dir, prefix)
        if not image:
            abort(404, description=f"{prefix} not found in scene {scene_id}")
        return send_file(image)

    @app.route("/api/scenes/<scene_id>/annotation", methods=["PUT"])
    def save_annotation(scene_id: str):
        scene_dir = _scene_directory(scene_id)
        payload = request.get_json(force=True, silent=True) or {}
        try:
            x = float(payload["x"])
            y = float(payload["y"])
        except (KeyError, TypeError, ValueError):
            abort(400, description="Annotation requires numeric x and y fields")
        label = payload.get("label", "").strip()
        if not label:
            abort(400, description="Annotation label cannot be empty")

        timestamp = datetime.now(timezone.utc).isoformat()
        image_b = _find_image(scene_dir, "image_b")
        image_size = _image_size(image_b) if image_b else None
        annotation_payload = {
            "scene": scene_dir.name,
            "annotation": {
                "point": {"x": x, "y": y},
                "label": label,
                "updated_at": timestamp,
                "image": image_b.name if image_b else None,
            },
        }
        if image_size:
            annotation_payload["annotation"]["image_size"] = {
                "width": image_size[0],
                "height": image_size[1],
            }
        path = _annotation_path(scene_dir)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(annotation_payload, handle, indent=2)
            handle.write("\n")

        return jsonify({
            "status": "ok",
            "annotation": annotation_payload["annotation"],
        })

    @app.route("/api/scenes/upload", methods=["POST"])
    def upload_scene():
        scene_id_raw = request.form.get("scene_id", "").strip()
        normalized_scene_id = _normalize_scene_id(scene_id_raw) if scene_id_raw else None
        if scene_id_raw and not normalized_scene_id:
            abort(400, description="Scene name must contain letters, numbers, '_' or '-'.")

        scene_id = normalized_scene_id or _generate_scene_id()
        scene_dir = resolved_root / scene_id
        if scene_dir.exists():
            abort(400, description=f"Scene '{scene_id}' already exists. Please pick a different name.")

        file_a = request.files.get("image_a")
        file_b = request.files.get("image_b")
        suffix_a = _validate_image_file(file_a, "Image A")
        suffix_b = _validate_image_file(file_b, "Image B")

        scene_dir.mkdir(parents=False, exist_ok=False)
        file_a.save(scene_dir / f"image_a{suffix_a}")
        file_b.save(scene_dir / f"image_b{suffix_b}")

        payload = _scene_payload(scene_dir)
        return jsonify({
            "status": "ok",
            "scene": payload,
        })

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the annotation server for human collected data.")
    parser.add_argument("data_root", help="Path to folder whose subdirectories contain image_a/image_b pairs.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind. Default: %(default)s")
    parser.add_argument("--port", type=int, default=1234, help="Port to serve the UI. Default: %(default)s")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (auto reload). Only for local development.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data_root = Path(args.data_root)
    try:
        app = create_app(data_root)
    except ValueError as exc:  # Raised when directory is invalid
        raise SystemExit(str(exc)) from exc

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
