"""tests/test_coach_open_loops_behavior.py — the open-loop behaviour pin (#2486/#2491).

The mechanism under test is "a coach keeps a promise it made in a text". Its
characteristic failure is not a crash — it is a follow-up that fires from something
the coach never said, which is ADR-104 fabrication delivered in the most trusted
voice on the platform. So the pins here are mostly about what does NOT fire:

  * an offer is not a promise;
  * a promise with no resolvable day is not schedulable, and a guess would be a lie;
  * a promise fires ONCE — the write-once claim, not a status flag on a derived row;
  * the chat path stays the only writer of the CHAT# partition (the whole reason
    #2486 and #2491 were merged: two extractors racing one partition).

The mutation proof is explicit: the same seeded thread, one word changed, must flip
the outcome — otherwise the test would pass with the detector stubbed out.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import (
    coach_event_triggers as cet,  # noqa: E402
    coach_open_loops as col,  # noqa: E402
    coach_outbound,  # noqa: E402
)
from experiment import phase_taxonomy  # noqa: E402

TODAY = "2026-08-14"  # a Friday
COACH_PK = "COACH#pattern_coach"


def coach_row(text, date="2026-08-12", uid="aaaa1111"):
    return {"pk": COACH_PK, "sk": f"CHAT#{date}#{uid}", "role": "coach", "text": text}


def matthew_row(text, date="2026-08-12", uid="bbbb2222"):
    return {"pk": COACH_PK, "sk": f"CHAT#{date}#{uid}", "role": "matthew", "text": text}


def loops(rows, persona="pattern_coach"):
    return col.extract_open_loops(rows, persona)


# ── L1: what a promise is, and what it is not ─────────────────────────────────


def test_a_stated_commitment_with_a_named_day_becomes_an_open_loop():
    got = loops([coach_row("Good. I'll check in Friday to see how the sleep window held.")])
    assert len(got) == 1
    assert got[0]["kind"] == col.KIND_PROMISE
    assert got[0]["due"] == "2026-08-14"
    assert got[0]["sentence"].startswith("I'll check in Friday")


def test_the_mutation_that_proves_the_detector_runs():
    """One word apart: a commitment fires, an offer does not.

    Same speaker, same day, same verb. If the detector were stubbed to always fire
    (or never), one of these two assertions breaks.
    """
    committed = loops([coach_row("I'll check in Friday.")])
    offered = loops([coach_row("I could check in Friday.")])
    assert len(committed) == 1
    assert offered == []


@pytest.mark.parametrize(
    "text",
    [
        "Want me to check in Friday?",  # a question is an offer
        "If you want, I'll check in Friday.",  # hedged
        "I was going to check in Friday.",  # past intent, not a commitment
        "I'll check in soon.",  # no resolvable day
        "I'll check in at some point next month.",  # beyond the trusted horizon
        "I'll think about it Friday.",  # not a promise to make CONTACT
    ],
)
def test_nothing_that_was_not_actually_promised_becomes_a_follow_up(text):
    assert loops([coach_row(text)]) == []


def test_a_day_it_cannot_resolve_is_silence_not_a_guess():
    """ADR-104: 'sometime next week-ish' produces no follow-up at all.

    The failure this pins is the tempting one — defaulting an unresolvable promise
    to 'a few days' would schedule a text he was never told to expect.
    """
    assert col.resolve_due("I'll follow up in a bit.", "2026-08-12") is None
    assert col.resolve_due("I'll follow up Friday.", "2026-08-12") == "2026-08-14"


def test_a_weekday_said_on_that_weekday_means_the_NEXT_one():
    # Said on Friday, "I'll check in Friday" cannot mean the moment it was said.
    assert col.resolve_due("I'll check in Friday.", "2026-08-14") == "2026-08-21"


def test_two_promises_in_one_reply_stay_distinct():
    got = loops([coach_row("I'll follow up tomorrow. And I'll text you Monday about the labs.")])
    assert len(got) == 2
    assert len({ln["loop_id"] for ln in got}) == 2


# ── L2: due-window semantics ──────────────────────────────────────────────────


def test_a_promise_is_not_due_before_its_day():
    ln = loops([coach_row("I'll check in Friday.")])[0]
    assert not col.is_due(ln, "2026-08-13")
    assert col.is_due(ln, "2026-08-14")


def test_a_promise_has_one_grace_day_and_a_pre_event_has_none():
    """Late semantics differ ON PURPOSE and the difference is the point.

    A kept promise is still worth keeping the morning after the cap ate it. 'Good
    luck with the presentation' the day AFTER the presentation is not support.
    """
    promise = loops([coach_row("I'll check in Friday.")])[0]
    pre = loops([matthew_row("I have a presentation Friday.")])[0]
    assert col.is_due(promise, "2026-08-15")
    assert not col.is_due(promise, "2026-08-16")
    assert not col.is_due(pre, "2026-08-15")


# ── L3: the pre-event half (#2491's outcome) ──────────────────────────────────


def test_a_hard_thing_he_named_becomes_a_morning_of_event():
    got = loops([matthew_row("I have a presentation Friday and I'm dreading it.")])
    assert len(got) == 1
    assert got[0]["kind"] == col.KIND_PRE_EVENT
    assert got[0]["due"] == TODAY


def test_the_coach_he_told_is_the_one_who_texts():
    """A correction to #2491's body, pinned so it cannot drift back.

    Routing a pre-event to a lane that was not in the conversation would have that
    coach open a thread about a transcript it never saw.
    """
    got = loops([matthew_row("I have a flight tomorrow.")], persona="career_coach")
    assert got[0]["persona_id"] == "career_coach"


def test_an_ordinary_day_is_not_a_hard_thing():
    assert loops([matthew_row("I have a lot going on tomorrow.")]) == []
    assert loops([matthew_row("Might have a flight Friday.")]) == []


# ── L4: candidate wiring — the detector actually reaches the sweep ────────────


def test_a_due_promise_becomes_a_top_priority_candidate():
    ln = loops([coach_row("I'll check in Friday.")])
    got = cet.candidates({"open_loops": ln}, TODAY)
    assert len(got) == 1
    ev = got[0]
    assert ev["provenance"] == coach_outbound.PROVENANCE_PROMISE
    assert ev["persona_id"] == "pattern_coach"
    assert ev["event_id"].startswith("open_loop#promise#pattern_coach#")
    # The frame exists and carries the verbatim sentence — an evidence-less open
    # loop is not representable as a sendable candidate at all.
    assert "I'll check in Friday." in ev["frame"]


def test_a_turn_with_no_commitment_produces_no_candidate():
    ln = loops([coach_row("Sleep looked steadier this week.")])
    assert ln == []
    assert cet.candidates({"open_loops": ln}, TODAY) == []


def test_a_kept_promise_outranks_every_data_triggered_ping():
    """The ordering claim from #2527, now with a real promise in the list."""
    promise = cet.candidates({"open_loops": loops([coach_row("I'll check in Friday.")])}, TODAY)[0]
    ranks = [coach_outbound.priority(p) for p in (promise["provenance"], coach_outbound.PROVENANCE_CONCERN)]
    assert ranks[0] < ranks[1]


