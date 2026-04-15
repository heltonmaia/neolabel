import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectType(str, enum.Enum):
    pose_detection = "pose_detection"
    image_segmentation = "image_segmentation"


class LabelBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#3b82f6", pattern=r"^#[0-9a-fA-F]{6}$")
    shortcut: str | None = Field(default=None, max_length=10)


class LabelCreate(LabelBase):
    pass


class LabelRead(LabelBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: ProjectType


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    created_at: datetime
    labels: list[LabelRead] = []
