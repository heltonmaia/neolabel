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
  extraction (or a raw-image ZIP imported as pending frames),
  keyboard-driven annotation, YOLO-pose ZIP export.
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
| User | `id, username, email, google_sub, hashed_password, role, created_at` |
| Project | `id, name, description, type, keypoint_schema, owner_id, created_at, labels[]` |
| Label | `id, project_id, name, color, shortcut` |
| Item | `id, project_id, payload, status, assigned_to, created_at` |
| Annotation | `id, item_id, annotator_id, value, created_at, updated_at` |

- `User.hashed_password` is optional and, since the emergency-access
  migration, effectively vestigial: no login endpoint accepts a
  password anymore (`POST /auth/login` and the password break-glass are
  **removed** — see §4 Auth). A handful of pre-existing dormant accounts
  in prod still carry a hash from before the migration, and
  `hash_password`/`verify_password` (`core/security.py`) remain as
  internal helpers, but nothing in the HTTP API calls them. Every live
  account is either Google-provisioned (`email` + `google_sub`, the
  latter set on first Google login) or the single emergency-admin
  account (`email` set, `google_sub` always `None` — that path never
  calls Google). `username` is a display label (from the Google profile
  name, else the email local-part), not a login credential for anyone.
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
  emergency_code.json                 # at most one active emergency code (absent = none)
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
- **`allowlist.json`** (a list of `{email, role, name}`) lives
  **outside** `DATA_DIR`, at `ACCESS_ALLOWLIST_FILE` (default
  `../allowlist.json`, relative to the backend's working directory —
  i.e. the repo root, the same spot the old `seed_users.json`
  occupied). It replaces `seed_users.json` entirely and holds no
  passwords. See §4 for how it's used at login.
- **`emergency_code.json`** — unlike `allowlist.json`, this one lives
  **inside** `DATA_DIR`. Holds at most one record (the system has
  exactly one eligible emergency email, so one outstanding code is
  enough):
  ```json
  {
    "email": "owner@example.com",
    "code_hash": "<hex hmac_sha256(code, SECRET_KEY)>",
    "expires_at": "<ISO-8601 UTC>",
    "attempts": 0,
    "created_at": "<ISO-8601 UTC>"
  }
  ```
  Absent file = no outstanding code. See §4 for the full lifecycle
  (generation, verification, attempt/cooldown handling).

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

Google Sign-In is the primary login for every user. A single
**emergency email-code** flow is the Google-independent fallback for
the one configured admin — for when Google Sign-In itself is
unavailable (bad OAuth client, consent/allowlist misconfig,
token-verification failure, Google outage). The password break-glass
(`POST /auth/login`, `BREAKGLASS_ADMIN_EMAIL` /
`BREAKGLASS_ADMIN_PASSWORD`) is **removed** — no password is stored or
accepted anywhere in the system anymore.

- `POST /auth/google` — `{credential}` (the signed ID token Google
  Identity Services returns to the browser) → `{access_token,
  token_type}`. Verifies the token (signature, issuer, audience,
  expiry) → requires `email_verified` → looks up the lowercased email
  in the **allowlist** (`allowlist.json`, read fresh from disk on
  every call — see §3) → `403` if absent → finds or provisions a
  passwordless `UserRecord` by email (role, `google_sub`, and display
  name synced from the allowlist/Google claims on every login) →
  mints the standard session JWT. `401` on an invalid/expired/wrong-
  `aud` token; `403` if the email isn't verified or isn't allowlisted
  (the message never reveals whether an allowlist entry exists); `503`
  if Google's own verification call fails (outage). Rate-limited
  `5/min` per client IP.
- `GET  /auth/me` — current user (includes `email`).
- **`POST /auth/emergency/request`** — `{email}` → **always** `200
  {"detail": "If that email is registered, a code has been sent."}`,
  whether or not `email` matches `EMERGENCY_ADMIN_EMAIL`
  (case-insensitive) — no user enumeration. Only when it *does* match,
  and no unexpired code for it is still within its cooldown, does the
  call generate a 6-digit numeric code, store it (overwriting any
  previous code), and email it via Resend; any other input is a silent
  no-op. A Resend send failure is logged server-side but never changes
  the response (send status is never leaked). `email` is a plain
  string field (not format-validated) — anything that
  case-insensitively equals `EMERGENCY_ADMIN_EMAIL` counts.
  Rate-limited `5/min` per client IP.
