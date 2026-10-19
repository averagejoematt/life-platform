"""#5058 — effort ceilings by experience tier and movement class, the within-one-point tolerance, the
ceiling-change proposal, and the replay of the 22 graded sessions.

The charter (`config/training_charter.json` `effort_ceilings`) states the class bands
(`by_movement_class`) and the lifter's tier picks the bands in force (`experience_tier`). Every RPE in
this file is read from the charter; the tolerance edge is the charter's own number, +0 and +0.5 past it.
"""

from __future__ import annotations

import json
import pathlib

from health import adherence_calc
from training import (
    ceiling_proposal,
    effort_ceilings,
    intensity_prescription,
    load_progression,
    plan_engine,
    program_structure,
    training_charter as tc,
)
from training.intensity_prescription import grade_sets, resolve_ceiling

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "effort_ceilings_5058" / "replay_graded_sessions.json"

COMPOUND = effort_ceilings.ceiling(effort_ceilings.COMPOUNDS)
LAST_ISO = effort_ceilings.ceiling(effort_ceilings.LAST_ISOLATION_SET)
TOL = effort_ceilings.tolerance_rpe()


def _sets(*rpes):
    return [{"type": "normal", "rpe": r} for r in rpes]


# ── the charter: the tier picks the class bands ──────────────────────────────────────
def test_the_tier_picks_the_class_bands_and_the_named_classes_agree_with_the_current_tier():
    c = tc.load_charter()["effort_ceilings"]
    assert "by_experience_tier" not in c, "renamed to by_movement_class (#5058)"
    tier = c["experience_tier"]["current"]
    assert tier == "advanced"
    # must-agree pair: the class bands the charter states ARE the current tier's class bands
    for key, band in c["by_movement_class"].items():
        assert c["experience_tier"][tier][key] == band, key
    bands = effort_ceilings.class_bands()
    assert bands[effort_ceilings.COMPOUNDS] == [8, 9] and bands[effort_ceilings.LAST_ISOLATION_SET] == [9, 10]
    assert bands[effort_ceilings.BACK_OFF] == [7, 8]
    assert (COMPOUND, LAST_ISO, TOL) == (9.0, 10.0, 1.0)  # the ceiling is the band's HIGH end
    log = [e for e in tc.charter_value("change_log") if "#5058" in e["by"]]
    assert len(log) == 1 and "by_movement_class" in log[0]["what"]


def test_a_different_tier_moves_every_reader_without_a_typed_number():
    real = tc.charter_value

    def intermediate(path, default=None):
        return "intermediate" if path == "effort_ceilings.experience_tier.current" else real(path, default)

    bands = effort_ceilings.class_bands(intermediate)
    want = real("effort_ceilings.experience_tier.intermediate")
    assert bands[effort_ceilings.COMPOUNDS] == want["compounds_rpe"] and bands[effort_ceilings.COMPOUNDS] != [8, 9]
    assert effort_ceilings.ceiling(effort_ceilings.COMPOUNDS, intermediate) == max(want["compounds_rpe"])


def test_load_progression_reads_the_tier_not_the_low_end():
    lim = load_progression.effort_limits()
    assert lim["experience_tier"] == "advanced"
    assert lim["compound"]["ceiling_rpe"] == COMPOUND and lim["compound"]["limit_rpe"] == COMPOUND + TOL
    assert lim["last_isolation_set"]["ceiling_rpe"] == LAST_ISO


def test_an_unreadable_charter_names_no_ceiling():
    assert effort_ceilings.class_bands(lambda p, d=None: d) == {}
    assert effort_ceilings.ceiling(effort_ceilings.COMPOUNDS, lambda p, d=None: d) is None


# ── the generator writes each class's ceiling into the cue ───────────────────────────
def test_each_class_cue_names_its_charter_band_and_reads_back_as_its_ceiling():
    e = program_structure.EXPOSURES
    lo, hi = effort_ceilings.class_bands()[effort_ceilings.COMPOUNDS]
    blo, bhi = effort_ceilings.class_bands()[effort_ceilings.BACK_OFF]
    llo, lhi = effort_ceilings.class_bands()[effort_ceilings.LAST_ISOLATION_SET]
    # compound top set 8-9, back-offs 7-8 (the rep scheme's -10 %)
    assert f"top set of 4–6 @ RPE {lo:g}–{hi:g}" in e["heavy"]["cue"] and f"@ RPE {blo:g}–{bhi:g}" in e["heavy"]["cue"]
    assert resolve_ceiling("squat_barbell", e["heavy"]["cue"]) == {"rpe": COMPOUND, "basis": "exercise_notes:rpe"}
    for intensity in ("moderate", "volume"):
        assert f"@ RPE {lo:g}–{hi:g}" in e[intensity]["cue"]
        assert resolve_ceiling("x", e[intensity]["cue"])["rpe"] == COMPOUND
    # an isolation movement: earlier sets at the compounds band, the LAST set at the isolation band
    acc = resolve_ceiling("db_curl", e["accessory"]["cue"])
    assert f"last set RPE {llo:g}–{lhi:g}" in e["accessory"]["cue"]
    assert acc == {"rpe": COMPOUND, "basis": "exercise_notes:rpe", "last_set_rpe": LAST_ISO}
    for spec in e.values():
        assert len(spec["cue"]) <= 150 and "tier" in spec["cue"], spec["cue"]  # short, and it says where the number came from
    # the heavy top set's own `rpe` field is the band too
    rx = program_structure.session_prescription_for_role("upper_heavy")
    top = next(x for x in rx["exposures"] if x["intensity"] == "heavy")["sets"][0]
    assert top["kind"] == "top" and top["rpe"] == [lo, hi]


