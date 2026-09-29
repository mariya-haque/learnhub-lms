"""Student reviews of subjects, and the averages they roll up into.

Three rules shape this module:

* **You may only review what you can open.** The access check is the same one
  the player uses, so a rating always comes from somebody who actually had the
  course -- through direct enrollment or through a track.
* **Moderation hides, it never edits.** A teacher can unpublish a review that
  is abusive or off-topic, but there is deliberately no path to changing its
  text. Editable reviews are worse than no reviews.
* **A hidden review still counts for nobody.** Averages are computed over
  published rows only, so unpublishing genuinely removes its influence rather
  than leaving a ghost in the score.
"""

from sqlalchemy import func

from app.models import Course, MAX_RATING, MIN_RATING, Review, Role, User
from app.services.course import AccessDenied, can_manage, has_access


class FeedbackError(Exception):
    """A refused review action. The message is safe to show a user."""


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_review(db, review_id: int) -> Review | None:
    return db.query(Review).filter(Review.id == review_id).first()


def review_by(db, course_id: int, student_id: int) -> Review | None:
    return (
        db.query(Review)
        .filter(Review.course_id == course_id, Review.student_id == student_id)
        .first()
    )


def list_reviews(db, course_id: int, published_only: bool = True) -> list[Review]:
    query = db.query(Review).filter(Review.course_id == course_id)
    if published_only:
        query = query.filter(Review.is_published.is_(True))
    return query.order_by(Review.updated_at.desc(), Review.id.desc()).all()


def reviews_for_teacher(db, teacher: User, published_only: bool = False) -> list[Review]:
    """Everything students said about this teacher's subjects, newest first."""
    course_ids = [cid for (cid,) in _teacher_course_ids(db, teacher)]
    if not course_ids:
        return []
    query = db.query(Review).filter(Review.course_id.in_(course_ids))
    if published_only:
        query = query.filter(Review.is_published.is_(True))
    return query.order_by(Review.updated_at.desc(), Review.id.desc()).all()


def _teacher_course_ids(db, teacher: User):
    query = db.query(Course.id)
    if teacher.role != Role.admin:
        query = query.filter(Course.teacher_id == teacher.id)
    return query.all()


# --------------------------------------------------------------------------
# Aggregates
# --------------------------------------------------------------------------

def summary(db, course_id: int) -> dict:
    """Average, count and the 1-5 spread, over published reviews only."""
    rows = (
        db.query(Review.rating, func.count(Review.id))
        .filter(Review.course_id == course_id, Review.is_published.is_(True))
        .group_by(Review.rating)
        .all()
    )

    distribution = {star: 0 for star in range(MIN_RATING, MAX_RATING + 1)}
    total = 0
    weighted = 0
    for rating, count in rows:
        distribution[rating] = count
        total += count
        weighted += rating * count

    return {
        "count": total,
        "average": round(weighted / total, 1) if total else 0,
        "distribution": distribution,
    }


def summaries_for(db, course_ids: list[int]) -> dict[int, dict]:
    """Averages for many courses in one query.

    The catalogue renders dozens of cards; asking per card would be dozens of
    round trips for a number that is on the same table.
    """
    if not course_ids:
        return {}

    rows = (
        db.query(
            Review.course_id,
            func.avg(Review.rating),
            func.count(Review.id),
        )
        .filter(Review.course_id.in_(course_ids), Review.is_published.is_(True))
        .group_by(Review.course_id)
        .all()
    )
    found = {
        course_id: {"average": round(float(avg or 0), 1), "count": count}
        for course_id, avg, count in rows
    }
    # Courses with no reviews still need an entry, so templates never branch on
    # a missing key.
    return {cid: found.get(cid, {"average": 0, "count": 0}) for cid in course_ids}


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def _assert_can_review(db, course: Course, student: User) -> None:
    if can_manage(course, student):
        raise FeedbackError("You cannot review a subject you teach.")
    if student.role != Role.student:
        raise FeedbackError("Only students can leave a review.")
    if not has_access(db, course, student):
        raise FeedbackError(
            "Enroll in this subject, or join its track, before reviewing it."
        )


def upsert_review(db, course: Course, student: User, data) -> Review:
    """Create this student's review, or update the one they already left."""
    _assert_can_review(db, course, student)

    if not (MIN_RATING <= data.rating <= MAX_RATING):
        raise FeedbackError(f"Give a rating between {MIN_RATING} and {MAX_RATING}.")

    review = review_by(db, course.id, student.id)
    if review is None:
        review = Review(course_id=course.id, student_id=student.id)
        db.add(review)

    review.rating = data.rating
    review.comment = (data.comment or "").strip() or None
    # Re-publish on edit: a student rewriting a hidden review deserves the
    # fresh text to be judged on its own.
    review.is_published = True

    db.commit()
    db.refresh(review)
    return review


def delete_review(db, review: Review) -> None:
    db.delete(review)
    db.commit()


def set_published(db, review: Review, published: bool) -> Review:
    """Moderation. Hides or restores; never touches the text."""
    review.is_published = published
    db.commit()
    db.refresh(review)
    return review


def require_moderate(db, review: Review, user: User) -> Course:
    """Only the subject's teacher, or an admin, may hide a review of it."""
    course = db.query(Course).filter(Course.id == review.course_id).first()
    if not course:
        raise AccessDenied("That subject no longer exists.")
    if not can_manage(course, user):
        raise AccessDenied("You can only moderate feedback on subjects you teach.")
    return course
