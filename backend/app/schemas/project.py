import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectType(str, enum.Enum):
    pose_detection = "pose_detection"
    # Kept for backward compatibility with any pre-existing projects; the UI
    # no longer offers it at creation time and there is no annotation UI for
    # it. Safe to retire once we confirm no project.json carries it.
    image_segmentation = "image_segmentation"


class KeypointSchema(str, enum.Enum):
    """Pose keypoint layout for a project. Immutable after creation —
    changing it would invalidate existing annotations. See SPEC §2."""

    infant = "infant"  # 17 COCO keypoints, BabyAvatar guide
    rodent = "rodent"  # 7 keypoints (N, LEar, REar, BC, TB, TM, TT) for OF / EPM


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
    # Default matches the only schema that existed before the field was
    # introduced, so tolerant reads of older project.json files produce the
    # original behavior.
    keypoint_schema: KeypointSchema = KeypointSchema.infant


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
