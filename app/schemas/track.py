from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrackCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    code: str | None = Field(default=None, max_length=16)
    description: str | None = None
    accent: str | None = "indigo"
    is_published: bool = False


class TrackUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    code: str | None = Field(default=None, max_length=16)
    description: str | None = None
    accent: str | None = None
    requires_subscription: bool | None = None
    is_published: bool | None = None


class TrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    code: str | None = None
    description: str | None = None
    accent: str | None = None
    is_published: bool
    created_at: datetime | None = None


class SubjectLink(BaseModel):
    """Attach or detach one course as a subject of a track."""

    course_id: int


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = None
    is_published: bool = True


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    is_published: bool | None = None


class ChapterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    order_index: int
    is_published: bool


class ChapterAssign(BaseModel):
    """File a piece of content under a chapter. ``chapter_id`` null = unfile."""

    kind: str = Field(pattern="^(lecture|note|test)$")
    item_id: int
    chapter_id: int | None = None
