# Video rotation after annotation — design

**Date:** 2026-06-04
**Status:** Approved (pending spec review)

## Problem

Some videos were uploaded without the rotation they needed (the rotation is
chosen at upload time and baked into the extracted frames). Once frames are
extracted and annotated, there is currently no way to fix the orientation
without re-uploading and losing all annotation work.

We want a **per-video** action, available **after** annotation, that rotates
every extracted frame of a video and keeps the existing annotations aligned.

## Decisions (from brainstorming)

- **Approach:** rotate the already-extracted frame JPGs *in place* and
  transform the existing keypoint coordinates. Preserves item IDs and all
  annotation work. (Rejected alternative: re-extract from the stored original —
  higher quality but destroys/remaps annotations by `frame_index`; too risky.)
- **Angles:** 90° clockwise, 90° counter-clockwise, 180°. Successive
  applications are cumulative (90° CW ×2 = 180°; ×4 = original).
- **Permission:** admin only — matches the other bulk video operations
  (delete video, reassign), which use the `AdminUser` gate.

## Background (current state)

- Frames are always **640×640** (`_TARGET_SIZE`); upload letterboxes (`pad`)
  or stretches the source into that square. So for video frames a rotation
  never changes dimensions. (We still handle non-square generically — see
  below — so the logic is correct for any image.)
- Rotation already exists at **upload** time via ffmpeg `transpose`
  (`backend/app/services/video.py::_rotation_filter`): `90 → transpose=1`
  (clockwise), `180 → transpose=1,transpose=1`, `270 → transpose=2`
  (counter-clockwise). The post-hoc feature reuses the same convention so
  `90 = clockwise`.
- Annotations are stored as `{"keypoints": [[x, y, v], ...]}` with absolute
  pixel coordinates, one file per `{item_id}__{annotator_id}.json` under
  `projects/<pid>/annotations/`. Unset keypoints use the `[0, 0, 0]`
  convention (`v == 0`).
- Frame files: `projects/<pid>/frames/<source_video>/f_%06d.jpg`.
- The stored original video lives in `projects/<pid>/_videos/<name>.<ext>` and
  is **not** touched by this feature.
- **Pillow is intentionally not a dependency** — image work uses ffmpeg
  (already on PATH).

## API

```
POST /projects/{project_id}/videos/{source_video}/rotate
body: { "degrees": 90 | 180 | 270 }     # 90 = clockwise, 270 = counter-clockwise
->   { "rotated": <number of frames>, "degrees": <int> }
```

- Gate: `AdminUser`.
- `404` if the project doesn't exist or the `source_video` has no frames in
  the project (mirrors `reassign_video` / `delete_video`).
- `422` if `degrees` not in `{90, 180, 270}`.

Schema: add `RotateRequest { degrees: int }` to `schemas/item.py` (or reuse a
literal in the router). Validate `degrees ∈ {90,180,270}`.

## Service logic — `video.rotate_video(project_id, source_video, degrees)`

Core pure function (no ffmpeg, fully unit-testable):

```python
def rotate_keypoints(kps, w, h, degrees):
    """Return (new_kps, new_w, new_h). 90 = clockwise.
    Points with v == 0 are left untouched (preserves the [0,0,0] unset
    convention). Coordinates for v > 0 map as:
        90  (CW):  x' = h - y,  y' = x      ; new dims (h, w)
        270 (CCW): x' = y,      y' = w - x  ; new dims (h, w)
        180:       x' = w - x,  y' = h - y  ; new dims (w, h)
    """
```

`rotate_video` orchestration (two-phase commit for safety):

1. Collect the video's items: `payload.source_video == source_video`. If none,
   raise → router returns 404.
2. Compute new annotation values **in memory** for every item that has an
   annotation (`rotate_keypoints` on `value["keypoints"]`; other keys in
   `value` are left untouched). This phase cannot fail.
