"""Wissensgraph und Regeldefinitionen für PyReason.

Das gesamte Trainingswissen der Full-Spectrum-Methode ist hier als
annotierter Graph + logische Regeln kodiert. PyReason ist das Backbone
der Entscheidungslogik — Python macht nur Mathematik und Optimierung.
"""

from __future__ import annotations

import networkx as nx


def build_knowledge_graph() -> nx.DiGraph:
    """Erstelle den Wissensgraphen mit allen Knoten, Kanten und Annotationen."""

    g = nx.DiGraph()

    # =================================================================
    #  PHASEN
    # =================================================================
    g.add_node("general", is_general=1)
    g.add_node("supportive", is_supportive=1)
    g.add_node("specific", is_specific=1)

    # =================================================================
    #  ZONEN (mit Klassifikations-Attributen)
    # =================================================================
    endurance_zones = {
        "z80":  {"is_endurance_zone": 1, "endurance_priority": 1, "zone_pct": 1},
        "z85":  {"is_endurance_zone": 1, "endurance_priority": 1, "zone_pct": 1},
        "z90":  {"is_endurance_zone": 1, "endurance_priority": 1, "high_endurance_priority": 1, "zone_pct": 1},
        "z95":  {"is_endurance_zone": 1, "endurance_priority": 1, "high_endurance_priority": 1, "zone_pct": 1},
        "z100": {"is_endurance_zone": 1, "endurance_priority": 1, "high_endurance_priority": 1, "zone_pct": 1},
    }
    speed_zones = {
        "z105": {"is_speed_zone": 1, "zone_pct": 1},
        "z110": {"is_speed_zone": 1, "zone_pct": 1},
        "z115": {"is_speed_zone": 1, "zone_pct": 1},
    }
    for z, attrs in {**endurance_zones, **speed_zones}.items():
        g.add_node(z, **attrs)

    # =================================================================
    #  WORKOUTS (mit Klassifikations-Attributen)
    # =================================================================
    workout_attrs = {
        # Long Runs
        "long_easy_run":   {"is_long_run": 1, "medium_stress": 1},
        "long_fast_run":   {"is_long_run": 1, "high_stress": 1},
        "progression_run": {"is_long_run": 1, "medium_stress": 1},

        # Endurance Quality
        "tempo_continuous":       {"is_endurance": 1, "medium_stress": 1},
        "threshold_intervals":    {"is_endurance": 1, "medium_stress": 1},
        "float_recovery_workout": {"is_endurance": 1, "high_stress": 1},
        "race_pace_reps":         {"is_endurance": 1, "high_stress": 1},
        "race_pace_continuous":   {"is_endurance": 1, "high_stress": 1},

        # Speed Quality
        "specific_speed_intervals": {"is_speed": 1, "high_stress": 1},
        "fartlek":                  {"is_speed": 1, "medium_stress": 1},
        "speed_intervals":          {"is_speed": 1, "medium_stress": 1},
        "short_reps":               {"is_speed": 1, "low_stress": 1},

        # Easy / Supplement
        "easy_run":     {"is_easy": 1, "low_stress": 1},
        "strides":      {"is_supplement": 1, "low_stress": 1},
        "hill_sprints": {"is_supplement": 1, "low_stress": 1},

        # Taper-spezifische Workouts
        "race_pace_touch": {"is_taper_workout": 1, "low_stress": 1},
        "shake_out":       {"is_taper_workout": 1, "low_stress": 1, "is_easy": 1},
    }
    for w, attrs in workout_attrs.items():
        g.add_node(w, **attrs)

    # =================================================================
    #  TAPER-PHASEN (mit Diskriminator-Attributen)
    # =================================================================
    g.add_node("taper_early",  is_taper_early=1)   # 10–14 Tage
    g.add_node("taper_mid",    is_taper_mid=1)      # 5–9 Tage
    g.add_node("taper_late",   is_taper_late=1)     # 2–4 Tage
    g.add_node("taper_race",   is_taper_race=1)     # 0–1 Tage

    # Race-Pace-Touch nutzt z100
    g.add_edge("z100", "race_pace_touch", zone_uses=1)
    # Shake-out nutzt z80
    g.add_edge("z80", "shake_out", zone_uses=1)

    # =================================================================
    #  PACE-UPDATE-KNOTEN
    # =================================================================
    # Update-Trigger
    g.add_node("update_due",         is_update_due=1)
    g.add_node("update_not_due",     is_update_not_due=1)
    # Strategien
    g.add_node("strat_fitness",      is_fitness_strategy=1)
    g.add_node("strat_evolution",    is_evolution_strategy=1)
    g.add_node("strat_bridging",     is_bridging_strategy=1)
    # Warnungen
    g.add_node("warn_large_jump",    is_large_jump=1)      # >5%
    g.add_node("warn_extreme_jump",  is_extreme_jump=1)     # >10%
    g.add_node("warn_no_change",     is_no_change=1)        # <0.5%

    # =================================================================
    #  DISTANZEN (mit Klassifikation)
    # =================================================================
    g.add_node("dist_800m",     speed_distance=1, is_distance=1)
    g.add_node("dist_1500m",    speed_distance=1, is_distance=1)
    g.add_node("dist_mile",     speed_distance=1, is_distance=1)
    g.add_node("dist_3k",       balanced_distance=1, is_distance=1)
    g.add_node("dist_5k",       balanced_distance=1, is_distance=1)
    g.add_node("dist_10k",      endurance_distance=1, is_distance=1)
    g.add_node("dist_half",     endurance_distance=1, is_distance=1)
    g.add_node("dist_marathon", endurance_distance=1, is_distance=1)

    # =================================================================
    #  PROGRESSIONS-KNOTEN
    # =================================================================
    g.add_node("prog_intro", is_intro=1)
    g.add_node("prog_build", is_build=1)
    g.add_node("prog_peak", is_peak=1)
    g.add_node("prog_pretaper", is_pretaper=1)

    # =================================================================
    #  ATHLETEN-PLATZHALTER
    # =================================================================
    g.add_node("athlete")

    # =================================================================
    #  KANTEN: Phase → Zone (phase_activates)
    # =================================================================
    # General: breites Spektrum 80-90% + 110-115%
    for z in ["z80", "z85", "z90", "z110", "z115"]:
        g.add_edge("general", z, phase_activates=1)
    # Supportive: 90%, 95%, 105%, 110%
    for z in ["z90", "z95", "z105", "z110"]:
        g.add_edge("supportive", z, phase_activates=1)
    # Specific: 95%, 100%, 105%
    for z in ["z95", "z100", "z105"]:
        g.add_edge("specific", z, phase_activates=1)

    # =================================================================
    #  KANTEN: Zone → Zone (foundation_for) — "adds, not replaces"
    # =================================================================
    # Ausdauerseite
    g.add_edge("z80", "z85",  foundation_for=1)
    g.add_edge("z85", "z90",  foundation_for=1)
    g.add_edge("z90", "z95",  foundation_for=1)
    g.add_edge("z95", "z100", foundation_for=1)
    # Temposeite
    g.add_edge("z115", "z110", foundation_for=1)
    g.add_edge("z110", "z105", foundation_for=1)
    g.add_edge("z105", "z100", foundation_for=1)

    # =================================================================
    #  KANTEN: Zone → Zone (adjacent)
    # =================================================================
    adjacent_pairs = [
        ("z80", "z85"), ("z85", "z90"), ("z90", "z95"),
        ("z95", "z100"), ("z100", "z105"), ("z105", "z110"),
        ("z110", "z115"),
    ]
    for a, b in adjacent_pairs:
        g.add_edge(a, b, adjacent=1)
        g.add_edge(b, a, adjacent=1)  # Bidirektional

    # =================================================================
    #  KANTEN: Zone → Workout (zone_uses)
    # =================================================================
    zone_workout_map = {
        "z80":  ["easy_run"],
        "z85":  ["long_easy_run", "progression_run"],
        "z90":  ["tempo_continuous", "long_fast_run", "threshold_intervals"],
        "z95":  ["race_pace_reps", "float_recovery_workout", "race_pace_continuous"],
        "z100": ["race_pace_reps", "race_pace_continuous"],
        "z105": ["specific_speed_intervals", "fartlek"],
        "z110": ["speed_intervals", "short_reps"],
        "z115": ["strides", "hill_sprints"],
    }
    for zone, workouts in zone_workout_map.items():
        for w in workouts:
            g.add_edge(zone, w, zone_uses=1)

    # =================================================================
    #  KANTEN: Distanz → Zone (distance_prefers)
    #  Welche Zonen für welche Distanz am wichtigsten sind
    # =================================================================
    distance_zone_prefs = {
        "dist_800m":    ["z100", "z105", "z110", "z115"],
        "dist_1500m":   ["z100", "z105", "z110", "z115"],
        "dist_mile":    ["z100", "z105", "z110"],
        "dist_3k":      ["z95", "z100", "z105", "z110"],
        "dist_5k":      ["z90", "z95", "z100", "z105"],
        "dist_10k":     ["z90", "z95", "z100", "z105"],
        "dist_half":    ["z85", "z90", "z95", "z100"],
        "dist_marathon": ["z85", "z90", "z95", "z100"],
    }
    for dist, zones in distance_zone_prefs.items():
        for z in zones:
            g.add_edge(dist, z, distance_prefers=1)

    # =================================================================
    #  KANTEN: Phase → Erholungs-Minimum
    #  Kodiert als Kanten zu Marker-Knoten
    # =================================================================
    g.add_node("high_recovery_need")
    g.add_node("medium_recovery_need")
    g.add_edge("general", "high_recovery_need", phase_recovery=1)
    g.add_edge("supportive", "medium_recovery_need", phase_recovery=1)
    g.add_edge("specific", "medium_recovery_need", phase_recovery=1)

    # =================================================================
    #  PROGRESSIONSSTUFEN
    #
    #  Jedes Key-Workout hat 3–4 Stufen: base → volume → extension → recovery
    #  Kernregel R7: "Workouts über Volumen → Extension → Erholung steigern"
    #  Kernregel R8: "Nur eine Dimension pro Steigerungsschritt"
    #
    #  PyReason bestimmt welche Stufe aktiv ist (R31–R37).
    # =================================================================

    progression_stages = {
        # race_pace_reps (z95–100)
        "rpr_base":      {"is_base": 1},
        "rpr_volume":    {"is_volume_stage": 1},
        "rpr_extension": {"is_extension_stage": 1},
        "rpr_recovery":  {"is_recovery_stage": 1},

        # float_recovery_workout (z95)
        "flt_base":      {"is_base": 1},
        "flt_volume":    {"is_volume_stage": 1},
        "flt_extension": {"is_extension_stage": 1},
        "flt_recovery":  {"is_recovery_stage": 1},

        # tempo_continuous (z90)
        "tmp_base":      {"is_base": 1},
        "tmp_volume":    {"is_volume_stage": 1},
        "tmp_extension": {"is_extension_stage": 1},

        # specific_speed_intervals (z105)
        "ssi_base":      {"is_base": 1},
        "ssi_volume":    {"is_volume_stage": 1},
        "ssi_extension": {"is_extension_stage": 1},

        # speed_intervals (z110)
        "spd_base":      {"is_base": 1},
        "spd_volume":    {"is_volume_stage": 1},
        "spd_extension": {"is_extension_stage": 1},

        # long_fast_run (z90)
        "lfr_base":      {"is_base": 1},
        "lfr_volume":    {"is_volume_stage": 1},
        "lfr_extension": {"is_extension_stage": 1},

        # long_easy_run (z85)
        "ler_base":      {"is_base": 1},
        "ler_volume":    {"is_volume_stage": 1},
        "ler_extension": {"is_extension_stage": 1},
    }
    for stage, attrs in progression_stages.items():
        g.add_node(stage, **attrs)

    # Kanten: Workout → Stufen (has_stage)
    workout_stages = {
        "race_pace_reps":         ["rpr_base", "rpr_volume", "rpr_extension", "rpr_recovery"],
        "float_recovery_workout": ["flt_base", "flt_volume", "flt_extension", "flt_recovery"],
        "tempo_continuous":       ["tmp_base", "tmp_volume", "tmp_extension"],
        "specific_speed_intervals": ["ssi_base", "ssi_volume", "ssi_extension"],
        "speed_intervals":        ["spd_base", "spd_volume", "spd_extension"],
        "long_fast_run":          ["lfr_base", "lfr_volume", "lfr_extension"],
        "long_easy_run":          ["ler_base", "ler_volume", "ler_extension"],
    }
    for workout, stages in workout_stages.items():
        for stage in stages:
            g.add_edge(workout, stage, has_stage=1)

    # Kanten: Stufe → Stufe (progresses_to) — die Progressionskette
    progression_chains = [
        ("rpr_base", "rpr_volume"), ("rpr_volume", "rpr_extension"), ("rpr_extension", "rpr_recovery"),
        ("flt_base", "flt_volume"), ("flt_volume", "flt_extension"), ("flt_extension", "flt_recovery"),
        ("tmp_base", "tmp_volume"), ("tmp_volume", "tmp_extension"),
        ("ssi_base", "ssi_volume"), ("ssi_volume", "ssi_extension"),
        ("spd_base", "spd_volume"), ("spd_volume", "spd_extension"),
        ("lfr_base", "lfr_volume"), ("lfr_volume", "lfr_extension"),
        ("ler_base", "ler_volume"), ("ler_volume", "ler_extension"),
    ]
    for s1, s2 in progression_chains:
        g.add_edge(s1, s2, progresses_to=1)

    return g


