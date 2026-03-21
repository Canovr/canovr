"""Auth-Routes: Strava OAuth, Email-Login, Token-Management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

import bcrypt
from litestar import Controller, get, post
from litestar.exceptions import ClientException, NotAuthorizedException
from litestar.params import Body
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth_jwt import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from app.auth_models import (
    AuthResponse,
    EmailLoginRequest,
    EmailRegisterRequest,
    RefreshTokenRequest,
    StravaAuthRequest,
    StravaProfile,
    User,
)
from app.auth_models import RefreshToken as RefreshTokenDB
from app.database import SyncSession
from app.strava_service import exchange_code

LOGGER = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _issue_tokens(user_id: int) -> tuple[str, str]:
    """Erstellt Access + Refresh Token Paar und speichert Refresh Token in DB."""
    access_token = create_access_token(user_id)
    raw_refresh, token_hash, expires_at = create_refresh_token(user_id)

    with SyncSession() as session:
        db_token = RefreshTokenDB(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(db_token)
        session.commit()

    return access_token, raw_refresh


def _user_needs_onboarding(user: User) -> bool:
    return user.athlete is None


class AuthController(Controller):
    path = "/api/auth"
    tags = ["Auth"]

    @post("/strava")
    async def strava_auth(
        self,
        data: Annotated[StravaAuthRequest, Body()],
    ) -> AuthResponse:
        """Strava OAuth: Code gegen JWT tauschen."""
        try:
            strava_result = await exchange_code(data.code)
        except Exception as exc:
            LOGGER.exception("strava.auth.failed")
            raise ClientException(
                detail=f"Strava-Authentifizierung fehlgeschlagen: {exc}",
                status_code=502,
            )

        with SyncSession() as session:
            # Bestehender User?
            user = session.execute(
                select(User).where(User.strava_id == strava_result.strava_athlete_id)
            ).scalar_one_or_none()

            if user:
                # Token aktualisieren
                user.strava_access_token = strava_result.access_token
                user.strava_refresh_token = strava_result.refresh_token
                user.strava_token_expires_at = strava_result.expires_at
                session.commit()
                session.refresh(user)
            else:
                # Neuer User
                user = User(
                    strava_id=strava_result.strava_athlete_id,
                    first_name=strava_result.first_name,
                    last_name=strava_result.last_name,
                    strava_access_token=strava_result.access_token,
                    strava_refresh_token=strava_result.refresh_token,
                    strava_token_expires_at=strava_result.expires_at,
                    auth_provider="strava",
                )
                session.add(user)
                session.commit()
                session.refresh(user)

            needs_onboarding = _user_needs_onboarding(user)
            user_id = user.id
            first_name = user.first_name or ""
            last_name = user.last_name or ""

        access_token, refresh_token = _issue_tokens(user_id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            needs_onboarding=needs_onboarding,
            strava_profile=StravaProfile(
                first_name=first_name,
                last_name=last_name,
            ),
        )

    @post("/register")
    async def register(
        self,
        data: Annotated[EmailRegisterRequest, Body()],
    ) -> AuthResponse:
        """Email-Registrierung: Neuen Account anlegen."""
        password_hash = _hash_password(data.password)

        # Name aufteilen (falls Leerzeichen enthalten)
        name_parts = data.name.strip().split(maxsplit=1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        with SyncSession() as session:
            user = User(
                email=data.email.lower().strip(),
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                auth_provider="email",
            )
            session.add(user)
            try:
                session.commit()
                session.refresh(user)
            except IntegrityError:
                raise ClientException(
                    detail="Ein Account mit dieser Email existiert bereits.",
                    status_code=409,
                )
            user_id = user.id

        access_token, refresh_token = _issue_tokens(user_id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            needs_onboarding=True,
        )

    @post("/login")
    async def login(
        self,
        data: Annotated[EmailLoginRequest, Body()],
    ) -> AuthResponse:
        """Email-Login: Bestehenden Account authentifizieren."""
        with SyncSession() as session:
            user = session.execute(
                select(User).where(User.email == data.email.lower().strip())
            ).scalar_one_or_none()

        if not user or not user.password_hash:
            raise NotAuthorizedException("Ungültige Email oder Passwort")

        if not _verify_password(data.password, user.password_hash):
            raise NotAuthorizedException("Ungültige Email oder Passwort")

        needs_onboarding = _user_needs_onboarding(user)
        access_token, refresh_token = _issue_tokens(user.id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            needs_onboarding=needs_onboarding,
        )

    @post("/refresh")
    async def refresh(
        self,
        data: Annotated[RefreshTokenRequest, Body()],
    ) -> AuthResponse:
        """Token Refresh: Neues Token-Paar ausgeben."""
        token_hash = hash_refresh_token(data.refresh_token)

        with SyncSession() as session:
            db_token = session.execute(
                select(RefreshTokenDB).where(RefreshTokenDB.token_hash == token_hash)
            ).scalar_one_or_none()

            if not db_token:
                raise NotAuthorizedException("Ungültiges Refresh Token")

            if db_token.revoked_at is not None:
                raise NotAuthorizedException("Refresh Token wurde widerrufen")

            if db_token.expires_at < datetime.now(timezone.utc):
                raise NotAuthorizedException("Refresh Token abgelaufen")

            # Altes Token revoken (Rotation)
            db_token.revoked_at = datetime.now(timezone.utc)
            session.commit()

            user_id = db_token.user_id

        access_token, new_refresh = _issue_tokens(user_id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=new_refresh,
            needs_onboarding=False,
        )

    @post("/logout")
    async def logout(
        self,
        data: Annotated[RefreshTokenRequest, Body()],
    ) -> dict[str, str]:
        """Logout: Refresh Token revoken."""
        token_hash = hash_refresh_token(data.refresh_token)

        with SyncSession() as session:
            db_token = session.execute(
                select(RefreshTokenDB).where(RefreshTokenDB.token_hash == token_hash)
            ).scalar_one_or_none()

            if db_token and db_token.revoked_at is None:
                db_token.revoked_at = datetime.now(timezone.utc)
                session.commit()

        return {"status": "ok"}

    @get("/me")
    async def me(self, current_user: User) -> dict:
        """Aktueller User-Info (auth required)."""
        return {
            "id": current_user.id,
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "auth_provider": current_user.auth_provider,
            "has_athlete": current_user.athlete is not None,
        }
