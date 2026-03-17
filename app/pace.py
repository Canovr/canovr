"""Pace-Berechnungen für das Full-Spectrum-System.

Kernregel: Alle Trainingspaces als Prozentsatz der aktuellen Wettkampfpace.
5% langsamer ≈ doppelte Durchhaltefähigkeit.
"""

from __future__ import annotations

from app.models import DISTANCES


def seconds_to_display(seconds: float) -> str:
    """Sekunden → 'M:SS/km' Format."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}/km"


def race_pace_per_km(distance_key: str, race_time_seconds: float) -> float:
    """Berechne Race Pace in Sekunden pro km."""
    km = DISTANCES[distance_key]
    return race_time_seconds / km


def zone_pace(race_pace_s_per_km: float, percentage: int) -> float:
    """Pace für eine Zone berechnen.

    percentage > 100 → schneller (niedrigere Pace)
    percentage < 100 → langsamer (höhere Pace)

    pace_at_X% = race_pace / (X / 100)
    """
    return race_pace_s_per_km / (percentage / 100.0)


def compute_all_zones(race_pace_s_per_km: float) -> dict[int, float]:
    """Alle 8 Zonen-Paces berechnen."""
    percentages = [80, 85, 90, 95, 100, 105, 110, 115]
    return {p: zone_pace(race_pace_s_per_km, p) for p in percentages}


ZONE_ROLES: dict[int, str] = {
    80: "Basic Endurance — langsamste strukturierte Pace",
    85: "General Endurance — aerobe Basis",
    90: "Race-Supportive Endurance — direkte Wettkampfunterstützung",
    95: "Race-Specific Endurance — Hauptvorbereitung",
    100: "Race Pace — Wettkampfgeschwindigkeit",
    105: "Race-Specific Speed — Tempoentwicklung",
    110: "Race-Supportive Speed — Unterstützung für 105%",
    115: "General Speed — Schnelligkeitserhalt",
}
