from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

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
    scope: str = Query("all", pattern="^(all|annotated)$"),
) -> Response:
    _require_project_for_owner(project_id, current_user)
    annotated_only = scope == "annotated"

    # YOLO is always annotated-only — unannotated frames have no labels to write.
    # The `scope` param is accepted but ignored for this format.
    if format == "yolo":
        stream, size = item_service.build_yolo_export(project_id)

        def iter_zip():
            # Stream from the spooled temp file in 1 MiB chunks, then close it
            # so the OS reclaims the disk spill promptly.
            try:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                stream.close()

        return StreamingResponse(
            iter_zip(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="project_{project_id}_yolo.zip"',
                "Content-Length": str(size),
            },
        )

    # Filename suffix makes the scope obvious at a glance in the user's downloads folder.
    tag = "_annotated" if annotated_only else ""

    if format == "json":
        return StreamingResponse(
            item_service.iter_export_json(project_id, annotated_only),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="project_{project_id}{tag}.json"'
            },
        )
    if format == "jsonl":
        return StreamingResponse(
            item_service.iter_export_jsonl(project_id, annotated_only),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f'attachment; filename="project_{project_id}{tag}.jsonl"'
            },
        )
    return StreamingResponse(
        item_service.iter_export_csv(project_id, annotated_only),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="project_{project_id}{tag}.csv"'
        },
    )
