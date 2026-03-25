"""OAuth-State Utilities fuer Strava Login.

Erzeugt und validiert signierte, kurzlebige State-Tokens.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.env_loader import load_environment

load_environment()

_STATE_ALGORITHM = "HS256"
_STATE_TTL_SECONDS = 600  # 10 Minuten


def _state_secret() -> str:
    """Liest den State-Secret aus der Umgebung.

    Prioritaet:
    1) CANOVR_OAUTH_STATE_SECRET
    2) CANOVR_JWT_SECRET (Fallback)
    """
    secret = os.environ.get("CANOVR_OAUTH_STATE_SECRET") or os.environ.get("CANOVR_JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "Kein OAuth-State-Secret gefunden. "
            "Setze CANOVR_OAUTH_STATE_SECRET oder CANOVR_JWT_SECRET."
        )
    return secret


def create_strava_oauth_state() -> tuple[str, datetime]:
    """Erzeugt ein signiertes State-Token fuer den Strava OAuth Flow."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_STATE_TTL_SECONDS)
    payload = {
        "typ": "strava_oauth_state",
        "nonce": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, _state_secret(), algorithm=_STATE_ALGORITHM)
    return token, expires_at


def verify_strava_oauth_state(state_token: str) -> None:
    """Validiert das signierte State-Token.

    Wirft ValueError bei ungueltigem/abgelaufenem Token.
    """
    if not state_token or not state_token.strip():
        raise ValueError("State fehlt.")

    try:
        payload = jwt.decode(
            state_token,
            _state_secret(),
            algorithms=[_STATE_ALGORITHM],
            options={"require": ["exp", "iat", "nonce", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("State ist abgelaufen.") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("State ist ungueltig.") from exc

    if payload.get("typ") != "strava_oauth_state":
        raise ValueError("State-Typ ist ungueltig.")
