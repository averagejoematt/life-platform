"""tests/test_singleton_tombstone_guards.py — #946: singleton get_item readers
must honor the restart tombstone.

The intelligence wipe (Interpretation B) stamps tombstone=true + phase=pilot on
wiped records. Query paths hide them via with_phase_filter, but get_item
bypasses filters entirely — so every STATE#current-style singleton reader needs
an item-level guard (mirroring the #918 _stance_latest fix) or the wiped
cycle's narrative state keeps serving until the next writer run.

Special case: NARRATIVE#arc STATE#current reuses the attribute name `phase` for
its NARRATIVE phase (early_baseline/setback/...), so its readers guard on
tombstone + entered_date < genesis instead of the generic phase check.
"""

import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import coach_computation_engine as eng  # noqa: E402
import coach_narrative_orchestrator as orch  # noqa: E402
import elena_state_updater as elena  # noqa: E402
from ai_expert_analyzer_lambda import _load_engagement_signal  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402
from experiment.phase_filter import singleton_visible  # noqa: E402
from web import (
    site_api_coach as capi,  # noqa: E402
    site_api_intelligence as capi_intel,  # noqa: E402  # #1240: forecast/scenarios/state_of_matthew moved here from site_api_data
)

GENESIS = date.fromisoformat(EXPERIMENT_START_DATE)
PRE_GENESIS = (GENESIS - timedelta(days=9)).isoformat()
POST_GENESIS = (GENESIS + timedelta(days=3)).isoformat()

TOMBSTONED = {"tombstone": True, "phase": "pilot", "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}"}


class _FakeTable:
    """Minimal DDB table stand-in: one canned get_item item + query items,
    recording put_item calls."""

    def __init__(self, item=None, query_items=None):
        self.item = item
        self.query_items = query_items or []
        self.put_calls = []

    def get_item(self, Key=None, **kw):
        return {"Item": self.item} if self.item is not None else {}

    def query(self, **kw):
        return {"Items": list(self.query_items)}

    def put_item(self, Item=None, **kw):
        self.put_calls.append(Item)
        return {}


# ── the shared predicate ──────────────────────────────────────────────────────


def test_singleton_visible_hides_tombstoned_and_pilot():
    assert singleton_visible(None) is False
    assert singleton_visible({}) is False
    assert singleton_visible({"tombstone": True}) is False
    assert singleton_visible({"phase": "pilot", "x": 1}) is False
    assert singleton_visible({**TOMBSTONED, "date": "2026-07-10"}) is False


def test_singleton_visible_passes_current_phase_and_unphased():
    assert singleton_visible({"phase": "experiment", "x": 1}) is True
    assert singleton_visible({"x": 1}) is True  # config/profile: no phase attr


# ── orchestrator: generic singleton reads (engagement, stance, voice, …) ─────


def test_orchestrator_get_item_returns_none_for_tombstoned_singleton(monkeypatch):
    monkeypatch.setattr(orch, "table", _FakeTable(item={**TOMBSTONED, "presence_class": "dark", "severity": "alarm"}))
    assert orch._get_item("USER#matthew#SOURCE#engagement_state", "STATE#current") is None


def test_orchestrator_get_item_returns_none_for_pilot_phase(monkeypatch):
    monkeypatch.setattr(orch, "table", _FakeTable(item={"phase": "pilot", "summary": "old cycle"}))
    assert orch._get_item("COACH#sleep_coach", "COMPRESSED#latest") is None


def test_orchestrator_get_item_passes_clean_singleton(monkeypatch):
    monkeypatch.setattr(orch, "table", _FakeTable(item={"summary": "fresh", "phase": "experiment"}))
    got = orch._get_item("COACH#sleep_coach", "COMPRESSED#latest")
    assert got == {"summary": "fresh", "phase": "experiment"}


# ── orchestrator: the NARRATIVE#arc special case ──────────────────────────────


def test_orchestrator_arc_hidden_when_tombstoned(monkeypatch):
    monkeypatch.setattr(orch, "table", _FakeTable(item={**TOMBSTONED, "entered_date": PRE_GENESIS}))
    assert orch._narrative_arc_state() is None


def test_orchestrator_arc_hidden_when_entered_before_genesis(monkeypatch):
    # The live post-reset shape: NOT tombstoned (the old wipe skipped it), narrative
    # phase 'setback' from the previous cycle. Must not steer the new cycle.
    stale = {"phase": "setback", "entered_date": PRE_GENESIS, "previous_phase": "plateau"}
    monkeypatch.setattr(orch, "table", _FakeTable(item=stale))
    assert orch._narrative_arc_state() is None


def test_orchestrator_arc_serves_current_cycle_state(monkeypatch):
    # A legit arc's `phase` attr is a NARRATIVE phase — the generic experiment-phase
    # guard must NOT apply here, or the arc feature dies post-genesis.
    fresh = {"phase": "building_momentum", "entered_date": POST_GENESIS}
    monkeypatch.setattr(orch, "table", _FakeTable(item=fresh))
    assert orch._narrative_arc_state() == fresh


# ── computation engine: no path back to early_baseline (engine-bugs-1) ───────


def _trends(up=0, down=0, flat=0):
    metrics = {}
    for i in range(up):
        metrics[f"u{i}"] = {"direction": "up"}
    for i in range(down):
        metrics[f"d{i}"] = {"direction": "down"}
    for i in range(flat):
        metrics[f"f{i}"] = {"direction": "flat"}
    return {"domain": metrics}


def test_engine_stale_setback_arc_does_not_trip_breakthrough(monkeypatch):
    """Improving week-1 data + the surviving cycle-4 'setback' arc used to fire an
    absurd day-N 'breakthrough'. The stale arc must restart at early_baseline,
    where <14 days means no transition at all."""
    stale = {"phase": "setback", "entered_date": PRE_GENESIS, "previous_phase": "plateau"}
    fake = _FakeTable(item=stale)
    monkeypatch.setattr(eng, "table", fake)
    day2 = (GENESIS + timedelta(days=1)).isoformat()
    result = eng._detect_arc_transition(_trends(up=4, down=1), {}, {}, day2)
    assert result is None
    assert fake.put_calls == []


