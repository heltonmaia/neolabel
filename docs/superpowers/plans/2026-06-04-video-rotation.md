# Video Rotation After Annotation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin rotate every extracted frame of one video (90° CW, 90° CCW, or 180°) after annotation, transforming the existing keypoint coordinates so they stay aligned.

**Architecture:** A new admin-only endpoint `POST /projects/{id}/videos/{source}/rotate` calls a `video.rotate_video` service. The service computes new keypoint coordinates in memory (pure `rotate_keypoints` helper), rotates all frame JPGs in one ffmpeg pass into a temp dir, then commits atomically (`os.replace` each frame, bump `payload.frame_rev`, swap width/height on 90/270, save annotations). The frontend adds three per-row buttons in the Videos table and cache-busts frame images via `?r=<frame_rev>`.

**Tech Stack:** FastAPI + Pydantic v2 (backend), ffmpeg (`transpose`), filesystem JSON storage, React + TanStack Query + TypeScript (frontend).

**Spec:** `docs/superpowers/specs/2026-06-04-video-rotation-post-annotation-design.md`

**Conventions:** `90 = clockwise`, `270 = counter-clockwise` (matches `extract_frames`). Frames are 640×640 for video, but the logic handles any `width`/`height`. Keypoints with `v == 0` (`[0,0,0]` unset) are left untouched. ffmpeg only — no Pillow. Commit messages on this repo carry **no** `Co-Authored-By` trailer.

**Test commands (native venv fallback — Docker not running):**
```bash
cd backend
export UV_CACHE_DIR=/mnt/hd3/uv-cache
source /mnt/hd3/uv-common/uv-neo-label/bin/activate
python -m pytest <path> -q
```
Frontend typecheck: `cd frontend && npx tsc -b --noEmit`

---

## File structure

- Modify `SPEC.md` — document the rotate endpoint (source of truth; update first).
- Modify `backend/app/services/video.py` — add `rotate_keypoints` (pure) and `rotate_video` (orchestration).
- Modify `backend/app/schemas/item.py` — add `RotateRequest`.
- Modify `backend/app/api/v1/videos.py` — add the rotate route.
- Create `backend/tests/test_video_rotate.py` — unit + integration tests.
- Modify `frontend/src/api/videos.ts` — add `rotateVideo`.
- Create `frontend/src/lib/frameUrl.ts` — cache-busting frame URL helper.
- Create `frontend/src/features/projects/VideoRotateButtons.tsx` — the 3-button control.
- Modify `frontend/src/pages/ProjectDetailPage.tsx` — wire mutation + buttons, switch frame `<img>` srcs to `frameUrl`.
- Modify `frontend/src/pages/PoseAnnotatePage.tsx` — switch the frame `<img>` src to `frameUrl`.

---

## Task 1: Document the endpoint in SPEC.md

**Files:**
- Modify: `SPEC.md:225` (in the "Videos (pose projects)" list, after the `/assign` entry)

- [ ] **Step 1: Add the rotate endpoint to the API contract**

Insert this bullet immediately after the `PATCH .../assign` entry (currently ending at line 227, before the `DELETE` entry):

```markdown
- `POST   /projects/{id}/videos/{source}/rotate` — admin-only; rotates
  every extracted frame of the video in place and transforms the
  existing keypoint annotations to match. Body `{"degrees": 90|180|270}`
  where `90` is clockwise and `270` counter-clockwise (same convention
  as upload `rotation`). Frame files are re-rendered with FFmpeg
  `transpose`; each item's `payload.frame_rev` is bumped (cache-busting)
  and `width`/`height` are swapped on 90/270. Returns
  `{"rotated": <frame count>, "degrees": <int>}`. 404 if the video has
  no frames in the project; 422 if `degrees` is not 90/180/270.
```

- [ ] **Step 2: Commit**

```bash
git add SPEC.md
git commit -m "docs(spec): video rotate endpoint"
```

---

## Task 2: Pure `rotate_keypoints` helper (no ffmpeg)

