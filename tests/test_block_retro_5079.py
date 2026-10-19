"""tests/test_block_retro_5079.py — the /training-review block retro (#5079, epic #5051).

The contract test for `.claude/skills/training-review/SKILL.md` and the deterministic helper
`lambdas/training/block_retro.py`, on one fixture block (six May-tracker weeks, six PANEL# grades, the four
#5089 predictions as `scripts/register_charter_predictions.py` builds them, the counts the skill supplies):

  1. THE SCORECARD IS THE REVIEW'S: thirteen rows (the charter's `calibration.block_retro.scorecard_rows`), each
     with a scale baseline grade, inputs the evidence actually carries and rules the module knows; every
     `panel_mean` criterion exists in config/panel_rubric.json; the scale refines the rubric's letters.
  2. REPRODUCIBLE: the same fixture gives the same evidence, code scores, movers, fixes and predictions.
  3. THE GRADE: code + the panel median combine per the rule; movers against the baseline, then the last retro;
     every graded row below B is a fix; the reference row is carried (and raises no fix) in a block with no
     interruption; an ungraded row carries its last grade and says so.
  4. THE PANEL RE-GRADE: one call per seat on `charter.retro` with the charter block cached; a failed seat is
     named, never filled in; a paused budget calls nothing.
  5. THE PREDICTIONS: graded by their own measurement block once grade_by has passed, never before.
  6. THE ROW + THE DOC: RETRO#<block_end> on training_constraints (owner-only tier), the charter version stamped;
     nothing in lambdas/web or lambdas/emails imports the module.
  7. THE SKILL: frontmatter, the charter (never a copied target), the route, the owner-only stores, the private
     doc tab, no web fetch of the doc.

No live AI call and no AWS: the panel transport is a replay; the charter is the bundled file.
"""

# premerge-gate: #5079: os.walk sweep of lambdas/web/ and lambdas/emails/ — no published-surface module names the owner-only block retro

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))

import register_charter_predictions as rcp  # noqa: E402
from training import (
    block_retro as br,  # noqa: E402
    panel_rubric,  # noqa: E402
    training_charter as tc,  # noqa: E402
)

SKILL = _REPO / ".claude" / "skills" / "training-review" / "SKILL.md"
BLOCK_END = "2026-12-06"
SUNDAYS = ["2026-10-25", "2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22", "2026-11-29", "2026-12-06"]


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _scorecard():
    sc = br.load_scorecard()
    assert sc is not None, "config/training_scorecard.json unreadable"
    return sc


def _may_row(sunday: str, i: int) -> dict:
    from common.pacific_time import shift_day_key

    pos = ["in", "in", "below", "in", "in", "above", "in"][i]
    rate = {"in": 3.2, "below": 2.4, "above": 3.9}[pos]
    measured = {"state": "measured"}
    return {
        "week_start": shift_day_key(sunday, -6),
        "week_end": sunday,
        "weight": {
            "band_position_week": pos,
            "rate_week": {**measured, "value": rate, "counted": True},
            "rate_4wk": {**measured, "value": 3.1},
        },
        "waist": {**measured, "value": {"waist_navel_in": 40.0}, "date": sunday} if i in (2, 4, 6) else {"state": "absent"},
        "steps": {**measured, "days_measured": 7, "days_at_floor": 6 if i % 2 else 7, "days_at_target": 3},
        "anchors": {
            "anchors": {
                "squat": {**measured, "down": False, "tripped": False},
                "bench": {**measured, "down": i == 6, "tripped": False},
                "row": {**measured, "down": False, "tripped": i == 3},
                "press": {**measured, "down": False, "tripped": False},
            }
        },
        "fitness_tests": {"state": "absent"},
    }


def _panel_row(sunday: str, i: int) -> dict:
    rubric = panel_rubric.load_rubric()
    seats = {
        s: {"criteria": {c["id"]: {"score": 6.0 if c["id"] in ("cardio_dosed", "double_progression") else 8.5} for c in spec["criteria"]}}
        for s, spec in rubric["seats"].items()
    }
    return {"week_end": sunday, "overall_score": 8.1, "degraded": i == 1, "seats": seats}


