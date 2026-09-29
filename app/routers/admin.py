"""The admin area: site-wide numbers, and the people who use the site.

Every route here is gated by ``require_admin``/``require_admin_api``. The
refusals that matter -- deleting a teacher who still owns courses, demoting the
last administrator, deactivating yourself -- live in ``services/admin.py`` and
surface here as 400s carrying a message written for a human.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.routers.auth import require_admin, require_admin_api
from app.schemas import (
    PasswordReset,
    ReassignRequest,
    SubscriptionApprove,
    SubscriptionExtend,
    SubscriptionGrant,
    SubscriptionNote,
    UserCreate,
    UserUpdate,
)
from app.services import admin as admin_service
from app.services import billing as billing_service
from app.services import course as course_service
from app.services import track as track_service
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def _bad(message: str, status_code: int = 400):
    return JSONResponse(status_code=status_code, content={"message": message})


def _load(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    # An admin manages everything, so the unfiltered teacher listings are
    # already the whole site -- no separate "all courses" query needed.
    courses = course_service.list_courses_for_teacher(db, current_user)
    tracks = track_service.list_tracks_for_teacher(db, current_user)

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "current_user": current_user,
            "stats": admin_service.overview(db),
            "recent_users": admin_service.recent_users(db),
            "recent_attempts": admin_service.recent_attempts(db),
            "tracks": [
                {"track": t, "stats": track_service.track_stats(db, t.id)}
                for t in tracks
            ],
            "courses": [
                {"course": c, "stats": course_service.course_stats(db, c.id)}
                for c in courses
            ],
        },
    )


# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    q: str | None = Query(None),
    role: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    users = admin_service.list_users(db, search=q, role=role, status=status)

    rows = [
        {
            "user": user,
            "summary": admin_service.user_summary(db, user),
            "blockers": admin_service.deletion_blockers(db, user),
            "is_self": user.id == current_user.id,
        }
        for user in users
    ]

    # Candidates for "reassign this teacher's content to ...".
    teachers = [
        u for u in admin_service.list_users(db, role="teacher")
        if u.is_active
    ] + [u for u in admin_service.list_users(db, role="admin") if u.is_active]

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "current_user": current_user,
            "rows": rows,
            "teachers": teachers,
            "stats": admin_service.overview(db),
            "q": q or "",
            "role": role or "",
            "status": status or "",
        },
    )


@router.post("/api/users")
async def api_create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    try:
        user = admin_service.create_user(db, data)
    except admin_service.AdminError as exc:
        db.rollback()
        return _bad(str(exc))
    return {"id": user.id, "username": user.username, "role": user.role.value}


@router.put("/api/users/{user_id}")
async def api_update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    user = _load(db, user_id)
    if not user:
        return _bad("User not found.", 404)
    try:
        admin_service.update_user(db, user, data, current_user)
    except admin_service.AdminError as exc:
        db.rollback()
        return _bad(str(exc))
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role.value,
        "is_active": user.is_active,
    }


@router.post("/api/users/{user_id}/password")
async def api_reset_password(
    user_id: int,
    data: PasswordReset,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    user = _load(db, user_id)
    if not user:
        return _bad("User not found.", 404)
    try:
        admin_service.set_password(db, user, data.password)
    except admin_service.AdminError as exc:
        db.rollback()
        return _bad(str(exc))
    return {"message": f"Password updated for {user.username}."}


@router.post("/api/users/{user_id}/reassign")
async def api_reassign(
    user_id: int,
    data: ReassignRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    """Move a teacher's courses, tracks and classes to someone else."""
    source = _load(db, user_id)
    target = _load(db, data.to_user_id)
    if not source or not target:
        return _bad("User not found.", 404)

    try:
        moved = admin_service.reassign_content(db, source, target)
    except admin_service.AdminError as exc:
        db.rollback()
        return _bad(str(exc))

    return {
        "message": (
            f"Moved {moved['courses']} course(s), {moved['tracks']} track(s) and "
            f"{moved['classes']} class(es) to {target.display_name}."
        ),
        **moved,
    }


# --------------------------------------------------------------------------
# Subscriptions
#
# Payment happens outside the app, so everything here is an admin recording
# what already occurred. Nothing charges anyone.
# --------------------------------------------------------------------------

