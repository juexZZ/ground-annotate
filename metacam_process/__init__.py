"""Preprocessing for Metacam Studio exports.

Turns a Studio scene (`camera/`, `transforms.json`) into the layout the
annotation tools expect: undistorted `images/` plus a COLMAP `sparse/0` model.
"""

from .scene import Frame, Intrinsics, find_scenes, group_by_intrinsics, load_frames
from .steps import (
    DEFAULT_FOV_DEGREES,
    DEFAULT_SIZE,
    collect_fisheye_images,
    target_camera_matrix,
    undistort_images,
    write_sparse_model,
)

__all__ = [
    "Frame",
    "Intrinsics",
    "find_scenes",
    "group_by_intrinsics",
    "load_frames",
    "collect_fisheye_images",
    "undistort_images",
    "write_sparse_model",
    "target_camera_matrix",
    "DEFAULT_SIZE",
    "DEFAULT_FOV_DEGREES",
]
