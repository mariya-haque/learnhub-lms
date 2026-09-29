from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

MIN_RATING = 1
MAX_RATING = 5


class Review(Base):
    """One student's rating of one subject.

    Unique per (course, student): a review is edited, never stacked. Someone
    who changes their mind after the second chapter should be able to say so
    without the average counting them twice.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_review_once"),
        CheckConstraint(
            f"rating >= {MIN_RATING} AND rating <= {MAX_RATING}", name="ck_rating_range"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)

    # Moderation is a visibility switch, never an edit: a teacher may hide a
    # review but must not be able to put words in a student's mouth.
    is_published = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    course = relationship("Course", back_populates="reviews")
    student = relationship("User")

    @property
    def stars(self) -> str:
        """Filled and empty stars, for places that cannot render a component."""
        return "★" * (self.rating or 0) + "☆" * (MAX_RATING - (self.rating or 0))
