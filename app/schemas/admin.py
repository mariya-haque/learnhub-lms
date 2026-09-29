from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8)
    full_name: str | None = None
    email: str | None = None
    role: str = Field(default="student", pattern="^(student|teacher|admin)$")
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=32)
    full_name: str | None = None
    email: str | None = None
    role: str | None = Field(default=None, pattern="^(student|teacher|admin)$")
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8)


class ReassignRequest(BaseModel):
    """Move every course, track and class to another teacher."""

    to_user_id: int
