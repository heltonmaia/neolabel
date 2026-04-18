# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

- Product scope, domain model, API contract, roadmap: **SPEC.md** (source
  of truth — update it before changing behavior).
- How to set up and run the project as a user: **README.md**.

This file only covers what's needed to edit code here: repo layout,
commands, and conventions.

## Stack at a glance

- **Backend** — Python 3.12, FastAPI, Pydantic v2, filesystem JSON
  storage (no DB), JWT + bcrypt, FFmpeg for video frames.
- **Frontend** — React 18 + TypeScript, Vite, Tailwind, TanStack Query,
  Zustand (auth store with persist), React Router v6, React Hook Form +
  Zod. HTTP via axios with a Bearer interceptor in `src/api/client.ts`
  (401 triggers `useAuth.logout()` automatically). Alias `@/` → `src/`.

## Repo layout

```
backend/app/
  api/v1/          # routers: auth, users, projects, labels, items, videos
                   # api_router mounted in api/v1/__init__.py
  core/
    config.py      # pydantic-settings (DATA_DIR, SECRET_KEY, FRONTEND_URL, ...)
    security.py    # bcrypt + JWT
    storage.py     # single I/O gate: atomic JSON writes under DATA_DIR
    deps.py        # CurrentUser dep + role gates (AdminUser, ...)
  schemas/         # Pydantic v2 + enums (UserRole, ProjectType, ItemStatus)
  services/        # business logic (sync — call storage)
  main.py          # FastAPI app, CORS, include api_router, seed users on startup
backend/tests/     # pytest + httpx TestClient; conftest.py isolates DATA_DIR

frontend/src/
  api/             # axios client + per-resource modules (auth, projects, ...)
  pages/           # routes: Login, Projects, ProjectDetail, Annotate (text/pose)
  features/        # domain components (auth, projects)
  components/      # BabyAvatar (pose guide) + ui/
  stores/          # zustand (auth)
  lib/             # utils (env, download, keypoints)
  App.tsx          # routes  ·  main.tsx = providers (QueryClient, Router)

run.py                   # Docker-first interactive dev menu
docker-compose.yml       # dev stack (source mounted for hot-reload)
docker-compose.prod.yml  # prod stack (built images, no source mount)
deploy.sh                # VPS deploy: pull + rebuild + health-check
monitor.py               # prod health/status probe
harden.sh                # one-shot VPS hardening (UFW, fail2ban, unattended-upgrades)
backup.sh                # nightly tarball of DATA_DIR + secrets (run via root cron)
```

Prod-only files (`docker-compose.prod.yml`, `deploy.sh`, `monitor.py`,
`harden.sh`, `backup.sh`) are for the VPS deploy — don't invoke them
for local dev. See `CLAUDE.local.md` (gitignored, VPS notes) if present.

Data lives under `DATA_DIR` at runtime; see SPEC §3 for the on-disk shape.

## Commands

### Dev loop (Docker, recommended)

```bash
python run.py             # interactive menu (up/down/logs/status/tests)
docker compose up -d      # or start directly
docker compose logs -f    # follow
docker compose down       # stop
```

Source is bind-mounted, so hot-reload is automatic. Rebuild is only
needed when `pyproject.toml`, `package.json`, a `Dockerfile`, or
`docker-compose.yml` changes.

### Tests, lint, build

```bash
# Backend tests — run inside the backend container
docker compose exec backend pytest                        # full suite
docker compose exec backend pytest tests/test_auth_api.py # one file
docker compose exec backend pytest -k keypoint            # by name

# Backend lint/format (ruff, line-length=100)
ruff check backend
ruff format backend

# Frontend
cd frontend && npm run lint    # eslint
npm run build                  # tsc -b + vite build
```

Each test isolates `DATA_DIR` via the autouse `_isolated_data_dir`
fixture in `tests/conftest.py` — nothing touches the real `./data`.
Useful fixtures: `client`, `auth_headers`, `second_user_headers`,
`admin_headers`.

### Native dev (optional fallback)

Shared uv venv at `/mnt/hd3/uv-common/uv-neo-label`, cache at
`/mnt/hd3/uv-cache`.

```bash
export UV_CACHE_DIR=/mnt/hd3/uv-cache
source /mnt/hd3/uv-common/uv-neo-label/bin/activate
cd backend && VIRTUAL_ENV=/mnt/hd3/uv-common/uv-neo-label \
  UV_CACHE_DIR=/mnt/hd3/uv-cache uv pip install -e ".[dev]"
```

## Conventions

### Backend

- Services return plain dicts/models; routers do
  `Schema.model_validate(...)`.
- Every protected route uses `CurrentUser` dep — never read the JWT by
  hand.
- `*Read` Pydantic schemas use `ConfigDict(from_attributes=True)`.
- Destructive bulk operations (delete project, delete annotated, delete
  video) require `admin` via the role gates in `deps.py`.
- Unauthorized access to an owned resource returns **404** (hides
  existence). `projects.py` currently returns 403 — known exception,
  don't propagate that pattern.
- All I/O goes through `app/core/storage.py`. Writes are atomic.
- Media served by `GET /files/projects/{pid}/{subdir}/{path}` in
  `main.py` — `subdir` is restricted to `{"frames", "_videos"}`. Do
  **not** expose other JSON/artifacts through this route; they would
  be unauthenticated. Path traversal is blocked via `Path.resolve()`.
- `POST /auth/login` is rate-limited (`5/min` per real client IP) via
  `slowapi`. `core/ratelimit.py` pulls the IP from `X-Forwarded-For`
  (first hop) because prod runs behind two nginxes.
- Video upload streams the request body to disk in 1 MiB chunks and
  enforces `500 MiB` in `services/video.py`. Never `await file.read()`
  the whole body — that regressed once, OOM'd the container.

### Frontend

- Never set `Authorization` manually — the interceptor handles it. 401
  auto-logs out.
- Tailwind utility-first; no custom CSS outside `index.css`.
- Mutations invalidate TanStack Query keys — keep the invalidations
  tight to the affected resource (e.g. `['items', projectId]`).

### Schema evolution

No DB migrations — see SPEC §3. Use tolerant reads
(`dict.get(..., default)`) and, for incompatible changes, add a script
under `backend/scripts/` that walks `DATA_DIR`. **Update SPEC first.**

Existing one-shots in `backend/scripts/`:

- `reconcile_seed_users.py` — prunes users from `users.json` that are
  no longer in `seed_users.json` (the startup seeder is additive-only).
  Dry-run by default; `--apply` to commit. Invoked as
  `python -m scripts.reconcile_seed_users` from the backend container.

## Footguns

- `.env`, `seed_users.json`, and `data/` are all git-ignored — keep
  them that way.
- `SECRET_KEY` in `.env.example` is dev-only.
- CORS is pinned to `FRONTEND_URL` — revisit before exposing the API
  publicly.
- Storage is single-process. Multi-worker deployments need file locks
  or a DB.
- FFmpeg must be on `PATH` for video upload. The backend Docker image
  installs it; native setup must provide it.
- The tsconfig has no `noEmit`, so raw `tsc -b` emits `.js` files into
  `src/`. They're ignored via `.gitignore` but annoying. Prefer
  `npm run build` (which does the emit into `dist/`) or
  `npx tsc -b --noEmit` for typechecks.