# =========================================================================
#  PYREASON-REGELN (30 Regeln — das Backbone der Trainingslogik)
# =========================================================================

PYREASON_RULES: list[tuple[str, str]] = [

    # =================================================================
    #  KERN: Zonen- und Workout-Aktivierung (R1–R5)
    # =================================================================

    # R1: Phase aktiviert ihre Zonen
    ("active_zone(z) <-0 in_phase(x, p), phase_activates(p, z)",
     "R1_phase_activates_zone"),

    # R2: Aktive Zone empfiehlt Workouts
    ("do_workout(w) <-0 active_zone(z), zone_uses(z, w)",
     "R2_zone_recommends_workout"),

    # R3: Foundation-Kette: "Training adds, not replaces"
    ("active_zone(z1) <-0 active_zone(z2), foundation_for(z1, z2)",
     "R3_foundation_chain"),

    # R4: Always-On-Workouts (Strides, Easy)
    ("do_workout(w) <-0 always_on(z), zone_uses(z, w)",
     "R4_always_on"),

    # R5: Nachbarzonen erhalten Stützstatus
    ("support_zone(z1) <-0 active_zone(z2), adjacent(z1, z2)",
     "R5_adjacent_support"),

    # =================================================================
    #  WORKOUT-KLASSIFIKATION (R6–R9)
    # =================================================================

    # R6: Harte Workouts identifizieren
    ("is_hard(w) <-0 high_stress(w)",
     "R6_hard_workout"),

    # R7a/b: Quality = Endurance oder Speed
    ("is_quality(w) <-0 is_endurance(w)",
     "R7a_quality_endurance"),
    ("is_quality(w) <-0 is_speed(w)",
     "R7b_quality_speed"),

    # R8: Long Runs als eigene Kategorie
    ("is_key_session(w) <-0 is_long_run(w)",
     "R8_long_run_key"),

    # R9: Quality Workouts sind auch Key Sessions
    ("is_key_session(w) <-0 is_quality(w), is_hard(w)",
     "R9_hard_quality_key"),

    # =================================================================
    #  ERHOLUNG (R10–R12)
    # =================================================================

    # R10: Erschöpfter Athlet braucht Erholung
    ("needs_recovery(x) <-0 fatigued(x)",
     "R10_needs_recovery"),

    # R11: Erholter Athlet darf harte Workouts machen
    ("allow_hard(x) <-0 recovered(x)",
     "R11_allow_hard"),

    # R12: Anfänger brauchen extra Erholung
    ("extra_recovery_needed(x) <-0 novice(x), fatigued(x)",
     "R12_novice_extra_recovery"),

    # =================================================================
    #  PRIORITÄT UND PRÄFERENZ (R13–R16)
    # =================================================================

    # R13: Endurance-Workouts aus aktiven Zonen haben Priorität (Kernregel R3)
    ("priority_endurance(w) <-0 do_workout(w), is_endurance(w)",
     "R13_endurance_priority"),

    # R14: Primary Workout = aus primärer Phase-Zone + Quality
    ("primary_workout(w) <-0 in_phase(x, p), phase_activates(p, z), zone_uses(z, w), is_quality(w)",
     "R14_primary_workout"),

    # R15: Distanz-bevorzugtes Workout
    ("distance_preferred(w) <-0 targets(x, d), distance_prefers(d, z), zone_uses(z, w), do_workout(w)",
     "R15_distance_preferred"),

    # R16: Long Run Empfehlung aus Distanz-Zonen
    ("preferred_long_run(w) <-0 targets(x, d), distance_prefers(d, z), zone_uses(z, w), is_long_run(w)",
     "R16_preferred_long_run"),

    # =================================================================
    #  ERFAHRUNG (R17–R19)
    # =================================================================

    # R17: Erfahrene Athleten in Supportive → dürfen Race Pace antasten
    #      (is_supportive(p) als Diskriminator statt Konstantenname)
    ("early_race_pace(x) <-0 experienced(x), in_phase(x, p), is_supportive(p)",
     "R17_experienced_early_rp"),

    # R18: Anfänger → weniger Speed-Arbeit empfohlen
    ("reduce_speed(x) <-0 novice(x)",
     "R18_novice_reduce_speed"),

    # R19: Erfahrene → komplexe Workouts erlaubt (Float, Wechselkm)
    ("allow_complex(x) <-0 experienced(x)",
     "R19_experienced_complex"),

    # =================================================================
    #  VOLUMEN (R20–R22)
    # =================================================================

    # R20: Niedriges Volumen → weniger Sessions
    ("reduce_sessions(x) <-0 low_volume(x)",
     "R20_low_vol_reduce"),

    # R21: Hohes Volumen + sehr erfahren + supportive → 3 Quality erlaubt
    ("allow_three_quality(x) <-0 high_volume(x), very_experienced(x), in_phase(x, p), is_supportive(p)",
     "R21_three_quality"),

    # R22: Niedriges Volumen → Strides statt separate Speed-Session
    ("prefer_strides_over_speed(x) <-0 low_volume(x), reduce_speed(x)",
     "R22_strides_over_speed"),

    # =================================================================
    #  PROGRESSION (R23–R26)
    #  Nutzen Knoten-Attribute als Diskriminatoren (is_intro, is_build etc.)
    #  weil PyReason Knotennamen in Regeln als Variablen behandelt.
    # =================================================================

    # R23: Intro → konservatives Volumen
    ("conservative(x) <-0 in_progression(x, p), is_intro(p)",
     "R23_conservative"),

    # R24: Build → moderate Steigerung
    ("building(x) <-0 in_progression(x, p), is_build(p)",
     "R24_building"),

    # R25: Peak → volle Intensität
    ("at_peak(x) <-0 in_progression(x, p), is_peak(p)",
     "R25_at_peak"),

    # R26: Pre-Taper → Reduktion beginnen
    ("tapering(x) <-0 in_progression(x, p), is_pretaper(p)",
     "R26_tapering"),

    # =================================================================
    #  PHASEN-TRANSITION (R27–R29)
    #  Nutzen is_general/is_supportive/is_specific als Diskriminatoren.
    # =================================================================

    # R27: Bereit für nächste Phase wenn Peak erreicht in General
    ("ready_for_next(x) <-0 in_phase(x, p), is_general(p), at_peak(x)",
     "R27_ready_general_to_supportive"),

    # R28: Bereit für Specific wenn Peak in Supportive
    ("ready_for_next(x) <-0 in_phase(x, p), is_supportive(p), at_peak(x)",
     "R28_ready_supportive_to_specific"),

    # R29: Taper-bereit wenn Pre-Taper in Specific
    ("ready_for_taper(x) <-0 in_phase(x, p), is_specific(p), tapering(x)",
     "R29_ready_for_taper"),

    # =================================================================
    #  CONSTRAINTS (R30)
    # =================================================================

    # R30: Nur benachbarte Zonen dürfen in einem Workout gemischt werden
    ("mix_allowed(z1, z2) <-0 adjacent(z1, z2)",
     "R30_mix_adjacent_only"),

    # =================================================================
    #  WORKOUT-PROGRESSION (R31–R37)
    #  Kernregel R7: Volumen → Extension → Erholung
    #  Kernregel R8: Nur eine Dimension pro Steigerungsschritt
    #
    #  PyReason aktiviert die richtige Stufe basierend auf
    #  Progressionszustand + Erfahrung.
    # =================================================================

    # R31: Intro/Konservativ → Base-Stufe (wenig Volumen, viel Pause)
    ("use_stage(s) <-0 do_workout(w), has_stage(w, s), is_base(s), conservative(x)",
     "R31_base_when_conservative"),

    # R32: Build → Volume-Stufe (mehr Wiederholungen)
    ("use_stage(s) <-0 do_workout(w), has_stage(w, s), is_volume_stage(s), building(x)",
     "R32_volume_when_building"),

    # R33: Peak → Extension-Stufe (längere Intervalle)
    ("use_stage(s) <-0 do_workout(w), has_stage(w, s), is_extension_stage(s), at_peak(x)",
     "R33_extension_when_peak"),

    # R34: Peak + Erfahren → Recovery-Stufe (kürzere Pausen)
    ("use_stage(s) <-0 do_workout(w), has_stage(w, s), is_recovery_stage(s), at_peak(x), allow_complex(x)",
     "R34_recovery_when_peak_experienced"),

    # R35: Taper → zurück auf Volume-Stufe (erhalten, nicht steigern)
    ("use_stage(s) <-0 do_workout(w), has_stage(w, s), is_volume_stage(s), tapering(x)",
     "R35_volume_when_tapering"),

    # R36: Nächste mögliche Progression anzeigen
    ("next_progression(s2) <-0 use_stage(s1), progresses_to(s1, s2)",
     "R36_next_progression"),

    # R37: Workout ist progressionsfähig (hat aktive Stufe)
    ("has_progression(w) <-0 do_workout(w), has_stage(w, s), use_stage(s)",
     "R37_has_progression"),

    # =================================================================
    #  TAPER-LOGIK (R38–R47)
    #
    #  Kernregel Taper: "Volumen senken, Intensität erhalten"
    #  10–14 Tage: letzte spezifische Einheit
    #  5–9 Tage: nur kurze Race-Pace-Berührungen
    #  2–4 Tage: nur Easy + Strides
    #  0–1 Tage: Shake-out oder Ruhe
    # =================================================================

    # R38: Athlet ist im Taper-Modus
    ("in_taper_mode(x) <-0 in_taper(x, t)",
     "R38_taper_mode"),

    # R39: Early Taper → eine Quality-Session noch erlaubt
    ("taper_allow_one_quality(x) <-0 in_taper(x, t), is_taper_early(t)",
     "R39_early_taper_one_quality"),

    # R40: Early Taper → Volumen reduzieren (20%)
    ("taper_volume_reduce_light(x) <-0 in_taper(x, t), is_taper_early(t)",
     "R40_early_taper_volume"),

    # R41: Mid Taper → nur Race-Pace-Berührungen
    ("taper_race_pace_only(x) <-0 in_taper(x, t), is_taper_mid(t)",
     "R41_mid_taper_rp_touch"),

    # R42: Mid Taper → Volumen stärker reduzieren (40%)
    ("taper_volume_reduce_medium(x) <-0 in_taper(x, t), is_taper_mid(t)",
     "R42_mid_taper_volume"),

    # R43: Late Taper → nur Easy + Strides
    ("taper_easy_only(x) <-0 in_taper(x, t), is_taper_late(t)",
     "R43_late_taper_easy_only"),

    # R44: Late Taper → Volumen stark reduzieren (60%)
    ("taper_volume_reduce_heavy(x) <-0 in_taper(x, t), is_taper_late(t)",
     "R44_late_taper_volume"),

    # R45: Race-Woche → Shake-out oder Ruhe
    ("taper_shake_out_only(x) <-0 in_taper(x, t), is_taper_race(t)",
     "R45_race_week_shake_out"),

    # R46: Race-Woche → minimales Volumen (80% Reduktion)
    ("taper_volume_reduce_max(x) <-0 in_taper(x, t), is_taper_race(t)",
     "R46_race_week_volume"),

    # R47: Im Taper → Progression blockieren (nicht steigern)
    ("block_progression(x) <-0 in_taper_mode(x)",
     "R47_taper_blocks_progression"),

    # =================================================================
    #  PACE-AKTUALISIERUNG (R48–R54)
    #
    #  Kernregel R11: Von aktueller Fitness ausgehen
    #  Kernregel R12: Paces regelmäßig aktualisieren (~4 Wochen)
    # =================================================================

    # R48: Update fällig wenn ≥4 Wochen seit letztem Update
    ("pace_update_due(x) <-0 update_overdue(x)",
     "R48_update_due"),

    # R49: Fitness-Update empfohlen wenn neues Rennergebnis vorliegt
    ("recommend_fitness_update(x) <-0 has_race_result(x)",
     "R49_fitness_update_after_race"),

    # R50: Workout-Evolution empfohlen für schnelle Verbesserer
    ("recommend_evolution(x) <-0 rapid_improver(x)",
     "R50_evolution_for_rapid"),

    # R51: Bridging empfohlen wenn Ziel-Pace gesetzt und erfahren
    ("recommend_bridging(x) <-0 has_goal_pace(x), experienced(x)",
     "R51_bridging_for_experienced"),

    # R52: Warnung bei großem Pace-Sprung (>5%)
    ("warn_large_pace_jump(x) <-0 large_improvement(x)",
     "R52_warn_large_jump"),

    # R53: Warnung bei extremem Pace-Sprung (>10%)
    ("warn_extreme_pace_jump(x) <-0 extreme_improvement(x)",
     "R53_warn_extreme_jump"),

    # R54: Alle Zonen neu kalibrieren nach Update
    ("recalibrate_zones(x) <-0 pace_update_due(x), has_race_result(x)",
     "R54_recalibrate_after_race"),
]


