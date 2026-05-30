# Export flag `exclude_occluded` for YOLO-pose — design

**Date:** 2026-05-30
**Status:** Approved (pending spec review)

## Problem

In NeoLabel, an occluded keypoint is stored as `v=1` with real
coordinates ("you know where it is, it's just covered"). The YOLO-pose
export writes those points with their coordinates and visibility `1`,
and Ultralytics trains keypoint localization on every keypoint with
`v>0`. So occluded points become firm training targets — and in this
project they are producing strange post-training inference behavior.
We want an opt-in way to export a dataset where occluded keypoints are
**not** used as keypoint targets, so the user can A/B the two datasets.

## Goal

- Add an opt-in export flag that excludes occluded (`v=1`) keypoints
  from the **keypoint supervision** only.
- Keep it **off by default** — the standard COCO behavior is unchanged
  for existing callers.
- Apply to both `yolo` and `yolo_split` (they share one record
  generator).

## Non-goals

- No change to the bounding box. The box keeps using all `v>0` points
  (occluded + visible), preserving the subject's real extent. We are
  only removing keypoint supervision, not box supervision.
- No change to how occlusion is stored or annotated (still `v=1` with
  real coords on disk).
- No change to the other formats (`json`, `jsonl`, `csv`, `bundle`),
  which ignore the flag.
- No frame-skipping logic for all-occluded frames (see edge case).

## Behavior

With the flag **on**, for each exported frame's label line:

| Stored point | Flag off (current) | Flag on |
|---|---|---|
| Visible `v=2` | `x/w y/h 2` | `x/w y/h 2` (unchanged) |
| Occluded `v=1` | `x/w y/h 1` | `0.000000 0.000000 0` |
| OOF / unlabeled `v=0` | `0 0 0` | `0 0 0` (unchanged) |

The bounding box is computed from `visible_pts = [(x, y) for x, y, v
in kps if v > 0]` in **both** modes — occluded points still count
toward the box. The flag changes **only** the per-keypoint fields in
`kp_str`.

### Edge case

A frame whose only `v>0` points are occluded still yields a valid box
(occluded points are in `visible_pts`), so the item is not skipped.
Its label line carries the box plus all-`v=0` keypoints — box-only
supervision, no keypoint targets. This is acceptable and intentional;
we do not special-case it.

## API contract

```
GET /projects/{id}/export?format=yolo&exclude_occluded=true
GET /projects/{id}/export?format=yolo_split&train=70&val=20&test=10&seed=42&exclude_occluded=true
```

- New query param: `exclude_occluded: bool = Query(False)`.
- Applies to `format=yolo` and `format=yolo_split`. Ignored (harmless)
  for every other format.
- Default `false` → byte-identical to today's exports.

## Code changes

### Backend — `backend/app/services/item.py`

- `_yolo_records(project_id, num_kpts, exclude_occluded=False)` — add
  the keyword param. The only logic change is the keypoint-string
  construction. Replace the single `kp_str = ...` line with a form
  that, when `exclude_occluded` is true, emits `0.000000 0.000000 0`
  for any point with `v == 1` and the normal `x/w y/h v` otherwise.
  The `visible_pts`/bbox math is untouched.
- `build_yolo_export(project_id, exclude_occluded=False)` — add the
  param, pass it through to `_yolo_records`. Mention the flag in the
  README line when it's on (e.g. an extra line
  `Occluded keypoints (v=1): excluded from training`).
- `build_yolo_split_export(project_id, train, val, test, seed,
  exclude_occluded=False)` — add the param, pass it through to
  `_yolo_records`. Same README note when on.

### Backend — `backend/app/api/v1/items.py`

- Add `exclude_occluded: bool = Query(False)` to `export_project`.
- Pass it to `build_yolo_export(project_id, exclude_occluded)` and
  `build_yolo_split_export(project_id, train, val, test, seed,
  exclude_occluded)`.

### Frontend — `frontend/src/lib/download.ts`

- Add `excludeOccluded?: boolean` to `DownloadOptions`.
- In `downloadExport`, when `opts.excludeOccluded` is true **and** the
  format is `yolo` or `yolo_split`, add `exclude_occluded: true` to the
  request params. (Split params keep their existing `yolo_split`-only
  rule.)

### Frontend — `frontend/src/pages/ProjectDetailPage.tsx`

- New state: `const [excludeOccluded, setExcludeOccluded] =
  useState(false)`.
- A checkbox **"Excluir keypoints ocluídos (v=1) do treino"** rendered
  when `exportFormat === 'yolo' || exportFormat === 'yolo_split'`.
- `handleExport` forwards `excludeOccluded: (fmt === 'yolo' || fmt ===
  'yolo_split') ? excludeOccluded : undefined` to `downloadExport`.

## Testing

Backend (`backend/tests/test_items_api.py`, reusing existing helpers):

- **Occluded demotion + bbox preserved:** seed one pose item with 16
  visible (`v=2`) keypoints and 1 occluded (`v=1`) at a known
  position. Export `yolo` twice — without and with
  `exclude_occluded`. Assert:
  - without the flag, the occluded keypoint's triplet ends in ` 1`
    with non-zero normalized coords;
  - with the flag, that same keypoint is `0.000000 0.000000 0`;
  - the **bbox fields (`cx cy w h`) are identical** between the two
    label lines (proves occluded points still drive the box).
- **Endpoint honors the flag:** `GET ...?format=yolo&exclude_occluded=true`
  → 200, and no keypoint triplet in the label file has visibility `1`.
- **Split honors the flag:** `build_yolo_split_export(...,
  exclude_occluded=True)` over a small annotated set → no label across
  any split contains a `v=1` keypoint.
- **Default unchanged:** an export with no `exclude_occluded` param
  still emits `v=1` for occluded points (guards the default).

Frontend: no test suite — verify `npx tsc -b --noEmit` is clean and
that the checkbox appears only for `yolo`/`yolo_split` and gates the
param.