3. Rotate all frame JPGs with a **single** ffmpeg call over the image
   sequence into a temp dir:
   `ffmpeg -y -i frames/<v>/f_%06d.jpg -vf <transpose> <tmpdir>/f_%06d.jpg`
   where `<transpose>` is `transpose=1` (90), `transpose=1,transpose=1` (180),
   `transpose=2` (270). If ffmpeg fails, abort — nothing on disk has changed
   yet (temp dir only).
4. **Commit:** `os.replace` each temp frame over the original (fast, atomic per
   file), then for each item update `payload.width`/`payload.height` (swap on
   90/270) and bump `payload.frame_rev` (int, default 0) by 1; `save_item`.
   Then `save_annotation` for each recomputed annotation.
5. Clean up the temp dir. Return `{"rotated": len(items), "degrees": degrees}`.

Notes:
- Scope is the video frame group only (items with `source_video` + frames on
  disk). COCO-imported standalone images are not exposed in the Videos table
  and are out of scope.
- Status is irrelevant — pending/in-progress/done/reviewed frames are all
  rotated; only items that actually have an annotation get coordinate
  transforms.
- Storage writes are already atomic (single I/O gate).

## Cache-busting

The frame URL (`/files/.../f_000001.jpg`) is unchanged but its bytes change,
so the browser would show the stale image.

- Backend: `payload.frame_rev` (int) is bumped on every rotation.
- Frontend: append `?r=<frame_rev>` to frame image URLs wherever a frame is
  rendered — the Videos table thumbnails and the pose annotation view. A small
  helper (e.g. in `lib/`) centralizes "frame URL + rev". Items/videos with no
  `frame_rev` render without the param (back-compat).
- After a successful rotate, invalidate `['items', projectId]` and the videos
  query so counts/thumbnails refetch.

## UI

In the **Videos** table (both list and grid views), per row, add three small
buttons next to the existing reassign/approve/delete controls:

- ↻ 90° clockwise (`degrees: 90`)
- ↺ 90° counter-clockwise (`degrees: 270`)
- ⟳ 180° (`degrees: 180`)

Behavior:
- Confirmation dialog: "Rotate all N frames of \"<video>\" and adjust their
  annotations. This re-renders the frames." (reuse the existing confirm
  modal used by approve-all / delete-video).
- Per-row spinner while in flight (reuse the `approvingVideo`-style pattern,
  e.g. `rotatingVideo` state) so only the active row shows progress.
- Result toast: "Rotated N frames."
- `api/videos.ts` (or `api/items.ts`, matching where reassign lives): add
  `rotateVideo(projectId, sourceVideo, degrees)`.

## Testing

Backend, in a new `tests/test_video_rotate.py` (or appended to an existing
video test module):

- **Pure unit (`rotate_keypoints`), no ffmpeg:**
  - 90° CW, 270° CCW, 180° each map a known point correctly.
  - `v == 0` keypoints are left as `[0, 0, 0]`.
  - width/height swap on 90/270, unchanged on 180.
  - idempotency: applying 90° four times returns the original keypoints.
- **Integration (endpoint, ffmpeg available):**
  - Seed a video group by generating a small **non-square** test JPG via
    ffmpeg `lavfi` (e.g. 320×240) written into the frames dir with a matching
    item, annotate it, call rotate 90°, then assert: response `rotated`/`degrees`,
    `payload.width`/`height` swapped (read back via the existing JPEG SOF
    dimension reader in `item.py`), `frame_rev` bumped, and keypoints
    transformed.
  - `404` when the video isn't in the project.
  - admin-only: non-admin (owner) gets `404`/`403` per the gate's convention.

Frontend: typecheck (`npx tsc -b --noEmit`) — no frontend test suite exists.

## Out of scope

- Rotating the stored original `_videos/*` file.
- Re-extraction / re-letterboxing from the original.
- Rotating non-video (COCO-imported standalone) images.
- Arbitrary (non-90°) angles.
