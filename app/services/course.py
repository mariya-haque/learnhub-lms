"""Courses and enrollment.

Access control lives here rather than in the routers so that every caller --
HTML page, JSON endpoint or seeder -- goes through the same checks.
"""

import re

from sqlalchemy import func

from app.models import (
    Course,
    Enrollment,
    Lecture,
    LectureProgress,
    Role,
    SubStatus,
    Subscription,
    Test,
    Track,
    TrackEnrollment,
    User,
)


class AccessDenied(Exception):
    """The user may not touch this course."""


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return slug or "course"


def unique_slug(db, title: str, exclude_id: int | None = None) -> str:
    """A URL-safe slug, suffixed with -2, -3 ... if the base is taken."""
    base = slugify(title)
    candidate = base
    n = 1
    while True:
        query = db.query(Course).filter(Course.slug == candidate)
        if exclude_id:
            query = query.filter(Course.id != exclude_id)
        if not query.first():
            return candidate
        n += 1
        candidate = f"{base}-{n}"


def get_course(db, course_id: int):
    return db.query(Course).filter(Course.id == course_id).first()


def get_course_by_slug(db, slug: str):
    return db.query(Course).filter(Course.slug == slug).first()


def list_published_courses(db, search: str | None = None, subject: str | None = None):
    query = db.query(Course).filter(Course.is_published.is_(True))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(
            Course.title.ilike(like) | Course.description.ilike(like)
        )
    if subject:
        query = query.filter(Course.subject == subject)
    return query.order_by(Course.created_at.desc()).all()


def list_subjects(db) -> list[str]:
    rows = (
        db.query(Course.subject)
        .filter(Course.is_published.is_(True), Course.subject.isnot(None))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]})


def list_courses_for_teacher(db, teacher: User):
    query = db.query(Course)
    if teacher.role != Role.admin:
        query = query.filter(Course.teacher_id == teacher.id)
    return query.order_by(Course.created_at.desc()).all()


def list_courses_for_student(db, student: User):
    """Everything the student can open, however they got in.

    Two routes lead here -- enrolling in the course directly, or joining a track
    that contains it -- and a dashboard has no business distinguishing them.
    """
    ids = accessible_course_ids(db, student)
    if not ids:
        return []
    return db.query(Course).filter(Course.id.in_(ids)).order_by(Course.title).all()


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------

def can_manage(course: Course, user: User) -> bool:
    """A teacher owns their own courses; an admin owns all of them."""
    if user.role == Role.admin:
        return True
    return course.teacher_id == user.id


def require_manage(course: Course, user: User) -> Course:
    if not course:
        raise AccessDenied("That course no longer exists.")
    if not can_manage(course, user):
        raise AccessDenied("You can only manage courses you teach.")
    return course


def is_enrolled(db, course_id: int, student_id: int) -> bool:
    """Direct, per-course enrollment only.

    Kept narrow on purpose: this is what the Enroll/Leave button reflects, and
    a track member has nothing here to unenroll from. Use ``has_access`` to ask
    the broader question of whether someone may open the content.
    """
    return (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == course_id,
            Enrollment.student_id == student_id,
        )
        .first()
        is not None
    )


def _entitled_track_ids(db, student_id: int) -> set[int]:
    """Tracks whose paywall this student is currently past.

    Free tracks are in by definition. A paid track needs a subscription that is
    both ``active`` *and* still inside its window -- a row that lapsed
    overnight still says active until something notices, and the thing that
    notices must not be the access check waving it through.
    """
    free = {tid for (tid,) in
            db.query(Track.id).filter(Track.requires_subscription.is_(False))}

    paid = db.query(Subscription).filter(
        Subscription.student_id == student_id,
        Subscription.status == SubStatus.active,
    ).all()
    return free | {s.track_id for s in paid if s.is_current}


def is_track_member(db, course: Course, student_id: int) -> bool:
    """True when the student reaches this course through its track.

    Membership alone is not enough on a paid track: someone who joined while it
    was free, or whose subscription has run out, is still a member but is no
    longer entitled.
    """
    if not course.track_id:
        return False
    member = (
        db.query(TrackEnrollment)
        .filter(
            TrackEnrollment.track_id == course.track_id,
            TrackEnrollment.student_id == student_id,
        )
        .first()
        is not None
    )
    if not member:
        return False
    return course.track_id in _entitled_track_ids(db, student_id)


