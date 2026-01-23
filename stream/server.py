import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, abort, jsonify, render_template, request, send_file, url_for
from PIL import Image, ImageOps

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
FILENAME_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")


def _load_labels(labels_json_path: Path) -> List[str]:
    if not labels_json_path.is_file():
        raise ValueError(f"Labels json '{labels_json_path}' does not exist or is not a file.")
    try:
        with labels_json_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Labels json '{labels_json_path}' is not valid JSON.") from exc

    labels: Any
    if isinstance(raw, list):
        labels = raw
    elif isinstance(raw, dict):
        labels = raw.get("labels")
    else:
        labels = None

    if not isinstance(labels, list) or not labels:
        raise ValueError("Labels json must be a non-empty list, or a dict with a non-empty 'labels' list.")

    cleaned: List[str] = []
    seen = set()
    for item in labels:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        cleaned.append(name)
        seen.add(name)
    if not cleaned:
        raise ValueError("Labels json did not contain any valid string labels.")
    return cleaned


def _safe_filename(raw_value: str) -> Optional[str]:
    cleaned = FILENAME_SAFE_PATTERN.sub("", raw_value).strip()
    if not cleaned:
        return None
    return cleaned[:255]


def _default_output_path(images_root: Path) -> Path:
    return images_root / "stream_annotations.json"


def _exif_orientation(path: Path) -> int:
    # 1..8 per EXIF standard. Default = 1 (normal).
    try:
        with Image.open(path) as img:
            exif = getattr(img, "getexif", None)
            if exif is None:
                return 1
            value = img.getexif().get(274, 1)  # 274 = Orientation
            if isinstance(value, int) and 1 <= value <= 8:
                return value
            return 1
    except (OSError, FileNotFoundError, ValueError):
        return 1


def _image_size_raw(path: Path) -> Optional[Dict[str, int]]:
    """Original pixel dimensions as stored in the file (no EXIF transpose)."""
    try:
        with Image.open(path) as img:
            return {"width": int(img.width), "height": int(img.height)}
    except (OSError, FileNotFoundError, ValueError):
        return None


def _image_size_for_ui_coords(path: Path) -> Optional[Dict[str, int]]:
    """
    Return width/height in the same coordinate space as the browser click coordinates.

    Most browsers apply EXIF orientation for rendering; we mirror that here using
    ImageOps.exif_transpose so saved image_size matches (x, y) pixel units.
    """
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            return {"width": int(img.width), "height": int(img.height)}
    except (OSError, FileNotFoundError, ValueError):
        return None


