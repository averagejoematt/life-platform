"""#5793 — the evening protein-remaining nudge: one more slot on the #5098 protein ledger and runner.

Every gram below is DERIVED from the charter (the range low, the feeding threshold, the fat and fibre floors), never
typed: the floor and the intake are owner-only numbers, so the fixtures are offsets from whatever the charter says.

No live clock: every entrypoint takes its instant as an argument (`evening_decide(now_pt=TICK)`,
`runner.run_evening(table, send, TICK_UTC, tier)`).

Must-fail controls: below the range low SENDS; at it and above it are SILENT (the negative controls); no same-day
row is SILENT with the reason stamped; a second tick the same evening never re-sends.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO = os.path.join(os.path.dirname(__file__), "..")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

from common.pacific_time import PACIFIC  # noqa: E402
from emails import protein_nudge_runner as runner  # noqa: E402
from health import (
    macro_floors,  # noqa: E402
    protein_engine as pe,  # noqa: E402
)
from training import steps_nudge, training_charter  # noqa: E402

DAY = "2026-10-20"
NEXT = "2026-10-21"
TICK = datetime(2026, 10, 20, 19, 10, tzinfo=PACIFIC)  # 19:10 PDT: the first hourly :10 tick inside the evening window
TICK_UTC = TICK.astimezone(timezone.utc)  # 02:10Z on the NEXT UTC day — the reason the HAE read spans two rows


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled PUBLIC charter only: no owner twin from the laptop's env, no live S3 probe."""
    monkeypatch.delenv(training_charter.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(training_charter, "_from_s3", lambda key: None)
    training_charter.reset_cache()
    yield
    training_charter.reset_cache()


def _floor() -> float:
    return float(pe.range_low())


def _threshold() -> float:
    return float(training_charter.charter_value("nutrition.protein.feeding_threshold_g"))


def _eating_minutes() -> int:
    return int(round(float(training_charter.charter_value("nutrition.eating_window.eating_hours")) * 60))


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _row(*entries, total=None, **macros):
    """A MacroFactor-shaped day row; `total` defaults to the sum of the entries."""
    log = [{"time": t, "protein_g": g, "food_name": "x"} for t, g in entries]
    row = {"date": DAY, "total_protein_g": total if total is not None else sum(g for _, g in entries), "food_log": log}
    row.update(macros)
    return row


def _open_window_row(total_offset: float, **macros):
    """Two feedings, the first opened recently enough that the window is still open at TICK; total = floor + offset."""
    first = TICK - timedelta(minutes=_eating_minutes() - 90)
    second = first + timedelta(minutes=180)
    total = _floor() + total_offset
    a = _threshold() + 1  # one feeding at the threshold, the rest under it
    return _row((_hhmm(first), a), (_hhmm(second), round(total - a, 1)), total=total, **macros)


def decide(row, **kw):
    args = dict(date=DAY, now_pt=TICK, row=row, already_sent=False, budget_tier=0)
    args.update(kw)
    return pe.evening_decide(**args)


# ── the charter key ───────────────────────────────────────────────────────────────────────────────────────────
def test_evening_window_is_the_steps_nudge_evening_window():
    """A platform default derived from the existing evening pass on the same tick: no new schedule."""
    at = training_charter.charter_value("nutrition.protein.evening_nudge.at_pt")
    end = training_charter.charter_value("nutrition.protein.evening_nudge.window_end_pt")
    assert at == f"{steps_nudge.WINDOW_START_HOUR_PT:02d}:00" and end == f"{steps_nudge.WINDOW_END_HOUR_PT:02d}:00"
    assert "platform default" in training_charter.charter_value("nutrition.protein.evening_nudge.provenance")
    assert training_charter.charter_value("nutrition.protein.evening_nudge.max_per_day") == 1


# ── the verdict: the must-fail pair ───────────────────────────────────────────────────────────────────────────
def test_below_range_low_sends_with_grams_remaining_and_feedings_left():
    v = decide(_open_window_row(-12))
    assert v["send"] and v["reason"] == "below_range_low"
    assert v["remaining_g"] == pytest.approx(12.0) and v["total_g"] == pytest.approx(_floor() - 12)
    counted = sum(1 for f in v["feedings"] if f["g"] >= _threshold())
    assert v["window"]["open"] and v["feedings_counted"] == counted >= 1
    target = int(training_charter.charter_value("nutrition.protein.feedings_per_day"))
    assert v["feedings_left"] == max(0, target - counted)
    assert f"{12.0:g} g short of the {_floor():g} g range low" in v["text"]
    assert f"with {max(0, target - counted)} of them left in it" in v["text"]
    assert v["key"] == f"PROTEIN_NUDGE#{DAY}#evening" and v["key"] != pe.idempotency_key(DAY)


def test_at_or_above_range_low_is_silent():
    """Negative control: THE hit is strict at the range low, so exactly the floor is met and nothing sends."""
    for offset in (0, 0.1, 25):
        v = decide(_open_window_row(offset))
        assert not v["send"] and v["reason"] == "floor_met" and "text" not in v, offset


def test_a_tenth_under_the_floor_still_sends():
    assert decide(_open_window_row(-0.1))["send"]


def test_no_same_day_row_is_silent_with_the_reason():
    v = decide(None)
    assert not v["send"] and v["reason"] == "no_same_day_log" and "total_g" not in v


def test_a_row_with_no_protein_figure_is_unknown_not_zero():
    v = decide({"date": DAY, "food_log": []})
    assert not v["send"] and v["reason"] == "intake_unknown"


def test_rails_budget_window_already_sent():
    row = _open_window_row(-12)
    assert decide(row, budget_tier=pe.BUDGET_SILENCE_TIER)["reason"] == f"budget_tier_{pe.BUDGET_SILENCE_TIER}"
    assert decide(row, budget_tier=pe.BUDGET_SILENCE_TIER - 1)["send"]
    assert decide(row, already_sent=True)["reason"] == "already_sent"
    assert decide(row, now_pt=TICK.replace(hour=18, minute=59))["reason"] == "outside_window"
    assert decide(row, now_pt=TICK.replace(hour=21, minute=0))["reason"] == "outside_window"


def test_closed_window_states_no_feedings_left():
    first = TICK - timedelta(minutes=_eating_minutes() + 60)
    v = decide(_row((_hhmm(first), _floor() - 30)))
    assert v["send"] and v["window"]["open"] is False and v["feedings_left"] == 0
    assert "closed at" in v["text"] and "left in it" not in v["text"]


def test_copy_is_information_not_a_command():
    text = decide(_open_window_row(-12))["text"]
    for imperative in ("you should", "you must", "eat ", "make sure", "don't forget"):
        assert imperative not in text.lower()


# ── fat and fibre: one line each, only when below their floors ────────────────────────────────────────────────
def test_fat_and_fibre_ride_one_line_each_when_below():
    fat, fibre = macro_floors.floor_g("fat"), macro_floors.floor_g("fibre")
    v = decide(_open_window_row(-12, total_fat_g=fat - 5, total_fiber_g=fibre - 3))
    assert len(v["macro_lines"]) == 2
    assert v["text"].count(" floor.") == 2 and "Fat " in v["text"] and "Fibre " in v["text"]


def test_a_met_or_unknown_macro_gets_no_line():
    fat = macro_floors.floor_g("fat")
    v = decide(_open_window_row(-12, total_fat_g=fat))  # fat met, fibre absent (unknown)
    assert v["macro_lines"] == [] and v["macro_floors"]["fibre"]["unknown"] is True
    assert "Fat " not in v["text"] and "Fibre " not in v["text"]


def test_macros_never_trigger_the_note_on_their_own():
    fat = macro_floors.floor_g("fat")
    v = decide(_open_window_row(5, total_fat_g=fat - 20))
    assert not v["send"] and v["reason"] == "floor_met"


# ── the runner: the read, the claim, the stamp ────────────────────────────────────────────────────────────────
class _Table:
    def __init__(self, rows=None):
        self.items = {}
        for r in rows or []:
            self.items[(r["pk"], r["sk"])] = dict(r)

    def get_item(self, Key, **_kw):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        k = (Item["pk"], Item["sk"])
        if ConditionExpression and k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        it = self.items[(Key["pk"], Key["sk"])]
        it["status"], it["text"], it["error"] = (ExpressionAttributeValues[x] for x in (":s", ":t", ":e"))


def _mf(row):
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{DAY}", **row}


def _hae(utc_date, entries):
    return {"pk": "USER#matthew#SOURCE#apple_health", "sk": f"DATE#{utc_date}", "_rd_protein_hae": entries}


def _entry(pt: datetime, g: float):
    utc = pt.astimezone(timezone.utc)
    return {utc.strftime("%Y-%m-%dT%H:%M"): {"t": utc.isoformat(), "g": g}}


def test_runner_sends_once_an_evening_and_stamps_every_tick():
    t, sent = _Table([_mf(_open_window_row(-12))]), []
    first = runner.run_evening(t, sent.append, TICK_UTC, 0)
    second = runner.run_evening(t, sent.append, TICK_UTC + timedelta(hours=1), 0)
    assert first["send"] and first["key"] == f"PROTEIN_NUDGE#{DAY}#evening"
    assert not second["send"] and second["reason"] == "already_sent" and len(sent) == 1
    assert t.items[(runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}#evening")]["status"] == "sent"
    assert (runner.LEDGER_PK, f"EVAL_EVENING#{DAY}") in t.items
    assert (runner.LEDGER_PK, f"EVAL#{DAY}") not in t.items  # never feeds the breakfast dead-man


def test_breakfast_claim_does_not_block_the_evening_slot():
    t, sent = _Table([_mf(_open_window_row(-12)), {"pk": runner.LEDGER_PK, "sk": pe.idempotency_key(DAY), "status": "sent"}]), []
    assert runner.run_evening(t, sent.append, TICK_UTC, 0)["send"] and len(sent) == 1


def test_runner_floor_met_is_silent_but_stamped():
    t, sent = _Table([_mf(_open_window_row(0))]), []
    assert runner.run_evening(t, sent.append, TICK_UTC, 0)["reason"] == "floor_met" and not sent
    assert t.items[(runner.LEDGER_PK, f"EVAL_EVENING#{DAY}")]["send"] is False
    assert (runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}#evening") not in t.items


def test_runner_no_source_row_is_silent_with_the_reason_stamped():
    t, sent = _Table(), []
    assert runner.run_evening(t, sent.append, TICK_UTC, 0)["reason"] == "no_same_day_log" and not sent
    stamp = t.items[(runner.LEDGER_PK, f"EVAL_EVENING#{DAY}")]
    assert stamp["reason"] == "no_same_day_log" and stamp["source"] == "none"
    assert stamp["version"] == pe.EVENING_NUDGE_VERSION


def test_runner_hae_read_spans_both_utc_rows_and_keeps_only_the_pacific_day():
    """A Pacific evening is past UTC midnight: the late feeding sits on the NEXT UTC row and must count; the next
    Pacific day's early entry on that same row must not."""
    early, late = TICK.replace(hour=12, minute=0), TICK.replace(hour=17, minute=30)
    tomorrow = TICK + timedelta(days=1, hours=-10)  # next Pacific morning, same next-UTC row
    a, b = _threshold() + 1, _floor() / 4
    assert late.astimezone(timezone.utc).date().isoformat() == NEXT == tomorrow.astimezone(timezone.utc).date().isoformat()
    t, sent = _Table([_hae(DAY, _entry(early, a)), _hae(NEXT, {**_entry(late, b), **_entry(tomorrow, _floor())})]), []
    out = runner.run_evening(t, sent.append, TICK_UTC, 0)
    assert out["send"] and len(sent) == 1
    stamp = t.items[(runner.LEDGER_PK, f"EVAL_EVENING#{DAY}")]
    assert stamp["source"] == "hae_intraday"
    expected_remaining = round(_floor() - round(a + b, 1), 1)
    assert f"{expected_remaining:g} g short" in sent[0]
    # the HAE feed carries no fat or fibre: no line, never a guess
    assert "Fat " not in sent[0] and "Fibre " not in sent[0]


def test_runner_hae_late_entry_alone_reaches_the_floor_silently():
    """Must-fail mirror of the two-row read: if the next UTC row were ignored, this day would wrongly send."""
    early, late = TICK.replace(hour=12, minute=0), TICK.replace(hour=17, minute=30)
    t, sent = _Table([_hae(DAY, _entry(early, _floor() / 2)), _hae(NEXT, _entry(late, _floor() / 2))]), []
    assert runner.run_evening(t, sent.append, TICK_UTC, 0)["reason"] == "floor_met" and not sent


def test_runner_outside_window_touches_nothing():
    t = _Table()
    assert runner.run_evening(t, lambda s: None, TICK_UTC - timedelta(hours=2), 0)["reason"] == "outside_window" and not t.items


def test_runner_send_failure_is_recorded_not_raised():
    def boom(_):
        raise RuntimeError("ses down")

    t = _Table([_mf(_open_window_row(-12))])
    assert runner.run_evening(t, boom, TICK_UTC, 0)["reason"] == "send_failed"
    assert t.items[(runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}#evening")]["status"] == "failed"


def test_evening_stamp_sits_outside_the_breakfast_dead_mans_range():
    """`check_protein_nudge_liveness` queries sk BETWEEN EVAL#<first> AND EVAL#<last>: an evening stamp inside that
    range would make a dead breakfast pass look alive."""
    lo, hi = "EVAL#2026-10-18", "EVAL#2026-10-20"
    assert not (lo <= f"{runner.EVENING_EVAL_PREFIX}2026-10-19" <= hi)


# ── the wiring: the coach-nudge tick carries the pass ─────────────────────────────────────────────────────────
def test_coach_nudge_tick_runs_the_evening_pass(monkeypatch):
    from emails import coach_nudge_lambda as cn

    t, mails = _Table([_mf(_open_window_row(-12))]), []
    monkeypatch.setattr(cn, "_table", lambda: t)
    monkeypatch.setattr(cn.budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(cn, "_send_steps_email", lambda text, dry_run, subject="", label="": mails.append((subject, label, dry_run)))
    out = cn._protein_evening_pass(TICK_UTC, True)
    assert out["send"] and mails == [("Protein this evening", "Protein note", True)]
    assert t.items[(runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}#evening")]["status"] == "dry_run"


# ── the evening dead-man (qa-smoke): must-fail controls on an injected frozen clock ───────────────────────────
class _QaTable:
    def __init__(self, days=(), boom=False):
        self.sks, self.boom, self.queries = [f"EVAL_EVENING#{d}" for d in days], boom, 0

    def query(self, **kw):
        self.queries += 1
        if self.boom:
            raise RuntimeError("ddb down")
        return {"Items": [{"sk": s} for s in self.sks]}


class _QaCheck:
    def __init__(self, name, *_):
        self.name, self.status, self.msg = name, None, ""

    def ok(self, m=""):
        self.status, self.msg = "ok", m

    def fail(self, m=""):
        self.status, self.msg = "fail", m

    def warn(self, m="", chronic=False):
        self.status, self.msg = "warn", m


def _evening_check(table, hour, day=14):
    from datetime import datetime

    from operational import nudge_ledger_qa as q

    return q.check_protein_evening_liveness(table, _QaCheck, "t", lambda: datetime(2026, 11, day, hour, 0), armed_on="2026-11-13")[0]


def test_dead_man_fails_when_a_completed_evening_has_no_stamp():
    assert _evening_check(_QaTable([]), 22, day=14).status == "fail"  # 11-14 closed, nothing stamped
    assert _evening_check(_QaTable(["2026-11-13"]), 22, day=14).status == "fail"  # 11-14 itself still missing
    assert _evening_check(_QaTable(["2026-11-14"]), 8, day=15).status == "fail"  # 11-13 missing the next morning


def test_dead_man_is_not_yet_due_inside_or_before_the_window():
    assert _evening_check(_QaTable([]), 20, day=13).status == "ok"  # tonight's window still open, nothing earlier is armed
    t = _QaTable([])
    assert _evening_check(t, 12, day=13).status == "ok" and t.queries == 0
    assert _evening_check(_QaTable([]), 22, day=12).status == "ok"  # grace day: first evening after deploy is unjudged


def test_dead_man_ok_when_every_completed_evening_is_stamped_and_read_failure_warns():
    assert _evening_check(_QaTable(["2026-11-13", "2026-11-14"]), 22, day=14).status == "ok"
    assert _evening_check(_QaTable(boom=True), 22, day=14).status == "warn"


def test_dead_man_prefix_matches_the_writer_and_is_wired_into_qa_smoke():
    import inspect

    from operational import nudge_ledger_qa as q, qa_smoke_lambda as qs

    assert q.PROTEIN_EVENING_EVAL_PREFIX == runner.EVENING_EVAL_PREFIX
    assert "check_protein_evening_liveness" in inspect.getsource(qs)
