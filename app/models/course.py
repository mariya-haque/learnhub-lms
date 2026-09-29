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


class Course(Base):
    """A course, which doubles as a *subject* when it sits inside a track.

    ``track_id`` is nullable on purpose: a course with no track behaves exactly
    as it always has -- listed in the catalogue, enrolled in individually. Put
    it in a track and it becomes one of that track's subjects instead.
    """

    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    subject = Column(String, nullable=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True, index=True)
    # Name of a palette token ("indigo", "teal", ...) rather than a hex value,
    # so the stylesheet stays the single source of colour.
    accent = Column(String, default="indigo")
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    is_published = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    teacher = relationship("User", back_populates="courses_taught")
    track = relationship("Track", back_populates="subjects")
    chapters = relationship(
        "Chapter",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Chapter.order_index",
    )
    enrollments = relationship(
        "Enrollment", back_populates="course", cascade="all, delete-orphan"
    )
    lectures = relationship(
        "Lecture",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Lecture.order_index",
    )
    notes = relationship(
        "Note", back_populates="course", cascade="all, delete-orphan"
    )
    tests = relationship(
        "Test", back_populates="course", cascade="all, delete-orphan"
    )
    class_sessions = relationship(
        "ClassSession",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="ClassSession.starts_at",
    )
    reviews = relationship(
        "Review", back_populates="course", cascade="all, delete-orphan"
    )


class Chapter(Base):
    """A unit inside a subject -- "Kinematics", "Thermodynamics".

    Lectures, notes and tests point at a chapter optionally. Content with no
    chapter is not broken; it simply shows in an "Unfiled" group, which is
    where every piece of content created before chapters existed lands.
    """

    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, default=0, index=True)
    is_published = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="chapters")
    lectures = relationship(
        "Lecture", back_populates="chapter", order_by="Lecture.order_index"
    )
    notes = relationship("Note", back_populates="chapter")
    tests = relationship("Test", back_populates="chapter")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="enrollments")
    student = relationship("User", back_populates="enrollments")
