"""tests/test_panel_rubric_5072.py — the panel rubric eval harness (#5072, epic #5067).

What each test holds (one census gate each — every one iterates its whole set and reports every offender):

  1. THE RUBRIC IS THE CHARTER'S PANEL: the seats are exactly the charter's concession_ledger schools, each with
     4-6 criteria; every CODE criterion names a check that exists, and every check is used.
  2. THE GOLDEN GATE PASSES (recorded judge): `scripts/panel_rubric_gate.py --recorded` exits 0 on the fixtures.
  3. THE CONTROLS FAIL ON CODE ALONE: with no judge at all, every hand-built negative control misses the target
     and scores below the seat floor on each criterion it exists to fail — while the good plan meets it.
  4. THE WEEKLY MUTATIONS AND THE FIXTURES AGREE: `panel_rubric.negative_controls(good)` fails the same
     criteria the hand-built fixtures do (two independent paths to each defect).
  5. BLINDED: nothing the judge receives names the engine, its version, the author, a routine id or an issue.
  6. A DIFFERENT TIER: both judge routes resolve to a different model from the planner's red team.
  7. A PAUSED / FAILED JUDGE DEGRADES, NEVER FABRICATES.
  8. THE WEEKLY GRADE: real plan + every control back-to-back (the register's call count), the trend, the row.
  9. OUTCOMES OUTRANK THE RUBRIC.
 10. THE GATE CAN FAIL (mutation): a check that stops discriminating reds the gate, naming the control.

No live AI call and no AWS: the judge is a replay of `recorded_judge.json`; the charter is the bundled file.
"""

from __future__ import annotations

import copy
import importlib
import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO))

from training import panel_judge, panel_rubric, plan_engine, training_charter as tc  # noqa: E402

FIX = _REPO / "tests" / "fixtures" / "panel_golden_5072"
gate = importlib.import_module("panel_rubric_gate")


@pytest.fixture(autouse=True)
def _bundled_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _rubric():
    r = panel_rubric.load_rubric()
    assert r is not None, "config/panel_rubric.json unreadable"
    return r


