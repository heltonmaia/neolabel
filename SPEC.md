# NeoLabel — Specification

Source of truth for the product. Code follows the spec; when reality
diverges, update the spec **before** the code.

- User-facing overview and setup: **README.md**
- Repo internals and conventions for contributors: **CLAUDE.md**

## 1. Roadmap by phase

- ✅ **Phase 1 — Foundation.** Auth + projects CRUD, users, filesystem
  storage, login/register/projects UI.
- ✅ **Phase 2 — Text labeling MVP.** Labels, bulk item upload,
  keyboard-driven annotation UI, exports (JSON/JSONL/CSV).
- ✅ **Phase 3 — Pose detection.** Video upload with FFmpeg frame
  extraction, keyboard-driven annotation, YOLO-pose ZIP export.
  Keypoint schemas: infant pose (17 COCO, `BabyAvatar` guide) and
  rodent pose (7 keypoints) for behavioral assays (OF / EPM). See §2.
- ✅ **Phase 4 — Multi-user assignments.** `admin` role, per-user
  `assigned_to` on items (optional — items may be unassigned and live
  in the admin pool), admin-only video upload with optional assignee,
  per-video reassign/unassign/delete, visibility filtered by assignment.
- ⏳ **Phase 5 — Review workflow.** `reviewer` role wiring, Cohen's
  kappa, progress dashboards.
- ⏳ **Phase 6 — Images beyond pose.** Image classification, bounding
  boxes, COCO export.
- ⏳ **Phase 7 — NER.** Token-level annotation, span labels.

## 2. Domain model

Enums used across API and storage:

- `UserRole` ∈ {`admin`, `annotator`, `reviewer`}
- `ProjectType` ∈ {`pose_detection`, `image_segmentation`}
  — `image_segmentation` is a legacy enum value kept for back-compat with
  any pre-existing `project.json`; the creation UI no longer offers it.
- `KeypointSchema` ∈ {`infant`, `rodent`} — pose-only; see §2 keypoint
  schemas subsection.
- `ItemStatus` ∈ {`pending`, `in_progress`, `done`, `reviewed`}

Core records:

| Record | Shape (essential fields) |
|---|---|
| User | `id, username, hashed_password, role, created_at` |
| Project | `id, name, description, type, keypoint_schema, owner_id, created_at, labels[]` |
| Label | `id, project_id, name, color, shortcut` |
| Item | `id, project_id, payload, status, assigned_to, created_at` |
| Annotation | `id, item_id, annotator_id, value, created_at, updated_at` |

- `item.payload` is free-form JSON:
  - text items: `{text: str}`
  - pose frames: `{source_video: str, frame_index: int, image_url: str}`
