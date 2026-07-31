from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserRole


class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    client_type: Literal["web", "extension"] = "web"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).lower()


class LoginRequest(BaseModel):
    organization_slug: str
    email: EmailStr
    password: str
    client_type: Literal["web", "extension"] = "web"


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a credential
    expires_in: int


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: EmailStr
    role: UserRole

    model_config = {"from_attributes": True}
