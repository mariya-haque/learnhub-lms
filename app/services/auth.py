import re
from datetime import datetime, timedelta

import bcrypt
from jose import jwt

from app.config import get_settings
from app.models import Role, User

settings = get_settings()

# One definition of what a valid credential looks like, so the registration
# form and the admin's "add user" form can never drift apart.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD_LENGTH = 8


def validate_credentials(
    db,
    username: str,
    password: str | None,
    email: str | None = None,
    exclude_id: int | None = None,
) -> str | None:
    """Return the first problem with these credentials, or None if they are fine.

    ``password`` may be None when editing an existing account, where leaving the
    field blank means "keep the current one". ``exclude_id`` lets an edit ignore
    the account's own username and email when checking for collisions.
    """
    if not USERNAME_RE.match(username or ""):
        return ("Username must be 3-32 characters, using letters, numbers, "
                "dot, dash or underscore.")
    if email and not EMAIL_RE.match(email):
        return "Enter a valid email address."
    if password is not None and len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    clash = get_user_by_username(db, username)
    if clash and clash.id != exclude_id:
        return "That username is already taken."

    if email:
        clash = get_user_by_email(db, email)
        if clash and clash.id != exclude_id:
            return "An account with that email already exists."

    return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_user_by_username(db, username: str):
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db, email: str):
    return db.query(User).filter(User.email == email).first()


def create_user(
    db,
    username: str,
    password: str,
    email: str | None = None,
    full_name: str | None = None,
    role: Role = Role.student,
):
    """Register a new account. Callers must check availability first."""
    db_user = User(
        username=username,
        email=email,
        full_name=full_name,
        role=role,
        hashed_password=get_password_hash(password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def authenticate_user(db, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def ensure_user(
    db,
    username: str,
    password: str,
    role: Role,
    full_name: str | None = None,
    email: str | None = None,
):
    """Idempotent create, used by the seeder on every startup."""
    existing = get_user_by_username(db, username)
    if existing:
        return existing
    return create_user(
        db,
        username=username,
        password=password,
        email=email,
        full_name=full_name,
        role=role,
    )
