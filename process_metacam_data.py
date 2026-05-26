#!/usr/bin/env python3

import os
import sys
import json
import argparse
import struct
import collections
import zipfile
import shutil
from pathlib import Path
from typing import Dict, List
from datetime import datetime

import numpy as np
import cv2
from scipy.spatial.transform import Rotation as SciRot
from tqdm import tqdm
import subprocess
from huggingface_hub import HfApi, snapshot_download, upload_file, upload_folder

# Constants
# TEMP_DIR = Path("/local_data/jz4725/metacam/data_v3")
TEMP_DIR = Path("/local_data/jz4725/metacam/rebuttal")
ARCHIVE_DIR = Path("/local_data/jz4725/Urbansim_data_archive")
RAW_REPO = "ai4ce/UrbanSim_raw"
PROCESSED_REPO = "ai4ce/UrbanSim"
CHECKPOINT_FILE = ARCHIVE_DIR / "processing_status.json"

# COLMAP data structures
CameraModel = collections.namedtuple(
    "CameraModel", ["model_id", "model_name", "num_params"]
)
Camera = collections.namedtuple(
    "Camera", ["id", "model", "width", "height", "params"]
)
BaseImage = collections.namedtuple(
    "Image", ["id", "qvec", "tvec", "camera_id", "name", "xys", "point3D_ids"]
)
Point3D = collections.namedtuple(
    "Point3D", ["id", "xyz", "rgb", "error", "image_ids", "point2D_idxs"]
)

class Image(BaseImage):
    def qvec2rotmat(self):
        return qvec2rotmat(self.qvec)

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
CAMERA_MODEL_NAMES = dict(
    [(camera_model.model_name, camera_model) for camera_model in CAMERA_MODELS]
)

# Coordinate system transformation matrices
GLOBAL_ROT = np.array([
    [1.0, 0.0, 0.0],
    [0.0, -1.0, 0.0],
    [0.0, 0.0, -1.0]
])

GLOBAL_TRANS = np.array([
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0]
])


def write_next_bytes(fid, data, format_char_sequence, endian_character="<"):
    if isinstance(data, (list, tuple)):
        bytes = struct.pack(endian_character + format_char_sequence, *data)
    else:
        bytes = struct.pack(endian_character + format_char_sequence, data)
    fid.write(bytes)


def write_cameras_binary(cameras, path_to_model_file):
    with open(path_to_model_file, "wb") as fid:
        write_next_bytes(fid, len(cameras), "Q")
        for _, cam in cameras.items():
            model_id = CAMERA_MODEL_NAMES[cam.model].model_id
            camera_properties = [cam.id, model_id, cam.width, cam.height]
            write_next_bytes(fid, camera_properties, "iiQQ")
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
            track_length = pt.image_ids.shape[0]
            write_next_bytes(fid, track_length, "Q")
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
                f"{img.id} {q[0]} {q[1]} {q[2]} {q[3]} {t[0]} {t[1]} {t[2]} {img.camera_id} {img.name}\n"
            )
            obs_tokens = []
            for (x, y), p3d_id in zip(img.xys, img.point3D_ids):
                obs_tokens.extend([str(float(x)), str(float(y)), str(int(p3d_id))])
            fid.write(" ".join(obs_tokens) + "\n")


def write_points3D_text(points3D, path_to_model_file):
    with open(path_to_model_file, "w") as fid:
        for _, pt in points3D.items():
            track_length = int(pt.image_ids.shape[0])
            base = [
                str(int(pt.id)),
                str(float(pt.xyz[0])),
                str(float(pt.xyz[1])),
                str(float(pt.xyz[2])),
                str(int(pt.rgb[0])),
                str(int(pt.rgb[1])),
                str(int(pt.rgb[2])),
                str(float(pt.error)),
                str(track_length),
            ]
            track = []
            for image_id, point2D_id in zip(pt.image_ids, pt.point2D_idxs):
                track.extend([str(int(image_id)), str(int(point2D_id))])
            fid.write(" ".join(base + track) + "\n")


def qvec2rotmat(qvec):
    return np.array([
        [
            1 - 2 * qvec[2] ** 2 - 2 * qvec[3] ** 2,
            2 * qvec[1] * qvec[2] - 2 * qvec[0] * qvec[3],
            2 * qvec[3] * qvec[1] + 2 * qvec[0] * qvec[2],
        ],
        [
            2 * qvec[1] * qvec[2] + 2 * qvec[0] * qvec[3],
            1 - 2 * qvec[1] ** 2 - 2 * qvec[3] ** 2,
            2 * qvec[2] * qvec[3] - 2 * qvec[0] * qvec[1],
        ],
        [
            2 * qvec[3] * qvec[1] - 2 * qvec[0] * qvec[2],
            2 * qvec[2] * qvec[3] + 2 * qvec[0] * qvec[1],
            1 - 2 * qvec[1] ** 2 - 2 * qvec[2] ** 2,
        ],
    ])


