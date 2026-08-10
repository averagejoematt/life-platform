"""tests/test_coach_experiment_awareness.py — the texting coaches know what day it is
(cycle-13 coaching brilliance, Act 1a).

Three facts join every chat turn's prompt, and each one is a behaviour pin here:

  E1  the EXPERIMENT FRAME — Day N of cycle C (week W), with an honest pre-genesis
      countdown instead of a fabricated Day 1
  E2  a coach's OWN still-open preregistered calls — at most three, newest first,
      read through ``with_phase_filter`` so a wiped cycle's calls never resurface
  E3  the head coach's week — the integrator's one priority, tombstone-guarded

  E4  the grounder consequence: the new numbers become legitimate vocabulary, and
      the gate must STILL be able to fire on a number that appears nowhere

Wall-clock discipline (the golden-test trap): every test pins BOTH the genesis and
the "today" it passes in. Nothing here reads the real clock, so no calendar day can
turn these red.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_domain_facts as cdf  # noqa: E402

GENESIS = "2026-08-10"  # cycle 13
GENESES = {11: "2026-07-27", 12: "2026-08-03", 13: GENESIS}


@pytest.fixture(autouse=True)
def _pinned_cycle(monkeypatch):
    """Pin the experiment anchors so no real date participates in any assertion."""
    from common import constants
    from web import site_api_data

    monkeypatch.setattr(constants, "EXPERIMENT_START_DATE", GENESIS)
    monkeypatch.setattr(site_api_data, "CYCLE_GENESES", dict(GENESES))


class _Table:
    """Minimal DDB double: PREDICTION# queries by pk, one get_item singleton."""

    def __init__(self, predictions=(), singleton=None):
        self.predictions = list(predictions)
        self.singleton = singleton
        self.query_kwargs = []
        self.get_item_keys = []

    def query(self, **kw):
        self.query_kwargs.append(kw)
        pk = kw.get("ExpressionAttributeValues", {}).get(":pk")
        return {"Items": [p for p in self.predictions if p.get("pk") == pk]}

    def get_item(self, **kw):
        self.get_item_keys.append(kw.get("Key"))
        return {"Item": self.singleton} if self.singleton else {}


def _prediction(coach="sleep_coach", claim="HRV rises with a 10pm lights-out", **fields):
    rec = {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{fields.get('created_date', '2026-08-11')}-{abs(hash(claim)) % 9973}",
        "claim_natural": claim,
        "status": "pending",
        "confidence": 0.7,
        "created_date": "2026-08-11",
    }
    rec.update(fields)
    return rec


# ── E1: the experiment frame ─────────────────────────────────────────────────


def test_frame_names_the_day_the_cycle_and_the_week():
    assert cdf._experiment_frame_lines("2026-08-12") == ["Experiment: Day 3 of cycle 13 (week 1)."]


def test_frame_week_matches_the_integrator_row_not_the_monday_anchor():
    """The coach may quote the integrator's weekly digest, so it must name the week
    that row names: ``max(1, day // 7 + 1)`` verbatim from ai_expert_analyzer_lambda.
    Day 6 and Day 7 straddle the boundary where the Monday-anchored field-notes
    formula disagrees — pinning both sides is what makes the drift visible."""
    assert cdf._week_number(1) == 1
    assert cdf._week_number(6) == 1
    assert cdf._week_number(7) == 2
    assert cdf._week_number(13) == 2
    assert cdf._week_number(14) == 3
    assert "(week 2)." in cdf._experiment_frame_lines("2026-08-16")[0]  # Day 7


def test_pre_genesis_counts_down_instead_of_inventing_day_one():
    """A future genesis is sanctioned (#931/#939). "Day 1" during that window would
    be the exact fabrication class the platform exists to refuse — and the grounder's
    own pre_start check treats any Day-N claim before genesis as stale framing."""
    line = cdf._experiment_frame_lines("2026-08-09")[0]
    assert "cycle 13 starts 2026-08-10" in line
    assert "no Day 1 yet" in line
    assert "Day 1 of" not in line


def test_frame_survives_an_unreadable_cycle_ledger(monkeypatch):
    monkeypatch.setattr(cdf, "_current_cycle", lambda: None)
    assert cdf._experiment_frame_lines("2026-08-12") == ["Experiment: Day 3 (week 1)."]


def test_every_texting_coach_gets_the_frame_even_without_a_domain_pack():
    """Chat-tier coaches returned "" before this slice. Experiment awareness is a
    team-wide fact, not a per-domain one."""
    for coach in ("mind_coach", "eli_marsh", "nutrition_coach"):
        block = cdf.domain_facts_block(coach, _Table(), today="2026-08-12")
        assert "EXPERIMENT FRAME:" in block, coach
        assert "- Experiment: Day 3 of cycle 13 (week 1)." in block, coach


