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

0. **Preprocess (Metacam data)**
The annotation pipeline should work with any image folder. For data captured using metacam, preprocessing script `process_metacam_data.py` should be called first.
*TODO: modify the script to be not hardcoded.*

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
- Mask generation script: `generate_mask.py`
- No external services are required; everything runs locally.
