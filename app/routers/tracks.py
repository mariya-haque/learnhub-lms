"""Tracks: the student-facing programme catalogue and one track's detail page.

Both roles read these pages. A teacher sees their own unpublished tracks here
too, so the thing they are building is visible from the same place students
will eventually see it.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user, require_user_api
from app.services import assessment as assessment_service
from app.services import billing as billing_service
from app.services import chapter as chapter_service
from app.services import content as content_service
from app.services import course as course_service
from app.services import feedback as feedback_service
from app.services import track as track_service
from app.templating import templates

router = APIRouter(prefix="/tracks", tags=["tracks"])


def _deny(request, current_user, message, status_code=403):
    template = "errors/404.html" if status_code == 404 else "errors/403.html"
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"current_user": current_user, "message": message},
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
async def catalogue(
    request: Request,
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tracks = track_service.list_published_tracks(db, search=q)

    # A teacher's own drafts belong in this list too, marked as drafts, so the
    # programme they are assembling is not invisible until the moment it ships.
    if current_user.is_teacher:
        published_ids = {t.id for t in tracks}
        drafts = [
            t
            for t in track_service.list_tracks_for_teacher(db, current_user)
            if t.id not in published_ids
        ]
        tracks = tracks + drafts

    joined = {t.id for t in track_service.list_tracks_for_student(db, current_user)}

    cards = [
        {
            "track": track,
            "stats": track_service.track_stats(db, track.id),
            "joined": track.id in joined,
            "can_manage": track_service.can_manage(track, current_user),
        }
        for track in tracks
    ]

    return templates.TemplateResponse(
        request=request,
        name="tracks.html",
        context={
            "current_user": current_user,
            "cards": cards,
            "q": q or "",
            "can_create": current_user.is_teacher,
        },
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def track_detail(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    track = track_service.get_track_by_slug(db, slug)
    if not track:
        return _deny(request, current_user, "That track no longer exists.", 404)

    manageable = track_service.can_manage(track, current_user)
    if not track.is_published and not manageable:
        return _deny(request, current_user, "That track is not available yet.")

    joined = track_service.is_member(db, track.id, current_user.id)
    subjects = track_service.list_subjects(db, track.id, published_only=not manageable)

    # Each subject carries its chapter outline, so the page shows the whole
    # track -> subject -> chapter shape without a click per subject.
    ratings = feedback_service.summaries_for(db, [s.id for s in subjects])
    rows = []
    for subject in subjects:
        show_all = course_service.can_manage(subject, current_user)
        lectures = content_service.list_lectures(
            db, subject.id, published_only=not show_all
        )
        notes = content_service.list_notes(db, subject.id)
        tests = assessment_service.list_tests(
            db, subject.id, published_only=not show_all
        )
        rows.append({
            "subject": subject,
            "outline": chapter_service.outline(
                db, subject.id, lectures, notes, tests,
                published_only=not show_all,
            ),
            "stats": course_service.course_stats(db, subject.id),
            "progress": (
                course_service.course_progress(db, subject.id, current_user.id)
                if joined or course_service.is_enrolled(db, subject.id, current_user.id)
                else None
            ),
            "can_open": course_service.has_access(db, subject, current_user),
            "rating": ratings.get(subject.id, {"average": 0, "count": 0}),
        })

    entitled = billing_service.is_entitled(db, track, current_user)

    return templates.TemplateResponse(
        request=request,
        name="track_detail.html",
        context={
            "current_user": current_user,
            "track": track,
            "rows": rows,
            "joined": joined,
            "can_manage": manageable,
            "entitled": entitled,
            "plans": (
                billing_service.list_plans(db, track.id, active_only=True)
                if track.requires_subscription else []
            ),
            "subscription": billing_service.active_subscription(
                db, track.id, current_user.id
            ),
            "pending": billing_service.pending_subscription(
                db, track.id, current_user.id
            ),
            "stats": track_service.track_stats(db, track.id),
        },
    )


# --------------------------------------------------------------------------
# Membership
# --------------------------------------------------------------------------

@router.post("/{track_id}/join")
async def join_track(
    track_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    track = track_service.get_track(db, track_id)
    if not track:
        return JSONResponse(status_code=404, content={"message": "Track not found."})
    try:
        track_service.join(db, track, current_user)
    except course_service.AccessDenied as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})

    count = len(track_service.list_subjects(db, track.id, published_only=True))
    return {
        "message": f"Joined. {count} subject{'' if count == 1 else 's'} unlocked.",
        "slug": track.slug,
    }


@router.post("/{track_id}/leave")
async def leave_track(
    track_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    track = track_service.get_track(db, track_id)
    if not track:
        return JSONResponse(status_code=404, content={"message": "Track not found."})
    track_service.leave(db, track, current_user)
    return {"message": "Left the track."}


@router.get("/{slug}/join-redirect", response_class=RedirectResponse)
async def join_redirect(
    slug: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Non-JS fallback, matching the course catalogue's."""
    track = track_service.get_track_by_slug(db, slug)
    if track:
        try:
            track_service.join(db, track, current_user)
        except course_service.AccessDenied:
            pass
        return RedirectResponse(url=f"/tracks/{track.slug}", status_code=302)
    return RedirectResponse(url="/tracks", status_code=302)
