"""Shared Jinja2 environment.

One environment for every router, pointed at an absolute path so the app does
not depend on the process CWD.

``asset_url`` fingerprints static files with their mtime so a browser can never
serve a stale stylesheet or script after a change.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import get_settings

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def asset_url(path: str) -> str:
    """Return the /static URL for ``path`` with a cache-busting fingerprint."""
    try:
        stamp = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        stamp = 0
    return f"/static/{path}?v={stamp}"


def format_duration(seconds) -> str:
    """Seconds to a compact `1h 05m` / `12m 30s` label. Blank when unknown."""
    if not seconds:
        return ""
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_size(num_bytes) -> str:
    """Bytes to a human label, for the notes list."""
    if not num_bytes:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def format_money(minor, currency: str = "PKR") -> str:
    """Minor units to a display price. Kept here so templates never do maths."""
    from app.services.billing import format_money as _format

    return _format(minor, currency or "PKR")


_settings = get_settings()

templates.env.globals["asset_url"] = asset_url
templates.env.globals["app_name"] = _settings.app_name
templates.env.globals["show_demo_credentials"] = _settings.show_demo_credentials
templates.env.filters["duration"] = format_duration
templates.env.filters["filesize"] = format_size
templates.env.filters["money"] = format_money
