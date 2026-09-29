from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import Role


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    full_name: str | None = None
    role: Role
    created_at: datetime | None = None