def _read_results(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    images = data.get("images") if isinstance(data, dict) else None
    if not isinstance(images, list):
        return {}

    by_file: Dict[str, Dict[str, Any]] = {}
    for item in images:
        if not isinstance(item, dict):
            continue
        file_name = item.get("file")
        if not isinstance(file_name, str) or not file_name:
            continue
        by_file[file_name] = item
    return by_file


def _write_results(path: Path, labels: List[str], items_by_file: Dict[str, Dict[str, Any]]) -> None:
    payload = {
        "version": 2,
        "labels": labels,
        "images": [items_by_file[k] for k in sorted(items_by_file.keys())],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def create_app(images_root: Path, labels_json: Path, output_json: Optional[Path] = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    resolved_root = images_root.expanduser().resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"Images root '{resolved_root}' does not exist or is not a directory.")

    resolved_labels = labels_json.expanduser().resolve()
    labels = _load_labels(resolved_labels)

    resolved_output = (output_json or _default_output_path(resolved_root)).expanduser().resolve()
    if not str(resolved_output).startswith(str(resolved_root)):
        raise ValueError("Output json must live inside the images root folder (for safety).")

    def _list_images() -> List[Path]:
        images: List[Path] = []
        for entry in sorted(resolved_root.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            images.append(entry)
        return images

    def _image_path(file_name: str) -> Path:
        safe = _safe_filename(file_name)
        if not safe:
            abort(404)
        candidate = (resolved_root / safe).resolve()
        if not candidate.is_file() or not str(candidate).startswith(str(resolved_root)):
            abort(404)
        if candidate.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            abort(404)
        return candidate

    def _image_payload(file_path: Path) -> Dict[str, Any]:
        file_name = file_path.name
        results = _read_results(resolved_output)
        item = results.get(file_name)
        annotations = item.get("annotations") if isinstance(item, dict) else None
        has_any = isinstance(annotations, list) and len(annotations) > 0
        completed = isinstance(item, dict)
        orientation = _exif_orientation(file_path)
        return {
            "id": file_name,
            "file": file_name,
            "url": url_for("serve_image", file_name=file_name),
            "completed": completed,
            "annotated": bool(has_any),
            "result": item if isinstance(item, dict) else None,
            "meta": {
                "image_size": _image_size_raw(file_path),
                "exif_orientation": orientation,
                "display_size": _image_size_for_ui_coords(file_path),
                "point_space": "raw",
            },
        }

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            images_root=str(resolved_root),
            labels_path=str(resolved_labels),
            output_path=str(resolved_output),
        )

    @app.route("/api/labels", methods=["GET"])
    def get_labels():
        return jsonify(labels)

    @app.route("/api/images", methods=["GET"])
    def list_images():
        images = _list_images()
        payload = [_image_payload(p) for p in images]
        return jsonify(payload)

    @app.route("/api/images/<file_name>", methods=["GET"])
    def get_image(file_name: str):
        path = _image_path(file_name)
        return jsonify(_image_payload(path))

    @app.route("/api/images/<file_name>/raw", methods=["GET"])
    def serve_image(file_name: str):
        path = _image_path(file_name)
        return send_file(path)

    @app.route("/api/images/<file_name>/annotation", methods=["PUT"])
    def save_annotation(file_name: str):
        # Ensures the image exists (and prevents path traversal).
        image_path = _image_path(file_name)

        payload = request.get_json(force=True, silent=True) or {}
        new_traversal = bool(payload.get("new_traversal", False))
        annotations = payload.get("annotations", [])
        if annotations is None:
            annotations = []
        if not isinstance(annotations, list):
            abort(400, description="'annotations' must be a list.")

        normalized: List[Dict[str, Any]] = []
        for ann in annotations:
            if not isinstance(ann, dict):
                continue
            category = ann.get("category")
            point = ann.get("point")
            if not isinstance(category, str):
                continue
            category = category.strip()
            if not category or category not in labels:
                continue
            if not isinstance(point, dict) or "x" not in point or "y" not in point:
                continue
            try:
                x = float(point["x"])
                y = float(point["y"])
            except (TypeError, ValueError):
                continue
            normalized.append({"category": category, "point": {"x": x, "y": y}})

        results = _read_results(resolved_output)
        results[file_name] = {
            "file": file_name,
            "new_traversal": new_traversal,
            "annotations": normalized,
            "image_size": _image_size_raw(image_path),
            "exif_orientation": _exif_orientation(image_path),
            "display_size": _image_size_for_ui_coords(image_path),
            "point_space": "raw",
        }
        _write_results(resolved_output, labels, results)

        return jsonify({"status": "ok", "result": results[file_name]})

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the stream annotation server for flat image folders.")
    parser.add_argument("images_root", help="Path to a folder that contains images (flat list).")
    parser.add_argument("labels_json", help="Path to json file containing predefined labels.")
    parser.add_argument(
        "--output",
        default=None,
        help="Output results json path (must be inside images_root). Default: <images_root>/stream_annotations.json",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind. Default: %(default)s")
    parser.add_argument("--port", type=int, default=1235, help="Port to serve the UI. Default: %(default)s")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (auto reload). Only for local development.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    images_root = Path(args.images_root)
    labels_json = Path(args.labels_json)
    output = Path(args.output) if args.output else None
    try:
        app = create_app(images_root=images_root, labels_json=labels_json, output_json=output)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

