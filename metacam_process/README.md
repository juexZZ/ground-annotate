# metacam_process

Preprocessing for Metacam captures. Takes a scene exported by **Metacam Studio**
and produces the layout the annotation tools expect: undistorted pinhole
`images/` plus a COLMAP `sparse/0` model carrying the Studio poses.

Everything upstream of this is the Studio desktop app's job. Studio runs the
LiDAR-inertial SLAM and writes `transforms.json`; from there on the pipeline
lives in this repository.

## Input

One directory per scene under a common root, each as exported by Studio:

```
<data_root>/
  <scene>/
    transforms.json          # per-frame intrinsics + camera-to-world poses
    camera/
      left/<timestamp>.jpg
      right/<timestamp>.jpg
```

Subdirectories without a `transforms.json` are ignored, so a root may hold
unrelated folders (raw captures, trimmed subsets) without confusing discovery.

## Output

Written in place, alongside the inputs:

```
<scene>/
  fisheye/<side>_<timestamp>.jpg   # flattened copy (or symlink) of camera/
  images/<side>_<timestamp>.png    # undistorted, 800x800, 90 deg FOV
  sparse/0/                        # cameras/images/points3D, .bin and .txt
```

`images/` is what `stream/server.py` is pointed at. `sparse/0` holds one
`PINHOLE` camera (`400 400 400 400`) shared by all images, since undistortion
maps every camera onto the same target intrinsics. There are no triangulated
points — `points3D` is intentionally empty.

## Usage

```bash
python -m metacam_process <data_root>            # process every scene found
python -m metacam_process <data_root> --list     # show what would be processed
```

| flag | effect |
|---|---|
| `--scenes A B` | only these scene directory names |
| `--list` | print discovered scenes and exit |
| `--link` | symlink into `fisheye/` instead of copying every source JPG |
| `--force` | redo every stage, overwriting existing outputs |
| `--size` / `--fov` | undistortion target, default `800` px and `90` degrees |
| `--status` | progress file, default `<data_root>/.metacam_process_status.json` |

Progress is recorded per scene and per stage, so an interrupted run resumes
instead of redoing finished scenes. Individual files are also skipped when they
already exist.

## Worked example: the DejaView scenes (`data_v4`)

Eight scenes downloaded from
[`Mythicane/DejaView`](https://huggingface.co/datasets/Mythicane/DejaView) and
unzipped to `/local_data/jz4725/metacam/data_v4`.

**These are raw captures, straight off the device.** A scene looks like this —
`camera/left`, `camera/right`, plus the LiDAR/IMU stream in `data/` and the
factory calibration in `info/`:

```
data_v4/
  10 th floor 2 metro tech/
    camera/{left,right}/<timestamp>.jpg
    data/{data_0,data_1}        # raw LiDAR + IMU, opaque
    info/calibration.json       # factory calibration
    metadata.yaml
    colorized-realtime.las
  2 metro tech 8 floor/
  ...
```

There is no `transforms.json`, so there are no camera poses yet and this module
has nothing to work with:

```console
$ python -m metacam_process /local_data/jz4725/metacam/data_v4 --list
No scenes with a transforms.json found under /local_data/jz4725/metacam/data_v4
```

### 1. Run the capture through Metacam Studio

Open each capture in Studio and export the processed scene. Studio runs the SLAM
and writes `transforms.json` next to `camera/`, which is the handoff point — a
Studio-processed scene looks like the ones in `data_v3`. This is the only step
that is not in this repository.

### 2. Preprocess

Point the module at the root holding the exported scenes:

```bash
python -m metacam_process /local_data/jz4725/metacam/data_v4
```

Scene names here contain spaces, so quote them when selecting individual scenes:

```bash
python -m metacam_process /local_data/jz4725/metacam/data_v4 \
    --scenes "10 th floor 2 metro tech" "5 metro tech lobby"
```

Output takes this shape per scene (counts and calibration values depend on the
capture):

```console
============================================================
10 th floor 2 metro tech
============================================================
<N> frames in transforms.json | cameras: left, right
- collect fisheye
  <N> written, 0 already present, 0 missing
- undistort to 800x800 @ 90.0 deg FOV
  [left] <N/2> frames | source <W>x<H> | fl_x=... cx=... k1=...
  [right] <N/2> frames | source <W>x<H> | fl_x=... cx=... k1=...
  <N> written, 0 already present, 0 missing
- write COLMAP sparse model
  sparse/0 written with <N> images
```

The two `[left]` / `[right]` lines are worth reading: they confirm each camera
was undistorted with its own intrinsics. Seeing only one line, or the same
`fl_x` on both, means the frames did not carry per-camera calibration —
check the export before trusting the result.

Disk note — `fisheye/` duplicates every source JPG. On a full volume use
`--link` to symlink instead:

```bash
python -m metacam_process /local_data/jz4725/metacam/data_v4 --link
```

### 3. Annotate

`images/` is what the annotation server takes:

```bash
SCENE="/local_data/jz4725/metacam/data_v4/10 th floor 2 metro tech"
python stream/server.py "$SCENE/images" ./label_example.json \
    --output "$SCENE/stream_annotations.json" --port 12346
```

## Per-camera intrinsics

The left and right cameras are calibrated independently and their intrinsics
genuinely differ. In `data_v3/12thfloor/transforms.json`:

| | fl_x | cx | k1 |
|---|---|---|---|
| left | 785.898 | 1461.209 | 0.08281 |
| right | 782.652 | 1453.457 | 0.07951 |

Each side has exactly one intrinsic set across all its frames, so this is
per-camera calibration rather than anything per-frame.

This module groups frames by calibration and builds one undistortion map per
group, so each camera is undistorted with its own `K`/`D`.

**This differs from the original `process_urbansim_data.py`.** That script read
intrinsics from a single probe frame — `fisheye_files[0]`, i.e. whichever file
`Path.glob` happened to return first — and applied them to every image. One
camera therefore got undistorted with the other camera's model. Measured on
`12thfloor`, that misplaces content in the 800x800 output by a median of 5.7 px
(mean 6.6, p95 11.4, max 17.8), growing toward the image edges, and leaves a
systematic reprojection error against the shared `PINHOLE` model in `sparse/0`.

Consequence: re-running this module over scenes processed by the old script
changes the second camera's `images/`. Verified against the original on a
6-frame fixture — the probe-side images come out bit-identical, the other
side's differ across ~95% of pixels, and the entire `sparse/0` model (poses
included) is bit-identical.

## Layout

| file | contents |
|---|---|
| `__main__.py` | CLI, scene discovery, resume state |
| `steps.py` | the three pipeline steps |
| `scene.py` | `transforms.json` parsing, `Intrinsics`/`Frame`, grouping |
| `colmap.py` | COLMAP model structures and binary/text writers |
| `geometry.py` | Studio to COLMAP coordinate conversion |

Depends only on what the repository already requires: numpy, opencv-python,
scipy, tqdm.
