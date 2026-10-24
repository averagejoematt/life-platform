#!/usr/bin/env python3
"""#4580 B-01 + A-X1 — the weekly analyzer's grounding gate checks LABELLED facts and the public register.

The fixture is the wire: `LEAD_READ_2026_10_18` is the stored `EXPERT#integrator.public_summary`
(generated_at 2026-10-18T04:38Z, data_through 2026-10-17) served verbatim on /api/edition `blocks.lead_read`,
/api/weekly_priority and /api/coaching-dashboard. Against the record it was written on:

  * "his starting weight of 302.2 pounds" — 302.2 was the CURRENT weight; the start is 327.3
    (`EXPERIMENT_BASELINE_WEIGHT_LBS`). The labelled check existed but `_gate_prose` never passed
    `baseline_lbs`, so it never ran.
  * "54 logged training sessions in thirty days" — the prompt's count was Hevy ROWS + Strava day ROWS
    (23 + 31 = 54 on 2026-09-17..10-17); /api/training_overview serves workouts_30d = 39.
  * "after a previous cycle that stalled in the final phase" — a reference to an earlier cycle on a
    reader surface (owner ruling 2026-09-26).

Mutation controls: each class is shown absent when its fact / its wiring is removed (the `*_control` tests),
and `test_gate_prose_arms_the_labelled_start_weight` spies on the exact call `_gate_prose` makes.
Offline: the model seam is monkeypatched and DynamoDB is a dict.
"""

import json
import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai_expert_analyzer_lambda as az  # noqa: E402
from ai import grounded_generation as gg  # noqa: E402
from coach import audience_guard  # noqa: E402
from common import retry_utils  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from intelligence import labelled_facts as lf  # noqa: E402
from test_analyzer_gate_all_paths_2421 import FakeModel, FakeTable  # noqa: E402
from web import site_api_coach_stance as stance  # noqa: E402

LEAD_READ_2026_10_18 = (
    "I'm watching Matthew execute at a steady clip: 54 logged training sessions in thirty days, consistent daily movement, "
    "and a weight loss rate holding at 3.3 pounds per week from his starting weight of 302.2 pounds on day 42. The structural "
    "adherence is working. What I'm tracking closely now is the gap between doing and logging—his food logs stopped four "
    "days ago, and his journal entries have been silent for forty days. The wearables are still reporting (sleep locked, "
    "recovery stable), so the passive data shows the machine is humming, but without active logging, I can't see the "
    "decision-making underneath. For a twelve-month recomposition after a previous cycle that stalled in the final phase, "
    "that visibility is the early warning system. I've asked him to restart one of those two channels this week—food "
    "log or journal entry—because the goal isn't perfection in logging, it's seeing what's real so we can adjust before "
    "the momentum quiets."
)
# The labelled facts at write time: the served 30-day count, and the two gaps as the verifier re-derived them
# (the food gap was real when written — rows for 10-11..10-17 were ingested 2h16m later; the journal's last
# entry was 2026-09-09, 38-40 days before).
FACTS_AT_WRITE = {"sessions_30d": 39, "food_lag_days": 4, "journal_gap_days": 40}


def _metrics(findings):
    return sorted(f.get("metric") or f["type"] for f in findings)


# ── the labelled-fact classes, unit level ────────────────────────────────────
def test_the_served_lead_read_trips_the_session_count():
    found = lf.labelled_fact_findings(LEAD_READ_2026_10_18, FACTS_AT_WRITE)
    assert _metrics(found) == ["sessions_30d"], found
    assert found[0]["cited"] == 54 and found[0]["canonical"] == 39


def test_the_gaps_it_got_right_do_not_flag():
    """Grader B's food and journal gaps were right when written (the verifier's re-derivation) — no false hold."""
    found = lf.labelled_fact_findings(LEAD_READ_2026_10_18, FACTS_AT_WRITE)
    assert not [f for f in found if f["metric"] in ("food_log_gap_days", "journal_gap_days")]


def test_a_wrong_gap_flags_on_both_channels():
    found = lf.labelled_fact_findings(LEAD_READ_2026_10_18, {"food_lag_days": 0, "journal_gap_days": 25})
    assert _metrics(found) == ["food_log_gap_days", "journal_gap_days"], found


def test_labelled_facts_control_no_fact_no_finding():
    """Control: an unknown fact is a skipped check, never a pass on a made-up number."""
    assert lf.labelled_fact_findings(LEAD_READ_2026_10_18, {}) == []
    assert lf.labelled_fact_findings(LEAD_READ_2026_10_18, {"sessions_30d": None}) == []


def test_number_words():
    assert [lf.number_value(t) for t in ("54", "forty", "forty-two", "four", "thirteen", "lots")] == [54, 40, 42, 4, 13, None]


def test_the_starting_weight_is_caught_only_with_baseline_lbs():
    sentence = "a weight loss rate holding at 3.3 pounds per week from his starting weight of 302.2 pounds on day 42."
    armed = gg.grounding_findings(
        sentence, generation_date_iso="2026-10-17", start_date_iso="2026-09-06", baseline_lbs=az.EXPERIMENT_BASELINE_WEIGHT_LBS
    )
    assert "stale_baseline" in [f["type"] for f in armed], armed
    # control: the pre-fix call (no baseline_lbs) passes the same sentence
    unarmed = gg.grounding_findings(sentence, generation_date_iso="2026-10-17", start_date_iso="2026-09-06")
    assert "stale_baseline" not in [f["type"] for f in unarmed]


