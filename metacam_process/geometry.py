"""Coordinate-system conversion between Metacam Studio and COLMAP conventions."""

import numpy as np

GLOBAL_ROT = np.array([
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0],
])

GLOBAL_TRANS = np.array([
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
])

_Y_ROT_180 = np.array([
    [1.0, 0.0, 0.0, 0.0],
    [0.0, -1.0, 0.0, 0.0],
    [0.0, 0.0, -1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
])


def apply_coordinate_corrections(transform_matrix: np.ndarray) -> np.ndarray:
    """Map a Studio camera-to-world matrix into the convention COLMAP expects."""
    corrected = transform_matrix.copy()
    corrected[:3, :3] = corrected[:3, :3] @ GLOBAL_ROT
    corrected = GLOBAL_TRANS @ corrected
    return _Y_ROT_180 @ corrected
