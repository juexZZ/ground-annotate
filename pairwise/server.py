import argparse
import base64
import io
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
import numpy as np
from PIL import Image, ImageOps

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
SCENE_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
MASK_FILENAME = "mask_b.png"


def create_app(data_root: Path, mask_model_path: Optional[str], enable_masking: bool = True) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    resolved_root = data_root.expanduser().resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"Dataset root '{resolved_root}' does not exist or is not a directory.")

    app.config["DATA_ROOT"] = resolved_root
    app.config["DATA_ROOT_STR"] = str(resolved_root)
    app.config["MASK_RUNTIME"] = _initialize_mask_runtime(mask_model_path, enable_masking)

    def _mask_runtime() -> Dict:
        runtime = app.config.get("MASK_RUNTIME")
        if not isinstance(runtime, dict):
            abort(500, description="Mask runtime is not initialized")
        return runtime

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

    def _mask_path(scene_dir: Path) -> Path:
        return scene_dir / MASK_FILENAME

    def _mask_url(scene_dir: Path, mask_name: str) -> Optional[str]:
        mask_file = (scene_dir / mask_name).resolve()
        if not mask_file.is_file() or not str(mask_file).startswith(str(scene_dir.resolve())):
            return None
        version = int(mask_file.stat().st_mtime_ns)
        return url_for("serve_mask", scene_id=scene_dir.name, v=version)

    def _image_size(path: Path) -> Optional[Tuple[int, int]]:
        try:
            with Image.open(path) as img:
                upright = ImageOps.exif_transpose(img)
                return upright.width, upright.height
        except (OSError, FileNotFoundError):
            return None

    def _encode_mask_png(mask: np.ndarray) -> str:
        out = io.BytesIO()
        mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        mask_img.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode("ascii")

    def _save_mask(mask: np.ndarray, scene_dir: Path) -> str:
        mask_path = _mask_path(scene_dir)
        mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
        mask_img.save(mask_path)
        return mask_path.name

    def _parse_refinement_points(raw_points) -> List[Dict]:
        if not isinstance(raw_points, list) or len(raw_points) == 0:
            abort(400, description="Mask generation requires a non-empty points array")

        normalized: List[Dict] = []
        for idx, item in enumerate(raw_points):
            if not isinstance(item, dict):
                abort(400, description=f"Point at index {idx} must be an object")
            try:
                x = float(item["x"])
                y = float(item["y"])
            except (KeyError, TypeError, ValueError):
                abort(400, description=f"Point at index {idx} requires numeric x and y")
            kind = str(item.get("kind", "positive")).strip().lower()
            if kind not in {"positive", "negative"}:
                abort(400, description=f"Point at index {idx} kind must be 'positive' or 'negative'")
            normalized.append({"x": x, "y": y, "kind": kind})

        if not any(point["kind"] == "positive" for point in normalized):
            abort(400, description="At least one positive point is required")
        return normalized

    def _parse_annotation_point(payload, fallback_x: float, fallback_y: float) -> Dict:
        candidate = payload.get("annotation_point") if isinstance(payload, dict) else None
        if isinstance(candidate, dict):
            try:
                x = float(candidate["x"])
                y = float(candidate["y"])
            except (KeyError, TypeError, ValueError):
                abort(400, description="annotation_point requires numeric x and y")
            return {"x": x, "y": y}
        return {"x": fallback_x, "y": fallback_y}

    def _predict_mask(scene_dir: Path, points: List[Dict]) -> Tuple[np.ndarray, float, Tuple[int, int], str]:
        runtime = _mask_runtime()
        if not runtime.get("ready"):
            abort(503, description=runtime.get("message", "Mask model is not ready"))

        image_b = _find_image(scene_dir, "image_b")
        if not image_b:
            abort(404, description="image_b not found")

        try:
            with Image.open(image_b) as loaded:
                image = ImageOps.exif_transpose(loaded).convert("RGB")
                width, height = image.size
        except OSError:
            abort(500, description=f"Unable to load {image_b.name}")

        np_mod = runtime.get("np")
        model = runtime.get("model")
        processor = runtime.get("processor")
        lock = runtime.get("lock")
        if np_mod is None or model is None or processor is None or lock is None:
            abort(500, description="Mask runtime is incomplete")

        point_coords = np_mod.array([[p["x"], p["y"]] for p in points], dtype=np.float32)
        point_labels = np_mod.array([1 if p["kind"] == "positive" else 0 for p in points], dtype=np.int32)
        with lock:
            inference_state = processor.set_image(image)
            masks, scores, _ = model.predict_inst(
                inference_state,
                point_coords=point_coords,
                point_labels=point_labels,
                multimask_output=True,
            )
        sorted_idx = np_mod.argsort(scores)[::-1]
        best_idx = sorted_idx[0]
        best_mask = (masks[best_idx] > 0.5).astype(np.uint8)
        score = float(scores[best_idx])
        return best_mask, score, (width, height), image_b.name

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
        mask_name = payload.get("mask")
        mask_url = None
        if isinstance(mask_name, str) and mask_name:
            mask_url = _mask_url(scene_dir, mask_name)
        elif _mask_path(scene_dir).is_file():
            mask_name = MASK_FILENAME
            mask_url = _mask_url(scene_dir, mask_name)

        points_payload = payload.get("mask_points")
        normalized_points = []
        if isinstance(points_payload, list):
            for item in points_payload:
                if not isinstance(item, dict):
                    continue
                x = item.get("x")
                y = item.get("y")
                kind = item.get("kind")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)) and kind in {"positive", "negative"}:
                    normalized_points.append({"x": float(x), "y": float(y), "kind": kind})

        annotation_point = payload.get("annotation_point")
        annotation_point_payload = None
        if isinstance(annotation_point, dict):
            px = annotation_point.get("x")
            py = annotation_point.get("y")
            if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                annotation_point_payload = {"x": float(px), "y": float(py)}

        return {
            "x": point["x"],
            "y": point["y"],
            "annotation_point": annotation_point_payload or {"x": float(point["x"]), "y": float(point["y"])},
            "label": label,
            "updated_at": payload.get("updated_at"),
            "image_size": size_payload,
            "mask": mask_name if isinstance(mask_name, str) and mask_name else None,
            "mask_url": mask_url,
            "mask_points": normalized_points,
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

    @app.route("/api/scenes/<scene_id>/mask", methods=["GET"])
    def serve_mask(scene_id: str):
        scene_dir = _scene_directory(scene_id)
        mask_path = _mask_path(scene_dir)
        if not mask_path.is_file():
            abort(404, description=f"{MASK_FILENAME} not found in scene {scene_id}")
        return send_file(mask_path)

    @app.route("/api/mask/status", methods=["GET"])
    def mask_status():
        runtime = _mask_runtime()
        return jsonify({
            "ready": bool(runtime.get("ready")),
            "device": runtime.get("device"),
            "message": runtime.get("message"),
        })

    @app.route("/api/scenes/<scene_id>/mask-preview", methods=["POST"])
    def preview_mask(scene_id: str):
        scene_dir = _scene_directory(scene_id)
        payload = request.get_json(force=True, silent=True) or {}
        points = _parse_refinement_points(payload.get("points"))
        mask, score, image_size, image_name = _predict_mask(scene_dir, points)
        encoded = _encode_mask_png(mask)
        return jsonify({
            "status": "ok",
            "score": score,
            "image_size": {"width": image_size[0], "height": image_size[1]},
            "image": image_name,
            "mask_png_base64": encoded,
            "points": points,
        })

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
        annotation_point = _parse_annotation_point(payload, x, y)
        raw_points = payload.get("mask_points")
        points = _parse_refinement_points(raw_points) if raw_points is not None else [{"x": annotation_point["x"], "y": annotation_point["y"], "kind": "positive"}]
        if raw_points is None:
            points[0]["x"] = annotation_point["x"]
            points[0]["y"] = annotation_point["y"]

        annotation_payload = {
            "scene": scene_dir.name,
            "annotation": {
                "point": {"x": annotation_point["x"], "y": annotation_point["y"]},
                "annotation_point": {"x": annotation_point["x"], "y": annotation_point["y"]},
                "label": label,
                "updated_at": timestamp,
                "image": image_b.name if image_b else None,
                "mask_points": points,
            },
        }
        if image_size:
            annotation_payload["annotation"]["image_size"] = {
                "width": image_size[0],
                "height": image_size[1],
            }
        runtime = _mask_runtime()
        if runtime.get("ready"):
            mask, score, _, _ = _predict_mask(scene_dir, points)
            mask_filename = _save_mask(mask, scene_dir)
            annotation_payload["annotation"]["mask"] = mask_filename
            annotation_payload["annotation"]["mask_url"] = _mask_url(scene_dir, mask_filename)
            annotation_payload["annotation"]["mask_score"] = score

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
        "--mask-model-path",
        default=None,
        help="Optional path to SAM3 checkpoint. If omitted, SAM3 default loading is used.",
    )
    parser.add_argument(
        "--disable-masking",
        action="store_true",
        help="Disable SAM3 loading and mask preview APIs.",
    )
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
        app = create_app(data_root, mask_model_path=args.mask_model_path, enable_masking=not args.disable_masking)
    except ValueError as exc:  # Raised when directory is invalid
        raise SystemExit(str(exc)) from exc

    app.run(host=args.host, port=args.port, debug=args.debug)


