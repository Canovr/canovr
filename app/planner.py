"""Wochenplan-Generator (Constraint-basiert).

Liest PyReason-Inferenzergebnisse und nutzt sie für Scoring,
Auswahl und Platzierung. Die Trainingslogik steckt in PyReason —
hier nur Mathematik und Constraint-Optimierung.
"""

from __future__ import annotations

from app.knowledge import (
    DISTANCE_VOLUME, STAGE_DESCRIPTIONS, WORKOUT_STAGE_PREFIX, WORKOUT_TEMPLATES,
)
from app.models import DAY_NAMES, DayPlan, WeekPlanInput, WeeklyPlan
from app.pace import compute_all_zones, race_pace_per_km, seconds_to_display
from app.reasoner import InferenceResult


# =========================================================================
#  WORKOUT-METADATEN (nur numerische Werte — Logik ist in PyReason)
# =========================================================================

WORKOUT_SESSION_KM_PCT: dict[str, float] = {
    "long_easy_run": 0.28, "long_fast_run": 0.30, "progression_run": 0.25,
    "tempo_continuous": 0.15, "threshold_intervals": 0.15,
    "float_recovery_workout": 0.18,
    "race_pace_reps": 0.16, "race_pace_continuous": 0.16,
    "specific_speed_intervals": 0.13, "fartlek": 0.14,
    "speed_intervals": 0.12, "short_reps": 0.10,
    "easy_run": 0.10, "strides": 0.0, "hill_sprints": 0.0,
    "race_pace_touch": 0.10, "shake_out": 0.06,
}

WORKOUT_ZONE: dict[str, int] = {
    "easy_run": 80, "long_easy_run": 85, "progression_run": 85,
    "long_fast_run": 90, "tempo_continuous": 90, "threshold_intervals": 90,
    "float_recovery_workout": 95,
    "race_pace_reps": 100, "race_pace_continuous": 100,
    "specific_speed_intervals": 105, "fartlek": 105,
    "speed_intervals": 110, "short_reps": 110,
    "strides": 115, "hill_sprints": 115,
    "race_pace_touch": 100, "shake_out": 80,
}


# =========================================================================
#  SCHRITT 1: SCORING (liest PyReason-Ergebnisse)
# =========================================================================

def score_workout(
    workout_key: str,
    inference: InferenceResult,
    last_week: list[str],
) -> tuple[float, str]:
    """Score ein Workout basierend auf PyReason-Prädikaten.

    Jeder Faktor kommt aus PyReason, nicht aus hardcodierten Dicts.
    """
    if workout_key not in inference.recommended_workouts:
        return 0.0, "nicht empfohlen"

    factors = []

    # F1: Primary Workout (aus primärer Phase-Zone) — von PyReason R14
    f_primary = 1.2 if workout_key in inference.primary_workouts else 0.7
    factors.append(f"primary={'JA' if f_primary > 1 else 'nein'}({f_primary:.1f})")

    # F2: Distanz-bevorzugt — von PyReason R15
    f_dist = 1.3 if workout_key in inference.distance_preferred_workouts else 0.8
    factors.append(f"dist_pref={'JA' if f_dist > 1 else 'nein'}({f_dist:.1f})")

    # F3: Endurance-Priorität — von PyReason R13 (Kernregel: Ausdauer > Speed)
    f_endurance = 1.2 if workout_key in inference.priority_endurance_workouts else 0.9
    factors.append(f"end_prio={'JA' if f_endurance > 1 else 'nein'}({f_endurance:.1f})")

    # F4: Progression — von PyReason R23–R26
    if inference.conservative:
        f_prog = 0.70
    elif inference.building:
        f_prog = 0.85
    elif inference.at_peak:
        f_prog = 1.00
    elif inference.tapering:
        f_prog = 0.90
    else:
        f_prog = 0.85
    factors.append(f"prog={f_prog:.2f}")

    # F5: Recency-Penalty (einzige Nicht-PyReason-Logik — erfordert Trainingshistorie)
    if workout_key in last_week:
        f_recency = 0.15
    elif any(WORKOUT_ZONE.get(w) == WORKOUT_ZONE.get(workout_key) for w in last_week):
        f_recency = 0.45
    else:
        f_recency = 1.0
    factors.append(f"rec={f_recency:.2f}")

    # F6: Speed-Reduktion für Anfänger — von PyReason R18
    f_speed_reduce = 1.0
    if inference.reduce_speed and workout_key not in inference.priority_endurance_workouts:
        f_speed_reduce = 0.5
        factors.append("novice_speed_reduce(0.5)")

    score = f_primary * f_dist * f_endurance * f_prog * f_recency * f_speed_reduce
    reason = " × ".join(factors) + f" = {score:.3f}"

    return score, reason


