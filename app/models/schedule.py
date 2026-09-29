import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.config import get_settings
from app.database import Base

# How long before the start time the room unlocks for students, and how long
# after the end it stays reachable. Teachers ignore both -- they may open their
# own room whenever they like, to set up before anyone arrives.
JOIN_OPENS_MINUTES = get_settings().class_join_lead_minutes
JOIN_GRACE_MINUTES = 15


class MeetingProvider(str, enum.Enum):
    builtin = "builtin"    # a room this app hosts in an iframe, no account needed
    external = "external"  # a pasted Zoom / Google Meet / Teams link


class ClassState(str, enum.Enum):
    upcoming = "upcoming"
    live = "live"
    ended = "ended"
    cancelled = "cancelled"


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat those as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class ClassSession(Base):
    """One scheduled live class, owned by a course.

    Times are stored in UTC and rendered in the viewer's own zone by the
    browser -- a teacher in Karachi and a student in London must see the same
    moment, not the same wall-clock string.
    """

    __tablename__ = "class_sessions"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, nullable=False, default=60)

    provider = Column(
        Enum(MeetingProvider), nullable=False, default=MeetingProvider.builtin
    )
    # builtin: an unguessable room name, because the room itself is only as
    # private as its name. external: the teacher's own meeting link.
    room_name = Column(String, nullable=True)
    meeting_url = Column(String, nullable=True)

    is_cancelled = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="class_sessions")
    teacher = relationship("User")

    # ---------------------------------------------------------------- derived

    @property
    def starts_at_utc(self) -> datetime:
        return _as_utc(self.starts_at)

    @property
    def ends_at(self) -> datetime:
        return self.starts_at_utc + timedelta(minutes=self.duration_minutes or 60)

    @property
    def join_opens_at(self) -> datetime:
        return self.starts_at_utc - timedelta(minutes=JOIN_OPENS_MINUTES)

    @property
    def join_closes_at(self) -> datetime:
        return self.ends_at + timedelta(minutes=JOIN_GRACE_MINUTES)

    @property
    def state(self) -> ClassState:
        if self.is_cancelled:
            return ClassState.cancelled
        now = datetime.now(timezone.utc)
        if now < self.join_opens_at:
            return ClassState.upcoming
        if now <= self.join_closes_at:
            return ClassState.live
        return ClassState.ended

    @property
    def is_joinable(self) -> bool:
        """True inside the join window. Teachers bypass this; students do not."""
        return self.state == ClassState.live
