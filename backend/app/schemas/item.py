import enum
from datetime import datetime
from typing import Any

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
    """approve=True marks status=reviewed and clears any prior note.
    approve=False marks status=in_progress (preserving keypoints) and stores
    the optional note on the item so the assignee can see why it came back."""
    approve: bool
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
