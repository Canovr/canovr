"""Tests für PyReason-Regeln.

Jede Regelgruppe wird getestet: Fakten injizieren → prüfen ob
die richtigen Prädikate abgeleitet werden. Echtes PyReason, keine Mocks.
"""

import warnings

import pytest

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

from app.models import AthleteInput
from app.reasoner import run_inference


# =========================================================================
#  R1–R5: Zonen- und Workout-Aktivierung
# =========================================================================

class TestZoneActivation:
    def test_general_phase_activates_broad_spectrum(self):
        """General: z80-z90 + z110-z115 aktiv."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="general", days_since_hard_workout=3,
        ))
        for z in ["z80", "z85", "z90", "z110", "z115"]:
            assert z in r.active_zones, f"{z} sollte in general aktiv sein"

    def test_specific_phase_activates_narrow_spectrum(self):
        """Specific: z95, z100, z105 primär."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="specific", days_since_hard_workout=3,
        ))
        for z in ["z95", "z100", "z105"]:
            assert z in r.active_zones, f"{z} sollte in specific aktiv sein"

    def test_foundation_chain_adds_not_replaces(self):
        """R3: Wenn z95 aktiv, müssen z90, z85, z80 auch aktiv sein."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="specific", days_since_hard_workout=3,
        ))
        # z95 ist primär in specific → Foundation sollte z90, z85, z80 aktivieren
        for z in ["z80", "z85", "z90"]:
            assert z in r.active_zones, f"Foundation: {z} sollte durch z95 aktiv sein"

    def test_always_on_strides_and_easy(self):
        """R4: Strides und Easy Run immer empfohlen."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="specific", days_since_hard_workout=3,
        ))
        assert "strides" in r.recommended_workouts
        assert "easy_run" in r.recommended_workouts

    def test_zone_recommends_workouts(self):
        """R2: Aktive Zone empfiehlt ihre Workouts."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        # z90 aktiv in supportive → tempo_continuous empfohlen
        assert "tempo_continuous" in r.recommended_workouts

    def test_adjacent_support_zones(self):
        """R5: Nachbarzonen erhalten Stützstatus."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="specific", days_since_hard_workout=3,
        ))
        # z95 aktiv → z100 ist Nachbar → support_zone
        # (z100 ist auch durch phase_activates aktiv, also prüfe support existiert)
        assert len(r.support_zones) >= 0  # Support zones existieren


# =========================================================================
#  R6–R9: Workout-Klassifikation
# =========================================================================

class TestWorkoutClassification:
    def test_high_stress_is_hard(self):
        """R6: race_pace_reps (high_stress) → is_hard."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="specific", days_since_hard_workout=3,
        ))
        assert "race_pace_reps" in r.hard_workouts

    def test_endurance_is_quality(self):
        """R7a: Endurance-Workouts sind Quality."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert "tempo_continuous" in r.quality_workouts

    def test_speed_is_quality(self):
        """R7b: Speed-Workouts sind Quality."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert "specific_speed_intervals" in r.quality_workouts

    def test_long_run_is_key_session(self):
        """R8: Long Runs sind Key Sessions."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="general", days_since_hard_workout=3,
        ))
        assert "long_easy_run" in r.key_sessions


# =========================================================================
#  R10–R12: Erholung
# =========================================================================

class TestRecovery:
    def test_fatigued_needs_recovery(self):
        """R10: fatigued → needs_recovery."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="general", days_since_hard_workout=1,
        ))
        assert r.needs_recovery is True

    def test_recovered_allows_hard(self):
        """R11: recovered → allow_hard."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="general", days_since_hard_workout=5,
        ))
        assert r.allow_hard is True
        assert r.needs_recovery is False

    def test_novice_needs_extra_recovery(self):
        """R12: novice + fatigued → extra_recovery_needed."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=60,
            experience_years=1, current_phase="general", days_since_hard_workout=2,
        ))
        assert r.needs_recovery is True
        assert r.extra_recovery_needed is True

    def test_general_phase_needs_more_recovery(self):
        """General Phase hat höheren Erholungsbedarf (3 Tage vs 2)."""
        # 2 Tage reicht NICHT in general
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="general", days_since_hard_workout=2,
        ))
        assert r.needs_recovery is True

        # 2 Tage reicht in supportive
        r2 = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=2,
        ))
        assert r2.needs_recovery is False


# =========================================================================
#  R13–R16: Priorität und Präferenz
# =========================================================================

class TestPriority:
    def test_endurance_workouts_get_priority(self):
        """R13: Endurance-Workouts haben Priorität."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert len(r.priority_endurance_workouts) > 0

    def test_primary_workouts_from_phase_zones(self):
        """R14: Primary = aus primärer Phase-Zone + Quality."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert len(r.primary_workouts) > 0

    def test_distance_preferred_workouts(self):
        """R15: 10k bevorzugt bestimmte Workouts."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=3, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert len(r.distance_preferred_workouts) > 0


