"""Disk storage for uploaded lectures and notes.

Files are written under ``settings.upload_dir`` -- which lives outside
``app/static`` on purpose. A StaticFiles mount performs no authorisation, so
anything under it is readable by anyone who can guess the name. Course media is
served instead by ``routers/files.py``, behind an enrollment check.

Stored names are random UUIDs; the teacher-facing original name is kept in the
database and only reattached in the Content-Disposition header on download.
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings

settings = get_settings()

UPLOAD_ROOT = Path(settings.upload_dir)

VIDEOS = "videos"
NOTES = "notes"

# Extension allowlists. An allowlist rather than a denylist, because the set of
# things a browser will happily execute is longer than anyone remembers.
ALLOWED = {
    VIDEOS: {".mp4", ".webm", ".mov", ".m4v", ".ogv"},
    NOTES: {
        ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
        ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".zip",
    },
}

MAX_MB = {
    VIDEOS: settings.max_video_mb,
    NOTES: settings.max_note_mb,
}

# 1 MiB chunks: big enough to be fast, small enough that a 500 MB upload never
# sits in memory.
CHUNK_SIZE = 1024 * 1024


class UploadError(Exception):
    """A rejected upload. The message is safe to show a user."""


def ensure_dirs() -> None:
    for subdir in (VIDEOS, NOTES):
        (UPLOAD_ROOT / subdir).mkdir(parents=True, exist_ok=True)


def _extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def path_for(subdir: str, stored_name: str) -> Path:
    """Resolve a stored file, refusing anything that escapes the upload root."""
    base = (UPLOAD_ROOT / subdir).resolve()
    target = (base / stored_name).resolve()
    if base not in target.parents:
        raise UploadError("Invalid file path.")
    return target


def save_upload(file: UploadFile, subdir: str) -> tuple[str, str, int]:
    """Stream ``file`` to disk. Returns (stored_name, original_name, size).

    Raises ``UploadError`` for a bad extension or an over-size file. The size
    limit is enforced while copying, so an oversized upload is abandoned rather
    than fully written and then rejected.
    """
    original = os.path.basename(file.filename or "")
    if not original:
        raise UploadError("No file was selected.")

    ext = _extension(original)
    allowed = ALLOWED[subdir]
    if ext not in allowed:
        pretty = ", ".join(sorted(e.lstrip(".") for e in allowed))
        raise UploadError(f"Unsupported file type '{ext or original}'. Allowed: {pretty}.")

    limit_bytes = MAX_MB[subdir] * 1024 * 1024
    ensure_dirs()

    stored_name = f"{uuid.uuid4().hex}{ext}"
    destination = UPLOAD_ROOT / subdir / stored_name

    written = 0
    try:
        with open(destination, "wb") as buffer:
            while chunk := file.file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > limit_bytes:
                    raise UploadError(
                        f"File is larger than the {MAX_MB[subdir]} MB limit."
                    )
                buffer.write(chunk)
    except UploadError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise UploadError(f"Could not save the file: {exc}") from None
    finally:
        file.file.close()

    if written == 0:
        destination.unlink(missing_ok=True)
        raise UploadError("The selected file is empty.")

    return stored_name, original, written


def delete_upload(subdir: str, stored_name: str | None) -> None:
    """Remove a stored file. Silent if it is already gone."""
    if not stored_name:
        return
    try:
        path_for(subdir, stored_name).unlink(missing_ok=True)
    except (UploadError, OSError):
        # A missing or odd path is not worth failing a delete request over.
        pass


def copy_into(subdir: str, source: Path) -> tuple[str, str, int]:
    """Place an existing on-disk file into storage. Used only by the seeder."""
    ensure_dirs()
    stored_name = f"{uuid.uuid4().hex}{source.suffix.lower()}"
    destination = UPLOAD_ROOT / subdir / stored_name
    with open(source, "rb") as src, open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return stored_name, source.name, destination.stat().st_size
