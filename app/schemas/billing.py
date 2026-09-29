from pydantic import BaseModel, Field


class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = None
    # Minor units (paisa, cents). 250000 = Rs 2,500.
    price_minor: int = Field(ge=0, le=100_000_000)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    duration_days: int = Field(default=30, ge=1, le=3650)
    is_active: bool = True


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = None
    price_minor: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    is_active: bool | None = None


class SubscriptionRequest(BaseModel):
    plan_id: int


class SubscriptionApprove(BaseModel):
    """Recording a payment that happened somewhere else."""

    payment_method: str | None = None
    payment_reference: str | None = None
    # Overrides the plan's own length, for the cases that never fit it.
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    note: str | None = None


class SubscriptionNote(BaseModel):
    reason: str | None = None


class SubscriptionExtend(BaseModel):
    days: int = Field(ge=1, le=3650)


class SubscriptionGrant(BaseModel):
    """Free access with no payment: scholarships, trials, goodwill."""

    student_id: int
    track_id: int
    days: int = Field(default=30, ge=1, le=3650)
    note: str | None = None