SUPPLIED = {
    "sessions": {"logged": 28, "distinct_movements": 31},
    "sleep": {"nights": 42, "mean_hours": 7.4, "consistency": 0.82},
    "progression": {"steps_taken": 9, "step_due": 3, "stalls": 1},
    "cardio": {"conditioning_sessions": 5},
    "planning": {"custom_departures": 2, "committed_plans": 28},
    "anchor_e1rm": {"squat": {"baseline": 300, "current": 315}, "bench": {"baseline": 230, "current": 240}},
    "accessory_stalls": {"lateral raise": {"scored": True, "stall_runs": 0}, "face pull": {"scored": True, "stall_runs": 1}},
}


def _fixture():
    may = [_may_row(s, i) for i, s in enumerate(SUNDAYS)]
    panel = [_panel_row(s, i) for i, s in enumerate(SUNDAYS[1:])]
    return may, panel


def _replay(scores: dict | None = None, fail_seat: str | None = None):
    calls = []

    def call(body):
        calls.append(body)
        seat = body["system"][-1]["text"].rsplit("YOUR SEAT: ", 1)[1].strip()
        if seat == fail_seat:
            raise RuntimeError("seat transport down")
        rows = {r["id"]: {"score": (scores or {}).get(r["id"], 7), "why": f"{seat} read the row"} for r in _scorecard()["rows"]}
        return {"content": [{"type": "text", "text": json.dumps({"rows": rows, "concession_held": True})}], "usage": {"input_tokens": 10}}

    return call, calls


def _run(**kw):
    may, panel = _fixture()
    call, calls = _replay(**kw)
    out = br.run(BLOCK_END, may_rows=may, panel_rows=panel, predictions=rcp.build_records(), supplied=SUPPLIED, call=call)
    return out, calls


# ── 1. the scorecard ──────────────────────────────────────────────────────────────────────
def test_the_scorecard_is_the_reviews_thirteen_rows_on_a_scale_that_refines_the_rubric():
    sc = _scorecard()
    rubric = panel_rubric.load_rubric()
    problems = []
    if len(sc["rows"]) != tc.charter_value("calibration.block_retro.scorecard_rows"):
        problems.append(f"{len(sc['rows'])} rows vs the charter's calibration.block_retro.scorecard_rows")
    if len({r["id"] for r in sc["rows"]}) != len(sc["rows"]):
        problems.append("duplicate row ids")
    evidence = br.assemble_evidence(br.block_window(BLOCK_END))
    crit_ids = {f"{s}.{c['id']}" for s, spec in rubric["seats"].items() for c in spec["criteria"]}
    for r in sc["rows"]:
        if br.letter_rank(r.get("baseline_grade"), sc) is None:
            problems.append(f"{r['id']}: baseline {r.get('baseline_grade')!r} is not on the scale")
        if r.get("fix_route") not in ("issue", "charter"):
            problems.append(f"{r['id']}: fix_route {r.get('fix_route')!r}")
        for k in r["inputs"] + [x for rule in r["code_rules"] for x in (rule.get("numerator"), rule.get("denominator")) if x]:
            sec, _, key = k.partition(".")
            if key not in (evidence.get(sec) or {}):
                problems.append(f"{r['id']}: input {k} is not an evidence key")
        for rule in r["code_rules"]:
            if rule["kind"] not in br.RULES:
                problems.append(f"{r['id']}: rule kind {rule['kind']}")
            problems += [f"{r['id']}: {c} is not a panel rubric criterion" for c in rule.get("criteria", []) if c not in crit_ids]
    # The refinement: every score's family letter is the rubric's letter for the same score.
    for tenth in range(0, 101):
        s = tenth / 10
        mine, theirs = br.letter_for(s, sc), panel_rubric.letter_for(s, rubric)
        family = mine if mine in ("A", "A-", "B+") else mine.rstrip("+-")
        if family != theirs:
            problems.append(f"score {s}: scorecard {mine} vs rubric {theirs}")
    assert not problems, problems


