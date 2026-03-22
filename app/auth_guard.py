"""Auth-Guard: JWT-Validierung als Litestar Dependency."""

from __future__ import annotations

import logging

from litestar import Request
from litestar.exceptions import NotAuthorizedException
from sqlalchemy import select

from app.auth_jwt import decode_access_token
from app.auth_models import User
from app.database import SyncSession

LOGGER = logging.getLogger(__name__)


def provide_current_user(request: Request) -> User:
    """Litestar Dependency: Extrahiert und validiert JWT aus Authorization Header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise NotAuthorizedException("Fehlender oder ungültiger Authorization Header")

    token = auth_header[7:]
    try:
        user_id = decode_access_token(token)
    except ValueError as exc:
        raise NotAuthorizedException(str(exc))

    with SyncSession() as session:
        user = session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

    if not user:
        raise NotAuthorizedException("User nicht gefunden")

    return user
