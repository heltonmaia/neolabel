import enum
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ItemStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    reviewed = "reviewed"


class ItemCreate(BaseModel):
    payload: dict[str, Any]


class ItemBulkCreate(BaseModel):
    items: list[ItemCreate]


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    payload: dict[str, Any]
    status: ItemStatus
    created_at: datetime
    assigned_to: int | None = None
    review_note: str | None = None


class ReassignRequest(BaseModel):
    assignee_id: int | None = None


class ItemReviewIn(BaseModel):
    """Curation actions:
      - approve   -> status='reviewed', clears any prior note.
      - unapprove -> status='done' (revert a prior approval). Annotation stays.
      - send_back -> status='in_progress', preserves keypoints, stores the
                     optional note so the assignee sees what to fix.
    """
    action: Literal["approve", "unapprove", "send_back"]
    note: str | None = None


class AnnotationUpsert(BaseModel):
    value: dict[str, Any]


class AnnotationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    item_id: int
    annotator_id: int
    value: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ItemDetail(ItemRead):
    annotation: AnnotationRead | None = None
