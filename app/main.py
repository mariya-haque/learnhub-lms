from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import (
    admin,
    auth,
    billing,
    calendar,
    courses,
    dashboard,
    files,
    learn,
    teach,
    tests,
    tracks,
)
from app.services import storage
from app.services.migrate import ensure_schema
from app.services.seed import seed
from app.templating import STATIC_DIR, templates

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)

# Absolute path, so `uvicorn app.main:app` works from any working directory.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(tracks.router)
app.include_router(courses.router)
app.include_router(learn.router)
app.include_router(tests.router)
app.include_router(teach.router)
app.include_router(calendar.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(files.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Render errors as pages for humans and JSON for fetch().

    The 307 that `get_current_user` raises to bounce anonymous visitors is a
    redirect wearing an exception's clothes, so it has to pass through
    untouched.
    """
    location = (exc.headers or {}).get("Location")
    if location:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url=location, status_code=exc.status_code)

    wants_json = (
        request.url.path.startswith("/api")
        or "/api/" in request.url.path
        or request.headers.get("accept", "").startswith("application/json")
    )
    if wants_json:
        return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})

    template = "errors/403.html" if exc.status_code == 403 else "errors/404.html"
    if exc.status_code not in (403, 404):
        template = "errors/404.html"

    # `current_user` is looked up loosely here: an error page should never fail
    # because the session could not be resolved.
    current_user = None
    try:
        db = SessionLocal()
        try:
            current_user = auth._resolve_user_from_request(request, db)
        finally:
            db.close()
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"current_user": current_user, "message": exc.detail},
        status_code=exc.status_code,
    )


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # create_all adds tables but not columns; top up anything an older database
    # is missing so upgrading never means dropping data.
    added = ensure_schema(engine)
    if added:
        print(f"[schema] added missing columns: {', '.join(added)}")

    storage.ensure_dirs()

    if settings.seed_demo_data:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
