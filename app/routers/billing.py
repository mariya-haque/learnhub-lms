"""Student-facing subscriptions: what you have, and how to ask for more.

Requesting is all a student can do. Nothing here activates anything -- payment
happens outside the app and an admin records it, so every request lands as
``pending`` and waits.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.auth import get_current_user, require_user_api
from app.schemas import SubscriptionRequest
from app.services import billing as billing_service
from app.services import track as track_service
from app.templating import templates

router = APIRouter(tags=["subscriptions"])


@router.get("/subscriptions", response_class=HTMLResponse)
async def my_subscriptions(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    subscriptions = billing_service.list_for_student(db, current_user.id)
    subscribed_track_ids = {
        s.track_id for s in subscriptions if s.is_current or s.status.value == "pending"
    }

    # Everything still purchasable: published, paid, and not already held.
    offers = []
    for track in track_service.list_published_tracks(db):
        if not track.requires_subscription or track.id in subscribed_track_ids:
            continue
        plans = billing_service.list_plans(db, track.id, active_only=True)
        if plans:
            offers.append({"track": track, "plans": plans})

    return templates.TemplateResponse(
        request=request,
        name="subscriptions.html",
        context={
            "current_user": current_user,
            "subscriptions": subscriptions,
            "offers": offers,
        },
    )


@router.post("/subscriptions/request")
async def request_subscription(
    data: SubscriptionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_user_api),
):
    plan = billing_service.get_plan(db, data.plan_id)
    if not plan:
        return JSONResponse(status_code=404, content={"message": "Plan not found."})

    track = track_service.get_track(db, plan.track_id)
    if not track or not track.is_published:
        return JSONResponse(
            status_code=404, content={"message": "That track is not available."}
        )

    try:
        subscription = billing_service.request_subscription(
            db, track, plan, current_user
        )
    except billing_service.BillingError as exc:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(exc)})

    return {
        "id": subscription.id,
        "status": subscription.status.value,
        "message": (
            f"Request sent for {track.title} — {plan.name}. "
            "It unlocks once an administrator confirms your payment."
        ),
    }