def apply_coordinate_corrections(transform_matrix: np.ndarray) -> np.ndarray:
    corrected = transform_matrix.copy()
    corrected[:3, :3] = corrected[:3, :3] @ GLOBAL_ROT
    corrected = GLOBAL_TRANS @ corrected

    y_rot_180 = np.array([
        [1.0, 0.0, 0.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0]
    ])
    return y_rot_180 @ corrected


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_checkpoint(checkpoint):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(checkpoint, f, indent=2)


def update_checkpoint(checkpoint, scene_name, stage):
    if scene_name not in checkpoint:
        checkpoint[scene_name] = {"stages": {}}
    checkpoint[scene_name]["stages"][stage] = True
    checkpoint[scene_name]["last_updated"] = datetime.now().isoformat()
    save_checkpoint(checkpoint)


def list_scenes_from_hf(repo_id):
    api = HfApi()
    files = api.list_repo_files(repo_id, repo_type="dataset")
    scenes = []
    for file in files:
        if file.startswith("data/") and file.endswith(".zip"):
            scene_name = Path(file).stem
            scenes.append(scene_name)
    return scenes


def download_scene(scene_name):
    print(f"\n=== Downloading {scene_name} ===")
    api = HfApi()

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Download the zip file - it will be saved to local_dir/data/scene_name.zip
    downloaded_path = api.hf_hub_download(
        repo_id=RAW_REPO,
        repo_type="dataset",
        filename=f"data/{scene_name}.zip",
        local_dir=TEMP_DIR,
    )

    # Extract to temp location first
    temp_extract = TEMP_DIR / f"{scene_name}_temp"
    temp_extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(downloaded_path, 'r') as zip_ref:
        zip_ref.extractall(temp_extract)

    # Check if extracted content is in a subdirectory
    extracted_items = list(temp_extract.iterdir())
    final_path = TEMP_DIR / scene_name

    # Remove existing destination if it exists
    if final_path.exists():
        shutil.rmtree(final_path)

    if len(extracted_items) == 1 and extracted_items[0].is_dir():
        # Single directory inside zip, move its contents up
        shutil.move(str(extracted_items[0]), str(final_path))
        temp_extract.rmdir()
    else:
        # Multiple items or files, rename temp to final
        shutil.move(str(temp_extract), str(final_path))

    print(f"Extracted to {final_path}")


def convert_jpg_to_png(scene_path):
    """Convert all .jpg files in fisheye folder to .png"""
    print(f"\n=== Converting JPG to PNG for {scene_path.name} ===")

    fisheye_dir = scene_path / "fisheye"
    if not fisheye_dir.exists():
        print(f"Warning: fisheye directory not found at {fisheye_dir}")
        return

    jpg_files = list(fisheye_dir.glob("*.jpg"))
    for jpg_path in tqdm(jpg_files, desc="Converting JPG to PNG"):
        png_path = jpg_path.with_suffix('.png')

        # Read and save as PNG
        img = cv2.imread(str(jpg_path))
        if img is not None:
            cv2.imwrite(str(png_path), img)
            # Remove the original JPG file
            jpg_path.unlink()

    print(f"Converted {len(jpg_files)} JPG files to PNG")


