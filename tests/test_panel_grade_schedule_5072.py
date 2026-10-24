"""tests/test_panel_grade_schedule_5072.py — the weekly panel grade's schedule (#5072).

Three must-agree pairs, each read from the real artifact rather than restated:

  1. `mcp.panel_weekly_grade.JOB` (the one declaration) <-> `cdk/stacks/mcp_stack.py` + `config/schedules.json` —
     the rule's expression, its constant input, its target function, and the dead-man alarm's metric identity.
     Read from the stack's AST, so a CDK edit that drifts from the module reds here.
  2. The schedule <-> the week the job grades — the cron fires on a Monday in Pacific time in BOTH offsets,
     so the job's default week ("yesterday, Pacific", back 7 days) is the Mon-Sun week just finished.
  3. The budget class <-> the call path — the weekly route spends under `charter_judge` (a declared
     budget_guard band, never the hard-stop default), its real transport is `bedrock_client.invoke_with_retry`,
     a paused tier still yields a stored-honest outcome (EMF 1), and the AI budget ledger claims the dimension
     the spend lands under inside the warmer Lambda.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import schedule_rows  # noqa: E402 - tests/ is on sys.path; #4284 the schedule table

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO))

os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from mcp import panel_weekly_grade as pwg  # noqa: E402

STACK = _REPO / "cdk" / "stacks" / "mcp_stack.py"
CONSTRUCT_ID = "PanelWeeklyGrade"


def _literal(node):
    return ast.literal_eval(node)


def _calls(tree, attr):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == attr]


def _kw(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


# ── 1. JOB <-> the CDK stack and the schedule table ─────────────────────────────────────
def test_cdk_rule_and_deadman_match_the_job_declaration():
    tree = ast.parse(STACK.read_text(encoding="utf-8"))
    consts = {
        t.id: n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    problems = []

    rules = [c for c in _calls(tree, "Rule") if c.args[1:] and _literal(c.args[1]) == CONSTRUCT_ID]
    assert len(rules) == 1, f"exactly one {CONSTRUCT_ID} rule in mcp_stack.py, found {len(rules)}"
    sched = _kw(rules[0], "schedule")
    key = _literal(sched.args[0])
    if key != pwg.JOB["schedule_key"]:
        problems.append(f"rule reads schedule row {key!r}, JOB declares {pwg.JOB['schedule_key']!r}")
    row = schedule_rows.rows().get(pwg.JOB["schedule_key"]) or {}
    if row.get("expression") != pwg.JOB["schedule_utc"]:
        problems.append(f"config/schedules.json expression {row.get('expression')!r} != JOB {pwg.JOB['schedule_utc']!r}")
    if row.get("function") != pwg.JOB["function"] or row.get("stack") != "LifePlatformMcp":
        problems.append(f"schedule row targets {row.get('function')!r} in {row.get('stack')!r}")
    if "timezone" in row:
        problems.append("the row must stay fixed UTC (CONVENTIONS 1b) — the Monday-Pacific proof below assumes it")
    if _kw(rules[0], "enabled") is not None:
        problems.append("the rule must ship enabled — a disabled rule is not a schedule")

    inputs = [c for c in _calls(tree, "from_object") if _literal(c.args[0]) == pwg.JOB["event"]]
    assert len(inputs) == 1, f"the rule's constant input must be exactly {pwg.JOB['event']}"
    target = next(c for c in _calls(tree, "LambdaFunction") if any(s is inputs[0] for s in ast.walk(c)))
    fn_assign = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target.args[0].id for t in n.targets)
    )
    if consts.get(getattr(_kw(fn_assign.value, "function_name"), "id", None)) != pwg.JOB["function"]:
        problems.append(f"the rule's target is not {pwg.JOB['function']}")

    alarms = [
        c for c in _calls(tree, "Alarm") if _kw(c, "alarm_name") is not None and _literal(_kw(c, "alarm_name")) == pwg.JOB["deadman_alarm"]
    ]
    assert len(alarms) == 1, f"exactly one {pwg.JOB['deadman_alarm']} alarm"
    alarm = alarms[0]
    metric = _kw(alarm, "metric")
    for field, want in (
        ("namespace", pwg.JOB["metric_namespace"]),
        ("metric_name", pwg.JOB["metric_name"]),
        ("dimensions_map", pwg.JOB["metric_dimension"]),
    ):
        if _literal(_kw(metric, field)) != want:
            problems.append(f"dead-man metric {field} {_literal(_kw(metric, field))!r} != {want!r}")
    if _literal(_kw(metric, "period").args[0]) != pwg.JOB["deadman_period_s"]:
        problems.append("dead-man period drifted from JOB")
    for field in ("evaluation_periods", "datapoints_to_alarm"):
        if _literal(_kw(alarm, field)) != pwg.JOB["deadman_periods"]:
            problems.append(f"dead-man {field} drifted from JOB")
    if _kw(alarm, "treat_missing_data").attr != "BREACHING":
        problems.append("absence must be the failure (missing = BREACHING)")
    # one full week: a weekly job's dead-man must not be shorter (false red between runs) or longer than CloudWatch allows
    if pwg.JOB["deadman_period_s"] * pwg.JOB["deadman_periods"] != 7 * 86400:
        problems.append("the dead-man window must be exactly one week")
    assert not problems, "\n".join(problems)


def test_emf_line_carries_the_alarms_metric_identity():
    for status, want in (("graded", 1), ("no_plan", 1), ("failed", 0), ("no_rubric", 0)):
        rec = json.loads(pwg.emf_line(status))
        spec = rec["_aws"]["CloudWatchMetrics"][0]
        assert spec["Namespace"] == pwg.JOB["metric_namespace"]
        assert spec["Metrics"][0]["Name"] == pwg.JOB["metric_name"]
        assert {k: rec[k] for k in pwg.JOB["metric_dimension"]} == pwg.JOB["metric_dimension"]
        assert rec[pwg.JOB["metric_name"]] == want, status


# ── 2. the schedule <-> the week graded ────────────────────────────────────────────────
def test_the_cron_fires_on_a_pacific_monday_in_both_offsets_so_the_week_is_mon_to_sun():
    """`cron(M H ? * MON *)` fixed UTC: the firing instant, read in America/Los_Angeles in a PDT week and a PST
    week, must be a Monday — then `run()`'s default week_end (yesterday, Pacific) is the Sunday just finished."""
    fields = pwg.JOB["schedule_utc"][len("cron(") : -1].split()
    minute, hour, dom, _month, dow, _year = fields
    assert (dom, dow) == ("?", "MON"), f"a weekly Monday rule is expected, got {pwg.JOB['schedule_utc']}"
    pt = ZoneInfo("America/Los_Angeles")
    for monday in ("2026-10-19", "2026-11-16"):  # PDT, PST
        y, m, d = map(int, monday.split("-"))
        fire = datetime(y, m, d, int(hour), int(minute), tzinfo=timezone.utc).astimezone(pt)
        assert fire.strftime("%a") == "Mon", f"{monday} {hour}:{minute}Z is {fire:%a %H:%M} Pacific"