# =========================================================================
#  SCHRITT 2: AUSWAHL (liest PyReason allow_three_quality, reduce_sessions)
# =========================================================================

def _select_taper_workouts(
    inference: InferenceResult,
    inp: WeekPlanInput,
) -> tuple[list[tuple[str, float, str]], str | None, list[str]]:
    """Taper-spezifische Workout-Auswahl (PyReason R38–R47)."""
    trace: list[str] = []

    if inference.taper_shake_out_only:
        # Race-Woche: nur Shake-out
        trace.append("TAPER R45: Nur Shake-out oder Ruhe")
        return [], None, trace

    if inference.taper_easy_only:
        # Late Taper: kein Quality, kein Long Run
        trace.append("TAPER R43: Nur Easy + Strides")
        return [], None, trace

    long_run_key = None
    quality: list[tuple[str, float, str]] = []

    if inference.taper_race_pace_only:
        # Mid Taper: nur Race-Pace-Berührung
        trace.append("TAPER R41: Nur Race-Pace-Berührungen")
        quality = [("race_pace_touch", 1.0, "taper_mid")]
        return quality, None, trace

    if inference.taper_allow_one_quality:
        # Early Taper: eine Quality + reduzierter Long Run
        trace.append("TAPER R39: Eine Quality-Session + reduzierter Long Run")
        # Wähle das wichtigste Quality-Workout
        scored = []
        for w in inference.recommended_workouts:
            if w in ("easy_run", "strides", "hill_sprints", "race_pace_touch", "shake_out"):
                continue
            if w in ("long_easy_run", "long_fast_run", "progression_run"):
                continue
            score, reason = score_workout(w, inference, inp.last_week_workouts)
            if score > 0:
                scored.append((w, score, reason))
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored:
            quality = [scored[0]]
            trace.append(f"TAPER QUALITY: {scored[0][0]} (score={scored[0][1]:.3f})")

        # Reduzierter Long Run
        long_run_key = "long_easy_run"
        trace.append(f"TAPER LONG RUN: {long_run_key} (reduziert)")

        return quality, long_run_key, trace

    return [], None, trace


def select_workouts(
    inference: InferenceResult,
    inp: WeekPlanInput,
) -> tuple[list[tuple[str, float, str]], str | None, list[str]]:
    """Wähle Workouts per Scoring. Session-Limits aus PyReason."""

    # Taper überschreibt normale Auswahl (PyReason R38–R47)
    if inference.in_taper_mode:
        return _select_taper_workouts(inference, inp)

    trace: list[str] = []

    # Max Sessions — aus PyReason R20/R21
    n_hard = 2
    if inference.allow_three_quality:
        n_hard = 3
        trace.append("PYREASON R21: 3 Quality-Sessions erlaubt (erfahren + hohes Volumen)")
    if inference.reduce_sessions:
        n_hard = max(1, n_hard - 1)
        trace.append("PYREASON R20: Sessions reduziert (niedriges Volumen)")

    # Score alle Workouts
    scored: list[tuple[str, float, str]] = []
    for w in inference.recommended_workouts:
        if w in ("easy_run", "strides", "hill_sprints"):
            continue
        score, reason = score_workout(w, inference, inp.last_week_workouts)
        if score > 0:
            scored.append((w, score, reason))
    scored.sort(key=lambda x: x[1], reverse=True)

    # Long Runs: bevorzuge PyReason-preferred_long_runs
    long_run_key: str | None = None
    long_runs = [(w, s, r) for w, s, r in scored if w in ("long_easy_run", "long_fast_run", "progression_run")]
    # Priorisiere PyReason R16 preferred_long_runs
    preferred_lr = [lr for lr in long_runs if lr[0] in inference.preferred_long_runs]
    if preferred_lr:
        long_run_key = preferred_lr[0][0]
        trace.append(f"LONG RUN: {long_run_key} (PyReason R16: distanz-bevorzugt, score={preferred_lr[0][1]:.3f})")
    elif long_runs:
        long_run_key = long_runs[0][0]
        trace.append(f"LONG RUN: {long_run_key} (score={long_runs[0][1]:.3f})")

    # Quality Workouts
    quality = [(w, s, r) for w, s, r in scored if w not in ("long_easy_run", "long_fast_run", "progression_run")]
    selected: list[tuple[str, float, str]] = []
    used_zones: set[int] = set()
    has_endurance = False
    has_speed = False

    for w, s, r in quality:
        if len(selected) >= n_hard:
            break
        zone = WORKOUT_ZONE.get(w, 0)
        if zone in used_zones:
            continue

        # Strides-über-Speed wenn PyReason R22 aktiv
        if inference.prefer_strides_over_speed and w not in inference.priority_endurance_workouts:
            if w in ("speed_intervals", "short_reps"):
                trace.append(f"PYREASON R22: {w} übersprungen (Strides statt Speed)")
                continue

        selected.append((w, s, r))
        used_zones.add(zone)
        is_endurance = w in inference.priority_endurance_workouts
        has_endurance = has_endurance or is_endurance
        has_speed = has_speed or not is_endurance

    # Balance: mindestens 1 Endurance + 1 Speed
    if selected and not has_endurance:
        for w, s, r in quality:
            if w in inference.priority_endurance_workouts and WORKOUT_ZONE.get(w, 0) not in used_zones:
                if len(selected) >= n_hard:
                    selected[-1] = (w, s, r)
                else:
                    selected.append((w, s, r))
                trace.append(f"BALANCE: Endurance {w} ergänzt")
                break

    if selected and not has_speed and not inference.reduce_speed:
        for w, s, r in quality:
            if w not in inference.priority_endurance_workouts and WORKOUT_ZONE.get(w, 0) not in used_zones:
                if len(selected) >= n_hard:
                    selected[-1] = (w, s, r)
                else:
                    selected.append((w, s, r))
                trace.append(f"BALANCE: Speed {w} ergänzt")
                break

    for w, s, r in selected:
        trace.append(f"QUALITY: {w} (score={s:.3f}, {r})")

    return selected, long_run_key, trace