def test_the_baseline_carries_the_2026_10_18_grades_and_the_neutral_reference_row():
    sc = _scorecard()
    base = {r["id"]: r["baseline_grade"] for r in sc["rows"]}
    assert sc["baseline"]["date"] == "2026-10-18"
    assert base == {
        "outcome_weight_body_comp": "A",
        "strength_outcome": "A-",
        "consistency": "A",
        "sleep": "A-",
        "program_structure": "B+",
        "walking": "B",
        "exercise_selection_variety": "C",
        "fatigue_management": "C",
        "response_reference_event": "C+",
        "measurement": "C",
        "planning_loop": "C+",
        "cardio_programming": "D+",
        "engine_progression_logic": "D",
    }
    ref = next(r for r in sc["rows"] if r["id"] == "response_reference_event")
    assert ref["reference_only"] is True


# ── 2 + 3. reproducible, and the grade ────────────────────────────────────────────────────
def test_the_retro_is_reproducible_and_grades_every_row_with_its_evidence():
    a, calls = _run()
    b, _ = _run()
    strip = lambda r: {k: r[k] for k in ("evidence", "graded", "predictions")}  # noqa: E731
    assert json.dumps(strip(a), sort_keys=True, default=str) == json.dumps(strip(b), sort_keys=True, default=str)
    rows = a["graded"]["rows"]
    assert a["window"] == {"start": "2026-10-26", "end": BLOCK_END, "weeks": tc.charter_value("rotation.anchors_fixed_weeks")}
    # walking: 6 weeks x 7 measured days, floor met 7,6,7,6,7,6 (weeks 1..6) -> 39/42.
    assert rows["walking"]["code_rules"][0]["evidence"].endswith("= 39/42")
    assert rows["walking"]["code_score"] == round(10 * 39 / 42, 2)
    # weight: in the block (weeks ending 11-01..12-06) positions in, below, in, in, above, in -> 4/6.
    assert rows["outcome_weight_body_comp"]["code_score"] == round(10 * 4 / 6, 2)
    # anchors: 4 measured; bench down at the end, row tripped in one week -> 2 held.
    assert rows["strength_outcome"]["code_score"] == 5.0
    # consistency: 28 logged of lifting_days_per_wk x 6 planned.
    planned = tc.charter_value("split.lifting_days_per_wk") * 6
    assert rows["consistency"]["code_score"] == round(10 * min(1, 28 / planned), 2)
    # sleep has no code rule: the panel median alone.
    assert rows["sleep"]["code_score"] is None and rows["sleep"]["score"] == 7
    # every row: code + median per the rule, a letter, and a reason from every seat.
    for rid, r in rows.items():
        parts = [x for x in (r["code_score"], r["panel_median"]) if x is not None]
        assert r["score"] == round(sum(parts) / len(parts), 2), rid
        assert len(r["seat_reasons"]) == len(br.seats()), rid
    assert len(calls) == len(br.seats()) == len(tc.charter_value("concession_ledger"))


def test_movers_are_named_against_the_baseline_then_the_last_retro_and_low_grades_are_fixes():
    sc = _scorecard()
    first, _ = _run()
    g = first["graded"]
    assert g["compared_with"] == "baseline 2026-10-18"
    moved = {m["row"] for m in g["movers"]}
    assert moved == {rid for rid, r in g["rows"].items() if r["letter"] != r["prior_letter"]}
    assert all(m["change"] for m in g["movers"])
    graded_low = {rid for rid, r in g["rows"].items() if r["state"] == "graded" and br.below_fix_line(r["letter"], sc)}
    assert {f["row"] for f in g["fixes"]} == graded_low and graded_low
    # The reference row: no interruption in the block -> carried, never a fix.
    ref = g["rows"]["response_reference_event"]
    assert ref["state"] == "reference_carried" and ref["letter"] == "C+"
    assert "response_reference_event" not in {f["row"] for f in g["fixes"]}
    # The next retro compares with this one, not with the baseline.
    second = br.grade(sc, first["evidence"], br.code_scores(sc, first["evidence"]), first["panel"], prior=br.retro_item(first))
    assert second["compared_with"] == f"retro {BLOCK_END}" and second["movers"] == []


