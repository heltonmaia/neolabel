# Neonatal Pose Annotator — Build Prompt

You are building a **standalone web app** for annotating 17 COCO keypoints on neonatal video frames. The output feeds a YOLO-pose fine-tuning pipeline (`yolo26m-pose.pt`) for the PotiVision project. Scope: **pose keypoints only** — no bbox drawing, no segmentation, no activity labels.

---

## Goal

Produce a fast, keyboard-driven annotation tool that takes raw neonatal videos as input and emits a **YOLO-pose dataset** ready for `ultralytics` training, with a train/val split done **by baby** (never by frame) and diversity metadata captured per frame.

Target annotator productivity: **≤2 minutes per frame** for 17 keypoints once the UX is right. A dataset of ~300 frames should be completable in under a week of focused work.

---

## Input

- One or more videos of neonates (MP4 / MOV / WebM). Typical resolution 720p–1080p, 15–30 FPS.
- User-provided metadata per video:
  - `baby_id` (string) — anonymous identifier, used for train/val split.
  - `pose_tags` (multi-select): `supine`, `lateral_right`, `lateral_left`, `prone`, `fetal_flexion`, `extended`.
  - `occlusion_tags` (multi-select): `none`, `ecg_cables`, `spo2_probe`, `et_tube`, `ng_tube`, `diaper`, `blanket_partial`, `caregiver_hand`.
  - `lighting_tag` (single): `ambient`, `phototherapy_blue`, `dim`.
  - `framing_tag` (single): `tight_torso`, `full_body`, `oblique`.

---

## Output (YOLO-pose dataset)

Directory layout the app must emit when the user clicks **Export**:

```
dataset/
  data.yaml
  images/
    train/
      {baby_id}_{video_stem}_{frame_idx:06d}.jpg
    val/
      ...
  labels/
    train/
      {baby_id}_{video_stem}_{frame_idx:06d}.txt
    val/
      ...
  metadata.jsonl      # one line per exported frame with all tags + source
```

### `data.yaml`

```yaml
path: .              # resolved at training time
train: images/train
val: images/val

kpt_shape: [17, 3]   # 17 keypoints, each (x, y, visibility)
flip_idx: [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]

names:
  0: baby

# Keypoint order (COCO-17):
#  0 nose
#  1 left_eye       2 right_eye
#  3 left_ear       4 right_ear
#  5 left_shoulder  6 right_shoulder
#  7 left_elbow     8 right_elbow
#  9 left_wrist    10 right_wrist
# 11 left_hip      12 right_hip
# 13 left_knee     14 right_knee
# 15 left_ankle    16 right_ankle
```

### Label `.txt` (one line per frame — single baby per frame)

```
0 cx cy w h  x0 y0 v0  x1 y1 v1  ...  x16 y16 v16
```

- All coordinates normalized `0–1` to the full frame (not a crop).
- `cx cy w h` = bounding box enclosing all labeled keypoints + ~8% padding, clamped to `[0,1]`.
- `vi ∈ {0, 1, 2}`:
  - `0` = not labeled (occluded/outside frame — annotator explicitly marked "absent").
  - `1` = labeled but occluded (annotator estimated position under cables/cloth).
  - `2` = labeled and visible.
- When `v=0`, emit `x=0 y=0`.

### `metadata.jsonl`

One line per exported frame:

```json
{"file": "baby03_clip2_000450.jpg", "split": "train", "baby_id": "baby03", "video": "clip2.mp4", "frame_idx": 450, "timestamp_s": 15.0, "pose_tags": ["supine"], "occlusion_tags": ["ecg_cables"], "lighting_tag": "ambient", "framing_tag": "full_body", "annotator": "helton", "created_at": "2026-04-15T14:32:11Z", "visible_count": 15, "occluded_count": 2, "absent_count": 0}
```

---

## Train/val split

- **By baby, not by frame.** User picks a target val ratio (default 0.2).
- App proposes a split that assigns whole-baby sets to val such that val frame count ≈ target ratio. Show the proposed split before export; allow manual override per baby.
- **Hard rule:** if a `baby_id` appears in train, it must not appear in val. Reject export if violated.

---

## Frame extraction

- Load video via `<video>` element + HTMLCanvas frame grab (no server-side ffmpeg required for v1).
- **Sampling cadence:** user-selectable "one frame every N seconds" (default 3s). Pre-populate a timeline with sampled candidate frames as thumbnails.
- **On-demand capture:** user can also seek to any timestamp and add that frame manually.
- **Avoid near-duplicates:** when the user adds a manual frame, warn if another already-accepted frame is within `±1s` in the same video.
- Exported JPEG quality: 92.

---

## Annotation UX (keyboard-first)

**Layout:** left panel = frame list with status chips (pending / in-progress / done / skipped); center = canvas with the frame; right panel = keypoint list (17 rows) + metadata tags for the current video.

