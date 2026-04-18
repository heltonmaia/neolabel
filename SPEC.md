# Neo-Label — Specification

Source of truth for the product. Code follows the spec; when reality
diverges, update the spec **before** the code.

- User-facing overview and setup: **README.md**
- Repo internals and conventions for contributors: **CLAUDE.md**

## 1. Roadmap by phase

- ✅ **Phase 1 — Foundation.** Auth + projects CRUD, users, filesystem
  storage, login/register/projects UI.
- ✅ **Phase 2 — Text labeling MVP.** Labels, bulk item upload,
  keyboard-driven annotation UI, exports (JSON/JSONL/CSV).
- ✅ **Phase 3 — Pose detection.** 17 COCO keypoints, baby-avatar guide,
  video upload with FFmpeg frame extraction, YOLO-pose ZIP export.
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
- `ProjectType` ∈ {`text_classification`, `pose_detection`,
  `image_classification`, `bbox`, `ner`}
- `ItemStatus` ∈ {`pending`, `in_progress`, `done`, `reviewed`}

Core records:

| Record | Shape (essential fields) |
|---|---|
| User | `id, username, hashed_password, role, created_at` |
| Project | `id, name, description, type, owner_id, created_at, labels[]` |
| Label | `id, project_id, name, color, shortcut` |
| Item | `id, project_id, payload, status, assigned_to, created_at` |
| Annotation | `id, item_id, annotator_id, value, created_at, updated_at` |

- `item.payload` is free-form JSON:
  - text items: `{text: str}`
  - pose frames: `{source_video: str, frame_index: int, image_url: str}`
- `annotation.value` is label-type-specific JSON (e.g. for pose,
  `{keypoints: [[x, y, visibility], ...]}`).

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
- `GET    /projects/{id}/export?format=json|jsonl|csv|yolo` —
  YOLO returns a ZIP of the Ultralytics layout (pose projects)

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
