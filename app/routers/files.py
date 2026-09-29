"""Authenticated delivery of uploaded lectures and notes.

These files sit outside the /static mount, so this is the only way to reach
them -- and every request re-checks that the caller may see the course.

``FileResponse`` handles Range requests, so seeking in an uploaded video works
without any extra machinery here.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user
from app.services import content as content_service
from app.services import course as course_service
from app.services import storage

router = APIRouter(prefix="/files", tags=["files"])


def _authorise(db: Session, course_id: int, user):
    course = course_service.get_course(db, course_id)
    try:
        course_service.require_access(db, course, user)
    except course_service.AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return course


@router.get("/video/{lecture_id}")
async def stream_video(
    lecture_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    lecture = content_service.get_lecture(db, lecture_id)
    if not lecture or not lecture.stored_filename:
        raise HTTPException(status_code=404, detail="Video not found.")

    _authorise(db, lecture.course_id, current_user)

    try:
        path = storage.path_for(storage.VIDEOS, lecture.stored_filename)
    except storage.UploadError:
        raise HTTPException(status_code=404, detail="Video not found.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="The video file is missing.")

    return FileResponse(path, filename=lecture.original_filename, content_disposition_type="inline")


@router.get("/note/{note_id}")
async def download_note(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    note = content_service.get_note(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")

    _authorise(db, note.course_id, current_user)

    try:
        path = storage.path_for(storage.NOTES, note.stored_filename)
    except storage.UploadError:
        raise HTTPException(status_code=404, detail="Note not found.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="The note file is missing.")

    # Reattach the teacher's original filename; the stored name is a UUID.
    return FileResponse(
        path,
        filename=note.original_filename,
        media_type=note.content_type or "application/octet-stream",
    )
