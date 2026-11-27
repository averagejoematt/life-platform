"""tests/test_event_nudge_holds_6302.py — the owner's 2026-11-26 ruling on event-triggered Telegram sends (#6302).

Generic celebration and calibration nudges are HELD by per-item switches (an exact False restores); promised follow-ups,
pre-event reminders, measured-event concern, the early-warning check-in and the support-contact prompts keep sending.
A held send consumes nothing (no event claim, no daily slot) and says so. No clock is read: every moment is injected.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from coach import (  # noqa: E402
    calibration_deadman_alert as cda,
    coach_event_triggers as cet,
    coach_outbound as co,
    support_contact_prompts as scp,
)
from common import outbound_trial as ot  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402

NOW = datetime(2026, 11, 26, 10, 0, tzinfo=PACIFIC)
HOLDS = (
    ot.TELEGRAM_LIFT_PR_HELD,
    ot.TELEGRAM_MILESTONE_HELD,
    ot.TELEGRAM_CALIBRATION_PROMPT_HELD,
    ot.TELEGRAM_CALIBRATION_DEADMAN_TEXT_HELD,
)


@pytest.fixture
def hold(monkeypatch):
    def _set(*items, value=True):
        for i in items:
            monkeypatch.setitem(ot.TRIAL, i, value)

    return _set


class Table:
    def __init__(self):
        self.puts, self.updates = [], []

    def put_item(self, Item, **kw):
        self.puts.append(Item["sk"])

    def update_item(self, **kw):
        self.updates.append(kw)


def ev(kind, provenance, **extra):
    return {
        "kind": kind,
        "event_id": f"{kind}#x",
        "provenance": provenance,
        "persona_id": "physical_coach",
        "evidence": "- e",
        "frame": "f",
        **extra,
    }


LIFT = ev(cet.KIND_LIFT_PR, co.PROVENANCE_CELEBRATION)
MILE_MEASURED = ev(cet.KIND_MILESTONE, co.PROVENANCE_CELEBRATION, ladder="weight", milestone_id="m_w")
MILE_COUNT = ev(cet.KIND_MILESTONE, co.PROVENANCE_CELEBRATION, ladder="streak", milestone_id="m_s")
CALIB = ev(cet.KIND_CALIBRATION_PROMPT, co.PROVENANCE_CALIBRATION)
KEEP = [
    ev(cet.KIND_PROMISE, co.PROVENANCE_PROMISE),
    ev(cet.KIND_PRE_EVENT, co.PROVENANCE_PRE_EVENT),
    ev(cet.KIND_RECOVERY_SLIDE, co.PROVENANCE_CONCERN),
    ev(cet.KIND_EARLY_WARNING, co.PROVENANCE_CONCERN),
]


def sweep(monkeypatch, events, digest_ids=frozenset()):
    spoke, t = [], Table()
    monkeypatch.setattr(cet, "candidates", lambda s, today: list(events))
    monkeypatch.setattr(cet, "_celebration_allowed", lambda table, today: True)
    out = cet.run_sweep(
        now_pt=NOW,
        table=t,
        seat=lambda p: ("tok", 1),
        speak=lambda e, tok, chat: spoke.append(e["kind"]) or {"ok": True},
        chat_rows=lambda p: [],
        tier=0,
        signals={"milestone_digest_sent": set(digest_ids)},
    )
    return out, spoke, t


@pytest.mark.parametrize("event", [LIFT, MILE_COUNT, CALIB])
def test_held_kinds_send_nothing_and_consume_nothing(hold, monkeypatch, event):
    hold(*HOLDS)
    out, spoke, t = sweep(monkeypatch, [event])
    assert spoke == [] and t.puts == [] and t.updates == []  # no event claim, no daily slot spent
    assert out["reason"] == "held by owner ruling, not sent" and out["candidates"] == 1 and out["held"] == 1


@pytest.mark.parametrize("event", [LIFT, MILE_COUNT, MILE_MEASURED, CALIB])
def test_each_hold_restores_with_an_exact_false(hold, monkeypatch, event):
    hold(*HOLDS, value=False)
    out, spoke, t = sweep(monkeypatch, [event])
    assert spoke == [event["kind"]] and t.puts  # claimed and spoken


def test_restoring_one_item_leaves_the_others_held(hold, monkeypatch):
    hold(*HOLDS)
    hold(ot.TELEGRAM_LIFT_PR_HELD, value=False)
    assert sweep(monkeypatch, [LIFT])[1] == [cet.KIND_LIFT_PR]
    assert sweep(monkeypatch, [CALIB])[1] == []


def test_a_measured_milestone_he_has_not_been_told_still_sends(hold, monkeypatch):
    hold(*HOLDS)
    assert sweep(monkeypatch, [MILE_MEASURED], digest_ids=set())[1] == [cet.KIND_MILESTONE]


def test_a_milestone_the_digest_already_mailed_is_held(hold, monkeypatch):
    hold(*HOLDS)
    assert sweep(monkeypatch, [MILE_MEASURED], digest_ids={"m_w"})[1] == []


def test_an_unreadable_digest_cursor_holds_the_milestone(hold, monkeypatch):
    hold(*HOLDS)
    spoke = []
    monkeypatch.setattr(cet, "candidates", lambda s, today: [MILE_MEASURED])
    cet.run_sweep(
        now_pt=NOW, table=Table(), seat=lambda p: ("t", 1), speak=lambda e, *a: spoke.append(1) or {}, chat_rows=lambda p: [], signals={}
    )
    assert spoke == []


@pytest.mark.parametrize("event", KEEP, ids=lambda e: e["kind"])
def test_keep_kinds_still_send_with_every_hold_on(hold, monkeypatch, event):
    hold(*HOLDS)
    out, spoke, t = sweep(monkeypatch, [event])
    assert spoke == [event["kind"]]


def test_a_held_candidate_does_not_block_a_kept_one_behind_it(hold, monkeypatch):
    hold(*HOLDS)
    assert sweep(monkeypatch, [LIFT, KEEP[0]])[1] == [cet.KIND_PROMISE]


def test_the_sweep_heartbeat_count_still_includes_held_candidates(hold, monkeypatch):
    hold(*HOLDS)
    assert sweep(monkeypatch, [LIFT, CALIB])[0]["candidates"] == 2


# ── the calibration dead-man's Telegram text ──────────────────────────────────────────────────


def _block(extra=None):
    row = {
        "kind": "tape",
        "state": "missed_2",
        "cycle_start": "2026-11-01",
        "missed_cycles": 2,
        "due_on": "2026-11-15",
        "last_logged": None,
    }
    kinds = {"tape": row}
    if extra:
        kinds["titration"] = {
            "kind": "titration",
            "state": "missed_2",
            "cycle_start": "2026-11-09",
            "alert": "Weekly calorie decision was not made.",
        }
    return {"kinds": kinds}


def _deadman(block):
    t, sent = Table(), []
    out = cda.run(t, NOW, lambda p: ("tok", 1), lambda tok, chat, text: sent.append(text) or True, block=block)
    return out, sent, t


def test_deadman_text_held_sends_nothing_claims_nothing_and_says_so(hold):
    hold(*HOLDS)
    out, sent, t = _deadman(_block())
    assert sent == [] and t.puts == [] and out["reason"] == "held by owner ruling, not sent" and out["sent"] == []


def test_deadman_text_restored_by_an_exact_false(hold):
    hold(*HOLDS, value=False)
    out, sent, t = _deadman(_block())
    assert len(sent) == 1 and out["sent"] == ["tape"] and t.puts


def test_a_row_naming_its_own_alert_is_operational_and_still_sends(hold):
    hold(*HOLDS)
    out, sent, t = _deadman(_block(extra=True))
    assert out["sent"] == ["titration"] and len(sent) == 1 and "Weekly calorie decision" in sent[0] and "tape" not in sent[0]


def test_the_email_alarm_leg_is_untouched():
    import inspect

    assert "outbound_trial" not in inspect.getsource(__import__("mcp.calibration_leg", fromlist=["x"]))


# ── KEEP: the support-contact prompts are not on the switchboard ─────────────────────────────


def test_support_contact_prompts_still_send_with_every_hold_on(hold):
    hold(*HOLDS)
    t, sent = Table(), []
    out = scp.run(
        t,
        datetime(2026, 11, 29, 10, 0, tzinfo=PACIFIC),
        lambda p: ("tok", 1),
        lambda *a: sent.append(a[2]) or True,
        flag_rows=[],
        disruption_state={"phase": "off"},
    )
    assert out["sent"] == ["weekly"] and len(sent) == 1  # Sunday: the weekly prompt


def test_the_new_items_are_committed_on_and_known():
    for i in HOLDS:
        assert i in ot.ITEMS and ot.DESCRIPTIONS[i].startswith("held by owner ruling 2026-11-26")