**Files:**
- Modify: `backend/app/services/video.py` (add function near `_rotation_filter`)
- Test: `backend/tests/test_video_rotate.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_video_rotate.py`:

```python
"""Video rotation — coordinate transform + endpoint."""
from app.services.video import rotate_keypoints


def test_rotate_90_clockwise_maps_point_and_swaps_dims():
    # point (10, 20) in a 100w x 200h image
    kps = [[10, 20, 2]]
    new_kps, w, h = rotate_keypoints(kps, 100, 200, 90)
    assert new_kps == [[180, 10, 2]]  # x'=h-y=180, y'=x=10
    assert (w, h) == (200, 100)


def test_rotate_270_counter_clockwise():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 270)
    assert new_kps == [[20, 90, 2]]  # x'=y=20, y'=w-x=90
    assert (w, h) == (200, 100)


def test_rotate_180_keeps_dims():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 180)
    assert new_kps == [[90, 180, 2]]  # x'=w-x=90, y'=h-y=180
    assert (w, h) == (100, 200)


def test_unset_keypoints_are_untouched():
    # v == 0 means "unset" ([0,0,0]); must not be moved.
    new_kps, _, _ = rotate_keypoints([[0, 0, 0], [10, 20, 2]], 100, 200, 90)
    assert new_kps[0] == [0, 0, 0]


def test_four_90_rotations_return_original_square():
    kps = [[100, 50, 2], [600, 10, 1]]
    cur, w, h = kps, 640, 640
    for _ in range(4):
        cur, w, h = rotate_keypoints(cur, w, h, 90)
    assert cur == kps
    assert (w, h) == (640, 640)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_video_rotate.py -q`
Expected: FAIL — `ImportError: cannot import name 'rotate_keypoints'`

- [ ] **Step 3: Implement `rotate_keypoints`**

In `backend/app/services/video.py`, add after `_rotation_filter` (around line 52):

```python
def rotate_keypoints(
    kps: list, w: int, h: int, degrees: int
) -> tuple[list, int, int]:
    """Transform keypoints for an image rotation. `90` is clockwise, `270`
    counter-clockwise (matches the upload `rotation` convention).

    Returns (new_kps, new_w, new_h). Keypoints with visibility 0 (the
    `[0,0,0]` "unset" convention) are passed through unchanged so they
    keep reading as unset. Width/height swap on 90/270.
    """
    out: list = []
    for kp in kps:
        if len(kp) < 3 or kp[2] == 0:
            out.append(list(kp))
            continue
        x, y, v = kp[0], kp[1], kp[2]
        if degrees == 90:
            nx, ny = h - y, x
        elif degrees == 270:
            nx, ny = y, w - x
        else:  # 180
            nx, ny = w - x, h - y
        out.append([nx, ny, v])
    if degrees in (90, 270):
        return out, h, w
    return out, w, h
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_rotate.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/video.py backend/tests/test_video_rotate.py
git commit -m "feat(video): rotate_keypoints coordinate transform"
```

---

## Task 3: `rotate_video` service (ffmpeg frames + commit)

**Files:**
- Modify: `backend/app/services/video.py` (add `rotate_video`; ensure `import os`, `import tempfile`)
- Test: `backend/tests/test_video_rotate.py` (append)

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/test_video_rotate.py`:

```python
import subprocess
from pathlib import Path

import pytest

from app.core import storage
from app.services import video as video_service


def _make_frame(pdir: Path, video: str, w: int, h: int):
    """Render one solid-color non-square JPG into the video's frames dir."""
    frames_dir = pdir / "frames" / video
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = frames_dir / "f_000001.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=red:s={w}x{h}", "-frames:v", "1", str(out)],
        check=True,
    )
    return out


