"""Reading a Metacam Studio scene: `transforms.json` and its per-camera intrinsics."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TRANSFORMS_NAME = "transforms.json"


@dataclass(frozen=True)
class Intrinsics:
    """Fisheye intrinsics for one physical camera, at the reference resolution.

    Hashable and compared by value, so frames sharing a calibration group
    together and each group only builds its undistortion map once.
    """

    w: int
    h: int
    fl_x: float
    fl_y: float
    cx: float
    cy: float
    k1: float
    k2: float
    k3: float
    k4: float

    @classmethod
    def from_frame(cls, frame: dict) -> "Intrinsics":
        return cls(
            w=int(frame["w"]),
            h=int(frame["h"]),
            fl_x=float(frame["fl_x"]),
            fl_y=float(frame["fl_y"]),
            cx=float(frame["cx"]),
            cy=float(frame["cy"]),
            k1=float(frame.get("k1", 0.0)),
            k2=float(frame.get("k2", 0.0)),
            k3=float(frame.get("k3", 0.0)),
            k4=float(frame.get("k4", 0.0)),
        )

    def camera_matrix(self, scale_x: float = 1.0, scale_y: float = 1.0) -> np.ndarray:
        """K, rescaled from the reference resolution to the actual image size."""
        return np.array(
            [
                [self.fl_x * scale_x, 0.0, self.cx * scale_x],
                [0.0, self.fl_y * scale_y, self.cy * scale_y],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    def distortion(self) -> np.ndarray:
        return np.array([self.k1, self.k2, self.k3, self.k4], dtype=np.float64)


@dataclass(frozen=True)
class Frame:
    """One image in a scene, with its camera model and camera-to-world pose."""

    camera: str | None  # "left" / "right", or None when the path has no camera dir
    stem: str  # "left_<timestamp>"
    source_name: str  # name under fisheye/
    output_name: str  # name under images/
    intrinsics: Intrinsics
    transform_matrix: np.ndarray


def _parse_file_path(file_path: str) -> tuple[str | None, str, str, str]:
    """Split a Studio `file_path` (e.g. 'left\\<ts>.jpg') into naming components."""
    normalised = file_path.replace("\\", "/")
    parts = normalised.split("/")
    if len(parts) == 2:
        camera, timestamp_with_ext = parts
        stem = f"{camera}_{Path(timestamp_with_ext).stem}"
        return camera, stem, f"{stem}.jpg", f"{stem}.png"
    # Fall back to the bare filename when the layout is not <camera>/<file>.
    name = Path(normalised).name
    return None, Path(name).stem, name, name


def load_frames(scene_path: Path) -> list[Frame]:
    """Load every frame of a scene from its `transforms.json`."""
    transforms_path = scene_path / TRANSFORMS_NAME
    with open(transforms_path, "r") as f:
        data = json.load(f)

    frames = []
    for entry in data.get("frames", []):
        camera, stem, source_name, output_name = _parse_file_path(
            entry.get("file_path", "")
        )
        frames.append(
            Frame(
                camera=camera,
                stem=stem,
                source_name=source_name,
                output_name=output_name,
                intrinsics=Intrinsics.from_frame(entry),
                transform_matrix=np.array(entry["transform_matrix"], dtype=np.float64),
            )
        )
    return frames


def group_by_intrinsics(frames: list[Frame]) -> dict[Intrinsics, list[Frame]]:
    """Bucket frames by calibration, so each camera is undistorted with its own K/D."""
    groups: dict[Intrinsics, list[Frame]] = {}
    for frame in frames:
        groups.setdefault(frame.intrinsics, []).append(frame)
    return groups


def find_scenes(data_root: Path) -> list[Path]:
    """Every immediate subdirectory of `data_root` that holds a `transforms.json`."""
    return sorted(
        p for p in data_root.iterdir() if p.is_dir() and (p / TRANSFORMS_NAME).is_file()
    )
