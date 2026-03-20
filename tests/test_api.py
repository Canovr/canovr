"""API-Integrationstests mit Litestar TestClient."""

import concurrent.futures
import threading
import uuid
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

import pytest
from litestar.testing import TestClient
from sqlalchemy import select

from app.database import SyncSession
from app.database import Athlete as AthleteDB
from app.main import app


@pytest.fixture
def client():
    with TestClient(app=app) as c:
        yield c


class TestRootEndpoint:
    def test_root_returns_app_info(self, client):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["app"] == "CanovR"


class TestDistances:
    def test_returns_all_distances(self, client):
        r = client.get("/api/training/distances")
        assert r.status_code == 200
        data = r.json()
        assert "10k" in data
        assert "marathon" in data
        assert data["10k"] == 10.0


class TestRules:
    def test_returns_54_rules(self, client):
        r = client.get("/api/training/rules")
        assert r.status_code == 200
        data = r.json()
        assert len(data["pyreason_rules"]) >= 47  # Mindestens unsere Regeln


class TestRecommendEndpoint:
    def test_basic_recommendation(self, client):
        r = client.post("/api/training/recommend", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "days_since_hard_workout": 3,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["athlete_phase"] == "supportive"
        assert len(data["pace_zones"]) == 8
        assert len(data["recommended_workouts"]) > 0

    def test_recovery_mode(self, client):
        r = client.post("/api/training/recommend", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "general",
            "days_since_hard_workout": 1,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["recovery_needed"] is True
        # Nur Easy + Strides
        workout_keys = [w["name"] for w in data["recommended_workouts"]]
        assert len(workout_keys) <= 2

    def test_invalid_distance(self, client):
        r = client.post("/api/training/recommend", json={
            "target_distance": "50k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "days_since_hard_workout": 3,
        })
        assert r.status_code in (400, 500)


class TestWeekEndpoint:
    def test_basic_week_plan(self, client):
        r = client.post("/api/training/week", json={
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
            "week_in_phase": 4,
            "phase_weeks_total": 8,
            "days_since_hard_workout": 3,
        })
        assert r.status_code == 201
        data = r.json()
        assert len(data["days"]) == 7
        assert data["total_km"] > 0
        assert data["phase"] == "supportive"

    def test_taper_week(self, client):
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
        })
        assert r.status_code == 201
        data = r.json()
        assert data["total_km"] < 50  # Late taper = stark reduziert


