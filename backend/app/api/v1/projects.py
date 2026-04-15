from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import project as project_service

router = APIRouter()


def _get_owned(project_id: int, user_id: int) -> ProjectRead:
    project = project_service.get(project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(current_user: CurrentUser) -> list[ProjectRead]:
    return project_service.list_for_owner(current_user.id)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, current_user: CurrentUser) -> ProjectRead:
    return project_service.create(data, current_user.id)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, current_user: CurrentUser) -> ProjectRead:
    return _get_owned(project_id, current_user.id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, data: ProjectUpdate, current_user: CurrentUser
) -> ProjectRead:
    _get_owned(project_id, current_user.id)
    updated = project_service.update(project_id, data)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, current_user: CurrentUser) -> None:
    _get_owned(project_id, current_user.id)
    project_service.delete(project_id)