- **`POST /auth/emergency/verify`** — `{email, code}` → `200
  {access_token, token_type}` (same `Token` shape as `/auth/google`) on
  success; generic `400 {"detail": "Invalid or expired code."}` on
  *any* failure — no code on file, wrong email, expired, wrong code, or
  attempts already exhausted are all indistinguishable to the caller.
  On success: the stored code is deleted (single-use), the
  emergency-admin `UserRecord` is found-or-provisioned by
  `EMERGENCY_ADMIN_EMAIL` with role forced to `admin` (same
  provisioning helper `/auth/google` uses), and the standard session
  JWT is minted — identical shape and `ACCESS_TOKEN_EXPIRE_MINUTES` as
  every other login path. On a wrong code, `attempts` is incremented in
  place (see security properties below). This endpoint never calls
  Google and never reads `allowlist.json` — fully independent of both.
  Rate-limited `10/min` per client IP.
- **Emergency-code security properties** (`services/emergency.py`,
  hashing in `core/security.py`):
  - 6 digits, numeric, single-use, **10-minute TTL**
    (`EMERGENCY_CODE_TTL_MINUTES`, default 10).
  - Stored **hashed**, never in plaintext:
    `code_hash = hmac_sha256(code, SECRET_KEY)` (hex), compared with a
    constant-time `hmac.compare_digest` — a leaked `emergency_code.json`
    can't be brute-forced without `SECRET_KEY`.
  - **Attempt cap** (`EMERGENCY_CODE_MAX_ATTEMPTS`, default **5**): once
    hit, verify keeps returning the generic `400` — even for the
    correct code — but the record is **blocked, not deleted**. It only
    goes away when it naturally expires (TTL) or a fresh `request` call
    lands *after* the cooldown window, which overwrites it with a new
    code. Deleting it immediately on exhaustion was deliberately
    avoided: that would let an attacker who just burned a code trigger
    a brand-new one at network speed, defeating the cooldown below.
  - **Cooldown** (`EMERGENCY_CODE_COOLDOWN_SECONDS`, default **60**):
    `request` won't generate/send a new code while the existing
    record's `created_at` is within the cooldown window, regardless of
    whether that record is still guessable or already
    attempts-exhausted. Blocks inbox spam and burn-and-immediately-
    retry alike.
  - **No user enumeration**: `request` returns the identical body and
    status for the admin email, any other email, or a malformed one.
  - **Single eligible email**: only `EMERGENCY_ADMIN_EMAIL` (one
    setting, one admin, checked case-insensitively) can ever receive a
    code, and this check is **independent of `allowlist.json`** — the
    emergency path still works if the allowlist itself is what broke.
  - Delivery via **Resend** (`POST https://api.resend.com/emails`,
    `RESEND_API_KEY` bearer auth, `from = EMAIL_FROM`) over the
    `requests` library — chosen over SMTP because the production VPS
    blocks outbound SMTP ports. `services/email.py` is thin and
    mockable; tests monkeypatch it, so the suite makes no network call.
  - The minted session is the **standard** JWT — there is no separate,
    shorter- or longer-lived "emergency session" type.
- **Allowlist authorization, instant revocation** (`/auth/google`
  only). Access is gated by `allowlist.json` (§3), read fresh from disk
  on every call — removing an email denies that user on their very
  next login attempt, no restart required. A restart is only needed to
  *pre-provision* a newly-added email ahead of its first login (done at
  startup — see §5). The emergency-admin account sits entirely outside
  this mechanism.
- **Fail-closed.** A missing, unreadable, or malformed (not a JSON
  list) `allowlist.json` makes the loader return an empty map instead
  of raising — every `/auth/google` call then `403`s. The emergency
  path is unaffected (it never reads the allowlist), so it remains a
  way in even when the allowlist itself is broken.

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
- `GET    /projects/{id}/export?format=json|jsonl|csv|yolo|bundle|yolo_split|coco|coco_split` —
  streams the export. Text formats (`json`, `jsonl`, `csv`) and
  `bundle` always include every item (pending rows carry
  `annotation: null`) — filtering is downstream. `yolo` always
  exports annotated frames only (no-op for pending ones). `bundle`
  returns a self-contained ZIP: `annotations.json` (array of rows,
  `payload.image_url` rewritten to archive-relative paths) plus an
  `images/` folder with every referenced frame.
- `yolo_split` — same Ultralytics YOLO-pose dataset as `yolo`, but
  partitioned into `images/{train,val,test}` + `labels/{train,val,test}`
  from a seeded random shuffle. Extra query params: `train`, `val`,
  `test` (integer percentages, each 0–100, **must sum to 100** or the
  endpoint returns **422**; default 70/20/10) and `seed` (integer,
  default 42). A given seed + the same eligible frames always yields
  the same split. When `test=0`, the test folders and the `test:` key
  in `data.yaml` are omitted and `val` absorbs the rounding remainder
  (no frame is dropped). Annotated-only, like `yolo`.