def test_an_interruption_grades_the_reference_row_and_an_unmeasured_row_carries():
    sc = _scorecard()
    may, panel = _fixture()
    window = br.block_window(BLOCK_END)
    evidence = br.assemble_evidence(
        window, may_rows=may, panel_rows=panel, disruption_records=[{"start_date": "2026-11-10", "until": "2026-11-14"}]
    )
    codes = br.code_scores(sc, evidence)
    g = br.grade(sc, evidence, codes, {"seats": {}})
    assert g["rows"]["response_reference_event"]["state"] == "carried"  # no code, no panel -> carried, said so
    assert "sleep" in g["ungraded"] and g["rows"]["sleep"]["letter"] == "A-"
    panel_out = br.panel_regrade(sc, codes, window, call=_replay(scores={"response_reference_event": 5})[0])
    g2 = br.grade(sc, evidence, codes, panel_out)
    assert g2["rows"]["response_reference_event"]["state"] == "graded"
    assert "response_reference_event" in {f["row"] for f in g2["fixes"]}


def test_an_override_needs_a_letter_on_the_scale_and_a_reason():
    sc = _scorecard()
    out, _ = _run()
    with pytest.raises(ValueError):
        br.apply_overrides(copy.deepcopy(out["graded"]), {"walking": {"letter": "A"}}, sc)
    with pytest.raises(ValueError):
        br.apply_overrides(copy.deepcopy(out["graded"]), {"walking": {"letter": "Z", "reason": "x"}}, sc)
    g = br.apply_overrides(
        copy.deepcopy(out["graded"]), {"cardio_programming": {"letter": "B", "reason": "the owner logged rides off-platform"}}, sc
    )
    row = g["rows"]["cardio_programming"]
    assert row["letter"] == "B" and row["override"]["reason"] and "cardio_programming" not in {f["row"] for f in g["fixes"]}


# ── 4. the panel re-grade ─────────────────────────────────────────────────────────────────
def test_the_panel_regrade_rides_the_retro_route_with_the_charter_cached_and_names_a_failed_seat():
    sc = _scorecard()
    may, panel = _fixture()
    window = br.block_window(BLOCK_END)
    codes = br.code_scores(sc, br.assemble_evidence(window, may_rows=may, panel_rows=panel))
    seat = br.seats()[0]
    call, calls = _replay(fail_seat=seat)
    out = br.panel_regrade(sc, codes, window, call=call)
    assert out["route"] == "charter.retro" and out["status"] == "partial"
    assert out["seats"][seat]["status"] == "error" and out["seats"][seat]["rows"] == {}
    first = calls[0]["system"]
    assert first[0]["text"] == tc.prompt_prefix(published=False) and first[0]["cache_control"]["type"] == "ephemeral"
    assert all(c["system"][0] == first[0] for c in calls), "the cached charter block is byte-identical across seats"


def test_a_paused_budget_calls_nothing(monkeypatch):
    from training import panel_judge

    sc = _scorecard()
    window = br.block_window(BLOCK_END)
    codes = br.code_scores(sc, br.assemble_evidence(window))
    monkeypatch.setattr(panel_judge, "_allowed", lambda route: (False, f"paused ({route})"))
    monkeypatch.setattr(panel_judge, "_bedrock_call", lambda route: pytest.fail("a paused retro must not reach the model"))
    out = br.panel_regrade(sc, codes, window)
    assert out["status"] == "paused" and "charter.retro" in out["reason"]