def test_engine_tombstoned_arc_treated_as_absent(monkeypatch):
    fake = _FakeTable(item={**TOMBSTONED, "entered_date": PRE_GENESIS})
    monkeypatch.setattr(eng, "table", fake)
    day2 = (GENESIS + timedelta(days=1)).isoformat()
    assert eng._detect_arc_transition(_trends(up=4, down=1), {}, {}, day2) is None
    assert fake.put_calls == []


def test_engine_stale_arc_restarts_from_early_baseline_not_setback(monkeypatch):
    """Declining data still transitions (any → setback fires from day 1), but the
    FROM phase must be the fresh cycle's early_baseline, not cycle-4 'setback'
    (from which the same trends would have produced no write at all)."""
    stale = {"phase": "setback", "entered_date": PRE_GENESIS}
    fake = _FakeTable(item=stale)
    monkeypatch.setattr(eng, "table", fake)
    day2 = (GENESIS + timedelta(days=1)).isoformat()
    result = eng._detect_arc_transition(_trends(down=3, flat=1), {}, {}, day2)
    assert result is not None
    assert result["from"] == "early_baseline"
    assert result["to"] == "setback"
    state_writes = [p for p in fake.put_calls if p.get("sk") == "STATE#current"]
    assert state_writes and state_writes[0]["previous_phase"] == "early_baseline"


def test_engine_current_cycle_arc_still_progresses(monkeypatch):
    """A post-genesis arc is respected: setback → breakthrough on 60%+ improving."""
    current = {"phase": "setback", "entered_date": POST_GENESIS}
    fake = _FakeTable(item=current)
    monkeypatch.setattr(eng, "table", fake)
    later = (GENESIS + timedelta(days=10)).isoformat()
    result = eng._detect_arc_transition(_trends(up=4, down=1), {}, {}, later)
    assert result is not None and result["from"] == "setback" and result["to"] == "breakthrough"


# ── expert analyzer: presence signal ──────────────────────────────────────────


def test_analyzer_engagement_signal_empty_when_tombstoned(monkeypatch):
    import ai_expert_analyzer_lambda as ana

    wiped = {**TOMBSTONED, "presence_class": "dark", "severity": "alarm", "date": PRE_GENESIS}
    monkeypatch.setattr(ana, "table", _FakeTable(item=wiped))
    assert _load_engagement_signal() == {}


def test_analyzer_engagement_signal_passes_live_state(monkeypatch):
    import ai_expert_analyzer_lambda as ana

    live = {"presence_class": "present", "severity": "none", "date": POST_GENESIS}
    monkeypatch.setattr(ana, "table", _FakeTable(item=live))
    assert _load_engagement_signal() == live


# ── site_api: the EXPERT#integrator serving path (serving-bugs-1) ─────────────


def test_integrator_digest_none_when_tombstoned(monkeypatch):
    wiped = {**TOMBSTONED, "analysis": "week 4 of the stall...", "week_number": 4}
    monkeypatch.setattr(capi, "table", _FakeTable(item=wiped))
    assert capi._integrator_digest() is None


def test_integrator_digest_passes_clean_record(monkeypatch):
    clean = {"analysis": "fresh cycle read", "week_number": 1, "phase": "experiment"}
    monkeypatch.setattr(capi, "table", _FakeTable(item=clean))
    assert capi._integrator_digest() == clean


def test_weekly_priority_honest_null_when_digest_hidden(monkeypatch):
    monkeypatch.setattr(capi, "_integrator_digest", lambda: None)
    resp = capi.handle_weekly_priority({})
    body = json.loads(resp["body"])
    assert body["weekly_priority"] is None
    assert body["cross_domain_notes"] == {}


def test_team_tensions_empty_when_digest_hidden(monkeypatch):
    monkeypatch.setattr(capi, "_integrator_digest", lambda: None)
    assert capi._team_tensions() == []


def test_team_tensions_reads_guarded_accessor(monkeypatch):
    monkeypatch.setattr(
        capi,
        "_integrator_digest",
        lambda: {"disagreements": [{"topic": "zone 2", "coaches_involved": ["training", "glucose"], "position_a": "a", "position_b": "b"}]},
    )
    out = capi._team_tensions()
    assert len(out) == 1 and out[0]["topic"] == "zone 2"


def test_team_tensions_carry_generated_at(monkeypatch):
    # #2383 (ADR-104 honest dating) — every tension carries the digest's
    # generated_at so /coaching/ can date the band ("as of <date>"); the
    # front-end refuses to render undated argument prose as today's coaching.
    monkeypatch.setattr(
        capi,
        "_integrator_digest",
        lambda: {
            "generated_at": "2026-08-05T14:00:00+00:00",
            "disagreements": [
                {"topic": "zone 2", "coaches_involved": ["training", "glucose"], "position_a": "a", "position_b": "b"},
                {"topic": "protein", "coaches_involved": ["nutrition", "strength"], "position_a": "x", "position_b": "y"},
            ],
        },
    )
    out = capi._team_tensions()
    assert len(out) == 2
    assert all(t["generated_at"] == "2026-08-05T14:00:00+00:00" for t in out)


def test_team_tensions_generated_at_none_when_digest_undated(monkeypatch):
    # An undated digest propagates generated_at=None — the front-end's
    # datableTensions then refuses the prose (honest-empty), never fabricates.
    monkeypatch.setattr(
        capi,
        "_integrator_digest",
        lambda: {"disagreements": [{"topic": "zone 2", "coaches_involved": ["a", "b"], "position_a": "a", "position_b": "b"}]},
    )
    out = capi._team_tensions()
    assert len(out) == 1 and out[0]["generated_at"] is None


# ── Elena: persona running state (database-4) ─────────────────────────────────


def test_elena_query_prefix_filters_tombstoned_rows(monkeypatch):
    rows = [
        {"sk": f"CALLBACK#{PRE_GENESIS}#silence-crashes", "status": "pending", **TOMBSTONED},
        {"sk": f"CALLBACK#{POST_GENESIS}#new-promise", "status": "pending"},
    ]
    monkeypatch.setattr(elena, "table", _FakeTable(query_items=rows))
    got = elena._query_prefix("PERSONA#elena", "CALLBACK#")
    assert [r["sk"] for r in got] == [f"CALLBACK#{POST_GENESIS}#new-promise"]


