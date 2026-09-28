"""service — lógica de negocio del Identity Service.

Todas las operaciones mutan y emiten eventos dentro de la misma transacción
(outbox transaccional, ADR-0007). Nunca se devuelve el resultado de una
operación no confirmada.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from platform_contracts import events as ev
from platform_kernel.clock import utcnow
from platform_kernel.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from platform_kernel.events import build_event
from platform_kernel.ids import new_opaque_token, new_uuid7
from platform_kernel.security.passwords import hash_password, needs_rehash, verify_password
from platform_kernel.security.tokens import hash_opaque_token, new_access_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity import totp
from identity.config import IdentitySettings
from identity.email import send_mock_email
from identity.models import (
    EmailToken,
    FeatureFlag,
    LoginHistory,
    OutboxEvent,
    Session,
    User,
    UserRole,
)
from identity.schemas import RegisterOut, SessionOut, TokenPairOut, UserOut

DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-equalization-000")


class IdentityService:
    def __init__(self, session: AsyncSession, settings: IdentitySettings) -> None:
        self.session = session
        self.settings = settings

    # ------------------------------------------------------------------ eventos

    async def _emit(
        self,
        event_type: str,
        *,
        aggregate_id: str,
        aggregate_type: str,
        payload: dict[str, Any],
    ) -> str:
        envelope = build_event(
            event_type=event_type,
            schema_version=ev.EVENT_TYPES[event_type],
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            producer="identity",
            payload=payload,
        )
        self.session.add(OutboxEvent(**envelope.to_outbox_row()))
        return envelope.event_id

    # ------------------------------------------------------------------ consulta

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError("usuario")
        return user

    async def user_out(self, user: User) -> UserOut:
        roles = (await self.session.execute(select(UserRole.role).where(UserRole.user_id == user.id))).scalars().all()
        return UserOut(
            id=user.id,
            email=user.email,
            status=user.status,
            roles=list(roles),
            email_verified=user.email_verified_at is not None,
            mfa_enabled=user.mfa_enabled,
            created_at=user.created_at,
        )

    async def _roles(self, user_id: uuid.UUID) -> list[str]:
        rows = (await self.session.execute(select(UserRole.role).where(UserRole.user_id == user_id))).scalars()
        return list(rows)

    # ------------------------------------------------------------------ registro

    async def register(
        self,
        *,
        email: str,
        password: str,
        jurisdiction: str | None,
        accept_terms: bool,
        ip: str | None,
        user_agent: str | None,
    ) -> RegisterOut:
        if not accept_terms:
            raise ValidationError("Debe aceptar los términos y condiciones")
        email = email.lower()
        existing = await self.session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("Ya existe una cuenta con este email")
        if jurisdiction is None:
            raise ValidationError("La jurisdicción es obligatoria (Jurisdiction Rules Engine)")

        user = User(
            id=new_uuid7(),
            email=email,
            password_hash=hash_password(password),
            status="pending",
            jurisdiction=jurisdiction,
        )
        self.session.add(user)
        self.session.add(UserRole(user_id=user.id, role="user"))
        await self.session.flush()

        token = new_opaque_token()
        self.session.add(
            EmailToken(
                user_id=user.id,
                purpose="verify_email",
                token_hash=hash_opaque_token(token),
                expires_at=utcnow() + timedelta(hours=self.settings.verification_ttl_hours),
            )
        )
        await send_mock_email(
            self.session,
            to_email=email,
            subject="Verifica tu cuenta",
            body_text=f"Token de verificación: {token}",
            template="verify_email",
            meta={"user_id": str(user.id)},
        )
        await self._emit(
            ev.USER_REGISTERED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={
                "user_id": str(user.id),
                "email": email,
                "mode": "DEMO",
                "jurisdiction": jurisdiction,
                "ip": ip,
                "user_agent": user_agent,
            },
        )
        await self.session.commit()

        dev_token = token if self.settings.environment in ("local", "test") else None
        return RegisterOut(
            user_id=user.id,
            email=email,
            status=user.status,
            email_verification_required=self.settings.require_email_verification,
            dev_verification_token=dev_token,
        )

    async def verify_email(self, *, token: str) -> None:
        row = await self.session.execute(
            select(EmailToken).where(
                EmailToken.token_hash == hash_opaque_token(token),
                EmailToken.purpose == "verify_email",
            )
        )
        record = row.scalar_one_or_none()
        if record is None or record.consumed_at is not None or record.expires_at < utcnow():
            raise UnauthorizedError("Token de verificación inválido o caducado")
        user = await self.session.get(User, record.user_id)
        if user is None:
            raise NotFoundError("usuario")
        record.consumed_at = utcnow()
        user.email_verified_at = utcnow()
        if user.status == "pending":
            user.status = "active"
        await self._emit(
            ev.USER_EMAIL_VERIFIED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={"user_id": str(user.id), "email": user.email, "verified_at": user.email_verified_at.isoformat()},
        )
        await self.session.commit()

    # ------------------------------------------------------------------- login

    async def _record_login(
        self,
        *,
        user: User | None,
        email: str,
        ip: str | None,
        user_agent: str | None,
        success: bool,
        reason: str | None,
    ) -> None:
        self.session.add(
            LoginHistory(
                user_id=user.id if user else None,
                email=email,
                ip=ip,
                user_agent=user_agent,
                success=success,
                reason=reason,
            )
        )

    async def _fail_login(
        self, *, user: User | None, email: str, ip: str | None, user_agent: str | None, reason: str
    ) -> None:
        await self._record_login(user=user, email=email, ip=ip, user_agent=user_agent, success=False, reason=reason)
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= self.settings.login_max_failures:
                user.locked_until = utcnow() + timedelta(minutes=self.settings.lockout_minutes)
                user.status = "locked" if user.status == "active" else user.status
        await self._emit(
            ev.LOGIN_FAILED,
            aggregate_id=str(user.id) if user else "unknown",
            aggregate_type="User",
            payload={
                "user_id": str(user.id) if user else None,
                "email": email,
                "ip": ip,
                "reason": reason,
                "attempt_count": (user.failed_login_count if user else 0),
            },
        )
        await self.session.commit()

    async def login(
        self, *, email: str, password: str, ip: str | None, user_agent: str | None
    ) -> TokenPairOut | dict[str, Any]:
        email = email.lower()
        row = await self.session.execute(select(User).where(User.email == email))
        user = row.scalar_one_or_none()

        if user is None:
            verify_password(DUMMY_PASSWORD_HASH, password)
            await self._fail_login(user=None, email=email, ip=ip, user_agent=user_agent, reason="unknown_user")
            raise UnauthorizedError("Credenciales inválidas")

        if user.locked_until is not None and user.locked_until > utcnow():
            await self._fail_login(user=user, email=email, ip=ip, user_agent=user_agent, reason="locked")
            raise ForbiddenError("Cuenta bloqueada temporalmente por intentos fallidos")

        if not verify_password(user.password_hash, password):
            await self._fail_login(user=user, email=email, ip=ip, user_agent=user_agent, reason="bad_password")
            raise UnauthorizedError("Credenciales inválidas")

        if self.settings.require_email_verification and user.email_verified_at is None:
            await self._fail_login(user=user, email=email, ip=ip, user_agent=user_agent, reason="unverified_email")
            raise ForbiddenError("Email no verificado")

        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        if user.mfa_enabled and self.settings.flag_mfa:
            mfa_token = new_access_token(
                user_id=str(user.id),
                session_id="mfa-pending",
                roles=[],
                secret=self.settings.jwt_secret,
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                ttl_seconds=300,
            )
            await self._record_login(
                user=user, email=email, ip=ip, user_agent=user_agent, success=False, reason="mfa_required"
            )
            await self.session.commit()
            return {"mfa_required": True, "mfa_token": mfa_token}

        return await self._issue_session(user=user, ip=ip, user_agent=user_agent, mfa_used=False)

    async def mfa_login(self, *, mfa_token: str, code: str, ip: str | None, user_agent: str | None) -> TokenPairOut:
        from platform_kernel.security.tokens import TokenError, decode_jwt

        try:
            claims = decode_jwt(
                mfa_token,
                secret=self.settings.jwt_secret,
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                expected_type="access",
            )
        except TokenError as exc:
            raise UnauthorizedError("Token MFA inválido") from exc
        if claims.get("sid") != "mfa-pending":
            raise UnauthorizedError("Token MFA inválido")
        user = await self.session.get(User, uuid.UUID(str(claims["sub"])))
        if user is None or not user.mfa_enabled or user.mfa_secret is None:
            raise UnauthorizedError("MFA no configurado")
        if not totp.verify_totp(user.mfa_secret, code):
            raise UnauthorizedError("Código MFA incorrecto")
        return await self._issue_session(user=user, ip=ip, user_agent=user_agent, mfa_used=True)

    async def _issue_session(
        self, *, user: User, ip: str | None, user_agent: str | None, mfa_used: bool
    ) -> TokenPairOut:
        refresh_token = new_opaque_token()
        session = Session(
            user_id=user.id,
            refresh_hash=hash_opaque_token(refresh_token),
            expires_at=utcnow() + timedelta(days=self.settings.refresh_ttl_days),
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(session)
        user.failed_login_count = 0
        user.locked_until = None
        if user.status == "locked":
            user.status = "active"
        await self.session.flush()

        await self._record_login(user=user, email=user.email, ip=ip, user_agent=user_agent, success=True, reason=None)
        await self._emit(
            ev.USER_LOGGED_IN,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={
                "user_id": str(user.id),
                "session_id": str(session.id),
                "ip": ip,
                "user_agent": user_agent,
                "mfa_used": mfa_used,
            },
        )
        await self.session.commit()

        access = new_access_token(
            user_id=str(user.id),
            session_id=str(session.id),
            roles=await self._roles(user.id),
            secret=self.settings.jwt_secret,
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
            ttl_seconds=self.settings.access_token_ttl_seconds,
        )
        return TokenPairOut(
            access_token=access,
            refresh_token=refresh_token,
            expires_in=self.settings.access_token_ttl_seconds,
            session_id=session.id,
            user=await self.user_out(user),
        )

    # --------------------------------------------------------------- refresh

    async def refresh(self, *, refresh_token: str, ip: str | None, user_agent: str | None) -> TokenPairOut:
        row = await self.session.execute(
            select(Session).where(Session.refresh_hash == hash_opaque_token(refresh_token))
        )
        session = row.scalar_one_or_none()
        if session is None:
            raise UnauthorizedError("Refresh token inválido")

        if session.revoked_at is not None:
            # Reuso detectado: revocar toda la familia (ADR-0008)
            await self._revoke_family(session, reason="refresh_reuse_detected")
            raise UnauthorizedError("Refresh token reutilizado; sesión revocada")

        if session.expires_at < utcnow():
            raise UnauthorizedError("Sesión caducada")

        user = await self.session.get(User, session.user_id)
        if user is None or user.status in ("disabled", "deleted"):
            raise UnauthorizedError("Cuenta no disponible")

        new_refresh = new_opaque_token()
        old_id = session.id
        session.revoked_at = utcnow()
        session.revoke_reason = "rotated"
        new_session = Session(
            user_id=user.id,
            family_id=session.family_id,
            refresh_hash=hash_opaque_token(new_refresh),
            expires_at=utcnow() + timedelta(days=self.settings.refresh_ttl_days),
            rotated_from=old_id,
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(new_session)
        await self.session.flush()
        await self.session.commit()

        access = new_access_token(
            user_id=str(user.id),
            session_id=str(new_session.id),
            roles=await self._roles(user.id),
            secret=self.settings.jwt_secret,
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
            ttl_seconds=self.settings.access_token_ttl_seconds,
        )
        return TokenPairOut(
            access_token=access,
            refresh_token=new_refresh,
            expires_in=self.settings.access_token_ttl_seconds,
            session_id=new_session.id,
            user=await self.user_out(user),
        )

    async def _revoke_family(self, session: Session, *, reason: str) -> None:
        rows = await self.session.execute(select(Session).where(Session.family_id == session.family_id))
        revoked_any = False
        for s in rows.scalars():
            if s.revoked_at is None:
                s.revoked_at = utcnow()
                s.revoke_reason = reason
                revoked_any = True
                await self._emit(
                    ev.SESSION_REVOKED,
                    aggregate_id=str(s.id),
                    aggregate_type="Session",
                    payload={
                        "session_id": str(s.id),
                        "user_id": str(s.user_id),
                        "reason": reason,
                        "revoked_by": "system",
                    },
                )
        if revoked_any:
            await self.session.commit()

    # ------------------------------------------------------------------ logout

    async def logout(self, *, user_id: uuid.UUID, session_id: str | None, refresh_token: str | None) -> None:
        session: Session | None = None
        if refresh_token:
            row = await self.session.execute(
                select(Session).where(Session.refresh_hash == hash_opaque_token(refresh_token))
            )
            session = row.scalar_one_or_none()
            if session is None or session.user_id != user_id:
                raise UnauthorizedError("Refresh token inválido")
        elif session_id:
            session = await self.session.get(Session, uuid.UUID(session_id))
            if session is None or session.user_id != user_id:
                raise NotFoundError("sesión")

        if session is None:
            raise ValidationError("Se requiere refresh_token o session_id")

        if session.revoked_at is None:
            session.revoked_at = utcnow()
            session.revoke_reason = "logout"
            await self._emit(
                ev.SESSION_REVOKED,
                aggregate_id=str(session.id),
                aggregate_type="Session",
                payload={
                    "session_id": str(session.id),
                    "user_id": str(session.user_id),
                    "reason": "logout",
                    "revoked_by": str(user_id),
                },
            )
            await self.session.commit()

    async def list_sessions(self, *, user_id: uuid.UUID) -> list[SessionOut]:
        rows = await self.session.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None), Session.expires_at > utcnow())
            .order_by(Session.created_at.desc())
        )
        return [SessionOut.model_validate(s) for s in rows.scalars()]

    async def revoke_session(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        session = await self.session.get(Session, session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("sesión")
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            session.revoke_reason = "user_revoked"
            await self._emit(
                ev.SESSION_REVOKED,
                aggregate_id=str(session.id),
                aggregate_type="Session",
                payload={
                    "session_id": str(session.id),
                    "user_id": str(user_id),
                    "reason": "user_revoked",
                    "revoked_by": str(user_id),
                },
            )
            await self.session.commit()

    # -------------------------------------------------------------- contraseñas

    async def forgot_password(self, *, email: str, ip: str | None) -> None:
        email = email.lower()
        row = await self.session.execute(select(User).where(User.email == email))
        user = row.scalar_one_or_none()
        if user is None:
            return  # sin enumeración: respuesta idéntica
        token = new_opaque_token()
        self.session.add(
            EmailToken(
                user_id=user.id,
                purpose="password_reset",
                token_hash=hash_opaque_token(token),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        await send_mock_email(
            self.session,
            to_email=email,
            subject="Restablece tu contraseña",
            body_text=f"Token de restablecimiento: {token}",
            template="password_reset",
            meta={"user_id": str(user.id), "ip": ip},
        )
        await self._emit(
            ev.PASSWORD_RESET_REQUESTED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={
                "user_id": str(user.id),
                "email": email,
                "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
            },
        )
        await self.session.commit()

    async def reset_password(self, *, token: str, new_password: str) -> None:
        row = await self.session.execute(
            select(EmailToken).where(
                EmailToken.token_hash == hash_opaque_token(token),
                EmailToken.purpose == "password_reset",
            )
        )
        record = row.scalar_one_or_none()
        if record is None or record.consumed_at is not None or record.expires_at < utcnow():
            raise UnauthorizedError("Token de restablecimiento inválido o caducado")
        user = await self.session.get(User, record.user_id)
        if user is None:
            raise NotFoundError("usuario")
        record.consumed_at = utcnow()
        user.password_hash = hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        await self._revoke_family_for_user(user, reason="password_reset")
        await self._emit(
            ev.PASSWORD_RESET_COMPLETED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={"user_id": str(user.id), "reset_at": utcnow().isoformat()},
        )
        await self.session.commit()

    async def _revoke_family_for_user(self, user: User, *, reason: str) -> None:
        rows = await self.session.execute(select(Session).where(Session.user_id == user.id))
        for s in rows.scalars():
            if s.revoked_at is None:
                s.revoked_at = utcnow()
                s.revoke_reason = reason
                await self._emit(
                    ev.SESSION_REVOKED,
                    aggregate_id=str(s.id),
                    aggregate_type="Session",
                    payload={
                        "session_id": str(s.id),
                        "user_id": str(user.id),
                        "reason": reason,
                        "revoked_by": "system",
                    },
                )

    # --------------------------------------------------------------------- MFA

    async def mfa_setup(self, *, user_id: uuid.UUID) -> tuple[str, str]:
        if not self.settings.flag_mfa:
            raise ForbiddenError("MFA no habilitado (feature flag)")
        user = await self.get_user(user_id)
        secret = totp.generate_secret()
        user.mfa_secret = secret
        user.mfa_enabled = False
        await self.session.commit()
        url = totp.otpauth_url(secret, user.email, "PLATFORM")
        return secret, url

    async def mfa_verify_enable(self, *, user_id: uuid.UUID, code: str) -> None:
        if not self.settings.flag_mfa:
            raise ForbiddenError("MFA no habilitado (feature flag)")
        user = await self.get_user(user_id)
        if user.mfa_secret is None:
            raise ValidationError("MFA no configurado; ejecuta setup primero")
        if not totp.verify_totp(user.mfa_secret, code):
            raise UnauthorizedError("Código incorrecto")
        user.mfa_enabled = True
        await self._emit(
            ev.MFA_ENABLED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={"user_id": str(user.id), "mfa_type": "totp", "enabled_at": utcnow().isoformat()},
        )
        await self.session.commit()

    async def mfa_disable(self, *, user_id: uuid.UUID, code: str) -> None:
        if not self.settings.flag_mfa:
            raise ForbiddenError("MFA no habilitado (feature flag)")
        user = await self.get_user(user_id)
        if not user.mfa_enabled or user.mfa_secret is None:
            raise ValidationError("MFA no está activo")
        if not totp.verify_totp(user.mfa_secret, code):
            raise UnauthorizedError("Código incorrecto")
        user.mfa_enabled = False
        user.mfa_secret = None
        await self._emit(
            ev.MFA_DISABLED,
            aggregate_id=str(user.id),
            aggregate_type="User",
            payload={"user_id": str(user.id), "mfa_type": "totp", "disabled_at": utcnow().isoformat()},
        )
        await self.session.commit()

    # ------------------------------------------------------------ feature flags

    async def is_flag_enabled(self, key: str) -> bool:
        flag = await self.session.get(FeatureFlag, key)
        return bool(flag and flag.enabled)

    # ------------------------------------------------------------------- admin

    async def admin_list_users(self, *, limit: int = 50) -> list[UserOut]:
        rows = await self.session.execute(select(User).order_by(User.created_at.desc()).limit(limit))
        return [await self.user_out(u) for u in rows.scalars()]


__all__ = ["DUMMY_PASSWORD_HASH", "IdentityService", "new_uuid7"]