def _case(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _recorded():
    return json.loads((FIX / gate.RECORDED).read_text(encoding="utf-8"))["responses"]


def _replay(reply, calls=None):
    def call(body):
        if calls is not None:
            calls.append(body)
        return {"content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn", "usage": {}}

    return call


def test_the_rubric_is_the_charters_panel_and_every_check_resolves():
    rubric = _rubric()
    problems = []
    ledger = set(tc.charter_value("concession_ledger", {}) or {})
    if set(rubric["seats"]) != ledger or len(ledger) < 8:
        problems.append(f"seats {sorted(rubric['seats'])} != charter concession_ledger {sorted(ledger)}")
    used = set()
    for seat, spec in rubric["seats"].items():
        crits = spec["criteria"]
        if not 4 <= len(crits) <= 6:
            problems.append(f"{seat}: {len(crits)} criteria (4-6 required)")
        if len({c["id"] for c in crits}) != len(crits):
            problems.append(f"{seat}: duplicate criterion id")
        if not any(c["by"] == panel_rubric.BY_JUDGE for c in crits):
            problems.append(f"{seat}: no judge criterion — the seat would never be read by a model")
        for c in crits:
            if c["by"] == panel_rubric.BY_CODE:
                used.add(c.get("check"))
                if c.get("check") not in panel_rubric.CHECKS:
                    problems.append(f"{seat}.{c['id']}: check {c.get('check')!r} is not in panel_rubric.CHECKS")
            elif c["by"] != panel_rubric.BY_JUDGE:
                problems.append(f"{seat}.{c['id']}: by={c['by']!r}")
        if panel_rubric.concession(seat) is None:
            problems.append(f"{seat}: no concession readable from the charter")
    unused = set(panel_rubric.CHECKS) - used
    if unused:
        problems.append(f"checks no criterion uses: {sorted(unused)}")
    mins = [row["min"] for row in rubric["letters"]]
    if mins != sorted(mins, reverse=True) or mins[-1] != 0:
        problems.append(f"letters not descending to 0: {mins}")
    tgt = panel_rubric.target()
    if tgt.get("overall") not in [row["letter"] for row in rubric["letters"]] or not tgt.get("every_seat_at_least"):
        problems.append(f"charter panel_target {tgt} is not expressible on the rubric's scale")
    assert not problems, "\n".join(problems)


def test_the_golden_gate_passes_on_the_recorded_judge(capsys):
    code, lines = gate.run("recorded")
    assert code == 0, "\n".join(lines)
    kinds = {c["case_id"]: c.get("kind") for c in gate.golden_cases()}
    assert list(kinds.values()).count(gate.GOOD_KIND) >= 1 and list(kinds.values()).count(gate.CONTROL_KIND) >= 4, kinds
    assert set(_recorded()) == set(kinds), "every golden case needs exactly one recorded judge reply"


def test_negative_controls_fail_on_code_alone_and_the_good_plan_does_not():
    rubric = _rubric()
    problems = []
    for case in gate.golden_cases():
        graded = panel_rubric.combine(panel_rubric.prescore(case, rubric), None, rubric)
        graded["target"] = panel_rubric.target()
        if case.get("kind") == gate.GOOD_KIND:
            low = {f"{s}.{c}": v["score"] for s, seat in graded["seats"].items() for c, v in seat["criteria"].items() if v["score"] < 9}
            if not graded["target_met"] or low:
                problems.append(f"{case['case_id']}: the good plan misses on code alone: {low} {graded['overall']}")
        else:
            missed = panel_judge.failed_expectations(graded, case["expect_fail"])
            if missed:
                problems.append(f"{case['case_id']}: {missed}")
    assert not problems, "\n".join(problems)


def test_the_weekly_mutations_fail_what_the_hand_built_fixtures_fail():
    rubric = _rubric()
    good = _case("good_charter_plan")
    fixture_fails = sorted(tuple(sorted(c["expect_fail"])) for c in gate.golden_cases() if c.get("kind") == gate.CONTROL_KIND)
    mutation_fails = sorted(tuple(sorted(must)) for _, must in panel_rubric.CONTROL_MUTATIONS.values())
    assert fixture_fails == mutation_fails, "the fixtures and CONTROL_MUTATIONS must cover the same four defects"
    problems = []
    before = json.dumps(good, sort_keys=True)
    for c in panel_rubric.negative_controls(good):
        graded = panel_rubric.combine(panel_rubric.prescore(c, rubric), None, rubric)
        missed = panel_judge.failed_expectations(graded, c["expect_fail"])
        if missed:
            problems.append(f"{c['case_id']}: {missed}")
    assert json.dumps(good, sort_keys=True) == before, "negative_controls mutated the real plan"
    assert not problems, "\n".join(problems)


def test_the_judge_is_blinded_to_the_engine_its_version_and_the_author():
    rubric = _rubric()
    case = copy.deepcopy(_case("good_charter_plan"))
    for r in case["routines"]:  # plant every identifier a real plan can carry
        r.update(created_by="nightly_predraft", source_action="draft", routine_id="rt-PLANTED-ID", hevy_routine_id="hv-PLANTED")
        r["rationale"] = [f"{plan_engine.ENGINE_VERSION} built this (#5052)"]
        r["notes"] = f"pre-draft by the generator, {plan_engine.ENGINE_VERSION}, critics approved (#4084)"
        r["inputs_snapshot"]["nightly_predraft"] = {"role": "primary", "engine": plan_engine.ENGINE_VERSION}
        r["exercises"][0]["notes"] += " (engine v1.11.0, #5052)"
    body = panel_judge.build_body(case, rubric, panel_judge.WEEKLY_ROUTE)
    volatile = " ".join(b["text"] for b in body["system"][1:]) + " " + json.dumps(body["messages"])
    forbidden = (
        plan_engine.ENGINE_VERSION,
        "plan-engine",
        "rt-PLANTED-ID",
        "hv-PLANTED",
        "nightly",
        "predraft",
        "pre-draft",
        "generator",
        "#5052",
        "#4084",
        "critic",
        "1.11.0",
        "created_by",
    )
    leaks = [t for t in forbidden if t.lower() in volatile.lower()]
    assert not leaks, f"the judge's prompt names: {leaks}"
    assert "SESSION 1" in volatile and "progression: step" in volatile, "the blinded plan lost the plan itself"


def test_the_judge_runs_on_a_different_tier_from_the_planner():
    bad = {
        r: panel_judge.tier_check(r) for r in (panel_judge.WEEKLY_ROUTE, panel_judge.CI_ROUTE) if panel_judge.tier_check(r)["same_model"]
    }
    assert not bad, f"judge and planner resolve to the same model: {bad}"


def test_a_paused_or_failed_judge_degrades_and_never_fabricates(monkeypatch):
    from ai import budget_guard

    rubric = _rubric()
    case = _case("good_charter_plan")
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    paused = panel_judge.grade_case(case, rubric, route=panel_judge.CI_ROUTE)

    def boom(body):
        raise RuntimeError("ThrottlingException")

    failed = panel_judge.grade_case(case, rubric, call=boom)
    garbled = panel_judge.grade_case(case, rubric, call=lambda b: {"content": [{"type": "text", "text": "not json"}]})
    judge_ids = {f"{s}.{c['id']}" for s, cs in panel_rubric.judge_criteria(rubric).items() for c in cs}
    problems = []
    for name, g, status in (("paused", paused, "paused"), ("failed", failed, "error"), ("garbled", garbled, "unparsed")):
        if g["judge"]["status"] != status or not g["degraded"] or not g["degraded_reasons"]:
            problems.append(f"{name}: judge {g['judge']['status']} degraded={g['degraded']} {g['degraded_reasons']}")
        if set(g["unscored"]) != judge_ids:
            problems.append(f"{name}: unscored {sorted(g['unscored'])} != every judge criterion")
        if any(v["by"] == panel_rubric.BY_JUDGE for seat in g["seats"].values() for v in seat["criteria"].values()):
            problems.append(f"{name}: a judge score appeared with no judge reply")
    assert not problems, "\n".join(problems)


def test_the_live_gate_reds_when_the_judge_cannot_grade(monkeypatch, capsys):
    """Review of PR #5169: a live judge that errors (the Sonnet grant missing -> AccessDeniedException) or
    replies with nothing gradeable must red the live step with an ::error:: — never a code-only green.
    The budget pause stays the one soft path."""
    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)

    def denied(body):
        raise RuntimeError("AccessDeniedException: not authorized to perform bedrock:InvokeModel")

    def no_boto(route):
        raise ImportError("No module named 'boto3'")

    problems = []
    for name, factory in (
        ("transport raises", lambda route: denied),
        ("factory raises", no_boto),
        ("garbled reply", lambda route: (lambda b: {"content": [{"type": "text", "text": "not json"}], "usage": {}})),
    ):
        monkeypatch.setattr(panel_judge, "_bedrock_call", factory)
        code, lines = gate.run("live")
        out = capsys.readouterr().out
        n_cases = len(gate.golden_cases())
        if code != 1:
            problems.append(f"{name}: exit {code}, want 1 — {lines[-1]}")
        if sum(ln.startswith("FAIL ") for ln in lines) != n_cases:
            problems.append(f"{name}: not every case FAILed: {[ln for ln in lines if not ln.startswith('     ')]}")
        if out.count("::error title=panel rubric gate::") != n_cases:
            problems.append(f"{name}: {out.count('::error')} ::error:: annotations for {n_cases} cases")
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    code, lines = gate.run("live")
    out = capsys.readouterr().out
    if code != 0 or "::error" in out or "::warning title=panel rubric gate::judge paused" not in out:
        problems.append(f"paused: exit {code}, the pause must stay soft and warned — {lines[-1]}")
    monkeypatch.setenv("PANEL_JUDGE_CREDS", "failure")  # CI: the OIDC step refused (pull_request subject)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code = gate.main(["--live"])
    out = capsys.readouterr().out
    if code != 0 or "live judge NOT run" not in out or "::warning title=panel rubric gate::" not in out:
        problems.append(f"creds refused: exit {code}, must be a visible, warned skip — {out[-200:]}")
    assert not problems, "\n".join(problems)