# ── 5. the predictions ────────────────────────────────────────────────────────────────────
def test_the_charter_predictions_are_graded_by_their_own_measurement_after_grade_by_only():
    may, _ = _fixture()
    preds = rcp.build_records()
    assert br.grade_predictions(preds, "2026-12-05", may, SUPPLIED) == [], "nothing is graded before grade_by"
    got = {p["metric"]: p for p in br.grade_predictions(preds, BLOCK_END, may, SUPPLIED)}
    assert set(got) == set(br.PREDICTION_GRADERS) == {p["metric"] for p in preds}
    # steps 10-19..12-06: seven weeks, floor met 7,6,7,6,7,6,7 of 7 -> 46/49 = 0.939 >= 0.90.
    assert got["steps_floor_90pct"]["verdict"] == "confirmed" and got["steps_floor_90pct"]["evidence"]["share"] == round(46 / 49, 3)
    # rate: Sundays 11-01..12-06 -> in, below, in, in, above, in = 4 in band >= 4.
    assert got["rate_in_band_4_of_6"]["verdict"] == "confirmed" and got["rate_in_band_4_of_6"]["evidence"]["in_band"] == 4
    assert got["anchor_e1rm_up"]["verdict"] == "confirmed"
    assert got["zero_accessory_stalls"]["verdict"] == "refuted" and got["zero_accessory_stalls"]["evidence"]["stalled"] == ["face pull"]
    # A graded row is not graded twice; an unmeasured week is missing, never a miss.
    done = [{**p, "status": "confirmed"} for p in preds]
    assert br.grade_predictions(done, BLOCK_END, may, SUPPLIED) == []
    sparse = [r for r in may if r["week_end"] not in ("2026-11-01", "2026-11-08", "2026-11-15")]
    assert {p["metric"]: p for p in br.grade_predictions(preds, BLOCK_END, sparse, SUPPLIED)}["rate_in_band_4_of_6"][
        "verdict"
    ] == "inconclusive"


# ── 6. the row, the doc tab, privacy ──────────────────────────────────────────────────────
def test_the_retro_row_is_owner_only_and_stamped_and_the_doc_tab_renders():
    from privacy import field_tiers

    out, _ = _run()
    item = br.retro_item(out)
    assert (item["pk"], item["sk"]) == ("USER#matthew#SOURCE#training_constraints", f"RETRO#{BLOCK_END}")
    assert item["tier"] == "owner_only" and field_tiers.SOURCE_TIERS["training_constraints"] == field_tiers.TIER_OWNER_ONLY
    assert item["charter_version"] == tc.charter_version() and item["scorecard_version"] == _scorecard()["version"]
    assert len(item["rows"]) == 13 and len(item["predictions"]) == 4
    md = br.render_markdown(out)
    assert all(r["label"] in md for r in out["graded"]["rows"].values()) and "Movers:" in md
    schema = (_REPO / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    assert "`…SOURCE#training_constraints` / `RETRO#<YYYY-MM-DD>`" in schema


def test_no_published_surface_imports_the_retro():
    import os

    offenders = []
    for d in ("lambdas/web", "lambdas/emails"):
        for root, _dirs, files in os.walk(_REPO / d):
            for f in sorted(files):
                path = pathlib.Path(root) / f
                if f.endswith(".py") and ("block_retro" in path.read_text(encoding="utf-8")):
                    offenders.append(path.relative_to(_REPO).as_posix())
    assert not offenders, f"a published-surface module names the owner-only block retro: {offenders}"


# ── 7. the skill ──────────────────────────────────────────────────────────────────────────
def test_the_skill_is_wired_to_the_charter_the_route_and_the_owner_only_stores():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: training-review\n")
    must = [
        "config/training_scorecard.json",
        "lambdas/training/block_retro.py",
        "scripts/training_block_retro.py",
        "rotation.anchors_fixed_weeks",
        "charter.retro",
        "charter_retro",
        "ai.dev_session_cap",
        "RETRO#",
        "get_may_tracker",
        "PANEL#",
        "evaluate_prediction",
        "mcp__claude_ai_Claude_Docs__read",
        "97f07da3-857f-4e68-8125-69e4ae6b9081",
        "charter_version",
    ]
    missing = [m for m in must if m not in text]
    assert not missing, missing
    lowered = text.lower()
    assert "never web-fetch" in lowered and "never a public page" in lowered
    # No copied target: the charter's own date and band never appear in the skill.
    goal = tc.charter_value("governing_goal")
    leaks = [
        s for s in (goal["target_date"], f"{goal['rate_band_lb_per_wk']['floor']} lb", f"{tc.charter_value('steps.floor'):,}") if s in text
    ]
    assert not leaks, leaks
