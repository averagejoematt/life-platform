"""#5132 box 3 - the morning check-in's weekday dead-man.

The worker stamps ``COACH#morning_checkin / EVAL#<Pacific day>`` with its outcome on every weekday run
(``coach.morning_checkin_ledger``); ``nudge_ledger_qa.check_morning_checkin_liveness`` (nightly qa-smoke) reds when
the two newest completed weekdays carry neither a send nor a sanctioned skip, and warns when the same sanctioned
skip repeats for a whole week. Every clock below is a fixed instant: the expectations never read the live clock.

Calendar (2026): Mon 10-26, Tue 10-27, Wed 10-28, Thu 10-29, Fri 10-30, Sat 10-31, Sun 11-01, Mon 11-02.
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from coach import morning_checkin_ledger as ledger  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from operational import nudge_ledger_qa as q  # noqa: E402

ARMED = "2026-10-01"  # well before every fixture day, so the arming date never decides a verdict here


class _Check:
    def __init__(self, name, cat, tier):
        self.name, self.state, self.msg = name, None, ""

    def ok(self, m=""):
        self.state, self.msg = "ok", m
        return self

    def fail(self, m=""):
        self.state, self.msg = "fail", m
        return self

    def warn(self, m="", chronic=False):
        self.state, self.msg = "warn", m
        return self


class _QTable:
    def __init__(self, rows=(), boom=False):
        self._rows, self._boom = rows, boom

    def query(self, **kw):
        if self._boom:
            raise RuntimeError("ddb down")
        return {"Items": list(self._rows)}


def _rows(**by_day):
    """{'2026-10-30': 'sent'} -> ledger rows. Keys are passed as d_2026_10_30 for kwarg syntax."""
    return [{"pk": ledger.LEDGER_PK, "sk": f"EVAL#{d.replace('d_', '').replace('_', '-')}", "reason": r} for d, r in by_day.items()]


def _run(rows, today, armed_on=ARMED, boom=False):
    now = datetime(*today, 11, 30, tzinfo=PACIFIC)  # the 18:30Z QA run, after the 17:15Z worker run
    return q.check_morning_checkin_liveness(_QTable(rows, boom), _Check, "t", lambda: now, armed_on=armed_on)[0]


MON, TUE, WED, FRI_NEXT_MON = (2026, 10, 26), (2026, 10, 27), (2026, 10, 28), (2026, 11, 2)


def test_sent_yesterday_is_ok():
    c = _run(_rows(d_2026_10_27="sent"), WED)
    assert c.state == "ok" and c.name == "morning_checkin:weekday_liveness"


def test_two_weekdays_with_nothing_fails_and_names_both_days():
    c = _run(_rows(d_2026_10_22="sent"), WED)  # Tue 10-27 and Mon 10-26 are bare
    assert c.state == "fail" and "2026-10-27=no row" in c.msg and "2026-10-26=no row" in c.msg


def test_one_bare_weekday_is_not_yet_a_fault():
    assert _run(_rows(d_2026_10_26="sent"), WED).state == "ok"  # Tue bare, Mon sent


def test_saturday_and_sunday_never_count():
    # Monday morning: Fri sent, Sat+Sun bare. The weekend is not two silent days.
    assert _run(_rows(d_2026_10_30="sent"), FRI_NEXT_MON).state == "ok"
    # ... and a bare Friday + Thursday still fails ACROSS the weekend, on the two newest WEEKDAYS.
    c = _run(_rows(d_2026_10_28="sent"), FRI_NEXT_MON)
    assert c.state == "fail" and "2026-10-30=no row" in c.msg and "2026-10-29=no row" in c.msg
    # Tuesday after: Monday bare, Friday bare (the weekend between them is skipped) -> two weekdays in a row.
    c = _run(_rows(d_2026_10_29="sent"), (2026, 11, 3))
    assert c.state == "fail" and "2026-11-02=no row" in c.msg and "2026-10-30=no row" in c.msg
    # A Sat/Sun row, were one ever written, must not rescue two bare weekdays.
    c = _run(_rows(d_2026_10_31="sent", d_2026_11_01="sent"), FRI_NEXT_MON)
    assert c.state == "fail"


def test_every_sanctioned_skip_counts_as_an_outcome():
    for reason in ledger.SANCTIONED_SKIPS:
        c = _run(_rows(d_2026_10_27=reason, d_2026_10_26=reason), WED)
        assert c.state == "ok", (reason, c.msg)


def test_an_unsanctioned_outcome_is_silence():
    for reason in ("empty", "error:KeyError", "unknown:wat", ""):
        c = _run(_rows(d_2026_10_27=reason, d_2026_10_26=reason), WED)
        assert c.state == "fail", (reason, c.msg)
    assert "2026-10-27=error:KeyError" in _run(_rows(d_2026_10_27="error:KeyError", d_2026_10_26="empty"), WED).msg


def test_a_skip_that_repeats_for_a_week_warns_but_a_send_in_the_window_clears_it():
    today = (2026, 11, 3)  # Tue: the five newest completed weekdays are 11-02, 10-30, 10-29, 10-28, 10-27
    days = ("d_2026_11_02", "d_2026_10_30", "d_2026_10_29", "d_2026_10_28", "d_2026_10_27")
    latched = _run(_rows(**{d: "silence_respected" for d in days}), today)
    assert latched.state == "warn" and "silence_respected" in latched.msg
    four = _run(_rows(**{d: "silence_respected" for d in days[:4]}), today)
    assert four.state == "ok"  # four is not a week
    mixed = _run(_rows(**{d: ("sent" if d == "d_2026_10_29" else "silence_respected") for d in days}), today)
    assert mixed.state == "ok"
    different = _run(_rows(**{d: ("budget" if d == "d_2026_10_29" else "silence_respected") for d in days}), today)
    assert different.state == "ok"  # the reason changed: someone is acting on it
    assert _run(_rows(**{d: "sent" for d in days}), today).state == "ok"  # a feature that sends is never warned


def test_pending_until_armed_and_a_ddb_error_fails_loudly():
    c = _run([], (2026, 10, 26), armed_on="2026-10-27")  # today is the arming eve: no completed armed day
    assert c.state == "ok" and "pending" in c.msg
    c = _run([], WED, armed_on="2026-10-27")  # only Tue 10-27 is judgeable: one bare day is not two
    assert c.state == "ok"
    c = _run([], (2026, 10, 29), armed_on="2026-10-27")  # Tue + Wed both bare and armed
    assert c.state == "fail"
    assert _run([], WED, boom=True).state == "fail"


# ── the write half ───────────────────────────────────────────────────────────────────────────────


class _Table:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def put_item(self, Item, ConditionExpression=None):
        if self.fail:
            raise RuntimeError("throttled")
        self.store[(Item["pk"], Item["sk"])] = dict(Item)


def test_pair_contract_writer_and_reader_agree_on_the_row():
    assert q.MORNING_CHECKIN_LEDGER_PK == ledger.LEDGER_PK and q.STEPS_EVAL_PREFIX == ledger.EVAL_PREFIX
    t = _Table()
    ledger.stamp(t, "2026-10-27", "sent", datetime(2026, 10, 27, 17, 15, tzinfo=timezone.utc))
    row = t.store[(ledger.LEDGER_PK, "EVAL#2026-10-27")]
    assert row["reason"] == "sent" and row["version"] == ledger.VERSION and all(isinstance(v, str) for v in row.values())
    # What the writer stored is what the reader accepts.
    c = _run([row], WED)
    assert c.state == "ok"


def test_a_failing_stamp_never_blocks_the_run():
    ledger.stamp(_Table(fail=True), "2026-10-27", "sent", datetime(2026, 10, 27, 17, 15, tzinfo=timezone.utc))


def test_every_reason_the_worker_can_return_has_a_stored_token():
    """The derivation guard: the set of ``reason`` literals comes from the worker's own source."""
    src = open(os.path.join(REPO, "lambdas", "coach", "telegram_worker_lambda.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_morning_checkin")
    reasons = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "reason" and isinstance(v, ast.Constant):
                    reasons.add(v.value)
    assert {"weekend", "dark", "quiet hours", "silence respected", "budget", "capped", "held", "empty"} <= reasons
    for r in reasons - {"weekend"}:
        assert not ledger.reason_token({"ok": True, "reason": r}).startswith("unknown:"), r
    assert ledger.reason_token({"ok": True, "status": "grounded", "bubbles": 2}) == ledger.SENT
    # Every sanctioned token is reachable from the worker; the only unsanctioned ones are empty/unknown.
    assert {ledger.reason_token({"reason": r}) for r in reasons - {"weekend"}} == set(ledger.SANCTIONED_SKIPS) | {"empty"}


@pytest.fixture
def worker(monkeypatch):
    from coach import telegram_worker_lambda as w

    table = _Table()
    monkeypatch.setattr(w, "_table", lambda: table)
    monkeypatch.setattr(w, "_s3_client", lambda: None)
    return w, table


def _at(monkeypatch, w, when):
    monkeypatch.setattr(w, "_pacific_now", lambda: when)


def test_worker_stamps_the_sent_outcome(worker, monkeypatch):
    w, table = worker
    _at(monkeypatch, w, datetime(2026, 10, 27, 10, 15, tzinfo=PACIFIC))
    monkeypatch.setattr(w, "_morning_checkin", lambda: {"ok": True, "status": "grounded", "bubbles": 2})
    assert w.lambda_handler({"kind": "morning_checkin"}, None)["bubbles"] == 2
    assert table.store[(ledger.LEDGER_PK, "EVAL#2026-10-27")]["reason"] == "sent"


def test_worker_stamps_a_real_dark_run_and_never_stamps_a_weekend(worker, monkeypatch):
    w, table = worker
    import coach.persona_registry as reg

    monkeypatch.setattr(reg, "resolve", lambda *a, **k: {})  # no telegram_route -> dark, through the REAL inner function
    _at(monkeypatch, w, datetime(2026, 10, 27, 10, 15, tzinfo=PACIFIC))
    assert w.lambda_handler({"kind": "morning_checkin"}, None)["reason"] == "dark"
    assert table.store[(ledger.LEDGER_PK, "EVAL#2026-10-27")]["reason"] == "dark"
    _at(monkeypatch, w, datetime(2026, 10, 31, 10, 15, tzinfo=PACIFIC))  # a Saturday
    assert w.lambda_handler({"kind": "morning_checkin"}, None)["reason"] == "weekend"
    assert (ledger.LEDGER_PK, "EVAL#2026-10-31") not in table.store


def test_worker_stamps_a_crash_as_unsanctioned_and_still_raises(worker, monkeypatch):
    w, table = worker
    _at(monkeypatch, w, datetime(2026, 10, 27, 10, 15, tzinfo=PACIFIC))

    def boom():
        raise KeyError("x")

    monkeypatch.setattr(w, "_morning_checkin", boom)
    with pytest.raises(KeyError):
        w.lambda_handler({"kind": "morning_checkin"}, None)
    assert table.store[(ledger.LEDGER_PK, "EVAL#2026-10-27")]["reason"] == "error:KeyError"


def test_dead_man_is_registered_in_the_nightly_run():
    src = open(os.path.join(REPO, "lambdas", "operational", "qa_smoke_lambda.py"), encoding="utf-8").read()
    assert "nudge_ledger_qa.check_morning_checkin_liveness(" in src