def test_the_weekly_grade_judges_the_plan_and_every_control_back_to_back_and_trends():
    rubric = _rubric()
    good = _case("good_charter_plan")
    calls: list = []
    history = [{"week_end": "2026-10-11", "overall_score": 9.1, "seat_scores": {s: 9.0 for s in rubric["seats"]}}]
    g = panel_judge.grade_committed_week(
        "2026-10-18",
        week_start="2026-10-12",
        routines=good["routines"],
        constraint_block=good["constraint_block"],
        rubric=rubric,
        call=_replay(_recorded()["good_charter_plan"], calls),
        history=history,
    )
    assert len(calls) == panel_judge.WEEKLY_CALLS_PER_RUN, len(calls)
    assert all(c["system"][0].get("cache_control") for c in calls), "every call carries the cached charter block"
    assert g["status"] == "graded" and g["target_met"] and not g["degraded"], (g["degraded_reasons"], g["overall"])
    assert [c["control"] for c in g["controls"]] == list(panel_rubric.CONTROL_MUTATIONS) and not any(c["missed"] for c in g["controls"])
    assert g["trend"]["previous"] == "2026-10-11" and g["trend"]["overall_delta"] == round(g["overall"]["score"] - 9.1, 2)
    item = panel_judge.panel_item(g, "USER#matthew")
    assert (item["pk"], item["sk"]) == ("USER#matthew#SOURCE#training_constraints", "PANEL#2026-10-18")
    assert "routines" not in item and item["overall_letter"] == "A" and set(item["seat_scores"]) == set(rubric["seats"])
    empty = panel_judge.grade_committed_week("2026-10-18", routines=[], constraint_block=None, rubric=rubric, call=_replay({}))
    assert empty["status"] == "no_plan" and empty["degraded"]


