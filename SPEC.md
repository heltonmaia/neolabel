# Neo-Label — Specification

Spec-driven development: this document is the source of truth. Code follows the spec; when reality diverges, update the spec first.

## 1. Scope by Phase

### Phase 1 — Foundation (current)
- Monorepo + docker-compose (backend + frontend; no DB)
- Backend: FastAPI + JSON-on-disk storage, JWT auth
- Domain records: User, Project, Label, Item, Annotation
- API: auth (register/login/me), projects CRUD
- Frontend: Vite + React + TS + Tailwind + React Query
- Pages: login, register, projects list/create

### Phase 2 — Text classification MVP
- Item bulk upload (CSV/JSON)
- Annotation UI for text classification
- Keyboard shortcuts, auto-save
- Export JSON/JSONL/CSV

### Phase 3 — Multi-user & review
- Roles (admin/annotator/reviewer)
- Item assignment
- Review workflow
- Progress metrics, Cohen's kappa

### Phase 4 — Images
- Image upload (ZIP)
- Image classification UI
- Bounding box UI
- COCO export

### Phase 5 — NER
- Token-level annotation UI
- Span-based labels

## 2. Storage (filesystem, no DB)

All state lives on disk under `DATA_DIR` (default `./data`). Per project = one folder.

```
data/
  users.json                            # list[UserRecord]
  _counters.json                        # id counters per kind
  projects/<pid>/
    project.json                        # {id, name, description, type, owner_id,
                                        #  created_at, labels: [ {id, name, color, shortcut} ]}
    items/<iid>.json                    # {id, project_id, payload, status, created_at}
    annotations/<iid>__<uid>.json       # {id, item_id, annotator_id, value,
                                        #  created_at, updated_at}
```

- IDs: monotonic integers kept in `_counters.json` per kind (users, projects, labels, items, annotations).
- Atomic writes via `os.replace` on a `.tmp` sibling.
- Single-process safety only (no file locks across processes yet).

### Types
- `role` ∈ {admin, annotator, reviewer}
- `project.type` ∈ {text_classification, image_classification, ner, bbox}
- `item.status` ∈ {pending, in_progress, done, reviewed}
- `item.payload`: free-form JSON — `{text: str}` for text, `{image_url: str}` for image, etc.
- `annotation.value`: label-type-specific JSON

## 3. API Contract (Phase 1)

Base URL: `/api/v1`

### Auth
- `POST /auth/register` — {email, password} → 201 {id, email, role}
- `POST /auth/login` — form(username, password) → 200 {access_token, token_type}
- `GET  /auth/me` — Bearer → 200 User

### Projects
- `GET    /projects` — list user's projects
- `POST   /projects` — {name, description, type} → 201 Project
- `GET    /projects/{id}` — 200 Project (with labels)
- `PATCH  /projects/{id}` — partial update
- `DELETE /projects/{id}` — 204

### Labels
- `POST   /projects/{id}/labels` — {name, color, shortcut}
- `DELETE /labels/{id}`

All protected endpoints require `Authorization: Bearer <jwt>`.

## 4. Non-Functional
- OpenAPI at `/docs`
- CORS allows `FRONTEND_URL`
- Structured JSON logs
- Config via env vars (pydantic-settings)
- Passwords: bcrypt via passlib
- JWT: HS256, 60 min expiry (configurable)

## 5. Repository Layout
```
proj-neo-label/
├── backend/
│   ├── app/
│   │   ├── api/v1/           # routers
│   │   ├── core/             # config, db, security, deps
│   │   ├── models/           # SQLAlchemy
│   │   ├── schemas/          # Pydantic
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/              # axios client + endpoints
│   │   ├── components/ui/    # shadcn
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   └── projects/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── pages/
│   │   ├── stores/           # zustand
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
└── SPEC.md
```

## 6. Dev Workflow

### uv environment (shared)
The project uses a shared uv virtualenv at `/mnt/hd3/uv-common/uv-neo-label`
with cache at `/mnt/hd3/uv-cache`.

```bash
export UV_CACHE_DIR=/mnt/hd3/uv-cache
source /mnt/hd3/uv-common/uv-neo-label/bin/activate
```

### Run
1. `cp .env.example .env`
2. Backend:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```
3. Frontend: `cd frontend && npm install && npm run dev`

Data is created automatically under `DATA_DIR` on first write.

API at http://localhost:8000/docs · UI at http://localhost:5173