# ── E2: the coach's own open calls ───────────────────────────────────────────


def test_a_coach_cites_its_own_open_calls_newest_first_capped_at_three():
    preds = [_prediction(claim=f"call {n}", created_date=f"2026-08-1{n}") for n in range(1, 5)]  # 2026-08-11 .. 2026-08-14
    block = cdf.domain_facts_block("sleep_coach", _Table(preds), today="2026-08-15")
    assert block.count("Your open call:") == cdf.MAX_OWN_PREDICTIONS == 3
    assert 'Your open call: "call 4" (confidence 0.7, made 2026-08-14).' in block
    assert "call 1" not in block  # the oldest falls off, not a newer one


def test_only_pending_and_confirming_calls_are_open():
    preds = [
        _prediction(claim="graded already", status="resolved"),
        _prediction(claim="thrown out", status="inconclusive"),
        _prediction(claim="still confirming", status="confirming"),
    ]
    block = cdf.domain_facts_block("sleep_coach", _Table(preds), today="2026-08-12")
    assert "still confirming" in block
    assert "graded already" not in block and "thrown out" not in block


def test_a_claimless_row_is_not_rendered_as_an_empty_quote():
    preds = [_prediction(claim_natural=""), _prediction(claim="a real one")]
    block = cdf.domain_facts_block("sleep_coach", _Table(preds), today="2026-08-12")
    assert block.count("Your open call:") == 1
    assert '""' not in block


def test_the_prediction_read_goes_through_the_phase_filter(monkeypatch):
    """ADR-058. Without the wrapper a reset's pilot-tagged calls keep being quoted
    as live — and the wrapper is invisible to any assertion on the RESULT, so the
    pin is on the call itself."""
    from experiment import phase_filter

    seen = []
    real = phase_filter.with_phase_filter

    def spy(kwargs, **kw):
        seen.append(dict(kwargs))
        return real(kwargs, **kw)

    monkeypatch.setattr(phase_filter, "with_phase_filter", spy)
    table = _Table([_prediction()])
    cdf.domain_facts_block("sleep_coach", table, today="2026-08-12")

    assert seen, "with_phase_filter was never called on the PREDICTION# read"
    assert seen[0]["ExpressionAttributeValues"][":pk"] == "COACH#sleep_coach"
    # and the wrapper's filter actually reached the query boto3 saw
    assert "FilterExpression" in table.query_kwargs[0]
    assert table.query_kwargs[0]["ExpressionAttributeValues"][":phase_experiment"] == "experiment"


def test_a_route_id_resolves_to_the_canonical_prediction_partition():
    """The worker passes a persona id; the daily-reflection path passes a short one.
    Both must land on COACH#<persona>, or the coach silently has no open calls."""
    table = _Table([_prediction(coach="nutrition_coach", claim="protein floor holds")])
    assert "protein floor holds" in cdf.domain_facts_block("nutrition", table, today="2026-08-12")
    assert "protein floor holds" in cdf.domain_facts_block("nutrition_coach", table, today="2026-08-12")


def test_a_chat_tier_coach_makes_no_forecasts_so_none_are_read():
    table = _Table([_prediction()])
    block = cdf.domain_facts_block("eli_marsh", table, today="2026-08-12")
    assert "Your open call" not in block
    assert not table.query_kwargs, "no PREDICTION# partition exists for a chat-tier coach"


# ── E3: the head coach's week ────────────────────────────────────────────────


_INTEGRATOR = {
    "pk": "USER#matthew#SOURCE#ai_analysis",
    "sk": "EXPERT#integrator",
    "analysis": "Protein first. Everything else this week is downstream of it.",
    "week_number": 2,
    "phase": "experiment",
}


def test_the_lead_gets_the_integrators_one_priority():
    block = cdf.domain_facts_block("eli_marsh", _Table(singleton=_INTEGRATOR), today="2026-08-16")
    assert "This week's one priority (your team's integrator, week 2): Protein first." in block
    assert "YOUR DOMAIN FACTS" in block


def test_no_other_coach_gets_the_weekly_priority():
    table = _Table(singleton=_INTEGRATOR)
    for coach in ("sleep_coach", "nutrition_coach", "mind_coach"):
        assert "one priority" not in cdf.domain_facts_block(coach, table, today="2026-08-16"), coach
    assert {"sk": "EXPERT#integrator"} not in [k or {} for k in table.get_item_keys]