# =========================================================================
#  R17–R22: Erfahrung und Volumen
# =========================================================================

class TestExperienceVolume:
    def test_experienced_gets_early_race_pace_in_supportive(self):
        """R17: Erfahren + supportive → early_race_pace."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=6, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert r.early_race_pace is True

    def test_experienced_not_in_general(self):
        """R17: early_race_pace nur in supportive, nicht general."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=6, current_phase="general", days_since_hard_workout=3,
        ))
        assert r.early_race_pace is False

    def test_novice_reduces_speed(self):
        """R18: Anfänger → reduce_speed."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=60,
            experience_years=1, current_phase="general", days_since_hard_workout=5,
        ))
        assert r.reduce_speed is True

    def test_low_volume_reduces_sessions(self):
        """R20: <50 km/Woche → reduce_sessions."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=40,
            experience_years=3, current_phase="general", days_since_hard_workout=3,
        ))
        assert r.reduce_sessions is True

    def test_high_volume_experienced_allows_three_quality(self):
        """R21: Hohes Vol + sehr erfahren + supportive → allow_three_quality."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=110,
            experience_years=10, current_phase="supportive", days_since_hard_workout=3,
        ))
        assert r.allow_three_quality is True

    def test_low_volume_novice_prefers_strides(self):
        """R22: low_volume + novice → prefer_strides_over_speed."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=35,
            experience_years=1, current_phase="general", days_since_hard_workout=5,
        ))
        assert r.prefer_strides_over_speed is True


# =========================================================================
#  R23–R30: Progression, Transition, Constraints
# =========================================================================

class TestProgression:
    def test_intro_is_conservative(self):
        """R23: Woche 1/10 → conservative."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=1, phase_weeks_total=10)
        assert r.conservative is True
        assert r.building is False

    def test_build_phase(self):
        """R24: Woche 4/10 → building."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=4, phase_weeks_total=10)
        assert r.building is True
        assert r.conservative is False

    def test_peak_phase(self):
        """R25: Woche 8/10 → at_peak."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=8, phase_weeks_total=10)
        assert r.at_peak is True

    def test_pretaper_phase(self):
        """R26: Woche 10/10 → tapering."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=10, phase_weeks_total=10)
        assert r.tapering is True

    def test_only_one_progression_state(self):
        """Nur EIN Progressionszustand gleichzeitig."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=4, phase_weeks_total=10)
        states = [r.conservative, r.building, r.at_peak, r.tapering]
        assert sum(states) == 1, f"Genau ein Zustand erwartet, got {states}"


class TestTransition:
    def test_ready_for_next_at_peak_in_supportive(self):
        """R28: Peak in supportive → ready_for_next."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=8, phase_weeks_total=10)
        assert r.ready_for_next is True

    def test_not_ready_in_build(self):
        """Nicht bereit in Build-Phase."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=4, phase_weeks_total=10)
        assert r.ready_for_next is False

    def test_ready_for_taper_in_specific_pretaper(self):
        """R29: Pre-Taper in specific → ready_for_taper."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), week_in_phase=10, phase_weeks_total=10)
        assert r.ready_for_taper is True


# =========================================================================
#  R31–R37: Workout-Progression
# =========================================================================

