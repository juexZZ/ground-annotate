#!/bin/bash
source .venv/bin/activate

########## 1/29/annotations

DATA_DIR=../metacam/data_v3/28_metfloor_first150
python stream/server.py $DATA_DIR/images ./label_28_metfloor.json --output $DATA_DIR/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/2ndfloor
# python stream/server.py $DATA_DIR/images ./label_2ndfloor.json --output $DATA_DIR/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/12thfloor
# python stream/server.py $DATA_DIR/images ./label_12thfloor.json --output $DATA_DIR/stream_annotations.json --port 12346

#realsense

# DATA_DIR=../metacam/data_v3/2ndfloor
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_2ndfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/12thfloor
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_12thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

########## 1/30/annotations

# cDATA_DIR=../metacam/data_v3/28_metfloor
# python stream/server.py $DATA_DIR/images ./label_new_place_1.json --output $DATA_DIR/stream_annotations.json --port 12346

#realsense (tba)

# DATA_DIR=../metacam/data_v3/28_metfloor
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_new_place_1.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

########## 1/28/annotations

# DATA_DIR=../metacam/data_v3/8thfloor_remove
# python stream/server.py $DATA_DIR/images ./label_8thfloor.json --output $DATA_DIR/stream_annotations.json --port 12346

# DATA_DIR=../metacam/8thfloor_v2/8thfloor_static_2
# python stream/server.py $DATA_DIR/images ./label_8thstatic.json --output $DATA_DIR/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/6metro_add
# python stream/server.py $DATA_DIR/images ./label_6metro.json --output $DATA_DIR/stream_annotations.json --port 12345

# DATA_DIR=../metacam/data_v3/6metro_move
# python stream/server.py $DATA_DIR/images ./label_6metro.json --output $DATA_DIR/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/6metro_remove
# python stream/server.py $DATA_DIR/images ./label_6metro.json --output $DATA_DIR/stream_annotations.json --port 12346

#added polka-dotted chair and purple chair annotations
# DATA_DIR=../metacam/data_v3/8thfloor_add
# python stream/server.py $DATA_DIR/images ./label_8thfloor.json --output $DATA_DIR/stream_annotations.json --port 12346

#realsense

# DATA_DIR=../metacam/data_v3/6metro_remove
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_6metro.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/6metro_move
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_6metro.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/6metro_add 
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_6metro.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/8thfloor_remove
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

# DATA_DIR=../metacam/data_v3/8thfloor_move
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

#added polka-dotted chair and purple chair annotations
# DATA_DIR=../metacam/data_v3/8thfloor_add
# python stream/server.py $DATA_DIR/realsense/rgb_subsampled ./label_8thfloor.json --output $DATA_DIR/realsense/stream_annotations.json --port 12346