def undistort_images_and_masks(scene_path):
    print(f"\n=== Undistorting images for {scene_path.name} ===")

    transforms_path = scene_path / "transforms.json"
    with open(transforms_path, 'r') as f:
        data = json.load(f)
    frames = data.get('frames', [])

    fisheye_dir = scene_path / "fisheye"
    fisheye_mask_dir = scene_path / "fisheye_mask"
    undistorted_dir = scene_path / "images"
    undistorted_mask_dir = scene_path / "images_mask"

    undistorted_dir.mkdir(parents=True, exist_ok=True)
    undistorted_mask_dir.mkdir(parents=True, exist_ok=True)

    # Find first image that actually exists in fisheye folder
    actual_image_path = None
    actual_frame = None

    # First, try to find any existing image file in fisheye folder
    if fisheye_dir.exists():
        # Get list of actual fisheye images
        fisheye_files = list(fisheye_dir.glob("*.jpg")) + list(fisheye_dir.glob("*.png"))
        if fisheye_files:
            # Use the first available image
            actual_image_path = fisheye_files[0]
            # Try to find corresponding frame in json
            for frame in frames:
                file_path = frame.get('file_path', '').replace('\\', '/')
                parts = file_path.split('/')
                if len(parts) == 2:
                    camera_side, timestamp_with_ext = parts
                    timestamp = Path(timestamp_with_ext).stem
                    expected_name = f"{camera_side}_{timestamp}.jpg"
                    if actual_image_path.name == expected_name or actual_image_path.stem == f"{camera_side}_{timestamp}":
                        actual_frame = frame
                        break

    # If we couldn't find a matching frame, just use first frame for intrinsics
    if actual_frame is None:
        actual_frame = frames[0]

    # Get intrinsics and reference resolution from the frame
    intrinsics = {
        'w': int(actual_frame.get('w')),
        'h': int(actual_frame.get('h')),
        'fx': float(actual_frame.get('fl_x')),
        'fy': float(actual_frame.get('fl_y')),
        'cx': float(actual_frame.get('cx')),
        'cy': float(actual_frame.get('cy')),
        'k1': float(actual_frame.get('k1', 0.0)),
        'k2': float(actual_frame.get('k2', 0.0)),
        'k3': float(actual_frame.get('k3', 0.0)),
        'k4': float(actual_frame.get('k4', 0.0))
    }

    # Get reference resolution from transforms.json (usually 3040×4032 but may vary)
    reference_w = intrinsics['w']
    reference_h = intrinsics['h']

    # Detect actual image resolution from an existing image
    if actual_image_path and actual_image_path.exists():
        test_img = cv2.imread(str(actual_image_path))
        if test_img is not None:
            actual_h, actual_w = test_img.shape[:2]
        else:
            # Should not happen, but fallback to reference
            actual_w, actual_h = reference_w, reference_h
    else:
        raise ValueError(f"Could not find actual image path at {actual_image_path}")

    # Setup undistortion parameters
    scale_x = actual_w / reference_w
    scale_y = actual_h / reference_h

    K_fish = np.array([[intrinsics['fx'] * scale_x, 0.0, intrinsics['cx'] * scale_x],
                      [0.0, intrinsics['fy'] * scale_y, intrinsics['cy'] * scale_y],
                      [0.0, 0.0, 1.0]], dtype=np.float64)
    D = np.array([intrinsics['k1'], intrinsics['k2'],
                 intrinsics['k3'], intrinsics['k4']], dtype=np.float64)

    # Target: 800x800 image with 90 deg FOV (fx=fy=cx=cy=400)
    target_K = np.array([[400.0, 0.0, 400.0],
                        [0.0, 400.0, 400.0],
                        [0.0, 0.0, 1.0]], dtype=np.float64)
    out_size = (800, 800)

    # Undistort all images
    for frame in tqdm(frames, desc="Undistorting images"):
        file_path = frame.get('file_path', '').replace('\\', '/')
        # Parse path like "left/timestamp.png" -> read from "left_timestamp.jpg", output to "left_timestamp.png"
        parts = file_path.split('/')
        if len(parts) == 2:
            camera_side, timestamp_with_ext = parts
            timestamp = Path(timestamp_with_ext).stem  # Remove extension
            source_image_name = f"{camera_side}_{timestamp}.jpg"  # Source fisheye images are JPG
            output_image_name = f"{camera_side}_{timestamp}.png"  # Output undistorted images are PNG
        else:
            # Fallback to original logic if format is different
            source_image_name = Path(file_path).name
            output_image_name = Path(file_path).name

        src_path = fisheye_dir / source_image_name
        dst_path = undistorted_dir / output_image_name

        if dst_path.exists():
            continue

        if not src_path.exists():
            continue

        img = cv2.imread(str(src_path))
        if img is None:
            continue

        map1, map2 = cv2.fisheye.initUndistortRectifyMap(
            K_fish, D, np.eye(3), target_K, out_size, cv2.CV_16SC2)
        undistorted = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
        cv2.imwrite(str(dst_path), undistorted)

        # Also undistort the corresponding mask if it exists
        # Masks use .png extension for both source and output
        mask_filename = f"{camera_side}_{timestamp}.png"
        mask_src_path = fisheye_mask_dir / mask_filename
        mask_dst_path = undistorted_mask_dir / mask_filename

        if mask_src_path.exists():
            mask = cv2.imread(str(mask_src_path), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                undistorted_mask = cv2.remap(mask, map1, map2, cv2.INTER_NEAREST)
                cv2.imwrite(str(mask_dst_path), undistorted_mask)


def undistort_images(scene_path):
    # check if images folder exists
    if (scene_path / "images").exists():
        print(f"Images folder already exists for {scene_path.name}, skipping undistortion.")
        return
    print(f"\n=== Undistorting images (no masks) for {scene_path.name} ===")

    transforms_path = scene_path / "transforms.json"
    with open(transforms_path, 'r') as f:
        data = json.load(f)
    frames = data.get('frames', [])

    fisheye_dir = scene_path / "fisheye"
    undistorted_dir = scene_path / "images"

    undistorted_dir.mkdir(parents=True, exist_ok=True)

    actual_image_path = None
    actual_frame = None

    if fisheye_dir.exists():
        fisheye_files = list(fisheye_dir.glob("*.jpg")) + list(fisheye_dir.glob("*.png"))
        if fisheye_files:
            actual_image_path = fisheye_files[0]
            for frame in frames:
                file_path = frame.get('file_path', '').replace('\\', '/')
                parts = file_path.split('/')
                if len(parts) == 2:
                    camera_side, timestamp_with_ext = parts
                    timestamp = Path(timestamp_with_ext).stem
                    expected_name = f"{camera_side}_{timestamp}.jpg"
                    if actual_image_path.name == expected_name or actual_image_path.stem == f"{camera_side}_{timestamp}":
                        actual_frame = frame
                        break

    if actual_frame is None:
        actual_frame = frames[0]

    intrinsics = {
        'w': int(actual_frame.get('w')),
        'h': int(actual_frame.get('h')),
        'fx': float(actual_frame.get('fl_x')),
        'fy': float(actual_frame.get('fl_y')),
        'cx': float(actual_frame.get('cx')),
        'cy': float(actual_frame.get('cy')),
        'k1': float(actual_frame.get('k1', 0.0)),
        'k2': float(actual_frame.get('k2', 0.0)),
        'k3': float(actual_frame.get('k3', 0.0)),
        'k4': float(actual_frame.get('k4', 0.0))
    }

    reference_w = intrinsics['w']
    reference_h = intrinsics['h']

    if actual_image_path and actual_image_path.exists():
        test_img = cv2.imread(str(actual_image_path))
        if test_img is not None:
            actual_h, actual_w = test_img.shape[:2]
        else:
            actual_w, actual_h = reference_w, reference_h
    else:
        raise ValueError(f"Could not find actual image path at {actual_image_path}")

    scale_x = actual_w / reference_w
    scale_y = actual_h / reference_h

    K_fish = np.array([[intrinsics['fx'] * scale_x, 0.0, intrinsics['cx'] * scale_x],
                      [0.0, intrinsics['fy'] * scale_y, intrinsics['cy'] * scale_y],
                      [0.0, 0.0, 1.0]], dtype=np.float64)
    D = np.array([intrinsics['k1'], intrinsics['k2'],
                 intrinsics['k3'], intrinsics['k4']], dtype=np.float64)

    target_K = np.array([[400.0, 0.0, 400.0],
                        [0.0, 400.0, 400.0],
                        [0.0, 0.0, 1.0]], dtype=np.float64)
    out_size = (800, 800)

    for frame in tqdm(frames, desc="Undistorting images (no masks)"):
        file_path = frame.get('file_path', '').replace('\\', '/')
        parts = file_path.split('/')
        if len(parts) == 2:
            camera_side, timestamp_with_ext = parts
            timestamp = Path(timestamp_with_ext).stem
            source_image_name = f"{camera_side}_{timestamp}.jpg"
            output_image_name = f"{camera_side}_{timestamp}.png"
        else:
            source_image_name = Path(file_path).name
            output_image_name = Path(file_path).name

        src_path = fisheye_dir / source_image_name
        dst_path = undistorted_dir / output_image_name

        if dst_path.exists():
            continue
        if not src_path.exists():
            continue

        img = cv2.imread(str(src_path))
        if img is None:
            continue

        map1, map2 = cv2.fisheye.initUndistortRectifyMap(
            K_fish, D, np.eye(3), target_K, out_size, cv2.CV_16SC2)
        undistorted = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
        cv2.imwrite(str(dst_path), undistorted)

def copy_unditorted_images(scene_path):
    # from scene_path / camera / left or right / {image_id}.jpg
    # to scene_path / fisheye / left_{image_id}.jpg or right_{image_id}.jpg
    if (scene_path / "fisheye").exists():
        print(f"Fishey folder already exists for {scene_path.name}, skipping copy.")
        return
    original_dir = scene_path / "camera"
    fisheye_dir = scene_path / "fisheye"
    fisheye_dir.mkdir(parents=True, exist_ok=True)
    for side in ["left", "right"]:
        side_dir = original_dir / side
        if not side_dir.exists():
            continue
        for img_path in side_dir.glob("*.jpg"):
            timestamp = img_path.stem
            new_name = f"{side}_{timestamp}.jpg"
            new_path = fisheye_dir / new_name
            shutil.copy(img_path, new_path)



def create_sparse_model(scene_path):
    if (scene_path / "sparse").exists():
        print(f"Sparse folder already exists for {scene_path.name}, skipping copy.")
        return
    print(f"\n=== Creating COLMAP sparse model for {scene_path.name} ===")

    transforms_path = scene_path / "transforms.json"
    with open(transforms_path, 'r') as f:
        data = json.load(f)
    frames = data.get('frames', [])

    sparse_dir = scene_path / "sparse" / "0"
    sparse_dir.mkdir(parents=True, exist_ok=True)
    undistorted_dir = scene_path / "images"

    actual_w, actual_h = 800, 800

    # Single camera model for all images (both left and right)
    cameras = {
        1: Camera(id=1, model="PINHOLE", width=actual_w, height=actual_h,
                 params=np.array([400.0, 400.0, 400.0, 400.0]))
    }

    images = {}
    image_id = 1

    for frame in frames:
        transform_matrix = np.array(frame['transform_matrix'])
        corrected_transform = apply_coordinate_corrections(transform_matrix)
        camera_pose = np.linalg.inv(corrected_transform)

        rotation_matrix = camera_pose[:3, :3]
        translation = camera_pose[:3, 3]

        rot = SciRot.from_matrix(rotation_matrix)
        quat_xyzw = rot.as_quat()
        quat_wxyz = np.array([quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]])

        file_path = frame.get('file_path', '').replace('\\', '/')
        # Parse path like "left/timestamp.jpg" -> "left_timestamp.jpg" (matches undistorted output)
        parts = file_path.split('/')
        if len(parts) == 2:
            camera_side, timestamp_with_ext = parts
            timestamp = Path(timestamp_with_ext).stem
            image_name = f"{camera_side}_{timestamp}.png"  # Undistorted images are .png
        else:
            # Fallback to original logic
            image_name = Path(file_path).name

        # Use single camera model for all images
        cam_id = 1

        undistorted_image_path = undistorted_dir / image_name
        if not undistorted_image_path.exists():
            continue

        xys = np.empty((0, 2), dtype=np.float64)
        point3D_ids = np.empty(0, dtype=np.int64)

        images[image_id] = Image(
            id=image_id,
            qvec=quat_wxyz,
            tvec=translation,
            camera_id=cam_id,
            name=image_name,
            xys=xys,
            point3D_ids=point3D_ids
        )
        image_id += 1

    points3D = {}

    write_cameras_binary(cameras, sparse_dir / "cameras.bin")
    write_images_binary(images, sparse_dir / "images.bin")
    write_points3D_binary(points3D, sparse_dir / "points3D.bin")

    write_cameras_text(cameras, sparse_dir / "cameras.txt")
    write_images_text(images, sparse_dir / "images.txt")
    write_points3D_text(points3D, sparse_dir / "points3D.txt")

    print(f"Created sparse model with {len(images)} images")


