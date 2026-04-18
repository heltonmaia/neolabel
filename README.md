# Neo-Label

Web app for labeling data to build Machine Learning datasets. Create projects,
upload data, annotate with keyboard shortcuts, and export the result.

![Neo-Label sign-in](docs/screenshots/login.png)

> The full specification — domain model, API reference, and roadmap —
> lives in **[SPEC.md](./SPEC.md)**.

## Features

- **Authentication** by username/password (JWT) with roles (`admin`,
  `annotator`, `reviewer`). Destructive bulk operations (delete project,
  delete all annotated items) are admin-only.
- **Projects** with types:
  - **Pose detection** — 17 COCO keypoints, interactive baby avatar as a
    visual guide, video upload with FFmpeg-based frame extraction.
  - **Image segmentation** (roadmap).
- **Admin-only video upload** — optionally assigned to a specific
  annotator, or left in the admin pool (extracted frames with no
  assignee). Admins can reassign a whole video to another user, clear
  the assignment, or delete it (removing frames and annotations).
- **Per-user visibility** — annotators only see projects and items
  assigned to them; admins see everything.
- **Scale-ready project page**:
  - Videos table with search, assignee filter, per-row progress bar and
    totals.
  - Items section with status tabs, per-video filter, list/grid view,
    client-side pagination, and the assigned annotator shown on every
    row (dashed/italic when unassigned).
- **Annotation UI**:
  - Mouse or full-keyboard workflow (arrows + Enter/Space).
  - Shortcuts: `Tab`/`N` next keypoint, `1`–`9` jump, `O` hidden, `U`
    undo, `[` / `]` previous/next item.
  - Undo history (50 steps), clear point / clear all.
  - Auto-save on every action.
  - **Traversal order** — choose top-to-bottom (default), left-contour,
    or right-contour; clicking any point always overrides the pointer.
    Output array order is unchanged across modes.
  - **Reuse previous frame as template** — optional toggle that prefills
    a new frame with the previous frame's keypoints so you only drag to
    adjust. Safe to turn on/off mid-session.
- **Export** in JSON, JSONL, CSV, and **YOLO-pose ZIP** (Ultralytics-ready,
  COCO 17 keypoints) for pose projects.

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, filesystem JSON storage
  (no database), JWT + bcrypt, FFmpeg for videos.
- **Frontend:** React 18 + TypeScript, Vite, TailwindCSS, TanStack Query,
  Zustand, React Router, React Hook Form.

## Setup

```bash
cp .env.example .env
cp seed_users.example.json seed_users.json
# edit seed_users.json with the credentials you want
```

`seed_users.json` is **git-ignored** and is read on every backend
startup:

- Users listed here are **created** if they don't exist yet.
- If a listed user already exists, their **password and role are
  reconciled** to match the file — so editing the password and
  restarting the backend is the supported way to rotate credentials.
- Users not listed in the file are left untouched. To prune users that
  were removed from `seed_users.json`, run the reconciliation script:

  ```bash
  # dry-run (prints what would change, touches nothing)
  docker compose exec backend python -m scripts.reconcile_seed_users
  # apply
  docker compose exec backend python -m scripts.reconcile_seed_users --apply
  ```

  The script always preserves `admin`, unassigns any orphaned item
  references, and lists projects whose `owner_id` would become orphaned
  for manual review.

If you skip the file entirely, no users are created automatically — use
the register screen.

Format:

```json
[
  { "username": "admin",      "password": "change-me", "role": "admin" },
  { "username": "annotator1", "password": "change-me", "role": "annotator" }
]
```

Accepted roles: `admin`, `annotator`, `reviewer`.

## Running

The recommended dev workflow is Docker — it bundles FFmpeg, pins the
Python/Node versions, and mounts source code for hot-reload.

### Docker (recommended)

```bash
docker compose up --build -d
```

Or use the interactive menu, which wraps the same commands:

```bash
python run.py
```

Menu options: up (build + start), down, logs (follow), status, open UI,
run backend tests.

### Native

Requires Python 3.12, Node 18+, and FFmpeg on `PATH`.

```bash
# Backend
cd backend
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

URLs:

- API / docs: <http://localhost:8000/docs>
- UI: <http://localhost:5173>

## Development workflow

With the Docker dev stack, source code is bind-mounted into both
containers:

- **Backend** (`uvicorn --reload`): saving a `.py` reloads the app
  automatically.
- **Frontend** (Vite HMR): saving a `.tsx`/`.css` updates the browser
  instantly.

Rebuild (`docker compose up --build -d`) is only needed when
`pyproject.toml`, `package.json`, a `Dockerfile`, or `docker-compose.yml`
changes.

## Data

All data lives under `./data/` (configurable via `DATA_DIR`). Each project
is a subfolder with its config, items, annotations, uploaded videos, and
extracted frames. No database — backup is just copying that folder.

## Environment variables

See `.env.example`. Main ones:

- `DATA_DIR` — where data is stored (default `./data`).
- `SECRET_KEY` — JWT signing key (change for production).
- `FRONTEND_URL` — allowed CORS origin.
- `BACKEND_PORT`, `VITE_API_URL` — dev ports/URLs.
- `SEED_USERS_FILE` — path to the seed file (set automatically in
  `docker-compose.yml`).

## Tests

```bash
# inside the running backend container
docker compose exec backend pytest

# or, from the interactive menu
python run.py   # → "Run backend tests"
```

Each test runs against an isolated `DATA_DIR` via an autouse fixture, so
the suite never touches local data.
