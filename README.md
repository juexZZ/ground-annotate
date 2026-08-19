# Ground Annotate

A collection of standalone web tools for image annotation. The tools do not depend on the rest of the codebase and can be launched against any folder containing the expected layout.

Two annotation styles are available:

- **Pairwise** — compare `image_a` (reference) with `image_b` (current observation) and click the newly appeared object. See [`pairwise/README.md`](pairwise/README.md).
- **Stream** — annotate points on a flat folder of images against a predefined label set. See [`stream/README.md`](stream/README.md).

## Setup

From the repository root:

```bash
uv sync
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

## Stream annotation pipeline

The stream tool annotates a flat folder of images against a predefined label set.

0. **Preprocess (Metacam data).** The annotation pipeline works with any image folder. For data captured with Metacam, run [`metacam_process`](metacam_process/README.md) over the directory holding your scenes:

   ```bash
   python -m metacam_process /path/to/data_root          # process every scene
   python -m metacam_process /path/to/data_root --list   # check what it finds first
   ```

   It writes undistorted `images/` and a COLMAP `sparse/0` model into each scene; `images/` is what you point the annotation server at in step 3.

   The input must already be **exported from Metacam Studio** — Studio runs the SLAM and writes the `transforms.json` holding the camera poses, and that is the one step outside this repository. Raw captures straight off the device have no poses yet, and are reported rather than half-processed:

   ```console
   $ python -m metacam_process /local_data/jz4725/metacam/data_v4 --list
   No scenes with a transforms.json found under /local_data/jz4725/metacam/data_v4
   ```

   Once those scenes have been through Studio, the same command processes all eight. Quote scene names that contain spaces:

   ```bash
   DATA_ROOT=/local_data/jz4725/metacam/data_v4
   python -m metacam_process $DATA_ROOT --link
   python -m metacam_process $DATA_ROOT --scenes "5 metro tech lobby"
   ```

   `--link` symlinks into `fisheye/` instead of copying every source JPG, which matters on a full volume. See [`metacam_process/README.md`](metacam_process/README.md) for the full walkthrough, the remaining flags, and a note on the per-camera intrinsics fix.

1. **Get example data.** Unzip `example_data/stream/28_metfloor_first150.zip` to play with the pipeline. You will get a folder of images plus a reference `stream_annotations.json` — the reference file is included only as a sanity check; running the tool will write a fresh annotations JSON of your own.

2. **Read the annotation guideline.** Open [`docs/stream_protocol.html`](docs/stream_protocol.html) in a browser for the labeling protocol.

3. **Launch the server.** Point it at the unzipped image folder and a label set (example uses `label_28_metfloor.json` from the repo root):

   ```bash
   DATA_DIR=example_data/stream/28_metfloor_first150
   python stream/server.py $DATA_DIR/images ./label_28_metfloor.json \
       --output $DATA_DIR/stream_annotations.json --port 12346
   ```

   Then open `http://localhost:12346` in your browser. See [`stream/README.md`](stream/README.md) for full UI details and the output format. Additional launch commands for other datasets are collected in `launch_stream_server.sh`.

## Development notes

- Pairwise annotation tool: `pairwise/server.py` (assets: `pairwise/static/`, template: `pairwise/templates/`).
- Stream annotation tool: `stream/server.py` (assets: `stream/static/`, template: `stream/templates/`).
- Metacam preprocessing: `metacam_process/` (see [`metacam_process/README.md`](metacam_process/README.md)).
- Mask generation script: `generate_mask.py`
- No external services are required; everything runs locally.
