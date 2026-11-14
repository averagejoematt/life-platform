"""live_settings.py — THE one settings table of the live programming engine (#5861, fix round 9: consolidation).

Every value the live engine reads that the owner may change, and every labelled heuristic of the consolidated rules, is ONE
row here: its value, where it came from (the owner's ruling, or "heuristic" with its basis) and the metric a block retro
re-tunes it on. Fix rounds 1-8 kept five per-round default dicts (merged at read time) and ~25 settings, most of them dead
alternatives the owner had already ruled out; round 9 keeps only the knobs with a live choice behind them.

  * SETTINGS — library-carried (`config/exercise_library.json` `programming_settings`, written by
    `deploy/build_exercise_library.py` from this table). A value on disk overrides the default; nothing else is read.
  * HEURISTICS — code constants of the consolidated rules (progression, volume, novelty, time). Labelled, explainable,
    configurable here (owner ruling 18); never presented as measured.

Nothing here runs in shadow: the readers are live-only (tests/test_no_live_change_5861_l6.py). The tables in
docs/coaching/ENGINE_ARCHITECTURE.md are GENERATED from this module (`settings_table_markdown`) and held to it by
tests/test_consolidation_5861.py."""

from __future__ import annotations

from typing import Any

ISSUE = "#5861"
SETTINGS_KEY = "programming_settings"

SETTINGS: dict[str, dict[str, Any]] = {
    "session_cap_includes_cardio": {
        "default": True,
        "ruling": "owner ruling 1 (2026-11-13)",
        "what": "lifting and gym cardio share the 75-minute cap; the conditioning dose takes only the minutes lifting leaves "
        "(no strength work is cut for cardio). False: the cap is lifting only and the cardio block sits apart",
    },
    "press_sets": {
        "default": 3,
        "ruling": "owner ruling 6 (2026-11-13)",
        "what": "overhead-press working sets a week (2 or 3), taken from the side-delt (lateral raise) sets",
    },
    "priority_muscles": {
        "default": ["chest", "quadriceps"],
        "ruling": "owner ruling 9 (2026-11-13)",
        "what": "muscles planned toward the middle of MEV-MAV (never under MEV in a normal week) and trimmed last for time",
    },
    "abs_direct_sets_per_week": {
        "default": 4,
        "ruling": "owner ruling #8 (fix round 8)",
        "what": "challenging DIRECT ab sets a week, spread over the mornings; indirect trunk loading never counts; halved on a "
        "short or high-fatigue week",
    },
    "hard_conditioning_doses": {
        "default": 1,
        "ruling": "owner follow-up ruling (2026-11-13)",
        "what": "hard conditioning blocks a week (the week's conditioning host takes the first; 2 adds `live_rulings.SECOND_HOST`)",
    },
    "rate_ceiling_pct_bw": {
        "default": 1.0,
        "ruling": "owner ruling 11 (2026-11-13)",
        "what": "the ADVISORY upper planning reference for weekly loss, % of current bodyweight; never applied to a target",
    },
    "sequence_rule_from": {
        "default": None,
        "ruling": "owner ruling #4 (fix round 8)",
        "what": "the first Monday the week rules judge; None = the Monday after the library's approval; earlier history is kept, "
        "never re-sequenced",
    },
}