- `exclude_occluded` (bool, default `false`; applies to `yolo` and
  `yolo_split`, ignored otherwise) — when `true`, occluded keypoints
  (`v=1`) are written as `0 0 0` (demoted to `v=0`) so they carry no
  keypoint training supervision. The bounding box is unchanged: occluded
  points still count toward it. Lets you A/B a dataset that trains on
  occluded joints against one that doesn't.
- `coco` / `coco_split` — COCO Keypoints JSON for ViTPose/MMPose/pycocotools.
  `coco` streams a single `annotations.json` (`images`/`annotations`/
  `categories`, absolute-pixel keypoints in COCO-17 order, native 0/1/2
  visibility, person bbox padded 12% from the visible keypoints). `coco_split`
  returns a ZIP of `train.json`/`val.json`/`test.json` using the **same**
  `train/val/test/seed` partition as `yolo_split`, so the COCO and YOLO splits
  match frame-for-frame (the `file_name` is the same `NNNNNN_<stem>.jpg` as the
  YOLO export). **Infant pose only** — a rodent project returns **422**.

### Videos (pose projects)
- `POST   /projects/{id}/videos` — admin-only; form(`file`, `fps`,
  `assignee_id?`, `rotation`); streams the upload to disk in 1 MiB
  chunks, caps at **500 MiB** (returns 413 beyond that). `rotation`
  ∈ {0, 90, 180, 270} applies an FFmpeg `transpose` so extracted
  frames come out upright. `assignee_id` is optional — omit to leave
  every extracted frame unassigned (admin-pool only).
- `POST   /projects/{id}/import-images` — admin-only, pose projects only
  (400 otherwise); form(`file`, `assignee_id?`, `resize_mode` ∈
  {`pad`, `stretch`}, default `pad`). Streams an image ZIP to disk in
  1 MiB chunks (caps at **500 MiB** → 413), extracts with path-traversal
  guards, and creates one **pending** item per image (`.jpg`/`.jpeg`/
  `.png`, found recursively). Each image is re-encoded to 640×640 with
  the same FFmpeg resize as video upload, so image frames and video
  frames are interchangeable. All images flatten into one source group
  named after the ZIP; `frame_index` continues past any existing frames
  in that group. Returns `{items_created, skipped_files, source_video,
  resize_mode}`. 400 on empty / invalid ZIP / no images / bad
  `resize_mode`.
- `GET    /projects/{id}/videos` — admin overview (per-video
  `frames`, `done`, `assigned_to` — `null` when unassigned or mixed)
- `PATCH  /projects/{id}/videos/{source}/assign` — admin-only;
  reassigns every frame of the video. Body `{"assignee_id": null}`
  clears the assignment.
- `POST   /projects/{id}/videos/{source}/rotate` — admin-only; rotates
  every extracted frame of the video in place and transforms the
  existing keypoint annotations to match. Body `{"degrees": 90|180|270}`
  where `90` is clockwise and `270` counter-clockwise (same convention
  as upload `rotation`). Frame files are re-rendered with FFmpeg
  `transpose`; each item's `payload.frame_rev` is bumped (cache-busting)
  and `width`/`height` are swapped on 90/270. Returns
  `{"rotated": <frame count>, "degrees": <int>}`. 404 if the video has
  no frames in the project; 422 if `degrees` is not 90/180/270.
- `DELETE /projects/{id}/videos/{source}` — admin-only; deletes
  items, annotations, frames, and the original file

## 5. Non-functional

- OpenAPI at `/docs`.
- CORS restricted to `FRONTEND_URL` (single origin).
- `bcrypt` password hashing (`core/security.py:hash_password`/
  `verify_password`, not passlib — breaks on bcrypt 4.x) remains in the
  codebase but is no longer wired to any HTTP endpoint — no login path
  accepts a password (see §4 Auth).
- JWT HS256 with a configurable expiry (default 60 min).
- `POST /auth/google` and `POST /auth/emergency/request` are
  rate-limited to **5 requests/minute per client IP**;
  `POST /auth/emergency/verify` to **10/minute** (slowapi; IP resolved
  from `X-Forwarded-For` since the app sits behind nginx).
- Media endpoint `GET /files/projects/{pid}/{subdir}/{path}` only
  serves `subdir` ∈ {`frames`, `_videos`}; other files in `DATA_DIR`
  (users, counters, items, annotations JSON) are **not** web-reachable.
- Config via `pydantic-settings`, driven by `.env`.
- FFmpeg must be on `PATH` for video upload; the Docker image bundles
  it.
- On every startup, `seed_users()` provisions a passwordless user per
  `allowlist.json` entry (role and display name synced from the file)
  — additive: existing records absent from the allowlist are left
  dormant, never deleted — prune them with
  `backend/scripts/reconcile_users.py` (`--apply` to commit). The
  emergency-admin account is **not** part of startup seeding; it is
  found-or-provisioned lazily, only on the first successful
  `POST /auth/emergency/verify`.
