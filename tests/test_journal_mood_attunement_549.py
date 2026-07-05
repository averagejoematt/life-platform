"""tests/test_journal_mood_attunement_549.py — #549 journal <-> mood attunement.

The mind coach's orchestrator brief gains a journal-derived mood/connection signal
(built from #505's journal extraction v2 — enriched_mood/stress/social_quality/
themes/emotions), so it can read how Matthew FEELS, not just what he does. No new
AI call: this enriches the existing per-coach orchestrator brief + the existing
mind-coach generation prompt (ai_calls._run_coach_v2_pipeline).

These tests pin:
  - the deterministic aggregate/trend computed from raw journal entries
  - the trimmer, including the privacy gate on `notable_quote` (vice/real-name hits
    are dropped, never redacted-and-kept, matching the chronicle/podcast posture)
  - domain-based routing: only coach(es) whose domain covers Matthew's inner state
    see the signal (mind_coach + explorer_coach today), not the other 6 coaches
  - the deterministic brief-injection seam (works on every path, incl. fallback)
  - the ai_calls.py prompt-block builder that turns the brief's journal_mood into
    coach-generation guidance, including the mind_coach.json low_sentiment_protocol

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


def _journal_item(date, sk_suffix, **fields):
    item = {"pk": "USER#matthew#SOURCE#notion", "sk": f"DATE#{date}#journal#{sk_suffix}", "date": date}
    item.update(fields)
    return item


# ── domain routing ──────────────────────────────────────────────────────────


class TestCoachRouting:
    def test_mind_coach_wants_it(self):
        assert orch._coach_wants_journal_mood("mind_coach") is True

    def test_explorer_sees_everything(self):
        assert orch._coach_wants_journal_mood("explorer_coach") is True

    def test_other_coaches_do_not(self):
        for cid in ("sleep_coach", "training_coach", "nutrition_coach", "physical_coach", "glucose_coach", "labs_coach"):
            assert orch._coach_wants_journal_mood(cid) is False, cid


# ── the gather (deterministic aggregation, no LLM) ──────────────────────────


class TestGatherJournalMoodSignal:
    def test_insufficient_entries_returns_none(self, monkeypatch):
        entries = [_journal_item("2026-07-01", "morning", enriched_mood=3.0)]

        class FakeTable:
            def query(self, **kwargs):
                return {"Items": entries}

        monkeypatch.setattr(orch, "table", FakeTable())
        assert orch._gather_journal_mood_signal() is None

    def test_no_entries_returns_none(self, monkeypatch):
        class FakeTable:
            def query(self, **kwargs):
                return {"Items": []}

        monkeypatch.setattr(orch, "table", FakeTable())
        assert orch._gather_journal_mood_signal() is None

    def test_aggregates_trend_emotions_and_social(self, monkeypatch):
        # 8 entries, mood rising (2,2,2,2 -> 4,4,4,4) so second half average is higher.
        entries = []
        moods = [2, 2, 2, 2, 4, 4, 4, 4]
        for i, m in enumerate(moods):
            entries.append(
                _journal_item(
                    f"2026-06-{20 + i:02d}",
                    "evening",
                    enriched_mood=float(m),
                    enriched_stress=3.0,
                    enriched_emotions=["anxious", "hopeful"] if i % 2 == 0 else ["content"],
                    enriched_themes=["work pressure"],
                    enriched_social_quality="alone" if i < 5 else "meaningful",
                    enriched_notable_quote=f"Quote from day {i}." if i == 7 else None,
                )
            )

        class FakeTable:
            def query(self, **kwargs):
                return {"Items": entries}

        monkeypatch.setattr(orch, "table", FakeTable())
        signal = orch._gather_journal_mood_signal()
        assert signal is not None
        assert signal["entries_analyzed"] == 8
        assert signal["mood_trend"]["direction"] == "rising"
        assert signal["stress_trend"]["direction"] == "stable"
        assert "work pressure" in signal["dominant_themes"]
        assert signal["social_quality_distribution"]["alone"] == 5
        assert signal["social_quality_distribution"]["meaningful"] == 3
        assert signal["alone_ratio"] == 0.62
        # Latest notable quote wins.
        assert signal["notable_quote"] == "Quote from day 7."

    def test_fail_soft_on_query_error(self, monkeypatch):
        class FakeTable:
            def query(self, **kwargs):
                raise RuntimeError("ddb unavailable")

        monkeypatch.setattr(orch, "table", FakeTable())
        assert orch._gather_journal_mood_signal() is None


# ── the trimmer (privacy gate) ───────────────────────────────────────────────


class TestJournalMoodForBrief:
    def test_none_in_none_out(self):
        assert orch._journal_mood_for_brief(None) is None

    def test_clean_quote_survives(self):
        signal = {
            "window_days": 21,
            "entries_analyzed": 9,
            "mood_trend": {"direction": "falling", "avg": 2.5, "delta": -0.6, "n": 9},
            "stress_trend": {"direction": "stable", "avg": 3.0, "delta": 0.1, "n": 9},
            "dominant_emotions": ["lonely", "tired"],
            "dominant_themes": ["work pressure", "social isolation"],
            "social_quality_distribution": {"alone": 6, "surface": 3},
            "alone_ratio": 0.67,
            "notable_quote": "I keep telling myself it's fine, but I don't think it is.",
            "notable_quote_date": "2026-07-02",
        }
        out = orch._journal_mood_for_brief(signal)
        assert out["mood_trend"]["direction"] == "falling"
        assert out["notable_quote"] == signal["notable_quote"]
        assert out["notable_quote_date"] == "2026-07-02"
        assert out["alone_ratio"] == 0.67

    def test_vice_quote_is_dropped_not_redacted(self):
        signal = {
            "window_days": 21,
            "entries_analyzed": 9,
            "mood_trend": {"direction": "falling"},
            "stress_trend": {"direction": "stable"},
            "dominant_emotions": [],
            "dominant_themes": [],
            "social_quality_distribution": {},
            "alone_ratio": None,
            "notable_quote": "Smoked some weed to take the edge off tonight.",
            "notable_quote_date": "2026-07-02",
        }
        out = orch._journal_mood_for_brief(signal)
        assert "notable_quote" not in out
        assert "notable_quote_date" not in out
        # The rest of the (non-sensitive) signal still reaches the brief.
        assert out["mood_trend"]["direction"] == "falling"

    def test_real_name_quote_is_dropped(self):
        signal = {
            "mood_trend": {},
            "stress_trend": {},
            "dominant_emotions": [],
            "dominant_themes": [],
            "social_quality_distribution": {},
            "notable_quote": "I should really listen to Peter Attia more.",
        }
        out = orch._journal_mood_for_brief(signal)
        assert "notable_quote" not in out

    def test_empty_social_distribution_and_alone_ratio_omitted(self):
        signal = {"mood_trend": {}, "stress_trend": {}, "dominant_emotions": [], "dominant_themes": []}
        out = orch._journal_mood_for_brief(signal)
        assert "social_quality_distribution" not in out
        assert "alone_ratio" not in out


# ── the handler injection seam (domain-gated) ────────────────────────────────


def _wire_handler(monkeypatch, state):
    monkeypatch.setattr(orch, "_gather_all_state", lambda cid: state)
    monkeypatch.setattr(orch, "_build_user_message", lambda *a, **k: [{"type": "text", "text": "x"}])
    monkeypatch.setattr(
        orch, "_call_haiku", lambda **k: {"coach_id": state.get("_coach_id", "mind_coach"), "generation_brief": {"narrative_beat": "x"}}
    )
    monkeypatch.setattr(orch, "_cache_brief", lambda *a, **k: None)
    import budget_guard

    monkeypatch.setattr(budget_guard, "allow", lambda feature: True)


_RICH_SIGNAL = {
    "window_days": 21,
    "entries_analyzed": 9,
    "mood_trend": {"direction": "falling", "avg": 2.5, "delta": -0.6, "n": 9},
    "stress_trend": {"direction": "rising", "avg": 3.8, "delta": 0.5, "n": 9},
    "dominant_emotions": ["lonely"],
    "dominant_themes": ["social isolation"],
    "social_quality_distribution": {"alone": 6},
    "alone_ratio": 0.8,
    "notable_quote": "Some days the quiet feels heavier than others.",
    "notable_quote_date": "2026-07-03",
}


def test_handler_injects_journal_mood_for_mind_coach(monkeypatch):
    state = _orch_state()
    state["journal_mood"] = _RICH_SIGNAL
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "mind_coach", "date": "2026-07-04"}, None)
    jm = brief["generation_brief"]["journal_mood"]
    assert jm["mood_trend"]["direction"] == "falling"
    assert jm["notable_quote"] == _RICH_SIGNAL["notable_quote"]


def test_handler_omits_journal_mood_for_other_coaches(monkeypatch):
    state = _orch_state()
    state["journal_mood"] = _RICH_SIGNAL
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "sleep_coach", "date": "2026-07-04"}, None)
    assert "journal_mood" not in brief["generation_brief"]


def test_handler_omits_journal_mood_when_signal_thin(monkeypatch):
    state = _orch_state()
    state["journal_mood"] = None  # gather returned None (too little data)
    _wire_handler(monkeypatch, state)
    brief = orch.lambda_handler({"coach_id": "mind_coach", "date": "2026-07-04"}, None)
    assert "journal_mood" not in brief["generation_brief"]


# ── planning-message surfacing (domain-gated) ────────────────────────────────


def test_build_user_message_surfaces_for_mind_coach(monkeypatch):
    monkeypatch.setattr(orch, "_track_record_block", lambda cid: "(none)")
    state = _orch_state()
    state["journal_mood"] = _RICH_SIGNAL
    blocks = orch._build_user_message(state, "mind_coach", "2026-07-04")
    joined = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in blocks)
    assert "Journal Mood Signal" in joined
    assert "Some days the quiet feels heavier" in joined


def test_build_user_message_hides_for_sleep_coach(monkeypatch):
    monkeypatch.setattr(orch, "_track_record_block", lambda cid: "(none)")
    state = _orch_state()
    state["journal_mood"] = _RICH_SIGNAL
    blocks = orch._build_user_message(state, "sleep_coach", "2026-07-04")
    joined = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in blocks)
    assert "Journal Mood Signal" not in joined


# ── ai_calls.py: brief -> generation-prompt block ────────────────────────────


class TestJournalMoodPromptBlock:
    def test_absent_signal_is_a_noop(self):
        import ai_calls as ac

        assert ac._build_journal_mood_prompt_block(None, {"low_sentiment_protocol": {"rules": ["x"]}}) == ""

    def test_present_signal_renders_generic_rules(self):
        import ai_calls as ac

        block = ac._build_journal_mood_prompt_block({"mood_trend": {"direction": "falling"}}, {})
        assert "JOURNAL MOOD SIGNAL" in block
        assert "Never diagnose" in block

    def test_present_signal_includes_mind_coach_low_sentiment_protocol(self):
        import ai_calls as ac

        voice_spec = {
            "low_sentiment_protocol": {
                "rules": [
                    "Never quote raw journal pain verbatim outside this private planning step.",
                ]
            }
        }
        block = ac._build_journal_mood_prompt_block({"mood_trend": {"direction": "falling"}}, voice_spec)
        assert "Never quote raw journal pain verbatim" in block


def test_mind_coach_json_has_low_sentiment_protocol():
    """The voice-spec-level tone rules (#549 acceptance criterion) live in the
    coach's own config, not hardcoded in ai_calls.py, so they can be tuned like
    every other voice-spec field."""
    import json

    path = os.path.join(_REPO, "config", "coaches", "mind_coach.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    proto = cfg.get("low_sentiment_protocol")
    assert proto and proto.get("rules")
    assert len(proto["rules"]) >= 3
