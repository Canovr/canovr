"""Datenmodelle für CanovR API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


DISTANCES: dict[str, float] = {
    "800m": 0.8,
    "1500m": 1.5,
    "mile": 1.60934,
    "3k": 3.0,
    "5k": 5.0,
    "10k": 10.0,
    "half_marathon": 21.0975,
    "marathon": 42.195,
}


class AthleteInput(BaseModel):
    """Eingabe: Athletenprofil für eine Trainingsempfehlung."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "target_distance": "10k",
            "race_time_seconds": 2400.0,
            "weekly_km": 75.0,
            "experience_years": 5,
            "current_phase": "supportive",
            "days_since_hard_workout": 2,
        },
    })

    target_distance: str = Field(
        description="Zieldistanz: 800m, 1500m, mile, 3k, 5k, 10k, half_marathon, marathon",
        examples=["10k"],
    )
    race_time_seconds: float = Field(
        description="Aktuelle Bestzeit für Zieldistanz in Sekunden",
        examples=[2400.0],
        gt=0,
    )
    weekly_km: float = Field(
        description="Aktuelle Wochenkilometer",
        examples=[80.0],
        gt=0,
    )
    experience_years: int = Field(
        description="Lauferfahrung in Jahren",
        examples=[5],
        ge=0,
    )
    current_phase: str = Field(
        description="Aktuelle Trainingsphase: general, supportive, specific",
        examples=["supportive"],
    )
    days_since_hard_workout: int = Field(
        description="Tage seit letztem harten Workout",
        examples=[2],
        ge=0,
    )


DAY_NAMES = [
    "Sonntag", "Montag", "Dienstag", "Mittwoch",
    "Donnerstag", "Freitag", "Samstag",
]


class WeekPlanInput(BaseModel):
    """Eingabe für den Wochenplan-Generator."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "target_distance": "10k",
            "race_time_seconds": 2400.0,
            "weekly_km": 75.0,
            "experience_years": 5,
            "current_phase": "supportive",
            "week_in_phase": 3,
            "phase_weeks_total": 8,
            "last_week_workouts": ["tempo_continuous", "speed_intervals"],
            "rest_day": 1,
            "long_run_day": 0,
            "days_since_hard_workout": 2,
            "days_to_race": None,
        },
    })

    # Athletenprofil
    target_distance: str = Field(examples=["10k"])
    race_time_seconds: float = Field(examples=[2400.0], gt=0)
    weekly_km: float = Field(examples=[80.0], gt=0)
    experience_years: int = Field(examples=[5], ge=0)
    current_phase: str = Field(examples=["supportive"])

    # Phasen-Progression
    week_in_phase: int = Field(
        description="Aktuelle Woche innerhalb der Phase (1-basiert)",
        examples=[3], ge=1,
    )
    phase_weeks_total: int = Field(
        description="Geplante Gesamtdauer der aktuellen Phase in Wochen",
        examples=[8], ge=1,
    )

    # Letzte Woche (für Rotation)
    last_week_workouts: list[str] = Field(
        default_factory=list,
        description="Workout-Keys der letzten Woche, z.B. ['tempo_continuous', 'speed_intervals']",
    )

    # Präferenzen (0=So, 1=Mo, ..., 6=Sa)
    rest_day: int | None = Field(
        default=None,
        description="Gewünschter Ruhetag (0=So..6=Sa). None = Empfehlung",
        ge=0, le=6,
    )
    long_run_day: int | None = Field(
        default=None,
        description="Gewünschter Long-Run-Tag (0=So..6=Sa). None = Empfehlung",
        ge=0, le=6,
    )

    # Erholung
    days_since_hard_workout: int = Field(default=2, ge=0)

    # Taper
    days_to_race: int | None = Field(
        default=None,
        description="Tage bis zum Wettkampf. None = kein Taper. 0 = Renntag.",
        ge=0,
    )


class DayPlan(BaseModel):
    """Ein einzelner Tag im Wochenplan."""

    day_index: int
    day_name: str
    session_type: str  # "hard", "long_run", "easy", "rest", "easy+strides"
    workout_key: str | None = None
    workout_name: str | None = None
    description: str | None = None
    zone: str | None = None
    percentage: int | None = None
    pace: str | None = None
    volume: str | None = None
    estimated_km: float = 0.0
    scoring_reason: str | None = None


class WeeklyPlan(BaseModel):
    """Vollständiger 7-Tage-Wochenplan."""

    phase: str
    week_in_phase: int
    phase_weeks_total: int
    progression_pct: float
    total_km: float
    hard_sessions: int
    days: list[DayPlan]
    reasoning_trace: list[str]
    recommendations: list[str]


class PaceUpdateInput(BaseModel):
    """Eingabe für Pace-Aktualisierung."""

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "target_distance": "10k",
            "current_race_time_seconds": 2400.0,
            "new_race_time_seconds": 2340.0,
            "new_race_distance": None,
            "goal_race_time_seconds": 2250.0,
            "weeks_since_last_update": 4,
            "weeks_to_goal_race": 12,
            "experience_years": 5,
            "weekly_km": 75.0,
        },
    })

    target_distance: str = Field(examples=["10k"])
    current_race_time_seconds: float = Field(
        description="Aktuelle Basis-Wettkampfzeit in Sekunden",
        examples=[2400.0], gt=0,
    )
    new_race_time_seconds: float | None = Field(
        default=None,
        description="Neues Wettkampfergebnis in Sekunden (optional, für Fitness-Update)",
        gt=0,
    )
    new_race_distance: str | None = Field(
        default=None,
        description="Distanz des neuen Ergebnisses (falls abweichend von target_distance)",
    )
    goal_race_time_seconds: float | None = Field(
        default=None,
        description="Ziel-Wettkampfzeit in Sekunden (optional, für Bridging)",
        gt=0,
    )
    weeks_since_last_update: int = Field(default=0, ge=0)
    weeks_to_goal_race: int | None = Field(
        default=None,
        description="Wochen bis zum Zielwettkampf (für Bridging)",
        ge=1,
    )
    experience_years: int = Field(default=3, ge=0)
    weekly_km: float = Field(default=70.0, gt=0)


class PaceZoneDelta(BaseModel):
    """Pace-Zone mit Vergleich alt vs. neu."""

    label: str
    percentage: int
    old_pace: str
    new_pace: str
    delta_seconds: float
    role: str


class PaceUpdateResult(BaseModel):
    """Ergebnis einer Pace-Aktualisierung."""

    recommended_strategy: str
    strategy_reason: str
    old_race_pace: str
    new_race_pace: str
    improvement_pct: float
    zones: list[PaceZoneDelta]
    warnings: list[str]
    recommendations: list[str]
    reasoning_trace: list[str]
    rules_applied: list[str]


class PaceZone(BaseModel):
    """Eine Pace-Zone im Full-Spectrum-System."""

    label: str
    percentage: int
    pace_per_km: str
    pace_per_km_seconds: float
    role: str
    active: bool
    primary: bool


class WorkoutSuggestion(BaseModel):
    """Ein konkreter Workout-Vorschlag."""

    name: str
    zone: str
    percentage: int
    pace: str
    description: str
    volume_hint: str


class TrainingRecommendation(BaseModel):
    """Vollständige Trainingsempfehlung."""

    athlete_phase: str
    recovery_needed: bool
    recovery_reason: str | None = None
    pace_zones: list[PaceZone]
    recommended_workouts: list[WorkoutSuggestion]
    reasoning_trace: list[str]
    next_phase_hint: str | None = None
    rules_applied: list[str]
