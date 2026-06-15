from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.deps import AdminUser
from app.schemas.item import ReassignRequest, RotateRequest
from app.services import image_import as image_import_service
from app.services import import_coco as import_coco_service
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
    assignee_id: int | None = Form(None),
    rotation: int = Form(0),
    resize_mode: str = Form("pad"),
) -> dict:
    _require_project(project_id)
    if assignee_id is not None:
        _require_user(assignee_id)
    try:
        return video_service.extract_frames(
            project_id,
            file.file,
            file.filename or "video",
            fps,
            rotation=rotation,
            assignee_id=assignee_id,
            resize_mode=resize_mode,
        )
    except ValueError as e:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "larger than" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(code, str(e))
    except RuntimeError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.post(
    "/projects/{project_id}/import-coco",
    status_code=status.HTTP_201_CREATED,
    tags=["videos"],
)
async def import_coco_pose(
    project_id: int,
    current_user: AdminUser,
    file: UploadFile = File(...),
    assignee_id: int | None = Form(None),
) -> dict:
    project = _require_project(project_id)
    if project.type.value != "pose_detection":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "COCO-pose import is only available for pose_detection projects",
        )
    if assignee_id is not None:
        _require_user(assignee_id)
    try:
        return import_coco_service.import_coco_pose(
            project_id,
            file.file,
            file.filename or "import.zip",
            uploader_id=current_user.id,
            assignee_id=assignee_id,
        )
    except ValueError as e:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "larger than" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(code, str(e))


@router.post(
    "/projects/{project_id}/import-images",
    status_code=status.HTTP_201_CREATED,
    tags=["videos"],
)
async def import_images(
    project_id: int,
    current_user: AdminUser,
    file: UploadFile = File(...),
    assignee_id: int | None = Form(None),
    resize_mode: str = Form("pad"),
) -> dict:
    project = _require_project(project_id)
    if project.type.value != "pose_detection":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Image import is only available for pose_detection projects",
        )
    if assignee_id is not None:
        _require_user(assignee_id)
    try:
        return image_import_service.import_images(
            project_id,
            file.file,
            file.filename or "images.zip",
            assignee_id=assignee_id,
            resize_mode=resize_mode,
        )
    except ValueError as e:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "larger than" in str(e).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(code, str(e))
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
    if data.assignee_id is not None:
        _require_user(data.assignee_id)
    count = item_service.reassign_video(project_id, source_video, data.assignee_id)
    if count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found in project")
    return {"reassigned": count, "assignee_id": data.assignee_id}


@router.post(
    "/projects/{project_id}/videos/{source_video}/rotate",
    tags=["videos"],
)
def rotate_video(
    project_id: int,
    source_video: str,
    data: RotateRequest,
    current_user: AdminUser,
) -> dict:
    _require_project(project_id)
    if data.degrees not in (90, 180, 270):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "degrees must be 90, 180, or 270",
        )
    try:
        count = video_service.rotate_video(project_id, source_video, data.degrees)
    except RuntimeError as e:
        # ffmpeg failure — surface the message like upload_video does.
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
    if count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found in project")
    return {"rotated": count, "degrees": data.degrees}


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