def _initialize_mask_runtime(mask_model_path: Optional[str], enable_masking: bool) -> Dict:
    if not enable_masking:
        return {
            "ready": False,
            "device": None,
            "message": "Masking is disabled by --disable-masking",
            "model": None,
            "processor": None,
            "np": None,
            "lock": threading.Lock(),
        }

    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    try:
        import torch
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor
    except Exception as exc:
        return {
            "ready": False,
            "device": None,
            "message": f"SAM3 dependencies are unavailable: {exc}",
            "model": None,
            "processor": None,
            "np": None,
            "lock": threading.Lock(),
        }

    device = torch.device("cpu")
    if torch.cuda.is_available():
        device = torch.device("cuda")
        if torch.cuda.get_device_properties(0).major >= 8:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
    elif torch.backends.mps.is_available():
        device = torch.device("mps")

    try:
        if mask_model_path:
            model = build_sam3_image_model(checkpoint_path=mask_model_path, enable_inst_interactivity=True)
        else:
            model = build_sam3_image_model(enable_inst_interactivity=True)
        model.eval()
        model.to(device)
        processor = Sam3Processor(model)
        print(f"SAM3 model loaded from {mask_model_path if mask_model_path else 'default'}")
    except Exception as exc:
        return {
            "ready": False,
            "device": str(device),
            "message": f"Failed to initialize SAM3: {exc}",
            "model": None,
            "processor": None,
            "np": None,
            "lock": threading.Lock(),
        }

    return {
        "ready": True,
        "device": str(device),
        "message": "SAM3 model loaded",
        "model": model,
        "processor": processor,
        "np": np,
        "lock": threading.Lock(),
    }


if __name__ == "__main__":
    main()

