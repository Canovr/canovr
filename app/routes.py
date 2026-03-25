"""Litestar API-Routen für CanovR."""

from __future__ import annotations

from typing import Annotated

from litestar import Controller, get, post
from litestar.exceptions import ClientException
from litestar.openapi.spec import Example
from litestar.params import Body

from app.auth_models import User
from app.knowledge import DISTANCE_VOLUME, WORKOUT_TEMPLATES
from app.models import (
    DISTANCES,
    AthleteInput,
    PaceUpdateInput,
    PaceUpdateResult,
    PaceZone,
    PaceZoneDelta,
    TrainingRecommendation,
    WeekPlanInput,
    WeeklyPlan,
    WorkoutSuggestion,
)
from app.pace import ZONE_ROLES, compute_all_zones, race_pace_per_km, seconds_to_display
from app.reasoner import run_inference, run_pace_update_inference, run_week_inference


WORKOUT_ZONE: dict[str, int] = {
    "easy_run": 80, "long_easy_run": 85, "progression_run": 85,
    "long_fast_run": 90, "tempo_continuous": 90, "threshold_intervals": 90,
    "float_recovery_workout": 95,
    "race_pace_reps": 100, "race_pace_continuous": 100,
    "specific_speed_intervals": 105, "fartlek": 105,
    "speed_intervals": 110, "short_reps": 110,
    "strides": 115, "hill_sprints": 115,
}