def test_elena_get_item_hides_tombstoned_singleton(monkeypatch):
    monkeypatch.setattr(elena, "table", _FakeTable(item={**TOMBSTONED, "motifs": ["the body keeps receipts"]}))
    assert elena._get_item("PERSONA#elena", "MOTIF#state") is None


def test_elena_gather_state_clean_after_wipe(monkeypatch):
    wiped_rows = [
        {"sk": f"THREAD#{PRE_GENESIS}#silence-as-symptom", "status": "open", **TOMBSTONED},
        {"sk": f"CALLBACK#{PRE_GENESIS}#zone-2-walks", "status": "pending", **TOMBSTONED},
    ]
    fake = _FakeTable(item={**TOMBSTONED, "motifs": ["x"]}, query_items=wiped_rows)
    monkeypatch.setattr(elena, "table", fake)
    state = elena.gather_state()
    assert state["open_threads"] == []
    assert state["pending_callbacks"] == []
    assert state["motifs"] == []
    assert state["stance"] is None


# ── site_api: #1085 — the coach-route readers #946 missed ─────────────────────
# Live symptom (2026-07-12 pre-start): /api/coach_team served the WIPED cycle's
# ENSEMBLE#dispute argument, /api/panel_ledger the wiped bet ledger, and
# /api/field_notes?week= the wiped weekly note — all via reads that bypassed
# both the query-level phase filter and the singleton_visible predicate.


_DISPUTE_WIPED = {
    **TOMBSTONED,
    "topic": "Caloric intake adequacy",
    "week": "2026-W27",
    "coach_a": "nutrition_coach",
    "coach_b": "physical_coach",
    "turns": [{"speaker": "nutrition_coach", "name": "Dr. Marcus Webb", "line": "thin margins", "kind": "position"}],
}


def test_latest_dispute_hidden_when_newest_tombstoned(monkeypatch):
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[_DISPUTE_WIPED]))
    assert capi._latest_dispute() is None


def test_latest_dispute_hidden_on_phase_mismatch(monkeypatch):
    stale = {"phase": "pilot", "topic": "zone 2 fight", "turns": []}
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[stale]))
    assert capi._latest_dispute() is None


def test_latest_dispute_serves_current_cycle_thread(monkeypatch):
    fresh = {
        "phase": "experiment",
        "topic": "protein timing",
        "week": "2026-W29",
        "coach_a": "nutrition_coach",
        "coach_b": "training_coach",
        "turns": [{"speaker": "nutrition_coach", "name": "Dr. Marcus Webb", "line": "front-load it", "kind": "position"}],
        "created_at": "2026-07-20T00:00:00+00:00",
    }
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[fresh]))
    got = capi._latest_dispute()
    assert got is not None
    assert got["topic"] == "protein timing"
    assert got["turns"][0]["line"] == "front-load it"


def test_latest_dispute_none_when_partition_empty(monkeypatch):
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[]))
    assert capi._latest_dispute() is None


def test_latest_cycle_digest_hidden_when_tombstoned(monkeypatch):
    wiped = {**TOMBSTONED, "sk": "CYCLE#2026-07-10", "active_disagreements": [{"topic": "wiped fight", "coaches": ["sleep_coach"]}]}
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[wiped]))
    assert capi._latest_cycle_digest() is None


def test_latest_cycle_digest_passes_clean_record(monkeypatch):
    clean = {"sk": "CYCLE#2026-07-14", "active_disagreements": [{"topic": "fresh", "coaches": ["sleep_coach"]}], "phase": "experiment"}
    monkeypatch.setattr(capi, "table", _FakeTable(query_items=[clean]))
    got = capi._latest_cycle_digest()
    assert got is not None
    assert got["active_disagreements"][0]["topic"] == "fresh"


def test_stance_latest_hidden_when_tombstoned_or_phase_mismatched(monkeypatch):
    monkeypatch.setattr(capi, "table", _FakeTable(item={**TOMBSTONED, "headline_read": "old cycle read"}))
    assert capi._stance_latest("sleep_coach") is None
    # any non-current phase (not just 'pilot') is hidden after the #1085 normalization
    monkeypatch.setattr(capi, "table", _FakeTable(item={"phase": "cycle4", "headline_read": "old"}))
    assert capi._stance_latest("sleep_coach") is None


def test_stance_latest_passes_clean_record(monkeypatch):
    clean = {"headline_read": "fresh read", "phase": "experiment"}
    monkeypatch.setattr(capi, "table", _FakeTable(item=clean))
    assert capi._stance_latest("sleep_coach") == clean


def test_panel_ledger_empty_when_state_tombstoned(monkeypatch):
    wiped = {
        **TOMBSTONED,
        "state_json": json.dumps({"episode_count": 3, "open_bet": "step count", "bet_ledger": [{"outcome": "won"}]}),
    }
    monkeypatch.setattr(capi, "table", _FakeTable(item=wiped))
    body = json.loads(capi.handle_panel_ledger({})["body"])
    assert body["open_bet"] is None
    assert body["episode_count"] == 0
    assert body["ledger"] == []


def test_panel_ledger_serves_live_state(monkeypatch):
    live = {"state_json": json.dumps({"episode_count": 1, "open_bet": "hrv trend", "bet_ledger": [{"outcome": "open"}]})}
    monkeypatch.setattr(capi, "table", _FakeTable(item=live))
    body = json.loads(capi.handle_panel_ledger({})["body"])
    assert body["episode_count"] == 1
    assert body["open_bet"] == "hrv trend"


def test_field_note_single_week_hidden_when_tombstoned(monkeypatch):
    wiped = {**TOMBSTONED, "week": "2026-W27", "ai_present": "solid sleep consistency from the wiped cycle"}
    monkeypatch.setattr(capi, "table", _FakeTable(item=wiped))
    body = json.loads(capi.handle_field_notes({"queryStringParameters": {"week": "2026-W27"}})["body"])
    assert body["entry"] is None


def test_field_note_single_week_serves_current_cycle(monkeypatch):
    live = {"week": "2026-W29", "ai_present": "fresh note", "phase": "experiment"}
    monkeypatch.setattr(capi, "table", _FakeTable(item=live))
    body = json.loads(capi.handle_field_notes({"queryStringParameters": {"week": "2026-W29"}})["body"])
    assert body["entry"]["ai_present"] == "fresh note"


