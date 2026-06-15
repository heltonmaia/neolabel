# Image-ZIP upload — design

**Date:** 2026-06-15
**Status:** approved (design), pending implementation
**Scope:** add the ability to ingest a ZIP of raw images into a pose
project, alongside the existing video upload and COCO-keypoints import.

## 1. Problem

Today a `pose_detection` project gets frames in two ways:

- **Upload video** (`POST /projects/{id}/videos`) — FFmpeg extracts frames
  at a chosen FPS, resized to 640×640.
- **Import COCO keypoints** (`POST /projects/{id}/import-coco`) — a ZIP
  with `_annotations.coco.json` indexes; images are copied in at native
  resolution and imported **already annotated**.

There is no way to bring in a folder of **raw, unannotated images** to
annotate from scratch. This spec adds that path: upload a `.zip` of
images → one `pending` frame-item per image, ready for keypoint
annotation.

## 2. Decisions (settled during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Resize** | Resize every image to **640×640** using the same `pad`/`stretch` filter as the video uploader (default `pad`). | Image frames become byte-consistent with video frames — same export geometry, one mental model. |
| **Grouping** | **One group per ZIP**, named after the file (`photos.zip` → source `photos`). Subfolders are walked recursively but ignored for grouping. | Simplest; one row per upload in the Videos table. |
| **Scope** | **`pose_detection` projects only.** | Mirrors `import-coco` gating; it's the only annotation workflow that consumes frames today. |
| **Resize execution** | **One FFmpeg pass per image** (approach A). | Reuses the exact `scale/pad` + `-q:v 2` pipeline; no new dependency; ZIP images are heterogeneous so batch image2 demuxing is unreliable. |

Rejected: Pillow in-process resize (new dep, JPEGs would differ subtly
from the video path); per-subfolder grouping (more logic, not needed);
optional/native-resolution mode (consistency with video frames was the
explicit goal).

## 3. Architecture

Data flow, mirroring `import_coco.py`'s ZIP plumbing:

```
ZIP upload
  → stream to temp file in 1 MiB chunks, cap 500 MiB   (ValueError on over/empty)
  → _safe_extract into temp dir                         (path-traversal guard)
  → rglob *.jpg/.jpeg/.png, sort by filename
  → for each image:
        ffmpeg -i <src> -vf <resize_filter(mode)> -q:v 2  frames/<zip>/f_NNNNNN.jpg
        create item { payload{image_url, source_video=<zip>, frame_index, width:640, height:640},
                      status: pending, assigned_to: assignee_id }
  → return { items_created, skipped_files, source_video, resize_mode }
```

No schema change. Items are the **same shape** as video frames, so they
flow through the Videos table, assignment, annotation, and export
unchanged.

### 3.1 Shared resize helper

Extract the 640-resize constants and filter builder out of
`services/video.py` so both the video uploader and the new image importer
use one definition (keeps the two frame sources identical):

- New module **`backend/app/services/frames.py`** exposing:
  - `TARGET_SIZE = 640`, `RESIZE_MODES = ("stretch", "pad")`
  - `resize_filter(mode: str) -> str` — the current `_resize_filter` body
- `services/video.py` imports these and drops its private copies
  (`_TARGET_SIZE`, `_PAD_COLOR`, `_RESIZE_MODES`, `_resize_filter`).
  `_PAD_COLOR` moves to `frames.py` as a module constant used by
  `resize_filter`.

This is the only change to existing backend code; behavior of the video
path is unchanged (same filter string emitted).

### 3.2 New service — `services/image_import.py`

Reuses `import_coco.py`'s helpers as a pattern (some can be lifted as-is):

- `_SAFE` / `_safe_name(filename)` — group name from the ZIP filename.
- `_safe_extract(zf, dest)` — identical path-traversal guard.
- `_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}`.
- `_MAX_ZIP_BYTES = 500 MiB`, `_CHUNK_BYTES = 1 MiB`.

Main entry:

```python
def import_images(
    project_id: int,
    source: BinaryIO,
    filename: str,
    assignee_id: int | None = None,
    resize_mode: str = "pad",
) -> dict:
```

Behavior:

1. Validate `resize_mode in frames.RESIZE_MODES` (else `ValueError`).
2. Stream → cap → extract (as COCO import does).
3. Walk `extract_dir.rglob("*")`, keep regular **files** whose suffix is
   in `_IMAGE_SUFFIXES` (case-insensitive), sorted by path. Regular files
   that are not images are counted as `skipped_files`; directories are
   ignored (not counted).
4. `source_name = _safe_name(filename)`. **frame_index continues
   contiguously** from any existing frames in
   `frames/<source_name>/` (same counter logic as COCO import), so
   re-uploading extends the group rather than colliding.
5. For each image: run FFmpeg resize into
   `frames/<source_name>/f_{idx:06d}.jpg` (always `.jpg`, since we
   re-encode — matches video frames). On non-zero ffmpeg exit, raise
   `RuntimeError` (→ 500), consistent with the video path.
