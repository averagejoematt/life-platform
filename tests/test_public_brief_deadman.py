"""tests/test_public_brief_deadman.py — the public brief is ready for its first Monday run (owner approval 2026-11-12).

Pins, offline (no AWS; Bedrock replaced by a canned reply):

  1. THE DEAD-MAN. The Lambda door stamps ``COACH#public_brief / RUN#<cycle>`` with each coach's outcome; the nightly
     qa-smoke leg ``public_brief_liveness`` FAILs when the stamp is missing after the Monday deadline (must-fail control:
     the same clock one hour earlier is not yet judged), when the run errored, or when a coach was held/errored without
     a sanctioned reason, and when a ``written`` outcome has no brief row behind it. Its deadline hour is the schedule
     row's; the leg is wired into the nightly; the heartbeat ledger cites it instead of waiving the Monday run.
  2. THE REHEARSAL DOOR. ``today`` is accepted only with ``dry_run``: refused otherwise before any read, write or call;
     a dry run writes nothing (no brief, no call, no stamp) and reports what the publication and provenance checks
     decided, as counts and classes only.
  3. REQUIRED INPUTS. A coach whose required input has no observation is HELD with the missing names before any model
     call — the glucose coach with only calories data writes nothing. Must-fail control: the identical fixture with the
     requirement removed writes a calories-only brief under the glucose name, which is the defect the hold prevents.
"""

import json
import os
import re
import sys
from datetime import datetime

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": [], "blocked_vice_keywords": ["fixtureblockedword"]}))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from coach import persona_registry, public_brief as PB  # noqa: E402
from common import public_brief_policy as POL  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from operational import public_brief_qa as QA  # noqa: E402
from test_public_brief import COACH, SERIES, Table, _reply, _series, good_draft, readings, tolerance_for  # noqa: E402

CYCLE = "2026-11-16"


class _Check:
    def __init__(self, name, cat, tier):
        self.name, self.state, self.msg = name, None, ""

    def ok(self, m=""):
        self.state, self.msg = "ok", m

    def warn(self, m=""):
        self.state, self.msg = "warn", m

    def fail(self, m=""):
        self.state, self.msg = "fail", m


def _at(day, hh, mm=0):
    return lambda: datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").replace(tzinfo=PACIFIC)


def _judge(table, day="2026-11-16", hh=11, mm=30, coaches=(COACH,)):
    return QA.check_public_brief_liveness(table, _Check, "content", _at(day, hh, mm), coaches=list(coaches))[0]


def _wire(monkeypatch, invoke=None, today=CYCLE):
    """handle_event's scheduled path with the model and the readings replaced (the clock pinned to ``today``)."""
    import common.pacific_time as pt

    real = PB.run
    invoke = invoke or _reply(good_draft())
    monkeypatch.setattr(pt, "pacific_today", lambda: today)
    monkeypatch.setattr(
        PB,
        "run",
        lambda table, **kw: real(
            table,
            invoke=invoke,
            allow=lambda f: True,
            readings=readings,
            tolerance_for=tolerance_for,
            **{**kw, "coach_ids": kw.get("coach_ids") or [COACH]},
        ),
    )
    return invoke


# ── 2. the rehearsal door ───────────────────────────────────────────────────────────────────
def test_today_without_dry_run_is_refused_before_anything(monkeypatch):
    monkeypatch.setattr(PB, "run", lambda *a, **k: pytest.fail("run reached"))
    table = Table()
    assert PB.handle_event(table, {"mode": "public_brief", "today": CYCLE}) == {
        "status": "refused",
        "reason": "today_override_requires_dry_run",
    }
    assert PB.handle_event(table, {"mode": "public_brief", "today": CYCLE, "dry_run": False})["status"] == "refused"
    assert PB.handle_event(table, {"mode": "public_brief", "today": "next monday", "dry_run": True})["reason"] == "malformed_today"
    assert table.puts == []


def test_dry_run_with_today_rehearses_the_cycle_and_writes_nothing(monkeypatch):
    invoke = _wire(monkeypatch, today="2026-11-12")  # the real clock is before the first cycle
    table = Table()
    out = PB.handle_event(table, {"mode": "public_brief", "today": CYCLE, "dry_run": True})
    assert out["status"] == "ok" and out["cycle"] == CYCLE and len(invoke.calls) == 1
    res = out["results"][COACH]
    assert res["status"] == "dry_run" and (res["interpretations"], res["predictions"], res["recommendations"]) == (1, 2, 2)
    assert table.puts == []  # no brief, no ledger call, no run stamp
    chk = res["checks"]
    assert chk["brief_provenance_publishable"] is True
    assert chk["call_provenance_publishable"] == [True, True] and chk["calls_gradeable"] == [True, True]
    assert chk["call_class_now"] == [["private", "public_brief_dark"]] * 2  # dark while the switch is off
    assert [c[0] for c in chk["call_class_when_live"]] == ["public", "public"]
    assert not re.search(r"Daily calories averaged|Intake is below", json.dumps(out))  # the words never leave