# =========================================================================
#  SCHRITT 3: PLATZIERUNG (Constraint-Solving — reine Optimierung)
# =========================================================================

def get_stage_volume(
    workout_key: str,
    target_distance: str,
    inference: InferenceResult,
) -> tuple[str, str | None]:
    """Hole die progressionsabhängige Workout-Beschreibung.

    Returns: (volume_description, stage_name_or_None)
    """
    prefix = WORKOUT_STAGE_PREFIX.get(workout_key)
    if not prefix:
        # Kein Progressions-Workout → Fallback auf DISTANCE_VOLUME / Template
        dist_vols = DISTANCE_VOLUME.get(target_distance, {})
        tmpl = WORKOUT_TEMPLATES.get(workout_key, {})
        return dist_vols.get(workout_key, tmpl.get("volume_default", "")), None

    # Finde die höchste aktive Stufe für dieses Workout
    # (PyReason kann mehrere aktivieren, z.B. volume + extension bei Peak)
    stage_order = ["_recovery", "_extension", "_volume", "_base"]
    active_stage = None
    for suffix in stage_order:
        stage_name = prefix + suffix
        if stage_name in inference.active_stages:
            active_stage = stage_name
            break

    if not active_stage:
        # Fallback
        dist_vols = DISTANCE_VOLUME.get(target_distance, {})
        tmpl = WORKOUT_TEMPLATES.get(workout_key, {})
        return dist_vols.get(workout_key, tmpl.get("volume_default", "")), None

    # Stage-Beschreibung holen (distanzspezifisch oder default)
    stage_desc = STAGE_DESCRIPTIONS.get(active_stage, {})
    volume = stage_desc.get(target_distance, stage_desc.get("default", ""))

    # Stage-Label für Anzeige
    stage_label = active_stage.split("_", 1)[1].upper()  # "rpr_volume" → "VOLUME"
    return volume, stage_label


def _circular_distance(a: int, b: int) -> int:
    return min((a - b) % 7, (b - a) % 7)


