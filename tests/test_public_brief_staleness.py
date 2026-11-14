"""tests/test_public_brief_staleness.py — the nutrition coach never briefs from a stale MacroFactor export (2026-11-12).

MacroFactor arrives only as a manual export (s3://<bucket>/uploads/macrofactor/). A week whose export stopped mid-week can
still carry the 3 readings an observation needs, so "required input present" is not enough. Pins, offline:

  1. THE HOLD. A coach with ``public_brief_fresh_within_days`` whose required input has no reading on or after the floor
     (the run's Monday minus N days) is HELD ``inputs_stale`` with the input's name, before any model call, writing
     nothing. Must-fail control: the identical fixture with the requirement removed writes a brief from the stale week.
     A fresh series (the floor day itself) is briefed. A malformed requirement holds (fail closed).
  2. THE STAMP AND THE DEAD-MAN. The hold is stamped with its reason and inputs, and the nightly dead-man WARNs (a
     sanctioned honest hold), never OKs it and never FAILs it.
  3. THE PRE-RUN SIGNAL. ``public_brief:macrofactor_export_age`` WARNs from Saturday while an export can still land: an
     export older than 3 days, or (Sunday/Monday) logged days that end before the floor. Must-fail controls: the same
     store on a Thursday is OK (not yet watched); a fresh export on Sunday is OK; a summary-only stub is not a logged day.
"""

import json
import os
import sys
from datetime import datetime, timezone

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
from test_public_brief import COACH, SERIES, Table, _reply, good_draft, tolerance_for  # noqa: E402
from test_public_brief_deadman import _Check, _judge  # noqa: E402

CYCLE = "2026-11-16"


def _personas(**over):
    p = dict(persona_registry.personas()[COACH])
    for k, v in over.items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return {COACH: p}


def _run(personas, series):
    invoke = _reply(good_draft())
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
    return out["results"][COACH], invoke, table


def _stopped(last_day):
    """The fixture series with MacroFactor's readings cut after ``last_day`` (weight keeps arriving)."""
    return {m: [(d, v) for d, v in s if m == "weight_lbs" or d <= last_day] for m, s in SERIES.items()}


# ── 1. the hold ─────────────────────────────────────────────────────────────────────────────
def test_the_registry_declares_the_nutrition_freshness_floor():
    assert PB.fresh_within_days(COACH) == 2
    assert PB.fresh_floor(CYCLE, 2) == "2026-11-14"  # Saturday: a reading Saturday or Sunday is fresh for Monday


def test_an_export_that_stopped_mid_week_holds_the_coach_before_any_call():
    res, invoke, table = _run(_personas(), _stopped("2026-11-12"))  # 4 readings in the last 7 days: enough to observe
    assert res == {
        "status": "held",
        "reason": "inputs_stale",
        "stale": ["total_calories_kcal"],
        "fresh_from": "2026-11-14",
        "evidence_written": 0,
    }
    assert invoke.calls == [] and table.puts == []


def test_must_fail_control_without_the_requirement_the_stale_week_is_briefed():
    res, invoke, table = _run(_personas(public_brief_fresh_within_days=None), _stopped("2026-11-12"))
    assert res["status"] == "written" and len(invoke.calls) == 1  # the defect the hold prevents
    brief = next(r for r in table.puts if r["sk"] == POL.brief_sk(CYCLE))
    cal = next(o for o in brief["observations"] if o["metric"] == "total_calories_kcal")
    assert cal["latest"]["date"] == "2026-11-12"


def test_a_reading_on_the_floor_day_is_fresh():
    res, _invoke, _table = _run(_personas(), _stopped("2026-11-14"))
    assert res["status"] == "written"
    res, _invoke, _table = _run(_personas(), _stopped("2026-11-13"))  # one day short
    assert res["status"] == "held" and res["reason"] == PB.HELD_STALE


def test_an_absent_input_is_still_held_as_absent_not_stale():
    res, _invoke, _table = _run(_personas(), _stopped("2026-11-09"))  # 1 reading in the last 7 days: no observation
    assert res["reason"] == PB.HELD_FOR_INPUTS and res["missing"] == ["total_calories_kcal"]


@pytest.mark.parametrize("bad", [0, -1, "2", 1.5, True, None])
def test_a_malformed_requirement_holds_fail_closed(bad):
    personas = _personas()
    personas[COACH][PB.FRESH_KEY] = bad
    res, invoke, _table = _run(personas, SERIES)
    assert res["status"] == "held" and res["reason"] == PB.HELD_STALE and invoke.calls == []