def test_without_the_override_the_real_clock_refuses_the_first_cycle_early(monkeypatch):
    _wire(monkeypatch, today="2026-11-12")
    out = PB.handle_event(Table(), {"mode": "public_brief", "dry_run": True})
    assert out["status"] == "refused"  # run(today=None) reads the real clock — this pins the gap the override closes


def test_the_switch_and_the_route_stay_dark():
    assert POL.PUBLICATION_LIVE is False


# ── 1. the run stamp ────────────────────────────────────────────────────────────────────────
def test_the_scheduled_run_stamps_each_coach_outcome(monkeypatch):
    _wire(monkeypatch)
    table = Table()
    out = PB.handle_event(table, {"mode": "public_brief"})
    assert out["results"][COACH]["status"] == "written"
    stamp = table.store[(PB.RUN_PK, PB.run_sk(CYCLE))]
    assert stamp["status"] == "ok" and stamp["results"] == {COACH: {"status": "written"}} and stamp["run_on"] == CYCLE


def test_a_held_coach_is_stamped_with_its_reason(monkeypatch):
    _wire(monkeypatch, invoke=_reply({"interpretations": [{"text": "He felt tired.", "cites": ["o1"]}]}))
    table = Table()
    PB.handle_event(table, {"mode": "public_brief"})
    assert table.store[(PB.RUN_PK, PB.run_sk(CYCLE))]["results"][COACH] == {"status": "held", "reason": "no_item_passed"}


def test_a_partial_rerun_merges_and_never_stands_in_for_the_cycle(monkeypatch):
    table = Table()
    assert PB.stamp_run(table, CYCLE, {"status": "ok", "cycle": CYCLE, "results": {COACH: {"status": "x"}}}, merge=True) is False
    assert table.puts == []
    PB.stamp_run(
        table, CYCLE, {"status": "ok", "cycle": CYCLE, "results": {COACH: {"status": "held"}, "sleep_coach": {"status": "written"}}}
    )
    PB.stamp_run(table, CYCLE, {"status": "ok", "cycle": CYCLE, "results": {COACH: {"status": "written"}}}, merge=True)
    assert table.store[(PB.RUN_PK, PB.run_sk(CYCLE))]["results"] == {COACH: {"status": "written"}, "sleep_coach": {"status": "written"}}


def test_no_stamp_before_the_first_cycle():
    table = Table()
    assert PB.stamp_run(table, "2026-11-12", {"status": "refused", "cycle": "2026-11-09"}) is False and table.puts == []


# ── 1. the dead-man ─────────────────────────────────────────────────────────────────────────
def test_must_fail_no_stamp_after_the_deadline_and_not_before_it():
    table = Table()
    assert _judge(table).state == "fail"  # Monday 11:30 PT, the cycle's run window closed, nothing stamped
    assert _judge(table, hh=9, mm=45).state == "ok"  # Monday 09:45 PT: still in flight; the previous cycle is pre-first
    assert _judge(table, day="2026-11-12").state == "ok"  # before the first cycle: nothing is due
    assert _judge(table, day="2026-11-20").state == "fail"  # the hole stays red for the rest of the week


def test_ok_only_when_every_coach_has_its_brief_row(monkeypatch):
    _wire(monkeypatch)
    table = Table()
    PB.handle_event(table, {"mode": "public_brief"})
    assert _judge(table).state == "ok"
    del table.store[(f"COACH#{COACH}", POL.brief_sk(CYCLE))]  # a 'written' stamp with no row behind it
    c = _judge(table)
    assert c.state == "fail" and "no brief row" in c.msg


def test_a_coach_the_registry_expects_but_the_stamp_lacks_fails(monkeypatch):
    _wire(monkeypatch)
    table = Table()
    PB.handle_event(table, {"mode": "public_brief"})
    c = _judge(table, coaches=(COACH, "sleep_coach"))
    assert c.state == "fail" and "sleep_coach=no outcome" in c.msg


