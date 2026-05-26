# Pairwise Annotation Tool

A standalone web tool for collecting "new object" annotations from pairs of images. The annotator compares `image_a` (reference) with `image_b` (current observation) and clicks the newly appeared object in `image_b`.

## Expected dataset layout

```
root_folder/
├── scene_001/
│   ├── image_a.jpg
│   ├── image_b.jpg
│   └── annotation.json          # created by the tool
├── scene_002/
│   ├── image_a.png
│   └── image_b.png
└── ...
```

Each scene subdirectory must contain at least two images named `image_a.*` and `image_b.*` (any of `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`).

## Running the server

From the repo root:

```bash
python pairwise/server.py /path/to/root_folder
```

Default host/port are `127.0.0.1:1234`. You can customize them with `--host` or `--port` if needed. When the server is running, open `http://localhost:1234` in your browser.

### Remote access

If the dataset lives on a remote workstation but you want to annotate from a laptop:

- Launch the server on the workstation with a publicly reachable interface, e.g. `python pairwise/server.py /data/path --host 0.0.0.0 --port 1234`, and open `http://<workstation-ip>:1234` from your laptop (make sure firewalls allow that port).
- Alternatively, use SSH port forwarding: `ssh -L 1234:localhost:1234 user@workstation` and run the server on the workstation with the default host/port; then browse to `http://localhost:1234` locally.

## Using the UI

- The scene dropdown and sidebar list let you jump to any subfolder; annotated scenes are marked in green and show a check icon when active.
- A "Next" button iterates through scenes sequentially.
- Image A (left) is a read-only reference. Image B (right) supports interactive mask prompting: **left click = positive point**, **right click = negative point** (coordinates are stored in Image B pixel space, adjusted for scaling).
- After adding points and a category label, click **Generate / Update Mask** to run SAM3 and preview the mask overlay. Add more left/right clicks and regenerate until satisfied.
- **Confirm** writes `annotation.json` and `mask_b.png` in the scene folder (overwriting previous outputs). **Cancel** restores the latest saved annotation state for that scene.
- Saved annotations automatically re-appear when you revisit a scene, and you can overwrite them by clicking and confirming again.
- A "Create new scene" panel lets you upload `image_a`/`image_b` pairs directly from your machine; the tool will create a new subfolder, ingest the files, and immediately load it for annotation.

## Uploading new scenes

Use the upload panel on the right side of the UI:

1. (Optional) Provide a scene name consisting of letters, numbers, `_` or `-`. If left blank, the tool will generate a timestamped name.
2. Pick `image_a` and `image_b` from your machine (supported: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`).
3. Click **Upload scene**. A new subdirectory will be created under the dataset root, the files will be saved inside it, and the UI will automatically switch to that scene so you can annotate immediately.

## Annotation format

Each confirmation creates/overwrites `<scene>/annotation.json` with the following structure:

```json
{
  "scene": "scene_001",
  "annotation": {
    "point": {"x": 512.4, "y": 318.2},
    "label": "bicycle",
    "updated_at": "2024-05-01T12:34:56.789123+00:00",
    "image": "image_b.jpg",
    "image_size": {"width": 1024, "height": 768}
  }
}
```

`x` and `y` are stored in raw Image B pixel units (not screen coordinates) so they remain valid even if the UI is resized. The `image_size` entry captures the width and height of `image_b` at the time of annotation. Re-running the tool simply reuses the existing JSON files.

## Interactive Masking with SAM3

The pairwise server can load SAM3 at startup and generate masks directly during annotation (no separate post-processing step required).

### Setup

1. Install additional dependencies:
   ```bash
   uv pip install numpy torch torchvision
   uv pip install git+https://github.com/facebookresearch/sam3.git
   ```

   Or install from source:
   ```bash
   git clone https://github.com/facebookresearch/sam3.git
   cd sam3
   pip install -e .
   ```

2. Download SAM3 checkpoint files (if required) from:
   - https://github.com/facebookresearch/sam3
   - Note: Some SAM3 models may auto-download checkpoints on first use

### Usage

Launch with SAM3 enabled (default behavior):
```bash
python pairwise/server.py /path/to/root_folder --mask-model-path /path/to/sam3.pt
```

If your SAM3 install can resolve default checkpoints, `--mask-model-path` is optional:
```bash
python pairwise/server.py /path/to/root_folder
```

Disable masking explicitly (fallback to point-only annotation):
```bash
python pairwise/server.py /path/to/root_folder --disable-masking
```

Legacy batch script is still available for offline processing:
```bash
python generate_mask.py /path/to/root_folder --model-path /path/to/sam3.pt
```

### Updated Annotation Format

After interactive mask confirmation, the annotation file includes mask metadata:

```json
{
  "scene": "scene_001",
  "annotation": {
    "point": {"x": 512.4, "y": 318.2},
    "label": "bicycle",
    "updated_at": "2024-05-01T12:34:56.789123+00:00",
    "image": "image_b.jpg",
    "image_size": {"width": 1024, "height": 768},
    "mask_points": [
      {"x": 512.4, "y": 318.2, "kind": "positive"},
      {"x": 496.1, "y": 302.8, "kind": "negative"}
    ],
    "mask": "mask_b.png",
    "mask_score": 0.987
  }
}
```

## Push data to Hugging Face

```bash
python data_push_hf.py /path/to/data/root/ --repo-id juexzz/real-change --private --split-mode test
```
