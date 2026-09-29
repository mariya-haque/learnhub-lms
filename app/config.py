from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

# The project root (the folder holding `app/`), resolved from this file rather
# than the CWD so the app behaves the same however uvicorn is launched.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # SQLite by default so the app runs with no setup at all. Point
    # DATABASE_URL at Postgres to switch -- nothing else needs to change.
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'lms.db'}"
    app_name: str = "LearnHub"
    app_version: str = "1.0.0"
    debug: bool = True
    secret_key: str = "change-this-to-a-random-secret-key-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 720   # a study session outlives an hour
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Uploads ---------------------------------------------------------
    # Deliberately outside app/static: static files are served with no auth,
    # and course content must not sit on a guessable public URL.
    upload_dir: str = str(PROJECT_ROOT / "uploads")
    max_video_mb: int = 512
    max_note_mb: int = 32

    # --- Assessment defaults ---------------------------------------------
    default_pass_percent: int = 40
    grand_test_default_minutes: int = 60
    # How much of a video counts as "watched".
    lecture_complete_ratio: float = 0.9

    # --- Live classes ------------------------------------------------------
    # The built-in classroom is an iframe onto a public Jitsi Meet instance, so
    # scheduling a class needs no account, no API key and no media server of
    # our own. Point this at a self-hosted Jitsi to keep traffic in-house.
    meet_domain: str = "meet.jit.si"
    # Minutes before the start time that students may enter the room.
    class_join_lead_minutes: int = 10

    # --- Login page --------------------------------------------------------
    # Whether the sign-in page advertises the demo accounts and their
    # passwords. Off by default: the moment the app is reachable from the
    # internet, printing `admin / admin123` next to a one-click button hands
    # every visitor the keys. Turn it on for local demos only.
    show_demo_credentials: bool = False

    # --- First run --------------------------------------------------------
    # Creates the three demo accounts and a fully populated sample course so
    # the app is clickable before anyone has uploaded anything.
    seed_demo_data: bool = True

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