### Keypoint interaction
- The 17 keypoints have a **fixed order**. The app shows "Next: left_shoulder" with a colored cursor.
- **Click** places the keypoint at the click location with `v=2` (visible) and advances to the next.
- **Shift+Click** places with `v=1` (occluded, estimated).
- **Keyboard `A`** on the current keypoint marks it `v=0` (absent) without placing, and advances.
- **Keyboard `[` / `]`** go to previous / next keypoint in the list.
- **Keyboard `Backspace`** clears the current keypoint and stays.
- **Right-click** on any existing keypoint dot: context menu {change visibility, delete, re-place}.
- **Drag** an existing keypoint dot to reposition without changing visibility.

### Navigation
- **`J` / `K`** or **`←` / `→`**: prev / next frame in the active video's sample list.
- **`Space`**: toggle "done" status for current frame (done = all 17 keypoints have `v ∈ {0,1,2}` explicitly set).
- **`S`**: skip frame (exclude from export). Skipped frames can be re-included later.
- **`Z`** / **`Ctrl+Z`**: undo last action on current frame (place, move, delete, visibility change).
- **`+` / `-` / mouse wheel**: zoom; **hold space + drag**: pan. Zoom target follows cursor.
- **`G`**: toggle a subtle anatomical skeleton overlay connecting already-placed keypoints (helps spot wrong left/right).
- **`H`**: toggle help overlay showing all shortcuts.

### Visual affordances
- Each keypoint has a dedicated color (consistent across frames). Left side = warm palette, right side = cool palette, midline (nose) = white. This makes L/R swaps visually obvious.
- Unlabeled keypoints shown greyed in the right panel; `v=0` shown with a diagonal strike-through; `v=1` shown with a dashed ring; `v=2` shown with a solid ring.
- When "done" for a frame, the next pending frame auto-loads.

### Assisted labeling (optional, behind a toggle)
- "Prefill from previous frame" button: copies keypoints from the last completed frame of the same video as a starting point, all with `v=1` (annotator must confirm/move each). Fast path for slowly-moving babies.
- Optional "Prefill from model": POST the frame to an existing YOLO endpoint and pre-populate keypoints with model predictions; annotator corrects. Make this opt-in (the whole point of the dataset is to beat the model).

---

## Quality gates before export

Block export (or require override with warning) when:

1. Any frame marked "done" has keypoints where `v=2` is set but the point lies outside the frame.
2. More than 10% of frames have `visible_count < 5` (likely under-labeled).
3. Left/right pairs are systematically swapped on >5% of frames (heuristic: check that `left_shoulder.x < right_shoulder.x` on most supine frames — expose as a warning with examples to review, not a hard block).
4. `baby_id` is shared between train and val.
5. Diversity warning (soft): if any `baby_id` contributes >30% of total frames, or any `pose_tag` has <5% coverage, show a dashboard panel suggesting which combinations to label more of. Do not block.

---

## Project / session persistence

- Work-in-progress stored in **IndexedDB**: videos (as Blob), frame samples (as dataURLs or references), per-frame annotations, metadata.
- Auto-save on every annotation change.
- **Import / Export project**: single `.zip` containing annotations JSON + per-video metadata + video filenames. Videos themselves are *not* embedded in the project zip (too large) — user re-attaches them on import by filename match.
- Dataset export is a separate action that produces the YOLO-pose tree above.

---

## Tech stack (recommended)

- **Frontend only**, single-page. React + TypeScript + Vite.
- **Canvas** for rendering frames and keypoints (not SVG — performance matters when zoomed).
- **IndexedDB** via `idb` for persistence.
- **JSZip** for export bundling.
- No backend required for v1. (A thin Python script can consume the exported tree and launch `ultralytics` training separately.)

---

## Out of scope (explicit non-goals)

- Multi-baby frames. Assume one baby per frame. If two babies appear, instruct user to skip.
- Bounding box drawing (derived automatically from keypoints).
- Segmentation masks.
- Activity / state labels (still, moving, breathing pattern).
- Video-level temporal models (annotations are per-frame only).
- Model training. This app only produces the dataset.

---

## Acceptance criteria

1. I can load a video, sample frames every 3s, and see them as thumbnails.
2. I can annotate all 17 keypoints on a frame using only the keyboard + mouse click — no dropdowns, no typing.
3. Annotating a typical frame takes me ≤2 minutes.
4. Export produces a `dataset/` tree that `ultralytics` loads without error: `YOLO('yolo26m-pose.pt').train(data='dataset/data.yaml', epochs=1)` runs end-to-end.
5. Train/val split is enforced to be by-baby; attempting to violate this blocks export with a clear error.
6. Closing the browser mid-session and reopening restores all annotations exactly.
7. Metadata tags from the video-level form appear correctly in every `metadata.jsonl` row for that video.

---

## Reference: COCO-17 keypoint order and left/right flip map

```
index  name            flip_to
0      nose            0
1      left_eye        2
2      right_eye       1
3      left_ear        4
4      right_ear       3
5      left_shoulder   6
6      right_shoulder  5
7      left_elbow      8
8      right_elbow     7
9      left_wrist      10
10     right_wrist     9
11     left_hip        12
12     right_hip       11
13     left_knee       14
14     right_knee      13
15     left_ankle      16
16     right_ankle     15
```

The `flip_idx` array in `data.yaml` must match this mapping exactly — it drives YOLO's horizontal-flip augmentation during training. A wrong mapping silently teaches the model that "left" and "right" are interchangeable.
