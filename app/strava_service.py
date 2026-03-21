"""Strava OAuth Service: Token-Tausch und Profil-Abfrage."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.env_loader import load_environment

LOGGER = logging.getLogger(__name__)

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ATHLETE_URL = "https://www.strava.com/api/v3/athlete"

load_environment()


@dataclass
class StravaTokenResult:
    access_token: str
    refresh_token: str
    expires_at: datetime
    strava_athlete_id: int
    first_name: str
    last_name: str


def _get_client_id() -> str:
    val = os.environ.get("STRAVA_CLIENT_ID", "")
    if not val:
        raise RuntimeError("STRAVA_CLIENT_ID ist nicht gesetzt.")
    return val


def _get_client_secret() -> str:
    val = os.environ.get("STRAVA_CLIENT_SECRET", "")
    if not val:
        raise RuntimeError("STRAVA_CLIENT_SECRET ist nicht gesetzt.")
    return val


async def exchange_code(code: str) -> StravaTokenResult:
    """Tauscht Authorization Code gegen Strava Tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": _get_client_id(),
            "client_secret": _get_client_secret(),
            "code": code,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        data = resp.json()

    athlete = data.get("athlete", {})
    return StravaTokenResult(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=datetime.fromtimestamp(data["expires_at"], tz=timezone.utc),
        strava_athlete_id=athlete.get("id", data.get("athlete", {}).get("id", 0)),
        first_name=athlete.get("firstname", ""),
        last_name=athlete.get("lastname", ""),
    )


async def refresh_strava_token(refresh_token: str) -> StravaTokenResult:
    """Erneuert abgelaufene Strava Tokens."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": _get_client_id(),
            "client_secret": _get_client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        data = resp.json()

    return StravaTokenResult(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=datetime.fromtimestamp(data["expires_at"], tz=timezone.utc),
        strava_athlete_id=0,  # Not returned on refresh
        first_name="",
        last_name="",
    )
