"""Site administration: people, and the numbers across every course.

Two hazards shape this module, and both are about deletion.

**Deleting a teacher would delete their teaching.** ``User.courses_taught``
cascades with delete-orphan, so ``db.delete(teacher)`` takes their courses with
it -- and each course takes its chapters, lectures, notes, tests and every
*other* student's attempts. That is a catastrophic amount of collateral for one
click, so a teacher who owns anything cannot be deleted until their work is
reassigned or they are simply deactivated instead.

**An admin can lock everyone out.** Removing the last administrator, or
demoting or deactivating yourself, leaves nobody able to undo it. Those are
refused outright rather than confirmed, because a confirmation dialog is no use
once the door has already shut.
"""

from sqlalchemy import func

from app.models import (
    Attempt,
    AttemptStatus,
    ClassSession,
    Course,
    Enrollment,
    Lecture,
    LectureProgress,
    Note,
    Review,
    Role,
    SubStatus,
    Subscription,
    Test,
    Track,
    TrackEnrollment,
    User,
)
from app.services.auth import get_password_hash, validate_credentials


class AdminError(Exception):
    """A refused administrative action. The message is safe to show a user.

    ``reassignable`` tells the caller whether handing this person's work to
    someone else would actually clear the refusal. It is false for a student
    blocked by payment history, where there is nobody to hand anything to.
    """

    def __init__(self, message: str, reassignable: bool = False):
        super().__init__(message)
        self.reassignable = reassignable


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def _count(db, model, *filters) -> int:
    query = db.query(func.count(model.id))
    for condition in filters:
        query = query.filter(condition)
    return query.scalar() or 0


def overview(db) -> dict:
    """Site-wide totals for the admin dashboard."""
    graded = _count(db, Attempt, Attempt.status != AttemptStatus.in_progress)
    percents = [
        row[0] for row in
        db.query(Attempt.percent).filter(Attempt.status != AttemptStatus.in_progress)
    ]

    return {
        "students": _count(db, User, User.role == Role.student),
        "teachers": _count(db, User, User.role == Role.teacher),
        "admins": _count(db, User, User.role == Role.admin),
        "inactive": _count(db, User, User.is_active.is_(False)),
        "tracks": _count(db, Track),
        "tracks_published": _count(db, Track, Track.is_published.is_(True)),
        "courses": _count(db, Course),
        "courses_published": _count(db, Course, Course.is_published.is_(True)),
        "lectures": _count(db, Lecture),
        "notes": _count(db, Note),
        "tests": _count(db, Test),
        "classes": _count(db, ClassSession, ClassSession.is_cancelled.is_(False)),
        "enrollments": _count(db, Enrollment) + _count(db, TrackEnrollment),
        "attempts": graded,
        "open_attempts": _count(db, Attempt, Attempt.status == AttemptStatus.in_progress),
        "average": round(sum(percents) / len(percents), 1) if percents else 0,
    }


def recent_users(db, limit: int = 6) -> list[User]:
    return db.query(User).order_by(User.created_at.desc(), User.id.desc()).limit(limit).all()


def recent_attempts(db, limit: int = 8) -> list[Attempt]:
    return (
        db.query(Attempt)
        .filter(Attempt.status != AttemptStatus.in_progress)
        .order_by(Attempt.submitted_at.desc())
        .limit(limit)
        .all()
    )


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------

