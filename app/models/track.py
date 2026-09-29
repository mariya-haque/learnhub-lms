from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Track(Base):
    """An exam programme -- ECAT, SAT, MDCAT -- holding a set of subjects.

    A track is the top of the hierarchy: track -> subject (a course) -> chapter
    -> lectures, notes and tests. Courses may still stand on their own with no
    track at all, which is what every course created before tracks existed does.
    """

    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    # Short exam label shown as a badge, e.g. "ECAT". Falls back to the title.
    code = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    accent = Column(String, default="indigo")
    # Who may edit it. Same rule as courses: the owner, or an admin.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Off by default so adding billing never paywalls a track that was free
    # yesterday. Turning it on is an explicit act in the track's settings.
    requires_subscription = Column(Boolean, default=False, index=True)
    is_published = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User")
    subjects = relationship(
        "Course",
        back_populates="track",
        order_by="Course.title",
    )
    enrollments = relationship(
        "TrackEnrollment", back_populates="track", cascade="all, delete-orphan"
    )
    plans = relationship(
        "Plan",
        back_populates="track",
        cascade="all, delete-orphan",
        order_by="Plan.order_index",
    )
    # Not cascaded: a subscription is a financial record and must survive the
    # track it paid for being reorganised or removed.
    subscriptions = relationship("Subscription", back_populates="track")

    @property
    def label(self) -> str:
        return self.code or self.title


class TrackEnrollment(Base):
    """Joining a track grants access to every subject inside it.

    Deliberately not the same thing as a course ``Enrollment``: membership is
    stored once against the track, so a subject added next month is unlocked
    for existing members without backfilling anything.
    """

    __tablename__ = "track_enrollments"
    __table_args__ = (
        UniqueConstraint("track_id", "student_id", name="uq_track_enrollment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())

    track = relationship("Track", back_populates="enrollments")
    student = relationship("User")