# ── 2. the stamp and the dead-man ───────────────────────────────────────────────────────────
def test_the_hold_is_stamped_and_the_dead_man_warns(monkeypatch):
    import common.pacific_time as pt

    real = PB.run
    stopped = _stopped("2026-11-12")
    monkeypatch.setattr(pt, "pacific_today", lambda: CYCLE)
    monkeypatch.setattr(
        PB,
        "run",
        lambda table, **kw: real(
            table,
            invoke=_reply(good_draft()),
            allow=lambda f: True,
            readings=lambda m, s, e: [(d, v) for d, v in stopped.get(m, []) if s <= d <= e],
            tolerance_for=tolerance_for,
            **{**kw, "coach_ids": [COACH]},
        ),
    )
    table = Table()
    PB.handle_event(table, {"mode": "public_brief"})
    stamp = table.store[(PB.RUN_PK, PB.run_sk(CYCLE))]["results"][COACH]
    assert stamp == {"status": "held", "reason": "inputs_stale", "stale": ["total_calories_kcal"], "fresh_from": "2026-11-14"}
    c = _judge(table)
    assert c.state == "warn" and "inputs stale (total_calories_kcal" in c.msg


# ── 3. the pre-run signal ───────────────────────────────────────────────────────────────────
class _Rows:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, **kw):
        self.calls.append(kw)
        eav = kw["ExpressionAttributeValues"]
        return {"Items": [dict(r) for r in self.rows if r["pk"] == eav[":pk"] and eav[":s"] <= r["sk"] <= eav[":e"]]}


def _mf(day, ingested, entries=5):
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{day}", "date": day, "ingested_at": ingested, "entries_count": entries}


EXPORT_1109 = [_mf(f"2026-11-0{d}", "2026-11-10T04:54:39Z") for d in range(3, 10)]


def _age(rows, day, hh=11, mm=30):
    now = lambda: datetime.strptime(f"{day} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M").replace(tzinfo=PACIFIC)  # noqa: E731
    return QA.check_macrofactor_export_age(_Rows(rows), _Check, "content", now, bucket="matthew-life-platform")[0]


def test_an_old_export_warns_from_saturday_with_where_to_upload():
    c = _age(EXPORT_1109, "2026-11-14")
    assert c.state == "warn" and "older than 3 d" in c.msg and "s3://matthew-life-platform/uploads/macrofactor/" in c.msg
    assert "2026-11-16 brief" in c.msg and "nutrition_coach" in c.msg
    assert _age(EXPORT_1109, "2026-11-15").state == "warn"
    assert _age(EXPORT_1109, "2026-11-16", hh=8).state == "warn"  # Monday before the run


def test_must_fail_control_the_same_store_midweek_is_not_yet_watched():
    c = _age(EXPORT_1109, "2026-11-12")
    assert c.state == "ok" and "watched from Saturday" in c.msg and "2.6 d old" in c.msg
    assert _age(EXPORT_1109, "2026-11-16", hh=11).state == "ok"  # Monday after the run: the next cycle's watch is days off


def test_a_fresh_export_reaching_the_floor_is_ok_on_sunday():
    rows = EXPORT_1109 + [_mf(f"2026-11-{d}", "2026-11-15T05:00:00Z") for d in range(10, 15)]
    assert _age(rows, "2026-11-15").state == "ok"


def test_a_fresh_upload_whose_logged_days_end_before_the_floor_warns_on_sunday():
    rows = EXPORT_1109 + [_mf(f"2026-11-{d}", "2026-11-15T05:00:00Z") for d in range(10, 13)]
    c = _age(rows, "2026-11-15")
    assert c.state == "warn" and "no logged day on or after 2026-11-14" in c.msg and "older than" not in c.msg
    assert _age(rows, "2026-11-14").state == "ok"  # Saturday judges age only: Saturday's own day cannot be exported yet


def test_a_summary_only_stub_is_not_a_logged_day():
    rows = EXPORT_1109 + [_mf(f"2026-11-{d}", "2026-11-15T05:00:00Z", entries=0) for d in range(10, 15)]
    c = _age(rows, "2026-11-15")
    assert c.state == "warn" and "logged days through 2026-11-09" in c.msg


def test_no_upload_at_all_warns_and_the_message_carries_no_intake_value():
    c = _age([], "2026-11-14")
    assert c.state == "warn" and "no upload in the last" in c.msg
    rows = [dict(r, total_calories_kcal=2345, total_protein_g=167) for r in EXPORT_1109]
    c = _age(rows, "2026-11-14")
    assert "2345" not in c.msg and "167" not in c.msg


def test_the_watched_coaches_are_derived_from_the_registry():
    assert QA._export_coaches() == [("nutrition_coach", 2)]
    personas = _personas(public_brief_required_metrics=["weight_lbs"])
    assert QA._export_coaches(personas) == []  # no required MacroFactor input: nothing to watch


def test_the_leg_runs_nightly():
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")).read()
    assert '"macrofactor_export_age",' in src and "public_brief_qa.check_macrofactor_export_age(" in src


def test_the_read_is_bounded_and_projected():
    t = _Rows(EXPORT_1109)
    QA.check_macrofactor_export_age(t, _Check, "content", lambda: datetime(2026, 11, 14, 11, 30, tzinfo=PACIFIC))
    kw = t.calls[0]
    assert kw["ExpressionAttributeValues"][":pk"] == "USER#matthew#SOURCE#macrofactor"
    assert "ProjectionExpression" in kw and "total_calories_kcal" not in kw["ProjectionExpression"]
    assert datetime.now(timezone.utc)  # the leg reads the clock only through pt_now