def convert_las_to_ply(scene_path):
    # Lazy import: laspy is only required by this (currently inactive) stage.
    import laspy
    print(f"\n=== Converting LAS to PLY for {scene_path.name} ===")

    las_path = scene_path / "colorized.las"

    if not las_path.exists():
        print(f"Warning: LAS file not found at {las_path}")
        return

    with laspy.open(str(las_path)) as las_reader:
        las = las_reader.read()

    has_color = all(hasattr(las, attr) for attr in ["red", "green", "blue"])

    x = las.x
    y = las.y
    z = las.z

    points_homogeneous = np.column_stack([x, y, z, np.ones(len(x))])

    corrected_points = points_homogeneous.copy()
    corrected_points[:, :3] = corrected_points[:, :3] @ GLOBAL_ROT

    corrected_points = (GLOBAL_TRANS @ corrected_points.T).T

    y_rot_180 = np.array([
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0]
    ])
    corrected_points = (y_rot_180 @ corrected_points.T).T

    x, y, z = corrected_points[:, 0], corrected_points[:, 1], corrected_points[:, 2]

    if has_color:
        r_raw = getattr(las, "red")
        g_raw = getattr(las, "green")
        b_raw = getattr(las, "blue")

        max_val = float(max(r_raw.max(initial=0), g_raw.max(initial=0), b_raw.max(initial=0)))
        scale = 255.0 / max_val if max_val > 255.0 and max_val > 0 else 1.0
        r = np.clip((r_raw * scale).astype(np.uint8), 0, 255)
        g = np.clip((g_raw * scale).astype(np.uint8), 0, 255)
        b = np.clip((b_raw * scale).astype(np.uint8), 0, 255)
    else:
        r = g = b = None

    ply_path = scene_path / "raw_pcd.ply"
    write_ply_file(ply_path, corrected_points[:, :3], r, g, b)
    print(f"Created PLY file: {ply_path}")


