#!/usr/bin/env python3
"""
Script to generate object masks using SAM3 (Segment Anything Model 3) based on annotation points.

This script reads annotation.json files, uses the point coordinates to generate masks,
and saves them alongside the annotations.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import torch
from PIL import Image

# Set environment variable for MPS fallback if needed
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

########################################### visualization helper #################################################
import matplotlib.pyplot as plt
def show_mask(mask, ax, random_color=False, borders = True):
    if random_color:
        color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
    else:
        color = np.array([30/255, 144/255, 255/255, 0.6])
    h, w = mask.shape[-2:]
    mask = mask.astype(np.uint8)
    mask_image =  mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
    if borders:
        import cv2
        contours, _ = cv2.findContours(mask,cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE) 
        # Try to smooth contours
        contours = [cv2.approxPolyDP(contour, epsilon=0.01, closed=True) for contour in contours]
        mask_image = cv2.drawContours(mask_image, contours, -1, (1, 1, 1, 0.5), thickness=2) 
    ax.imshow(mask_image)

def show_points(coords, labels, ax, marker_size=375):
    pos_points = coords[labels==1]
    neg_points = coords[labels==0]
    ax.scatter(pos_points[:, 0], pos_points[:, 1], color='green', marker='*', s=marker_size, edgecolor='white', linewidth=1.25)
    ax.scatter(neg_points[:, 0], neg_points[:, 1], color='red', marker='*', s=marker_size, edgecolor='white', linewidth=1.25)   

def show_box(box, ax):
    x0, y0 = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    ax.add_patch(plt.Rectangle((x0, y0), w, h, edgecolor='green', facecolor=(0, 0, 0, 0), lw=2))    

def show_masks(image, masks, scores, point_coords=None, box_coords=None, input_labels=None, borders=True):
    for i, (mask, score) in enumerate(zip(masks, scores)):
        plt.figure(figsize=(10, 10))
        plt.imshow(image)
        show_mask(mask, plt.gca(), borders=borders)
        if point_coords is not None:
            assert input_labels is not None
            show_points(point_coords, input_labels, plt.gca())
        if box_coords is not None:
            # boxes
            show_box(box_coords, plt.gca())
        if len(scores) > 1:
            plt.title(f"Mask {i+1}, Score: {score:.3f}", fontsize=18)
        plt.axis('off')
        # plt.show()
        plt.savefig(f"mask_vis_{i+1}.png")
###############################################################################################################


def load_annotation(annotation_path: Path) -> Optional[Dict]:
    """Load annotation from JSON file."""
    if not annotation_path.exists():
        print(f"Annotation file not found: {annotation_path}")
        return None
    
    try:
        with open(annotation_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        annotation = data.get('annotation', {})
        if not annotation:
            print(f"No annotation data found in {annotation_path}")
            return None
        
        point = annotation.get('point', {})
        if 'x' not in point or 'y' not in point:
            print(f"Invalid point data in {annotation_path}")
            return None
        
        return {
            'point': {'x': float(point['x']), 'y': float(point['y'])},
            'label': annotation.get('label', ''),
            'image': annotation.get('image', 'image_b.jpg'),
            'image_size': annotation.get('image_size', {}),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Error reading annotation file {annotation_path}: {e}")
        return None


def load_image(image_path: Path) -> Optional[Image.Image]:
    """Load image as PIL Image."""
    if not image_path.exists():
        print(f"Image file not found: {image_path}")
        return None
    
    try:
        img = Image.open(image_path).convert('RGB')
        return img
    except Exception as e:
        print(f"Error loading image {image_path}: {e}")
        return None


def get_device():
    """Determine the best available device for computation."""
    if torch.cuda.is_available():
        device = torch.device("cuda")
        # Enable tf32 for Ampere GPUs
        if torch.cuda.get_device_properties(0).major >= 8:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        print(
            "\nSupport for MPS devices is preliminary. SAM 3 is trained with CUDA and might "
            "give numerically different outputs and sometimes degraded performance on MPS."
        )
    else:
        device = torch.device("cpu")
    
    return device

def build_model(model_path: Optional[str] = None) -> Tuple[torch.nn.Module, Sam3Processor]:
    """Build and return the SAM3 model and processor."""
    # Get device
    device = get_device()
    print(f"Using device: {device}")
    
    # Build SAM3 model
    if model_path:
        model = build_sam3_image_model(checkpoint_path=model_path, enable_inst_interactivity=True)
    else:
        model = build_sam3_image_model(enable_inst_interactivity=True)
    
    model.eval()
    model.to(device)
    
    # Create processor
    processor = Sam3Processor(model)
    
    return model, processor


def generate_mask_sam3(
    image: Image.Image,
    point: Tuple[float, float],
    model: torch.nn.Module,
    processor: Sam3Processor,
) -> Optional[np.ndarray]:
    """
    Generate mask using SAM3 model.
    
    Args:
        image: Input image as PIL Image
        point: Point coordinates (x, y)
        model: Pre-loaded SAM3 model
        processor: Pre-loaded SAM3 processor
    
    Returns:
        Binary mask as numpy array (H, W) with values 0 or 1
    """
    
    # Set the image (computes image embeddings)
    try:
        inference_state = processor.set_image(image)
    except Exception as e:
        print(f"Error setting image: {e}")
        return None
    
    # Prepare point coordinates
    # SAM3 expects points in format: np.array([[x, y]]) with shape (1, 2) for single point
    point_coords = np.array([[point[0], point[1]]], dtype=np.float32)
    point_labels = np.array([1], dtype=np.int32)  # 1 indicates foreground point
    
    # Generate mask
    try:
        masks, scores, logits = model.predict_inst(
            inference_state,
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=True,
        )
        
        sorted_ind = np.argsort(scores)[::-1]
        masks = masks[sorted_ind]
        scores = scores[sorted_ind]
        logits = logits[sorted_ind]
        
        # show_masks(image, masks, scores, point_coords=point_coords, input_labels=point_labels, borders=True)
        # breakpoint()
        
        # pick top 1 mask
        mask = masks[0]
        
        # Convert to binary (0 or 1)
        mask = (mask > 0.5).astype(np.uint8)
        
        return mask
    except Exception as e:
        print(f"Error generating mask: {e}")
        import traceback
        traceback.print_exc()
        return None


def save_mask(mask: np.ndarray, output_path: Path):
    """Save mask as PNG image."""
    try:
        # Convert binary mask (0/1) to 0-255 range
        mask_image = Image.fromarray((mask * 255).astype(np.uint8), mode='L')
        mask_image.save(output_path)
        print(f"Mask saved to: {output_path}")
    except Exception as e:
        print(f"Error saving mask to {output_path}: {e}")


def update_annotation_with_mask(annotation_path: Path, mask_filename: str):
    """Update annotation.json to include mask filename."""
    try:
        with open(annotation_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'annotation' not in data:
            data['annotation'] = {}
        
        data['annotation']['mask'] = mask_filename
        
        with open(annotation_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        
        print(f"Updated annotation.json with mask reference: {mask_filename}")
    except Exception as e:
        print(f"Error updating annotation file: {e}")


def process_scene(scene_dir, model, processor) -> bool:
    """Process a single scene directory."""
    print(f"\nProcessing scene: {scene_dir.name}")
    
    # Load annotation
    annotation_path = scene_dir / "annotation.json"
    annotation = load_annotation(annotation_path)
    if not annotation:
        return False
    
    # Find image file
    image_filename = annotation['image']
    image_path = scene_dir / image_filename
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        return False
    
    # Load image
    image = load_image(image_path)
    if image is None:
        return False
    
    # Get point coordinates
    point = (annotation['point']['x'], annotation['point']['y'])
    print(f"Point coordinates: ({point[0]:.2f}, {point[1]:.2f})")
    print(f"Label: {annotation['label']}")
    
    # Generate mask
    print("Generating mask with SAM3...")
    mask = generate_mask_sam3(image, point, model=model, processor=processor)
    if mask is None:
        return False
    
    # Save mask
    mask_filename = "mask_b.png"
    mask_path = scene_dir / mask_filename
    save_mask(mask, mask_path)
    
    # Update annotation
    update_annotation_with_mask(annotation_path, mask_filename)
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate object masks using SAM3 based on annotation points"
    )
    parser.add_argument(
        "data_root",
        type=Path,
        help="Path to root folder containing scene directories"
    )
    parser.add_argument(
        "--scene",
        type=str,
        help="Process specific scene directory (optional, processes all if not specified)"
    )
    parser.add_argument(
        "--model-path",
        type=str,
        help="Path to SAM3 checkpoint file (e.g., sam3_h.pt)"
    )
    parser.add_argument(
        "--model-type",
        type=str,
        choices=["vit_h", "vit_l", "vit_b"],
        default="vit_h",
        help="SAM3 model type (default: vit_h)"
    )
    
    args = parser.parse_args()
    
    data_root = args.data_root.expanduser().resolve()
    if not data_root.is_dir():
        print(f"Error: Data root '{data_root}' does not exist or is not a directory.")
        return 1
    
    model, processor = build_model(model_path=args.model_path)
    
    # Process scenes
    if args.scene:
        # Process single scene
        scene_dir = data_root / args.scene
        if not scene_dir.is_dir():
            print(f"Error: Scene directory '{scene_dir}' does not exist.")
            return 1
        process_scene(scene_dir, model=model, processor=processor)
    else:
        # Process all scenes
        scenes = [d for d in data_root.iterdir() if d.is_dir()]
        if not scenes:
            print(f"No scene directories found in {data_root}")
            return 1
        
        print(f"Found {len(scenes)} scene(s) to process")
        success_count = 0
        for scene_dir in sorted(scenes):
            if process_scene(scene_dir, model=model, processor=processor):
                success_count += 1
        
        print(f"\nCompleted: {success_count}/{len(scenes)} scenes processed successfully")
    
    return 0


if __name__ == "__main__":
    exit(main())

