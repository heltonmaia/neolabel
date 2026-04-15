import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.config import settings
from app.services import user as user_service

log = logging.getLogger("neolabel")

app = FastAPI(title="Neo-Label API", version="0.1.0")


@app.on_event("startup")
def seed_default_user() -> None:
    if user_service.ensure_seed_user("neuromate", "123456"):
        log.warning("Seeded default user: neuromate / 123456 (change in production)")

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
app.mount("/files", StaticFiles(directory=_data_dir), name="files")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
