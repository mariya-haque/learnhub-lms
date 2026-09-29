"""Lectures, notes and watch progress."""

import re
from urllib.parse import parse_qs, urlparse

from sqlalchemy import func

from app.config import get_settings
from app.models import Lecture, LectureProgress, Note, SourceType

settings = get_settings()

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}


def normalise_embed_url(url: str) -> tuple[str, str]:
    """Return ``(kind, url)`` where kind is 'iframe', 'file' or 'link'.

    A teacher will paste whatever is in their address bar, so a YouTube watch
    link, a youtu.be short link and an already-embeddable link all have to end
    up as the same playable thing.
    """
    if not url:
        return "link", ""

    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if host in _YOUTUBE_HOSTS:
        video_id = ""
        if host == "youtu.be":
            video_id = path.lstrip("/").split("/")[0]
        elif path.startswith("/embed/"):
            return "iframe", url
        elif path.startswith("/shorts/"):
            video_id = path.split("/shorts/", 1)[1].split("/")[0]
        else:
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        if video_id:
            start = (parse_qs(parsed.query).get("t") or [""])[0]
            suffix = f"?start={re.sub(r'[^0-9]', '', start)}" if start else ""
            return "iframe", f"https://www.youtube.com/embed/{video_id}{suffix}"

    if host in _VIMEO_HOSTS:
        if path.startswith("/video/"):
            return "iframe", url
        video_id = path.lstrip("/").split("/")[0]
        if video_id.isdigit():
            return "iframe", f"https://player.vimeo.com/video/{video_id}"

    if re.search(r"\.(mp4|webm|ogv|mov|m4v)(\?|$)", url, re.IGNORECASE):
        return "file", url

    # Unknown host: offer it as a link rather than guessing at an embed that
    # will be refused by X-Frame-Options anyway.
    return "link", url


# --------------------------------------------------------------------------
# Lectures
# --------------------------------------------------------------------------

def get_lecture(db, lecture_id: int):
    return db.query(Lecture).filter(Lecture.id == lecture_id).first()


def list_lectures(db, course_id: int, published_only: bool = False):
    query = db.query(Lecture).filter(Lecture.course_id == course_id)
    if published_only:
        query = query.filter(Lecture.is_published.is_(True))
    return query.order_by(Lecture.order_index, Lecture.id).all()


def _next_order(db, course_id: int) -> int:
    current = (
        db.query(func.max(Lecture.order_index))
        .filter(Lecture.course_id == course_id)
        .scalar()
    )
    return (current or 0) + 1


def create_url_lecture(db, course_id: int, data) -> Lecture:
    lecture = Lecture(
        course_id=course_id,
        title=data.title,
        description=data.description,
        video_url=data.video_url.strip(),
        source_type=SourceType.url,
        duration_seconds=data.duration_seconds,
        is_published=data.is_published,
        order_index=_next_order(db, course_id),
    )
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    return lecture


def create_upload_lecture(
    db,
    course_id: int,
    title: str,
    description: str | None,
    stored_name: str,
    original_name: str,
    size: int,
    is_published: bool = True,
) -> Lecture:
    lecture = Lecture(
        course_id=course_id,
        title=title,
        description=description,
        source_type=SourceType.upload,
        stored_filename=stored_name,
        original_filename=original_name,
        file_size=size,
        is_published=is_published,
        order_index=_next_order(db, course_id),
    )
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    return lecture


def update_lecture(db, lecture: Lecture, data) -> Lecture:
    payload = data.model_dump(exclude_unset=True)
    # Switching an uploaded lecture to a URL is allowed; the old file is
    # cleaned up by the router, which owns storage.
    if payload.get("video_url"):
        payload["video_url"] = payload["video_url"].strip()
        lecture.source_type = SourceType.url
    for field, value in payload.items():
        setattr(lecture, field, value)
    db.commit()
    db.refresh(lecture)
    return lecture