def test_rotate_video_swaps_dims_and_transforms_annotation(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    pdir = storage.project_dir(pid)
    frame_path = _make_frame(pdir, "clip", 320, 240)
    assert video_service._jpeg_size_for_test(frame_path) == (320, 240)

    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/clip/f_000001.jpg",
                    "source_video": "clip", "frame_index": 1,
                    "width": 320, "height": 240},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    storage.save_annotation(pid, {
        "id": storage.next_id("annotations"), "item_id": iid, "annotator_id": 1,
        "value": {"keypoints": [[50, 60, 2], [0, 0, 0]]},
        "created_at": "2026-06-04T00:00:00Z", "updated_at": "2026-06-04T00:00:00Z",
    })

    n = video_service.rotate_video(pid, "clip", 90)
    assert n == 1

    item = storage.load_item(pid, iid)
    assert (item["payload"]["width"], item["payload"]["height"]) == (240, 320)
    assert item["payload"]["frame_rev"] == 1
    assert video_service._jpeg_size_for_test(frame_path) == (240, 320)

    ann = storage.find_any_annotation_for_item(pid, iid)
    # 90° CW in 320x240: (50,60) -> (h-y, x) = (180, 50); unset stays [0,0,0]
    assert ann["value"]["keypoints"] == [[180, 50, 2], [0, 0, 0]]


def test_rotate_video_missing_video_returns_zero(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot2", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    assert video_service.rotate_video(pid, "nope", 90) == 0


def test_rotate_video_rejects_bad_degrees(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot3", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    with pytest.raises(ValueError):
        video_service.rotate_video(pid, "clip", 45)
```

Note: `_jpeg_size_for_test` is a thin public alias added in Step 3 so the test
can reuse the existing private `item._jpeg_size` reader without importing a
private name across modules.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_video_rotate.py -q`
Expected: FAIL — `AttributeError: module 'app.services.video' has no attribute 'rotate_video'`

- [ ] **Step 3: Implement `rotate_video` (+ test helper)**

In `backend/app/services/video.py`, add `os` and `tempfile` to the imports at the top (after `import subprocess`):

```python
import os
import tempfile
```

Then add these functions (after `rotate_keypoints`):

```python
def _jpeg_size_for_test(path: Path) -> tuple[int, int] | None:
    """Public alias of item._jpeg_size, for tests asserting rotated dims."""
    from app.services.item import _jpeg_size
    return _jpeg_size(path)


def rotate_video(project_id: int, source_video: str, degrees: int) -> int:
    """Rotate every extracted frame of `source_video` in place and transform
    the existing keypoint annotations to match. `90` = clockwise.

    Two-phase commit: render all frames into a temp dir first; only if every
    frame succeeds do we replace the originals and persist metadata, so a
    mid-way ffmpeg failure leaves the data untouched.

    Returns the number of frames rotated (0 if the video has no frames).
    Raises ValueError on bad `degrees`.
    """
    if degrees not in (90, 180, 270):
        raise ValueError("degrees must be 90, 180, or 270")

    items = [
        i for i in storage.list_items(project_id)
        if (i.get("payload") or {}).get("source_video") == source_video
    ]
    if not items:
        return 0

    pdir = storage.project_dir(project_id)
    frames_dir = pdir / "frames" / source_video
    frames = sorted(frames_dir.glob("f_*.jpg"))
    if not frames:
        return 0

    transpose = _rotation_filter(degrees)  # never None for 90/180/270

    # Phase A — compute new annotation values in memory (cannot fail).
    new_anns: list[dict] = []
    for it in items:
        ann = storage.find_any_annotation_for_item(project_id, it["id"])
        if not ann:
            continue
        value = ann.get("value") or {}
        kps = value.get("keypoints")
        if not kps:
            continue
        p = it.get("payload") or {}
        w = p.get("width") or _TARGET_SIZE
        h = p.get("height") or _TARGET_SIZE
        new_kps, _, _ = rotate_keypoints(kps, w, h, degrees)
        new_anns.append({**ann, "value": {**value, "keypoints": new_kps}})

    # Phase B — render all frames into a temp dir under frames/ (same FS so
    # os.replace is atomic). image2 demuxer reads the f_%06d.jpg sequence.
    with tempfile.TemporaryDirectory(dir=str(frames_dir.parent)) as tmp:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-start_number", "1",
            "-i", str(frames_dir / "f_%06d.jpg"),
            "-vf", transpose, "-q:v", "2",
            str(Path(tmp) / "f_%06d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        rotated = sorted(Path(tmp).glob("f_*.jpg"))
        if len(rotated) != len(frames):
            raise RuntimeError(
                f"rotation produced {len(rotated)} frames, expected {len(frames)}"
            )
        # Phase C — commit frame files (fast renames).
        for src in rotated:
            os.replace(str(src), str(frames_dir / src.name))

    # Phase D — persist payload + annotations.
    swap = degrees in (90, 270)
    for it in items:
        p = it.get("payload") or {}
        if swap:
            w = p.get("width") or _TARGET_SIZE
            h = p.get("height") or _TARGET_SIZE
            p["width"], p["height"] = h, w
        p["frame_rev"] = int(p.get("frame_rev", 0)) + 1
        it["payload"] = p
        storage.save_item(it)
    for ann in new_anns:
        storage.save_annotation(project_id, ann)

    return len(items)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_rotate.py -q`
Expected: PASS (8 passed). Requires `ffmpeg` on PATH.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/video.py backend/tests/test_video_rotate.py
git commit -m "feat(video): rotate_video frames + annotations in place"
```

---

## Task 4: API endpoint + schema

**Files:**
- Modify: `backend/app/schemas/item.py` (add `RotateRequest` after `ReassignRequest`, line ~36)
- Modify: `backend/app/api/v1/videos.py` (add route after `reassign_video`, line ~124)
- Test: `backend/tests/test_video_rotate.py` (append HTTP tests)

- [ ] **Step 1: Write the failing HTTP tests**

Append to `backend/tests/test_video_rotate.py`:

```python
@pytest.fixture
def pose_project(client, admin_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "rot-http", "type": "pose_detection"},
        headers=admin_headers,
    )
    return r.json()


def _seed_video_frame(pid: int, video: str, w: int, h: int) -> int:
    pdir = storage.project_dir(pid)
    _make_frame(pdir, video, w, h)
    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/{video}/f_000001.jpg",
                    "source_video": video, "frame_index": 1, "width": w, "height": h},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    return iid


