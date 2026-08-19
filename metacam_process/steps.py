"""The three preprocessing steps that turn a Metacam Studio export into a
COLMAP-style scene the annotation tools can consume.

    camera/{left,right}/*.jpg      ->  fisheye/{side}_{ts}.jpg   (collect_fisheye_images)
    fisheye/{side}_{ts}.jpg        ->  images/{side}_{ts}.png    (undistort_images)
    transforms.json + images/      ->  sparse/0/                 (write_sparse_model)
"""

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation as SciRot
from tqdm import tqdm

from . import colmap
from .geometry import apply_coordinate_corrections
from .scene import Frame, Intrinsics, group_by_intrinsics

CAMERA_SIDES = ("left", "right")

DEFAULT_SIZE = 800
DEFAULT_FOV_DEGREES = 90.0


@dataclass
class StepResult:
    written: int = 0
    skipped: int = 0
    missing: int = 0

    def __str__(self) -> str:
        return f"{self.written} written, {self.skipped} already present, {self.missing} missing"


def target_camera_matrix(size: int, fov_degrees: float) -> np.ndarray:
    """Pinhole K for a square output image of the given size and field of view.

    The defaults (800 px, 90 deg) reproduce the original hard-coded
    fx=fy=cx=cy=400 target.
    """
    # Rounded because tan(pi/4) is not exactly 1 in floating point, which would
    # otherwise write 400.00000000000006 instead of 400.0 into cameras.txt.
    focal = round((size / 2.0) / math.tan(math.radians(fov_degrees) / 2.0), 9)
    centre = size / 2.0
    return np.array(
        [[focal, 0.0, centre], [0.0, focal, centre], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def collect_fisheye_images(
    scene_path: Path, link: bool = False, overwrite: bool = False
) -> StepResult:
    """Flatten `camera/<side>/<ts>.jpg` into `fisheye/<side>_<ts>.jpg`."""
    camera_dir = scene_path / "camera"
    fisheye_dir = scene_path / "fisheye"
    fisheye_dir.mkdir(parents=True, exist_ok=True)

    result = StepResult()
    for side in CAMERA_SIDES:
        side_dir = camera_dir / side
        if not side_dir.is_dir():
            continue
        for img_path in sorted(side_dir.glob("*.jpg")):
            dst = fisheye_dir / f"{side}_{img_path.stem}.jpg"
            if dst.exists() or dst.is_symlink():
                if not overwrite:
                    result.skipped += 1
                    continue
                dst.unlink()
            if link:
                dst.symlink_to(img_path.resolve())
            else:
                shutil.copy(img_path, dst)
            result.written += 1
    return result


def _probe_image_size(fisheye_dir: Path, frames: list[Frame]) -> tuple[int, int] | None:
    """Actual (width, height) of the first readable source image in this group."""
    for frame in frames:
        path = fisheye_dir / frame.source_name
        if not path.exists():
            continue
        img = cv2.imread(str(path))
        if img is not None:
            return img.shape[1], img.shape[0]
    return None


def undistort_images(
    scene_path: Path,
    frames: list[Frame],
    size: int = DEFAULT_SIZE,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
    overwrite: bool = False,
) -> StepResult:
    """Fisheye -> pinhole, using each camera's own intrinsics.

    Frames are grouped by calibration so the left and right cameras are each
    undistorted with their own K/D, and the remap tables are built once per
    group rather than once per image.
    """
    fisheye_dir = scene_path / "fisheye"
    images_dir = scene_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    target_k = target_camera_matrix(size, fov_degrees)
    out_size = (size, size)
    result = StepResult()

    groups = group_by_intrinsics(frames)
    for intrinsics, group in groups.items():
        label = ", ".join(sorted({f.camera or "?" for f in group}))

        actual = _probe_image_size(fisheye_dir, group)
        if actual is None:
            print(f"  [{label}] no readable source image found, skipping {len(group)} frames")
            result.missing += len(group)
            continue
        actual_w, actual_h = actual

        scale_x = actual_w / intrinsics.w
        scale_y = actual_h / intrinsics.h
        k_fish = intrinsics.camera_matrix(scale_x, scale_y)
        distortion = intrinsics.distortion()

        # Identical for every frame in the group, so build it once.
        map1, map2 = cv2.fisheye.initUndistortRectifyMap(
            k_fish, distortion, np.eye(3), target_k, out_size, cv2.CV_16SC2
        )

        print(
            f"  [{label}] {len(group)} frames | source {actual_w}x{actual_h} "
            f"| fl_x={intrinsics.fl_x:.3f} cx={intrinsics.cx:.3f} k1={intrinsics.k1:.6f}"
        )

        for frame in tqdm(group, desc=f"  undistort {label}", leave=False):
            dst_path = images_dir / frame.output_name
            if dst_path.exists() and not overwrite:
                result.skipped += 1
                continue
            src_path = fisheye_dir / frame.source_name
            if not src_path.exists():
                result.missing += 1
                continue
            img = cv2.imread(str(src_path))
            if img is None:
                result.missing += 1
                continue
            undistorted = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
            cv2.imwrite(str(dst_path), undistorted)
            result.written += 1

    return result


def write_sparse_model(
    scene_path: Path,
    frames: list[Frame],
    size: int = DEFAULT_SIZE,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
) -> int:
    """Emit `sparse/0` with the Studio poses and no triangulated points.

    All images share a single PINHOLE camera because undistortion has already
    mapped every camera onto the same target intrinsics.
    """
    target_k = target_camera_matrix(size, fov_degrees)
    focal = target_k[0, 0]
    centre = target_k[0, 2]

    cameras = {
        1: colmap.Camera(
            id=1,
            model="PINHOLE",
            width=size,
            height=size,
            params=np.array([focal, focal, centre, centre]),
        )
    }

    images_dir = scene_path / "images"
    images = {}
    image_id = 1
    for frame in frames:
        if not (images_dir / frame.output_name).exists():
            continue

        world_to_camera = np.linalg.inv(
            apply_coordinate_corrections(frame.transform_matrix)
        )
        quat_xyzw = SciRot.from_matrix(world_to_camera[:3, :3]).as_quat()
        quat_wxyz = np.array(
            [quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]]
        )
        xys, point3D_ids = colmap.empty_observations()

        images[image_id] = colmap.Image(
            id=image_id,
            qvec=quat_wxyz,
            tvec=world_to_camera[:3, 3],
            camera_id=1,
            name=frame.output_name,
            xys=xys,
            point3D_ids=point3D_ids,
        )
        image_id += 1

    colmap.write_model(cameras, images, {}, scene_path / "sparse" / "0")
    return len(images)
