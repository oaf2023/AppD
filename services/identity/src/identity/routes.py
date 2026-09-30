"""routes — endpoints HTTP del Identity Service."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response
from platform_contracts.roles import BACKOFFICE_ROLES
from platform_kernel.auth import AuthContext, require_roles, require_service, require_user
from platform_kernel.errors import NotFoundError, UnauthorizedError
from platform_kernel.idempotency import idempotent_execute
from platform_kernel.ratelimit import RateLimiter, enforce
from sqlalchemy.ext.asyncio import AsyncSession

from identity.config import IdentitySettings, get_identity_settings
from identity.db import get_session
from identity.schemas import (
    ForgotPasswordIn,
    HealthOut,
    LoginIn,
    LogoutIn,
    MessageOut,
    MfaLoginIn,
    MfaRequiredOut,
    MfaSetupOut,
    MfaVerifyIn,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    ResetPasswordIn,
    SessionOut,
    TokenPairOut,
    UserInternalOut,
    UserOut,
    VerifyEmailIn,
)
from identity.service import IdentityService

router = APIRouter()

SettingsDep = Annotated[IdentitySettings, Depends(get_identity_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _client_ip(request: Request, settings: IdentitySettings) -> str | None:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return (request.headers.get("user-agent") or "")[:400] or None


def _service(session: AsyncSession, settings: IdentitySettings) -> IdentityService:
    return IdentityService(session, settings)


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter  # type: ignore[no-any-return]


async def _active_session_guard(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
) -> AuthContext:
    """La sesión del token debe seguir activa (logout/revocación efectiva al instante)."""
    from platform_kernel.clock import utcnow

    from identity.models import Session

    if auth.session_id in ("", "mfa-pending"):
        raise UnauthorizedError("Sesión inválida")
    row = await session.get(Session, uuid.UUID(auth.session_id))
    if row is None or row.revoked_at is not None or row.expires_at < utcnow() or row.user_id != uuid.UUID(auth.user_id):
        raise UnauthorizedError("Sesión revocada o caducada")
    return auth


# ---------------------------------------------------------------------- salud


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut(service="identity", status="ok", version="0.1.0")


@router.get("/readyz", tags=["system"])
async def readyz(session: SessionDep) -> dict[str, str]:
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


# ------------------------------------------------------------------- registro


@router.post("/api/v1/auth/register", response_model=RegisterOut, status_code=201, tags=["auth"])
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RegisterOut:
    ip = _client_ip(request, settings)
    await enforce(limiter, f"register:ip:{ip}", settings.rate_limit_register_per_minute, 60)

    svc = _service(session, settings)
    payload = body.model_dump(mode="json")

    async def run() -> tuple[int, dict[str, Any]]:
        out = await svc.register(
            email=body.email,
            password=body.password,
            jurisdiction=body.jurisdiction,
            accept_terms=body.accept_terms,
            ip=ip,
            user_agent=_user_agent(request),
        )
        return 201, out.model_dump(mode="json")

    if idempotency_key:
        status, data, replayed = await idempotent_execute(
            store=request.app.state.idempotency,
            scope="auth:register",
            key=idempotency_key,
            payload=payload,
            execute=run,
        )
        response.status_code = status
        response.headers["Idempotent-Replay"] = "true" if replayed else "false"
        return RegisterOut.model_validate(data)

    status, data = await run()
    response.status_code = status
    return RegisterOut.model_validate(data)


@router.post("/api/v1/auth/verify-email", response_model=MessageOut, tags=["auth"])
async def verify_email(body: VerifyEmailIn, session: SessionDep, settings: SettingsDep) -> MessageOut:
    svc = _service(session, settings)
    await svc.verify_email(token=body.token)
    return MessageOut(detail="Email verificado")


# ---------------------------------------------------------------------- login


@router.post("/api/v1/auth/login", response_model=TokenPairOut | MfaRequiredOut, tags=["auth"])
async def login(
    body: LoginIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
) -> TokenPairOut | MfaRequiredOut:
    ip = _client_ip(request, settings)
    await enforce(limiter, f"login:ip:{ip}", settings.rate_limit_ip_per_minute, 60)
    await enforce(limiter, f"login:email:{body.email}", settings.rate_limit_login_per_minute, 60)
    svc = _service(session, settings)
    result = await svc.login(email=body.email, password=body.password, ip=ip, user_agent=_user_agent(request))
    if isinstance(result, dict):
        return MfaRequiredOut(mfa_required=True, mfa_token=result["mfa_token"])
    return result


@router.post("/api/v1/auth/mfa/login", response_model=TokenPairOut, tags=["auth"])
async def mfa_login(
    body: MfaLoginIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
) -> TokenPairOut:
    ip = _client_ip(request, settings)
    await enforce(limiter, f"mfa:ip:{ip}", settings.rate_limit_ip_per_minute, 60)
    svc = _service(session, settings)
    return await svc.mfa_login(mfa_token=body.mfa_token, code=body.code, ip=ip, user_agent=_user_agent(request))


@router.post("/api/v1/auth/refresh", response_model=TokenPairOut, tags=["auth"])
async def refresh(
    body: RefreshIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
) -> TokenPairOut:
    ip = _client_ip(request, settings)
    await enforce(limiter, f"refresh:ip:{ip}", settings.rate_limit_ip_per_minute, 60)
    svc = _service(session, settings)
    return await svc.refresh(refresh_token=body.refresh_token, ip=ip, user_agent=_user_agent(request))


@router.post("/api/v1/auth/logout", response_model=MessageOut, tags=["auth"])
async def logout(
    body: LogoutIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
) -> MessageOut:
    svc = _service(session, settings)
    await svc.logout(
        user_id=uuid.UUID(auth.user_id),
        session_id=auth.session_id,
        refresh_token=body.refresh_token,
    )
    return MessageOut(detail="Sesión cerrada")


# ---------------------------------------------------------------- contraseñas


@router.post("/api/v1/auth/password/forgot", response_model=MessageOut, status_code=202, tags=["auth"])
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
) -> MessageOut:
    ip = _client_ip(request, settings)
    await enforce(limiter, f"forgot:ip:{ip}", settings.rate_limit_forgot_per_hour, 3600)
    await enforce(limiter, f"forgot:email:{body.email}", settings.rate_limit_forgot_per_hour, 3600)
    svc = _service(session, settings)
    await svc.forgot_password(email=body.email, ip=ip)
    return MessageOut(detail="Si el cuenta existe, se enviará un enlace de restablecimiento")


@router.post("/api/v1/auth/password/reset", response_model=MessageOut, tags=["auth"])
async def reset_password(body: ResetPasswordIn, session: SessionDep, settings: SettingsDep) -> MessageOut:
    svc = _service(session, settings)
    await svc.reset_password(token=body.token, new_password=body.new_password)
    return MessageOut(detail="Contraseña actualizada; todas las sesiones han sido revocadas")


# -------------------------------------------------------------- perfil/sesiones


@router.get("/api/v1/me", response_model=UserOut, tags=["account"])
async def me(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> UserOut:
    svc = _service(session, settings)
    user = await svc.get_user(uuid.UUID(auth.user_id))
    return await svc.user_out(user)


@router.get("/api/v1/auth/sessions", response_model=list[SessionOut], tags=["account"])
async def list_sessions(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> list[SessionOut]:
    svc = _service(session, settings)
    return await svc.list_sessions(user_id=uuid.UUID(auth.user_id))


@router.delete("/api/v1/auth/sessions/{session_id}", response_model=MessageOut, tags=["account"])
async def revoke_session(
    session_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> MessageOut:
    svc = _service(session, settings)
    await svc.revoke_session(user_id=uuid.UUID(auth.user_id), session_id=session_id)
    return MessageOut(detail="Sesión revocada")


# ------------------------------------------------------------------------ MFA


@router.post("/api/v1/auth/mfa/setup", response_model=MfaSetupOut, tags=["mfa"])
async def mfa_setup(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> MfaSetupOut:
    svc = _service(session, settings)
    secret, url = await svc.mfa_setup(user_id=uuid.UUID(auth.user_id))
    return MfaSetupOut(secret=secret, otpauth_url=url)


@router.post("/api/v1/auth/mfa/verify", response_model=MessageOut, tags=["mfa"])
async def mfa_verify(
    body: MfaVerifyIn,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> MessageOut:
    svc = _service(session, settings)
    await svc.mfa_verify_enable(user_id=uuid.UUID(auth.user_id), code=body.code)
    return MessageOut(detail="MFA activado")


@router.delete("/api/v1/auth/mfa", response_model=MessageOut, tags=["mfa"])
async def mfa_disable(
    body: MfaVerifyIn,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(_active_session_guard)],
) -> MessageOut:
    svc = _service(session, settings)
    await svc.mfa_disable(user_id=uuid.UUID(auth.user_id), code=body.code)
    return MessageOut(detail="MFA desactivado")


# ---------------------------------------------------------------------- admin


@router.get("/api/v1/admin/users", response_model=list[UserOut], tags=["admin"])
async def admin_list_users(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_roles(*BACKOFFICE_ROLES))],
) -> list[UserOut]:
    svc = _service(session, settings)
    return await svc.admin_list_users()


# ------------------------------------------------------------------- interno


@router.get(
    "/internal/v1/users/{user_id}",
    response_model=UserInternalOut,
    tags=["internal"],
    summary="Perfil mínimo para servicios internos (Q-api-map §3)",
)
async def get_user_internal(
    user_id: uuid.UUID,
    session: SessionDep,
    service: Annotated[str, Depends(require_service)],
) -> UserInternalOut:
    """Solo JWT de servicio (accounts/kyc/admin); 404 si el usuario no existe."""
    from identity.models import User

    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("usuario")
    return UserInternalOut(
        user_id=user.id,
        status=user.status,
        jurisdiction=user.jurisdiction,
        email_verified=user.email_verified_at is not None,
    )


__all__ = ["router"]