def place_workouts(
    quality: list[tuple[str, float, str]],
    long_run_key: str | None,
    inp: WeekPlanInput,
) -> tuple[dict[int, str], list[str]]:
    trace: list[str] = []
    placement: dict[int, str] = {}

    # Ruhetag
    rest_day = inp.rest_day
    if rest_day is None:
        lr_day = inp.long_run_day if inp.long_run_day is not None else 6
        rest_day = (lr_day + 1) % 7
        trace.append(f"EMPFEHLUNG Ruhetag: {DAY_NAMES[rest_day]} (Tag nach Long Run)")
    else:
        trace.append(f"GEWÄHLT Ruhetag: {DAY_NAMES[rest_day]}")
    placement[rest_day] = "__rest__"

    # Long Run
    lr_day = inp.long_run_day
    if lr_day is None:
        lr_day = 6 if 6 != rest_day else 0
        trace.append(f"EMPFEHLUNG Long Run: {DAY_NAMES[lr_day]}")
    else:
        trace.append(f"GEWÄHLT Long Run: {DAY_NAMES[lr_day]}")
    if long_run_key:
        placement[lr_day] = long_run_key

    # Quality: härteste zuerst, max Abstand
    hard_days: set[int] = set()
    if long_run_key:
        hard_days.add(lr_day)

    quality_sorted = sorted(quality, key=lambda x: x[1], reverse=True)

    for w_key, _s, _r in quality_sorted:
        available = [
            d for d in range(7)
            if d not in placement
            and not any(_circular_distance(d, hd) <= 1 for hd in hard_days)
        ]
        if not available:
            available = [d for d in range(7) if d not in placement]
        if not available:
            trace.append(f"ÜBERSPRUNGEN: {w_key}")
            break

        day_scores = [(d, min((_circular_distance(d, hd) for hd in hard_days), default=7)) for d in available]
        day_scores.sort(key=lambda x: x[1], reverse=True)
        best_day = day_scores[0][0]

        placement[best_day] = w_key
        hard_days.add(best_day)
        trace.append(f"PLATZIERT: {w_key} → {DAY_NAMES[best_day]} (Abstand={day_scores[0][1]:.0f}d)")

    return placement, trace


# =========================================================================
#  SCHRITT 4+5: VOLUMEN + STRIDES (reine Mathematik)
# =========================================================================

def _progression_volume_factor(inference: InferenceResult) -> float:
    """Volumen-Faktor aus PyReason-Progressionszustand."""
    if inference.conservative:
        return 0.70
    if inference.building:
        return 0.85
    if inference.at_peak:
        return 1.00
    if inference.tapering:
        return 0.90
    return 0.85


def distribute_volume(placement: dict[int, str], inp: WeekPlanInput, inference: InferenceResult) -> dict[int, float]:
    prog = _progression_volume_factor(inference)
    taper = inference.taper_volume_factor
    # Taper reduziert das GESAMTE Wochenvolumen
    effective_weekly_km = inp.weekly_km * taper
    day_km: dict[int, float] = {}
    allocated = 0.0

    for day, w_key in placement.items():
        if w_key == "__rest__":
            day_km[day] = 0.0
            continue
        km_pct = WORKOUT_SESSION_KM_PCT.get(w_key, 0.10)
        km = effective_weekly_km * km_pct * prog
        day_km[day] = round(km, 1)
        allocated += day_km[day]

    easy_days = [d for d in range(7) if d not in placement]
    remaining = max(0, effective_weekly_km - allocated)

    if easy_days:
        weights: dict[int, float] = {}
        for d in easy_days:
            prev_key = placement.get((d - 1) % 7, "")
            next_key = placement.get((d + 1) % 7, "")
            w = 1.0
            if prev_key not in ("__rest__", "") and prev_key in [k for k in placement.values() if k != "__rest__"]:
                w = 1.3
            if next_key not in ("__rest__", "") and next_key in [k for k in placement.values() if k != "__rest__"]:
                w = 0.8
            weights[d] = w

        total_w = sum(weights.values())
        for d in easy_days:
            km = remaining * weights[d] / total_w if total_w > 0 else 0.0
            day_km[d] = round(min(km, 16.0), 1)

        actual = sum(day_km.get(d, 0) for d in easy_days)
        leftover = remaining - actual
        if leftover > 1.0:
            per_day = leftover / len(easy_days)
            for d in easy_days:
                day_km[d] = round(min(day_km[d] + per_day, 16.0), 1)

    return day_km


def place_strides(placement: dict[int, str], day_km: dict[int, float]) -> set[int]:
    hardest_day = max(
        (d for d, w in placement.items() if w != "__rest__" and w in WORKOUT_SESSION_KM_PCT),
        key=lambda d: WORKOUT_SESSION_KM_PCT.get(placement.get(d, ""), 0),
        default=-1,
    )
    candidates = [
        (d, day_km.get(d, 0))
        for d in range(7)
        if d not in placement and (hardest_day < 0 or _circular_distance(d, hardest_day) > 1)
    ]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return {d for d, _ in candidates[:2]}


# =========================================================================
#  HAUPTFUNKTION
# =========================================================================