- `annotation.value` is label-type-specific JSON. For pose:
  ```json
  {
    "keypoints": [[x, y, v], ...],
    "out_of_frame": [false, ..., true]   // optional, length must match keypoints
  }
  ```
  - `v` is the COCO visibility flag: `0` = not labeled / out of image,
    `1` = labeled but occluded (you know where, but it's covered),
    `2` = labeled and visible.
  - `out_of_frame[i] = true` is a NeoLabel-only marker that the
    annotator **explicitly** said this keypoint is not in the image
    (e.g. cropped out). The corresponding `keypoints[i]` is
    `[0, 0, 0]` — the same encoding COCO datasets use for "not in
    image", so YOLO/COCO exports stay standard. The parallel array
    only exists so the backend can tell "annotator marked OOF" apart
    from "annotator hasn't gotten to it yet".
  - Legacy annotations omit `out_of_frame` entirely; the backend
    treats them with the v>0 rule (see ItemStatus below).

### Pose item completion

Pose items reach `done` when **every** keypoint is *addressed* — either
labeled (`v > 0`) or explicitly marked out-of-frame
(`out_of_frame[i] = true`). Anything else stays `in_progress`. Without
the OOF marker an annotator can never finish a frame where part of the
subject is genuinely outside the image, which is why the field exists.

Non-pose item types are `done` on any save.

### Keypoint schemas (`pose_detection`)

Every pose project carries a `keypoint_schema` field on
`project.json` that picks which layout annotators and exports operate
on. The field is:

- **Required at creation**, chosen in the project-creation form.
- **Immutable afterwards** — changing the schema would invalidate
  every annotation already stored under the project. There is no API
  to edit it; to change schema you create a new project.
- **Tolerant on read** — `project.json` files written before the
  field existed default to `infant`, preserving legacy behavior
  without a migration.

`annotation.value.keypoints` is schema-dependent; array order is stable
per schema and matches the list below. Adding a new schema does not
require a storage migration (value is free-form JSON per project) — it
does require frontend wiring (visual guide component, shortcuts, YOLO
export branch).

- **Infant pose — 17 keypoints.** COCO-17 (nose, eyes, ears, shoulders,
  elbows, wrists, hips, knees, ankles). Visual guide: `BabyAvatar`
  component. YOLO export: `kpt_shape: [17, 3]`, `class: person`.
- **Rodent pose — 7 keypoints.** `N` (nose), `LEar`, `REar`, `BC`
  (body center), `TB` (tail base), `TM` (tail middle), `TT` (tail tip).
  Target use: Open Field and Elevated Plus Maze (EPM) video
  annotation. Visual guide: `RodentAvatar` component. YOLO export:
  `kpt_shape: [7, 3]`, `class: rodent`,
  `flip_idx: [0, 2, 1, 3, 4, 5, 6]`. See `docs/schemas/rodent-pose.svg`.

## 3. Storage (filesystem, no DB)

All state under `DATA_DIR` (default `./data`). One folder per project.

```
data/
  users.json                          # list[UserRecord]
  _counters.json                      # monotonic id counters per kind
  projects/<pid>/
    project.json                      # project config + labels
    items/<iid>.json                  # one file per item
    annotations/<iid>__<uid>.json     # one file per (item, annotator)
    _videos/<name>.<ext>              # uploaded video originals
    frames/<name>/frame_<N>.jpg       # frames extracted by FFmpeg
```

- IDs are monotonic integers tracked in `_counters.json` per kind
  (users, projects, labels, items, annotations).
- Writes are atomic via `os.replace` on a `.tmp` sibling (see
  `app/core/storage.py`).
- **Single-process only.** Multiple worker processes require file locks
  or a migration to a real database — do not scale out without one.

### Schema evolution

No migrations. To change a record shape:

- Prefer **tolerant reads**: use `dict.get(key, default)` so older files
  keep working.
- For incompatible changes, write a one-shot script under
  `backend/scripts/` that walks `DATA_DIR` and rewrites the JSON.
- **Record the change in this file first.**

## 4. API contract

Base URL: `/api/v1`. All protected endpoints require
`Authorization: Bearer <jwt>`. Unauthorized access to a resource the
user does not own returns **404** (to avoid leaking existence), with
`projects.py` currently a known 403 exception (tracked to fix).

### Auth
- `POST /auth/register` — `{username, password}` → 201 User
- `POST /auth/login` — form(`username`, `password`) →
  `{access_token, token_type}`
- `GET  /auth/me` — current user

### Users (admin-visible directory)
- `GET /users` — list all users (used by admin to assign videos)

### Projects
- `GET    /projects` — projects the user can see (owner or
  has items assigned in)
- `POST   /projects` — create
- `GET    /projects/{id}` — project + labels
- `PATCH  /projects/{id}` — partial update
- `DELETE /projects/{id}` — admin or owner

### Labels
- `POST   /projects/{id}/labels`
- `DELETE /labels/{id}`

### Items and annotations
- `POST   /projects/{id}/items/bulk` — owner/admin
- `GET    /projects/{id}/items?limit&offset&assigned_to` —
  non-admin non-owner is forced to `assigned_to = self`
- `GET    /items/{id}` — item + annotation (if any)
- `PUT    /items/{id}/annotation` — upsert (assignee/admin/owner only)
- `DELETE /items/{id}/annotation` — clear annotation, keep item
- `DELETE /items/{id}` — admin/owner only
- `POST   /projects/{id}/items/delete-annotated` — admin-only bulk
- `GET    /projects/{id}/export?format=json|jsonl|csv|yolo|bundle` —
  streams the export. Text formats (`json`, `jsonl`, `csv`) and
  `bundle` always include every item (pending rows carry
  `annotation: null`) — filtering is downstream. `yolo` always
  exports annotated frames only (no-op for pending ones). `bundle`
  returns a self-contained ZIP: `annotations.json` (array of rows,
  `payload.image_url` rewritten to archive-relative paths) plus an
  `images/` folder with every referenced frame.

### Videos (pose projects)
- `POST   /projects/{id}/videos` — admin-only; form(`file`, `fps`,
  `assignee_id?`, `rotation`); streams the upload to disk in 1 MiB
  chunks, caps at **500 MiB** (returns 413 beyond that). `rotation`
  ∈ {0, 90, 180, 270} applies an FFmpeg `transpose` so extracted
  frames come out upright. `assignee_id` is optional — omit to leave
  every extracted frame unassigned (admin-pool only).
- `GET    /projects/{id}/videos` — admin overview (per-video
  `frames`, `done`, `assigned_to` — `null` when unassigned or mixed)
- `PATCH  /projects/{id}/videos/{source}/assign` — admin-only;
  reassigns every frame of the video. Body `{"assignee_id": null}`
  clears the assignment.
- `DELETE /projects/{id}/videos/{source}` — admin-only; deletes
  items, annotations, frames, and the original file

## 5. Non-functional

- OpenAPI at `/docs`.
- CORS restricted to `FRONTEND_URL` (single origin).
- Passwords hashed with `bcrypt` directly (not passlib — breaks on
  bcrypt 4.x). One-way; never logged.
- JWT HS256 with a configurable expiry (default 60 min).
- `POST /auth/login` is rate-limited to **5 requests/minute per client
  IP** (slowapi; IP resolved from `X-Forwarded-For` since the app sits
  behind nginx).
- Media endpoint `GET /files/projects/{pid}/{subdir}/{path}` only
  serves `subdir` ∈ {`frames`, `_videos`}; other files in `DATA_DIR`
  (users, counters, items, annotations JSON) are **not** web-reachable.
- Config via `pydantic-settings`, driven by `.env`.
- FFmpeg must be on `PATH` for video upload; the Docker image bundles
  it.
- Seed users reconciled on every startup from `SEED_USERS_FILE`
  (default `seed_users.json`) — missing users are created, and each
  listed user's password and role are updated in place when they differ
  from the file (so the JSON is authoritative for listed accounts).
  Users not in the file are left untouched.
