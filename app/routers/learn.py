"""The lecture player and watch-progress tracking."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user, require_user_api
from app.schemas import ProgressPing
from app.services import content as content_service
from app.services import course as course_service
from app.templating import templates

router = APIRouter(prefix="/learn", tags=["learn"])


@router.get("/{lecture_id}", response_class=HTMLResponse)
async def player(
    lecture_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture:
        return templates.TemplateResponse(
            request=request,
            name="errors/404.html",
            context={"current_user": current_user},
            status_code=404,
        )

    course = course_service.get_course(db, lecture.course_id)
    try:
        course_service.require_access(db, course, current_user)
    except course_service.AccessDenied as exc:
        return templates.TemplateResponse(
            request=request,
            name="errors/403.html",
            context={"current_user": current_user, "message": str(exc), "course": course},
            status_code=403,
        )

    manageable = course_service.can_manage(course, current_user)
    published_only = not manageable

    # How the <video>/<iframe> should be rendered.
    if lecture.source_type.value == "upload":
        media_kind, media_url = "file", f"/files/video/{lecture.id}"
    else:
        media_kind, media_url = content_service.normalise_embed_url(lecture.video_url or "")

    previous, nxt = content_service.adjacent_lectures(
        db, lecture, published_only=published_only
    )
    siblings = content_service.list_lectures(
        db, course.id, published_only=published_only
    )
    progress = content_service.progress_map(db, course.id, current_user.id)
    entry = progress.get(lecture.id)

    return templates.TemplateResponse(
        request=request,
        name="learn.html",
        context={
            "current_user": current_user,
            "course": course,
            "lecture": lecture,
            "lectures": siblings,
            "progress": progress,
            "entry": entry,
            "resume_at": (entry.last_position_seconds if entry else 0) or 0,
            "completed": bool(entry and entry.completed),
            "media_kind": media_kind,
            "media_url": media_url,
            "prev_lecture": previous,
            "next_lecture": nxt,
            "notes": content_service.list_notes(db, course.id, lecture_id=lecture.id),
            "summary": course_service.course_progress(db, course.id, current_user.id),
        },
    )


@router.post("/api/{lecture_id}/progress")
async def save_progress(
    lecture_id: int,
    payload: ProgressPing,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture:
        return JSONResponse(status_code=404, content={"message": "Lecture not found."})

    course = course_service.get_course(db, lecture.course_id)
    try:
        course_service.require_access(db, course, current_user)
    except course_service.AccessDenied as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})

    entry = content_service.record_progress(db, lecture, current_user.id, payload)
    summary = course_service.course_progress(db, course.id, current_user.id)
    return {
        "completed": entry.completed,
        "position": entry.last_position_seconds,
        "course_percent": summary["percent"],
    }


@router.post("/api/{lecture_id}/complete")
async def toggle_complete(
    lecture_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture:
        return JSONResponse(status_code=404, content={"message": "Lecture not found."})

    course = course_service.get_course(db, lecture.course_id)
    try:
        course_service.require_access(db, course, current_user)
    except course_service.AccessDenied as exc:
        return JSONResponse(status_code=403, content={"message": str(exc)})

    existing = content_service.get_progress(db, lecture.id, current_user.id)
    entry = content_service.set_completed(
        db, lecture, current_user.id, not (existing and existing.completed)
    )
    summary = course_service.course_progress(db, course.id, current_user.id)
    return {"completed": entry.completed, "course_percent": summary["percent"]}