def test_recap_hidden_when_tombstoned(monkeypatch):
    # The live wiped RECAP#latest was only saved by its day-count guard
    # (claims day 7 > pre-start day 0) — which would expire on day 7 of the
    # NEW cycle. The tombstone guard must hide it regardless of day math.
    wiped = {**TOMBSTONED, "story_so_far": "week seven of the cut", "experiment_day": 7}
    monkeypatch.setattr(capi, "table", _FakeTable(item=wiped))
    body = json.loads(capi.handle_recap()["body"])
    assert body["recap"] is None


def test_recap_serves_clean_record(monkeypatch):
    live = {"story_so_far": "fresh cycle opening", "phase": "experiment"}
    monkeypatch.setattr(capi, "table", _FakeTable(item=live))
    monkeypatch.setattr(capi, "_regeneration_paused", lambda _f: False)
    body = json.loads(capi.handle_recap()["body"])
    assert body["recap"]["story_so_far"] == "fresh cycle opening"


# ── site-api-ai (board_ask prompt grounding): same class, separate lambda ─────


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def test_board_coach_memory_hidden_when_tombstoned(monkeypatch):
    ai = _ai()
    wiped = {**TOMBSTONED, "summary": "week 4 of the stall", "key_concerns": ["adherence"]}
    monkeypatch.setattr(ai, "table", _FakeTable(item=wiped))
    assert ai._coach_memory_bits("sleep_coach") == ""


def test_board_coach_memory_serves_clean_record(monkeypatch):
    ai = _ai()
    # grounding_gated: a clean post-#2428 row carries the compression gate's stamp —
    # without it the board reader excludes the row as ungated legacy state.
    monkeypatch.setattr(ai, "table", _FakeTable(item={"summary": "fresh cycle memory", "phase": "experiment", "grounding_gated": True}))
    assert "fresh cycle memory" in ai._coach_memory_bits("sleep_coach")


def test_board_coach_stance_bits_hidden_on_any_stale_phase(monkeypatch):
    ai = _ai()
    monkeypatch.setattr(ai, "table", _FakeTable(item={"phase": "cycle4", "headline_read": "old read"}))
    assert ai._coach_stance_bits("sleep_coach") == ""


def test_board_recent_interactions_query_is_phase_filtered(monkeypatch):
    ai = _ai()

    class _RecordingTable(_FakeTable):
        def query(self, **kw):
            self.query_kwargs = kw
            return {"Items": []}

    t = _RecordingTable()
    monkeypatch.setattr(ai, "table", t)
    assert ai._coach_recent_interactions("sleep_coach") == ""
    # #1085: the wiped cycle's INTERACTION# rows must be filtered server-side
    assert "FilterExpression" in t.query_kwargs


# ── site_api_data: #1197 — the latest-DATE# QUERY readers #946/#1085 missed ────
# handle_state_of_matthew / handle_forecast / handle_scenarios take the newest
# DATE# record via ScanIndexForward=False + Limit=1 and (before #1197) set
# available=True with no tombstone/phase guard — their _INTERNAL strip removed
# the `phase` attr instead of FILTERING on it. So a wiped cycle-N record served
# as current for the ~1-day..1-week window until the next writer run overwrote
# it (LIVE symptom: /api/state_of_matthew served the tombstoned cycle-5
# "Week 1, Day 1" brief on /coaching/ on Day 4 of cycle 6). Each partition is
# EXPERIMENT_SCOPED in phase_taxonomy, so the fix is the same singleton_visible
# predicate the coach get_item readers already apply.

# (handler, SOURCE# partition it reads latest-DATE# from) — enumerate every
# public latest-DATE# reader in site_api_data so a newly-added one without a
# guard fails this family.
_LATEST_DATE_READERS = [
    (capi_intel.handle_forecast, "forecast"),
    (capi_intel.handle_scenarios, "scenarios"),
    (capi_intel.handle_state_of_matthew, "state_of_matthew"),
]

_SOM_NARRATIVE = {
    "narrative": "# State of Matthew — Week 1, Day 1\n\nThe cut begins…",
    "date": "2026-07-12",
    "sections_available": {"forecast": True},
}


def _handler_body(handler):
    return json.loads(handler()["body"])


@pytest.mark.parametrize("source", [s for _h, s in _LATEST_DATE_READERS])
def test_latest_date_readers_cover_experiment_scoped_partitions(source):
    # Ties the guard set to the taxonomy: each partition guarded here must be
    # EXPERIMENT_SCOPED (if it were reclassified, the guard rationale changes).
    assert phase_taxonomy.SOURCE_CLASS[source] == phase_taxonomy.EXPERIMENT_SCOPED


@pytest.mark.parametrize("handler,source", _LATEST_DATE_READERS)
def test_latest_date_reader_hidden_when_tombstoned(monkeypatch, handler, source):
    wiped = {**TOMBSTONED, "date": PRE_GENESIS, **_SOM_NARRATIVE}
    monkeypatch.setattr(capi_intel, "table", _FakeTable(query_items=[wiped]))
    body = _handler_body(handler)
    assert body.get("available") is False
    # the wiped payload must not leak — no tombstoned narrative served as current
    assert "narrative" not in body
    assert body.get("tombstone") is not True


@pytest.mark.parametrize("handler,source", _LATEST_DATE_READERS)
def test_latest_date_reader_hidden_on_non_current_phase(monkeypatch, handler, source):
    # any non-current phase (not just 'pilot'), no tombstone attr — the latent
    # sibling shape (a surviving cycle-4 record that the wipe never tombstoned).
    stale = {"phase": "cycle4", "date": PRE_GENESIS, **_SOM_NARRATIVE}
    monkeypatch.setattr(capi_intel, "table", _FakeTable(query_items=[stale]))
    body = _handler_body(handler)
    assert body.get("available") is False
    assert "narrative" not in body


@pytest.mark.parametrize("handler,source", _LATEST_DATE_READERS)
def test_latest_date_reader_serves_current_cycle_record(monkeypatch, handler, source):
    fresh = {"phase": "experiment", "date": POST_GENESIS, **_SOM_NARRATIVE}
    monkeypatch.setattr(capi_intel, "table", _FakeTable(query_items=[fresh]))
    body = _handler_body(handler)
    assert body.get("available") is True


