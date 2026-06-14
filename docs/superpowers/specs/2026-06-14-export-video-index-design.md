# Export video index (per-video frame boundaries) — design

**Date:** 2026-06-14
**Status:** Approved (pending spec review)

## Problem

The flat dataset exports (notably YOLO-pose) flatten every video's frames into
a single folder of files named `{item_id:06d}_{f_NNNNNN}.jpg`. Once unzipped,
there is no easy way to tell **which frames belong to which source video**, or
where a given video's frames start and end. A user training per-video or
auditing coverage has to reconstruct that mapping by hand.

We want an **opt-in flag** on export that adds a small manifest file describing,
per source video, the first and last frame and the frame count actually present
in that export.

## Decisions (from brainstorming)

- **Scope:** all **flat** export formats — `yolo`, `bundle`, `coco`, `json`,
  `jsonl`, `csv`. **Not** the split formats (`yolo_split`, `coco_split`): there
  a video's frames scatter across train/val/test, so a per-video boundary file
  is ambiguous. (Rejected: limiting to `yolo`/`bundle`/`coco` only — the user
  wants it on every flat format for a single consistent mental model.)
- **Delivery:** the manifest is a separate file, so it needs a container.
  `yolo`/`bundle` are already ZIPs → just add an entry. `coco`/`json`/`jsonl`/
  `csv` are single-file responses → when the flag is on they are **wrapped in a
  ZIP** containing the native file + `video_index.csv`. Turning the flag on
  therefore changes those four downloads from `.json`/`.csv`/etc. to `.zip`.
  This is the only honest way to deliver two files.
- **Format:** one CSV (`video_index.csv`). Universally readable, uniform across
  all six formats.
- **Default off.** With the flag off, every export is **byte-identical** to
  today. This invariant is guarded by tests.

## Background (current state)

- Frames are extracted as `projects/<pid>/frames/<source_video>/f_%06d.jpg`
  (`video.extract_frames`). The stem `f_000123` is the 1-based **extracted-frame
  index** (extraction applies an fps filter, so this is the sampled-frame
  ordinal, not necessarily the original video frame number).
- `payload.source_video` holds the sanitized video name; `payload.image_url`
  is `/files/projects/<pid>/frames/<source_video>/f_NNNNNN.jpg`.
