"""Authentifizierungs- und Account-API Tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from litestar.testing import TestClient
from sqlalchemy import select

from app.auth_jwt import create_access_token
from app.auth_models import User
from app.database import SyncSession
from app.database import Athlete as AthleteDB
from app.main import app
from app.strava_service import StravaTokenResult


@pytest.fixture
def client():
    with TestClient(app=app) as c:
        yield c


def _random_email() -> str:
    return f"auth-{uuid.uuid4()}@canovr.com"


class TestStravaAuth:
    def test_state_endpoint_returns_signed_state(self, client: TestClient):
        response = client.get("/api/auth/strava/state")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["state"], str)
        assert len(body["state"]) > 32
        assert "expires_at" in body

    def test_strava_auth_rejects_invalid_state(self, client: TestClient):
        response = client.post(
            "/api/auth/strava",
            json={"code": "dummy-code", "state": "invalid-state"},
        )
        assert response.status_code == 400

    def test_strava_auth_does_not_persist_strava_tokens(self, client: TestClient, monkeypatch):
        async def _fake_exchange_code(_code: str) -> StravaTokenResult:
            return StravaTokenResult(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                strava_athlete_id=987654321,
                first_name="Test",
                last_name="Runner",
            )

        monkeypatch.setattr("app.auth_routes.exchange_code", _fake_exchange_code)
        state_response = client.get("/api/auth/strava/state")
        state = state_response.json()["state"]

        response = client.post(
            "/api/auth/strava",
            json={"code": "valid-code", "state": state},
        )
        assert response.status_code == 201

        body = response.json()
        assert body["needs_onboarding"] is True
        assert body["strava_profile"]["first_name"] == "Test"
        assert body["strava_profile"]["last_name"] == "Runner"

        with SyncSession() as session:
            user = session.execute(
                select(User).where(User.strava_id == 987654321)
            ).scalar_one()
            assert user.strava_access_token is None
            assert user.strava_refresh_token is None
            assert user.strava_token_expires_at is None


class TestEmailAuth:
    def test_register_login_refresh_logout_flow(self, client: TestClient):
        email = _random_email()
        password = "secure-pass-123"

        register_response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": "Test User"},
        )
        assert register_response.status_code == 201
        register_body = register_response.json()
        assert register_body["needs_onboarding"] is True

        login_response = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 201
        login_body = login_response.json()

        refresh_response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login_body["refresh_token"]},
        )
        assert refresh_response.status_code == 201
        refreshed = refresh_response.json()

        logout_response = client.post(
            "/api/auth/logout",
            json={"refresh_token": refreshed["refresh_token"]},
        )
        assert logout_response.status_code == 201

        refresh_after_logout = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refreshed["refresh_token"]},
        )
        assert refresh_after_logout.status_code == 401

    def test_me_returns_athlete_id_null_without_profile(self, client: TestClient):
        email = _random_email()
        password = "secure-pass-123"
        register = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": "Me Test"},
        )
        access_token = register.json()["access_token"]

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["has_athlete"] is False
        assert body["athlete_id"] is None

    def test_me_returns_athlete_id_when_profile_exists(self, client: TestClient):
        with SyncSession() as session:
            user = User(
                email=_random_email(),
                first_name="Existing",
                last_name="Athlete",
                auth_provider="email",
            )
            session.add(user)
            session.commit()
            session.refresh(user)

            athlete = AthleteDB(
                user_id=user.id,
                name="Existing Athlete",
                target_distance="10k",
                race_time_seconds=2400,
                weekly_km=50,
                experience_years=3,
                current_phase="general",
                week_in_phase=1,
                phase_weeks_total=8,
            )
            session.add(athlete)
            session.commit()
            session.refresh(athlete)

            access_token = create_access_token(user.id)
            expected_athlete_id = athlete.id

        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me.status_code == 200
        body = me.json()
        assert body["has_athlete"] is True
        assert body["athlete_id"] == expected_athlete_id

    def test_delete_account_removes_user(self, client: TestClient):
        email = _random_email()
        password = "secure-pass-123"

        register = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": "Delete User"},
        )
        access_token = register.json()["access_token"]

        delete = client.delete("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert delete.status_code == 200
        assert delete.json()["status"] == "deleted"

        me_after_delete = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_after_delete.status_code == 401
