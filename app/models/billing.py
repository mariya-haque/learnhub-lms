import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class SubStatus(str, enum.Enum):
    pending = "pending"      # requested, waiting for an admin to confirm payment
    active = "active"        # paid and inside its window
    expired = "expired"      # ran past expires_at
    cancelled = "cancelled"  # ended early by an admin
    rejected = "rejected"    # payment never arrived


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat those as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Plan(Base):
    """What a track costs, for one billing period.

    Money is stored in minor units (paisa, cents) as an integer. A float would
    make Rs 2,500.00 arrive as 2499.9999999999995 sooner or later, and prices
    are the last place that should be approximate.
    """

    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False, index=True)
    name = Column(String, nullable=False)              # "Monthly", "Annual"
    description = Column(Text, nullable=True)
    price_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="PKR")
    duration_days = Column(Integer, nullable=False, default=30)
    order_index = Column(Integer, default=0, index=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    track = relationship("Track", back_populates="plans")
    subscriptions = relationship("Subscription", back_populates="plan")

    @property
    def price(self) -> float:
        return (self.price_minor or 0) / 100

    @property
    def is_free(self) -> bool:
        return not self.price_minor


class Subscription(Base):
    """One student's paid access to one track.

    The price and currency are copied in at request time rather than read
    through ``plan``. Repricing a plan next term must not silently rewrite what
    somebody already paid, and a receipt has to stay true after the fact.
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True, index=True)

    status = Column(
        Enum(SubStatus), nullable=False, default=SubStatus.pending, index=True
    )

    # Snapshot of what was agreed, kept even if the plan changes or is deleted.
    price_minor = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="PKR")
    plan_name = Column(String, nullable=True)

    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Who confirmed the payment, and against what.
    activated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    payment_method = Column(String, nullable=True)      # "JazzCash", "Bank transfer"
    payment_reference = Column(String, nullable=True)
    note = Column(Text, nullable=True)

    student = relationship("User", foreign_keys=[student_id])
    approver = relationship("User", foreign_keys=[activated_by])
    track = relationship("Track", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")

    # ---------------------------------------------------------------- derived

    @property
    def expires_at_utc(self) -> datetime | None:
        return _as_utc(self.expires_at)

    @property
    def is_current(self) -> bool:
        """Active *and* still inside its window.

        Read this rather than ``status == active``: a subscription that ran out
        overnight still carries the old status until something notices, and the
        thing that notices must not be the access check letting it through.
        """
        if self.status != SubStatus.active:
            return False
        expires = self.expires_at_utc
        return expires is None or expires > datetime.now(timezone.utc)

    @property
    def days_left(self) -> int | None:
        expires = self.expires_at_utc
        if expires is None:
            return None
        delta = expires - datetime.now(timezone.utc)
        return max(0, delta.days)

    @property
    def price(self) -> float:
        return (self.price_minor or 0) / 100
