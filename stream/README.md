# Stream Annotation Tool

This folder contains an alternative annotation style (**stream**) for flat image folders.

## Expected dataset layout

```
images_root/
├── 000001.jpg
├── 000002.jpg
├── ...
└── stream_annotations.json     # created by the tool (default)
```

## Labels file

You must provide a predefined label set via JSON. Two supported formats:

### Option A: a plain list

```json
["car", "person", "bicycle"]
```

### Option B: an object with `labels`

```json
{"labels": ["car", "person", "bicycle"]}
```

## Running the server

From the repo root:

```bash
python stream/server.py /path/to/images_root /path/to/labels.json
```

Defaults:
- Host: `127.0.0.1`
- Port: `1235`
- Output: `/path/to/images_root/stream_annotations.json`

## UI behavior

- Click **a point in the image**, then click a **label button** to assign that point to the label.
- You can add **multiple labeled points** per image.
- If there are **no objects of interest**, add nothing and press **← / →** to move on; navigating marks the image as **completed** by writing an entry with an empty `annotations` list.
- Press **← / →** to navigate quickly; the current image is **auto-saved on navigation** (overwriting any prior saved result for that image).
- Toggle **New traverse?** to mark that image as a new traversal/chapter start; the button remains lit until toggled off.

## Output format

The tool writes one JSON file for the whole folder (default `stream_annotations.json`):

```json
{
  "version": 1,
  "labels": ["car", "person", "bicycle"],
  "images": [
    {
      "file": "000001.jpg",
      "new_traversal": false,
      "annotations": [
        {"category": "car", "point": {"x": 512.4, "y": 318.2}}
      ]
    }
  ]
}
```