def test_a_tombstoned_integrator_row_contributes_nothing(monkeypatch):
    """#946/#1969 — the wipe tombstones ai_analysis IN PLACE and get_item bypasses
    the query filter, so the guard is the only thing between a reset and the head
    coach narrating the deleted cycle as 'this week'."""
    wiped = {**_INTEGRATOR, "tombstone": True}
    assert cdf._weekly_priority_lines(_Table(singleton=wiped)) == []
    stale = {**_INTEGRATOR, "phase": "pilot"}
    assert cdf._weekly_priority_lines(_Table(singleton=stale)) == []
    # mutation-proof: the same guard must PASS the clean row it is meant to allow
    assert cdf._weekly_priority_lines(_Table(singleton=_INTEGRATOR))


def test_an_empty_integrator_analysis_renders_nothing_rather_than_a_stub():
    assert cdf._weekly_priority_lines(_Table(singleton={**_INTEGRATOR, "analysis": "  "})) == []


def test_a_long_integrator_analysis_is_bounded():
    long_row = {**_INTEGRATOR, "analysis": "word " * 400}
    line = cdf._weekly_priority_lines(_Table(singleton=long_row))[0]
    assert len(line) < cdf.MAX_PRIORITY_CHARS + 120
    assert line.endswith("…")


# ── E4: the grounder consequence ─────────────────────────────────────────────


def _grounder_over(block, as_of):
    """The real gate, armed exactly as the worker arms it — with the SAME injected
    day the block was rendered for. (The parameter is deliberately not named
    ``today``: every dated literal in this file is injected, and reusing the name
    for a helper parameter is what makes that pattern unreadable.)"""
    from coach.coach_chat_grounding import build_grounder

    facts = {"generation_date": as_of, "night_of": "2026-08-11", "recovery_pct": 55.0}
    return build_grounder(facts, generation_date_iso=as_of, extra_sources=(block,))


def test_the_day_number_and_a_calls_confidence_become_legitimate_vocabulary():
    today = "2026-08-27"  # Day 18, week 3 — day/week values outside the benign smalls
    block = cdf.domain_facts_block(
        "sleep_coach",
        _Table([_prediction(claim="HRV rises with lights-out at 10", confidence=0.73)]),
        today=today,
    )
    assert "Day 18" in block and "0.73" in block
    findings = _grounder_over(block, today)("We're on day 18 and I put that call at 0.73 confidence.")
    assert findings == [], findings


def test_the_gate_can_still_fire_on_a_number_from_nowhere():
    """The mutation control. A block that widens the allow-list is only safe if the
    gate that reads it is still able to refuse — a vocabulary that swallows every
    number is a guard that guards nothing."""
    today = "2026-08-27"
    block = cdf.domain_facts_block("sleep_coach", _Table([_prediction(confidence=0.73)]), today=today)
    assert _grounder_over(block, today)("Your HRV averaged 137 ms this week."), "137 appears in no source"


def test_the_frames_day_number_agrees_with_the_gates_own_day_arithmetic():
    """The frame and the deterministic Day-N freshness class both derive from
    EXPERIMENT_START_DATE. If they ever disagree the coach argues with its own gate
    and every reply naming the day gets held — which is why the worker feeds the
    SAME Pacific date to both."""
    for today, expected_day in (("2026-08-10", 1), ("2026-08-27", 18), ("2026-09-14", 36)):
        block = cdf.domain_facts_block("mind_coach", _Table(), today=today)
        assert f"Day {expected_day} " in block
        assert _grounder_over(block, today)(f"Day {expected_day} and the plan holds.") == []


# ── fail-soft ────────────────────────────────────────────────────────────────


def test_storage_failure_costs_the_ddb_sections_not_the_frame():
    class _Boom:
        def query(self, **kw):
            raise RuntimeError("ddb down")

        def get_item(self, **kw):
            raise RuntimeError("ddb down")

    block = cdf.domain_facts_block("sleep_coach", _Boom(), today="2026-08-12")
    assert "EXPERIMENT FRAME:" in block
    assert "Your open call" not in block


def test_the_worker_feeds_the_pacific_date_to_both_the_pack_and_the_gate():
    """#2392's class. The worker computes the Pacific day once and hands it to
    domain_facts_block AND build_grounder; a UTC default would put the coach a day
    ahead of its own frame after 5pm PT."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach", "telegram_worker_lambda.py")).read()
    assert 'today_pt = pacific_now().strftime("%Y-%m-%d")' in src
    assert "domain_facts_block(persona_id, _table(), today_pt)" in src
    assert "generation_date_iso=today_pt" in src
