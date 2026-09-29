"""Tracks: exam programmes that group subjects.

The hierarchy is track -> subject -> chapter -> content. A *subject* is a
``Course`` carrying a ``track_id``; nothing about a course changes by joining a
track, which is why every existing course, page and URL still works.

Membership is the interesting part. Joining a track is stored once, against the
track, rather than fanned out into per-course rows -- so a subject added next
term is unlocked for existing members with no backfill, and leaving a track
does not silently drop individual course enrollments a student made themselves.
"""

from sqlalchemy import func

from app.models import Course, Role, Track, TrackEnrollment, User
from app.services.course import AccessDenied, slugify


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def unique_slug(db, title: str, exclude_id: int | None = None) -> str:
    base = slugify(title)
    candidate = base
    n = 1
    while True:
        query = db.query(Track).filter(Track.slug == candidate)
        if exclude_id:
            query = query.filter(Track.id != exclude_id)
        if not query.first():
            return candidate
        n += 1
        candidate = f"{base}-{n}"


def get_track(db, track_id: int) -> Track | None:
    return db.query(Track).filter(Track.id == track_id).first()


def get_track_by_slug(db, slug: str) -> Track | None:
    return db.query(Track).filter(Track.slug == slug).first()


def list_published_tracks(db, search: str | None = None) -> list[Track]:
    query = db.query(Track).filter(Track.is_published.is_(True))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(Track.title.ilike(like) | Track.description.ilike(like))
    return query.order_by(Track.title).all()


def list_tracks_for_teacher(db, teacher: User) -> list[Track]:
    """Tracks this teacher may edit: their own, or everything for an admin."""
    query = db.query(Track)
    if teacher.role != Role.admin:
        query = query.filter(Track.created_by == teacher.id)
    return query.order_by(Track.title).all()


def list_subjects(db, track_id: int, published_only: bool = False) -> list[Course]:
    query = db.query(Course).filter(Course.track_id == track_id)
    if published_only:
        query = query.filter(Course.is_published.is_(True))
    return query.order_by(Course.title).all()


def list_tracks_for_student(db, student: User) -> list[Track]:
    return (
        db.query(Track)
        .join(TrackEnrollment, TrackEnrollment.track_id == Track.id)
        .filter(TrackEnrollment.student_id == student.id)
        .order_by(Track.title)
        .all()
    )


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------

def can_manage(track: Track, user: User) -> bool:
    if user.role == Role.admin:
        return True
    return track.created_by == user.id


def require_manage(track: Track, user: User) -> Track:
    if not track:
        raise AccessDenied("That track no longer exists.")
    if not can_manage(track, user):
        raise AccessDenied("You can only manage tracks you created.")
    return track


def is_member(db, track_id: int, student_id: int) -> bool:
    return (
        db.query(TrackEnrollment)
        .filter(
            TrackEnrollment.track_id == track_id,
            TrackEnrollment.student_id == student_id,
        )
        .first()
        is not None
    )


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------

def join(db, track: Track, student: User) -> TrackEnrollment:
    existing = (
        db.query(TrackEnrollment)
        .filter(
            TrackEnrollment.track_id == track.id,
            TrackEnrollment.student_id == student.id,
        )
        .first()
    )
    if existing:
        return existing
    if not track.is_published:
        raise AccessDenied("That track is not open for enrollment yet.")

    # Imported here rather than at module scope: billing reads tracks, so a
    # top-level import would close the loop between the two services.
    from app.services import billing

    if not billing.is_entitled(db, track, student):
        raise AccessDenied(
            "This track needs a subscription. Choose a plan to request access."
        )

    membership = TrackEnrollment(track_id=track.id, student_id=student.id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def leave(db, track: Track, student: User) -> None:
    """Drop track membership only.

    Any per-subject enrollment the student made on their own is left alone --
    leaving a programme should not quietly unenroll someone from a course they
    joined separately.
    """
    db.query(TrackEnrollment).filter(
        TrackEnrollment.track_id == track.id,
        TrackEnrollment.student_id == student.id,
    ).delete()
    db.commit()


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def create_track(db, data, owner: User) -> Track:
    track = Track(
        title=data.title.strip(),
        slug=unique_slug(db, data.title),
        code=(data.code or "").strip() or None,
        description=data.description,
        accent=data.accent or "indigo",
        is_published=data.is_published,
        created_by=owner.id,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def update_track(db, track: Track, data) -> Track:
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] != track.title:
        track.slug = unique_slug(db, payload["title"], exclude_id=track.id)
    for field, value in payload.items():
        setattr(track, field, value)
    db.commit()
    db.refresh(track)
    return track


def delete_track(db, track: Track) -> None:
    """Remove the programme, not the teaching.

    Subjects are detached rather than deleted -- a track is a grouping, and
    deleting one must never take a term's lectures and tests with it.

    A track anyone has ever subscribed to cannot be removed at all: those rows
    are the record of money changing hands, and they are meaningless without
    the thing they paid for.
    """
    from app.models import Subscription

    sold = db.query(Subscription).filter(Subscription.track_id == track.id).count()
    if sold:
        raise AccessDenied(
            f"This track has {sold} subscription record(s) and cannot be deleted. "
            "Unpublish it instead — the payment history has to stay."
        )

    db.query(Course).filter(Course.track_id == track.id).update({"track_id": None})
    db.delete(track)
    db.commit()


def add_subject(db, track: Track, course: Course) -> Course:
    """Put a course into a track. Callers must have proved they own both."""
    if course.track_id == track.id:
        return course
    course.track_id = track.id
    db.commit()
    db.refresh(course)
    return course


def remove_subject(db, course: Course) -> Course:
    course.track_id = None
    db.commit()
    db.refresh(course)
    return course


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def member_count(db, track_id: int) -> int:
    return (
        db.query(func.count(TrackEnrollment.id))
        .filter(TrackEnrollment.track_id == track_id)
        .scalar()
        or 0
    )


def track_stats(db, track_id: int) -> dict:
    """Totals for a track card: subjects, chapters, and everything inside them."""
    from app.models import Chapter, Lecture, Test

    subject_ids = [cid for (cid,) in
                   db.query(Course.id).filter(Course.track_id == track_id)]
    if not subject_ids:
        return {"subjects": 0, "chapters": 0, "lectures": 0, "tests": 0,
                "students": member_count(db, track_id)}

    def count(model, extra=None):
        query = db.query(func.count(model.id)).filter(model.course_id.in_(subject_ids))
        if extra is not None:
            query = query.filter(extra)
        return query.scalar() or 0

    return {
        "subjects": len(subject_ids),
        "chapters": count(Chapter),
        "lectures": count(Lecture, Lecture.is_published.is_(True)),
        "tests": count(Test, Test.is_published.is_(True)),
        "students": member_count(db, track_id),
    }


