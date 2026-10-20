"""tests/test_lab_followup_5111.py — the follow-up draw cadence and the owner-only priorities seam (#5111; ingest #4639).

Holds: the lab_draw cycle (ok / due inside the reminder window / overdue) from the charter cadence; the owner-only fallback date
when no draw is readable; the reminder key is once per cycle and a new draw opens a new key; a broken read is read_failed; the
priorities seam is absent -> nothing, present -> the owner context only, never a published one. Neutral fixtures: no result,
marker or diagnosis appears here. The publish-tree privacy sweep lives in test_calibration_cadence_5061.py.

No clock is read: every `today` is a fixed date; the cycle length comes from the same charter values the code reads (#4848).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from coach import coach_event_triggers as cet  # noqa: E402
from training import (  # noqa: E402
    calibration_cadence as cc,  # noqa: E402
    coach_context,
    lab_priorities,
)
from training.training_charter import charter_value  # noqa: E402

CYCLE = int(charter_value("nutrition.labs.follow_up_weeks")) * 7
LEAD = int(charter_value("nutrition.labs.reminder_lead_days"))
LAST = "2026-10-05"


def plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def lab(today, draws=()):
    return cc.compute(today, {"lab_draw": lambda: list(draws)}, anchor="2026-09-06")["kinds"]["lab_draw"]


def test_the_cadence_is_the_charters():
    assert (CYCLE, LEAD) == (112, 14)
    assert lab(plus(LAST, 1), [LAST])["due_on"] == plus(LAST, CYCLE)


def test_ok_then_due_inside_the_window_then_overdue():
    due = plus(LAST, CYCLE)
    assert lab(plus(due, -LEAD - 1), [LAST])["state"] == cc.OK
    assert lab(plus(due, -LEAD), [LAST])["state"] == cc.DUE
    assert lab(due, [LAST])["state"] == cc.DUE
    assert lab(plus(due, 1), [LAST])["state"] == cc.OVERDUE
    assert lab(plus(due, CYCLE * 3), [LAST])["state"] == cc.OVERDUE  # never the behavioural dead-man


def test_the_reminder_is_once_per_cycle_and_a_new_draw_opens_a_new_key():
    t1, t2 = plus(LAST, CYCLE - LEAD), plus(LAST, CYCLE + 3)
    k1 = [e["event_id"] for e in cet.detect_calibration({"kinds": {"lab_draw": lab(t1, [LAST])}}, t1)]
    k2 = [e["event_id"] for e in cet.detect_calibration({"kinds": {"lab_draw": lab(t2, [LAST])}}, t2)]
    assert k1 == k2 == [f"CALIB_PROMPT#lab_draw#{LAST}"]
    new = plus(LAST, CYCLE + 5)
    assert lab(plus(new, CYCLE), [LAST, new])["prompt_key"] == f"CALIB_PROMPT#lab_draw#{new}"


def test_no_prompt_text_carries_a_result():
    row = lab(plus(LAST, CYCLE), [LAST])
    stripped = row["prompt"].replace(plus(LAST, CYCLE), "").replace(LAST, "")  # the two dates are the only digits allowed
    assert "follow-up draw" in row["prompt"] and not any(ch.isdigit() for ch in stripped)


def test_no_draw_and_no_owner_date_is_unknown_not_a_guess():
    r = lab("2026-10-19")
    assert r["state"] == cc.UNKNOWN and r["prompt"] is None


def test_the_owner_only_fallback_date_sets_the_due_day(monkeypatch):
    real = cc._cv
    monkeypatch.setattr(cc, "_cv", lambda path, default=None: "2027-01-25" if path == "lab_followup.next_draw_on" else real(path, default))
    r = lab(plus("2027-01-25", -LEAD - 1))
    assert r["due_on"] == "2027-01-25" and r["state"] == cc.OK
    assert lab(plus("2027-01-25", -LEAD))["state"] == cc.DUE
    assert lab("2027-01-25", [LAST])["due_on"] == plus(LAST, CYCLE)  # a real draw outranks the fixed date


def test_a_broken_read_is_read_failed():
    def boom():
        raise RuntimeError("x")

    r = cc.compute("2026-10-19", {"lab_draw": boom})["kinds"]["lab_draw"]
    assert r["state"] == cc.READ_FAILED and r["prompt"] is None


# ── the priorities seam ──────────────────────────────────────────────────────────────────────
ROW = {
    "pk": "USER#matthew#SOURCE#clinical",
    "sk": lab_priorities.SK,
    "text": "  Neutral   fixture priority one.  ",
    "updated_at": "2026-10-19T08:00",
}


def ctx(published=False, rows=None):
    return coach_context.assemble(
        "2026-10-20", packet=None, constraint_block=None, lab_priorities=lab_priorities.from_rows(rows), published=published
    )


def test_absent_says_nothing():
    for rows in (None, [], [{"sk": "EVENT#x"}], [{**ROW, "text": " "}], "nope", {"sk": lab_priorities.SK}):
        c = ctx(rows=rows)
        assert c["lab_priorities"] is None and "LAB-DRIVEN" not in c["text"]


def test_present_reaches_the_owner_context_only():
    c = ctx(rows=[{"sk": "EVENT#x"}, ROW])
    assert c["lab_priorities"]["text"] == "Neutral fixture priority one."
    assert "LAB-DRIVEN PRIORITIES (owner-only)" in c["text"] and "Neutral fixture priority one." in c["text"]
    p = ctx(published=True, rows=[ROW])
    assert p["lab_priorities"] is None and "Neutral fixture" not in p["text"]


def test_the_clinical_renderer_ignores_the_priorities_row():
    from health.clinical_facts import render_clinical_block

    assert "Neutral fixture" not in render_clinical_block([ROW], published=False)
    assert "Neutral fixture" not in render_clinical_block([ROW], published=True)


class _Table:
    """A minimal injected table: pk -> rows, honouring the sk begins_with condition."""

    def __init__(self, parts):
        self.parts = parts

    def query(self, **kw):
        cond = kw["KeyConditionExpression"]
        flat = []

        def walk(c):
            for v in getattr(c, "_values", []):
                if hasattr(v, "_values"):
                    walk(v)
                else:
                    flat.append(v)

        walk(cond)
        pk = next(v for v in flat if isinstance(v, str) and v.startswith("USER#"))
        pref = next((v for v in flat if isinstance(v, str) and not v.startswith("USER#")), "")
        return {"Items": [r for r in self.parts.get(pk, []) if str(r["sk"]).startswith(pref)]}


def test_the_latest_draw_may_live_in_the_clinical_record():
    t = _Table(
        {
            "USER#matthew#SOURCE#labs": [{"sk": "DATE#2026-04-03", "draw_date": "2026-04-03"}],
            "USER#matthew#SOURCE#clinical": [{"sk": "LABS#2026-10-10"}, {"sk": "MED#x"}],
        }
    )
    assert cc.draw_dates(t) == ["2026-04-03", "2026-10-10"]
    row = cc.compute("2026-10-19", cc.table_readers(t), anchor="2026-09-06")["kinds"]["lab_draw"]
    assert row["last_logged"] == "2026-10-10"
    assert row["due_on"] == plus("2026-10-10", CYCLE)
    assert row["state"] == "ok" and row["prompt"] is None