def _subscription(db: Session, sub_id: int):
    from app.models import Subscription
    return db.query(Subscription).filter(Subscription.id == sub_id).first()


@router.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_page(
    request: Request,
    q: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    subscriptions = billing_service.list_all(db, status=status, search=q)

    return templates.TemplateResponse(
        request=request,
        name="admin/subscriptions.html",
        context={
            "current_user": current_user,
            "subscriptions": subscriptions,
            "summary": billing_service.revenue_summary(db),
            "methods": billing_service.PAYMENT_METHODS,
            "tracks": track_service.list_tracks_for_teacher(db, current_user),
            "students": admin_service.list_users(db, role="student"),
            "q": q or "",
            "status": status or "",
        },
    )


@router.post("/api/subscriptions/{sub_id}/approve")
async def api_approve_subscription(
    sub_id: int,
    data: SubscriptionApprove,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    subscription = _subscription(db, sub_id)
    if not subscription:
        return _bad("Subscription not found.", 404)
    try:
        billing_service.approve(db, subscription, current_user, data)
    except billing_service.BillingError as exc:
        db.rollback()
        return _bad(str(exc))
    return {
        "id": subscription.id,
        "status": subscription.status.value,
        "message": f"Activated until {subscription.expires_at_utc:%d %b %Y}.",
    }


@router.post("/api/subscriptions/{sub_id}/reject")
async def api_reject_subscription(
    sub_id: int,
    data: SubscriptionNote,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    subscription = _subscription(db, sub_id)
    if not subscription:
        return _bad("Subscription not found.", 404)
    try:
        billing_service.reject(db, subscription, current_user, data.reason)
    except billing_service.BillingError as exc:
        db.rollback()
        return _bad(str(exc))
    return {"id": subscription.id, "message": "Request rejected."}


@router.post("/api/subscriptions/{sub_id}/cancel")
async def api_cancel_subscription(
    sub_id: int,
    data: SubscriptionNote,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    subscription = _subscription(db, sub_id)
    if not subscription:
        return _bad("Subscription not found.", 404)
    try:
        billing_service.cancel(db, subscription, current_user, data.reason)
    except billing_service.BillingError as exc:
        db.rollback()
        return _bad(str(exc))
    return {"id": subscription.id, "message": "Subscription cancelled."}


@router.post("/api/subscriptions/{sub_id}/extend")
async def api_extend_subscription(
    sub_id: int,
    data: SubscriptionExtend,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    subscription = _subscription(db, sub_id)
    if not subscription:
        return _bad("Subscription not found.", 404)
    try:
        billing_service.extend(db, subscription, data.days)
    except billing_service.BillingError as exc:
        db.rollback()
        return _bad(str(exc))
    return {
        "id": subscription.id,
        "message": f"Extended to {subscription.expires_at_utc:%d %b %Y}.",
    }


@router.post("/api/subscriptions/grant")
async def api_grant_subscription(
    data: SubscriptionGrant,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    """Free access with no payment record: scholarships, trials, goodwill."""
    student = _load(db, data.student_id)
    track = track_service.get_track(db, data.track_id)
    if not student or not track:
        return _bad("Student or track not found.", 404)
    if student.role != Role.student:
        return _bad("Subscriptions are for student accounts.")

    subscription = billing_service.grant(
        db, track, student, current_user, data.days, data.note
    )
    # Granting access without membership would unlock nothing, so join them in.
    track_service.join(db, track, student)

    return {
        "id": subscription.id,
        "message": (
            f"{student.display_name} granted {data.days} days on {track.title}."
        ),
    }


@router.delete("/api/users/{user_id}")
async def api_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin_api),
):
    user = _load(db, user_id)
    if not user:
        return _bad("User not found.", 404)

    name = user.display_name
    try:
        admin_service.delete_user(db, user, current_user)
    except admin_service.AdminError as exc:
        db.rollback()
        # 409: the request was well-formed, the account simply is not removable
        # in its current state. `canReassign` tells the UI whether to offer the
        # hand-over flow or just the message.
        return JSONResponse(
            status_code=409,
            content={
                "message": str(exc),
                "canReassign": getattr(exc, "reassignable", False),
            },
        )

    return {"message": f"{name} deleted."}
