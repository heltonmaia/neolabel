from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser
from app.schemas.project import LabelCreate, LabelRead
from app.services import label as label_service
from app.services import project as project_service

router = APIRouter()


@router.post(
    "/projects/{project_id}/labels",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
    tags=["labels"],
)
def create_label(project_id: int, data: LabelCreate, current_user: CurrentUser) -> LabelRead:
    project = project_service.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if current_user.role != "admin" and project.owner_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    label = label_service.create(project_id, data)
    if not label:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return label


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["labels"])
def delete_label(label_id: int, current_user: CurrentUser) -> None:
    found = label_service.find(label_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Label not found")
    project, _ = found
    if current_user.role != "admin" and project.get("owner_id") != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your project")
    label_service.delete(label_id)
