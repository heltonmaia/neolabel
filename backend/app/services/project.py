from datetime import datetime, timezone

from app.core import storage
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate


def _hydrate(d: dict) -> ProjectRead:
    return ProjectRead.model_validate(d)


def list_for_owner(owner_id: int) -> list[ProjectRead]:
    return [_hydrate(p) for p in storage.list_projects() if p.get("owner_id") == owner_id]


def list_all() -> list[ProjectRead]:
    return [_hydrate(p) for p in storage.list_projects()]


def get(project_id: int) -> ProjectRead | None:
    d = storage.load_project(project_id)
    return _hydrate(d) if d else None


def get_raw(project_id: int) -> dict | None:
    return storage.load_project(project_id)


def create(data: ProjectCreate, owner_id: int) -> ProjectRead:
    pid = storage.next_id("projects")
    record = {
        "id": pid,
        "name": data.name,
        "description": data.description,
        "type": data.type.value,
        "owner_id": owner_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "labels": [],
    }
    storage.save_project(record)
    return _hydrate(record)


def update(project_id: int, data: ProjectUpdate) -> ProjectRead | None:
    record = storage.load_project(project_id)
    if not record:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        record[key] = value
    storage.save_project(record)
    return _hydrate(record)


def delete(project_id: int) -> None:
    storage.delete_project(project_id)
