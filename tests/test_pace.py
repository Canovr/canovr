"""Tests für Pace-Berechnungen."""

from app.pace import compute_all_zones, race_pace_per_km, seconds_to_display, zone_pace


class TestRacePace:
    def test_10k_40min(self):
        assert race_pace_per_km("10k", 2400) == 240.0

    def test_5k_20min(self):
        assert race_pace_per_km("5k", 1200) == 240.0

    def test_marathon_3h(self):
        rp = race_pace_per_km("marathon", 10800)
        assert round(rp, 1) == 256.0  # 4:16/km

    def test_800m(self):
        rp = race_pace_per_km("800m", 120)  # 2:00
        assert rp == 150.0  # 2:30/km


class TestZonePace:
    def test_100_pct_equals_race_pace(self):
        assert zone_pace(240.0, 100) == 240.0

    def test_95_pct_is_slower(self):
        # 95% der Geschwindigkeit → langsamere Pace
        assert zone_pace(240.0, 95) > 240.0

    def test_105_pct_is_faster(self):
        assert zone_pace(240.0, 105) < 240.0

    def test_80_pct_is_slowest(self):
        p80 = zone_pace(240.0, 80)
        p115 = zone_pace(240.0, 115)
        assert p80 > p115  # 80% langsamer als 115%

    def test_5pct_rule_approximation(self):
        """5% langsamer ≈ doppelte Durchhaltefähigkeit."""
        p100 = zone_pace(240.0, 100)
        p95 = zone_pace(240.0, 95)
        # 95% Pace sollte ~5% langsamer sein als 100%
        ratio = p95 / p100
        assert 1.04 < ratio < 1.06


class TestComputeAllZones:
    def test_returns_8_zones(self):
        zones = compute_all_zones(240.0)
        assert len(zones) == 8
        assert set(zones.keys()) == {80, 85, 90, 95, 100, 105, 110, 115}

    def test_zones_are_ordered(self):
        zones = compute_all_zones(240.0)
        paces = [zones[p] for p in sorted(zones.keys())]
        # Höhere % → schnellere Pace (niedrigere Sekunden)
        assert paces == sorted(paces, reverse=True)


class TestSecondsToDisplay:
    def test_4min(self):
        assert seconds_to_display(240.0) == "4:00/km"

    def test_3min30(self):
        assert seconds_to_display(210.0) == "3:30/km"

    def test_5min05(self):
        assert seconds_to_display(305.0) == "5:05/km"
