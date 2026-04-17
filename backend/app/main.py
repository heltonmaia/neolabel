import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import api_router
from app.core.config import settings
from app.core.ratelimit import limiter
from app.schemas.user import UserRole
from app.services import user as user_service

log = logging.getLogger("neolabel")

app = FastAPI(title="Neo-Label API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
def seed_default_users() -> None:
    """Seed users from SEED_USERS_FILE (JSON). Missing file → no seeding."""
    seed_path = Path(settings.SEED_USERS_FILE)
    if not seed_path.is_absolute():
        seed_path = Path.cwd() / seed_path
    if not seed_path.exists():
        log.warning(
            "No seed users file at %s — skipping. Register users via /auth/register "
            "or create the file from seed_users.example.json.",
            seed_path,
        )
        return
    try:
        entries = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("Failed to read %s: %s", seed_path, e)
        return
    for entry in entries:
        try:
            role = UserRole(entry.get("role", "annotator"))
            status = user_service.upsert_seed_user(
                entry["username"], entry["password"], role
            )
            if status != "unchanged":
                log.warning(
                    "seed_users: %s user %s (role=%s)", status, entry["username"], role.value
                )
        except (KeyError, ValueError) as e:
            log.error("Skipping malformed seed entry %r: %s", entry, e)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

_data_dir = Path(settings.DATA_DIR)
_data_dir.mkdir(parents=True, exist_ok=True)

# Only project-scoped frames and videos are served. Metadata files
# (users.json, project.json, items/, annotations/) must never leak.
_ALLOWED_MEDIA_SUBDIRS = frozenset({"frames", "_videos"})


@app.get("/files/projects/{project_id}/{subdir}/{path:path}", tags=["files"])
def serve_media(project_id: int, subdir: str, path: str) -> FileResponse:
    if subdir not in _ALLOWED_MEDIA_SUBDIRS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    base = (_data_dir / "projects" / str(project_id) / subdir).resolve()
    full = (base / path).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not full.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(full)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