def accessible_course_ids(db, student: User) -> set[int]:
    """Every course id the student may open, by either route."""
    direct = {
        cid for (cid,) in
        db.query(Enrollment.course_id).filter(Enrollment.student_id == student.id)
    }

    entitled = _entitled_track_ids(db, student.id)
    via_track = {
        cid for (cid, track_id) in
        db.query(Course.id, Course.track_id)
        .join(TrackEnrollment, TrackEnrollment.track_id == Course.track_id)
        .filter(TrackEnrollment.student_id == student.id)
        if track_id in entitled
    }
    return direct | via_track


def has_access(db, course: Course, user: User) -> bool:
    """Can this user open the course content at all?"""
    if can_manage(course, user):
        return True
    if not course.is_published:
        return False
    return is_enrolled(db, course.id, user.id) or is_track_member(db, course, user.id)


def require_access(db, course: Course, user: User) -> Course:
    """Readable if you teach it, administer it, are enrolled, or joined its track."""
    if not course:
        raise AccessDenied("That course no longer exists.")
    if can_manage(course, user):
        return course
    if not course.is_published:
        raise AccessDenied("That course is not available yet.")
    if not has_access(db, course, user):
        raise AccessDenied(
            "Enroll in this subject, or join its track, to open its content."
        )
    return course


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def create_course(db, data, teacher: User) -> Course:
    course = Course(
        title=data.title,
        slug=unique_slug(db, data.title),
        description=data.description,
        subject=data.subject,
        accent=data.accent or "indigo",
        is_published=data.is_published,
        teacher_id=teacher.id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def update_course(db, course: Course, data) -> Course:
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] != course.title:
        course.slug = unique_slug(db, payload["title"], exclude_id=course.id)
    for field, value in payload.items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


def delete_course(db, course: Course) -> None:
    """Cascades to lectures, notes, tests, attempts and enrollments.

    Stored files are removed by the caller, which knows about storage.
    """
    db.delete(course)
    db.commit()


def enroll(db, course: Course, student: User) -> Enrollment:
    existing = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == course.id,
            Enrollment.student_id == student.id,
        )
        .first()
    )
    if existing:
        return existing
    if not course.is_published:
        raise AccessDenied("That course is not open for enrollment yet.")
    enrollment = Enrollment(course_id=course.id, student_id=student.id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def unenroll(db, course: Course, student: User) -> None:
    db.query(Enrollment).filter(
        Enrollment.course_id == course.id,
        Enrollment.student_id == student.id,
    ).delete()
    db.commit()


# --------------------------------------------------------------------------
# Stats used by the course cards and dashboards
# --------------------------------------------------------------------------

def enrollment_count(db, course_id: int) -> int:
    return (
        db.query(func.count(Enrollment.id))
        .filter(Enrollment.course_id == course_id)
        .scalar()
        or 0
    )


def course_stats(db, course_id: int) -> dict:
    lectures = (
        db.query(func.count(Lecture.id))
        .filter(Lecture.course_id == course_id, Lecture.is_published.is_(True))
        .scalar()
        or 0
    )
    tests = (
        db.query(func.count(Test.id))
        .filter(Test.course_id == course_id, Test.is_published.is_(True))
        .scalar()
        or 0
    )
    return {
        "lectures": lectures,
        "tests": tests,
        "students": enrollment_count(db, course_id),
    }


def course_progress(db, course_id: int, student_id: int) -> dict:
    """How much of a course's published lectures a student has finished."""
    total = (
        db.query(func.count(Lecture.id))
        .filter(Lecture.course_id == course_id, Lecture.is_published.is_(True))
        .scalar()
        or 0
    )
    done = (
        db.query(func.count(LectureProgress.id))
        .join(Lecture, Lecture.id == LectureProgress.lecture_id)
        .filter(
            Lecture.course_id == course_id,
            Lecture.is_published.is_(True),
            LectureProgress.student_id == student_id,
            LectureProgress.completed.is_(True),
        )
        .scalar()
        or 0
    )
    percent = round((done / total) * 100) if total else 0
    return {"total": total, "completed": done, "percent": percent}
