from app.core import storage
from app.schemas.project import LabelCreate, LabelRead


def create(project_id: int, data: LabelCreate) -> LabelRead | None:
    project = storage.load_project(project_id)
    if not project:
        return None
    lid = storage.next_id("labels")
    label = {"id": lid, "project_id": project_id, **data.model_dump()}
    project.setdefault("labels", []).append(label)
    storage.save_project(project)
    return LabelRead.model_validate(label)


def find(label_id: int) -> tuple[dict, dict] | None:
    """Return (project_dict, label_dict) or None."""
    for project in storage.list_projects():
        for lbl in project.get("labels", []):
            if lbl["id"] == label_id:
                return project, lbl
    return None


def delete(label_id: int) -> bool:
    found = find(label_id)
    if not found:
        return False
    project, _ = found
    project["labels"] = [l for l in project["labels"] if l["id"] != label_id]
    storage.save_project(project)
    return True