# =========================================================================
#  WORKOUT-BESCHREIBUNGEN UND DISTANZ-VOLUMINA
#  (Textuelle Daten — bleiben hier, da sie keine Logik sind)
# =========================================================================

WORKOUT_TEMPLATES: dict[str, dict[str, str]] = {
    "easy_run":     {"name": "Lockerer Dauerlauf", "description": "Lockerer Lauf bei 45–65% RP. Erholung und Grundlage.", "volume_default": "30–60 min"},
    "long_easy_run":   {"name": "Langer lockerer Lauf", "description": "Langer Lauf bei 85% RP. Aerobe Grundlage.", "volume_default": "60–120 min"},
    "progression_run": {"name": "Progressionslauf", "description": "Start locker, letztes Drittel bei 85–90%.", "volume_default": "50–80 min"},
    "long_fast_run":   {"name": "Langer schneller Lauf", "description": "Durchgängig bei 90% RP.", "volume_default": "40–80 min"},
    "tempo_continuous":       {"name": "Tempo-Dauerlauf", "description": "Durchgängiger Lauf bei 90% RP.", "volume_default": "20–45 min"},
    "threshold_intervals":    {"name": "Schwellenintervalle", "description": "Intervalle bei 90–95% RP mit kurzer Trabpause.", "volume_default": "4–6 × 2 km, 2 min Pause"},
    "float_recovery_workout": {"name": "Float-Recovery-Workout", "description": "Wechselkilometer: 1 km@95% + 1 km@85%.", "volume_default": "6–10 × (1 km schnell + 1 km Float)"},
    "race_pace_reps":         {"name": "Wettkampftempo-Wdh.", "description": "Intervalle bei 95–100% RP.", "volume_default": "6–8 × 1 km oder 4 × 2 km"},
    "race_pace_continuous":   {"name": "Wettkampftempo-Dauerlauf", "description": "Durchgängig bei 95–100% RP.", "volume_default": "4–8 km"},
    "specific_speed_intervals": {"name": "Spez. Tempointeralle", "description": "Intervalle bei 105% RP.", "volume_default": "5–6 × 1 km, 3 min Pause"},
    "fartlek":       {"name": "Fartlek", "description": "Fahrtspiel bei 100–108% RP.", "volume_default": "8–10 × 2 min / 1 min locker"},
    "speed_intervals": {"name": "Tempointeralle", "description": "Schnelle Intervalle bei 110% RP.", "volume_default": "10–12 × 400 m, 90 s Pause"},
    "short_reps":    {"name": "Kurze Wiederholungen", "description": "200–600 m bei 110% RP.", "volume_default": "8–12 × 200–400 m"},
    "strides":       {"name": "Steigerungsläufe", "description": "5–6 × 100 m. 2× pro Woche, ganzjährig.", "volume_default": "5–6 × 100 m"},
    "hill_sprints":  {"name": "Bergsprints", "description": "8–10 × 10 s maximal bergauf.", "volume_default": "8–10 × 10 s"},
    "race_pace_touch": {"name": "Race-Pace-Berührung", "description": "Kurze Berührung des Wettkampftempos. Intensität erhalten, Volumen minimal.", "volume_default": "2 km Einlaufen + 3 × 1 km @ 100% + 2 km Auslaufen"},
    "shake_out": {"name": "Shake-out", "description": "Kurzer lockerer Lauf mit optionalen Steigerungen. Beine lockern vor dem Rennen.", "volume_default": "20–30 min locker + 3–4 × 100 m Steigerungen"},
}