def test_a_note_naming_one_last_set_ceiling_reads_as_before():
    """Backward compatible: "2-3 RIR on the last set" alone is still the movement's ceiling (no split)."""
    assert resolve_ceiling("x", "2-3 RIR on the last set") == {"rpe": 8.0, "basis": "exercise_notes:rir"}
    assert resolve_ceiling("x", "RPE 8.5 cap. Last set RPE 9.5.")["last_set_rpe"] == 9.5
    assert intensity_prescription.read_ceiling("RPE 8.5 cap") == (8.5, "rpe")  # the split never cuts a decimal


# ── grade_sets: within +tolerance is never a breach ───────────────────────────────────
def test_the_tolerance_edge_plus_one_is_within_plus_one_and_a_half_is_a_breach():
    edge = grade_sets(8.0, _sets(8.0, 8.0 + TOL), tolerance_rpe=TOL)
    assert (edge["sets_over_ceiling"], edge["sets_within_tolerance"], edge["sets_beat_ceiling"]) == (0, 1, 1)
    assert edge["pct_within_ceiling"] == 100.0 and edge["max_overage"] == TOL
    past = grade_sets(8.0, _sets(8.0, 8.0 + TOL + 0.5), tolerance_rpe=TOL)
    assert (past["sets_over_ceiling"], past["sets_within_tolerance"], past["sets_beat_ceiling"]) == (1, 0, 1)
    assert past["pct_within_ceiling"] == 50.0
    strict = grade_sets(8.0, _sets(8.0, 8.0 + TOL))  # no tolerance passed: the pure strict compare
    assert strict["sets_over_ceiling"] == 1


def test_the_last_isolation_set_is_graded_against_its_own_band():
    g = grade_sets(COMPOUND, _sets(COMPOUND, COMPOUND, LAST_ISO), tolerance_rpe=0, last_set_ceiling=LAST_ISO)
    assert g["sets_beat_ceiling"] == 0 and g["last_set_ceiling_rpe"] == LAST_ISO
    early = grade_sets(COMPOUND, _sets(LAST_ISO, COMPOUND), tolerance_rpe=0, last_set_ceiling=LAST_ISO)
    assert early["sets_over_ceiling"] == 1  # the same RPE on an EARLIER set reads the compounds band


# ── the ceiling-change proposal ──────────────────────────────────────────────────────
def _row(date, graded, beat, cls="compound", key="lat_pulldown"):
    return {
        "date": date,
        "adherence": {
            "status": "matched",
            "movements": [
                {
                    "movement_key": key,
                    "intensity": {
                        "status": "graded",
                        "ceiling_rpe": 8,
                        "sets_graded": graded,
                        "sets_beat_ceiling": beat,
                        "movement_class": cls,
                    },
                }
            ],
        },
    }


def test_the_proposal_fires_when_more_than_half_the_sets_beat_the_ceiling_two_weeks_running():
    rule = effort_ceilings.proposal_rule()
    assert (rule["share_of_sets"], rule["weeks_running"]) == (0.5, 2)
    rows = [_row("2026-10-16", 10, 6), _row("2026-10-09", 10, 7)]
    out = ceiling_proposal.compute(rows, "2026-10-18")
    assert out["state"] == "proposed" and out["auto_applied"] is False and "owner ruling" in out["applies"]
    (p,) = out["proposals"]
    assert p["movement_class"] == "compound" and p["charter_band"] == [8, 9] and p["experience_tier"] == "advanced"
    assert "70% and 60%" in p["text"] and "Nothing changes until you rule" in p["text"]
    assert out["charter_version"] == tc.charter_version()


def test_the_proposal_does_not_fire_at_exactly_half_or_on_one_week():
    at_half = ceiling_proposal.compute([_row("2026-10-16", 10, 6), _row("2026-10-09", 10, 5)], "2026-10-18")
    assert at_half["state"] == "none" and not at_half["proposals"]  # "more than 50 %": 50 % is not more
    one_week = ceiling_proposal.compute([_row("2026-10-16", 10, 9)], "2026-10-18")
    assert one_week["state"] == "insufficient" and not one_week["proposals"]  # an unmeasured week is not a share of zero
    other_class = ceiling_proposal.compute([_row("2026-10-16", 10, 9, "isolation"), _row("2026-10-09", 10, 9)], "2026-10-18")
    assert (
        other_class["state"] == "insufficient" and not other_class["proposals"]
    )  # two weeks of DIFFERENT classes are not two weeks running