H = "heuristic"
HEURISTICS: dict[str, dict[str, Any]] = {
    # ── progression (live_load) ──
    "history_days": {
        "value": 56,
        "group": "progression",
        "basis": "a same-role exposure in the last 8 weeks is a load reference; older, the engine's own ramp load stands",
        "retune": "block retro: how often a lift returns after >8 weeks",
    },
    "below_floor_exposures": {
        "value": 2,
        "group": "progression",
        "basis": "fix round 10: the top set under the rep range's floor in two same-role exposures running steps the lift down "
        "(at least step_down_pct; as far as the last exposure says reaches the floor with 2 in reserve) — nothing blocks it (a slump, strain, pain or first-back hold stops only a step up); RPE plays no part, so "
        "missing or always-10 RPE never moves a load down on its own",
        "retune": "block retro: exposures spent under the floor; step-downs followed by a new best within 3 weeks (too eager)",
    },
    "step_down_pct": {
        "value": 5,
        "group": "progression",
        "basis": "the smallest step-down: 5% under the last top load (one implement step on most lifts); a larger step only "
        "when the last exposure says 5% still leaves him under the floor",
        "retune": "block retro: e1RM a month after each step-down",
    },
    "implausible_rpe": {
        "value": 9.5,
        "group": "progression",
        "basis": "RPE missing on every set, or >= 9.5 on every set, is EFFORT UNKNOWN: the step up rides on reps alone; a load "
        "moves down only on reps under the floor, never on effort",
        "retune": "block retro: RPE calibration report (rpe_calibration)",
    },
    "slump_anchors": {
        "value": 4,
        "group": "progression",
        "basis": "four or more anchors declining together (or, in a deficit, at least half of them) is systemic — sleep, recovery "
        "or the deficit, not the lifts: no load steps UP and non-priority accessory volume comes down about a third (a lift under its "
        "floor still steps down)",
        "retune": "block retro: anchor e1RM across the block vs sleep and loss rate",
    },
    "decline_pct": {
        "value": 0.02,
        "group": "progression",
        "basis": "an anchor is DECLINING when its same-role e1RM fell 2%+ across its latest same-role exposures (newest vs two back) with no recovery between "
        "(a level under an old best is not a decline: the one-rep-short lifter holds steady)",
        "retune": "block retro: slump calls vs the next block's anchor e1RM",
    },
    "slump_accessory_cut": {
        "value": 0.34,
        "group": "progression",
        "basis": "the slump's volume answer: about a third of each accessory's working sets (never under 2); anchors keep theirs",
        "retune": "block retro: recovery markers in the weeks after a slump hold",
    },
    "second_lift_band": {
        "value": [7, 8],
        "group": "progression",
        "basis": "owner ruling 5: squat and deadlift never both maximal in one session; the lift that does not lead runs one band "
        "lower, loaded from its own same-role e1RM at that band",
        "retune": "block retro: both lifts' e1RM trend under alternation",
    },
    # ── novelty (live_load) ──
    "familiar_days": {
        "value": 56,
        "group": "novelty",
        "basis": "a movement pattern logged in the last ~8 weeks is familiar (a biomechanically similar swap included): normal "
        "effort, no re-entry cap",
        "retune": "block retro: first-exposure RPE vs the cap",
    },
    "new_pattern_rpe": {
        "value": 7,
        "group": "novelty",
        "basis": "a NEW pattern runs one exposure at RPE <= 7 (technique, soreness); then normal effort",
        "retune": "block retro: soreness / discomfort notes after a new pattern",
    },
    "layoff_days": {
        "value": 10,
        "group": "novelty",
        "basis": "owner ruling #10 (fix round 8): after 10+ days with no session, each lift's FIRST session back runs at RPE 8 at "
        "its last same-role load, no step; normal progression from the next exposure",
        "retune": "block retro: second-session performance after a layoff",
    },
    "first_back_rpe": {"value": 8, "group": "novelty", "basis": "see layoff_days", "retune": "see layoff_days"},
    # ── volume (live_volume) ──
    "hard_rpe": {
        "value": 8,
        "group": "volume",
        "basis": "a working set prescribed at RPE >= 8 (the top of its effort line) is a hard set; the ONE counter",
        "retune": "block retro: logged RPE of prescribed hard sets",
    },
    "secondary_credit": {
        "value": 0.5,
        "group": "volume",
        "basis": "a lift's secondary muscle takes half a set (the fatigue model's convention)",
        "retune": "none (convention)",
    },
    "priority_aim": {
        "value": 0.25,
        "group": "volume",
        "basis": "a priority muscle aims a quarter of the way from MEV to MAV (chest and quadriceps 8 -> 10): more than the "
        "minimum, never mechanical volume maximisation (ruling 9)",
        "retune": "block retro: priority muscles' anchor progression",
    },
    "slot_max_sets": {
        "value": 3,
        "group": "volume",
        "basis": "an accessory slot takes at most 3 working sets; 4+ in one slot is junk volume",
        "retune": "none",
    },
    "slot_min_sets": {
        "value": 2,
        "group": "volume",
        "basis": "an accessory or anchor never runs one working set: drop, don't shave",
        "retune": "none",
    },
    "delt_heads": {
        "value": {"side_delts": 6, "rear_delts": 4},
        "group": "volume",
        "basis": "owner ruling #9: each delt head assessed apart, direct + indirect; the side delt (no compound trains it much) "
        "aims at 6 hard sets, the rear at 4",
        "retune": "block retro: lateral-raise and rear-delt progression",
    },
    "delt_credit": {
        "value": {
            "horizontal_press": {"front_delts": 0.5},
            "vertical_press": {"front_delts": 1.0, "side_delts": 0.5},
            "horizontal_pull": {"rear_delts": 0.5},
        },
        "group": "volume",
        "basis": "indirect delt-head credit by library pattern: pressing -> front (and, overhead, half a side), rowing -> rear "
        "(practitioner consensus; explicit so it can be argued with)",
        "retune": "none (convention)",
    },
    "short_week_floor": {
        "value": 3,
        "group": "volume",
        "basis": "a 1-3 morning week holds each priority muscle and each major pattern at maintenance: MV x mornings / 3 hard "
        "sets (at least 2-3), full-body mornings of 4-6 movements at 2-3 sets — never a 1-set anchor",
        "retune": "block retro: anchor e1RM after a short week",
    },
    "time_cap_minutes": {
        "value": 75,
        "group": "time",
        "basis": "the owner's 75-minute morning, warm-ups included (#5799 time model, 99 s a set measured)",
        "retune": "the #5799 measured set time",
    },
}