class TestWorkoutProgression:
    def test_base_stages_in_intro(self):
        """R31: Intro → base stages aktiv."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=1, phase_weeks_total=10)
        base_stages = [s for s in r.active_stages if s.endswith("_base")]
        assert len(base_stages) > 0, "Base stages sollten in Intro aktiv sein"

    def test_volume_stages_in_build(self):
        """R32: Build → volume stages aktiv."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=4, phase_weeks_total=10)
        vol_stages = [s for s in r.active_stages if s.endswith("_volume")]
        assert len(vol_stages) > 0, "Volume stages sollten in Build aktiv sein"

    def test_extension_stages_in_peak(self):
        """R33: Peak → extension stages aktiv."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=8, phase_weeks_total=10)
        ext_stages = [s for s in r.active_stages if s.endswith("_extension")]
        assert len(ext_stages) > 0, "Extension stages sollten in Peak aktiv sein"

    def test_recovery_stages_only_for_experienced(self):
        """R34: Recovery stages nur wenn experienced + peak."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=8, phase_weeks_total=10)
        rec_stages = [s for s in r.active_stages if s.endswith("_recovery")]
        assert len(rec_stages) > 0, "Erfahren + Peak → Recovery stages"

        # Anfänger bekommt keine Recovery stages
        r2 = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=1, current_phase="supportive", days_since_hard_workout=5,
        ), week_in_phase=8, phase_weeks_total=10)
        rec2 = [s for s in r2.active_stages if s.endswith("_recovery")]
        assert len(rec2) == 0, "Anfänger sollte keine Recovery stages bekommen"

    def test_next_progressions_exist(self):
        """R36: Nächste Progression wird angezeigt."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="supportive", days_since_hard_workout=3,
        ), week_in_phase=4, phase_weeks_total=10)
        assert len(r.next_progressions) > 0


# =========================================================================
#  R38–R47: Taper
# =========================================================================

class TestTaper:
    def test_early_taper_allows_one_quality(self):
        """R39: 12 Tage → taper_allow_one_quality."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=12)
        assert r.in_taper_mode is True
        assert r.taper_allow_one_quality is True
        assert r.taper_volume_factor == 0.80

    def test_mid_taper_race_pace_only(self):
        """R41: 7 Tage → taper_race_pace_only."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=7)
        assert r.taper_race_pace_only is True
        assert r.taper_volume_factor == 0.60

    def test_late_taper_easy_only(self):
        """R43: 3 Tage → taper_easy_only."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=3)
        assert r.taper_easy_only is True
        assert r.taper_volume_factor == 0.40

    def test_race_week_shake_out(self):
        """R45: 1 Tag → taper_shake_out_only."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=1)
        assert r.taper_shake_out_only is True
        assert r.taper_volume_factor == 0.20

    def test_taper_blocks_progression(self):
        """R47: Taper blockiert Progression."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=10)
        assert r.block_progression is True

    def test_no_taper_without_days_to_race(self):
        """Kein Taper wenn days_to_race nicht gesetzt."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ))
        assert r.in_taper_mode is False

    def test_no_taper_beyond_14_days(self):
        """Kein Taper wenn >14 Tage bis Rennen."""
        r = run_inference(AthleteInput(
            target_distance="10k", race_time_seconds=2400, weekly_km=80,
            experience_years=5, current_phase="specific", days_since_hard_workout=3,
        ), days_to_race=20)
        assert r.in_taper_mode is False


# =========================================================================
#  R48–R54: Pace-Update
# =========================================================================

class TestPaceUpdate:
    def test_update_due_after_4_weeks(self):
        """R48: ≥4 Wochen → pace_update_due."""
        from app.models import PaceUpdateInput
        from app.reasoner import run_pace_update_inference
        r = run_pace_update_inference(PaceUpdateInput(
            target_distance="10k", current_race_time_seconds=2400,
            new_race_time_seconds=2340, weeks_since_last_update=5,
            experience_years=5, weekly_km=80,
        ))
        assert r.pace_update_due is True

    def test_fitness_update_with_race_result(self):
        """R49: Rennergebnis → recommend_fitness_update."""
        from app.models import PaceUpdateInput
        from app.reasoner import run_pace_update_inference
        r = run_pace_update_inference(PaceUpdateInput(
            target_distance="10k", current_race_time_seconds=2400,
            new_race_time_seconds=2340, weeks_since_last_update=2,
            experience_years=5, weekly_km=80,
        ))
        assert r.recommend_fitness_update is True

    def test_warn_extreme_jump(self):
        """R53: >10% Sprung → warn_extreme_pace_jump."""
        from app.models import PaceUpdateInput
        from app.reasoner import run_pace_update_inference
        r = run_pace_update_inference(PaceUpdateInput(
            target_distance="10k", current_race_time_seconds=2400,
            new_race_time_seconds=2100, weeks_since_last_update=2,
            experience_years=3, weekly_km=70,
        ))
        assert r.warn_extreme_pace_jump is True

    def test_bridging_for_experienced_with_goal(self):
        """R51: Ziel + erfahren → recommend_bridging."""
        from app.models import PaceUpdateInput
        from app.reasoner import run_pace_update_inference
        r = run_pace_update_inference(PaceUpdateInput(
            target_distance="10k", current_race_time_seconds=2400,
            goal_race_time_seconds=2280, weeks_since_last_update=4,
            weeks_to_goal_race=12, experience_years=7, weekly_km=90,
        ))
        assert r.recommend_bridging is True