class TrainingController(Controller):
    path = "/api/training"
    tags = ["Training"]

    @post("/recommend")
    async def recommend(
        self,
        current_user: User,
        data: Annotated[AthleteInput, Body(examples=[Example(
            summary="10k-Läufer, 40:00",
            value={
                "target_distance": "10k",
                "race_time_seconds": 2400.0,
                "weekly_km": 75.0,
                "experience_years": 5,
                "current_phase": "supportive",
                "days_since_hard_workout": 2,
            },
        )])],
    ) -> TrainingRecommendation:
        """Trainingsempfehlung via PyReason-Inferenz."""
        if data.target_distance not in DISTANCES:
            raise ClientException(
                detail=f"Unbekannte Distanz. Gültig: {', '.join(DISTANCES.keys())}",
                status_code=400,
            )
        if data.current_phase not in ("general", "supportive", "specific"):
            raise ClientException(
                detail="Phase muss 'general', 'supportive' oder 'specific' sein",
                status_code=400,
            )

        rp = race_pace_per_km(data.target_distance, data.race_time_seconds)
        all_zones = compute_all_zones(rp)
        inference = run_inference(data)

        pace_zones = []
        for pct in sorted(all_zones.keys()):
            zk = f"z{pct}"
            is_active = zk in inference.active_zones
            pace_zones.append(PaceZone(
                label=zk, percentage=pct,
                pace_per_km=seconds_to_display(all_zones[pct]),
                pace_per_km_seconds=round(all_zones[pct], 1),
                role=ZONE_ROLES[pct],
                active=is_active or zk in inference.support_zones,
                primary=is_active and zk not in inference.support_zones,
            ))

        workouts = []
        dist_volumes = DISTANCE_VOLUME.get(data.target_distance, {})

        if inference.needs_recovery:
            for w_key in ("easy_run", "strides"):
                tmpl = WORKOUT_TEMPLATES[w_key]
                zone_pct = WORKOUT_ZONE[w_key]
                workouts.append(WorkoutSuggestion(
                    name=tmpl["name"], zone=f"z{zone_pct}", percentage=zone_pct,
                    pace=seconds_to_display(all_zones[zone_pct]),
                    description=tmpl["description"],
                    volume_hint=dist_volumes.get(w_key, tmpl["volume_default"]),
                ))
        else:
            for w_key in inference.recommended_workouts:
                if w_key not in WORKOUT_TEMPLATES:
                    continue
                tmpl = WORKOUT_TEMPLATES[w_key]
                zone_pct = WORKOUT_ZONE.get(w_key, 100)
                workouts.append(WorkoutSuggestion(
                    name=tmpl["name"], zone=f"z{zone_pct}", percentage=zone_pct,
                    pace=seconds_to_display(all_zones[zone_pct]),
                    description=tmpl["description"],
                    volume_hint=dist_volumes.get(w_key, tmpl["volume_default"]),
                ))
        workouts.sort(key=lambda w: w.percentage)

        # Phase hint aus PyReason
        phase_hint = None
        if inference.ready_for_next:
            phase_hint = "PyReason: Bereit für nächste Trainingsphase."
        elif inference.ready_for_taper:
            phase_hint = "PyReason: Taper einleiten."

        return TrainingRecommendation(
            athlete_phase=data.current_phase,
            recovery_needed=inference.needs_recovery,
            recovery_reason="PyReason R10: fatigued → needs_recovery" if inference.needs_recovery else None,
            pace_zones=pace_zones,
            recommended_workouts=workouts,
            reasoning_trace=inference.trace,
            next_phase_hint=phase_hint,
            rules_applied=inference.rules_fired,
        )

    @post("/week")
    async def week_plan(
        self,
        current_user: User,
        data: Annotated[WeekPlanInput, Body(examples=[Example(
            summary="Supportive Phase Woche 3/8",
            value={
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
        )])],
    ) -> WeeklyPlan:
        """7-Tage-Wochenplan via PyReason + Constraint-Solving."""
        from app.planner import generate_week_plan

        if data.target_distance not in DISTANCES:
            raise ClientException(
                detail=f"Unbekannte Distanz. Gültig: {', '.join(DISTANCES.keys())}",
                status_code=400,
            )
        if data.current_phase not in ("general", "supportive", "specific"):
            raise ClientException(
                detail="Phase muss 'general', 'supportive' oder 'specific' sein",
                status_code=400,
            )

        inference = run_week_inference(data)
        return generate_week_plan(data, inference)

    @post("/pace-update")
    async def pace_update(
        self,
        current_user: User,
        data: Annotated[PaceUpdateInput, Body(examples=[Example(
            summary="Fitness-Update nach neuem 10k",
            value={
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
        )])],
    ) -> PaceUpdateResult:
        """Pace-Aktualisierung via PyReason (R48–R54).

        Berechnet neue Paces, empfiehlt Strategie, warnt bei Anomalien.
        """
        if data.target_distance not in DISTANCES:
            raise ClientException(
                detail=f"Unbekannte Distanz. Gültig: {', '.join(DISTANCES.keys())}",
                status_code=400,
            )

        # PyReason-Inferenz für Strategie + Warnungen
        inference = run_pace_update_inference(data)

        # --- Neue Race Pace berechnen ---
        old_rp = race_pace_per_km(data.target_distance, data.current_race_time_seconds)

        new_race_time = data.current_race_time_seconds  # Default: keine Änderung

        if data.new_race_time_seconds is not None:
            # Neues Rennergebnis auf Zieldistanz umrechnen falls nötig
            race_dist = data.new_race_distance or data.target_distance
            if race_dist != data.target_distance and race_dist in DISTANCES:
                # Umrechnung über Pace-Verhältnis (5%-Regel)
                race_km = DISTANCES[race_dist]
                target_km = DISTANCES[data.target_distance]
                new_pace = data.new_race_time_seconds / race_km
                # Skalierung: kürzere Distanz → schnellere Pace
                ratio = (target_km / race_km) ** 0.06  # ~5% pro Verdoppelung
                new_race_time = new_pace * ratio * target_km
            else:
                new_race_time = data.new_race_time_seconds

        # Bridging: interpoliere zwischen aktuell und Ziel
        if (data.goal_race_time_seconds is not None
                and data.weeks_to_goal_race is not None
                and inference.recommend_bridging):
            progress = min(1.0, data.weeks_since_last_update / max(1, data.weeks_to_goal_race))
            bridged_time = (
                data.current_race_time_seconds
                + (data.goal_race_time_seconds - data.current_race_time_seconds) * progress
            )
            # Bridging nur wenn es eine Verbesserung ist
            if bridged_time < new_race_time:
                new_race_time = bridged_time

        new_rp = race_pace_per_km(data.target_distance, new_race_time)

        improvement_pct = round(
            (data.current_race_time_seconds - new_race_time)
            / data.current_race_time_seconds * 100, 2
        )

        # --- Zonen vergleichen ---
        old_zones = compute_all_zones(old_rp)
        new_zones = compute_all_zones(new_rp)
        zone_deltas = []
        for pct in sorted(old_zones.keys()):
            delta = round(old_zones[pct] - new_zones[pct], 1)
            zone_deltas.append(PaceZoneDelta(
                label=f"z{pct}", percentage=pct,
                old_pace=seconds_to_display(old_zones[pct]),
                new_pace=seconds_to_display(new_zones[pct]),
                delta_seconds=delta,
                role=ZONE_ROLES[pct],
            ))

        # --- Strategie bestimmen (PyReason-driven) ---
        if inference.recommend_bridging:
            strategy = "bridging"
            reason = "PyReason R51: Ziel-Pace gesetzt + erfahren → lineare Annäherung"
        elif inference.recommend_evolution:
            strategy = "workout_evolution"
            reason = "PyReason R50: Schnelle Verbesserung → Paces fixieren, Workouts evolvieren"
        elif inference.recommend_fitness_update:
            strategy = "fitness_update"
            reason = "PyReason R49: Neues Rennergebnis → direkte Pace-Aktualisierung"
        else:
            strategy = "fitness_update"
            reason = "Standard: Fitness-Update basierend auf letztem Ergebnis"

        # --- Warnungen (PyReason R52/R53) ---
        warnings: list[str] = []
        if inference.warn_extreme_pace_jump:
            warnings.append(
                f"PyReason R53: Extremer Pace-Sprung ({improvement_pct:+.1f}%). "
                "Eingabefehler? Überprüfe das Ergebnis."
            )
        elif inference.warn_large_pace_jump:
            warnings.append(
                f"PyReason R52: Großer Pace-Sprung ({improvement_pct:+.1f}%). "
                "Konservativere Anpassung erwägen."
            )

        # --- Empfehlungen ---
        recommendations: list[str] = []
        if inference.pace_update_due:
            recommendations.append("PyReason R48: Pace-Update war fällig (≥4 Wochen).")
        if inference.recalibrate_zones:
            recommendations.append("PyReason R54: Alle Zonen-Paces wurden neu kalibriert.")
        if strategy == "workout_evolution":
            recommendations.append(
                "Bei Workout-Evolution: Paces NICHT ändern. "
                "Stattdessen Workouts bei fester Pace weiterentwickeln."
            )
        if strategy == "bridging":
            recommendations.append(
                f"Bridging: Paces werden schrittweise zum Ziel angepasst "
                f"({data.weeks_to_goal_race} Wochen verbleibend)."
            )

        return PaceUpdateResult(
            recommended_strategy=strategy,
            strategy_reason=reason,
            old_race_pace=seconds_to_display(old_rp),
            new_race_pace=seconds_to_display(new_rp),
            improvement_pct=improvement_pct,
            zones=zone_deltas,
            warnings=warnings,
            recommendations=recommendations,
            reasoning_trace=inference.trace,
            rules_applied=inference.rules_fired,
        )

    @get("/distances")
    async def list_distances(self) -> dict[str, float]:
        return DISTANCES

    @get("/rules")
    async def list_rules(self) -> dict[str, list[str]]:
        from app.knowledge import PYREASON_RULES
        return {
            "pyreason_rules": [f"{name}: {rule}" for rule, name in PYREASON_RULES],
            "total": [f"{len(PYREASON_RULES)} Regeln"],
        }
