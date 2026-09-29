"""Live classes and the calendar that shows them.

Two rules shape this module:

* **Times are UTC everywhere on the server.** The browser sends an instant and
  renders an instant; no wall-clock string ever crosses the wire. SQLite gives
  naive datetimes back, so anything read from the database goes through
  ``_as_utc`` before it is compared with `now`.
* **A room is only as private as its name.** The built-in classroom is a public
  Jitsi room, which means anyone who knows the room name can walk in. Room
  names are therefore random and never derived from the course or title, and
  the name is only handed to callers who pass the enrollment check.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from app.config import get_settings
from app.models import (
    ClassSession,
    ClassState,
    Course,
    MeetingProvider,
    Role,
    User,
)
from app.services.course import (
    AccessDenied,
    accessible_course_ids,
    can_manage,
    has_access,
)

settings = get_settings()

# Enough to be unguessable, short enough to read out over a bad connection.
ROOM_BYTES = 16

_URL_RE = re.compile(r"^https://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


class ScheduleError(Exception):
    """A refused scheduling action. The message is safe to show a user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _to_storage(value: datetime) -> datetime:
    """Normalise an incoming instant to naive UTC for the database.

    Pydantic hands us an aware datetime; SQLite would store the offset as text
    and then hand back something that compares unequal to everything else. One
    conversion here keeps every stored value in the same frame.
    """
    if value.tzinfo is None:
        raise ScheduleError("A start time must include a timezone offset.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def get_session(db, session_id: int) -> ClassSession | None:
    return db.query(ClassSession).filter(ClassSession.id == session_id).first()


def _visible_course_ids(db, user: User) -> list[int]:
    """Every course whose classes this user is entitled to see.

    Teachers see the courses they own, admins see everything, students see what
    they are enrolled in. A teacher who is also enrolled somewhere as a student
    gets both, which is why this returns a union rather than branching once.
    """
    if user.role == Role.admin:
        return [cid for (cid,) in db.query(Course.id).all()]

    owned = {cid for (cid,) in db.query(Course.id).filter(Course.teacher_id == user.id)}
    # Reaching a subject through its track counts, so joining a track puts the
    # whole programme's timetable on the student's calendar at once.
    return list(owned | accessible_course_ids(db, user))


def list_sessions_for_user(
    db,
    user: User,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ClassSession]:
    """Classes visible to ``user``, optionally windowed to [start, end)."""
    course_ids = _visible_course_ids(db, user)
    if not course_ids:
        return []

    query = db.query(ClassSession).filter(ClassSession.course_id.in_(course_ids))
    if start is not None:
        query = query.filter(ClassSession.starts_at >= _to_storage(start))
    if end is not None:
        query = query.filter(ClassSession.starts_at < _to_storage(end))
    return query.order_by(ClassSession.starts_at).all()


def list_sessions_for_course(db, course_id: int) -> list[ClassSession]:
    return (
        db.query(ClassSession)
        .filter(ClassSession.course_id == course_id)
        .order_by(ClassSession.starts_at)
        .all()
    )


def upcoming_for_user(db, user: User, limit: int = 5) -> list[ClassSession]:
    """The next few classes that have not finished yet, soonest first.

    Filtered on ``join_closes_at`` rather than the start time so a class that is
    running right now still counts as upcoming -- that is precisely the one the
    dashboard most needs to show.
    """
    cutoff = _now() - timedelta(minutes=settings.class_join_lead_minutes + 240)
    rows = [
        s
        for s in list_sessions_for_user(db, user, start=cutoff)
        if not s.is_cancelled and s.state in (ClassState.upcoming, ClassState.live)
    ]
    return rows[:limit]


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------

def require_view(db, session: ClassSession, course: Course, user: User) -> ClassSession:
    """Readable if you teach the course, administer it, or are enrolled."""
    if not session:
        raise AccessDenied("That class no longer exists.")
    if can_manage(course, user):
        return session
    if not has_access(db, course, user):
        raise AccessDenied("Enroll in this subject, or join its track, to attend.")
    return session


def can_join(session: ClassSession, course: Course, user: User) -> tuple[bool, str]:
    """(allowed, reason). The reason is written to be shown to the user.

    A teacher may open their own room at any time -- setting up before students
    arrive is normal. Students are held to the join window so a room cannot be
    used as an unsupervised hangout for the fortnight before the lesson.
    """
    if session.is_cancelled:
        return False, "This class was cancelled."
    if can_manage(course, user):
        return True, ""

    state = session.state
    if state == ClassState.upcoming:
        return False, "The room opens shortly before the class starts."
    if state == ClassState.ended:
        return False, "This class has finished."
    return True, ""


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def new_room_name() -> str:
    """A random room name. Never derived from the course -- see module docstring."""
    return f"learnhub-{uuid.uuid4().hex[:ROOM_BYTES]}"


def _validated_external_url(url: str | None) -> str:
    url = (url or "").strip()
    if not url:
        raise ScheduleError("Paste the meeting link, or use a built-in room instead.")
    if not _URL_RE.match(url):
        raise ScheduleError("That does not look like a valid https:// meeting link.")
    return url


def create_session(db, course: Course, data, teacher: User) -> ClassSession:
    starts_at = _to_storage(data.starts_at)

    session = ClassSession(
        course_id=course.id,
        teacher_id=teacher.id,
        title=data.title.strip(),
        description=(data.description or "").strip() or None,
        starts_at=starts_at,
        duration_minutes=data.duration_minutes,
        provider=data.provider,
    )

    if data.provider == MeetingProvider.external:
        session.meeting_url = _validated_external_url(data.meeting_url)
    else:
        session.room_name = new_room_name()

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def update_session(db, session: ClassSession, data) -> ClassSession:
    payload = data.model_dump(exclude_unset=True)

    if "starts_at" in payload and payload["starts_at"] is not None:
        payload["starts_at"] = _to_storage(payload["starts_at"])

    provider = payload.get("provider", session.provider)
    if provider == MeetingProvider.external:
        # Switching to an external link, or editing one, must not leave the old
        # value in place -- a stale link silently sends students nowhere.
        url = payload.get("meeting_url", session.meeting_url)
        payload["meeting_url"] = _validated_external_url(url)
        session.room_name = None
    else:
        payload["meeting_url"] = None
        if not session.room_name:
            session.room_name = new_room_name()

    for field, value in payload.items():
        if value is not None or field in ("description", "meeting_url"):
            setattr(session, field, value)

    db.commit()
    db.refresh(session)
    return session


def cancel_session(db, session: ClassSession) -> ClassSession:
    """Cancel rather than delete, so students see it disappear with a reason."""
    session.is_cancelled = True
    db.commit()
    db.refresh(session)
    return session


def delete_session(db, session: ClassSession) -> None:
    db.delete(session)
    db.commit()


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------

def join_url(session: ClassSession) -> str | None:
    """Where a participant actually goes. None if nothing is configured yet."""
    if session.provider == MeetingProvider.external:
        return session.meeting_url
    if not session.room_name:
        return None
    return f"https://{settings.meet_domain}/{session.room_name}"


def embed_url(session: ClassSession, user: User) -> str | None:
    """The built-in room, pre-configured for an iframe.

    The name is passed through so participants show up as themselves rather
    than "Fellow Jitster", and the pre-join screen is skipped because the app
    has already decided this person is allowed in.
    """
    if session.provider != MeetingProvider.builtin:
        return None
    base = join_url(session)
    if not base:
        return None
    name = quote(f'"{user.display_name}"', safe="")
    return (
        f"{base}#config.prejoinPageEnabled=false"
        f"&config.disableDeepLinking=true"
        f"&userInfo.displayName={name}"
    )


def to_payload(session: ClassSession, user: User, course: Course | None = None) -> dict:
    """One class, shaped for the calendar's JavaScript.

    ``roomUrl`` is omitted unless the caller may actually join right now, so an
    unguessable room name never sits in the page source of someone who is not
    entitled to walk in.
    """
    course = course or session.course
    manage = can_manage(course, user)
    allowed, reason = can_join(session, course, user)

    return {
        "id": session.id,
        "courseId": course.id,
        "courseTitle": course.title,
        "courseSlug": course.slug,
        "accent": course.accent or "indigo",
        "title": session.title,
        "description": session.description or "",
        "startsAt": session.starts_at_utc.isoformat(),
        "endsAt": session.ends_at.isoformat(),
        "durationMinutes": session.duration_minutes,
        "provider": session.provider.value,
        "state": session.state.value,
        "teacher": session.teacher.display_name if session.teacher else "",
        "canManage": manage,
        "canJoin": allowed,
        "joinReason": reason,
        "joinPath": f"/classes/{session.id}" if allowed else None,
        # Only the owner needs the raw link, and only to display it.
        "meetingUrl": session.meeting_url if manage else None,
    }
