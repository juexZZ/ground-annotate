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

try:
    import sam3
    # Try different possible import paths for SAM3
    BUILD_FUNC_NAME = None
    build_sam3_image_model = None
    build_sam3 = None
    
    try:
        from sam3 import build_sam3_image_model
        BUILD_FUNC = build_sam3_image_model
        BUILD_FUNC_NAME = "build_sam3_image_model"
    except ImportError:
        try:
            from sam3.model_builder import build_sam3
            BUILD_FUNC = build_sam3
            BUILD_FUNC_NAME = "build_sam3"
        except ImportError:
            BUILD_FUNC = None
            BUILD_FUNC_NAME = None
    
    from sam3.model.sam3_image_processor import Sam3Processor
    SAM3_AVAILABLE = True
except ImportError as e:
    SAM3_AVAILABLE = False
    BUILD_FUNC = None
    BUILD_FUNC_NAME = None
    build_sam3_image_model = None
    build_sam3 = None
    print("Warning: sam3 package not found. Please install it with:")
    print("  pip install git+https://github.com/facebookresearch/sam3.git")
    print("  or")
    print("  git clone https://github.com/facebookresearch/sam3.git")
    print("  cd sam3")
    print("  pip install -e .")
    print(f"\nImport error: {e}")
    print("\nSee: https://github.com/facebookresearch/sam3")


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


def generate_mask_sam3(
    image: Image.Image,
    point: Tuple[float, float],
    model_path: Optional[str] = None,
    model_type: str = "vit_h"
) -> Optional[np.ndarray]:
    """
    Generate mask using SAM3 model.
    
    Args:
        image: Input image as PIL Image
        point: Point coordinates (x, y)
        model_path: Path to SAM3 checkpoint file (optional)
        model_type: Model type - "vit_h", "vit_l", or "vit_b"
    
    Returns:
        Binary mask as numpy array (H, W) with values 0 or 1
    """
    if not SAM3_AVAILABLE:
        raise ImportError("sam3 package is required. Install from: https://github.com/facebookresearch/sam3")
    
    # Get device
    device = get_device()
    print(f"Using device: {device}")
    
    # Build SAM3 model
    try:
        if BUILD_FUNC is None:
            raise ImportError("Could not find SAM3 build function")
        
        # Try building the model - different build functions may have different signatures
        if BUILD_FUNC_NAME == "build_sam3_image_model":
            # build_sam3_image_model() may take no args or checkpoint path
            if model_path:
                model = BUILD_FUNC(checkpoint_path=model_path)
            else:
                model = BUILD_FUNC()
        else:
            # build_sam3() with model config
            if model_path:
                model = BUILD_FUNC(
                    model_cfg=model_type,
                    checkpoint_path=model_path,
                    device=device
                )
            else:
                model = BUILD_FUNC(
                    model_cfg=model_type,
                    device=device
                )
        
        model.eval()
        model.to(device)
        
        # Create processor
        processor = Sam3Processor(model)
    except Exception as e:
        print(f"Error loading SAM3 model: {e}")
        print("Make sure you have installed sam3 and downloaded the checkpoint if required.")
        print("See: https://github.com/facebookresearch/sam3")
        import traceback
        traceback.print_exc()
        return None
    
    # Set the image (computes image embeddings)
    try:
        inference_state = processor.set_image(image)
    except Exception as e:
        print(f"Error setting image: {e}")
        return None
    
    # Prepare point coordinates
    # SAM3 expects points in format: np.array([[x, y]]) with shape (1, 2) for single point
    # Based on the notebook example: point_coords should be shape (1, 2) for a single point
    # point_labels should be shape (1, 1) for a single point: np.array([[1]])
    point_coords = np.array([[point[0], point[1]]], dtype=np.float32)
    point_labels = np.array([[1]], dtype=np.int32)  # 1 indicates foreground point
    
    # Generate mask using predict_inst
    # Based on notebook: model.predict_inst(inference_state, point_coords=..., point_labels=..., ...)
    try:
        masks, scores, _ = model.predict_inst(
            inference_state,
            point_coords=point_coords,
            point_labels=point_labels,
            multimask_output=False  # Return single best mask
        )
        
        # masks shape depends on output: could be (num_masks, H, W) or (1, H, W) or (1, 1, H, W)
        # Handle different possible shapes
        if isinstance(masks, torch.Tensor):
            masks = masks.cpu().numpy()
        
        # Flatten to get the mask
        if masks.ndim == 4:
            mask = masks[0, 0]  # (batch, num_masks, H, W) -> (H, W)
        elif masks.ndim == 3:
            mask = masks[0]  # (num_masks, H, W) or (1, H, W) -> (H, W)
        else:
            mask = masks  # Already (H, W)
        
        # Convert to binary (0 or 1) - masks are typically float in [0, 1]
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


def process_scene(scene_dir: Path, model_path: Optional[str] = None, model_type: str = "vit_h"):
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
    mask = generate_mask_sam3(image, point, model_path=model_path, model_type=model_type)
    if mask is None:
        return False
    
    # Save mask
    mask_filename = "mask.png"
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
    
    if not SAM3_AVAILABLE:
        print("Error: sam3 package is required but not installed.")
        print("Install with: pip install git+https://github.com/facebookresearch/sam3.git")
        print("Or see: https://github.com/facebookresearch/sam3")
        return 1
    
    # Process scenes
    if args.scene:
        # Process single scene
        scene_dir = data_root / args.scene
        if not scene_dir.is_dir():
            print(f"Error: Scene directory '{scene_dir}' does not exist.")
            return 1
        process_scene(scene_dir, model_path=args.model_path, model_type=args.model_type)
    else:
        # Process all scenes
        scenes = [d for d in data_root.iterdir() if d.is_dir()]
        if not scenes:
            print(f"No scene directories found in {data_root}")
            return 1
        
        print(f"Found {len(scenes)} scene(s) to process")
        success_count = 0
        for scene_dir in sorted(scenes):
            if process_scene(scene_dir, model_path=args.model_path, model_type=args.model_type):
                success_count += 1
        
        print(f"\nCompleted: {success_count}/{len(scenes)} scenes processed successfully")
    
    return 0


if __name__ == "__main__":
    exit(main())