# =========================================================================
#  PROGRESSIONSSTUFEN-BESCHREIBUNGEN
#  Logik (welche Stufe aktiv) → PyReason R31–R37
#  Beschreibung (was konkret gelaufen wird) → hier
# =========================================================================

STAGE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    # race_pace_reps: Volumen → Extension → Erholung
    "rpr_base":      {"default": "4–6 × 1 km @ 100%, 3 min Pause",
                      "10k": "4 × 1 km @ 100%, 3 min Pause",
                      "half_marathon": "3 × 3 km @ 100%, 3 min Pause",
                      "marathon": "3 × 3 km @ 100%, 3 min Pause"},
    "rpr_volume":    {"default": "6–8 × 1 km @ 100%, 3 min Pause",
                      "10k": "5 × 2 km @ 100%, 3 min Pause",
                      "half_marathon": "4 × 3 km @ 100%, 3 min Pause",
                      "marathon": "5 × 3 km @ 100%, 3 min Pause"},
    "rpr_extension": {"default": "4 × 2 km @ 100%, 3 min Pause",
                      "10k": "3 × 3 km @ 100%, 3 min Pause",
                      "half_marathon": "5 × 3 km @ 100%, Float 1 km",
                      "marathon": "6 × 3 km @ 100%, Float 1 km"},
    "rpr_recovery":  {"default": "4 × 2 km @ 100%, 90 s Pause",
                      "10k": "3 × 3 km @ 100%, Float 1 km @ 85%",
                      "half_marathon": "5 × 3 km @ 100%, Float 1 km @ 85%",
                      "marathon": "6 × 3 km @ 100%, Float 1 km @ 85%"},

    # float_recovery_workout: Float-Pace steigern
    "flt_base":      {"default": "6 × (1 km@95% + 1 km Trab)"},
    "flt_volume":    {"default": "8 × (1 km@95% + 1 km@80%)"},
    "flt_extension": {"default": "6 × (1 km@95% + 1 km@85%)"},
    "flt_recovery":  {"default": "7 × (1 km@95% + 1 km@85%) → Wechselkm"},

    # tempo_continuous: Dauer steigern
    "tmp_base":      {"default": "20 min @ 90%"},
    "tmp_volume":    {"default": "30 min @ 90%"},
    "tmp_extension": {"default": "40–45 min @ 90%"},

    # specific_speed_intervals: Reps → längere Reps
    "ssi_base":      {"default": "4 × 1 km @ 105%, 3 min Pause"},
    "ssi_volume":    {"default": "6 × 1 km @ 105%, 3 min Pause"},
    "ssi_extension": {"default": "4 × 1.5 km @ 105%, 3 min Pause"},

    # speed_intervals: Mehr Reps
    "spd_base":      {"default": "8 × 400 m @ 110%, 90 s Pause"},
    "spd_volume":    {"default": "10 × 400 m @ 110%, 90 s Pause"},
    "spd_extension": {"default": "12 × 400 m @ 110%, 90 s Pause"},

    # long_fast_run: Distanz steigern
    "lfr_base":      {"default": "8–10 km @ 90%",
                      "half_marathon": "12–15 km @ 90%",
                      "marathon": "15–18 km @ 90%"},
    "lfr_volume":    {"default": "12–15 km @ 90%",
                      "half_marathon": "18–20 km @ 95%",
                      "marathon": "22–25 km progressiv (86–92%)"},
    "lfr_extension": {"default": "16–20 km @ 90%",
                      "half_marathon": "20–25 km @ 95%",
                      "marathon": "25–32 km progressiv (86–92%)"},

    # long_easy_run: Dauer steigern
    "ler_base":      {"default": "60 min @ 85%",
                      "marathon": "70–80 min @ 85%"},
    "ler_volume":    {"default": "80–90 min @ 85%",
                      "marathon": "90–110 min @ 85%"},
    "ler_extension": {"default": "100–120 min @ 85%",
                      "marathon": "120–150 min @ 85%"},
}