def delete_lecture(db, lecture: Lecture) -> None:
    # Detach notes rather than deleting them -- a handout usually outlives the
    # video it was filed under.
    db.query(Note).filter(Note.lecture_id == lecture.id).update({"lecture_id": None})
    db.query(LectureProgress).filter(
        LectureProgress.lecture_id == lecture.id
    ).delete()
    db.delete(lecture)
    db.commit()


def reorder_lectures(db, course_id: int, ids: list[int]) -> None:
    lectures = {lec.id: lec for lec in list_lectures(db, course_id)}
    for position, lecture_id in enumerate(ids, start=1):
        lecture = lectures.get(lecture_id)
        if lecture:
            lecture.order_index = position
    db.commit()


def adjacent_lectures(db, lecture: Lecture, published_only: bool = True):
    """(previous, next) in display order, for the player's nav buttons."""
    siblings = list_lectures(db, lecture.course_id, published_only=published_only)
    ids = [item.id for item in siblings]
    if lecture.id not in ids:
        return None, None
    index = ids.index(lecture.id)
    previous = siblings[index - 1] if index > 0 else None
    nxt = siblings[index + 1] if index + 1 < len(siblings) else None
    return previous, nxt


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

def get_note(db, note_id: int):
    return db.query(Note).filter(Note.id == note_id).first()


def list_notes(db, course_id: int, lecture_id: int | None = None):
    query = db.query(Note).filter(Note.course_id == course_id)
    if lecture_id is not None:
        query = query.filter(Note.lecture_id == lecture_id)
    return query.order_by(Note.created_at.desc(), Note.id.desc()).all()


def create_note(
    db,
    course_id: int,
    title: str,
    description: str | None,
    stored_name: str,
    original_name: str,
    size: int,
    content_type: str | None,
    lecture_id: int | None = None,
) -> Note:
    note = Note(
        course_id=course_id,
        lecture_id=lecture_id,
        title=title,
        description=description,
        stored_filename=stored_name,
        original_filename=original_name,
        file_size=size,
        content_type=content_type,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def update_note(db, note: Note, data) -> Note:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(note, field, value)
    db.commit()
    db.refresh(note)
    return note


def delete_note(db, note: Note) -> None:
    db.delete(note)
    db.commit()


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

def get_progress(db, lecture_id: int, student_id: int):
    return (
        db.query(LectureProgress)
        .filter(
            LectureProgress.lecture_id == lecture_id,
            LectureProgress.student_id == student_id,
        )
        .first()
    )


def progress_map(db, course_id: int, student_id: int) -> dict[int, LectureProgress]:
    """lecture_id -> progress, so a lecture list renders in one query."""
    rows = (
        db.query(LectureProgress)
        .join(Lecture, Lecture.id == LectureProgress.lecture_id)
        .filter(
            Lecture.course_id == course_id,
            LectureProgress.student_id == student_id,
        )
        .all()
    )
    return {row.lecture_id: row for row in rows}


def record_progress(db, lecture: Lecture, student_id: int, data) -> LectureProgress:
    """Upsert a watch position. Completion is sticky -- rewatching a finished
    lecture must not un-complete it."""
    entry = get_progress(db, lecture.id, student_id)
    if not entry:
        entry = LectureProgress(lecture_id=lecture.id, student_id=student_id)
        db.add(entry)

    entry.last_position_seconds = max(0.0, float(data.position_seconds or 0))

    duration = data.duration_seconds or lecture.duration_seconds
    if duration and not lecture.duration_seconds:
        # The player is the only thing that actually knows how long an
        # uploaded file is, so trust its first report.
        lecture.duration_seconds = int(duration)

    if data.completed:
        entry.completed = True
    elif duration and duration > 0:
        ratio = entry.last_position_seconds / float(duration)
        if ratio >= settings.lecture_complete_ratio:
            entry.completed = True

    db.commit()
    db.refresh(entry)
    return entry


def set_completed(db, lecture: Lecture, student_id: int, completed: bool):
    entry = get_progress(db, lecture.id, student_id)
    if not entry:
        entry = LectureProgress(lecture_id=lecture.id, student_id=student_id)
        db.add(entry)
    entry.completed = completed
    db.commit()
    db.refresh(entry)
    return entry