def test_a_tripped_outcome_outranks_a_passing_rubric():
    rubric = _rubric()
    case = copy.deepcopy(_case("good_charter_plan"))
    case["constraint_block"]["tripwires"] = [t for t in case["constraint_block"]["tripwires"] if t["id"] != "anchor_lift_strength_drop"] + [
        {"id": "anchor_lift_strength_drop", "state": "tripped"}
    ]
    g = panel_judge.grade_case(case, rubric, call=_replay(_recorded()["good_charter_plan"]))
    assert g["target_met"] and g["rubric_outranked"] == ["anchor_lift_strength_drop is tripped"], g["rubric_outranked"]


def test_the_gate_reds_when_a_check_stops_discriminating(monkeypatch):
    """Mutation proof (also the census verdict): a dose check that passes everything lets the no-dose control
    through on that criterion — the gate must exit 1 and name it."""
    monkeypatch.setitem(panel_rubric.CHECKS, "cardio_dosed", lambda f: (10.0, "mutated: always dosed"))
    code, lines = gate.run("recorded")
    assert code == 1, "\n".join(lines)
    assert any(ln.startswith("FAIL neg_cardio_no_dose") for ln in lines) and any("galpin.cardio_dosed" in ln for ln in lines), lines


def test_the_mcp_job_wires_readers_stores_one_row_and_never_raises(monkeypatch, capsys):
    """The weekly job's wiring: committed routines only, the PANEL# row written once, a failure emits the
    dead-man datapoint at 0 and returns — the handler dispatches the constant input to it."""
    import os

    os.environ.setdefault("USER_ID", "matthew")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
    from mcp import panel_weekly_grade as pwg

    good = _case("good_charter_plan")
    stored = []
    monkeypatch.setattr(pwg, "read_routines", lambda s, e: good["routines"])
    monkeypatch.setattr(pwg, "read_constraint_block", lambda e: good["constraint_block"])
    monkeypatch.setattr(pwg, "read_history", lambda: [])
    monkeypatch.setattr(pwg, "store", lambda g: stored.append(g["week_end"]) or {"written": True})
    reply = _recorded()["good_charter_plan"]
    real_grade = panel_judge.grade_committed_week
    monkeypatch.setattr(panel_judge, "grade_committed_week", lambda *a, **k: real_grade(*a, call=_replay(reply), **k))
    out = json.loads(pwg.lambda_entry({"job": "panel_weekly_grade", "week_end": "2026-10-18"})["body"])
    assert out["status"] == "graded" and out["target_met"] and stored == ["2026-10-18"], out
    monkeypatch.setattr(pwg, "run", lambda week_end=None: (_ for _ in ()).throw(RuntimeError("boom")))
    resp = pwg.lambda_entry({"job": "panel_weekly_grade"})
    emf = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.startswith('{"_aws"')]
    assert resp["statusCode"] == 200 and [e["PanelGradeOutcome"] for e in emf] == [1, 0], emf
    assert pwg._committed(type("IR", (), {"status": "draft", "hevy_routine_id": None})()) is False
    handler_src = (_REPO / "mcp" / "handler.py").read_text(encoding="utf-8")
    assert f'event.get("job") == "{pwg.JOB["event"]["job"]}"' in handler_src, "mcp.handler no longer dispatches the weekly grade"
