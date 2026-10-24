"""tests/test_lab_followup_5111.py — the follow-up draw cadence and the owner-only priorities seam (#5111; ingest #4639).

Holds: the lab_draw cycle (ok / due inside the reminder window / overdue) from the charter cadence; the owner-only fallback date
when no draw is readable; the reminder key is once per cycle and a new draw opens a new key; a broken read is read_failed; the
priorities seam is absent -> nothing, present -> the owner context only, never a published one; the dead-man (the charter's weeks past
the due day, still no draw) rides the shared fixed-text alert once per cycle; the next draw's date and state reach the planning
context, the nutrition context and both owner Telegram threads on the owner channel only. Neutral fixtures: no result,
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
DEAD_WEEKS = int(charter_value("nutrition.labs.dead_man_weeks_after_due"))
LAST = "2026-10-05"


def plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def lab(today, draws=()):
    return cc.compute(today, {"lab_draw": lambda: list(draws)}, anchor="2026-09-06")["kinds"]["lab_draw"]


def test_the_cadence_is_the_charters():
    assert (CYCLE, LEAD, DEAD_WEEKS) == (112, 14, 4)
    prov = charter_value("nutrition.labs.provenance")
    assert "platform default" in prov and "pending an owner ruling" in prov  # no number here has an owner ruling yet
    assert lab(plus(LAST, 1), [LAST])["due_on"] == plus(LAST, CYCLE)


def test_ok_then_due_inside_the_window_then_overdue():
    due = plus(LAST, CYCLE)
    assert lab(plus(due, -LEAD - 1), [LAST])["state"] == cc.OK
    assert lab(plus(due, -LEAD), [LAST])["state"] == cc.DUE
    assert lab(due, [LAST])["state"] == cc.DUE
    assert lab(plus(due, 1), [LAST])["state"] == cc.OVERDUE
    dead = plus(due, DEAD_WEEKS * 7)
    assert lab(plus(dead, -1), [LAST])["state"] == cc.OVERDUE
    assert lab(dead, [LAST])["state"] == cc.MISSED_2  # the dead-man: the charter's weeks past the due day, still no draw
    assert lab(dead, [LAST])["dead_man_on"] == dead


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


def test_the_loader_writes_the_priorities_row_the_reader_reads():
    """The owner's paved road (scripts/load_clinical_record.py) and the reader agree on ONE row."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("load_clinical_record", ROOT / "scripts" / "load_clinical_record.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)

    items = loader.build_items({"lab_priorities": {"text": "first flag  second flag"}}, now="2026-10-20T00:00:00+00:00")
    rows = [i for i in items if str(i.get("sk")) == lab_priorities.SK]
    assert len(rows) == 1, items
    assert rows[0]["sk"] == "PRIORITIES#current" and rows[0]["text"] and rows[0]["updated_at"]
    got = lab_priorities.from_rows(items)
    assert got is not None and got["text"] == "first flag second flag"

    assert [
        i
        for i in loader.build_items({"lab_priorities": "not a dict"}, now="2026-10-20T00:00:00+00:00")
        if str(i.get("sk")) == lab_priorities.SK
    ] == []


# ── the dead-man (#5111) ─────────────────────────────────────────────────────────────────────
def test_the_deadman_rides_the_shared_alert_once_per_cycle_with_dates_only():
    from coach import calibration_deadman_alert as cda

    due = plus(LAST, CYCLE)
    row = lab(plus(due, DEAD_WEEKS * 7), [LAST])
    block = {"kinds": {"lab_draw": row}}
    assert cc.deadman_kinds(block) == ["lab_draw"] and cc.prompts_due(block) == []  # the dead-man replaces the prompt
    [alert] = cda.due(block)
    assert alert["event_id"] == f"CALIB_DEADMAN#lab_draw#{LAST}"
    stripped = alert["text"].replace(due, "").replace(LAST, "")
    assert "follow-up lab draw" in alert["text"] and not any(ch.isdigit() for ch in stripped)
    new = plus(due, DEAD_WEEKS * 7 + 1)
    assert lab(plus(new, 1), [LAST, new])["state"] == cc.OK  # a new draw clears it


def test_the_owner_only_date_also_reaches_the_deadman(monkeypatch):
    real = cc._cv
    monkeypatch.setattr(cc, "_cv", lambda path, default=None: "2027-01-25" if path == "lab_followup.next_draw_on" else real(path, default))
    assert lab(plus("2027-01-25", DEAD_WEEKS * 7))["state"] == cc.MISSED_2


# ── the next draw in the coach contexts (#5111) ──────────────────────────────────────────────
def _labs_table(clinical=(), labs=()):
    return _Table({"USER#matthew#SOURCE#clinical": list(clinical), "USER#matthew#SOURCE#labs": list(labs)})


