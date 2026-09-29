"""Subscriptions: what a track costs, and who has paid for it.

Payment happens outside the app -- bank transfer, JazzCash, EasyPaisa, cash --
and an admin records it here. That shapes the lifecycle:

    request  ->  pending  ->  active (admin confirms payment)  ->  expired
                     \\-->  rejected            \\-->  cancelled

Three rules are worth stating plainly:

* **Entitlement is a question about time, not a status column.** A subscription
  that ran out overnight still says ``active`` until something looks at it, so
  every check goes through ``is_current`` (status *and* window) rather than
  reading the status directly.
* **Prices are integers.** Minor units, never floats. Rs 2,500.00 stored as a
  float becomes 2499.9999999999995 eventually, and money is the last thing that
  should drift.
* **What was agreed is copied, not referenced.** A subscription snapshots its
  price, currency and plan name, so repricing next term cannot rewrite what
  somebody already paid.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models import Plan, Role, SubStatus, Subscription, Track, User

# What an admin may record a payment as. Free text would make the receipts
# unsearchable within a month.
PAYMENT_METHODS = [
    "Bank transfer",
    "JazzCash",
    "EasyPaisa",
    "Cash",
    "Card",
    "Other",
]


class BillingError(Exception):
    """A refused billing action. The message is safe to show a user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_storage(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def format_money(minor: int | None, currency: str = "PKR") -> str:
    """Minor units to a display string. ``Rs 2,500`` rather than ``PKR 2500.00``."""
    amount = (minor or 0) / 100
    symbol = {"PKR": "Rs", "USD": "$", "GBP": "£", "EUR": "€"}.get(currency, currency)
    if amount == int(amount):
        return f"{symbol} {int(amount):,}"
    return f"{symbol} {amount:,.2f}"


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

def get_plan(db, plan_id: int) -> Plan | None:
    return db.query(Plan).filter(Plan.id == plan_id).first()


def list_plans(db, track_id: int, active_only: bool = False) -> list[Plan]:
    query = db.query(Plan).filter(Plan.track_id == track_id)
    if active_only:
        query = query.filter(Plan.is_active.is_(True))
    return query.order_by(Plan.order_index, Plan.price_minor).all()


def _next_order(db, track_id: int) -> int:
    current = (
        db.query(func.max(Plan.order_index)).filter(Plan.track_id == track_id).scalar()
    )
    return (current or 0) + 1


def create_plan(db, track: Track, data) -> Plan:
    plan = Plan(
        track_id=track.id,
        name=data.name.strip(),
        description=(data.description or "").strip() or None,
        price_minor=data.price_minor,
        currency=(data.currency or "PKR").upper(),
        duration_days=data.duration_days,
        is_active=data.is_active,
        order_index=_next_order(db, track.id),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db, plan: Plan, data) -> Plan:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "currency" and value:
            value = value.upper()
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db, plan: Plan) -> None:
    """Detach it from its history rather than deleting the history with it.

    Subscriptions snapshot the plan's name and price, so a sold plan can be
    withdrawn without any receipt losing its meaning.
    """
    db.query(Subscription).filter(Subscription.plan_id == plan.id).update(
        {"plan_id": None}, synchronize_session=False
    )
    db.delete(plan)
    db.commit()


# --------------------------------------------------------------------------
# Entitlement
# --------------------------------------------------------------------------

def sweep_expired(db, student_id: int | None = None) -> int:
    """Move subscriptions whose window has closed from active to expired.

    Purely cosmetic: ``is_current`` never trusts the status alone, so nothing
    depends on this having run. It exists so the admin's list and a student's
    own page do not keep claiming "active" about something that is not.
    """
    query = db.query(Subscription).filter(
        Subscription.status == SubStatus.active,
        Subscription.expires_at.isnot(None),
        Subscription.expires_at < _to_storage(_now()),
    )
    if student_id is not None:
        query = query.filter(Subscription.student_id == student_id)

    changed = query.update({"status": SubStatus.expired}, synchronize_session=False)
    if changed:
        db.commit()
    return changed


def active_subscription(db, track_id: int, student_id: int) -> Subscription | None:
    """The live subscription for this track, or None."""
    rows = (
        db.query(Subscription)
        .filter(
            Subscription.track_id == track_id,
            Subscription.student_id == student_id,
            Subscription.status == SubStatus.active,
        )
        .order_by(Subscription.expires_at.desc())
        .all()
    )
    # `is_current` re-checks the window, so a stale `active` row never counts.
    return next((s for s in rows if s.is_current), None)


def pending_subscription(db, track_id: int, student_id: int) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.track_id == track_id,
            Subscription.student_id == student_id,
            Subscription.status == SubStatus.pending,
        )
        .order_by(Subscription.requested_at.desc())
        .first()
    )


def is_entitled(db, track: Track, user: User) -> bool:
    """May this user reach the track's content?

    A free track is open to everyone. Staff always get in -- an admin checking
    a paywalled track, or a teacher looking at their own programme, must not be
    asked to buy it.
    """
    if not track.requires_subscription:
        return True
    if user.role in (Role.admin, Role.teacher):
        return True
    return active_subscription(db, track.id, user.id) is not None


def list_for_student(db, student_id: int) -> list[Subscription]:
    sweep_expired(db, student_id)
    return (
        db.query(Subscription)
        .filter(Subscription.student_id == student_id)
        .order_by(Subscription.requested_at.desc())
        .all()
    )


