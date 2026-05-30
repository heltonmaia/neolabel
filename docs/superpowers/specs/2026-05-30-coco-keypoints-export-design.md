# COCO Keypoints JSON export (ViTPose) — design

**Date:** 2026-05-30
**Status:** Approved (pending spec review)

## Problem

NeoLabel exports YOLO-pose, CSV, JSONL, etc., but not COCO Keypoints
JSON. We need COCO Keypoints output so the infant-pose dataset can
fine-tune ViTPose (HuggingFace transformers) and feed any
MMPose/pycocotools pipeline. It must sit ALONGSIDE the existing
exporters without changing them. Critically, the COCO splits must match
the existing YOLO splits exactly so YOLO and ViTPose are comparable in
the paper.

## Goals

- New COCO Keypoints exporters: `coco` (single `annotations.json`) and
  `coco_split` (ZIP of `train.json` / `val.json` / `test.json`).
- Splits produced by `coco_split` are byte-for-byte the same partition
  as `yolo_split` for the same `train/val/test/seed` — guaranteed by
  sharing the partition routine and the eligible-item ordering.
- COCO `file_name` matches the YOLO export filename for the same frame,
  so a frame lines up across both datasets.
- Infant (COCO-17 `person`) only.
- Do not change any existing exporter's output.

## Non-goals

- No `exclude_occluded` support for COCO (COCO stays faithful: occluded
  keypoints keep `v=1`). Can be added later.
- No rodent (7-keypoint) COCO export — rejected with 422.
- No persistent on-disk split storage (NeoLabel computes splits at
  export time from `train/val/test/seed`; COCO mirrors that).

## Key facts (already verified in the codebase)

- NeoLabel stores pose keypoints in **COCO-17 order already**
  (`frontend/src/lib/keypoints.ts::COCO_KEYPOINTS`, indices 0=nose …
  16=right_ankle), and the YOLO exporter writes them in that order. So
  the COCO export needs **no keypoint reordering**.
- Visibility is the **COCO 0/1/2 convention natively** (`0`=not
  labeled/OOF stored as `[0,0,0]`, `1`=occluded, `2`=visible). Mapping
  is the identity.
- Annotation coordinates are stored in the **annotated frame's pixel
  resolution** (the working-copy frame). `_jpeg_size(src)` returns that
  same resolution. So keypoints are already absolute pixels and
  `images[].width/height` = `_jpeg_size`.
- YOLO export names frames `f"{item['id']:06d}_{src.stem}{src.suffix}"`
  (e.g. `000726_f_000002.jpg`). COCO uses the **same** name.

## Output format (COCO Keypoints)

Each JSON has exactly three top-level keys: `images`, `annotations`,
`categories`.

### images[] — one per annotated frame
```json
{ "id": <int 1..N>, "file_name": "<stem>.jpg", "width": <int>, "height": <int> }
```
- `file_name` = `f"{item['id']:06d}_{src.stem}{src.suffix}"` (matches YOLO).
- `width`/`height` from `_jpeg_size(src)`.

### annotations[] — one per annotated infant (one per frame)
```json
{
  "id": <int, unique, != image_id>,
  "image_id": <int, references images[].id>,
  "category_id": 1,
  "keypoints": [x1,y1,v1, ..., x17,y17,v17],
  "num_keypoints": <count of v>0>,
  "bbox": [x, y, w, h],
  "area": <float w*h>,
  "iscrowd": 0
}
```
- `image_id` = the image's `id` (running index `i`, 1..N).
- `id` (annotation) = `i + 1_000_000` — a fixed offset so it is unique
  AND always differs from `image_id`. Documented in a comment.
- `keypoints`: 51 numbers = 17 `(x, y, v)` triples in COCO-17 order,
  **absolute pixels**, taken verbatim from the stored annotation
  (`v=0` points are `0,0,0`; occluded `x,y,1`; visible `x,y,2`).
- `num_keypoints`: count of triples with `v > 0`.
- `bbox` `[x, y, w, h]`, **absolute pixels**, top-left + size. Derived
  from the keypoints with `v > 0`: min/max x and y, padded ~12% on each
  side, clamped to `[0, width]` / `[0, height]`. Documented in a
  comment. (YOLO uses 10%; COCO uses 12% per the request.)
- `area` = bbox `w * h`. `iscrowd` = 0. `category_id` = 1.

### categories[] — fixed, emitted verbatim
```json
[{
  "id": 1, "name": "person", "supercategory": "person",
  "keypoints": ["nose","left_eye","right_eye","left_ear","right_ear",
    "left_shoulder","right_shoulder","left_elbow","right_elbow",
    "left_wrist","right_wrist","left_hip","right_hip",
    "left_knee","right_knee","left_ankle","right_ankle"],
  "skeleton": [[16,14],[14,12],[17,15],[15,13],[12,13],[6,12],[7,13],
    [6,7],[6,8],[7,9],[8,10],[9,11],[2,3],[1,2],[1,3],[2,4],[3,5],[4,6],[5,7]]
}]
```
(`skeleton` is 1-indexed, COCO convention — copied verbatim.)

Only annotated frames appear; un-annotated frames are skipped.

## Split = YOLO split, guaranteed

`coco_split` uses the same `train/val/test/seed` query params as
`yolo_split` and produces the identical per-frame assignment. This is
guaranteed structurally by sharing two extracted helpers (below), so
both exporters partition the **same ordered list of eligible items**
with the **same shuffle + floor** routine.

When `test == 0`: emit `train.json` + `val.json` only (val is the
catch-all), no `test.json` — same rule as `yolo_split`'s `data.yaml`.

Canonical comparison params for the paper: **70/20/10, seed 42**
(the defaults). Comparability holds for any params as long as the same
ones are used for both `yolo_split` and `coco_split`.

