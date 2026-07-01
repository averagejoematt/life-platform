"""tests/test_engagement_coach.py — Phase 2: coaches notice the quiet stretch.

The presence/quiet-stretch signal (engagement_core → engagement_state) reaches
every coach through the SAME deterministic seam as stance/protocols. These tests
prove the trimmer drops the cause and stays quiet when present, and that the
handler injects the signal into the brief (and omits it when present).

All offline — DynamoDB / Haiku mocked.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_narrative_orchestrator as orch  # noqa: E402


def _orch_state():
    return {
        "target_compressed": {"summary": "", "key_concerns": []},
        "other_compressed": {},
        "ensemble_digest": {"coach_summaries": []},
        "influence_graph": {"weights": {}},
        "computation_results": {"trends": {}},
        "narrative_arc": {"current_phase": "early_baseline"},
        "voice_state": {"recent_openings": []},
        "open_threads": [],
        "active_predictions": [],
        "current_stance": None,
    }


def _lull_signal():
    return {
        "date": "2026-06-30",
        "presence_class": "quiet",
        "gap_days": 3,
        "last_food_log_date": "2026-06-26",
        "channels_quiet": ["food", "training", "habits"],
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
        "passive_read": {"rhr": 64},
    }


# ── the trimmer ───────────────────────────────────────────────────────────────


def test_trimmer_omits_when_present():
    present = {"presence_class": "present", "gap_days": 0, "returned": False}
    assert orch._engagement_for_brief(present) is None
    assert orch._engagement_for_brief(None) is None
    assert orch._engagement_for_brief({}) is None


def test_trimmer_surfaces_lull_without_cause():
    out = orch._engagement_for_brief(_lull_signal())
    assert out["presence_class"] == "quiet"
    assert out["gap_days"] == 3
    assert out["channels_quiet"] == ["food", "training", "habits"]
    assert out["passive_still_flowing"] is True
    # The cause of the gap must never be present — only carried real signals.
    assert "reason" not in out
    assert out["passive_read"] == {"rhr": 64}


def test_trimmer_surfaces_return_with_delta():
    sig = {
        "presence_class": "present",
        "gap_days": 0,
        "returned": True,
        "resumed_after_days": 5,
        "weight_delta_over_gap": 3.2,
    }
    out = orch._engagement_for_brief(sig)
    assert out is not None  # a return is news even though he's present again
    assert out["returned"] is True
    assert out["resumed_after_days"] == 5
    assert out["weight_delta_over_gap_lbs"] == 3.2


def test_trimmer_carries_planned_pause():
    sig = dict(_lull_signal(), planned_pause=True, planned_pause_reason="travel", presence_class="light")
    out = orch._engagement_for_brief(sig)
    assert out["planned_pause"] is True
    assert out["planned_pause_reason"] == "travel"


# ── the handler injection seam ────────────────────────────────────────────────


def _wire_handler(monkeypatch, state):
    monkeypatch.setattr(orch, "_gather_all_state", lambda cid: state)
    monkeypatch.setattr(orch, "_build_user_message", lambda *a, **k: [{"type": "text", "text": "x"}])
    monkeypatch.setattr(orch, "_call_haiku", lambda **k: {"coach_id": "sleep_coach", "generation_brief": {"narrative_beat": "x"}})
    monkeypatch.setattr(orch, "_cache_brief", lambda *a, **k: None)
    import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)


def test_handler_injects_engagement(monkeypatch):
    state = _orch_state()
    state["engagement_signal"] = _lull_signal()
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "sleep_coach", "date": "2026-06-30"}, None)
    es = brief["generation_brief"]["engagement_signal"]
    assert es["presence_class"] == "quiet"
    assert es["gap_days"] == 3


def test_handler_omits_engagement_when_present(monkeypatch):
    state = _orch_state()
    state["engagement_signal"] = {"presence_class": "present", "gap_days": 0, "returned": False}
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "sleep_coach", "date": "2026-06-30"}, None)
    assert "engagement_signal" not in brief["generation_brief"]


def test_handler_omits_engagement_when_absent(monkeypatch):
    state = _orch_state()  # no engagement_signal key at all
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "sleep_coach", "date": "2026-06-30"}, None)
    assert "engagement_signal" not in brief["generation_brief"]


def test_build_user_message_surfaces_engagement(monkeypatch):
    monkeypatch.setattr(orch, "_track_record_block", lambda cid: "(none)")
    state = _orch_state()
    state["engagement_signal"] = _lull_signal()
    blocks = orch._build_user_message(state, "sleep_coach", "2026-06-30")
    joined = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in blocks)
    assert "Presence signal" in joined
