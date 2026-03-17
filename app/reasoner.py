"""PyReason-basierter Inferenz-Engine.

Übersetzt Athleten-Rohdaten in kategorische Fakten, füttert PyReason,
und extrahiert alle abgeleiteten Prädikate. PyReason ist das Backbone —
hier passiert die gesamte Trainingslogik.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pyreason as pr

from app.knowledge import DISTANCE_NODE_MAP, PYREASON_RULES, build_knowledge_graph
from app.models import AthleteInput, PaceUpdateInput, WeekPlanInput


_reasoning_lock = threading.Lock()

ZONE_NODES = ["z80", "z85", "z90", "z95", "z100", "z105", "z110", "z115"]

WORKOUT_NODES = [
    "easy_run", "long_easy_run", "long_fast_run",
    "tempo_continuous", "threshold_intervals",
    "race_pace_reps", "race_pace_continuous",
    "float_recovery_workout",
    "specific_speed_intervals", "fartlek",
    "speed_intervals", "short_reps",
    "strides", "hill_sprints",
    "progression_run",
]


@dataclass
class InferenceResult:
    """Vollständiges Ergebnis der PyReason-Inferenz."""

    # Zonen
    active_zones: list[str] = field(default_factory=list)
    support_zones: list[str] = field(default_factory=list)

    # Workouts
    recommended_workouts: list[str] = field(default_factory=list)
    primary_workouts: list[str] = field(default_factory=list)
    distance_preferred_workouts: list[str] = field(default_factory=list)
    priority_endurance_workouts: list[str] = field(default_factory=list)
    preferred_long_runs: list[str] = field(default_factory=list)

    # Workout-Klassifikation
    hard_workouts: list[str] = field(default_factory=list)
    quality_workouts: list[str] = field(default_factory=list)
    key_sessions: list[str] = field(default_factory=list)

    # Athleten-Zustand
    needs_recovery: bool = False
    allow_hard: bool = True
    extra_recovery_needed: bool = False

    # Erfahrung / Volumen
    early_race_pace: bool = False
    reduce_speed: bool = False
    allow_complex: bool = False
    reduce_sessions: bool = False
    allow_three_quality: bool = False
    prefer_strides_over_speed: bool = False

    # Progression
    conservative: bool = False
    building: bool = False
    at_peak: bool = False
    tapering: bool = False

    # Taper (R38–R47)
    in_taper_mode: bool = False
    taper_allow_one_quality: bool = False
    taper_race_pace_only: bool = False
    taper_easy_only: bool = False
    taper_shake_out_only: bool = False
    block_progression: bool = False
    taper_volume_factor: float = 1.0  # 1.0 = kein Taper, 0.2 = 80% Reduktion

    # Phasen-Transition
    ready_for_next: bool = False
    ready_for_taper: bool = False

    # Workout-Progression (R31–R37)
    active_stages: list[str] = field(default_factory=list)
    next_progressions: list[str] = field(default_factory=list)
    workouts_with_progression: list[str] = field(default_factory=list)

    # Pace-Update (R48–R54)
    pace_update_due: bool = False
    recommend_fitness_update: bool = False
    recommend_evolution: bool = False
    recommend_bridging: bool = False
    warn_large_pace_jump: bool = False
    warn_extreme_pace_jump: bool = False
    recalibrate_zones: bool = False

    # Zonen-Mixing
    mixable_pairs: list[tuple[str, str]] = field(default_factory=list)

    # Meta
    rules_fired: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    facts_injected: list[str] = field(default_factory=list)


# =========================================================================
#  FAKT-INJEKTION: Rohdaten → kategorische Fakten
# =========================================================================

def _classify_experience(years: int) -> list[tuple[str, str]]:
    """Erfahrung in kategorische Fakten übersetzen."""
    facts = []
    if years < 2:
        facts.append(("novice(athlete)", "classify_novice"))
    if years >= 5:
        facts.append(("experienced(athlete)", "classify_experienced"))
    if years >= 8:
        facts.append(("very_experienced(athlete)", "classify_very_experienced"))
    if not facts:
        facts.append(("intermediate(athlete)", "classify_intermediate"))
    return facts


def _classify_volume(weekly_km: float) -> list[tuple[str, str]]:
    """Wochenkilometer in kategorische Fakten übersetzen."""
    if weekly_km < 50:
        return [("low_volume(athlete)", "classify_low_volume")]
    if weekly_km >= 100:
        return [("high_volume(athlete)", "classify_high_volume")]
    return [("medium_volume(athlete)", "classify_medium_volume")]


def _classify_recovery(days_since_hard: int, phase: str, experience_years: int) -> list[tuple[str, str]]:
    """Erholungszustand klassifizieren.

    Schwellenwerte:
      General: 3 Tage (Anfänger: 4)
      Supportive/Specific: 2 Tage (Anfänger: 3)
    """
    min_days = {"general": 3, "supportive": 2, "specific": 2}.get(phase, 2)
    if experience_years < 2:
        min_days += 1

    if days_since_hard >= min_days:
        return [("recovered(athlete)", f"classify_recovered_{days_since_hard}d_>={min_days}d")]
    return [("fatigued(athlete)", f"classify_fatigued_{days_since_hard}d_<{min_days}d")]


def _classify_taper(days_to_race: int | None) -> list[tuple[str, str]]:
    """Taper-Phase klassifizieren.

    10–14 Tage: taper_early (letzte spezifische Einheit, -20% Vol)
    5–9 Tage:   taper_mid (nur Race-Pace-Berührungen, -40% Vol)
    2–4 Tage:   taper_late (nur Easy + Strides, -60% Vol)
    0–1 Tage:   taper_race (Shake-out oder Ruhe, -80% Vol)
    """
    if days_to_race is None:
        return []

    if days_to_race <= 1:
        return [("in_taper(athlete, taper_race)", f"classify_taper_race_{days_to_race}d")]
    if days_to_race <= 4:
        return [("in_taper(athlete, taper_late)", f"classify_taper_late_{days_to_race}d")]
    if days_to_race <= 9:
        return [("in_taper(athlete, taper_mid)", f"classify_taper_mid_{days_to_race}d")]
    if days_to_race <= 14:
        return [("in_taper(athlete, taper_early)", f"classify_taper_early_{days_to_race}d")]
    return []


def _classify_progression(week: int, total: int) -> list[tuple[str, str]]:
    """Progressionszustand klassifizieren.

    0–30%:  Intro (konservativ)
    30–70%: Build (Aufbau)
    70–90%: Peak (volle Intensität)
    90–100%: Pre-Taper (Reduktion)
    """
    if total <= 0:
        return [("in_progression(athlete, prog_build)", "classify_prog_default")]

    pct = (week - 1) / total
    if pct < 0.3:
        return [("in_progression(athlete, prog_intro)", f"classify_prog_intro_{pct:.0%}")]
    if pct < 0.7:
        return [("in_progression(athlete, prog_build)", f"classify_prog_build_{pct:.0%}")]
    if pct < 0.9:
        return [("in_progression(athlete, prog_peak)", f"classify_prog_peak_{pct:.0%}")]
    return [("in_progression(athlete, prog_pretaper)", f"classify_prog_pretaper_{pct:.0%}")]


# =========================================================================
#  HAUPT-INFERENZ
# =========================================================================

def run_inference(
    athlete: AthleteInput,
    week_in_phase: int = 1,
    phase_weeks_total: int = 8,
    days_to_race: int | None = None,
) -> InferenceResult:
    """Führe vollständige PyReason-Inferenz durch.

    Übersetzt Rohdaten → Fakten → PyReason → strukturiertes Ergebnis.
    """
    result = InferenceResult()

    with _reasoning_lock:
        pr.reset()
        pr.reset_settings()
        pr.settings.verbose = False
        pr.settings.atom_trace = True

        # 1. Wissensgraph laden
        graph = build_knowledge_graph()
        pr.load_graph(graph)

        # 2. Alle 30 Regeln laden
        for rule_str, rule_name in PYREASON_RULES:
            pr.add_rule(pr.Rule(rule_str, rule_name))

        # 3. FAKTEN INJIZIEREN

        # Phase
        phase = athlete.current_phase
        if phase not in ("general", "supportive", "specific"):
            phase = "general"
        _add_fact(f"in_phase(athlete, {phase})", "athlete_phase", result)

        # Always-On (Kernregel R14: Strides + Easy ganzjährig)
        _add_fact("always_on(z115)", "R14_strides_always", result)
        _add_fact("always_on(z80)", "R14_easy_always", result)

        # Distanz
        dist_node = DISTANCE_NODE_MAP.get(athlete.target_distance)
        if dist_node:
            _add_fact(f"targets(athlete, {dist_node})", "athlete_distance", result)

        # Erfahrung
        for fact_str, name in _classify_experience(athlete.experience_years):
            _add_fact(fact_str, name, result)

        # Volumen
        for fact_str, name in _classify_volume(athlete.weekly_km):
            _add_fact(fact_str, name, result)

        # Erholung
        for fact_str, name in _classify_recovery(
            athlete.days_since_hard_workout, phase, athlete.experience_years
        ):
            _add_fact(fact_str, name, result)

        # Progression
        for fact_str, name in _classify_progression(week_in_phase, phase_weeks_total):
            _add_fact(fact_str, name, result)

        # Taper
        for fact_str, name in _classify_taper(days_to_race):
            _add_fact(fact_str, name, result)

        # 4. REASONING
        interpretation = pr.reason(timesteps=4)

        # 5. ERGEBNISSE EXTRAHIEREN
        _extract_results(interpretation, result)

    return result


def run_week_inference(inp: WeekPlanInput) -> InferenceResult:
    """Convenience: Inferenz mit WeekPlanInput (hat week_in_phase etc.)."""
    athlete = AthleteInput(
        target_distance=inp.target_distance,
        race_time_seconds=inp.race_time_seconds,
        weekly_km=inp.weekly_km,
        experience_years=inp.experience_years,
        current_phase=inp.current_phase,
        days_since_hard_workout=inp.days_since_hard_workout,
    )
    return run_inference(
        athlete,
        week_in_phase=inp.week_in_phase,
        phase_weeks_total=inp.phase_weeks_total,
        days_to_race=inp.days_to_race,
    )


def run_pace_update_inference(inp: PaceUpdateInput) -> InferenceResult:
    """Inferenz für Pace-Aktualisierung (R48–R54).

    Übersetzt Pace-Update-Daten in Fakten und lässt PyReason
    Strategie, Warnungen und Empfehlungen ableiten.
    """
    result = InferenceResult()

    with _reasoning_lock:
        pr.reset()
        pr.reset_settings()
        pr.settings.verbose = False
        pr.settings.atom_trace = True

        graph = build_knowledge_graph()
        pr.load_graph(graph)

        for rule_str, rule_name in PYREASON_RULES:
            pr.add_rule(pr.Rule(rule_str, rule_name))

        # --- Fakten ---

        # Update überfällig?
        if inp.weeks_since_last_update >= 4:
            _add_fact("update_overdue(athlete)", "update_overdue_4w", result)

        # Neues Rennergebnis?
        if inp.new_race_time_seconds is not None:
            _add_fact("has_race_result(athlete)", "has_race_result", result)

            # Verbesserung berechnen
            improvement_pct = (
                (inp.current_race_time_seconds - inp.new_race_time_seconds)
                / inp.current_race_time_seconds * 100
            )
            if abs(improvement_pct) > 10:
                _add_fact("extreme_improvement(athlete)",
                          f"extreme_{improvement_pct:+.1f}%", result)
            elif abs(improvement_pct) > 5:
                _add_fact("large_improvement(athlete)",
                          f"large_{improvement_pct:+.1f}%", result)

            # Schneller Verbesserer? (>3% in <4 Wochen)
            if improvement_pct > 3 and inp.weeks_since_last_update <= 4:
                _add_fact("rapid_improver(athlete)",
                          f"rapid_{improvement_pct:.1f}%_in_{inp.weeks_since_last_update}w", result)

        # Ziel-Pace?
        if inp.goal_race_time_seconds is not None:
            _add_fact("has_goal_pace(athlete)", "has_goal_pace", result)

        # Erfahrung
        for fact_str, name in _classify_experience(inp.experience_years):
            _add_fact(fact_str, name, result)

        # Volumen
        for fact_str, name in _classify_volume(inp.weekly_km):
            _add_fact(fact_str, name, result)

        # Reasoning
        interpretation = pr.reason(timesteps=4)

        # Ergebnisse
        _extract_results(interpretation, result)

    return result


# =========================================================================
#  HILFSFUNKTIONEN
# =========================================================================

def _add_fact(fact_str: str, name: str, result: InferenceResult) -> None:
    """Fakt hinzufügen und im Trace loggen."""
    pr.add_fact(pr.Fact(fact_str, name, start_time=0, end_time=4))
    result.facts_injected.append(f"{name}: {fact_str}")
    result.trace.append(f"FAKT: {fact_str} [{name}]")


def _query_safe(interpretation: object, query_str: str) -> bool:
    """Sichere PyReason-Abfrage (fängt Exceptions ab)."""
    try:
        return interpretation.query(pr.Query(query_str))
    except Exception:
        return False


def _extract_results(interpretation: object, result: InferenceResult) -> None:
    """Extrahiere alle Prädikate aus der PyReason-Interpretation."""

    # --- Zonen ---
    for z in ZONE_NODES:
        if _query_safe(interpretation, f"active_zone({z})"):
            result.active_zones.append(z)
            result.rules_fired.append(f"active_zone({z})")
        if _query_safe(interpretation, f"support_zone({z})"):
            if z not in result.active_zones:
                result.support_zones.append(z)

    # --- Workouts ---
    for w in WORKOUT_NODES:
        if _query_safe(interpretation, f"do_workout({w})"):
            result.recommended_workouts.append(w)
        if _query_safe(interpretation, f"primary_workout({w})"):
            result.primary_workouts.append(w)
        if _query_safe(interpretation, f"distance_preferred({w})"):
            result.distance_preferred_workouts.append(w)
        if _query_safe(interpretation, f"priority_endurance({w})"):
            result.priority_endurance_workouts.append(w)
        if _query_safe(interpretation, f"preferred_long_run({w})"):
            result.preferred_long_runs.append(w)

        # Klassifikation
        if _query_safe(interpretation, f"is_hard({w})"):
            result.hard_workouts.append(w)
        if _query_safe(interpretation, f"is_quality({w})"):
            result.quality_workouts.append(w)
        if _query_safe(interpretation, f"is_key_session({w})"):
            result.key_sessions.append(w)

    # --- Athleten-Zustand ---
    result.needs_recovery = _query_safe(interpretation, "needs_recovery(athlete)")
    result.allow_hard = _query_safe(interpretation, "allow_hard(athlete)")
    result.extra_recovery_needed = _query_safe(interpretation, "extra_recovery_needed(athlete)")

    # --- Erfahrung / Volumen ---
    result.early_race_pace = _query_safe(interpretation, "early_race_pace(athlete)")
    result.reduce_speed = _query_safe(interpretation, "reduce_speed(athlete)")
    result.allow_complex = _query_safe(interpretation, "allow_complex(athlete)")
    result.reduce_sessions = _query_safe(interpretation, "reduce_sessions(athlete)")
    result.allow_three_quality = _query_safe(interpretation, "allow_three_quality(athlete)")
    result.prefer_strides_over_speed = _query_safe(interpretation, "prefer_strides_over_speed(athlete)")

    # --- Progression ---
    result.conservative = _query_safe(interpretation, "conservative(athlete)")
    result.building = _query_safe(interpretation, "building(athlete)")
    result.at_peak = _query_safe(interpretation, "at_peak(athlete)")
    result.tapering = _query_safe(interpretation, "tapering(athlete)")

    # --- Taper (R38–R47) ---
    result.in_taper_mode = _query_safe(interpretation, "in_taper_mode(athlete)")
    result.taper_allow_one_quality = _query_safe(interpretation, "taper_allow_one_quality(athlete)")
    result.taper_race_pace_only = _query_safe(interpretation, "taper_race_pace_only(athlete)")
    result.taper_easy_only = _query_safe(interpretation, "taper_easy_only(athlete)")
    result.taper_shake_out_only = _query_safe(interpretation, "taper_shake_out_only(athlete)")
    result.block_progression = _query_safe(interpretation, "block_progression(athlete)")

    # Volumen-Faktor aus Taper-Stufe
    if _query_safe(interpretation, "taper_volume_reduce_max(athlete)"):
        result.taper_volume_factor = 0.20
    elif _query_safe(interpretation, "taper_volume_reduce_heavy(athlete)"):
        result.taper_volume_factor = 0.40
    elif _query_safe(interpretation, "taper_volume_reduce_medium(athlete)"):
        result.taper_volume_factor = 0.60
    elif _query_safe(interpretation, "taper_volume_reduce_light(athlete)"):
        result.taper_volume_factor = 0.80
    else:
        result.taper_volume_factor = 1.0

    # --- Pace-Update (R48–R54) ---
    result.pace_update_due = _query_safe(interpretation, "pace_update_due(athlete)")
    result.recommend_fitness_update = _query_safe(interpretation, "recommend_fitness_update(athlete)")
    result.recommend_evolution = _query_safe(interpretation, "recommend_evolution(athlete)")
    result.recommend_bridging = _query_safe(interpretation, "recommend_bridging(athlete)")
    result.warn_large_pace_jump = _query_safe(interpretation, "warn_large_pace_jump(athlete)")
    result.warn_extreme_pace_jump = _query_safe(interpretation, "warn_extreme_pace_jump(athlete)")
    result.recalibrate_zones = _query_safe(interpretation, "recalibrate_zones(athlete)")

    # --- Phasen-Transition ---
    result.ready_for_next = _query_safe(interpretation, "ready_for_next(athlete)")
    result.ready_for_taper = _query_safe(interpretation, "ready_for_taper(athlete)")

    # --- Zone-Mixing ---
    for i, z1 in enumerate(ZONE_NODES):
        for z2 in ZONE_NODES[i + 1:]:
            if _query_safe(interpretation, f"mix_allowed({z1}, {z2})"):
                result.mixable_pairs.append((z1, z2))

    # --- Progression Stages (R31–R37) ---
    all_stages = [
        "rpr_base", "rpr_volume", "rpr_extension", "rpr_recovery",
        "flt_base", "flt_volume", "flt_extension", "flt_recovery",
        "tmp_base", "tmp_volume", "tmp_extension",
        "ssi_base", "ssi_volume", "ssi_extension",
        "spd_base", "spd_volume", "spd_extension",
        "lfr_base", "lfr_volume", "lfr_extension",
        "ler_base", "ler_volume", "ler_extension",
    ]
    for s in all_stages:
        if _query_safe(interpretation, f"use_stage({s})"):
            result.active_stages.append(s)
        if _query_safe(interpretation, f"next_progression({s})"):
            result.next_progressions.append(s)

    for w in WORKOUT_NODES:
        if _query_safe(interpretation, f"has_progression({w})"):
            result.workouts_with_progression.append(w)

    # --- Zusammenfassung ---
    result.trace.append(
        f"PYREASON: {len(result.active_zones)} Zonen, "
        f"{len(result.recommended_workouts)} Workouts, "
        f"{len(result.primary_workouts)} primär, "
        f"{len(result.distance_preferred_workouts)} distanz-bevorzugt"
    )
    result.trace.append(
        f"PROGRESSION: {len(result.active_stages)} aktive Stufen, "
        f"{len(result.next_progressions)} nächste Schritte"
    )
    if result.active_stages:
        result.trace.append(f"STUFEN: {', '.join(result.active_stages)}")
    result.trace.append(
        f"ZUSTAND: recovery={'JA' if result.needs_recovery else 'NEIN'}, "
        f"progression={'INTRO' if result.conservative else 'BUILD' if result.building else 'PEAK' if result.at_peak else 'TAPER' if result.tapering else '?'}, "
        f"reduce_speed={'JA' if result.reduce_speed else 'NEIN'}, "
        f"allow_3q={'JA' if result.allow_three_quality else 'NEIN'}"
    )
    if result.in_taper_mode:
        taper_type = (
            "RACE" if result.taper_shake_out_only else
            "LATE" if result.taper_easy_only else
            "MID" if result.taper_race_pace_only else
            "EARLY" if result.taper_allow_one_quality else "?"
        )
        result.trace.append(
            f"TAPER: {taper_type}, Volumen-Faktor={result.taper_volume_factor:.0%}, "
            f"Progression blockiert={'JA' if result.block_progression else 'NEIN'}"
        )
    if result.ready_for_next:
        result.trace.append("TRANSITION: Bereit für nächste Phase")
    if result.ready_for_taper:
        result.trace.append("TRANSITION: Bereit für Taper")