6. Create one `pending` item per successfully written frame with
   `payload = {image_url, source_video, frame_index, width: 640,
   height: 640}` and `assigned_to = assignee_id`.
7. If `items_created == 0` (no images in archive) → `ValueError`
   ("No images found in archive").
8. Return `{items_created, skipped_files, source_video, resize_mode}`.

Unlike COCO import, this creates **no annotations** — items are blank/
pending. `uploader_id` is therefore not needed.

### 3.3 New endpoint — `api/v1/videos.py`

```python
@router.post("/projects/{project_id}/import-images", status_code=201, tags=["videos"])
async def import_images(
    project_id: int,
    current_user: AdminUser,
    file: UploadFile = File(...),
    assignee_id: int | None = Form(None),
    resize_mode: str = Form("pad"),
) -> dict:
```

- `_require_project(project_id)`; gate `project.type.value == "pose_detection"`
  else `400` (same message style as `import-coco`).
- `_require_user(assignee_id)` when provided.
- Call `image_import_service.import_images(...)`.
- `ValueError → 413` if `"larger than"` in message else `400`;
  `RuntimeError → 500` — same mapping the other two endpoints use.

### 3.4 Frontend

**`api/videos.ts`**

```ts
export interface ImageImportResult {
  items_created: number;
  skipped_files: number;
  source_video: string;
  resize_mode: ResizeMode;
}

export async function importImages(
  projectId: number,
  file: File,
  assigneeId: number | null,
  resizeMode: ResizeMode = 'pad',
): Promise<ImageImportResult>
```

(FormData with `file`, optional `assignee_id`, `resize_mode`;
`multipart/form-data`.)

**`pages/ProjectDetailPage.tsx`** — new `<details>` card **"Upload images
(ZIP)"**, gated `isPose && isAdmin`, placed **immediately after "Upload
video"**. Structure mirrors the COCO card:

- Dropzone accepting `.zip` (copy: "Click to choose an images ZIP — JPG/PNG").
- **Resize radio** reusing the video card's Keep-aspect-ratio / Stretch
  markup (default `pad`).
- Assignee `<select>` (same options as the other cards).
- Submit button "Upload & extract" (disabled until a file is chosen).
- Result summary after success: "Created N items · skipped M files".

New local state (`imagesFile`, `imagesAssignee`, `imagesResizeMode`,
`imagesResult`) and a `imagesImport` `useMutation` cloned from
`cocoImport`, invalidating `['items', projectId]` and
`['videos', projectId]` on success so the new group appears in the
Videos table immediately.

## 4. Errors & edge cases

| Case | Result |
|---|---|
| Non-pose project | `400` (endpoint gate) |
| Empty upload | `400` "Empty file" |
| Not a ZIP / corrupt | `400` "Not a valid ZIP: …" |
| ZIP with no images | `400` "No images found in archive" |
| Over 500 MiB | `413` |
| Path traversal in archive | `400` "Unsafe path in archive: …" |
| Non-image files mixed in | Skipped, counted in `skipped_files` |
| Nested subfolders | Walked recursively, all flattened into one group |
| FFmpeg failure on an image | `500` (whole upload fails; partial frames may remain — acceptable, admin retries) |
| Re-upload same ZIP name | Extends the existing group; `frame_index` continues contiguously |

## 5. Testing — `tests/test_image_import.py`

Build small in-memory ZIPs with `zipfile` + tiny generated JPEG/PNG
bytes (or Pillow if already available in test env; otherwise minimal
valid image bytes). Cases:

1. **Happy path** — 2–3 images → `items_created` matches; each frame on
   disk is 640×640; items are `pending`; `source_video` == zip stem;
   `frame_index` is 1..N.
2. **Assignee wiring** — `assigned_to` set on every created item.
3. **Gating** — non-pose project → `400`.
4. **Empty file** → `400`; **corrupt ZIP** → `400`.
5. **No images** (ZIP of only `.txt`) → `400` "No images found in
   archive" (raised before any dict is returned).
6. **Nested folders** flatten into one group.
7. **Mixed non-image files** skipped and counted.
8. **resize_mode** — `stretch` accepted; invalid mode → `400`.
9. **Contiguous re-upload** — second upload of same name continues
   `frame_index` past the first.

Backend tests run in-container via `pytest`; use existing fixtures
(`client`, `admin_headers`, isolated `DATA_DIR`).

## 6. Docs to update (before/with code)

- **SPEC.md** — ingest section: document `import-images` alongside the
  video and COCO paths; note Phase 3 gains raw-image ingest.
- **README.md** — "What you can do" step 1: mention "or upload a ZIP of
  images".
- **CLAUDE.md** — `videos.py` pointer: note it also hosts the
  image-ZIP importer (`POST /projects/{id}/import-images`).

## 7. Out of scope (YAGNI)

- Per-subfolder grouping.
- Native-resolution / optional-resize mode.
- Non-pose project types (Phase 6 image classification/bbox — no UI yet).
- Importing images with sidecar annotations (that's what COCO import is
  for).
- Per-image rotation on import (the Videos table already has per-group
  rotate post-upload).
