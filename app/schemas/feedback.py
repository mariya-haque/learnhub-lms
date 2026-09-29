from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.feedback import MAX_RATING, MIN_RATING


class ReviewSave(BaseModel):
    """Leave or update a review. One per student per subject."""

    rating: int = Field(ge=MIN_RATING, le=MAX_RATING)
    comment: str | None = Field(default=None, max_length=1500)


class ReviewModerate(BaseModel):
    is_published: bool


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    student_id: int
    rating: int
    comment: str | None = None
    is_published: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