def write_ply_file(ply_path, points, r=None, g=None, b=None):
    # Lazy import: open3d is only required by this (currently inactive) stage.
    import open3d as o3d
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points)

    if r is not None and g is not None and b is not None:
        colors = np.column_stack([r, g, b]) / 255.0
        pcd.colors = o3d.utility.Vector3dVector(colors)
    else:
        num_points = len(points)
        white_colors = np.ones((num_points, 3))
        pcd.colors = o3d.utility.Vector3dVector(white_colors)

    o3d.io.write_point_cloud(str(ply_path), pcd)


def clean_mismatches(scene_path):
    print(f"\n=== Cleaning mismatches for {scene_path.name} ===")

    # Scan actual files
    fisheye_dir = scene_path / "fisheye"
    fisheye_mask_dir = scene_path / "fisheye_mask"
    images_dir = scene_path / "images"
    images_mask_dir = scene_path / "images_mask"

    # Get file stems (without extension) to handle JPG vs PNG
    fisheye_stems = set([f.stem for f in fisheye_dir.glob("*") if f.is_file()]) if fisheye_dir.exists() else set()
    fisheye_mask_stems = set([f.stem for f in fisheye_mask_dir.glob("*") if f.is_file()]) if fisheye_mask_dir.exists() else set()
    images_stems = set([f.stem for f in images_dir.glob("*") if f.is_file()]) if images_dir.exists() else set()
    images_mask_stems = set([f.stem for f in images_mask_dir.glob("*") if f.is_file()]) if images_mask_dir.exists() else set()

    # Load transforms.json
    transforms_path = scene_path / "transforms.json"
    with open(transforms_path, 'r') as f:
        transforms_data = json.load(f)
    frames = transforms_data.get('frames', [])

    # Extract image stems from transforms.json (without extension)
    transform_stems = set()
    for frame in frames:
        file_path = frame.get('file_path', '').replace('\\', '/')
        # Parse path like "left/timestamp.png" -> "left_timestamp"
        parts = file_path.split('/')
        if len(parts) == 2:
            camera_side, timestamp_with_ext = parts
            timestamp = Path(timestamp_with_ext).stem
            image_stem = f"{camera_side}_{timestamp}"  # No extension
        else:
            image_stem = Path(file_path).stem
        transform_stems.add(image_stem)

    # Load splits
    train_path = scene_path / "nvs_split" / "train.txt"
    val_path = scene_path / "nvs_split" / "val.txt"

    train_stems = set()
    val_stems = set()

    if train_path.exists():
        with open(train_path, 'r') as f:
            # Extract stems without extension
            train_stems = set([Path(line.strip()).stem for line in f if line.strip()])

    if val_path.exists():
        with open(val_path, 'r') as f:
            # Extract stems without extension
            val_stems = set([Path(line.strip()).stem for line in f if line.strip()])

    split_stems = train_stems | val_stems

    # Compute intersection: must exist in filesystem AND (transforms.json OR splits)
    all_filesystem_stems = fisheye_stems | fisheye_mask_stems | images_stems | images_mask_stems
    referenced_stems = transform_stems | split_stems
    valid_stems = all_filesystem_stems & referenced_stems

    # Delete unreferenced images from disk (compare by stem)
    for dir_path in [fisheye_dir, fisheye_mask_dir, images_dir, images_mask_dir]:
        if not dir_path.exists():
            continue
        for file_path in dir_path.glob("*"):
            if file_path.is_file() and file_path.stem not in valid_stems:
                file_path.unlink()
                print(f"Deleted unreferenced: {file_path}")

    # Remove missing images from transforms.json
    valid_frames = []
    for frame in frames:
        file_path = frame.get('file_path', '').replace('\\', '/')
        # Parse path like "left/timestamp.png" -> "left_timestamp"
        parts = file_path.split('/')
        if len(parts) == 2:
            camera_side, timestamp_with_ext = parts
            timestamp = Path(timestamp_with_ext).stem
            image_stem = f"{camera_side}_{timestamp}"
        else:
            image_stem = Path(file_path).stem

        if image_stem in valid_stems:
            valid_frames.append(frame)

    transforms_data['frames'] = valid_frames
    with open(transforms_path, 'w') as f:
        json.dump(transforms_data, f, indent=2)

    # Update split files - write with .png extension
    removed_train = 0
    removed_val = 0

    if train_path.exists():
        valid_train = [f"{stem}.png" for stem in train_stems if stem in valid_stems]
        removed_train = len(train_stems) - len(valid_train)
        with open(train_path, 'w') as f:
            f.write('\n'.join(sorted(valid_train)) + '\n')
        print(f"Updated train.txt: {len(valid_train)} valid, {removed_train} removed")

    if val_path.exists():
        valid_val = [f"{stem}.png" for stem in val_stems if stem in valid_stems]
        removed_val = len(val_stems) - len(valid_val)
        with open(val_path, 'w') as f:
            f.write('\n'.join(sorted(valid_val)) + '\n')
        print(f"Updated val.txt: {len(valid_val)} valid, {removed_val} removed")

    print(f"Kept {len(valid_stems)} valid images total")


