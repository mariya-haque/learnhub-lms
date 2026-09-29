from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.schedule import MeetingProvider


class ClassSessionCreate(BaseModel):
    """A new live class.

    ``starts_at`` must carry a timezone -- the browser sends the instant as
    UTC. Accepting a naive datetime here would silently mean "whatever zone the
    server happens to sit in", which is exactly the bug this app must not have.
    """

    course_id: int
    title: str = Field(min_length=2, max_length=160)
    description: str | None = None
    starts_at: datetime
    duration_minutes: int = Field(default=60, ge=5, le=480)
    provider: MeetingProvider = MeetingProvider.builtin
    meeting_url: str | None = None


class ClassSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    starts_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    provider: MeetingProvider | None = None
    meeting_url: str | None = None
    is_cancelled: bool | None = None


class ClassSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    teacher_id: int
    title: str
    description: str | None = None
    starts_at: datetime
    duration_minutes: int
    provider: MeetingProvider
    meeting_url: str | None = None
    is_cancelled: bool
    created_at: datetime | None = None