for _row in HEURISTICS.values():
    _row["label"] = H  # ruling 18: every row a labelled heuristic

TRIM_ORDER: tuple[str, ...] = ("accessory_backoff", "anchor_backoff", "priority_last_set")
"""THE one time fit's order (fix round 9): non-priority accessory back-off sets, then non-priority anchor back-offs, then a
priority muscle's last sets; never under 2 working sets, an accessory left at 2 is dropped whole only after every back-off is
gone. Read by `live_volume.time_fit`."""


def settings(lib: dict[str, Any] | None) -> dict[str, Any]:
    """The library's programming settings over SETTINGS' defaults (a missing key reads its default; an unknown key is ignored)."""
    got = (lib or {}).get(SETTINGS_KEY) or {}
    return {k: got.get(k, row["default"]) for k, row in SETTINGS.items()}


def value(name: str) -> Any:
    """One heuristic's value."""
    return HEURISTICS[name]["value"]


def defaults() -> dict[str, Any]:
    """{setting: default} — what the library builder writes."""
    return {k: row["default"] for k, row in SETTINGS.items()}


def settings_table_markdown() -> str:
    """The generated settings + heuristics tables (docs/coaching/ENGINE_ARCHITECTURE.md, between the GENERATED markers)."""
    out = ["| Setting | Default | Provenance | What it does |", "|---|---|---|---|"]
    for k, row in SETTINGS.items():
        out.append(f"| `{k}` | `{row['default']!r}` | {row['ruling']} | {row['what']} |")
    out += ["", "| Heuristic | Value | Rule | Basis | Re-tuned on |", "|---|---|---|---|---|"]
    for k, row in HEURISTICS.items():
        out.append(f"| `{k}` | `{row['value']!r}` | {row['group']} | {row['basis']} | {row['retune']} |")
    out += ["", f"Time-fit order: {' -> '.join(TRIM_ORDER)}."]
    return "\n".join(out)
