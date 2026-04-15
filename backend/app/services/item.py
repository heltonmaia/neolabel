from datetime import datetime, timezone

from app.core import storage
from app.schemas.item import (
    AnnotationRead,
    AnnotationUpsert,
    ItemCreate,
    ItemRead,
    ItemStatus,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bulk_create(project_id: int, items: list[ItemCreate]) -> int:
    count = 0
    for i in items:
        iid = storage.next_id("items")
        record = {
            "id": iid,
            "project_id": project_id,
            "payload": i.payload,
            "status": ItemStatus.pending.value,
            "created_at": _now(),
        }
        storage.save_item(record)
        count += 1
    return count


def list_for_project(
    project_id: int, limit: int = 100, offset: int = 0
) -> tuple[list[ItemRead], int]:
    all_items = storage.list_items(project_id)
    total = len(all_items)
    page = all_items[offset : offset + limit]
    return [ItemRead.model_validate(i) for i in page], total


def get(item_id: int) -> dict | None:
    return storage.find_item(item_id)


def get_annotation(project_id: int, item_id: int, annotator_id: int) -> AnnotationRead | None:
    d = storage.load_annotation(project_id, item_id, annotator_id)
    return AnnotationRead.model_validate(d) if d else None


def _status_for(project_type: str | None, value: dict) -> str:
    """For pose projects, 'done' requires all 17 keypoints labeled (v>0)."""
    if project_type == "pose_detection":
        kps = value.get("keypoints") or []
        if len(kps) == 17 and all(isinstance(k, list) and len(k) >= 3 and k[2] > 0 for k in kps):
            return ItemStatus.done.value
        return ItemStatus.in_progress.value
    return ItemStatus.done.value


def upsert_annotation(item: dict, annotator_id: int, data: AnnotationUpsert) -> AnnotationRead:
    pid = item["project_id"]
    existing = storage.load_annotation(pid, item["id"], annotator_id)
    now = _now()
    if existing:
        existing["value"] = data.value
        existing["updated_at"] = now
        record = existing
    else:
        record = {
            "id": storage.next_id("annotations"),
            "item_id": item["id"],
            "annotator_id": annotator_id,
            "value": data.value,
            "created_at": now,
            "updated_at": now,
        }
    storage.save_annotation(pid, record)
    project = storage.load_project(pid)
    item["status"] = _status_for(project.get("type") if project else None, data.value)
    storage.save_item(item)
    return AnnotationRead.model_validate(record)


def export_project(project_id: int) -> list[dict]:
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    return [
        {
            "id": i["id"],
            "payload": i["payload"],
            "status": i["status"],
            "annotation": anns.get(i["id"], {}).get("value") if i["id"] in anns else None,
        }
        for i in items
    ]