## Code changes

### Refactor in `backend/app/services/item.py` (behavior-preserving)

Extract two shared helpers; existing YOLO tests are the regression guard
(must stay green):

- `_eligible_pose_items(project_id, num_kpts) -> Iterator[tuple[dict, Path, int, int, list]]`
  — yields `(item, src, w, h, kps)` for each export-eligible item in
  `storage.list_items` order, applying the exact eligibility filter
  currently inside `_yolo_records` (has annotation; `len(kps) ==
  num_kpts`; `image_url` under `/files/`; src exists; `_jpeg_size` ok;
  at least one `v>0`). `_yolo_records` is rewritten to consume this and
  format the YOLO label line — its output stays byte-identical.
- `_partition(seq, train, val, test, seed) -> list[tuple[str, list]]`
  — the shuffle (`random.Random(seed)`) + floor partition currently
  inline in `build_yolo_split_export`, returning `[("train", [...]),
  ("val", [...]), ("test", [...])]` (test omitted when `test == 0`,
  val is the catch-all). `build_yolo_split_export` is rewritten to use
  it; output stays identical.

### New `backend/app/services/coco_export.py`

- `_COCO_CATEGORIES` — the fixed `categories` list above (module const).
- `_coco_image_and_annotation(i, item, src, w, h, kps) -> tuple[dict, dict]`
  — builds the `images[]` entry and `annotations[]` entry for one
  frame (filename, bbox 12% pad + clamp, keypoints flatten,
  num_keypoints, area, id offset).
- `build_coco_export(project_id) -> bytes` — JSON bytes of
  `{images, annotations, categories}` over all eligible items
  (`_eligible_pose_items`), `i` running 1..N.
- `build_coco_split_export(project_id, train, val, test, seed) -> tuple[BinaryIO, int]`
  — partitions the eligible items via `_partition`, builds one COCO
  JSON per split, writes `train.json`/`val.json`/`test.json` into a
  spooled ZIP (same 64 MiB spill pattern as YOLO). Per-split image ids
  restart at 1 (each JSON is self-contained).

### `backend/app/api/v1/items.py`

- Extend the `format` regex with `coco|coco_split`.
- `coco` branch: reject non-infant (num_kpts != 17) with **422**
  ("COCO export is only available for infant (17-keypoint) pose
  projects"); else return `build_coco_export` as a JSON download
  (`Content-Disposition` attachment `project_{id}_coco.json`,
  media type `application/json`).
- `coco_split` branch: same infant check; reuse the `train+val+test ==
  100` 422 check; stream `build_coco_split_export` via `_stream_zip` as
  `project_{id}_coco_split.zip`.

### Frontend

- `frontend/src/lib/download.ts`: widen `ExportFormat` with `coco` and
  `coco_split`; filename `project_{id}_coco.json` and
  `project_{id}_coco_split.zip`; send split params for `coco_split`
  (same rule as `yolo_split`).
- `frontend/src/pages/ProjectDetailPage.tsx`: add `coco` (JSON) and
  `coco_split` (ZIP) radio options for infant pose projects; the
  train/valid/test/seed split panel and the sum-100 download gate also
  apply when `coco_split` is selected. Use the project's
  `keypoint_schema` (infant) to decide whether to show the COCO
  options; if the field isn't available client-side, show them for pose
  projects and let the backend 422 guard rodent.

## Testing

Backend (`backend/tests/`), reusing existing helpers; add **pycocotools**
to the dev dependency group:

- **Loads with pycocotools:** build `coco` and each split JSON, write to
  a temp path, assert `pycocotools.coco.COCO(path)` constructs without
  error.
- **Structure:** exactly the 3 top-level keys; every annotation
  `keypoints` length 51 and `bbox` length 4; image ids and annotation
  ids unique and `> 0`; each annotation `id != image_id`;
  `num_keypoints` equals the count of `v>0`; `categories` equals the
  fixed constant verbatim.
- **Absolute pixels:** keypoint and bbox coordinates can exceed 1.0 and
  fall within `[0, width]` / `[0, height]`.
- **Split == YOLO split:** build `coco_split` and `yolo_split` over the
  same project with the same `train/val/test/seed`; map `file_name →
  split` from each (COCO via the three JSONs, YOLO via the
  `images/<split>/` paths) and assert the two maps are identical.
- **Infant-only:** a rodent project returns 422 for `coco` and
  `coco_split`.
- **Existing YOLO tests still pass** (regression guard for the
  `_yolo_records` / `build_yolo_split_export` refactor).

Frontend: no test suite — verify `npx tsc -b --noEmit` is clean and the
COCO options appear for infant pose projects.

## Example (one frame, illustrative)

```json
{
  "images": [
    { "id": 1, "file_name": "000726_f_000002.jpg", "width": 640, "height": 480 }
  ],
  "annotations": [
    {
      "id": 1000001, "image_id": 1, "category_id": 1,
      "keypoints": [320,180,2, 332,168,2, 308,168,2, 0,0,0, 296,172,1,
                    360,250,2, 280,250,2, 380,320,2, 260,320,1,
                    392,300,2, 250,300,2, 348,360,2, 292,360,2,
                    352,430,2, 288,430,2, 356,470,1, 286,470,2],
      "num_keypoints": 16,
      "bbox": [241.2, 152.4, 158.0, 350.6],
      "area": 55394.8,
      "iscrowd": 0
    }
  ],
  "categories": [ { "id": 1, "name": "person", "supercategory": "person",
    "keypoints": ["nose", "left_eye", "..."], "skeleton": [[16,14], "..."] } ]
}
```
(Numbers above are illustrative; the real exporter computes bbox/area
from the actual stored keypoints.)
