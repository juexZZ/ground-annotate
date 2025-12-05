# Human Annotation Tool

This directory contains a standalone web tool for collecting "new object" annotations from pairs of images. It does not depend on the rest of the codebase and can be launched against any folder that contains scene subdirectories.

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

Each scene subdirectory must contain at least two images named `image_a.*` and `image_b.*` (any of `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`). The annotator compares `image_a` (reference) with `image_b` (current observation) and clicks the newly appeared object in `image_b`.

## Setup (recommended virtual environment)

From the repository root:

```bash
python -m venv annotate/.venv
source annotate/.venv/bin/activate  # Windows: annotate\.venv\Scripts\activate
pip install -r annotate/requirements.txt
```

## Running the server

```
python annotate/server.py /path/to/root_folder
```

Default host/port are `127.0.0.1:1234`. You can customize them with `--host` or `--port` if needed. When the server is running, open `http://localhost:1234` in your browser.

## Using the UI

- The scene dropdown and sidebar list let you jump to any subfolder; annotated scenes are marked in green and show a check icon when active.
- A "Next" button iterates through scenes sequentially.
- Image A (left) is a read-only reference. Image B (right) is clickable: clicking records the coordinate of the new object (coordinates are stored in Image B pixel space, adjusted for scaling).
- After clicking Image B, a sidebar form shows the coordinate and lets you type a category label. "Confirm" writes `annotation.json` in the scene folder (overwriting any previous annotation). "Cancel" discards the pending click.
- Saved annotations automatically re-appear when you revisit a scene, and you can overwrite them by clicking and confirming again.

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

## Development notes

- The server is a small Flask app located in `annotate/server.py`. Static assets live under `annotate/static/` and the HTML template is in `annotate/templates/`.
- No external services are required; everything runs locally.