- Items are stored/listed in **id order** (upload order), and a video's frames
  are created in one batch, so a video's frames form a contiguous block in the
  export (minus gaps where frames weren't annotated).
- Export response shapes today (`api/v1/items.py::export_project`):
  - `yolo`, `bundle`, `yolo_split`, `coco_split` → ZIP (`_stream_zip`).
  - `coco` → single `application/json` `Response`.
  - `json`/`jsonl`/`csv` → streamed single file (`StreamingResponse`).
- Membership per flat format (which items contribute a frame):
  - `yolo`, `coco` → `item.eligible_pose_items(project_id, num_kpts)` (annotated,
    valid keypoint count, frame on disk, ≥1 visible kp). `coco` uses
    `_NUM_KPTS == 17`; both build their files from this exact stream.
  - `bundle`, `json`, `jsonl`, `csv` → **all** items (pending rows included);
    for the index we count only rows that reference a frame (`image_url` present).

## CSV format — `video_index.csv`

```
source_video,first_frame,last_frame,num_frames
parto_01,1,250,250
parto_02,3,180,140
```

- `source_video` — `payload.source_video`; empty string for items without one
  (e.g. COCO-imported standalone images), bucketed together.
- `first_frame` / `last_frame` — the smallest / largest frame number present
  for that video in **this** export, parsed as `int` from the stem `f_<digits>`.
  If a stem doesn't match `f_<digits>`, fall back to the raw stem string. Sort
  key is `(0, int)` for numeric stems and `(1, stem)` otherwise, so min/max are
  well-defined even with mixed/imported data.
- `num_frames` — count of that video's frames present in this export. Because
  `yolo`/`coco` are annotated-only, `num_frames` can be **less** than
  `last_frame - first_frame + 1` (gaps are expected and intentional).
- Row order — first appearance of each `source_video` in the export's item
  stream (matches the contiguous block order in the files).

## Service logic (`backend/app/services/item.py`)

Two small, pure, independently testable helpers + per-builder collection.

```python
def _frame_ref(payload: dict) -> tuple[str, str] | None:
    """(source_video or "", frame_stem) for a payload that references a frame,
    else None. frame_stem = Path(image_url).stem, e.g. "f_000123"."""

def build_video_index_csv(pairs: Iterable[tuple[str, str]]) -> str:
    """Aggregate (source_video, frame_stem) pairs into the CSV text above:
    per source_video → first_frame, last_frame, num_frames; rows ordered by
    first appearance. Pure; no I/O."""
```

A shared ZIP helper wraps single-file outputs:

```python
def zip_bytes(entries: list[tuple[str, bytes]]) -> tuple[BinaryIO, int]:
    """Spooled (64 MiB) ZIP_DEFLATED archive from in-memory (name, bytes)
    entries; returns (file-at-0, size). Caller closes."""
```

**Collect membership during the write** (divergence-proof — the index always
reflects exactly what was emitted):

- `build_yolo_export(project_id, exclude_occluded=False, video_index=False)`:
  `_yolo_records` is extended to also surface `source_video` (it already has the
  `item` in scope). The builder accumulates `(source_video, src.stem)` per
  written record and, when `video_index`, writes `video_index.csv` into the zip.
  `build_yolo_split_export` unpacks the widened tuple and ignores the new field.
  ZIP name unchanged (`project_<id>_yolo.zip`).
- `build_bundle_export(project_id, video_index=False)`: accumulate
  `_frame_ref(payload)` for each item whose payload references a frame
  (`_frame_ref` non-None) — same membership rule as `json`/`jsonl`/`csv`; when
  `video_index`, write `video_index.csv` into the zip. Name unchanged.
- `coco`: `build_coco_export` stays pure (returns the JSON bytes). The
  **endpoint** computes the pairs from `eligible_pose_items(project_id,
  _NUM_KPTS)` (the same stream `build_coco_export` consumes, so the index ==
  the json's `images[]`), then `zip_bytes([("project_<id>_coco.json", json),
  ("video_index.csv", csv)])`.
- `json`/`jsonl`/`csv`: a new single-pass
  `build_text_export_zip(project_id, fmt) -> (BinaryIO, int)` iterates
  `_iter_export_rows` **once**, building the native body (array / lines / csv
  via the existing serialization) **and** collecting `_frame_ref(row["payload"])`
  pairs, then `zip_bytes([("project_<id>.<ext>", body), ("video_index.csv",
  csv)])`. (Streaming is given up only when the flag is on, which is fine — the
  other ZIP exports already spool.)

### Optional polish

Where a README already exists in the archive (`yolo`, `bundle`), append one
line noting `video_index.csv` and its columns when the flag is on.

## API (`backend/app/api/v1/items.py::export_project`)

Add `video_index: bool = Query(False)`.

- Honored only for the six flat formats above. On `yolo_split` / `coco_split`
  it is **silently ignored** (mirrors how `exclude_occluded` is ignored on
  non-YOLO formats) — the UI hides the checkbox there anyway.
- Dispatch when `video_index` is on:
  - `yolo` → `build_yolo_export(..., video_index=True)` → `_stream_zip(...,
    "project_<id>_yolo.zip")` (unchanged name).
  - `bundle` → `build_bundle_export(project_id, video_index=True)` → same name.
  - `coco` → `zip_bytes([...])` → `_stream_zip(..., "project_<id>_coco.zip")`.
  - `json`/`jsonl`/`csv` → `build_text_export_zip(...)` → `_stream_zip(...,
    "project_<id>_<fmt>.zip")`.
- When `video_index` is off: every branch is exactly as today.

No schema/enum changes; the `format` query pattern is unchanged.

## Frontend

`src/lib/download.ts`:
- Add `videoIndex?: boolean` to `DownloadOptions`. When set, add
  `video_index: true` to `params`.
- Download filename: when `videoIndex` is on **and** format ∈ `{coco, json,
  jsonl, csv}`, override `a.download` to `project_<id>_<fmt>.zip` (coco →
  `project_<id>_coco.zip`). `yolo`/`bundle` already resolve to `.zip` — unchanged.

`src/pages/ProjectDetailPage.tsx` export modal:
- Add `videoIndex` boolean state; render a checkbox *"Incluir índice de vídeos
  (início/fim dos frames por vídeo)"*.
- Show the checkbox only for flat formats (hide for `yolo_split` / `coco_split`).
- Pass `videoIndex` through to `downloadExport`.

## Testing (`backend/tests/`)

New cases (extend `test_items_api.py` / `test_coco_export.py`, or a new
`test_export_video_index.py`):

- **Manifest correctness (unit-ish):** a project with 2 source videos and
  sparse annotations → `first_frame`/`last_frame` are the min/max present and
  `num_frames` equals the count present (gaps do not inflate it); rows ordered
  by first appearance.
- **yolo + `video_index`:** zip contains `video_index.csv`; its per-video
  `num_frames` match the seeded per-video annotated-frame counts, and the sum
  of `num_frames` across rows equals the number of `labels/train/*.txt` files
  (the filename `{id}_{f_NNNNNN}` doesn't carry the video, so map via seeded
  data, not the filenames).
- **Flag-off invariant:** `yolo` (and `csv`) without the flag contain **no**
  `video_index.csv` and are otherwise unchanged.
- **json + `video_index`:** response is a ZIP containing `project_<id>.json`
  (parses, equals the streamed-body rows) **and** `video_index.csv`.
- **csv + `video_index`:** ZIP with inner `project_<id>.csv` + manifest.
- **coco + `video_index`:** ZIP with `project_<id>_coco.json` (valid COCO) +
  manifest; manifest row count == distinct videos among the COCO `images[]`.
- **split formats ignore the flag:** `yolo_split?video_index=true` is a normal
  split zip with **no** `video_index.csv`.
- **Robustness:** an item with no `source_video` / a non-`f_NNNNNN` stem
  (COCO-imported shape) is bucketed without raising.

Frontend: typecheck (`npx tsc -b --noEmit`) — no frontend test suite exists.

## Out of scope

- Split formats (`yolo_split`, `coco_split`).
- Any change to flag-off output (must stay byte-identical).
- Per-frame metadata beyond first/last/count (e.g. full per-file listing,
  timestamps, original video frame numbers).
- Exposing the index through the unauthenticated `/files/` media route.
