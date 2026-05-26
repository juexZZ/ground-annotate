#!/bin/bash
# annotat realsense images
source .venv/bin/activate

DATA_DIR="/local_data/jz4725/metacam/data_v3/8thfloor_move"
python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 27040

# DATA_DIR="/local_data/jz4725/metacam/data_v3/8thfloor_remove"
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR="/local_data/jz4725/metacam/data_v3/8thfloor_add"
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346