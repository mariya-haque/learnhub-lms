from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseBase(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    description: str | None = None
    subject: str | None = Field(default=None, max_length=60)
    accent: str = "indigo"
    is_published: bool = False


class CourseCreate(CourseBase):
    pass


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    subject: str | None = Field(default=None, max_length=60)
    accent: str | None = None
    is_published: bool | None = None


class CourseResponse(CourseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    teacher_id: int
    created_at: datetime | None = None
