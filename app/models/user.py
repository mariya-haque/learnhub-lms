import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Role(str, enum.Enum):
    """A str-Enum so templates can compare against plain strings."""

    student = "student"
    teacher = "teacher"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.student, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    courses_taught = relationship(
        "Course", back_populates="teacher", cascade="all, delete-orphan"
    )
    enrollments = relationship(
        "Enrollment", back_populates="student", cascade="all, delete-orphan"
    )
    attempts = relationship(
        "Attempt", back_populates="student", cascade="all, delete-orphan"
    )

    # --- Convenience used all over the templates -------------------------
    @property
    def is_teacher(self) -> bool:
        return self.role in (Role.teacher, Role.admin)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    @property
    def initial(self) -> str:
        return (self.display_name or "?")[0].upper()
