"""Athleten-API mit Persistenz.

CRUD für Athleten, Rennergebnisse, Workout-Tracking und
DB-gestützte Wochenplanung.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time

from typing import Annotated

from litestar import Controller, delete, get, patch, post
from litestar.exceptions import NotFoundException
from litestar.openapi.spec import Example
from litestar.params import Body
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import CompletedWorkout, PaceHistory, RaceResult, WeekPlan, SyncSession
from app.database import Athlete as AthleteDB
from app.inference_worker import get_inference_worker
from app.knowledge import DISTANCE_VOLUME, WORKOUT_TEMPLATES
from app.models import (
    DISTANCES,
    AthleteInput,
    PaceUpdateInput,
    WeekPlanInput,
    WeeklyPlan,
)
from app.pace import ZONE_ROLES, compute_all_zones, race_pace_per_km, seconds_to_display
from app.planner import generate_week_plan
from app.reasoner import InferenceResult, run_pace_update_inference


_LOGGER = logging.getLogger("canovr.athlete_week")


# =========================================================================
#  REQUEST / RESPONSE MODELLE
# =========================================================================

class AthleteCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "Lisa Müller",
            "target_distance": "10k",
            "race_time_seconds": 2700.0,
            "weekly_km": 55.0,
            "experience_years": 3,
            "current_phase": "general",
            "week_in_phase": 1,
            "phase_weeks_total": 8,
            "rest_day": 1,
            "long_run_day": 0,
            "days_to_race": 56,
        },
    })

    name: str
    target_distance: str
    race_time_seconds: float = Field(gt=0)
    weekly_km: float = Field(gt=0)
    experience_years: int = Field(ge=0)
    current_phase: str = "general"
    week_in_phase: int = Field(default=1, ge=1)
    phase_weeks_total: int = Field(default=8, ge=1)
    rest_day: int | None = Field(default=None, ge=0, le=6)
    long_run_day: int | None = Field(default=None, ge=0, le=6)
    days_to_race: int | None = Field(default=None, ge=0)


class AthleteUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "weekly_km": 65.0,
            "current_phase": "supportive",
            "week_in_phase": 3,
            "days_to_race": 42,
        },
    })

    name: str | None = None
    target_distance: str | None = None
    race_time_seconds: float | None = Field(default=None, gt=0)
    weekly_km: float | None = Field(default=None, gt=0)
    experience_years: int | None = Field(default=None, ge=0)
    current_phase: str | None = None
    week_in_phase: int | None = Field(default=None, ge=1)
    phase_weeks_total: int | None = Field(default=None, ge=1)
    rest_day: int | None = None
    long_run_day: int | None = None
    days_to_race: int | None = None


class AthleteResponse(BaseModel):
    id: int
    name: str
    target_distance: str
    race_time_seconds: float
    race_pace: str
    weekly_km: float
    experience_years: int
    current_phase: str
    week_in_phase: int
    phase_weeks_total: int
    rest_day: int | None
    long_run_day: int | None
    days_to_race: int | None
    pace_zones: dict[str, str]


class RaceResultCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "date": "2026-03-15",
            "distance": "10k",
            "time_seconds": 2650.0,
            "notes": "Flache Strecke, leichter Gegenwind ab km 7",
        },
    })

    date: dt.date
    distance: str
    time_seconds: float = Field(gt=0)
    notes: str | None = None


class RaceResultResponse(BaseModel):
    id: int
    date: dt.date
    distance: str
    time_seconds: float
    pace: str
    notes: str | None


class CompleteWorkoutCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "date": "2026-03-17",
            "workout_key": "tempo_continuous",
            "zone": "z85",
            "distance_km": 12.0,
            "duration_minutes": 55.0,
            "notes": "Inkl. 2km Ein-/Auslaufen",
        },
    })

    date: dt.date
    workout_key: str
    zone: str | None = None
    distance_km: float | None = None
    duration_minutes: float | None = None
    notes: str | None = None


class WorkoutHistoryResponse(BaseModel):
    id: int
    date: dt.date
    workout_key: str
    workout_name: str
    zone: str | None
    distance_km: float | None
    notes: str | None


# =========================================================================
#  HILFSFUNKTIONEN
# =========================================================================

def _get_athlete(athlete_id: int) -> AthleteDB:
    with SyncSession() as session:
        result = session.execute(
            select(AthleteDB).where(AthleteDB.id == athlete_id)
        )
        athlete = result.scalar_one_or_none()
        if not athlete:
            raise NotFoundException(detail=f"Athlet {athlete_id} nicht gefunden")
        return athlete


def _athlete_to_response(a: AthleteDB) -> AthleteResponse:
    rp = race_pace_per_km(a.target_distance, a.race_time_seconds)
    zones = compute_all_zones(rp)
    return AthleteResponse(
        id=a.id, name=a.name, target_distance=a.target_distance,
        race_time_seconds=a.race_time_seconds,
        race_pace=seconds_to_display(rp),
        weekly_km=a.weekly_km, experience_years=a.experience_years,
        current_phase=a.current_phase,
        week_in_phase=a.week_in_phase,
        phase_weeks_total=a.phase_weeks_total,
        rest_day=a.rest_day, long_run_day=a.long_run_day,
        days_to_race=a.days_to_race,
        pace_zones={f"z{pct}": seconds_to_display(pace) for pct, pace in sorted(zones.items())},
    )


def _get_last_week_workouts(athlete_id: int) -> list[str]:
    """Hole die Workouts der letzten 7 Tage aus der DB."""
    cutoff = dt.date.today() - dt.timedelta(days=7)
    with SyncSession() as session:
        result = session.execute(
            select(CompletedWorkout.workout_key)
            .where(CompletedWorkout.athlete_id == athlete_id)
            .where(CompletedWorkout.date >= cutoff)
        )
        return [row[0] for row in result.all()]


def _days_since_last_hard_workout(athlete_id: int) -> int:
    """Tage seit letztem harten Workout. 99 wenn keine Historie."""
    with SyncSession() as session:
        result = session.execute(
            select(CompletedWorkout.date)
            .where(CompletedWorkout.athlete_id == athlete_id)
            .where(CompletedWorkout.zone.notin_(["z80", None]))
            .order_by(CompletedWorkout.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return 99  # Keine Historie → ausgeruht
        return (dt.date.today() - row).days


def _days_since_last_pace_update(athlete_id: int) -> int:
    """Wochen seit letztem Pace-Update."""
    with SyncSession() as session:
        result = session.execute(
            select(PaceHistory.date)
            .where(PaceHistory.athlete_id == athlete_id)
            .order_by(PaceHistory.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return 99  # Nie aktualisiert
        delta = dt.date.today() - row
        return delta.days // 7


# =========================================================================
#  CONTROLLER
# =========================================================================

class AthleteController(Controller):
    path = "/api/athletes"
    tags = ["Athletes"]

    @post("/")
    async def create_athlete(
        self,
        data: Annotated[AthleteCreate, Body(examples=[Example(
            summary="10k-Läuferin, 45:00",
            value={
                "name": "Lisa Müller",
                "target_distance": "10k",
                "race_time_seconds": 2700.0,
                "weekly_km": 55.0,
                "experience_years": 3,
                "current_phase": "general",
                "week_in_phase": 1,
                "phase_weeks_total": 8,
                "rest_day": 1,
                "long_run_day": 0,
                "days_to_race": 56,
            },
        )])],
    ) -> AthleteResponse:
        """Neuen Athleten anlegen."""
        if data.target_distance not in DISTANCES:
            raise ValueError(f"Unbekannte Distanz: {data.target_distance}")

        with SyncSession() as session:
            athlete = AthleteDB(
                name=data.name,
                target_distance=data.target_distance,
                race_time_seconds=data.race_time_seconds,
                weekly_km=data.weekly_km,
                experience_years=data.experience_years,
                current_phase=data.current_phase,
                week_in_phase=data.week_in_phase,
                phase_weeks_total=data.phase_weeks_total,
                rest_day=data.rest_day,
                long_run_day=data.long_run_day,
                days_to_race=data.days_to_race,
            )
            session.add(athlete)
            session.commit()
            session.refresh(athlete)
            return _athlete_to_response(athlete)

    @get("/{athlete_id:int}")
    async def get_athlete(self, athlete_id: int) -> AthleteResponse:
        """Athletenprofil abrufen."""
        athlete = _get_athlete(athlete_id)
        return _athlete_to_response(athlete)

    @patch("/{athlete_id:int}")
    async def update_athlete(
        self,
        athlete_id: int,
        data: Annotated[AthleteUpdate, Body(examples=[Example(
            summary="Phase-Wechsel + Umfang hoch",
            value={
                "weekly_km": 65.0,
                "current_phase": "supportive",
                "week_in_phase": 3,
                "days_to_race": 42,
            },
        )])],
    ) -> AthleteResponse:
        """Athletenprofil aktualisieren."""
        with SyncSession() as session:
            result = session.execute(
                select(AthleteDB).where(AthleteDB.id == athlete_id)
            )
            athlete = result.scalar_one_or_none()
            if not athlete:
                raise NotFoundException(detail=f"Athlet {athlete_id} nicht gefunden")

            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(athlete, field, value)

            session.commit()
            session.refresh(athlete)
            return _athlete_to_response(athlete)

    @post("/{athlete_id:int}/race")
    async def add_race_result(
        self,
        athlete_id: int,
        data: Annotated[RaceResultCreate, Body(examples=[Example(
            summary="10k-Rennergebnis",
            value={
                "date": "2026-03-15",
                "distance": "10k",
                "time_seconds": 2650.0,
                "notes": "Flache Strecke, leichter Gegenwind ab km 7",
            },
        )])],
    ) -> RaceResultResponse:
        """Rennergebnis eintragen + automatisches Pace-Update."""
        athlete = _get_athlete(athlete_id)

        with SyncSession() as session:
            # Rennergebnis speichern
            race = RaceResult(
                athlete_id=athlete_id,
                date=data.date,
                distance=data.distance,
                time_seconds=data.time_seconds,
                notes=data.notes,
            )
            session.add(race)

            # Automatisches Pace-Update via PyReason
            weeks_since = _days_since_last_pace_update(athlete_id)
            update_input = PaceUpdateInput(
                target_distance=athlete.target_distance,
                current_race_time_seconds=athlete.race_time_seconds,
                new_race_time_seconds=data.time_seconds,
                new_race_distance=data.distance,
                weeks_since_last_update=weeks_since,
                experience_years=athlete.experience_years,
                weekly_km=athlete.weekly_km,
            )
            inference = run_pace_update_inference(update_input)

            # Neue Race Pace berechnen (vereinfacht: direkt übernehmen wenn gleiche Distanz)
            if data.distance == athlete.target_distance and inference.recommend_fitness_update:
                old_time = athlete.race_time_seconds
                new_time = data.time_seconds
                improvement = round((old_time - new_time) / old_time * 100, 2)

                # Pace-History speichern
                ph = PaceHistory(
                    athlete_id=athlete_id,
                    date=data.date,
                    old_race_time_seconds=old_time,
                    new_race_time_seconds=new_time,
                    strategy="fitness_update",
                    improvement_pct=improvement,
                )
                session.add(ph)

                # Athleten-Pace aktualisieren
                result = session.execute(
                    select(AthleteDB).where(AthleteDB.id == athlete_id)
                )
                db_athlete = result.scalar_one()
                db_athlete.race_time_seconds = new_time

            session.commit()

            pace = seconds_to_display(data.time_seconds / DISTANCES.get(data.distance, 1))
            return RaceResultResponse(
                id=race.id, date=data.date, distance=data.distance,
                time_seconds=data.time_seconds, pace=pace, notes=data.notes,
            )

    @post("/{athlete_id:int}/complete-workout")
    async def complete_workout(
        self,
        athlete_id: int,
        data: Annotated[CompleteWorkoutCreate, Body(examples=[Example(
            summary="Tempo-Dauerlauf",
            value={
                "date": "2026-03-17",
                "workout_key": "tempo_continuous",
                "zone": "z85",
                "distance_km": 12.0,
                "duration_minutes": 55.0,
                "notes": "Inkl. 2km Ein-/Auslaufen",
            },
        )])],
    ) -> WorkoutHistoryResponse:
        """Workout als erledigt markieren."""
        _get_athlete(athlete_id)  # Existenz prüfen

        with SyncSession() as session:
            workout = CompletedWorkout(
                athlete_id=athlete_id,
                date=data.date,
                workout_key=data.workout_key,
                zone=data.zone,
                distance_km=data.distance_km,
                duration_minutes=data.duration_minutes,
                notes=data.notes,
            )
            session.add(workout)
            session.commit()
            session.refresh(workout)

            tmpl = WORKOUT_TEMPLATES.get(data.workout_key, {})
            return WorkoutHistoryResponse(
                id=workout.id, date=data.date, workout_key=data.workout_key,
                workout_name=tmpl.get("name", data.workout_key),
                zone=data.zone, distance_km=data.distance_km, notes=data.notes,
            )

    @get("/{athlete_id:int}/history")
    async def get_history(self, athlete_id: int) -> dict:
        """Trainingshistorie: Workouts, Rennen, Pace-Verlauf."""
        _get_athlete(athlete_id)

        with SyncSession() as session:
            # Letzte 30 Workouts
            workouts_q = session.execute(
                select(CompletedWorkout)
                .where(CompletedWorkout.athlete_id == athlete_id)
                .order_by(CompletedWorkout.date.desc())
                .limit(30)
            )
            workouts = workouts_q.scalars().all()

            # Alle Rennergebnisse
            races_q = session.execute(
                select(RaceResult)
                .where(RaceResult.athlete_id == athlete_id)
                .order_by(RaceResult.date.desc())
            )
            races = races_q.scalars().all()

            # Pace-History
            paces_q = session.execute(
                select(PaceHistory)
                .where(PaceHistory.athlete_id == athlete_id)
                .order_by(PaceHistory.date.desc())
            )
            paces = paces_q.scalars().all()

        return {
            "workouts": [
                {
                    "date": str(w.date), "workout_key": w.workout_key,
                    "workout_name": WORKOUT_TEMPLATES.get(w.workout_key, {}).get("name", w.workout_key),
                    "zone": w.zone, "distance_km": w.distance_km,
                }
                for w in workouts
            ],
            "races": [
                {
                    "date": str(r.date), "distance": r.distance,
                    "time_seconds": r.time_seconds,
                    "pace": seconds_to_display(r.time_seconds / DISTANCES.get(r.distance, 1)),
                }
                for r in races
            ],
            "pace_history": [
                {
                    "date": str(p.date), "strategy": p.strategy,
                    "old_pace": seconds_to_display(p.old_race_time_seconds / DISTANCES.get("10k", 10)),
                    "new_pace": seconds_to_display(p.new_race_time_seconds / DISTANCES.get("10k", 10)),
                    "improvement_pct": p.improvement_pct,
                }
                for p in paces
            ],
        }

    @post("/{athlete_id:int}/week")
    async def generate_week(self, athlete_id: int) -> WeeklyPlan:
        """Wochenplan aus DB-Profil generieren.

        Liest Profil, letzte Workouts und Pace-History automatisch aus der DB.
        """
        total_start = time.perf_counter()

        load_athlete_start = time.perf_counter()
        athlete = _get_athlete(athlete_id)
        load_athlete_ms = (time.perf_counter() - load_athlete_start) * 1000

        load_history_start = time.perf_counter()
        last_week = _get_last_week_workouts(athlete_id)
        days_since_hard = _days_since_last_hard_workout(athlete_id)
        load_history_ms = (time.perf_counter() - load_history_start) * 1000

        inp = WeekPlanInput(
            target_distance=athlete.target_distance,
            race_time_seconds=athlete.race_time_seconds,
            weekly_km=athlete.weekly_km,
            experience_years=athlete.experience_years,
            current_phase=athlete.current_phase,
            week_in_phase=athlete.week_in_phase,
            phase_weeks_total=athlete.phase_weeks_total,
            last_week_workouts=last_week,
            rest_day=athlete.rest_day,
            long_run_day=athlete.long_run_day,
            days_since_hard_workout=days_since_hard,
            days_to_race=athlete.days_to_race,
        )

        inference_start = time.perf_counter()
        inference_payload, inference_request_id = get_inference_worker().infer_week(inp)
        inference_ms = (time.perf_counter() - inference_start) * 1000

        plan_start = time.perf_counter()
        inference = InferenceResult(**inference_payload)
        plan = generate_week_plan(inp, inference)
        plan_ms = (time.perf_counter() - plan_start) * 1000

        total_ms = (time.perf_counter() - total_start) * 1000
        _LOGGER.info(json.dumps({
            "event": "athlete_week_timing",
            "athlete_id": athlete_id,
            "inference_request_id": inference_request_id,
            "load_athlete_ms": round(load_athlete_ms, 2),
            "load_history_ms": round(load_history_ms, 2),
            "inference_ms": round(inference_ms, 2),
            "plan_ms": round(plan_ms, 2),
            "total_ms": round(total_ms, 2),
        }, ensure_ascii=False))

        return plan
