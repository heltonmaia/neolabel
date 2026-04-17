from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import AdminUser, CurrentUser
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import item as item_service
from app.services import project as project_service

router = APIRouter()


def _get_accessible(project_id: int, user) -> ProjectRead:
    project = project_service.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if user.role == "admin" or project.owner_id == user.id:
        return project
    if item_service.user_has_assignment_in_project(project_id, user.id):
        return project
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


@router.get("", response_model=list[ProjectRead])
def list_projects(
    current_user: CurrentUser,
    owner_id: int | None = Query(None),
) -> list[ProjectRead]:
    if current_user.role == "admin":
        if owner_id is not None:
            return project_service.list_for_owner(owner_id)
        return project_service.list_all()
    # Annotator sees projects they own + projects where items are assigned to them.
    return project_service.list_visible_for_user(current_user.id)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, current_user: CurrentUser) -> ProjectRead:
    return project_service.create(data, current_user.id)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, current_user: CurrentUser) -> ProjectRead:
    return _get_accessible(project_id, current_user)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, data: ProjectUpdate, current_user: CurrentUser
) -> ProjectRead:
    _get_accessible(project_id, current_user)
    updated = project_service.update(project_id, data)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, current_user: AdminUser) -> None:
    # Admin-only: allow deleting any project (not just own)
    if not project_service.get(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    project_service.delete(project_id)
