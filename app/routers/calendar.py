"""The shared calendar and the live classroom.

Students and teachers hit the same page and the same events endpoint; what
differs is only which courses each may see, which is decided in
``services/schedule.py`` rather than here.

The classroom route is the sensitive one. It is the only place that hands out a
room URL, and it does so after re-checking both enrollment and the join window,
because a room name is a bearer token: whoever has it can walk in.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MeetingProvider
from app.routers.auth import get_current_user, require_user_api
from app.services import course as course_service
from app.services import schedule as schedule_service
from app.templating import templates

router = APIRouter(tags=["calendar"])


def _deny(request, current_user, message, status_code=403):
    return templates.TemplateResponse(
        request=request,
        name="errors/403.html",
        context={"current_user": current_user, "message": message},
        status_code=status_code,
    )


def _parse_instant(value: str | None) -> datetime | None:
    """Parse an ISO-8601 instant from the query string, tolerating a 'Z'."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# The calendar
# --------------------------------------------------------------------------

@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Teachers need their course list to populate the "schedule a class" form;
    # students never see that form, so they never need it.
    courses = (
        course_service.list_courses_for_teacher(db, current_user)
        if current_user.is_teacher
        else []
    )

    upcoming = schedule_service.upcoming_for_user(db, current_user, limit=6)

    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context={
            "current_user": current_user,
            "upcoming": [
                schedule_service.to_payload(s, current_user) for s in upcoming
            ],
            "courses": [
                {"id": c.id, "title": c.title, "accent": c.accent or "indigo"}
                for c in courses
            ],
            "can_schedule": bool(courses),
        },
    )


@router.get("/calendar/api/events")
async def api_events(
    start: str | None = Query(None),
    end: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    """Every class visible to the caller inside [start, end).

    The window is optional; without it the endpoint answers with a sane band
    around today rather than the whole table.
    """
    window_start = _parse_instant(start) or datetime.now(timezone.utc) - timedelta(days=45)
    window_end = _parse_instant(end) or window_start + timedelta(days=120)

    sessions = schedule_service.list_sessions_for_user(
        db, current_user, start=window_start, end=window_end
    )
    return {
        "events": [schedule_service.to_payload(s, current_user) for s in sessions]
    }


# --------------------------------------------------------------------------
# The classroom
# --------------------------------------------------------------------------

@router.get("/classes/{session_id}", response_class=HTMLResponse)
async def classroom(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    session = schedule_service.get_session(db, session_id)
    if not session:
        return _deny(request, current_user, "That class no longer exists.", 404)

    course = course_service.get_course(db, session.course_id)
    try:
        schedule_service.require_view(db, session, course, current_user)
    except course_service.AccessDenied as exc:
        return _deny(request, current_user, str(exc))

    allowed, reason = schedule_service.can_join(session, course, current_user)
    url = schedule_service.join_url(session) if allowed else None

    if allowed and not url:
        allowed = False
        reason = "This class has no meeting link yet. Ask the teacher to add one."

    return templates.TemplateResponse(
        request=request,
        name="classroom.html",
        context={
            "current_user": current_user,
            "session": session,
            "course": course,
            "allowed": allowed,
            "reason": reason,
            "join_url": url,
            "embed_url": schedule_service.embed_url(session, current_user) if allowed else None,
            "is_builtin": session.provider == MeetingProvider.builtin,
            "payload": schedule_service.to_payload(session, current_user, course),
        },
    )


@router.get("/classes/{session_id}/status")
async def api_class_status(
    session_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    """Polled by a waiting student so the page can unlock itself on time.

    Without this, someone who opens a class five minutes early has to guess
    when to refresh.
    """
    session = schedule_service.get_session(db, session_id)
    if not session:
        return JSONResponse(status_code=404, content={"message": "Class not found."})

    course = course_service.get_course(db, session.course_id)
    try:
        schedule_service.require_view(db, session, course, current_user)
    except course_service.AccessDenied as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})

    allowed, reason = schedule_service.can_join(session, course, current_user)
    return {
        "state": session.state.value,
        "canJoin": allowed,
        "reason": reason,
        "startsAt": session.starts_at_utc.isoformat(),
    }