# Mapping: Workout → Stufen-Prefix (für Lookup)
WORKOUT_STAGE_PREFIX: dict[str, str] = {
    "race_pace_reps": "rpr",
    "float_recovery_workout": "flt",
    "tempo_continuous": "tmp",
    "specific_speed_intervals": "ssi",
    "speed_intervals": "spd",
    "long_fast_run": "lfr",
    "long_easy_run": "ler",
}


DISTANCE_VOLUME: dict[str, dict[str, str]] = {
    "800m":          {"race_pace_reps": "3 × 500 m @ 100%, 6–8 min Pause", "specific_speed_intervals": "10–12 × 200 m @ 105%", "speed_intervals": "6–8 × 300 m @ 110%", "long_easy_run": "40–60 min", "tempo_continuous": "15–20 min"},
    "1500m":         {"race_pace_reps": "6–8 × 600 m @ 95–100%, 2–3 min Pause", "specific_speed_intervals": "8 × 400 m @ 105%", "long_easy_run": "50–70 min", "tempo_continuous": "15–25 min"},
    "5k":            {"race_pace_reps": "4–6 × 1 km @ 95–100%", "specific_speed_intervals": "5–6 × 1 km @ 105%", "long_fast_run": "30–50 min @ 90%", "float_recovery_workout": "6 × (1 km@95% + 1 km@85%)"},
    "10k":           {"race_pace_reps": "5 × 2 km @ 100%", "specific_speed_intervals": "6 × 1 km @ 105%", "long_fast_run": "40–70 min @ 90%", "float_recovery_workout": "6–7 × (1 km@95% + 1 km@85%)", "race_pace_continuous": "4–7 Meilen @ 95–100%"},
    "half_marathon":  {"race_pace_reps": "5 × 3 km @ 100%, Float 1 km", "race_pace_continuous": "14–15 km @ 100%", "long_fast_run": "20–25 km @ 95%", "specific_speed_intervals": "5 × 2 km @ 105%", "tempo_continuous": "25–40 min @ 90%"},
    "marathon":      {"race_pace_reps": "6 × 3 km @ 100%, Float 1 km", "race_pace_continuous": "15–20 Meilen @ 95%", "long_fast_run": "25–32 km progressiv (86–92%)", "specific_speed_intervals": "4–5.5 Meilen @ 105%", "tempo_continuous": "10 Meilen @ 90%", "long_easy_run": "90–150 min"},
}

# Mapping von API-Distanznamen zu Graph-Knoten
DISTANCE_NODE_MAP: dict[str, str] = {
    "800m": "dist_800m", "1500m": "dist_1500m", "mile": "dist_mile",
    "3k": "dist_3k", "5k": "dist_5k", "10k": "dist_10k",
    "half_marathon": "dist_half", "marathon": "dist_marathon",
}