class TestPaceUpdateEndpoint:
    def test_fitness_update(self, client):
        r = client.post("/api/training/pace-update", json={
            "target_distance": "10k",
            "current_race_time_seconds": 2400,
            "new_race_time_seconds": 2340,
            "weeks_since_last_update": 5,
            "experience_years": 5,
            "weekly_km": 80,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["recommended_strategy"] == "fitness_update"
        assert data["improvement_pct"] > 0
        assert len(data["zones"]) == 8

    def test_extreme_jump_warning(self, client):
        r = client.post("/api/training/pace-update", json={
            "target_distance": "10k",
            "current_race_time_seconds": 2400,
            "new_race_time_seconds": 2100,
            "weeks_since_last_update": 2,
            "experience_years": 3,
            "weekly_km": 70,
        })
        assert r.status_code == 201
        data = r.json()
        assert len(data["warnings"]) > 0
        assert any("Extrem" in w or "extrem" in w.lower() for w in data["warnings"])


class TestAthleteEndpoints:
    def test_create_and_get_athlete(self, client):
        r = client.post("/api/athletes", json={
            "name": "Test Läufer",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        })
        assert r.status_code == 201
        data = r.json()
        athlete_id = data["id"]
        assert data["name"] == "Test Läufer"
        assert data["race_pace"] == "4:00/km"

        # GET
        r2 = client.get(f"/api/athletes/{athlete_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "Test Läufer"

    def test_update_athlete(self, client):
        # Create
        r = client.post("/api/athletes", json={
            "name": "Update Test", "target_distance": "5k",
            "race_time_seconds": 1200, "weekly_km": 60,
            "experience_years": 3, "current_phase": "general",
        })
        aid = r.json()["id"]

        # Update
        r2 = client.patch(f"/api/athletes/{aid}", json={
            "current_phase": "supportive", "weekly_km": 70,
        })
        assert r2.status_code == 200
        assert r2.json()["current_phase"] == "supportive"
        assert r2.json()["weekly_km"] == 70

    def test_create_athlete_is_idempotent_with_same_key(self, client):
        idem_key = f"test-idem-{uuid.uuid4()}"
        payload = {
            "name": "Idempotenz Test",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        }
        headers = {"X-Idempotency-Key": idem_key}

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

    def test_create_athlete_idempotency_handles_parallel_requests(self):
        idem_key = f"test-idem-race-{uuid.uuid4()}"
        payload = {
            "name": "Idempotenz Race Test",
            "target_distance": "10k",
            "race_time_seconds": 2400,
            "weekly_km": 80,
            "experience_years": 5,
            "current_phase": "supportive",
        }
        headers = {"X-Idempotency-Key": idem_key}
        barrier = threading.Barrier(2)

        def _post_once() -> tuple[int, int]:
            with TestClient(app=app) as thread_client:
                barrier.wait(timeout=5)
                resp = thread_client.post("/api/athletes", json=payload, headers=headers)
                return resp.status_code, resp.json()["id"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut1 = pool.submit(_post_once)
            fut2 = pool.submit(_post_once)
            status_id_1 = fut1.result(timeout=10)
            status_id_2 = fut2.result(timeout=10)

        statuses = {status_id_1[0], status_id_2[0]}
        ids = {status_id_1[1], status_id_2[1]}
        assert statuses == {200, 201}
        assert len(ids) == 1

        with SyncSession() as session:
            rows = session.execute(
                select(AthleteDB).where(AthleteDB.client_request_id == idem_key)
            ).scalars().all()
        assert len(rows) == 1

    def test_athlete_week_from_db(self, client):
        r = client.post("/api/athletes", json={
            "name": "Wochenplan Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
            "week_in_phase": 4, "phase_weeks_total": 8,
        })
        aid = r.json()["id"]

        r2 = client.post(f"/api/athletes/{aid}/week")
        assert r2.status_code == 201
        assert len(r2.json()["days"]) == 7

    def test_complete_workout_and_history(self, client):
        r = client.post("/api/athletes", json={
            "name": "History Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
        })
        aid = r.json()["id"]

        # Workout erledigen
        r2 = client.post(f"/api/athletes/{aid}/complete-workout", json={
            "date": "2026-03-16",
            "workout_key": "tempo_continuous",
            "zone": "z90",
            "distance_km": 12.0,
        })
        assert r2.status_code == 201
        assert r2.json()["workout_name"] == "Tempo-Dauerlauf"

        # Historie prüfen
        r3 = client.get(f"/api/athletes/{aid}/history")
        assert r3.status_code == 200
        assert len(r3.json()["workouts"]) == 1

    def test_race_result_updates_pace(self, client):
        r = client.post("/api/athletes", json={
            "name": "Race Test", "target_distance": "10k",
            "race_time_seconds": 2400, "weekly_km": 80,
            "experience_years": 5, "current_phase": "supportive",
        })
        aid = r.json()["id"]
        assert r.json()["race_pace"] == "4:00/km"

        # Rennergebnis
        r2 = client.post(f"/api/athletes/{aid}/race", json={
            "date": "2026-03-15",
            "distance": "10k",
            "time_seconds": 2340,
        })
        assert r2.status_code == 201

        # Pace sollte aktualisiert sein
        r3 = client.get(f"/api/athletes/{aid}")
        assert r3.json()["race_pace"] == "3:54/km"

    def test_athlete_not_found(self, client):
        r = client.get("/api/athletes/99999")
        assert r.status_code == 404