def list_all(
    db,
    status: str | None = None,
    search: str | None = None,
    track_id: int | None = None,
) -> list[Subscription]:
    sweep_expired(db)
    query = db.query(Subscription)

    if status in {s.value for s in SubStatus}:
        query = query.filter(Subscription.status == SubStatus(status))
    if track_id:
        query = query.filter(Subscription.track_id == track_id)
    if search:
        like = f"%{search.strip()}%"
        query = query.join(User, User.id == Subscription.student_id).filter(
            User.username.ilike(like)
            | User.full_name.ilike(like)
            | Subscription.payment_reference.ilike(like)
        )

    return query.order_by(Subscription.requested_at.desc()).all()


def revenue_summary(db) -> dict:
    """What has actually been collected, by currency.

    Only ever counts subscriptions an admin confirmed -- pending requests are
    not money, and counting them would overstate takings on every dashboard.
    """
    rows = (
        db.query(Subscription.currency, func.sum(Subscription.price_minor))
        .filter(Subscription.status.in_([SubStatus.active, SubStatus.expired]))
        .group_by(Subscription.currency)
        .all()
    )
    return {
        "collected": [
            {"currency": currency, "total": format_money(total, currency)}
            for currency, total in rows
            if total
        ],
        "pending": db.query(func.count(Subscription.id))
            .filter(Subscription.status == SubStatus.pending)
            .scalar() or 0,
        "active": sum(
            1 for s in db.query(Subscription)
            .filter(Subscription.status == SubStatus.active)
            if s.is_current
        ),
    }


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

def request_subscription(db, track: Track, plan: Plan, student: User) -> Subscription:
    """A student asks for access. Nothing unlocks until an admin confirms."""
    if plan.track_id != track.id:
        raise BillingError("That plan belongs to a different track.")
    if not plan.is_active:
        raise BillingError("That plan is no longer available.")

    if active_subscription(db, track.id, student.id):
        raise BillingError("You already have an active subscription to this track.")
    existing = pending_subscription(db, track.id, student.id)
    if existing:
        raise BillingError(
            "You already have a request waiting for confirmation on this track."
        )

    subscription = Subscription(
        student_id=student.id,
        track_id=track.id,
        plan_id=plan.id,
        status=SubStatus.pending,
        price_minor=plan.price_minor,
        currency=plan.currency,
        plan_name=plan.name,
        requested_at=_to_storage(_now()),
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def approve(db, subscription: Subscription, admin: User, data) -> Subscription:
    """Record the payment and start the clock."""
    if subscription.status == SubStatus.active and subscription.is_current:
        raise BillingError("That subscription is already active.")

    days = data.duration_days or (
        subscription.plan.duration_days if subscription.plan else 30
    )
    if days < 1:
        raise BillingError("A subscription must run for at least one day.")

    now = _now()
    subscription.status = SubStatus.active
    subscription.started_at = _to_storage(now)
    subscription.expires_at = _to_storage(now + timedelta(days=days))
    subscription.activated_by = admin.id
    subscription.payment_method = (data.payment_method or "").strip() or None
    subscription.payment_reference = (data.payment_reference or "").strip() or None
    if data.note:
        subscription.note = data.note.strip() or None

    db.commit()
    db.refresh(subscription)
    return subscription


def reject(db, subscription: Subscription, admin: User, reason: str | None) -> Subscription:
    if subscription.status != SubStatus.pending:
        raise BillingError("Only a pending request can be rejected.")
    subscription.status = SubStatus.rejected
    subscription.activated_by = admin.id
    subscription.note = (reason or "").strip() or None
    db.commit()
    db.refresh(subscription)
    return subscription


def cancel(db, subscription: Subscription, admin: User, reason: str | None) -> Subscription:
    """End an active subscription early. The record stays; the access stops."""
    if subscription.status not in (SubStatus.active, SubStatus.pending):
        raise BillingError("That subscription is not running.")
    subscription.status = SubStatus.cancelled
    subscription.expires_at = _to_storage(_now())
    subscription.activated_by = admin.id
    subscription.note = (reason or "").strip() or subscription.note
    db.commit()
    db.refresh(subscription)
    return subscription


def extend(db, subscription: Subscription, days: int) -> Subscription:
    """Add days, from today or from the current end date, whichever is later.

    Extending a subscription that lapsed last week should give a full new
    period rather than silently burning most of it on days already gone.
    """
    if days < 1:
        raise BillingError("Enter a number of days to add.")

    now = _now()
    base = subscription.expires_at_utc
    start = base if base and base > now else now
    subscription.expires_at = _to_storage(start + timedelta(days=days))
    subscription.status = SubStatus.active
    if not subscription.started_at:
        subscription.started_at = _to_storage(now)

    db.commit()
    db.refresh(subscription)
    return subscription


def grant(db, track: Track, student: User, admin: User, days: int, note: str | None):
    """Give access directly, with no request and no payment.

    Scholarships, trials and "their transfer cleared, just sort it out" -- all
    of which happen, and none of which should mean faking a payment record.
    """
    now = _now()
    subscription = Subscription(
        student_id=student.id,
        track_id=track.id,
        plan_id=None,
        status=SubStatus.active,
        price_minor=0,
        currency="PKR",
        plan_name="Granted by admin",
        requested_at=_to_storage(now),
        started_at=_to_storage(now),
        expires_at=_to_storage(now + timedelta(days=max(1, days))),
        activated_by=admin.id,
        payment_method="Granted",
        note=(note or "").strip() or None,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription
