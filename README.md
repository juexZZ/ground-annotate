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

### Remote access

If the dataset lives on a remote workstation but you want to annotate from a laptop:

- Launch the server on the workstation with a publicly reachable interface, e.g. `python annotate/server.py /data/path --host 0.0.0.0 --port 1234`, and open `http://<workstation-ip>:1234` from your laptop (make sure firewalls allow that port).
- Alternatively, use SSH port forwarding: `ssh -L 1234:localhost:1234 user@workstation` and run the server on the workstation with the default host/port; then browse to `http://localhost:1234` locally.

## Using the UI

- The scene dropdown and sidebar list let you jump to any subfolder; annotated scenes are marked in green and show a check icon when active.
- A "Next" button iterates through scenes sequentially.
- Image A (left) is a read-only reference. Image B (right) is clickable: clicking records the coordinate of the new object (coordinates are stored in Image B pixel space, adjusted for scaling).
- After clicking Image B, a sidebar form shows the coordinate and lets you type a category label. "Confirm" writes `annotation.json` in the scene folder (overwriting any previous annotation). "Cancel" discards the pending click.
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

## Development notes

- The server is a small Flask app located in `annotate/server.py`. Static assets live under `annotate/static/` and the HTML template is in `annotate/templates/`.
- No external services are required; everything runs locally.
