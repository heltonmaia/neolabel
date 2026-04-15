from fastapi import APIRouter

from app.api.v1 import auth, items, labels, projects, videos

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(labels.router)
api_router.include_router(items.router)
api_router.include_router(videos.router)