def zip_folders(scene_path):
    print(f"\n=== Compressing folders with pigz for {scene_path.name} ===")

    folders_to_compress = ['images', 'images_mask', 'fisheye', 'fisheye_mask']

    for folder_name in folders_to_compress:
        folder_path = scene_path / folder_name
        if not folder_path.exists():
            continue

        tar_gz_path = scene_path / f"{folder_name}.tar.gz"

        # Use tar with pigz for parallel compression
        # -c: create archive, -f: output file, --use-compress-program: use pigz instead of gzip
        # -C: change to directory before adding files
        try:
            subprocess.run(
                ['tar', '-cf', str(tar_gz_path), '--use-compress-program=pigz',
                 '-C', str(scene_path), folder_name],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"Created {tar_gz_path}")
        except subprocess.CalledProcessError as e:
            print(f"Error compressing {folder_name}: {e.stderr}")
            raise


def cleanup_before_upload(scene_path):
    """Delete everything except the files/folders to upload"""
    print(f"\n=== Cleaning up before upload for {scene_path.name} ===")

    # Define what we want to KEEP for upload
    files_to_keep = {
        'images.tar.gz',
        'images_mask.tar.gz',
        'fisheye.tar.gz',
        'fisheye_mask.tar.gz',
        'raw_pcd.ply',
        'transforms.json'
    }

    folders_to_keep = {
        'sparse',
        'nvs_split'
    }

    # Get all items in the scene directory
    all_items = list(scene_path.iterdir())

    for item in all_items:
        item_name = item.name

        # Keep files that are in our keep list
        if item.is_file() and item_name in files_to_keep:
            continue

        # Keep folders that are in our keep list
        if item.is_dir() and item_name in folders_to_keep:
            continue

        # Delete everything else
        if item.is_file():
            item.unlink()
            print(f"Deleted file: {item_name}")
        elif item.is_dir():
            shutil.rmtree(item)
            print(f"Deleted folder: {item_name}/")

    print(f"Cleanup complete - kept only files/folders for upload")


