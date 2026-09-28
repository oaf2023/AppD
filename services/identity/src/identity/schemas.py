"""schemas — contratos de API del Identity Service (Pydantic v2)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{1,255}$")


class _BaseIn(BaseModel):
    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class RegisterIn(_BaseIn):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    jurisdiction: str | None = Field(default=None, max_length=8)
    accept_terms: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: EmailStr) -> str:
        return str(v).lower()


class RegisterOut(BaseModel):
    user_id: uuid.UUID
    email: str
    status: str
    email_verification_required: bool
    dev_verification_token: str | None = None  # solo environment=local/test (sink MOCK)


class VerifyEmailIn(_BaseIn):
    token: str = Field(min_length=32, max_length=128)


class LoginIn(_BaseIn):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: EmailStr) -> str:
        return str(v).lower()


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: uuid.UUID
    user: UserOut


class MfaRequiredOut(BaseModel):
    mfa_required: bool = True
    mfa_token: str


class MfaLoginIn(_BaseIn):
    mfa_token: str
    code: str = Field(min_length=6, max_length=8)


class RefreshIn(_BaseIn):
    refresh_token: str = Field(min_length=32, max_length=128)


class LogoutIn(_BaseIn):
    refresh_token: str | None = None


class ForgotPasswordIn(_BaseIn):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: EmailStr) -> str:
        return str(v).lower()


class ResetPasswordIn(_BaseIn):
    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=12, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    roles: list[str]
    email_verified: bool
    mfa_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    ip: str | None
    user_agent: str | None
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    detail: str


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_url: str


class MfaVerifyIn(_BaseIn):
    code: str = Field(min_length=6, max_length=8)


class HealthOut(BaseModel):
    service: str
    status: Literal["ok", "degraded"]
    version: str


__all__ = [
    "ForgotPasswordIn",
    "HealthOut",
    "LoginIn",
    "LogoutIn",
    "MessageOut",
    "MfaLoginIn",
    "MfaRequiredOut",
    "MfaSetupOut",
    "MfaVerifyIn",
    "RefreshIn",
    "RegisterIn",
    "RegisterOut",
    "ResetPasswordIn",
    "SessionOut",
    "TokenPairOut",
    "UserOut",
    "VerifyEmailIn",
]