def list_users(
    db,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> list[User]:
    query = db.query(User)

    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            User.username.ilike(like)
            | User.full_name.ilike(like)
            | User.email.ilike(like)
        )
    if role in ("student", "teacher", "admin"):
        query = query.filter(User.role == Role(role))
    if status == "active":
        query = query.filter(User.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(User.is_active.is_(False))

    return query.order_by(User.role, User.username).all()


def user_summary(db, user: User) -> dict:
    """The counts that matter when deciding what to do with an account."""
    if user.role in (Role.teacher, Role.admin):
        return {
            "courses": _count(db, Course, Course.teacher_id == user.id),
            "tracks": _count(db, Track, Track.created_by == user.id),
            "classes": _count(db, ClassSession, ClassSession.teacher_id == user.id),
        }
    return {
        "enrollments": _count(db, Enrollment, Enrollment.student_id == user.id),
        "tracks": _count(db, TrackEnrollment, TrackEnrollment.student_id == user.id),
        "attempts": _count(db, Attempt, Attempt.student_id == user.id),
    }


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------

def _admin_count(db) -> int:
    return _count(db, User, User.role == Role.admin, User.is_active.is_(True))


def _assert_not_self(actor: User, target: User, action: str) -> None:
    if actor.id == target.id:
        raise AdminError(f"You cannot {action} your own account.")


def _assert_not_last_admin(db, target: User, action: str) -> None:
    """Refuse anything that would leave the site with no working administrator."""
    if target.role != Role.admin or not target.is_active:
        return
    if _admin_count(db) <= 1:
        raise AdminError(
            f"This is the only active administrator, so it cannot be {action}. "
            "Promote another account to admin first."
        )


def deletion_blockers(db, user: User) -> list[str]:
    """What deletion would destroy that must not be destroyed. Empty means safe.

    For a teacher, courses are the danger: the cascade would take their
    chapters, lectures, notes, tests and every student's attempts too.

    For a student, it is money. A subscription that was ever confirmed is the
    record of a payment, and deleting the person would erase it. Requests that
    never became payments (pending, rejected) are not history and go quietly.
    """
    blockers = []
    courses = _count(db, Course, Course.teacher_id == user.id)
    tracks = _count(db, Track, Track.created_by == user.id)
    paid = _count(
        db,
        Subscription,
        Subscription.student_id == user.id,
        Subscription.status.in_(
            [SubStatus.active, SubStatus.expired, SubStatus.cancelled]
        ),
    )

    if courses:
        blockers.append(f"{courses} course{'' if courses == 1 else 's'}")
    if tracks:
        blockers.append(f"{tracks} track{'' if tracks == 1 else 's'}")
    if paid:
        blockers.append(f"{paid} subscription record{'' if paid == 1 else 's'}")
    return blockers


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def create_user(db, data) -> User:
    username = (data.username or "").strip()
    email = (data.email or "").strip() or None
    full_name = (data.full_name or "").strip() or None

    problem = validate_credentials(db, username, data.password, email)
    if problem:
        raise AdminError(problem)

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        role=Role(data.role),
        is_active=data.is_active,
        hashed_password=get_password_hash(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(db, user: User, data, actor: User) -> User:
    payload = data.model_dump(exclude_unset=True)

    new_role = Role(payload["role"]) if payload.get("role") else user.role
    new_active = payload.get("is_active", user.is_active)

    # Demoting or deactivating yourself is how an admin locks themselves out.
    if user.id == actor.id:
        if new_role != user.role:
            raise AdminError("You cannot change your own role.")
        if not new_active:
            raise AdminError("You cannot deactivate your own account.")

    if user.role == Role.admin and (new_role != Role.admin or not new_active):
        _assert_not_last_admin(db, user, "changed")

    username = (payload.get("username") or user.username).strip()
    email = payload.get("email", user.email)
    email = (email or "").strip() or None

    problem = validate_credentials(db, username, None, email, exclude_id=user.id)
    if problem:
        raise AdminError(problem)

    user.username = username
    user.email = email
    if "full_name" in payload:
        user.full_name = (payload["full_name"] or "").strip() or None
    user.role = new_role
    user.is_active = new_active

    db.commit()
    db.refresh(user)
    return user


def set_password(db, user: User, password: str) -> User:
    if len(password or "") < 8:
        raise AdminError("Password must be at least 8 characters.")
    user.hashed_password = get_password_hash(password)
    db.commit()
    return user


def reassign_content(db, source: User, target: User) -> dict:
    """Hand every course, track and class from one teacher to another.

    The way to remove a teacher without destroying a term's work: move what they
    own, then delete or deactivate the empty account.
    """
    if target.role not in (Role.teacher, Role.admin):
        raise AdminError("Content can only be reassigned to a teacher or admin.")
    if source.id == target.id:
        raise AdminError("Pick a different teacher to reassign to.")

    courses = db.query(Course).filter(Course.teacher_id == source.id).update(
        {"teacher_id": target.id}, synchronize_session=False
    )
    tracks = db.query(Track).filter(Track.created_by == source.id).update(
        {"created_by": target.id}, synchronize_session=False
    )
    classes = db.query(ClassSession).filter(ClassSession.teacher_id == source.id).update(
        {"teacher_id": target.id}, synchronize_session=False
    )
    db.commit()
    return {"courses": courses, "tracks": tracks, "classes": classes}


def delete_user(db, user: User, actor: User) -> dict:
    """Remove an account, refusing anything that would take other work with it."""
    _assert_not_self(actor, user, "delete")
    _assert_not_last_admin(db, user, "deleted")

    blockers = deletion_blockers(db, user)
    if blockers:
        # Teaching can be handed over; a payment record cannot. Say whichever
        # is true rather than offering a fix that does not apply.
        owns_teaching = bool(
            _count(db, Course, Course.teacher_id == user.id)
            or _count(db, Track, Track.created_by == user.id)
        )
        remedy = (
            "Reassign them to another teacher first, or deactivate this account "
            "instead — deleting it would delete that content too."
            if owns_teaching
            else "Deactivate this account instead — they cannot sign in, and the "
                 "payment history stays intact."
        )
        raise AdminError(
            f"{user.display_name} still has {' and '.join(blockers)}. {remedy}",
            reassignable=owns_teaching,
        )

    # Rows that hang off the user by foreign key without a cascading
    # relationship. Left behind, they would point at an id that no longer exists.
    removed = {
        "track_memberships": db.query(TrackEnrollment)
            .filter(TrackEnrollment.student_id == user.id)
            .delete(synchronize_session=False),
        "progress": db.query(LectureProgress)
            .filter(LectureProgress.student_id == user.id)
            .delete(synchronize_session=False),
        # Their reviews go with them, and the affected averages recompute --
        # a rating has to belong to somebody who exists.
        "reviews": db.query(Review)
            .filter(Review.student_id == user.id)
            .delete(synchronize_session=False),
        # Only requests that never became payments reach this point; anything
        # confirmed was refused by deletion_blockers above.
        "requests": db.query(Subscription)
            .filter(Subscription.student_id == user.id)
            .delete(synchronize_session=False),
    }

    # Enrollments and attempts cascade from the relationship; courses cannot
    # exist here because deletion_blockers just proved there are none.
    db.delete(user)
    db.commit()
    return removed
