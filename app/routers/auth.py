from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Role
from app.services.auth import (
    EMAIL_RE,
    MIN_PASSWORD_LENGTH,
    USERNAME_RE,
    authenticate_user,
    create_access_token,
    create_user,
    get_user_by_email,
    get_user_by_username,
)
from app.templating import templates

router = APIRouter(prefix="", tags=["auth"])
settings = get_settings()


def _redirect_to_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": "/login"},
    )


def _resolve_user_from_request(request: Request, db: Session):
    """Return the signed-in User, or None. Never raises.

    The single place that knows how a session cookie becomes a user.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None

    # The cookie is set as "Bearer <jwt>", but tolerate a bare token too.
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None

    username = payload.get("sub")
    if not username:
        return None

    return get_user_by_username(db, username=username)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """For HTML pages: bounce anonymous visitors to the login screen."""
    user = _resolve_user_from_request(request, db)
    if user is None:
        raise _redirect_to_login()
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)):
    """For pages that render differently, but still render, when signed out."""
    return _resolve_user_from_request(request, db)


def require_user_api(request: Request, db: Session = Depends(get_db)):
    """For JSON endpoints: 401 with a JSON body, never a redirect.

    Use this for every /api route. `get_current_user` is for HTML pages only --
    its 307 to /login is invisible to fetch(), which would then parse the login
    page as if it were data.
    """
    user = _resolve_user_from_request(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again to continue.",
        )
    return user


def require_role(*roles: Role, message: str = "This area is for teachers."):
    """Page-level role gate. Renders a 403 page rather than a bare error."""

    def dependency(request: Request, db: Session = Depends(get_db)):
        user = _resolve_user_from_request(request, db)
        if user is None:
            raise _redirect_to_login()
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message,
            )
        return user

    return dependency


def require_role_api(*roles: Role):
    """JSON role gate. 401 when signed out, 403 when signed in as the wrong role."""

    def dependency(request: Request, db: Session = Depends(get_db)):
        user = require_user_api(request, db)
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to do that.",
            )
        return user

    return dependency


require_teacher = require_role(Role.teacher, Role.admin)
require_teacher_api = require_role_api(Role.teacher, Role.admin)
require_admin = require_role(
    Role.admin, message="This area is for administrators."
)
require_admin_api = require_role_api(Role.admin)


def home_for(user) -> str:
    """Where signing in lands you: the job you actually came to do."""
    if not user:
        return "/dashboard"
    if user.is_admin:
        return "/admin"
    return "/teach" if user.is_teacher else "/dashboard"


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@router.get("/", response_class=RedirectResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    user = _resolve_user_from_request(request, db)
    if user:
        return RedirectResponse(url=home_for(user))
    return RedirectResponse(url="/login")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    user = _resolve_user_from_request(request, db)
    if user:
        return RedirectResponse(url=home_for(user))
    return templates.TemplateResponse(request=request, name="login.html", context={})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, username.strip(), password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password.", "username": username},
        )
    return _issue_session(home_for(user), user.username)


def _issue_session(url: str, username: str) -> RedirectResponse:
    """Redirect to `url` with a fresh signed session cookie."""
    token = create_access_token(data={"sub": username})
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    user = _resolve_user_from_request(request, db)
    if user:
        return RedirectResponse(url=home_for(user))
    return templates.TemplateResponse(request=request, name="register.html", context={})


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(""),
    email: str = Form(""),
    role: str = Form("student"),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()
    email = email.strip()
    full_name = full_name.strip()

    # Only student and teacher are self-assignable; admin is seeded, never
    # claimed by anyone who can guess a form field name.
    chosen_role = Role.teacher if role == "teacher" else Role.student

    if not USERNAME_RE.match(username):
        error = "Username must be 3-32 characters, using letters, numbers, dot, dash or underscore."
    elif email and not EMAIL_RE.match(email):
        error = "Enter a valid email address."
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    elif password != confirm_password:
        error = "The two passwords do not match."
    elif get_user_by_username(db, username):
        error = "That username is already taken."
    elif email and get_user_by_email(db, email):
        error = "An account with that email already exists."
    else:
        error = None

    if error:
        # Re-render with the entered values so the user doesn't retype everything.
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error": error,
                "username": username,
                "email": email,
                "full_name": full_name,
                "role": chosen_role.value,
            },
        )

    try:
        user = create_user(
            db,
            username=username,
            password=password,
            email=email or None,
            full_name=full_name or None,
            role=chosen_role,
        )
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error": "Could not create the account. Please try again.",
                "username": username,
                "email": email,
                "full_name": full_name,
                "role": chosen_role.value,
            },
        )

    return _issue_session(home_for(user), user.username)


@router.get("/logout", response_class=RedirectResponse)
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response
