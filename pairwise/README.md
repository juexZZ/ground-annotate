# Pairwise Annotation Tool

This is the original annotation style for **scene folders** that contain `image_a.*` and `image_b.*`.

## Run

From the repo root:

```bash
python pairwise/server.py /path/to/root_folder --mask-model-path /path/to/sam3_checkpoint.pt
```

Then open `http://127.0.0.1:1234`.

If SAM3 is installed and the model loads successfully, the UI supports interactive mask refinement:

- Left click on Image B to add a positive point.
- Right click on Image B to add a negative point.
- Click **Generate / Update Mask** to run SAM3 and preview the mask overlay.
- Add more left/right clicks and generate again until the mask looks correct.
- Click **Confirm** to save annotation + refined points + `mask_b.png`.

Useful flags:```bash
# Use default SAM3 model loading (explicit checkpoint path)
python pairwise/server.py ../change_annotation_test --mask-model-path ../sam3/checkpoints/sam3.pt 

# Disable masking endpoints/UI workflow
python pairwise/server.py /path/to/root_folder --disable-masking
```

Push data to HF:
```bash
python data_push_hf.py /path/to/data/root/ --repo-id juexzz/real-change --private --split-mode test
```
