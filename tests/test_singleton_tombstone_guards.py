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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import coach_computation_engine as eng  # noqa: E402
import coach_narrative_orchestrator as orch  # noqa: E402
import elena_state_updater as elena  # noqa: E402
from ai_expert_analyzer_lambda import _load_engagement_signal  # noqa: E402
from constants import EXPERIMENT_START_DATE  # noqa: E402
from phase_filter import singleton_visible  # noqa: E402
from web import site_api_coach as capi  # noqa: E402

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
    monkeypatch.setattr(ai, "table", _FakeTable(item={"summary": "fresh cycle memory", "phase": "experiment"}))
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