# ── the cycle-reference class (A-X1) ─────────────────────────────────────────
def test_the_served_lead_read_carries_a_cycle_reference():
    found = lf.reader_surface_findings(LEAD_READ_2026_10_18)
    assert len(found) == 1 and "previous cycle" in found[0]["detail"], found


def test_restart_as_a_verb_is_not_a_cycle_reference():
    """Control: the same read's "asked him to restart one of those two channels" is about logging, not the experiment."""
    assert lf.reader_surface_findings("I've asked him to restart one of those two channels this week.") == []


# The same read with BOTH reader-surface defects removed: the cycle reference (#4580 A-X1) and the journal's
# silence (#5131 — the read also narrated it, and reader_safe now refuses that class on its own).
_CYCLE_PHRASE = " after a previous cycle that stalled in the final phase"
_SILENCE_PHRASE = ", and his journal entries have been silent for forty days"
FIXED_READ = LEAD_READ_2026_10_18.replace(_CYCLE_PHRASE, "").replace(_SILENCE_PHRASE, "")


def test_audience_guard_holds_the_public_slot_empty():
    assert audience_guard.reader_safe(LEAD_READ_2026_10_18, coach_id="integrator") is None
    assert audience_guard.reader_safe(LEAD_READ_2026_10_18.replace(_CYCLE_PHRASE, ""), coach_id="integrator") is None  # #5131
    assert audience_guard.reader_safe(FIXED_READ, coach_id="integrator") == FIXED_READ


# ── wired into the analyzer's ONE chokepoint ─────────────────────────────────
@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    az._CANON_FACTS_CACHE.clear()
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    yield
    az._CANON_FACTS_CACHE.clear()


def _synth(priority, public):
    return json.dumps({"weekly_priority": priority, "public_summary": public, "cross_domain_notes": {}, "disagreements": []})


CLEAN = "Hold the evening walk and let the pattern speak for itself."
CYCLE_REF = "He is building visibility after a previous cycle that stalled in the final phase."


def test_gate_prose_arms_the_labelled_start_weight(table, monkeypatch):
    seen = {}

    def _spy(text, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(az._gg, "grounding_findings", _spy)
    assert az._gate_prose("probe", CLEAN, "PROMPT", "sk-test") == CLEAN
    assert seen.get("baseline_lbs") == az.EXPERIMENT_BASELINE_WEIGHT_LBS


def test_gate_prose_holds_a_wrong_session_count(table, model, monkeypatch):
    monkeypatch.setattr(lf, "labelled_facts", lambda *_a, **_k: {"sessions_30d": 39})
    model("He logged 54 training sessions in thirty days.")  # the one rewrite repeats it
    assert az._gate_prose("probe", "He logged 54 training sessions in thirty days.", "PROMPT 54", "sk-test") == ""


def test_a_cycle_reference_in_public_summary_holds_and_keeps_the_prior(table, model):
    prior = {"pk": az.CACHE_PK, "sk": "EXPERT#integrator", "analysis": "Yesterday's read.", "public_summary": "Yesterday's public read."}
    table.items[(az.CACHE_PK, "EXPERT#integrator")] = dict(prior)
    m = model(_synth(CLEAN, CYCLE_REF))  # the rewrite repeats it
    assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
    assert m.calls >= 2, "one corrective rewrite before the hold"
    assert "previous cycle" in json.dumps(m.requests[-1]), "the correction names the phrase"
    assert not [w for w in table.writes if w.get("analysis") != prior["analysis"]], "a held read writes no new text"
    assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["public_summary"] == "Yesterday's public read."


def test_a_rewrite_that_drops_the_reference_publishes(table, model):
    model(_synth(CLEAN, CYCLE_REF), _synth(CLEAN, "He is building visibility, one logged meal at a time."))
    out = az.generate_synthesis({"sleep": "s", "training": "t"})
    assert out is not None and "previous cycle" not in out["public_summary"]
    assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["public_summary"] == "He is building visibility, one logged meal at a time."


def test_reader_check_control_owner_read_priority_is_not_a_reader_surface(table, model):
    """Control: the owner-read weekly_priority may name the cycle (the ruling covers reader surfaces only)."""
    model(_synth(CYCLE_REF, CLEAN))
    out = az.generate_synthesis({"sleep": "s", "training": "t"})
    assert out is not None and out["weekly_priority"] == CYCLE_REF


# ── the serve side: the stored read is withheld the moment site-api deploys ───
def _served_digest(**fields):
    row = {"pk": "USER#matthew#SOURCE#ai_analysis", "sk": "EXPERT#integrator", "generated_at": "2026-10-18T04:38:17Z", **fields}
    return stance._integrator_digest(_g={"table": FakeDdbTable(rows=[row])})


def test_the_stored_read_is_not_served_to_readers():
    """/api/weekly_priority, /api/coaching-dashboard, /api/coach_analysis and /api/edition's lead_read all read
    `analysis` off this one chokepoint; the stored 2026-10-18 read (and the owner-read analysis beside it, which may
    name the cycle) must not reach them."""
    owner_read = "You stalled in the final phase of the previous cycle; this week, restart the food log."
    item = _served_digest(public_summary=LEAD_READ_2026_10_18, analysis=owner_read)
    assert item["analysis"] is None


def test_serve_side_control_a_clean_read_still_serves():
    assert _served_digest(public_summary=FIXED_READ, analysis="You logged well.")["analysis"] == FIXED_READ