@pytest.mark.parametrize("handler,source", _LATEST_DATE_READERS)
def test_latest_date_reader_available_false_when_partition_empty(monkeypatch, handler, source):
    monkeypatch.setattr(capi_intel, "table", _FakeTable(query_items=[]))
    body = _handler_body(handler)
    assert body.get("available") is False


# ── #1895: the CLOSURE guard — derived, not hand-enumerated ───────────────────
# Everything above this line tests a reader someone remembered to add. That is
# why this class keeps coming back: #946 fixed the coach readers, #1085 fixed the
# ones #946 missed, #1197 fixed the latest-DATE# readers — and then #1654 split
# ledger/what_changed/discoveries out of site_api_data.py into a NEW module whose
# what_changed() read SNAPSHOT#current with no guard at all. Nothing here noticed,
# because nothing here asks "is that the complete set?"
#
# Live symptom (#1895, Day 3 of cycle 11): /api/what_changed served the cycle-5
# snapshot (tombstone=true, phase=pilot, computed_at 2026-07-04) and the home
# ribbon announced it as "newly unlocked this month" — 25 days stale, from a
# wiped cycle.
#
# So this test derives the reader set from the SOURCE instead: every get_item on
# a STATE#current / SNAPSHOT#current singleton in lambdas/web/ must apply the
# shared predicate. A new module gets caught the day it is written.

_SINGLETON_SKS = {"STATE#current", "SNAPSHOT#current"}

# Sites that read a singleton sk but are genuinely exempt. Each entry needs a
# reason — an allowlist without one is how this guard rots into a rubber stamp.
_SINGLETON_GUARD_EXEMPT: dict[tuple[str, str], str] = {}


