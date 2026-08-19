"""CLI: preprocess Metacam Studio scenes into annotation-ready form.

    python -m metacam_process /path/to/data_root
    python -m metacam_process /path/to/data_root --scenes 12thfloor 2ndfloor
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .scene import TRANSFORMS_NAME, find_scenes, load_frames
from .steps import (
    DEFAULT_FOV_DEGREES,
    DEFAULT_SIZE,
    collect_fisheye_images,
    undistort_images,
    write_sparse_model,
)

STATUS_NAME = ".metacam_process_status.json"
STAGES = ("fisheye", "undistorted", "sparse")


def load_status(path: Path) -> dict:
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_status(path: Path, status: dict) -> None:
    with open(path, "w") as f:
        json.dump(status, f, indent=2)


def mark_done(status: dict, path: Path, scene: str, stage: str) -> None:
    entry = status.setdefault(scene, {"stages": {}})
    entry["stages"][stage] = True
    entry["last_updated"] = datetime.now().isoformat()
    save_status(path, status)


def process_scene(scene_path: Path, args, status: dict, status_path: Path) -> None:
    scene = scene_path.name
    done = {} if args.force else status.get(scene, {}).get("stages", {})

    print(f"\n{'=' * 60}\n{scene}\n{'=' * 60}")

    frames = load_frames(scene_path)
    cameras = sorted({f.camera or "?" for f in frames})
    print(f"{len(frames)} frames in {TRANSFORMS_NAME} | cameras: {', '.join(cameras)}")

    if done.get("fisheye"):
        print("- collect fisheye: already done")
    else:
        print("- collect fisheye")
        result = collect_fisheye_images(
            scene_path, link=args.link, overwrite=args.force
        )
        print(f"  {result}")
        mark_done(status, status_path, scene, "fisheye")

    if done.get("undistorted"):
        print("- undistort: already done")
    else:
        print(f"- undistort to {args.size}x{args.size} @ {args.fov} deg FOV")
        result = undistort_images(
            scene_path,
            frames,
            size=args.size,
            fov_degrees=args.fov,
            overwrite=args.force,
        )
        print(f"  {result}")
        mark_done(status, status_path, scene, "undistorted")

    if done.get("sparse"):
        print("- sparse model: already done")
    else:
        print("- write COLMAP sparse model")
        count = write_sparse_model(
            scene_path, frames, size=args.size, fov_degrees=args.fov
        )
        print(f"  sparse/0 written with {count} images")
        mark_done(status, status_path, scene, "sparse")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess Metacam Studio scenes for the annotation tools."
    )
    parser.add_argument(
        "data_root", type=Path, help="directory holding one subdirectory per scene"
    )
    parser.add_argument(
        "--scenes", nargs="+", help="only process these scene directory names"
    )
    parser.add_argument(
        "--size", type=int, default=DEFAULT_SIZE, help="undistorted output edge in px"
    )
    parser.add_argument(
        "--fov", type=float, default=DEFAULT_FOV_DEGREES, help="output field of view"
    )
    parser.add_argument(
        "--link",
        action="store_true",
        help="symlink into fisheye/ instead of copying (saves disk)",
    )
    parser.add_argument(
        "--force", action="store_true", help="redo every stage, overwriting outputs"
    )
    parser.add_argument(
        "--list", action="store_true", help="list discovered scenes and exit"
    )
    parser.add_argument(
        "--status",
        type=Path,
        help=f"progress file (default: <data_root>/{STATUS_NAME})",
    )
    args = parser.parse_args()

    if not args.data_root.is_dir():
        parser.error(f"data_root is not a directory: {args.data_root}")

    scenes = find_scenes(args.data_root)
    if args.scenes:
        wanted = set(args.scenes)
        found = {p.name for p in scenes}
        for name in sorted(wanted - found):
            print(f"warning: no scene named {name!r} with a {TRANSFORMS_NAME}")
        scenes = [p for p in scenes if p.name in wanted]

    if not scenes:
        print(f"No scenes with a {TRANSFORMS_NAME} found under {args.data_root}")
        return

    if args.list:
        for path in scenes:
            print(path.name)
        return

    status_path = args.status or args.data_root / STATUS_NAME
    status = {} if args.force else load_status(status_path)

    print(f"Found {len(scenes)} scene(s) under {args.data_root}")
    for idx, scene_path in enumerate(scenes, start=1):
        print(f"\n[{idx}/{len(scenes)}]", end="")
        process_scene(scene_path, args, status, status_path)

    print(f"\n{'=' * 60}\nDone: {len(scenes)} scene(s)\n{'=' * 60}")


if __name__ == "__main__":
    main()