@pytest.mark.parametrize(
    "outcome,state",
    [
        ({"status": "held", "reason": "no_item_passed"}, "fail"),
        ({"status": "held", "reason": "unparseable"}, "fail"),
        ({"status": "error"}, "fail"),
        ({"status": "refused", "reason": "inputs_not_publishable"}, "fail"),
        ({"status": "held", "reason": PB.HELD_FOR_INPUTS, "missing": ["blood_glucose_avg"]}, "warn"),
        ({"status": "insufficient_data"}, "warn"),
    ],
)
def test_coach_outcomes(outcome, state):
    table = Table()
    PB.stamp_run(table, CYCLE, {"status": "ok", "cycle": CYCLE, "results": {COACH: outcome}})
    assert _judge(table).state == state


@pytest.mark.parametrize(
    "run,state", [({"status": "paused", "feature": "coach_narrative"}, "warn"), ({"status": "error", "error": "x"}, "fail")]
)
def test_run_outcomes(run, state):
    table = Table()
    PB.stamp_run(table, CYCLE, run)
    assert _judge(table).state == state


def test_the_deadline_is_the_schedule_rows_hour():
    row = json.load(open(os.path.join(_REPO, "config", "schedules.json")))["schedules"]["coach-history-summarizer#PublicBrief"]
    assert row["expression"] == f"cron(0 {QA.DUE_HOUR_PT} ? * MON *)" and "timezone" not in row  # Pacific wall clock


def test_the_leg_runs_nightly_and_the_heartbeat_ledger_cites_it():
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")).read()
    assert '("public_brief_liveness", lambda: public_brief_qa.check_public_brief_liveness(' in src
    import test_heartbeat_completeness as HB

    row = HB.COVERAGE["coach-history-summarizer"]
    assert "public_brief_liveness" in row[2] and row[-1] == "qa-smoke-failures"
    assert "never backfilled" not in row[2]  # the Monday run is no longer waived


# ── 3. required inputs ──────────────────────────────────────────────────────────────────────
GLUCOSE = "glucose_coach"


def _glucose_personas(required=True):
    p = dict(persona_registry.personas()[GLUCOSE])
    if not required:
        p.pop(PB.REQUIRED_KEY, None)
    return {GLUCOSE: p}


def _glucose_draft():
    d = good_draft()
    d["predictions"] = [dict(d["predictions"][0], metric="total_calories_kcal", cites=["o1"])]
    d["recommendations"] = d["recommendations"][1:]
    return d


def _glucose_run(personas, extra=None):
    series = dict(SERIES, **(extra or {}))
    invoke = _reply(_glucose_draft())
    table = Table()
    out = PB.run(
        table,
        today=CYCLE,
        invoke=invoke,
        allow=lambda f: True,
        readings=lambda m, s, e: [(d, v) for d, v in series.get(m, []) if s <= d <= e],
        tolerance_for=tolerance_for,
        personas=personas,
    )
    return out["results"][GLUCOSE], invoke, table


def test_a_coach_without_its_required_input_is_held_before_any_call():
    res, invoke, table = _glucose_run(_glucose_personas())
    assert res == {"status": "held", "reason": PB.HELD_FOR_INPUTS, "missing": ["blood_glucose_avg"], "evidence_written": 0}
    assert invoke.calls == [] and table.puts == []


def test_must_fail_control_without_the_requirement_a_calories_only_brief_is_written():
    res, invoke, table = _glucose_run(_glucose_personas(required=False))
    assert res["status"] == "written" and len(invoke.calls) == 1
    brief = next(r for r in table.puts if r["sk"] == POL.brief_sk(CYCLE))
    assert [o["metric"] for o in brief["observations"]] == ["total_calories_kcal"]  # the substitute the hold refuses


def test_with_glucose_readings_the_coach_is_briefed():
    res, _invoke, _table = _glucose_run(_glucose_personas(), {"blood_glucose_avg": _series("2026-10-19", 28, 98.0, 0.1)})
    assert res["status"] == "written"


def test_every_brief_coach_requires_an_input_it_can_observe():
    personas = persona_registry.personas()
    for cid in PB.brief_coaches():
        req = PB.required_metrics(cid)
        assert req, f"{cid} declares no {PB.REQUIRED_KEY}"
        assert set(req) <= set(PB.coach_metrics(cid)), f"{cid}: a required input it can never observe holds it forever"
    assert {cid for cid, p in personas.items() if p.get(PB.REQUIRED_KEY)} <= set(PB.brief_coaches())