def test_rotate_endpoint_admin_ok(client, admin_headers, pose_project):
    pid = pose_project["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 90}, headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"rotated": 1, "degrees": 90}


def test_rotate_endpoint_404_when_no_frames(client, admin_headers, pose_project):
    pid = pose_project["id"]
    r = client.post(
        f"/api/v1/projects/{pid}/videos/ghost/rotate",
        json={"degrees": 90}, headers=admin_headers,
    )
    assert r.status_code == 404


def test_rotate_endpoint_422_bad_degrees(client, admin_headers, pose_project):
    pid = pose_project["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 45}, headers=admin_headers,
    )
    assert r.status_code == 422


def test_rotate_endpoint_forbidden_for_non_admin(client, auth_headers, admin_headers):
    # Project owned by a non-admin; that owner still can't rotate (admin-only).
    pid = client.post(
        "/api/v1/projects",
        json={"name": "owned", "type": "pose_detection"},
        headers=auth_headers,
    ).json()["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 90}, headers=auth_headers,
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_video_rotate.py -k endpoint -q`
Expected: FAIL — 404 (route not registered) for the admin_ok test.

- [ ] **Step 3: Add the `RotateRequest` schema**

In `backend/app/schemas/item.py`, after `class ReassignRequest` (line ~35):

```python
class RotateRequest(BaseModel):
    degrees: int  # 90 (clockwise), 180, or 270 (counter-clockwise)
```

- [ ] **Step 4: Add the route**

In `backend/app/api/v1/videos.py`, update the schema import line:

```python
from app.schemas.item import ReassignRequest, RotateRequest
```

Then add after `reassign_video` (after line ~124):

```python
@router.post(
    "/projects/{project_id}/videos/{source_video}/rotate",
    tags=["videos"],
)
def rotate_video(
    project_id: int,
    source_video: str,
    data: RotateRequest,
    current_user: AdminUser,
) -> dict:
    _require_project(project_id)
    if data.degrees not in (90, 180, 270):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "degrees must be 90, 180, or 270",
        )
    count = video_service.rotate_video(project_id, source_video, data.degrees)
    if count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found in project")
    return {"rotated": count, "degrees": data.degrees}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_video_rotate.py -q`
Expected: PASS (12 passed).

- [ ] **Step 6: Lint + commit**

```bash
ruff check backend/app/services/video.py backend/app/api/v1/videos.py backend/app/schemas/item.py
git add backend/app/api/v1/videos.py backend/app/schemas/item.py backend/tests/test_video_rotate.py
git commit -m "feat(api): admin endpoint to rotate a video's frames"
```

---

## Task 5: Frontend API client + frame URL helper

**Files:**
- Create: `frontend/src/lib/frameUrl.ts`
- Modify: `frontend/src/api/videos.ts` (add `rotateVideo` after `deleteVideo`)

- [ ] **Step 1: Create the cache-busting helper**

Create `frontend/src/lib/frameUrl.ts`:

```ts
import { FILES_BASE } from './env';

/**
 * Absolute URL for a frame image, cache-busted by `frame_rev` so a re-rendered
 * frame (e.g. after rotation) isn't served stale from the browser cache.
 * Returns null when the payload has no image_url.
 */
export function frameUrl(
  payload: { image_url?: string; frame_rev?: number } | undefined | null,
): string | null {
  const url = payload?.image_url;
  if (!url) return null;
  const full = `${FILES_BASE}${url}`;
  return payload?.frame_rev ? `${full}?r=${payload.frame_rev}` : full;
}
```

- [ ] **Step 2: Add the API call**

In `frontend/src/api/videos.ts`, append:

```ts
export async function rotateVideo(
  projectId: number,
  sourceVideo: string,
  degrees: 90 | 180 | 270,
) {
  const { data } = await api.post<{ rotated: number; degrees: number }>(
    `/projects/${projectId}/videos/${encodeURIComponent(sourceVideo)}/rotate`,
    { degrees },
  );
  return data;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: exit 0 (no errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/frameUrl.ts frontend/src/api/videos.ts
git commit -m "feat(frontend): rotateVideo api + cache-busting frameUrl helper"
```

---

## Task 6: Wire frame cache-busting at all render sites

**Files:**
- Modify: `frontend/src/pages/PoseAnnotatePage.tsx:7,663-664`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (videoThumbs ~344-357; thumb img ~1419; item grid img ~1888; item list img ~2064; outliers modal img ~2315)

There is no frontend test suite; the gate for this task is the typecheck plus a
manual visual check after rotating a video.

- [ ] **Step 1: Switch PoseAnnotatePage to `frameUrl`**

In `frontend/src/pages/PoseAnnotatePage.tsx`, change the import (line 7) from:

```ts
import { FILES_BASE } from '@/lib/env';
```
to:
```ts
import { frameUrl } from '@/lib/frameUrl';
```

Then replace lines 663-664:

```ts
  const imageUrl = payload.image_url;
  const fullUrl = imageUrl ? `${FILES_BASE}${imageUrl}` : null;
```
with:
```ts
  const fullUrl = frameUrl(payload as { image_url?: string; frame_rev?: number });
```

(If `FILES_BASE` is now unused elsewhere in the file, remove the dead import; the typecheck in Step 3 will flag it.)

- [ ] **Step 2: Switch ProjectDetailPage frame images to `frameUrl`**

Add the import near the other lib imports (next to the existing `FILES_BASE` import, ~line 28):

```ts
import { frameUrl } from '@/lib/frameUrl';
```

(a) Make thumbnails carry `frame_rev`. Replace the `videoThumbs` memo (lines ~344-357):

```tsx
  const videoThumbs = useMemo(() => {
    const best = new Map<string, { idx: number; url: string }>();
    for (const i of items) {
      const p = i.payload as { source_video?: string; frame_index?: number; image_url?: string; frame_rev?: number };
      const sv = p.source_video;
      const fi = p.frame_index;
      const url = frameUrl(p);
      if (!sv || !url || typeof fi !== 'number') continue;
      const cur = best.get(sv);
      if (!cur || fi < cur.idx) best.set(sv, { idx: fi, url });
    }
    const out: Record<string, string> = {};
    best.forEach((v, k) => { out[k] = v.url; });
    return out;
  }, [items]);
```

(b) Thumbnail `<img>` (~line 1419): the value is now already absolute. Change:

```tsx
                        src={`${FILES_BASE}${thumb}`}
```
to:
```tsx
                        src={thumb}
```

(c) Item grid `<img>` (~line 1873-1888). Change the URL derivation:

```tsx
              const imgUrl = (i.payload as { image_url?: string }).image_url;
```
to:
```tsx
              const imgUrl = frameUrl(i.payload as { image_url?: string; frame_rev?: number });
```
and its `<img src>` (~line 1888):
```tsx
                      src={`${FILES_BASE}${imgUrl}`}
```
to:
```tsx
                      src={imgUrl}
```
(adjust the surrounding truthiness guard if it checks `imgUrl` — it still works since `frameUrl` returns `string | null`.)

(d) Item list `<img>` (~line 2062-2064). Change:

```tsx
                  {(i.payload as { image_url?: string }).image_url && (
                    <img
                      src={`${FILES_BASE}${(i.payload as { image_url: string }).image_url}`}
```
to:
```tsx
                  {frameUrl(i.payload as { image_url?: string; frame_rev?: number }) && (
                    <img
                      src={frameUrl(i.payload as { image_url?: string; frame_rev?: number }) ?? ''}
```

(e) Outliers modal `<img>` (~line 2313-2315). Change:

```tsx
                        {sv.image_url && (
                          <img
                            src={`${FILES_BASE}${sv.image_url}`}
```
to:
```tsx
                        {sv.image_url && (
                          <img
                            src={frameUrl(sv as { image_url?: string; frame_rev?: number }) ?? ''}
```

(If `FILES_BASE` is no longer referenced in this file after these edits, remove its import.)

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: exit 0. Fix any "unused FILES_BASE" by removing the dead import.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PoseAnnotatePage.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(frontend): cache-bust frame images via frame_rev"
```

---

## Task 7: Rotate buttons in the Videos table

**Files:**
- Create: `frontend/src/features/projects/VideoRotateButtons.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (import; add `rotatingVideo` state + `rotateMut`; render buttons in both list ~1463 and grid ~1581 rows)

- [ ] **Step 1: Create the button component**

Create `frontend/src/features/projects/VideoRotateButtons.tsx`:

```tsx
interface Props {
  inFlight: boolean;
  disabled?: boolean;
  onRotate: (degrees: 90 | 180 | 270) => void;
}

/** Three small per-video rotation controls: 90° CW, 90° CCW, 180°. */
export function VideoRotateButtons({ inFlight, disabled, onRotate }: Props) {
  const cls = 'p-1 text-slate-400 hover:text-slate-700 disabled:opacity-40 leading-none';
  const off = inFlight || disabled;
  return (
    <span className="inline-flex items-center">
      <button type="button" disabled={off} onClick={() => onRotate(90)}
        className={cls} title="Rotate 90° clockwise"
        aria-label="Rotate 90 degrees clockwise">↻</button>
      <button type="button" disabled={off} onClick={() => onRotate(270)}
        className={cls} title="Rotate 90° counter-clockwise"
        aria-label="Rotate 90 degrees counter-clockwise">↺</button>
      <button type="button" disabled={off} onClick={() => onRotate(180)}
        className={cls} title="Rotate 180°"
        aria-label="Rotate 180 degrees">⟳</button>
    </span>
  );
}
```

- [ ] **Step 2: Import + state + mutation in ProjectDetailPage**

Add the import near the other feature/component imports:

```tsx
import { VideoRotateButtons } from '@/features/projects/VideoRotateButtons';
```

Add to the `videos.ts` API import (the line that imports `reassignVideo`, `deleteVideo`, etc.) the `rotateVideo` name:

```tsx
import { /* existing: */ rotateVideo } from '@/api/videos';
```

Add state next to `approvingVideo` (~line 327):

```tsx
  const [rotatingVideo, setRotatingVideo] = useState<string | null>(null);
```

Add the mutation next to `approveAllMut` (~line 328-335):

```tsx
  const rotateMut = useMutation({
    mutationFn: ({ source, degrees }: { source: string; degrees: 90 | 180 | 270 }) =>
      rotateVideo(projectId, source, degrees),
    onMutate: ({ source }) => setRotatingVideo(source),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
    onError: () => alert('Rotation failed — check the backend logs.'),
    onSettled: () => setRotatingVideo(null),
  });
```

- [ ] **Step 3: Render the buttons in the LIST row**

In the list-view actions cell (right before the Delete button at ~line 1499, i.e. after the approve-all button block), insert:

```tsx
                    <VideoRotateButtons
                      inFlight={rotatingVideo === v.source_video}
                      disabled={rotateMut.isPending}
                      onRotate={(degrees) =>
                        confirmDialog.ask({
                          title: 'Rotate video?',
                          message: `Rotate all ${v.frames} frames of "${v.source_video}" by ${degrees}° and adjust their annotations. The frames are re-rendered.`,
                          confirmLabel: 'Rotate',
                          onConfirm: () => rotateMut.mutate({ source: v.source_video, degrees }),
                        })
                      }
                    />
```

- [ ] **Step 4: Render the buttons in the GRID row**

In the grid-view actions area (right before the Delete button at ~line 1629), insert the same block:

```tsx
                      <VideoRotateButtons
                        inFlight={rotatingVideo === v.source_video}
                        disabled={rotateMut.isPending}
                        onRotate={(degrees) =>
                          confirmDialog.ask({
                            title: 'Rotate video?',
                            message: `Rotate all ${v.frames} frames of "${v.source_video}" by ${degrees}° and adjust their annotations. The frames are re-rendered.`,
                            confirmLabel: 'Rotate',
                            onConfirm: () => rotateMut.mutate({ source: v.source_video, degrees }),
                          })
                        }
                      />
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/projects/VideoRotateButtons.tsx frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(frontend): per-video rotate controls in Videos table"
```

---

## Task 8: Full regression + manual verification

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass except the pre-existing `test_build_coco_export_loads_with_pycocotools` (fails only because `pycocotools` isn't in the native venv; passes in Docker). No new failures.

- [ ] **Step 2: Frontend typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: exit 0.

- [ ] **Step 3: Manual check (user-driven)**

Bring up the dev stack, open a pose project with an annotated video, click each rotate button, and confirm: frames visibly rotate, the thumbnail updates (no stale cache), and on the annotate page the keypoints stay on the same body parts. The user runs this ("eu testo tudo").

- [ ] **Step 4: Final commit (if any cleanup) and stop for review**

```bash
git status
```
No further commits unless cleanup is needed; hand back to the user for the merge decision.

---

## Self-review notes

- **Spec coverage:** API (Task 4), service logic + two-phase commit + `rotate_keypoints` (Tasks 2-3), cache-busting `frame_rev` (Tasks 5-6), UI buttons (Task 7), tests (Tasks 2-4, 8), SPEC doc (Task 1). All spec sections mapped.
- **Deviation from spec:** the spec mentioned a success "toast"; the codebase has no toast system (errors use `alert`, successes rely on query invalidation + spinner, e.g. approve-all). Task 7 follows that existing pattern: spinner while in flight, `alert` on error, no success toast.
- **Type consistency:** `rotateVideo(projectId, sourceVideo, degrees: 90|180|270)` and `rotateMut.mutate({ source, degrees })` agree; `frameUrl(payload)` signature is reused identically at every call site; backend `rotate_video(project_id, source_video, degrees)` matches the route call.
- **`v == 0` handling** is consistent between `rotate_keypoints` (Task 2) and its assertions (Tasks 2-3).
