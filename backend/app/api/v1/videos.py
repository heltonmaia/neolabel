from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.deps import AdminUser
from app.schemas.item import ReassignRequest
from app.services import item as item_service
from app.services import project as project_service
from app.services import user as user_service
from app.services import video as video_service

router = APIRouter()


def _require_project(project_id: int):
    project = project_service.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _require_user(user_id: int):
    user = user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Assignee does not exist")
    return user


@router.post(
    "/projects/{project_id}/videos",
    status_code=status.HTTP_201_CREATED,
    tags=["videos"],
)
async def upload_video(
    project_id: int,
    current_user: AdminUser,
    file: UploadFile = File(...),
    fps: float = Form(...),
    assignee_id: int = Form(...),
) -> dict:
    _require_project(project_id)
    _require_user(assignee_id)
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    try:
        return video_service.extract_frames(
            project_id, data, file.filename or "video", fps, assignee_id=assignee_id
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except RuntimeError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get("/projects/{project_id}/videos", tags=["videos"])
def list_videos(project_id: int, current_user: AdminUser) -> list[dict]:
    _require_project(project_id)
    return item_service.videos_in_project(project_id)


@router.patch(
    "/projects/{project_id}/videos/{source_video}/assign",
    tags=["videos"],
)
def reassign_video(
    project_id: int,
    source_video: str,
    data: ReassignRequest,
    current_user: AdminUser,
) -> dict:
    _require_project(project_id)
    _require_user(data.assignee_id)
    count = item_service.reassign_video(project_id, source_video, data.assignee_id)
    if count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found in project")
    return {"reassigned": count, "assignee_id": data.assignee_id}


@router.delete(
    "/projects/{project_id}/videos/{source_video}",
    tags=["videos"],
)
def delete_video(
    project_id: int,
    source_video: str,
    current_user: AdminUser,
) -> dict:
    _require_project(project_id)
    count = item_service.delete_video(project_id, source_video)
    if count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found in project")
    return {"deleted": count}
