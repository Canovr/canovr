"""API-Integrationstests mit Litestar TestClient."""

import concurrent.futures
import os
import threading
import uuid
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

# Ensure JWT secret is set for tests
os.environ.setdefault("CANOVR_JWT_SECRET", "test-secret-do-not-use-in-production")

import pytest
from litestar.testing import TestClient
from sqlalchemy import select

from app.auth_jwt import create_access_token
from app.auth_models import User
from app.database import SyncSession
from app.database import Athlete as AthleteDB
from app.main import app


@pytest.fixture
def client():
    with TestClient(app=app) as c:
        yield c


@pytest.fixture
def auth_headers():
    """Erstellt einen Test-User in der DB und gibt Auth-Headers mit gültigem JWT zurück."""
    with SyncSession() as session:
        user = User(email=f"test-{uuid.uuid4()}@canovr.com", first_name="Test", last_name="User", auth_provider="email")
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

    token = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


class TestRootEndpoint:
    def test_root_returns_app_info(self, client):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["app"] == "CanovR"


class TestDistances:
    def test_returns_all_distances(self, client, auth_headers):
        r = client.get("/api/training/distances", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "10k" in data
        assert "marathon" in data
        assert data["10k"] == 10.0


class TestRules:
    def test_returns_54_rules(self, client, auth_headers):
        r = client.get("/api/training/rules", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data["pyreason_rules"]) >= 47  # Mindestens unsere Regeln


class TestRecommendEndpoint:
    def test_basic_recommendation(self, client, auth_headers):
        r = client.post("/api/training/recommend", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "days_since_hard_workout": 3,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data["athlete_phase"] == "supportive"
        assert len(data["pace_zones"]) == 8
        assert len(data["recommended_workouts"]) > 0

    def test_recovery_mode(self, client, auth_headers):
        r = client.post("/api/training/recommend", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "general",
            "days_since_hard_workout": 1,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data["recovery_needed"] is True
        # Nur Easy + Strides
        workout_keys = [w["name"] for w in data["recommended_workouts"]]
        assert len(workout_keys) <= 2

    def test_invalid_distance(self, client, auth_headers):
        r = client.post("/api/training/recommend", json={
            "target_distance": "50k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "days_since_hard_workout": 3,
        }, headers=auth_headers)
        assert r.status_code in (400, 500)


class TestWeekEndpoint:
    def test_basic_week_plan(self, client, auth_headers):
        r = client.post("/api/training/week", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "week_in_phase": 4,
            "phase_weeks_total": 8,
            "days_since_hard_workout": 3,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert len(data["days"]) == 7
        assert data["total_km"] > 0
        assert data["phase"] == "supportive"

    def test_taper_week(self, client, auth_headers):
        r = client.post("/api/training/week", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "specific",
            "week_in_phase": 6,
            "phase_weeks_total": 6,
            "days_since_hard_workout": 3,
            "days_to_race": 3,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data["total_km"] < 50  # Late taper = stark reduziert


class TestPaceUpdateEndpoint:
    def test_fitness_update(self, client, auth_headers):
        r = client.post("/api/training/pace-update", json={
            "target_distance": "10k",
            "current_race_time_seconds": 2400,
            "new_race_time_seconds": 2340,
            "weeks_since_last_update": 5,
            "experience_years": 5,
            "weekly_km": 80,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert data["recommended_strategy"] == "fitness_update"
        assert data["improvement_pct"] > 0
        assert len(data["zones"]) == 8

    def test_extreme_jump_warning(self, client, auth_headers):
        r = client.post("/api/training/pace-update", json={
            "target_distance": "10k",
            "current_race_time_seconds": 2400,
            "new_race_time_seconds": 2100,
            "weeks_since_last_update": 2,
            "experience_years": 3,
            "weekly_km": 70,
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        assert len(data["warnings"]) > 0
        assert any("Extrem" in w or "extrem" in w.lower() for w in data["warnings"])


class TestAthleteEndpoints:
    def test_create_and_get_athlete(self, client, auth_headers):
        r = client.post("/api/athletes", json={
            "name": "Test Läufer",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        }, headers=auth_headers)
        assert r.status_code == 201
        data = r.json()
        athlete_id = data["id"]
        assert data["name"] == "Test Läufer"
        assert data["race_pace"] == "4:00/km"

        # GET
        r2 = client.get(f"/api/athletes/{athlete_id}", headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["name"] == "Test Läufer"

    def test_update_athlete(self, client, auth_headers):
        # Create
        r = client.post("/api/athletes", json={
            "name": "Update Test", "target_distance": "5k",
            "race_time_seconds": 1200, "weekly_km": 60,
            "experience_years": 3, "current_phase": "general",
        }, headers=auth_headers)
        aid = r.json()["id"]

        # Update
        r2 = client.patch(f"/api/athletes/{aid}", json={
            "current_phase": "supportive", "weekly_km": 70,
        }, headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["current_phase"] == "supportive"
        assert r2.json()["weekly_km"] == 70

    def test_create_athlete_is_idempotent_with_same_key(self, client, auth_headers):
        idem_key = f"test-idem-{uuid.uuid4()}"
        payload = {
            "name": "Idempotenz Test",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        }
        headers = {**auth_headers, "X-Idempotency-Key": idem_key}

        first = client.post("/api/athletes", json=payload, headers=headers)
        second = client.post("/api/athletes", json=payload, headers=headers)

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert second.headers.get("X-Idempotency-Replayed") == "true"

        with SyncSession() as session:
            rows = session.execute(
                select(AthleteDB).where(AthleteDB.client_request_id == idem_key)
            ).scalars().all()
        assert len(rows) == 1

    def test_create_athlete_idempotency_handles_parallel_requests(self, client, auth_headers):
        idem_key = f"test-idem-race-{uuid.uuid4()}"
        payload = {
            "name": "Idempotenz Race Test",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        }
        headers = {**auth_headers, "X-Idempotency-Key": idem_key}
        barrier = threading.Barrier(2)

        def _post_once() -> tuple[int, int]:
            barrier.wait(timeout=5)
            resp = client.post("/api/athletes", json=payload, headers=headers)
            return resp.status_code, resp.json()["id"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut1 = pool.submit(_post_once)
            fut2 = pool.submit(_post_once)
            status_id_1 = fut1.result(timeout=10)
            status_id_2 = fut2.result(timeout=10)

        ids = {status_id_1[1], status_id_2[1]}
        assert len(ids) == 1

        with SyncSession() as session:
            rows = session.execute(
                select(AthleteDB).where(AthleteDB.client_request_id == idem_key)
            ).scalars().all()
        assert len(rows) == 1

    def test_athlete_week_from_db(self, client, auth_headers):
        r = client.post("/api/athletes", json={
            "name": "Wochenplan Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
            "week_in_phase": 4, "phase_weeks_total": 8,
        }, headers=auth_headers)
        aid = r.json()["id"]

        r2 = client.post(f"/api/athletes/{aid}/week", headers=auth_headers)
        assert r2.status_code == 201
        assert len(r2.json()["days"]) == 7

    def test_complete_workout_and_history(self, client, auth_headers):
        r = client.post("/api/athletes", json={
            "name": "History Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
        }, headers=auth_headers)
        aid = r.json()["id"]

        # Workout erledigen
        r2 = client.post(f"/api/athletes/{aid}/complete-workout", json={
            "date": "2026-03-16",
            "workout_key": "tempo_continuous",
            "zone": "z90",
            "distance_km": 12.0,
        }, headers=auth_headers)
        assert r2.status_code == 201
        assert r2.json()["workout_name"] == "Tempo-Dauerlauf"

        # Historie prüfen
        r3 = client.get(f"/api/athletes/{aid}/history", headers=auth_headers)
        assert r3.status_code == 200
        assert len(r3.json()["workouts"]) == 1

    def test_race_result_updates_pace(self, client, auth_headers):
        r = client.post("/api/athletes", json={
            "name": "Race Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
        }, headers=auth_headers)
        aid = r.json()["id"]
        assert r.json()["race_pace"] == "4:00/km"

        # Rennergebnis
        r2 = client.post(f"/api/athletes/{aid}/race", json={
            "date": "2026-03-15",
            "distance": "10k",
            "time_seconds": 2340,
        }, headers=auth_headers)
        assert r2.status_code == 201

        # Pace sollte aktualisiert sein
        r3 = client.get(f"/api/athletes/{aid}", headers=auth_headers)
        assert r3.json()["race_pace"] == "3:54/km"

    def test_athlete_not_found(self, client, auth_headers):
        r = client.get("/api/athletes/99999", headers=auth_headers)
        assert r.status_code == 404
