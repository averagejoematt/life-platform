"""tests/test_coach_stance_engine.py — the coach-opinion engine (2026-06-29).

Covers the evolving, evidence-derived stance:
  * the raw-vitals guard (a stance speaks to THINKING, never fabricates numbers),
  * track-record reduction (agrees with the coach page's hit-rate),
  * grounded evolution — a "how my read changed" claim survives only with a real
    signal (a logged correction or a stage shift); first runs blank it,
  * self-correction once on a leaked number, with a residual grounding flag,
  * fail-soft: a stance error never aborts the weekly compression run,
  * the orchestrator closes the loop (STANCE#latest → brief.current_stance, verbatim),
  * the public render prefers STANCE#latest and falls back to the ladder offline.

All offline — `_call_haiku` and DynamoDB reads are mocked / fail through.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_history_summarizer as chs  # noqa: E402
import coach_narrative_orchestrator as orch  # noqa: E402
from web import site_api_coach as capi  # noqa: E402

# ── the raw-vitals guard ─────────────────────────────────────────────────────


class TestRawVitalsGuard:
    def test_detects_fabricated_numbers(self):
        assert chs._contains_raw_vitals("your HRV sat at 45 ms")
        assert chs._contains_raw_vitals("RHR is 64 now")
        assert chs._contains_raw_vitals("recovery hit 30%")
        assert chs._contains_raw_vitals("you're down to 232 lbs")

    def test_allows_clean_opinion_prose(self):
        assert not chs._contains_raw_vitals("your sleep duration is solid and steady now")
        assert not chs._contains_raw_vitals("I'm focused on consistency over any single peak night")

    def test_vital_hits_counts_across_fields(self):
        s = {"headline_read": "RHR 64 and HRV 45 ms", "focused_on_now": ["recovery 30%"]}
        assert chs._vital_hits(s) >= 2


# ── track-record reduction ───────────────────────────────────────────────────


def test_summarize_track_record():
    learning = [
        {"sk": "LEARNING#2026-06-20#a", "verdict": "confirmed", "claim_natural": "sleep would stabilize"},
        {"sk": "LEARNING#2026-06-18#b", "verdict": "refuted", "claim": "deep sleep up"},
        {"sk": "LEARNING#2026-06-15#c", "outcome": "confirmed"},
    ]
    conf = [{"subdomain": "duration", "mean_confidence": 0.72}]
    t = chs._summarize_track_record(learning, conf)
    assert (t["confirmed"], t["refuted"], t["decided"]) == (2, 1, 3)
    assert t["hit_rate_pct"] == 67
    assert t["confidence"]["duration"] == 0.72
    assert len(t["recent"]) == 3


def test_summarize_track_record_empty():
    t = chs._summarize_track_record([], [])
    assert t["decided"] == 0 and t["hit_rate_pct"] is None


# ── grounded evolution ───────────────────────────────────────────────────────


def test_claims_change_detector():
    assert chs._claims_change("I've changed my read")
    assert chs._claims_change("where I once worried, I now trust the trend")
    assert not chs._claims_change("I'm focused on consistency")


def test_sanitize_drops_ungrounded_change():
    stance = {"how_my_read_changed": "I changed my mind", "stage": {"label": "consistency"}, "coach_id": "c"}
    prior = {"stage": {"label": "consistency"}}
    chs._sanitize_stance(stance, {"corrections_made": []}, prior)
    assert stance["how_my_read_changed"] == ""


def test_sanitize_keeps_change_grounded_by_correction():
    stance = {"how_my_read_changed": "I changed my mind", "stage": {"label": "consistency"}, "coach_id": "c"}
    prior = {"stage": {"label": "consistency"}}
    chs._sanitize_stance(stance, {"corrections_made": ["was wrong about naps"]}, prior)
    assert stance["how_my_read_changed"]


def test_sanitize_keeps_change_grounded_by_stage_shift():
    stance = {"how_my_read_changed": "I shifted up a stage", "stage": {"label": "architecture"}, "coach_id": "c"}
    prior = {"stage": {"label": "consistency"}}
    chs._sanitize_stance(stance, {"corrections_made": []}, prior)
    assert stance["how_my_read_changed"]


# ── generation (mocked LLM) ──────────────────────────────────────────────────


def test_generate_stance_first_run_blanks_change(monkeypatch):
    monkeypatch.setattr(
        chs,
        "_call_haiku",
        lambda **k: {
            "headline_read": "Your sleep base is forming.",
            "focused_on_now": ["consistency"],
            "set_aside_for_now": ["architecture"],
            "stage": {"label": "foundation", "rationale": "early"},
            "how_my_read_changed": "I've shifted from duration to timing",  # model invented a change
            "confidence_note": "early days",
            "evidence_basis": ["thread x"],
        },
    )
    out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {"hit_rate_pct": None}, None)
    assert out["how_my_read_changed"] == ""  # no prior stance => no change is possible
    assert out["coach_id"] == "sleep_coach"
    assert out["as_of"] and out["grounding_flag"] is False


def test_generate_stance_self_corrects_leaked_vitals(monkeypatch):
    responses = [
        {"headline_read": "Your RHR dropped to 53 and HRV is 45 ms.", "stage": {"label": "x"}},
        {"headline_read": "Your recovery signal is trending the right way.", "stage": {"label": "x"}},
    ]
    calls = []

    def fake(**k):
        calls.append(k)
        return responses[len(calls) - 1]

    monkeypatch.setattr(chs, "_call_haiku", fake)
    out = chs._generate_stance("sleep_coach", {"corrections_made": []}, {}, None)
    assert len(calls) == 2  # regenerated once
    assert out["grounding_flag"] is False
    assert "53" not in out["headline_read"]


def test_generate_stance_flags_persistent_vitals(monkeypatch):
    monkeypatch.setattr(chs, "_call_haiku", lambda **k: {"headline_read": "RHR 53 bpm, steady", "stage": {"label": "x"}})
    out = chs._generate_stance("sleep_coach", {}, {}, None)
    assert out["grounding_flag"] is True


def test_generate_stance_non_dict_returns_none(monkeypatch):
    monkeypatch.setattr(chs, "_call_haiku", lambda **k: "not json")
    assert chs._generate_stance("sleep_coach", {}, {}, None) is None


# ── fail-soft orchestration in the weekly run ────────────────────────────────


def test_run_stance_skips_on_compression_fallback():
    r = chs._run_stance("sleep_coach", {"_fallback": True}, {})
    assert r["written"] is False and r["reason"] == "compression_fallback"


def test_run_stance_is_failsoft(monkeypatch):
    monkeypatch.setattr(chs, "_gather_learning", lambda cid: [])
    monkeypatch.setattr(chs, "_get_item", lambda pk, sk: None)

    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(chs, "_generate_stance", boom)
    r = chs._run_stance("sleep_coach", {"summary": "x"}, {"confidence_records": []})
    assert r["written"] is False and "error" in r  # swallowed, not raised


# ── orchestrator: closes the stance → generation loop ────────────────────────


def _orch_state(stance=None):
    empty = {"summary": "", "key_concerns": []}
    return {
        "target_compressed": empty,
        "other_compressed": {},
        "ensemble_digest": {"coach_summaries": []},
        "influence_graph": {"weights": {}},
        "computation_results": {"trends": {}},
        "narrative_arc": {"current_phase": "early_baseline"},
        "voice_state": {"recent_openings": []},
        "open_threads": [],
        "active_predictions": [],
        "current_stance": stance,
    }


def test_stance_for_brief_trims_internal_fields():
    full = {
        "headline_read": "h",
        "focused_on_now": ["a"],
        "set_aside_for_now": ["b"],
        "stage": {"label": "s"},
        "how_my_read_changed": "c",
        "as_of": "2026-06-29",
        "confidence_note": "n",
        "grounding_flag": True,
        "generated_at": "x",
        "evidence_basis": ["e"],
    }
    t = orch._stance_for_brief(full)
    assert set(t) == {"headline_read", "focused_on_now", "set_aside_for_now", "stage", "how_my_read_changed", "as_of"}
    assert "grounding_flag" not in t and "evidence_basis" not in t


def test_build_user_message_surfaces_stance(monkeypatch):
    monkeypatch.setattr(orch, "_track_record_block", lambda cid: "(none)")
    stance = {"headline_read": "your duration is solid", "focused_on_now": ["timing"], "stage": {"label": "consistency"}}
    blocks = orch._build_user_message(_orch_state(stance), "sleep_coach", "2026-06-29")
    suffix = blocks[-1]["text"]
    assert "Current Stance" in suffix
    assert "your duration is solid" in suffix


def test_handler_injects_stance_into_brief(monkeypatch):
    stance = {
        "headline_read": "your duration is solid",
        "focused_on_now": ["timing"],
        "set_aside_for_now": [],
        "stage": {"label": "consistency"},
        "how_my_read_changed": "",
        "as_of": "2026-06-29",
        "grounding_flag": False,
        "generated_at": "x",
    }
    monkeypatch.setattr(orch, "_gather_all_state", lambda cid: _orch_state(stance))
    monkeypatch.setattr(orch, "_build_user_message", lambda *a, **k: [{"type": "text", "text": "x"}])
    monkeypatch.setattr(orch, "_call_haiku", lambda **k: {"coach_id": "sleep_coach", "generation_brief": {"narrative_beat": "x"}})
    monkeypatch.setattr(orch, "_cache_brief", lambda *a, **k: None)
    import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)

    brief = orch.lambda_handler({"coach_id": "sleep_coach", "date": "2026-06-29"}, None)
    cs = brief["generation_brief"]["current_stance"]
    assert cs["headline_read"] == "your duration is solid"
    assert "grounding_flag" not in cs  # trimmed to the generation-relevant fields


# ── public render: stance preferred, ladder fallback ─────────────────────────


def test_stance_block_prefers_stance(monkeypatch):
    monkeypatch.setattr(
        capi,
        "_stance_latest",
        lambda cid: {
            "headline_read": "Your base is solid.",
            "focused_on_now": ["timing"],
            "set_aside_for_now": ["architecture"],
            "stage": {"label": "consistency"},
            "how_my_read_changed": "",
            "confidence_note": "steady",
            "as_of": "2026-06-29",
        },
    )
    sb = capi._stance_block("sleep_coach", 230)
    assert sb["source"] == "stance"
    assert sb["headline_read"] == "Your base is solid."
    assert sb["stage"]["label"] == "consistency"


def test_stance_block_falls_back_to_ladder(monkeypatch):
    monkeypatch.setattr(capi, "_stance_latest", lambda cid: None)
    sb = capi._stance_block("sleep_coach", 306)
    assert sb["source"] == "ladder"
    assert sb["band_metric"] == "weight_lbs"
    assert sb["headline_read"]  # mapped from the rung's read_of_him
    assert sb["stage"]["label"]  # mapped from the rung's headline
    assert sb["rung"]  # ladder extras preserved for back-compat