def test_read_carries_the_next_draw_and_the_priorities_from_one_clinical_read():
    calls = []
    t = _labs_table(clinical=[{"sk": "LABS#2026-10-10"}, ROW], labs=[{"sk": "DATE#2026-04-03", "draw_date": "2026-04-03"}])
    real = t.query
    t.query = lambda **kw: calls.append(kw["KeyConditionExpression"]) or real(**kw)
    got = lab_priorities.read(t, "2026-10-23")
    assert got["priorities"]["text"] == "Neutral fixture priority one."
    fu = got["followup"]
    assert (fu["state"], fu["due_on"], fu["last_logged"]) == ("ok", plus("2026-10-10", CYCLE), "2026-10-10")
    assert fu["line"].startswith(f"next follow-up draw due about {plus('2026-10-10', CYCLE)}")
    assert len(calls) == 2  # the clinical partition once (keys + priorities), the labs partition once

    calls.clear()
    held = lab_priorities.read(t, "2026-10-23", rows=[{"sk": "LABS#2026-10-10"}])
    assert held["followup"]["due_on"] == fu["due_on"] and len(calls) == 1  # rows held: the clinical partition is not re-read


def test_the_clinical_projection_names_no_result_attribute():
    seen = {}

    class T:
        def query(self, **kw):
            seen.update(kw)
            return {"Items": []}

    lab_priorities._clinical_keys(T())
    names = {seen["ExpressionAttributeNames"].get(p.strip(), p.strip()) for p in seen["ProjectionExpression"].split(",")}
    assert names == {"sk", "text", "updated_at"}


def test_a_broken_read_says_read_failed_and_never_raises():
    class Boom:
        def query(self, **_):
            raise RuntimeError("x")

    got = lab_priorities.read(Boom(), "2026-10-23")
    assert got["priorities"] is None and got["followup"]["state"] == cc.READ_FAILED
    assert "never guess" in got["followup"]["line"]
    assert lab_priorities.read(_labs_table(), "not-a-day")["followup"]["state"] == cc.READ_FAILED


def test_no_draw_and_no_date_says_unknown():
    fu = lab_priorities.read(_labs_table(), "2026-10-23")["followup"]
    assert fu["state"] == cc.UNKNOWN and "never guess" in fu["line"]


def _fu(today="2026-10-23"):
    return lab_priorities.read(_labs_table(clinical=[{"sk": "LABS#2026-10-10"}, ROW]), today)


def test_the_planning_context_carries_the_next_draw_on_the_owner_channel_only():
    labs = _fu()
    c = coach_context.assemble(
        "2026-10-23", packet=None, constraint_block=None, lab_priorities=labs["priorities"], lab_followup=labs["followup"]
    )
    assert "LAB FOLLOW-UP (owner-only)" in c["text"] and labs["followup"]["due_on"] in c["text"]
    assert coach_context.summary(c)["lab_followup"] == labs["followup"]["line"]
    p = coach_context.assemble(
        "2026-10-23",
        packet=None,
        constraint_block=None,
        lab_priorities=labs["priorities"],
        lab_followup=labs["followup"],
        published=True,
    )
    assert p["lab_followup"] is None and "LAB FOLLOW-UP" not in p["text"] and labs["followup"]["due_on"] not in p["text"]


def test_the_nutrition_context_carries_both_on_the_owner_channel_only():
    labs = _fu()
    cal = {"kcal": 1500, "source": "charter", "provenance": "x"}
    kw = {"calorie": cal, "lab_priorities": labs["priorities"], "lab_followup": labs["followup"]}
    owner = coach_context.nutrition_context("2026-10-23", published=False, **kw)
    assert "LAB-DRIVEN PRIORITIES (owner-only)" in owner["text"] and "LAB FOLLOW-UP (owner-only)" in owner["text"]
    pub = coach_context.nutrition_context("2026-10-23", published=True, **kw)
    assert "LAB" not in pub["text"] and "Neutral fixture" not in pub["text"] and pub["lab_followup"] is None


def test_the_owner_telegram_threads_read_the_lab_lines(monkeypatch):
    from coach import coach_domain_facts as df

    t = _labs_table(clinical=[{"sk": "LABS#2026-10-10"}, ROW])
    monkeypatch.setattr("training.may_tracker.latest_completed_row", lambda table, today: None)
    training = df._training_context("2026-10-23", "CLINICAL BLOCK", t)
    assert "LAB FOLLOW-UP (owner-only)" in training and "Neutral fixture priority one." in training
    nutrition = df._nutrition_context("2026-10-23", t)
    assert "LAB FOLLOW-UP (owner-only)" in nutrition and "Neutral fixture priority one." in nutrition
    assert df._owner_labs(None, "2026-10-23") == {}


def test_the_mcp_planning_context_passes_the_followup(monkeypatch):
    from mcp import plan_helpers as ph

    t = _labs_table(labs=[{"sk": "DATE#2026-10-10", "draw_date": "2026-10-10"}])
    monkeypatch.setattr("mcp.config.table", t, raising=False)
    got = ph._lab_followup([{"sk": "MED#x"}], "2026-10-23")
    assert got["followup"]["due_on"] == plus("2026-10-10", CYCLE)
    assert ph._lab_followup({"state": "read_failed"}, "2026-10-23")["followup"]["state"] == cc.READ_FAILED