def generate_week_plan(inp: WeekPlanInput, inference: InferenceResult) -> WeeklyPlan:
    trace: list[str] = list(inference.trace)
    recommendations: list[str] = []

    rp = race_pace_per_km(inp.target_distance, inp.race_time_seconds)
    all_zones = compute_all_zones(rp)
    dist_volumes = DISTANCE_VOLUME.get(inp.target_distance, {})

    # Empfehlungen
    if inference.needs_recovery:
        recommendations.append("Erholung nötig — keine zusätzliche harte Einheit eingeplant.")
    if inference.extra_recovery_needed:
        recommendations.append("Anfänger + erschöpft — lieber Workout streichen.")
    if inference.prefer_strides_over_speed:
        recommendations.append("Bei niedrigem Volumen Strides statt Speed-Session.")
    if inference.ready_for_next:
        recommendations.append("Bereit für nächste Trainingsphase.")
    if inference.ready_for_taper:
        recommendations.append("Taper einleiten — Volumen senken, Intensität erhalten.")
    if inference.conservative:
        recommendations.append("Intro-Phase — Volumen konservativ halten.")
    if inference.in_taper_mode:
        vol_pct = int(inference.taper_volume_factor * 100)
        recommendations.append(
            f"TAPER AKTIV: Volumen auf {vol_pct}% reduziert. "
            "Intensität erhalten, Volumen senken."
        )
    if inference.taper_shake_out_only:
        recommendations.append("Race-Woche — nur Shake-out oder Ruhe.")
    if inference.taper_easy_only:
        recommendations.append("Late Taper — nur lockere Läufe + Strides.")
    if inference.block_progression:
        recommendations.append("Taper — keine Progression, nur erhalten.")

    # Auswahl + Platzierung
    quality, long_run_key, select_trace = select_workouts(inference, inp)
    trace.extend(select_trace)

    placement, place_trace = place_workouts(quality, long_run_key, inp)
    trace.extend(place_trace)

    day_km = distribute_volume(placement, inp, inference)
    strides_days = place_strides(placement, day_km)
    trace.append(f"STRIDES: {', '.join(DAY_NAMES[d] for d in sorted(strides_days))}")

    # Tage zusammenbauen
    days: list[DayPlan] = []
    total_km = 0.0
    hard_count = 0

    for d in range(7):
        w_key = placement.get(d)
        km = day_km.get(d, 0.0)
        total_km += km

        if w_key == "__rest__":
            days.append(DayPlan(day_index=d, day_name=DAY_NAMES[d], session_type="rest", estimated_km=0.0, description="Ruhetag"))
            continue

        if w_key and w_key in WORKOUT_SESSION_KM_PCT:
            tmpl = WORKOUT_TEMPLATES.get(w_key, {})
            zone_pct = WORKOUT_ZONE.get(w_key, 80)
            is_hard = w_key in inference.hard_workouts
            is_long = w_key in ("long_easy_run", "long_fast_run", "progression_run")
            is_key = w_key in inference.key_sessions

            session_type = "long_run" if is_long else ("hard" if is_hard else "moderate")
            if is_key:
                hard_count += 1

            # Progressionsabhängige Workout-Beschreibung (PyReason R31–R37)
            volume_desc, stage_label = get_stage_volume(w_key, inp.target_distance, inference)

            scoring_note = None
            if w_key in inference.primary_workouts:
                scoring_note = "Primary (R14)"
            if w_key in inference.distance_preferred_workouts:
                scoring_note = (scoring_note or "") + " + Dist-Pref (R15)"
            if stage_label:
                scoring_note = (scoring_note + " | " if scoring_note else "") + f"Stage: {stage_label} (R31-37)"

            days.append(DayPlan(
                day_index=d, day_name=DAY_NAMES[d], session_type=session_type,
                workout_key=w_key, workout_name=tmpl.get("name", w_key),
                description=tmpl.get("description", ""), zone=f"z{zone_pct}",
                percentage=zone_pct, pace=seconds_to_display(all_zones[zone_pct]),
                volume=volume_desc,
                estimated_km=km, scoring_reason=scoring_note,
            ))
        else:
            session_type = "easy+strides" if d in strides_days else "easy"
            desc = "Lockerer Dauerlauf" + (" + 5–6 × 100 m Steigerungsläufe" if d in strides_days else "")
            days.append(DayPlan(
                day_index=d, day_name=DAY_NAMES[d], session_type=session_type,
                workout_key="easy_run",
                workout_name="Lockerer Dauerlauf" + (" + Strides" if d in strides_days else ""),
                description=desc, zone="z80", percentage=80,
                pace=seconds_to_display(all_zones[80]), estimated_km=km,
            ))

    prog_pct = (inp.week_in_phase - 1) / max(1, inp.phase_weeks_total) * 100

    return WeeklyPlan(
        phase=inp.current_phase, week_in_phase=inp.week_in_phase,
        phase_weeks_total=inp.phase_weeks_total, progression_pct=round(prog_pct, 1),
        total_km=round(total_km, 1), hard_sessions=hard_count,
        days=days, reasoning_trace=trace, recommendations=recommendations,
    )
