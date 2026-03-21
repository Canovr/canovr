"""JWT-Utilities: Token-Erstellung und -Validierung."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.env_loader import load_environment

load_environment()

_JWT_SECRET: str | None = None
_JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30


def _get_secret() -> str:
    global _JWT_SECRET  # noqa: PLW0603
    if _JWT_SECRET is None:
        _JWT_SECRET = os.environ.get("CANOVR_JWT_SECRET", "")
        if not _JWT_SECRET:
            raise RuntimeError(
                "CANOVR_JWT_SECRET ist nicht gesetzt. "
                "Setze eine sichere Zufallszeichenkette als Umgebungsvariable."
            )
    return _JWT_SECRET


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _get_secret(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Decode und validiere Access Token. Gibt user_id zurück."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token abgelaufen")
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Ungültiges Token: {exc}")

    if payload.get("type") != "access":
        raise ValueError("Kein Access Token")

    return int(payload["sub"])


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """Erstellt Refresh Token. Gibt (raw_token, token_hash, expires_at) zurück."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return raw_token, token_hash, expires_at


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