def test_open_loops_are_ordered_oldest_due_first():
    rows = [coach_row("I'll check in Friday.", uid="c1"), coach_row("I'll follow up tomorrow.", uid="c2")]
    got = cet.detect_open_loops(loops(rows), TODAY)
    # Both were made 08-12: "tomorrow" is due 08-13 (one grace day left), "Friday"
    # is due today. The older obligation speaks first.
    assert len(got) == 2
    assert "c2" in got[0]["event_id"] and "c1" in got[1]["event_id"]


def test_a_detector_explosion_does_not_silence_the_others(monkeypatch):
    monkeypatch.setattr(cet, "detect_open_loops", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cet.candidates({"open_loops": [{"broken": True}]}, TODAY) == []


# ── L5: the partition decision, pinned ────────────────────────────────────────


def test_the_open_loop_feature_writes_no_new_row_class():
    """The whole partition argument, as an executable assertion.

    ``coach_open_loops`` must contain no put/update path at all: the record of a
    promise is the CHAT# turn, and the only state the feature writes is the existing
    write-once event claim, whose sole writer is the sweep. If a future change adds a
    derived row here, this test is where the design conversation restarts.
    """
    import inspect

    # The module docstring ARGUES about COMMITMENT#; the code must not touch it.
    code = inspect.getsource(col).split('"""', 2)[-1]
    assert "put_item" not in code
    assert "update_item" not in code
    assert "COMMITMENT#" not in code


def test_the_source_turn_stays_cross_phase_and_the_claim_stays_system_state():
    """A reset must not make a coach forget a promise it has not kept yet.

    The turn is CROSS_PHASE (ADR-153) so the promise survives; the fire-once claim is
    SYSTEM_STATE so a reset cannot license the same text twice.
    """
    assert phase_taxonomy.classify(COACH_PK, "CHAT#2026-08-12#aaaa1111") == phase_taxonomy.CROSS_PHASE
    assert phase_taxonomy.classify("COACH#outbound_events", "EVENT#open_loop#promise#pattern_coach#CHAT#x#0") == phase_taxonomy.SYSTEM_STATE


def test_summary_rows_cannot_be_read_back_as_turns():
    """CHAT#summary# lives inside the CHAT# prefix by design; a summary that says
    'she said she would check in Friday' must never itself become a promise."""
    rows = [{"pk": COACH_PK, "sk": "CHAT#summary#2026-08-12", "role": "summary", "text": "I'll check in Friday."}]
    assert loops(rows) == []


# ── L6: fire-once, end to end through the sweep ───────────────────────────────


class FakeTable:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.claims = set()

    def query(self, **kwargs):
        return {"Items": list(self.rows)}

    def put_item(self, Item=None, **kwargs):  # noqa: N803 — boto3 kwarg name
        key = (Item["pk"], Item["sk"])
        if key in self.claims:
            raise RuntimeError("ConditionalCheckFailedException")
        self.claims.add(key)

    def update_item(self, **kwargs):
        return {}


class Clock:
    """A fixed Friday morning, 10:00 PT — outside quiet hours, after the cutoff."""

    hour = 10

    def strftime(self, fmt):
        return {"%Y-%m-%d": TODAY}.get(fmt, TODAY)


def _sweep(table, sent):
    return cet.run_sweep(
        now_pt=Clock(),
        table=table,
        seat=lambda pid: ("token", 42),
        speak=lambda ev, t, c: (sent.append(ev["event_id"]), {"ok": True, "status": "sent"})[1],
        chat_rows=lambda pid: [],
        tier=0,
        signals={"open_loops": loops([coach_row("I'll check in Friday.")])},
    )


def test_a_due_promise_produces_exactly_one_text_and_never_a_second():
    table, sent = FakeTable(), []
    first = _sweep(table, sent)
    second = _sweep(table, sent)
    assert first["ok"] and first["candidates"] == 1
    assert sent == ["open_loop#promise#pattern_coach#CHAT#2026-08-12#aaaa1111#0"]
    assert second["reason"] == "nothing sendable"
    assert len(sent) == 1


def test_a_dark_bot_leaves_the_promise_unspent():
    """The claim ordering is load-bearing: a coach with no BotFather registration
    must not burn the event, or the first text after registration is a silence."""
    table, sent = FakeTable(), []
    out = cet.run_sweep(
        now_pt=Clock(),
        table=table,
        seat=lambda pid: (None, None),
        speak=lambda ev, t, c: sent.append(ev) or {"ok": True},
        chat_rows=lambda pid: [],
        tier=0,
        signals={"open_loops": loops([coach_row("I'll check in Friday.")])},
    )
    assert out["reason"] == "nothing sendable"
    assert sent == []
    assert table.claims == set()


def test_quiet_hours_still_govern_a_kept_promise():
    class Night(Clock):
        hour = 23

    table, sent = FakeTable(), []
    out = cet.run_sweep(
        now_pt=Night(),
        table=table,
        seat=lambda pid: ("token", 42),
        speak=lambda ev, t, c: sent.append(ev) or {"ok": True},
        chat_rows=lambda pid: [],
        tier=0,
        signals={"open_loops": loops([coach_row("I'll check in Friday.")])},
    )
    assert out["reason"] == "quiet hours"
    assert sent == []


def test_silence_respect_applies_to_promises_too():
    """A kept promise is still an unsolicited text. Two ignored in a row = stop."""
    ignored = [
        {"role": "coach", "provenance": coach_outbound.PROVENANCE_PROMISE},
        {"role": "coach", "provenance": coach_outbound.PROVENANCE_PROMISE},
    ]
    table, sent = FakeTable(), []
    out = cet.run_sweep(
        now_pt=Clock(),
        table=table,
        seat=lambda pid: ("token", 42),
        speak=lambda ev, t, c: sent.append(ev) or {"ok": True},
        chat_rows=lambda pid: ignored,
        tier=0,
        signals={"open_loops": loops([coach_row("I'll check in Friday.")])},
    )
    assert out["reason"] == "nothing sendable"
    assert sent == []


def test_the_promise_frame_forbids_the_apology_and_the_announcement():
    frame = coach_outbound.event_frame(coach_outbound.PROVENANCE_PROMISE, "- evidence line")
    assert frame and "apolog" in frame.lower()
    assert "evidence line" in frame
    # An open loop with nothing behind it is not representable as a frame.
    assert coach_outbound.event_frame(coach_outbound.PROVENANCE_PROMISE, "") == ""
