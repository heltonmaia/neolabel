from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.deps import CurrentUser
from app.services import project as project_service
from app.services import video as video_service

router = APIRouter()


@router.post(
    "/projects/{project_id}/videos",
    status_code=status.HTTP_201_CREATED,
    tags=["videos"],
)
async def upload_video(
    project_id: int,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    fps: float = Form(...),
) -> dict:
    project = project_service.get(project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    try:
        return video_service.extract_frames(project_id, data, file.filename or "video", fps)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except RuntimeError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