def upload_to_hf(scene_path, scene_name):
    print(f"\n=== Uploading {scene_name} to HuggingFace ===")

    api = HfApi()

    # Upload the entire scene folder as a single commit
    # This reduces the number of commits from ~7-8 per scene to just 1
    api.upload_folder(
        folder_path=str(scene_path),
        path_in_repo=f"data/{scene_name}",
        repo_id=PROCESSED_REPO,
        repo_type="dataset",
        commit_message=f"Add processed scene: {scene_name}"
    )

    print(f"Upload complete for {scene_name} (single commit)")


def cleanup_temp(scene_name):
    print(f"\n=== Cleaning up temp files for {scene_name} ===")

    scene_path = TEMP_DIR / scene_name
    temp_extract_path = TEMP_DIR / f"{scene_name}_temp"
    zip_path = TEMP_DIR / "data" / f"{scene_name}.zip"

    if scene_path.exists():
        shutil.rmtree(scene_path)
    if temp_extract_path.exists():
        shutil.rmtree(temp_extract_path)
    if zip_path.exists():
        zip_path.unlink()

    print(f"Cleaned up temp directory")


def copy_to_archive(scene_name):
    print(f"\n=== Copying {scene_name} to archive ===")

    src_path = TEMP_DIR / scene_name
    dst_path = ARCHIVE_DIR / scene_name

    if src_path.exists():
        if dst_path.exists():
            shutil.rmtree(dst_path)
        shutil.copytree(src_path, dst_path)
        print(f"Copied to {dst_path}")


