import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class SourceType(str, enum.Enum):
    upload = "upload"   # an mp4 sitting in uploads/videos
    url = "url"         # a YouTube / Vimeo / direct link


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    # Null means unfiled -- valid, and what pre-chapter content looks like.
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, default=0, index=True)

    source_type = Column(Enum(SourceType), nullable=False, default=SourceType.url)
    video_url = Column(String, nullable=True)          # source_type == url
    stored_filename = Column(String, nullable=True)    # source_type == upload
    original_filename = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    is_published = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="lectures")
    chapter = relationship("Chapter", back_populates="lectures")
    notes = relationship("Note", back_populates="lecture")
    progress = relationship(
        "LectureProgress", back_populates="lecture", cascade="all, delete-orphan"
    )


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    # Null means a course-wide handout rather than one attached to a lecture.
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    stored_filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    content_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="notes")
    chapter = relationship("Chapter", back_populates="notes")
    lecture = relationship("Lecture", back_populates="notes")

    @property
    def extension(self) -> str:
        _, _, ext = self.original_filename.rpartition(".")
        return ext.upper() if ext else "FILE"


class LectureProgress(Base):
    __tablename__ = "lecture_progress"
    __table_args__ = (
        UniqueConstraint("lecture_id", "student_id", name="uq_lecture_progress"),
    )

    id = Column(Integer, primary_key=True, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    completed = Column(Boolean, default=False)
    last_position_seconds = Column(Float, default=0.0)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lecture = relationship("Lecture", back_populates="progress")