def _singleton_get_item_sites():
    """(file, sk, lineno, guarded) for every get_item on a singleton sk in lambdas/web/."""
    import ast
    import pathlib

    web = pathlib.Path(__file__).resolve().parent.parent / "lambdas" / "web"
    out = []
    for path in sorted(web.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        lines = src.split("\n")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get_item"):
                continue
            sk = None
            for kw in node.keywords:
                if kw.arg != "Key" or not isinstance(kw.value, ast.Dict):
                    continue
                for k, v in zip(kw.value.keys, kw.value.values):
                    if isinstance(k, ast.Constant) and k.value == "sk" and isinstance(v, ast.Constant):
                        sk = v.value
            if sk not in _SINGLETON_SKS:
                continue
            # The guard may sit on the same line, just before, or a little after —
            # window generously, since a documented guard often carries a comment
            # block between the read and the predicate.
            window = "\n".join(lines[max(0, node.lineno - 6) : node.lineno + 16])
            out.append((path.name, sk, node.lineno, "singleton_visible" in window))
    return out


def test_singleton_reader_scan_finds_the_known_sites():
    """Guard the guard: if this finds nothing, the AST scan silently stopped working."""
    sites = _singleton_get_item_sites()
    assert len(sites) >= 4, f"expected several singleton readers in lambdas/web/, found {sites}"
    files = {f for f, _sk, _ln, _g in sites}
    assert "site_api_ledger.py" in files, "the #1895 what_changed reader must be in scope of this scan"


def test_every_singleton_reader_honors_the_restart_tombstone():
    """The closure property: no STATE#/SNAPSHOT#current reader may skip the predicate."""
    unguarded = [
        (f, sk, ln) for f, sk, ln, guarded in _singleton_get_item_sites() if not guarded and (f, sk) not in _SINGLETON_GUARD_EXEMPT
    ]
    assert not unguarded, (
        "singleton get_item reader(s) without singleton_visible — a restart tombstones "
        "these records rather than deleting them, so the wiped cycle would serve as "
        "current until the next writer run (#946/#1085/#1197/#1895):\n"
        + "\n".join(f"  {f}:{ln} sk={sk!r}" for f, sk, ln in unguarded)
        + "\nApply experiment.phase_filter.singleton_visible, or add a documented entry to _SINGLETON_GUARD_EXEMPT."
    )


# ── #1895: behavioural — /api/what_changed and the AI grounding read ──────────


def _what_changed_body(item):
    from web import site_api_ledger as led

    return json.loads(led.what_changed(_g={"table": _FakeTable(item=item)})["body"])


_WC_PILOT = {
    "deltas": [{"label": "sleep", "delta": 0.4, "direction": "up"}],
    "newly_unlocked": [{"label": "habit_pct_vs_day_grade", "r": 0.8777, "n": 20, "first_seen": "2026-06-30"}],
    "honest_null": False,
    "window_start": "2026-06-05",
    "window_end": "2026-07-04",
    "week": "2026-W27",
    "computed_at": "2026-07-04T20:45:08+00:00",
}


def test_what_changed_shaped_empty_when_tombstoned():
    """The live #1895 shape: the wiped cycle's snapshot must not serve as current."""
    body = _what_changed_body({**TOMBSTONED, **_WC_PILOT})
    assert body["honest_null"] is True
    assert body["newly_unlocked"] == [] and body["deltas"] == []
    # the wiped payload must not leak in any field
    assert body["window_start"] is None and body["window_end"] is None and body["week"] is None
    assert "0.8777" not in json.dumps(body)


def test_what_changed_shaped_empty_on_non_current_phase():
    """The latent sibling: a prior cycle's record the wipe never tombstoned."""
    body = _what_changed_body({"phase": "cycle4", **_WC_PILOT})
    assert body["honest_null"] is True and body["newly_unlocked"] == []


def test_what_changed_still_serves_the_current_cycle():
    """The guard must not break the feature — a clean record serves normally."""
    body = _what_changed_body({"phase": "experiment", **_WC_PILOT})
    assert body["honest_null"] is False
    assert body["newly_unlocked"][0]["label"] == "habit_pct_vs_day_grade"
    assert body["week"] == "2026-W27"


def test_what_changed_shaped_empty_when_absent():
    """Pre-first-run: unchanged behaviour (the branch this guard now shares)."""
    body = _what_changed_body(None)
    assert body["honest_null"] is True and body["deltas"] == []


def test_ask_grounding_drops_tombstoned_monthly_motion(monkeypatch):
    """#1895's third instance: the leak reaching the MODEL, not just the page.

    _ask_fetch_computed_reads grounds /api/ask. Unguarded it fed the wiped cycle's
    monthly deltas straight into the prompt, where no page-level check can see it.
    """
    ai = _ai()
    monkeypatch.setattr(ai, "table", _FakeTable(item={**TOMBSTONED, **_WC_PILOT}))
    reads = ai._ask_fetch_computed_reads()
    assert "0.8777" not in json.dumps(reads, default=str)
    assert not (reads.get("monthly_motion") or reads.get("what_changed"))


def test_ask_grounding_keeps_current_cycle_monthly_motion(monkeypatch):
    """The guard must not blind the model to the LIVE cycle's deltas."""
    ai = _ai()
    monkeypatch.setattr(ai, "table", _FakeTable(item={"phase": "experiment", **_WC_PILOT}))
    reads = ai._ask_fetch_computed_reads()
    assert "sleep" in json.dumps(reads, default=str)


# ── #1895: the home constellation's edges (acceptance criterion 2) ────────────
# /api/pillar_coupling reads a trailing-60 window of character_sheet DATE# records
# and computes pairwise Pearson r. character_sheet is wiped ("all") and tombstoned,
# so an UNFILTERED query draws the prior cycle. Live on Day 3 of cycle 11: 118 of
# 122 records tombstoned, yet the endpoint served 14 edges (r=-0.87, n=47, p=0.0,
# significant=true) labelled 2026-05-30 -> 2026-07-28 as current — statistically
# confident claims about a cycle that had been wiped.


def test_pillar_coupling_query_is_phase_filtered(monkeypatch):
    """The fake table cannot evaluate a FilterExpression, so assert it is SENT —
    same technique as test_board_recent_interactions_query_is_phase_filtered."""

    class _RecordingTable(_FakeTable):
        def query(self, **kw):
            self.query_kwargs = kw
            return {"Items": []}

    t = _RecordingTable()
    monkeypatch.setattr(capi_intel, "table", t)
    capi_intel.handle_pillar_coupling()
    assert "FilterExpression" in t.query_kwargs, (
        "pillar_coupling must phase-filter its character_sheet window, or the " "constellation draws the wiped cycle's co-movement (#1895)"
    )


def test_pillar_coupling_honest_null_on_a_thin_fresh_cycle(monkeypatch):
    """Post-filter, a fresh cycle has too few sheets to correlate — the honest answer
    is no edges, not edges derived from whatever survived."""
    monkeypatch.setattr(capi_intel, "table", _FakeTable(query_items=[]))
    body = json.loads(capi_intel.handle_pillar_coupling()["body"])
    assert body["honest_null"] is True
    assert body["edges"] == [] and body["window_days"] == 0


# ── #1895: the front-end belts (story.js) ────────────────────────────────────
# Source-level assertions: these are ES modules with site-absolute imports, so a
# real DOM render lives in tests/visual_qa.py (post-deploy). What must not happen
# silently is the belts being deleted, so pin their presence and their reasons.


def _story_js():
    import pathlib

    return (pathlib.Path(__file__).resolve().parent.parent / "site" / "assets" / "js" / "story.js").read_text(encoding="utf-8")


def test_home_ribbon_gates_this_month_copy_on_recency():
    """The copy says 'this month' — it must not describe a stale record. The server
    refuses tombstoned ones; this belt covers a NON-tombstoned record going stale
    when weekly-correlation-compute stalls (observed live: unchanged since 07-04)."""
    src = _story_js()
    assert "computed_at" in src and "MAX_AGE_DAYS" in src, "the #1895 recency belt is missing from story.js"
    assert "newly unlocked this month" in src, "the gated copy moved — re-point the belt"


def test_constellation_narrates_its_empty_state():
    """A fresh cycle renders nodes with no lines. Unexplained emptiness reads as a
    broken chart, so the caption must say why (Matthew's call on #1910)."""
    src = _story_js()
    assert "honest_null" in src, "the constellation empty-state branch is missing"
    assert "no lines yet" in src, "the empty constellation must explain itself, not just render blank"


# ── #1969: the GENERATION path (lambdas/intelligence + lambdas/coach) ─────────
# The web/ scan above closed the SERVING path. #1969 found the same class alive
# in the generation path: ai_expert_analyzer's prior-analysis get_item was
# tombstone-blind, so on Day 1 of cycle 11 it fed the wiped cycle-10 EXPERT#
# text into the live prompt as _prior_analysis_summary (the probable vector for
# #1897's "seven days of an experiment"), then the fresh put_item overwrote the
# record and hid the evidence. Sibling copies of the same unguarded _get_item
# helper lived in coach_ensemble_digest / coach_history_summarizer /
# coach_state_updater / coach_observatory_renderer / coach_quality_gate.
# Behavioural tests first, then the derived closure scan (guard the SET).


def test_expert_prior_analysis_hidden_when_tombstoned(monkeypatch):
    """The #1969 replay: a tombstoned EXPERT# record yields an empty prior_summary
    — honest absence (ADR-104), not fabricated continuity with a wiped cycle."""
    import ai_expert_analyzer_lambda as ana

    wiped = {**TOMBSTONED, "analysis": "Seven days of an experiment tell a story...", "key_recommendation": "hold the deficit"}
    monkeypatch.setattr(ana, "table", _FakeTable(item=wiped))
    assert ana._load_prior_analysis("nutrition") == ("", "")


def test_expert_prior_analysis_hidden_on_non_current_phase(monkeypatch):
    import ai_expert_analyzer_lambda as ana

    monkeypatch.setattr(ana, "table", _FakeTable(item={"phase": "pilot", "analysis": "old cycle text"}))
    assert ana._load_prior_analysis("nutrition") == ("", "")


def test_expert_prior_analysis_serves_current_cycle(monkeypatch):
    import ai_expert_analyzer_lambda as ana

    live = {"phase": "experiment", "analysis": "a" * 400, "key_recommendation": "b" * 300}
    monkeypatch.setattr(ana, "table", _FakeTable(item=live))
    summary, rec = ana._load_prior_analysis("nutrition")
    assert summary == "a" * 300 and rec == "b" * 200  # truncation contract unchanged


def test_expert_prior_analysis_empty_when_absent(monkeypatch):
    import ai_expert_analyzer_lambda as ana

    monkeypatch.setattr(ana, "table", _FakeTable(item=None))
    assert ana._load_prior_analysis("nutrition") == ("", "")


def _fn():
    import field_notes_lambda as fn

    return fn


def test_field_note_prior_notes_skip_tombstoned(monkeypatch):
    """Prior weeks' notes feed the field-notes prompt — the same prior-context
    class as the analyzer read. Wiped weeks contribute nothing."""
    fn = _fn()
    wiped = {**TOMBSTONED, "ai_present": "the wiped cycle's observation", "ai_tone": "steady"}
    monkeypatch.setattr(fn, "table", _FakeTable(item=wiped))
    assert fn.get_prior_notes("2026-W31") == []


def test_field_note_prior_notes_serve_current_cycle(monkeypatch):
    fn = _fn()
    live = {"phase": "experiment", "ai_present": "fresh observation", "ai_tone": "steady"}
    monkeypatch.setattr(fn, "table", _FakeTable(item=live))
    notes = fn.get_prior_notes("2026-W31", count=2)
    assert len(notes) == 2 and all(n["present"] == "fresh observation" for n in notes)


def test_field_note_tombstoned_week_regenerates(monkeypatch):
    """A tombstoned same-week note must not suppress the fresh cycle's generation
    — the public read is phase-filtered, so suppression leaves the week blank."""
    fn = _fn()
    monkeypatch.setattr(fn, "table", _FakeTable(item={**TOMBSTONED, "ai_generated_at": "2026-07-20T00:00:00"}))
    sentinel = RuntimeError("proceeded past the dedup check")
    monkeypatch.setattr(fn, "gather_week_data", lambda *a, **k: (_ for _ in ()).throw(sentinel))
    with pytest.raises(RuntimeError, match="proceeded past the dedup check"):
        fn.generate_field_notes("2026-W31")


def test_field_note_live_week_still_skips(monkeypatch):
    fn = _fn()
    monkeypatch.setattr(fn, "table", _FakeTable(item={"phase": "experiment", "ai_generated_at": "2026-07-30T00:00:00"}))
    assert fn.generate_field_notes("2026-W31")["status"] == "already_exists"


def _cg():
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    from intelligence import challenge_generator_lambda as cg

    return cg


def test_challenge_dedup_treats_tombstoned_as_absent(monkeypatch):
    """A tombstoned colliding challenge row is the wiped cycle's archive — the
    fresh cycle re-issues, and the put restamps the record."""
    cg = _cg()

    fake = _FakeTable(item={**TOMBSTONED, "name": "Zone 2 Block"})
    monkeypatch.setattr(cg, "table", fake)
    result = cg.store_challenge({"name": "Zone 2 Block", "domain": "movement"})
    assert result is not None
    assert fake.put_calls, "the fresh cycle's challenge must be written, not suppressed by the wiped record"


def test_challenge_dedup_still_skips_live_duplicate(monkeypatch):
    cg = _cg()

    fake = _FakeTable(item={"phase": "experiment", "name": "Zone 2 Block"})
    monkeypatch.setattr(cg, "table", fake)
    assert cg.store_challenge({"name": "Zone 2 Block", "domain": "movement"}) is None
    assert fake.put_calls == []


_COACH_GET_ITEM_MODULES = [
    "coach_ensemble_digest",
    "coach_history_summarizer",
    "coach_observatory_renderer",
    "coach_quality_gate",
    "coach_state_updater",
]


@pytest.mark.parametrize("modname", _COACH_GET_ITEM_MODULES)
def test_coach_get_item_hides_tombstoned_singleton(monkeypatch, modname):
    """Every copy of the coach _get_item helper honors the restart tombstone —
    the sibling set of the analyzer bug (#1969), fixed as a class."""
    import importlib

    mod = importlib.import_module(modname)
    monkeypatch.setattr(mod, "table", _FakeTable(item={**TOMBSTONED, "summary": "the wiped cycle's state"}))
    assert mod._get_item("COACH#sleep_coach", "COMPRESSED#latest") is None


@pytest.mark.parametrize("modname", _COACH_GET_ITEM_MODULES)
def test_coach_get_item_passes_clean_singleton(monkeypatch, modname):
    import importlib

    mod = importlib.import_module(modname)
    monkeypatch.setattr(mod, "table", _FakeTable(item={"summary": "fresh", "phase": "experiment"}))
    assert mod._get_item("COACH#sleep_coach", "COMPRESSED#latest") == {"summary": "fresh", "phase": "experiment"}


def test_relapse_event_ignores_tombstoned_habit_scores(monkeypatch):
    """A relapse 'event' fired off wiped vice_streaks would trigger stance
    refreshes from a cycle that no longer exists."""
    import coach_prediction_evaluator as pe

    monkeypatch.setattr(pe, "table", _FakeTable(item={**TOMBSTONED, "vice_streaks": {"zzq": 12}}))
    assert pe._habit_scores_for("2026-07-20") == {}


def test_habit_scores_serve_current_cycle(monkeypatch):
    import coach_prediction_evaluator as pe

    live = {"phase": "experiment", "vice_streaks": {"zzq": 12}}
    monkeypatch.setattr(pe, "table", _FakeTable(item=live))
    assert pe._habit_scores_for("2026-07-20") == live


# ── #1969: the closure scan for the generation path — derived, not enumerated ──
# Same technique as the web/ scan above, wider net: EVERY get_item call in
# lambdas/intelligence/ + lambdas/coach/ must either show the singleton_visible
# predicate near the call site or carry a documented exemption. Keyed by
# (package/file, unparsed sk expression) so the entry survives line drift but
# dies with a refactor — forcing the reason to be re-argued, not inherited.

_GENERATION_PACKAGES = ("intelligence", "coach")

_GENERATION_GET_ITEM_EXEMPT: dict = {
    (
        "coach/coach_chat_summary.py",
        "summary_sk(target)",
    ): "CHAT#summary — CROSS_PHASE since ADR-153 (the texting relationship survives resets); never tombstoned",
    (
        "coach/coach_chat_summary.py",
        "BITS_SK",
    ): "RELATIONSHIP#bits (#2487) — the inside-references ledger rides the same ADR-153 CROSS_PHASE rule as "
    "RELATIONSHIP#state and CHAT#summary: a reset re-anchors the experiment, it does not un-say a shared joke, "
    "so the row is never tombstoned and a visibility filter would hide memory that is supposed to survive",
    (
        "coach/coach_domain_facts.py",
        "'PROFILE#v1'",
    ): "user profile — cross_phase, no phase attr, never tombstoned (same as intelligence_common's entry)",
    (
        "intelligence/ai_expert_analyzer_lambda.py",
        "ingest_health_sk(src)",
    ): "SYSTEM# ingest-health ops row — system_state, never tombstoned",
    ("intelligence/intelligence_common.py", "'PROFILE#v1'"): "user profile — cross_phase, no phase attr, never tombstoned",
    (
        "intelligence/intelligence_common.py",
        "f'SOURCE#coach_credibility#{coach_id}'",
    ): "no live writer anywhere in the repo; fail-soft nascent default — nothing to tombstone",
    ("coach/coach_calibration.py", "conf_sk"): "domain-specific guard: explicit tombstone check restarts the Beta prior (ADR-077)",
    (
        "coach/coach_computation_engine.py",
        "'STATE#current'",
    ): "NARRATIVE#arc reuses the `phase` attr for its NARRATIVE phase — guarded on tombstone + entered_date < genesis instead (#946 special case)",
    (
        "coach/coach_corrections.py",
        "sk",
    ): "coach_corrections is CROSS_PHASE (durable machinery-feedback ledger) — never tombstoned at reset",
    (
        "coach/coach_diary_reaction.py",
        "sk",
    ): "deliberate cross-cycle dedup: entry-keyed reacted-already marker — treating a tombstoned reaction as absent would re-spend Bedrock re-reacting to pre-genesis entries",
    (
        "coach/coach_narrative_orchestrator.py",
        "'STATE#current'",
    ): "NARRATIVE#arc special case — tombstone + entered_date guard, documented in _narrative_arc_state (#946)",
    ("coach/coach_prediction_evaluator.py", "sk"): "domain-specific guard: explicit tombstone check restarts the Beta prior (ADR-077)",
    (
        "coach/coach_prediction_evaluator.py",
        "f'STANCE#{today_str}'",
    ): "event-refresh spend-cap counter — counting a same-day tombstoned stance is conservative (caps spend); content never feeds generation",
    (
        "coach/coach_prediction_evaluator.py",
        "_LAST_DECIDED_SK",
    ): "scientific-liveness marker — operational system_state, documented at the call site (#727)",
    (
        "coach/dispute_docket.py",
        "sk",
    ): "guarded via _docket_row_stands (applies singleton_visible), which also clears tombstoned rows out of the finite open-docket key space (#1801)",
    ("coach/intake_response.py", "f'DATE#{nxt}'"): "whoop is RAW_TIMESERIES — kept forever, never tombstoned",
    ("coach/inter_coach_dialogue_lambda.py", "'CONFIG#v1'"): "ENSEMBLE#influence_graph static config — system_state, no phase attr",
    (
        "coach/voice_fidelity_harness.py",
        "f'RUN#{run_month}'",
    ): "monthly-run idempotency marker — ops bookkeeping; a tombstoned marker suppressing a re-run is conservative",
}


def _generation_get_item_sites():
    """(pkg/file, sk_source, lineno, guarded) for every get_item call in the
    generation packages. sk_source is the unparsed AST of the inline Key sk value
    ('<dynamic>' when the Key is built elsewhere)."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "lambdas"
    out = []
    for pkg in _GENERATION_PACKAGES:
        for path in sorted((root / pkg).glob("*.py")):
            src = path.read_text(encoding="utf-8")
            lines = src.split("\n")
            for node in ast.walk(ast.parse(src)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get_item"):
                    continue
                sk_source = "<dynamic>"
                for kw in node.keywords:
                    if kw.arg == "Key" and isinstance(kw.value, ast.Dict):
                        for k, v in zip(kw.value.keys, kw.value.values):
                            if isinstance(k, ast.Constant) and k.value == "sk":
                                sk_source = ast.unparse(v)
                window = "\n".join(lines[max(0, node.lineno - 10) : node.lineno + 16])
                out.append((f"{pkg}/{path.name}", sk_source, node.lineno, "singleton_visible" in window))
    return out


def test_generation_get_item_scan_finds_the_known_sites():
    """Guard the guard: the scan must keep seeing the generation path."""
    sites = _generation_get_item_sites()
    assert len(sites) >= 25, f"expected the generation packages' get_item sites, found only {len(sites)}"
    keys = {(f, sk) for f, sk, _ln, _g in sites}
    assert (
        "intelligence/ai_expert_analyzer_lambda.py",
        "f'EXPERT#{expert_key}'",
    ) in keys, "the #1969 prior-analysis read left the scan's scope"


def test_generation_exemptions_do_not_rot():
    """Every exemption must still point at a real, still-unguarded call site —
    a stale entry is a hole the next blind read walks through."""
    sites = {(f, sk): guarded for f, sk, _ln, guarded in _generation_get_item_sites()}
    stale = [key for key in _GENERATION_GET_ITEM_EXEMPT if key not in sites or sites[key]]
    assert not stale, f"exemption entries no longer matching an unguarded site — remove or re-key them: {stale}"


def test_every_generation_get_item_guarded_or_exempt():
    """The #1969 closure property: no get_item in the generation path may be
    tombstone-blind without a documented reason."""
    unguarded = [
        (f, sk, ln) for f, sk, ln, guarded in _generation_get_item_sites() if not guarded and (f, sk) not in _GENERATION_GET_ITEM_EXEMPT
    ]
    assert not unguarded, (
        "tombstone-blind get_item call site(s) in the generation path — a restart "
        "tombstones experiment-scoped records IN PLACE, so an unguarded read feeds "
        "the wiped cycle's content into fresh-cycle generation (#946/#1969, live "
        "vector for #1897):\n"
        + "\n".join(f"  lambdas/{f}:{ln} sk={sk}" for f, sk, ln in unguarded)
        + "\nApply experiment.phase_filter.singleton_visible near the call site, "
        "or add a documented entry to _GENERATION_GET_ITEM_EXEMPT."
    )