def process_scene(scene_name, checkpoint, test_mode, rerun_mode=False):
    print(f"\n{'='*60}")
    print(f"Processing scene: {scene_name}")
    print(f"{'='*60}")

    if not test_mode and not rerun_mode:
        status = checkpoint.get(scene_name, {}).get("stages", {})
    else:
        status = {}

    scene_path = TEMP_DIR / scene_name

    # # Stage 1: Download
    # if not status.get("downloaded"):
    #     download_scene(scene_name)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "downloaded")
    # else:
    #     print(f"\n=== Skipping download (already completed) ===")

    # # Stage 1.5: Convert JPG to PNG - SKIPPED (keeping fisheye as JPG to save storage)
    # # The undistort step will read JPG from fisheye and output PNG to images
    # print(f"\n=== Skipping JPG conversion (fisheye kept as JPG) ===")

    # Stage 2: Undistort
    print("processing scene path:", scene_path)
    if not status.get("undistorted"):
        print("copy raw images to fisheye folder")
        copy_unditorted_images(scene_path)
        print("undistorting images from fisheye folder to images folder")
        undistort_images(scene_path)
        print("creating colmap")
        create_sparse_model(scene_path)
        if not test_mode:
            update_checkpoint(checkpoint, scene_name, "undistorted")
    else:
        print(f"\n=== Skipping undistortion (already completed) ===")

    # # Stage 3: LAS conversion
    # if not status.get("las_converted"):
    #     convert_las_to_ply(scene_path)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "las_converted")
    # else:
    #     print(f"\n=== Skipping LAS conversion (already completed) ===")

    # # Stage 4: Clean mismatches
    # if not status.get("cleaned"):
    #     clean_mismatches(scene_path)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "cleaned")
    # else:
    #     print(f"\n=== Skipping cleaning (already completed) ===")

    # # Stage 5: Zip
    # if not status.get("zipped"):
    #     zip_folders(scene_path)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "zipped")
    # else:
    #     print(f"\n=== Skipping zipping (already completed) ===")

    # # Stage 5.5: Cleanup before upload
    # if not status.get("cleaned_for_upload"):
    #     cleanup_before_upload(scene_path)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "cleaned_for_upload")
    # else:
    #     print(f"\n=== Skipping cleanup before upload (already completed) ===")

    # # Stage 6: Upload
    # if not status.get("uploaded"):
    #     copy_to_archive(scene_name)
    #     upload_to_hf(scene_path, scene_name)
    #     if not test_mode:
    #         update_checkpoint(checkpoint, scene_name, "uploaded")
    # else:
    #     print(f"\n=== Skipping upload (already completed) ===")

    # # Cleanup temp
    # cleanup_temp(scene_name)

    print(f"\n{'='*60}")
    print(f"Completed processing: {scene_name}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Automate UrbanSim data processing pipeline")
    parser.add_argument("--test", action="store_true", help="Test mode: process only one scene, skip checkpoints")
    parser.add_argument("--rerun", action="store_true", help="Rerun everything from scratch, deleting existing checkpoint history")
    args = parser.parse_args()

    test_mode = args.test
    rerun_mode = args.rerun

    if test_mode:
        print("Running in TEST MODE - will process only one scene without checkpoints")
        checkpoint = {}
    else:
        if rerun_mode:
            print("="*60)
            print("Running in RERUN MODE - deleting existing checkpoint history")
            print("All scenes will be reprocessed from scratch!")
            print("="*60)
            if CHECKPOINT_FILE.exists():
                CHECKPOINT_FILE.unlink()
                print(f"Deleted checkpoint file: {CHECKPOINT_FILE}")
            checkpoint = {}
        else:
            print("Running in PRODUCTION MODE - will process all scenes with checkpoints")
            checkpoint = load_checkpoint()

    # # List all scenes from HuggingFace
    # print(f"\nListing scenes from {RAW_REPO}...")
    # scenes = list_scenes_from_hf(RAW_REPO)
    # print(f"Found {len(scenes)} scenes")

    # for quick local demo, read all subfolder names from temp directory
    # filter out __MACOSX folders if any
    scenes = [p.name for p in TEMP_DIR.iterdir() if p.is_dir() and p.name != "__MACOSX"]
    print(f"\nFound {len(scenes)} scenes in temp directory for processing")

    if test_mode:
        # scenes = scenes[:1]
        print(f"Test mode: processing {len(scenes)} scene(s)")

    # Process each scene
    for idx, scene_name in enumerate(scenes, start=1):
        if not test_mode and not rerun_mode:
            status = checkpoint.get(scene_name, {}).get("stages", {})
            if status.get("uploaded"):
                print(f"\nSkipping {scene_name} (already fully processed) [{idx}/{len(scenes)}]")
                continue

        print(f"\n[Scene {idx}/{len(scenes)}]")
        process_scene(scene_name, checkpoint, test_mode, rerun_mode)

    print("\n" + "="*60)
    print("All scenes processed successfully!")
    print("="*60)


if __name__ == "__main__":
    main()
