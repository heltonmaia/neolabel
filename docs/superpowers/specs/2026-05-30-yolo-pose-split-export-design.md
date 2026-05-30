# YOLO-pose export with train/val/test split — design

**Date:** 2026-05-30
**Status:** Approved (pending spec review)

## Problem

The YOLO-pose export (`format=yolo`) dumps every annotated frame into a
single `images/train/` + `labels/train/` directory, and `data.yaml`
points both `train:` and `val:` at that same folder. Users training a
model want a standard YOLO dataset already partitioned into
`train` / `val` / `test`, produced from a reproducible random shuffle
so a given seed always yields the same split.

## Goals

- Add a **separate** export option that produces a train/val/test split.
- Ratios and the random seed are **user-configurable** (defaults
  70 / 20 / 10, seed 42).
- The split is **reproducible**: same seed + same eligible frames →
  identical assignment.
- Use the **Ultralytics** folder layout (consistent with the existing
  flat export).
- Leave the existing flat `yolo` export unchanged.

## Non-goals

- No stratification (pose export has a single class, so there is
  nothing to stratify on).
- No guarantee that every split is non-empty. With a tiny dataset, a
  floor-based partition may leave `val` or `test` empty; that is
  acceptable.
- No change to the other export formats (`json`, `jsonl`, `csv`,
  `bundle`).

## API contract

```
GET /projects/{project_id}/export
    ?format=yolo_split
    &train=70 &val=20 &test=10   # integers, each >= 0
    &seed=42                     # integer
```

- `format` regex gains `yolo_split`:
  `^(json|jsonl|csv|yolo|bundle|yolo_split)$`.
- The four new query params apply **only** to `yolo_split`; they are
  ignored for every other format.
- Validation (returns **422** on failure):
  - `train + val + test == 100`
  - each of `train`, `val`, `test` `>= 0`
- Like `yolo`, the split export is **annotated-only** (unannotated
  frames have no labels).

Downloaded filename: `project_{project_id}_yolo_split.zip`.

## Output structure (Ultralytics layout)

```
data.yaml
images/train/<stem>.jpg
images/val/<stem>.jpg
images/test/<stem>.jpg        # omitted entirely when test == 0
labels/train/<stem>.txt
labels/val/<stem>.txt
labels/test/<stem>.txt        # omitted entirely when test == 0
README.txt
```

`data.yaml` (no `path:` key — same rationale as the existing export,
so Ultralytics resolves relative paths against the yaml's own parent):

```yaml
# YOLO-pose dataset (<schema_label>)
train: images/train
val: images/val
test: images/test            # line omitted when test == 0
kpt_shape: [<num_kpts>, 3]
flip_idx: <flip_idx>
names:
  0: <class_name>
```

`<stem>`, the per-item label line (`0 cx cy w h  x1 y1 v1 ...`), bbox
padding, normalization, visibility filtering, and the schema selection
(`infant` 17 COCO kpts / `rodent` 7 kpts) are **identical** to the
existing flat export.

`README.txt` reports project id, schema label, the seed and ratios
used, and the per-split frame counts.

## Split algorithm

1. Collect the **eligible** items in the same order
   `build_yolo_export` already iterates them — i.e. only items that
   pass every existing filter (has annotation, correct keypoint count,
   `image_url` under `/files/`, source file exists, JPEG dims
   readable, at least one visible keypoint). Each eligible item is
   reduced to its `(src_path, stem, label_line)` record.
2. Shuffle the eligible list with `random.Random(seed)` (a local RNG
   instance — never the global `random` module, so the result is
   deterministic and isolated).
3. Partition by floor counts on the shuffled list:
   - `n_train = floor(n * train / 100)`
   - `n_val   = floor(n * val   / 100)`
   - `test` gets the remainder (`n - n_train - n_val`).
   This guarantees every eligible frame lands in exactly one split.
4. Write each record into `images/<split>/` + `labels/<split>/`.

## Code changes

### Backend

`backend/app/services/item.py`

- **Refactor (no behavior change):** extract the shared pieces out of
  `build_yolo_export` so the flat and split builders can reuse them:
  - `_yolo_schema_meta(project)` → `(num_kpts, flip_idx, class_name,
    schema_label)`.
  - a generator that yields the eligible `(src_path, stem,
    label_line)` records for a project (the body of the current
    per-item loop). `build_yolo_export` is rewritten to consume it and
    write everything into `train`, producing byte-identical output to
    today.
- **New:** `build_yolo_split_export(project_id, train, val, test,
  seed) -> tuple[BinaryIO, int]` — collects records, shuffles with
  `random.Random(seed)`, partitions, writes the split layout + a
  `data.yaml` whose `test:` key (and the test folders) are present
  only when `test > 0`. Same `SpooledTemporaryFile(max_size=64 MiB)`
  spill-to-disk strategy as the flat export.

`backend/app/api/v1/items.py`

- Extend the `format` regex with `yolo_split`.
- Add `train: int = Query(70, ge=0, le=100)`, `val`, `test`,
  `seed: int = Query(42)` query params.
- Branch: when `format == "yolo_split"`, validate the ratio sum
  (raise `HTTPException(422)` if `!= 100`), call
  `build_yolo_split_export`, stream via the existing `_stream_zip`
  with filename `project_{id}_yolo_split.zip`.

### Frontend

`frontend/src/api/items.ts` — widen the export format type to include
`yolo_split`.

`frontend/src/lib/download.ts` — when `format === 'yolo_split'`, append
`train/val/test/seed` query params and name the file
`project_{id}_yolo_split.zip`. Widen the `ExportFormat` union.

`frontend/src/pages/ProjectDetailPage.tsx`

- Add a radio option **"YOLO-pose (train/valid/test split)"**
  (value `yolo_split`) under the existing flat YOLO option.
- When `yolo_split` is selected, reveal four number inputs:
  **train %, valid %, test %, seed** (defaults 70 / 20 / 10 / 42).
- Show a live sum hint; **disable the download button** while the
  three percentages don't sum to 100.
- Pass the ratios + seed through `handleExport` → `downloadExport`.
- Update the `'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle'` unions in
  this file to include `'yolo_split'`.

### SPEC.md

Per repo convention (update SPEC before changing behavior), document
the new `yolo_split` format and its query params in the export section
of `SPEC.md` as part of the implementation.

## Testing

Backend (`backend/tests/`, pytest + TestClient, isolated `DATA_DIR`):

- Sum of the three split counts equals the flat export's exported
  count (same eligibility filter).
- Same seed → identical per-frame split assignment across two calls;
  a different seed generally differs.
- `test=0` → no `images/test/` or `labels/test/` entries and no
  `test:` key in `data.yaml`.
- Ratio sum `!= 100` → 422.
- Tiny dataset (e.g. 3 eligible frames at 70/20/10) does not crash and
  partitions without loss (every frame placed exactly once).
- `data.yaml` for the split contains `train: images/train` /
  `val: images/val` and the correct `kpt_shape` for the project
  schema.

Frontend: no test suite (lint + typecheck only) — verify the union
types compile and the modal gates the download button on a 100 sum.
