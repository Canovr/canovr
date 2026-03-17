"""Shared fixtures für CanovR Tests."""

from __future__ import annotations

import warnings

import pytest

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")


@pytest.fixture
def athlete_10k_experienced():
    """Erfahrener 10k-Läufer, 40:00, supportive Phase."""
    from app.models import AthleteInput
    return AthleteInput(
        target_distance="10k",
        race_time_seconds=2400,
        weekly_km=80,
        experience_years=5,
        current_phase="supportive",
        days_since_hard_workout=3,
    )


@pytest.fixture
def athlete_marathon_novice():
    """Marathon-Anfänger, 3:30, general Phase, erschöpft."""
    from app.models import AthleteInput
    return AthleteInput(
        target_distance="marathon",
        race_time_seconds=12600,
        weekly_km=45,
        experience_years=1,
        current_phase="general",
        days_since_hard_workout=1,
    )


@pytest.fixture
def week_input_build():
    """Wochenplan-Input: 10k, Build-Phase (Woche 4/8)."""
    from app.models import WeekPlanInput
    return WeekPlanInput(
        target_distance="10k",
        race_time_seconds=2400,
        weekly_km=80,
        experience_years=5,
        current_phase="supportive",
        week_in_phase=4,
        phase_weeks_total=8,
        last_week_workouts=["tempo_continuous", "speed_intervals"],
        days_since_hard_workout=3,
    )


@pytest.fixture
def week_input_taper():
    """Wochenplan-Input: 10k, Taper 7 Tage vor Rennen."""
    from app.models import WeekPlanInput
    return WeekPlanInput(
        target_distance="10k",
        race_time_seconds=2400,
        weekly_km=80,
        experience_years=5,
        current_phase="specific",
        week_in_phase=6,
        phase_weeks_total=6,
        days_since_hard_workout=3,
        days_to_race=7,
    )
