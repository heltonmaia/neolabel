import csv
import io
import json

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from app.core.deps import AdminUser, CurrentUser
from app.schemas.item import (
    AnnotationRead,
    AnnotationUpsert,
    ItemBulkCreate,
    ItemDetail,
    ItemRead,
)
from app.services import item as item_service
from app.services import project as project_service

router = APIRouter()


def _require_project_for_owner(project_id: int, user):
    """Owner-level access: admin or the project owner. Used for writes that shape
    the project (bulk upload, export)."""
    project = project_service.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _require_project_access(project_id: int, user):
    """Read-level access: admin, owner, or a user with at least one assigned item."""
    project = project_service.get(project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if user.role == "admin" or project.owner_id == user.id:
        return project
    if item_service.user_has_assignment_in_project(project_id, user.id):
        return project
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


def _require_item_access(item: dict, user):
    """Annotator can touch an item only if it's assigned to them. Admin/owner always."""
    project = project_service.get(item["project_id"])
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if user.role == "admin" or project.owner_id == user.id:
        return project
    if item.get("assigned_to") == user.id:
        return project
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")


@router.post(
    "/projects/{project_id}/items/bulk",
    status_code=status.HTTP_201_CREATED,
    tags=["items"],
)
def bulk_upload(project_id: int, data: ItemBulkCreate, current_user: CurrentUser) -> dict:
    _require_project_for_owner(project_id, current_user)
    count = item_service.bulk_create(project_id, data.items)
    return {"created": count}


@router.get("/projects/{project_id}/items", tags=["items"])
def list_items(
    project_id: int,
    current_user: CurrentUser,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    assigned_to: int | None = Query(None),
) -> dict:
    project = _require_project_access(project_id, current_user)
    # Non-admin, non-owner: force filter to own assignments.
    if current_user.role != "admin" and project.owner_id != current_user.id:
        assigned_to = current_user.id
    items, total = item_service.list_for_project(
        project_id, limit, offset, assigned_to=assigned_to
    )
    return {"total": total, "items": items}


@router.get("/items/{item_id}", response_model=ItemDetail, tags=["items"])
def get_item(item_id: int, current_user: CurrentUser) -> ItemDetail:
    item = item_service.get(item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    _require_item_access(item, current_user)
    annotation = item_service.get_annotation(item["project_id"], item["id"], current_user.id)
    return ItemDetail(
        id=item["id"],
        project_id=item["project_id"],
        payload=item["payload"],
        status=item["status"],
        created_at=item["created_at"],
        annotation=annotation,
        assigned_to=item.get("assigned_to"),
    )


@router.delete(
    "/items/{item_id}/annotation",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["items"],
)
def clear_annotation(item_id: int, current_user: CurrentUser) -> None:
    item = item_service.get(item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    _require_item_access(item, current_user)
    item_service.clear_annotation(item_id)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["items"])
def delete_item(item_id: int, current_user: CurrentUser) -> None:
    item = item_service.get(item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    # Destructive: require owner/admin, not assignee.
    _require_project_for_owner(item["project_id"], current_user)
    item_service.delete(item_id)


@router.post("/projects/{project_id}/items/delete-annotated", tags=["items"])
def delete_annotated_items(project_id: int, current_user: AdminUser) -> dict:
    # Admin-only: bulk destructive operation
    if not project_service.get(project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    count = item_service.delete_annotated(project_id)
    return {"deleted": count}


@router.put("/items/{item_id}/annotation", response_model=AnnotationRead, tags=["items"])
def upsert_annotation(
    item_id: int, data: AnnotationUpsert, current_user: CurrentUser
) -> AnnotationRead:
    item = item_service.get(item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    _require_item_access(item, current_user)
    return item_service.upsert_annotation(item, current_user.id, data)


@router.get("/projects/{project_id}/export", tags=["items"])
def export_project(
    project_id: int,
    current_user: CurrentUser,
    format: str = Query("json", pattern="^(json|jsonl|csv|yolo)$"),
) -> Response:
    _require_project_for_owner(project_id, current_user)

    if format == "yolo":
        data = item_service.export_yolo(project_id)
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="project_{project_id}_yolo.zip"'
            },
        )

    rows = item_service.export_project(project_id)

    if format == "json":
        return Response(
            content=json.dumps(rows, default=str, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="project_{project_id}.json"'},
        )
    if format == "jsonl":
        body = "\n".join(json.dumps(r, default=str, ensure_ascii=False) for r in rows)
        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="project_{project_id}.jsonl"'},
        )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "payload", "status", "annotation"])
    for r in rows:
        writer.writerow(
            [
                r["id"],
                json.dumps(r["payload"], ensure_ascii=False),
                r["status"],
                json.dumps(r["annotation"], ensure_ascii=False) if r["annotation"] else "",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="project_{project_id}.csv"'},
    )
