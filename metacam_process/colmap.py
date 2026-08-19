"""Minimal COLMAP sparse-model writers.

Only the subset needed to emit a `sparse/0` model with known poses and no
triangulated points. Both binary and text variants are written, since
downstream tools differ in which one they read.
"""

import collections
import struct
from pathlib import Path

import numpy as np

CameraModel = collections.namedtuple(
    "CameraModel", ["model_id", "model_name", "num_params"]
)
Camera = collections.namedtuple("Camera", ["id", "model", "width", "height", "params"])
Image = collections.namedtuple(
    "Image", ["id", "qvec", "tvec", "camera_id", "name", "xys", "point3D_ids"]
)
Point3D = collections.namedtuple(
    "Point3D", ["id", "xyz", "rgb", "error", "image_ids", "point2D_idxs"]
)

CAMERA_MODELS = {
    CameraModel(model_id=0, model_name="SIMPLE_PINHOLE", num_params=3),
    CameraModel(model_id=1, model_name="PINHOLE", num_params=4),
    CameraModel(model_id=2, model_name="SIMPLE_RADIAL", num_params=4),
    CameraModel(model_id=3, model_name="RADIAL", num_params=5),
    CameraModel(model_id=4, model_name="OPENCV", num_params=8),
    CameraModel(model_id=5, model_name="OPENCV_FISHEYE", num_params=8),
    CameraModel(model_id=6, model_name="FULL_OPENCV", num_params=12),
    CameraModel(model_id=7, model_name="FOV", num_params=5),
    CameraModel(model_id=8, model_name="SIMPLE_RADIAL_FISHEYE", num_params=4),
    CameraModel(model_id=9, model_name="RADIAL_FISHEYE", num_params=5),
    CameraModel(model_id=10, model_name="THIN_PRISM_FISHEYE", num_params=12),
}
CAMERA_MODEL_NAMES = {m.model_name: m for m in CAMERA_MODELS}


def write_next_bytes(fid, data, format_char_sequence, endian_character="<"):
    if isinstance(data, (list, tuple)):
        packed = struct.pack(endian_character + format_char_sequence, *data)
    else:
        packed = struct.pack(endian_character + format_char_sequence, data)
    fid.write(packed)


def write_cameras_binary(cameras, path_to_model_file):
    with open(path_to_model_file, "wb") as fid:
        write_next_bytes(fid, len(cameras), "Q")
        for _, cam in cameras.items():
            model_id = CAMERA_MODEL_NAMES[cam.model].model_id
            write_next_bytes(fid, [cam.id, model_id, cam.width, cam.height], "iiQQ")
            for p in cam.params:
                write_next_bytes(fid, float(p), "d")


def write_images_binary(images, path_to_model_file):
    with open(path_to_model_file, "wb") as fid:
        write_next_bytes(fid, len(images), "Q")
        for _, img in images.items():
            write_next_bytes(fid, img.id, "i")
            write_next_bytes(fid, img.qvec.tolist(), "dddd")
            write_next_bytes(fid, img.tvec.tolist(), "ddd")
            write_next_bytes(fid, img.camera_id, "i")
            for char in img.name:
                write_next_bytes(fid, char.encode("utf-8"), "c")
            write_next_bytes(fid, b"\x00", "c")
            write_next_bytes(fid, len(img.point3D_ids), "Q")
            for xy, p3d_id in zip(img.xys, img.point3D_ids):
                write_next_bytes(fid, [*xy, p3d_id], "ddq")


def write_points3D_binary(points3D, path_to_model_file):
    with open(path_to_model_file, "wb") as fid:
        write_next_bytes(fid, len(points3D), "Q")
        for _, pt in points3D.items():
            write_next_bytes(fid, pt.id, "Q")
            write_next_bytes(fid, pt.xyz.tolist(), "ddd")
            write_next_bytes(fid, pt.rgb.tolist(), "BBB")
            write_next_bytes(fid, pt.error, "d")
            write_next_bytes(fid, pt.image_ids.shape[0], "Q")
            for image_id, point2D_id in zip(pt.image_ids, pt.point2D_idxs):
                write_next_bytes(fid, [image_id, point2D_id], "ii")


def write_cameras_text(cameras, path_to_model_file):
    with open(path_to_model_file, "w") as fid:
        for _, cam in cameras.items():
            params = " ".join(str(float(p)) for p in cam.params)
            fid.write(f"{cam.id} {cam.model} {cam.width} {cam.height} {params}\n")


def write_images_text(images, path_to_model_file):
    with open(path_to_model_file, "w") as fid:
        for _, img in images.items():
            q = img.qvec.tolist()
            t = img.tvec.tolist()
            fid.write(
                f"{img.id} {q[0]} {q[1]} {q[2]} {q[3]} "
                f"{t[0]} {t[1]} {t[2]} {img.camera_id} {img.name}\n"
            )
            obs_tokens = []
            for (x, y), p3d_id in zip(img.xys, img.point3D_ids):
                obs_tokens.extend([str(float(x)), str(float(y)), str(int(p3d_id))])
            fid.write(" ".join(obs_tokens) + "\n")


def write_points3D_text(points3D, path_to_model_file):
    with open(path_to_model_file, "w") as fid:
        for _, pt in points3D.items():
            base = [
                str(int(pt.id)),
                str(float(pt.xyz[0])),
                str(float(pt.xyz[1])),
                str(float(pt.xyz[2])),
                str(int(pt.rgb[0])),
                str(int(pt.rgb[1])),
                str(int(pt.rgb[2])),
                str(float(pt.error)),
                str(int(pt.image_ids.shape[0])),
            ]
            track = []
            for image_id, point2D_id in zip(pt.image_ids, pt.point2D_idxs):
                track.extend([str(int(image_id)), str(int(point2D_id))])
            fid.write(" ".join(base + track) + "\n")


def write_model(cameras, images, points3D, sparse_dir: Path) -> None:
    """Write a complete COLMAP model in both binary and text form."""
    sparse_dir.mkdir(parents=True, exist_ok=True)
    write_cameras_binary(cameras, sparse_dir / "cameras.bin")
    write_images_binary(images, sparse_dir / "images.bin")
    write_points3D_binary(points3D, sparse_dir / "points3D.bin")
    write_cameras_text(cameras, sparse_dir / "cameras.txt")
    write_images_text(images, sparse_dir / "images.txt")
    write_points3D_text(points3D, sparse_dir / "points3D.txt")


def empty_observations() -> tuple[np.ndarray, np.ndarray]:
    """Placeholder 2D observations for an image with no triangulated points."""
    return np.empty((0, 2), dtype=np.float64), np.empty(0, dtype=np.int64)
