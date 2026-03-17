"""Tests für den Wochenplan-Generator."""

import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

from app.models import WeekPlanInput
from app.planner import generate_week_plan
from app.reasoner import run_week_inference


def _make_plan(inp: WeekPlanInput):
    inference = run_week_inference(inp)
    return generate_week_plan(inp, inference)


class TestWeekStructure:
    def test_plan_has_7_days(self, week_input_build):
        plan = _make_plan(week_input_build)
        assert len(plan.days) == 7

    def test_has_rest_day(self, week_input_build):
        plan = _make_plan(week_input_build)
        rest_days = [d for d in plan.days if d.session_type == "rest"]
        assert len(rest_days) >= 1

    def test_has_long_run(self, week_input_build):
        plan = _make_plan(week_input_build)
        long_runs = [d for d in plan.days if d.session_type == "long_run"]
        assert len(long_runs) == 1

    def test_total_km_within_range(self, week_input_build):
        plan = _make_plan(week_input_build)
        assert plan.total_km > 50  # Nicht zu wenig
        assert plan.total_km < 120  # Nicht absurd viel

    def test_strides_on_easy_days(self, week_input_build):
        plan = _make_plan(week_input_build)
        strides_days = [d for d in plan.days if d.session_type == "easy+strides"]
        assert len(strides_days) >= 1
        assert len(strides_days) <= 2


class TestNoConsecutiveHardDays:
    def test_no_consecutive_hard_days(self, week_input_build):
        plan = _make_plan(week_input_build)
        hard_indices = [
            d.day_index for d in plan.days
            if d.session_type in ("hard", "long_run")
        ]
        for i in range(len(hard_indices)):
            for j in range(i + 1, len(hard_indices)):
                dist = min(
                    abs(hard_indices[i] - hard_indices[j]),
                    7 - abs(hard_indices[i] - hard_indices[j]),
                )
                assert dist >= 2, (
                    f"Harte Tage {hard_indices[i]} und {hard_indices[j]} "
                    f"zu nah beieinander (Abstand={dist})"
                )


class TestTaperVolume:
    def test_taper_reduces_total_km(self, week_input_taper):
        plan = _make_plan(week_input_taper)
        # Taper bei 7 Tagen = 60% → ~48 km statt 80 km
        assert plan.total_km < 60, f"Taper sollte Volumen reduzieren, got {plan.total_km}"

    def test_taper_has_fewer_hard_sessions(self, week_input_taper):
        plan = _make_plan(week_input_taper)
        assert plan.hard_sessions <= 1


class TestCustomRestDay:
    def test_rest_day_on_wednesday(self):
        inp = WeekPlanInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive",
            week_in_phase=4, phase_weeks_total=8,
            rest_day=3,  # Mittwoch
            days_since_hard_workout=3,
        )
        plan = _make_plan(inp)
        wednesday = plan.days[3]
        assert wednesday.session_type == "rest"
        assert wednesday.day_name == "Mittwoch"

    def test_long_run_on_sunday(self):
        inp = WeekPlanInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive",
            week_in_phase=4, phase_weeks_total=8,
            long_run_day=0,  # Sonntag
            rest_day=1,  # Montag
            days_since_hard_workout=3,
        )
        plan = _make_plan(inp)
        sunday = plan.days[0]
        assert sunday.session_type == "long_run"


class TestProgressionStages:
    def test_intro_uses_base_volume(self):
        inp = WeekPlanInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive",
            week_in_phase=1, phase_weeks_total=10,
            days_since_hard_workout=3,
        )
        plan = _make_plan(inp)
        # Mindestens ein Workout sollte "BASE" im scoring_reason haben
        has_base = any(
            d.scoring_reason and "BASE" in d.scoring_reason
            for d in plan.days if d.scoring_reason
        )
        assert has_base, "Intro-Phase sollte Base-Stufen verwenden"

    def test_peak_uses_extension_volume(self):
        inp = WeekPlanInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive",
            week_in_phase=8, phase_weeks_total=10,
            days_since_hard_workout=3,
        )
        plan = _make_plan(inp)
        has_ext = any(
            d.scoring_reason and "EXTENSION" in d.scoring_reason
            for d in plan.days if d.scoring_reason
        )
        assert has_ext, "Peak-Phase sollte Extension-Stufen verwenden"