def test_a_pre_5058_row_reads_its_strict_over_count_and_progressed_sets_stay_out():
    old = {
        "date": "2026-10-16",
        "adherence": {
            "status": "matched",
            "movements": [
                {
                    "movement_key": "lat_pulldown",
                    "intensity": {"status": "graded", "ceiling_rpe": 8, "sets_graded": 4, "sets_over_ceiling": 3, "sets_progressed": 1},
                }
            ],
        },
    }  # noqa: E501
    out = ceiling_proposal.compute(
        [old, _row("2026-10-09", 10, 8)],
        "2026-10-18",
        catalog_movements={"lat_pulldown": {"anchor_family": "vertical_pull", "title": "Lat Pulldown (Cable)"}},
    )
    assert out["by_class"]["compound"]["weeks"][0] == {**out["by_class"]["compound"]["weeks"][0], "sets_graded": 3, "sets_beat_ceiling": 3}
    assert out["state"] == "proposed"


def test_the_plan_carries_the_proposal_and_an_unread_window_is_unknown():
    common = dict(date="2026-10-19", catalog_movements={})
    unread = plan_engine.constraint_block(**common)
    assert unread["ceiling_change_proposal"]["state"] == "unknown" and unread["ceiling_change_proposal"]["auto_applied"] is False
    assert unread["progression"]["effort_limits"]["experience_tier"] == "advanced"
    read = plan_engine.constraint_block(**common, hevy_workouts_prescription_window=[_row("2026-10-16", 10, 6), _row("2026-10-09", 10, 7)])
    assert read["ceiling_change_proposal"]["state"] == "proposed"


# ── the replay: the 22 graded sessions, before and after ─────────────────────────────
def _replay(mode: str) -> list[tuple[str, dict]]:
    fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    out = []
    for s in fx["sessions"]:
        movements = []
        for m in s["movements"]:
            if mode == "before":  # the grader as it ran: the stored ceiling, strict
                g = grade_sets(m["ceiling_rpe"], m["sets"])
            elif mode == "tolerance":  # the same prescriptions, the charter's +1
                g = grade_sets(m["ceiling_rpe"], m["sets"], tolerance_rpe=TOL)
            else:  # what the generator writes now: the tier's class ceilings + the tolerance
                last = LAST_ISO if m["movement_class"] == "isolation" else None
                g = grade_sets(COMPOUND if m["ceiling_rpe"] is not None else None, m["sets"], tolerance_rpe=TOL, last_set_ceiling=last)
            g["basis"] = m["basis"]
            movements.append({"movement_key": m["movement_key"], "intensity": g})
        rollup = adherence_calc._intensity_rollup(movements)
        out.append((s, {"verdict": adherence_calc._as_prescribed(s["sets_pct"], rollup, movements)["verdict"], **rollup}))
    return out


def test_the_replay_fixture_reproduces_every_stored_verdict_before_5058():
    """22 sessions graded `as_prescribed` yes/no with a graded intensity dimension, 2026-09-16..10-18, read
    read-only from DynamoDB. The strict grader over the fixture reproduces each stored verdict and each
    session's stored breach count — the fixture is the wire, not a paraphrase."""
    before = _replay("before")
    assert len(before) == 22
    assert [(s["date"], r["verdict"], r["sets_over_ceiling"]) for s, r in before] == [
        (s["date"], s["stored_verdict"], s["stored_sets_over_ceiling"]) for s, _ in before
    ]
    assert sum(r["verdict"] == "yes" for _s, r in before) == 2  # 20 of 22 `no`


def test_the_replay_as_prescribed_rate_before_and_after():
    """Before: 2 of 22 as prescribed, 129 breach sets of 383 graded. The charter's +1 on the SAME
    prescriptions: 8 of 22, 29 breaches (the 100 sets within one point are within_tolerance). At the
    tier's class ceilings (what the generator now writes): 16 of 22 — the six that are not `yes` fail on
    SET COMPLETION (five) or an unlogged RPE on a movement with its own ceiling (one), never on effort."""
    rates = {mode: sum(r["verdict"] == "yes" for _s, r in _replay(mode)) for mode in ("before", "tolerance", "charter")}
    assert rates == {"before": 2, "tolerance": 8, "charter": 16}
    breaches = {mode: sum(r["sets_over_ceiling"] for _s, r in _replay(mode)) for mode in ("before", "tolerance", "charter")}
    assert breaches == {"before": 129, "tolerance": 29, "charter": 0}
    for s, r in _replay("charter"):
        if r["verdict"] != "yes":
            assert s["sets_pct"] < 100.0 or r["verdict"] == "unknown", (s["date"], r)


def test_the_replay_never_loses_a_breach_past_the_tolerance():
    """No session that had a set more than +1 over its own ceiling reads `yes` with the tolerance applied."""
    for (s, before), (_s, after) in zip(_replay("before"), _replay("tolerance")):
        if after["verdict"] == "yes":
            assert before["max_overage"] is None or before["max_overage"] <= TOL, s["date"]
