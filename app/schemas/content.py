from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.content import SourceType


class LectureCreate(BaseModel):
    """URL-backed lectures only. Uploads arrive as multipart, not JSON."""

    title: str = Field(min_length=2, max_length=160)
    description: str | None = None
    video_url: str = Field(min_length=4)
    duration_seconds: int | None = None
    is_published: bool = True


class LectureUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    video_url: str | None = None
    duration_seconds: int | None = None
    is_published: bool | None = None


class LectureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    order_index: int
    source_type: SourceType
    video_url: str | None = None
    original_filename: str | None = None
    duration_seconds: int | None = None
    is_published: bool
    created_at: datetime | None = None


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    lecture_id: int | None = None


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    lecture_id: int | None = None
    title: str
    description: str | None = None
    original_filename: str
    file_size: int | None = None
    content_type: str | None = None
    created_at: datetime | None = None


class ProgressPing(BaseModel):
    """Sent by the player every few seconds and on pause/unload."""

    position_seconds: float = Field(ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    completed: bool | None = None


class ReorderPayload(BaseModel):
    """New display order, as a list of lecture ids."""

    ids: list[int]