def test_the_default_week_ends_yesterday_pacific(monkeypatch):
    seen = {}
    monkeypatch.setattr("common.pacific_time.pacific_today", lambda: "2026-10-26")
    monkeypatch.setattr(pwg, "read_routines", lambda s, e: seen.update(start=s, end=e) or [])
    monkeypatch.setattr(pwg, "read_constraint_block", lambda e: None)
    monkeypatch.setattr(pwg, "read_history", lambda: [])
    monkeypatch.setattr(pwg, "read_food_plan", lambda s, r: None)
    out = pwg.run()
    assert (seen["start"], seen["end"]) == ("2026-10-19", "2026-10-25") and out["status"] == "no_plan", (seen, out)


# ── 3. the budget class <-> the call path ──────────────────────────────────────────────
def test_the_weekly_judge_is_budget_classed_and_calls_bedrock_client(monkeypatch):
    from ai import bedrock_client, budget_guard
    from training import charter_ai, panel_judge

    feature = charter_ai.CALLERS[panel_judge.WEEKLY_ROUTE].feature
    assert feature == "charter_judge"
    cutoff = budget_guard._FEATURE_CUTOFF.get(feature)
    assert cutoff is not None and cutoff < budget_guard._HARD_STOP_TIER, f"{feature} must be a declared band below the hard stop: {cutoff}"

    calls = []
    monkeypatch.setattr(bedrock_client, "invoke_with_retry", lambda body, model_name=None: calls.append(model_name) or {"content": []})
    panel_judge._bedrock_call(panel_judge.WEEKLY_ROUTE)({"messages": []})
    assert calls == [getattr(charter_ai, charter_ai.CALLERS[panel_judge.WEEKLY_ROUTE].model_var)], calls


def test_a_paused_tier_still_lands_an_honest_degraded_week(monkeypatch, capsys):
    """At a tier at/above charter_judge's band the run spends nothing and still lands a graded, degraded row —
    so the dead-man reads 1 and the pause is named, never a fabricated score or a silent skip."""
    from ai import bedrock_client, budget_guard

    fixtures = _REPO / "tests" / "fixtures" / "panel_golden_5072"
    good = json.loads((fixtures / "good_charter_plan.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    monkeypatch.setattr(bedrock_client, "invoke_with_retry", lambda *a, **k: pytest.fail("a paused tier must not call Bedrock"))
    monkeypatch.setattr(pwg, "read_routines", lambda s, e: good["routines"])
    monkeypatch.setattr(pwg, "read_constraint_block", lambda e: good["constraint_block"])
    monkeypatch.setattr(pwg, "read_history", lambda: [])
    monkeypatch.setattr(pwg, "read_food_plan", lambda s, r: None)
    stored = []
    monkeypatch.setattr(pwg, "store", lambda g: stored.append(g) or {"written": True})
    out = json.loads(pwg.lambda_entry({"job": "panel_weekly_grade", "week_end": "2026-10-18"})["body"])
    emf = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.startswith('{"_aws"')]
    assert out["status"] == "graded" and out["degraded"] and stored, out
    assert any("paused by the budget guard" in r for r in out["degraded_reasons"]), out["degraded_reasons"]
    assert [e[pwg.JOB["metric_name"]] for e in emf] == [1], emf


def test_the_budget_ledger_claims_the_dimension_the_weekly_spend_lands_under():
    """In a Lambda, bedrock_client books spend to AWS_LAMBDA_FUNCTION_NAME; the rule targets the warmer, so the
    charter_judge ledger row must name that dimension or the close reads it as unclaimed (#3447 leg a)."""
    import ai_budget_ledger

    row = ai_budget_ledger.LEDGER["charter_judge"]
    assert pwg.JOB["function"] in row["attribution_keys"], row
    assert ai_budget_ledger.validate() == []
