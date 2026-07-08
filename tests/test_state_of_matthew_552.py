"""tests/test_state_of_matthew_552.py — the "State of Matthew" weekly model brief
(#552, epic #528).

Pins the contract:
- deterministic assembly gracefully degrades section-by-section (a genuinely
  unavailable input — e.g. calibration n=0 post-reset — is OMITTED, not
  zero-filled or errored around)
- the highlight picker is a fixed, deterministic priority order
- the ONE weekly Haiku narration call never gets to publish a number/causal
  claim that isn't grounded in the pre-computed state (ADR-104); a violation,
  a budget-tier pause, or a Bedrock error all fall back to the same
  deterministic templated narrative — no regeneration, no second call
- the DDB record shape + the I/O seams (fetch_* against a fake table)

No real Bedrock calls anywhere in this file.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

import bedrock_client  # noqa: E402
import budget_guard  # noqa: E402
import state_of_matthew_lambda as eng  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _forecast_summary():
    return {
        "date": "2026-07-05",
        "model": "ewma-v1",
        "confidence": 0.80,
        "forecasts": [
            {"metric": "recovery_pct", "unit": "%", "horizon_days": 1, "frame": "tomorrow", "point": 64.2, "lo": 55.0, "hi": 73.4},
            {"metric": "sleep_hours", "unit": "h", "horizon_days": 1, "frame": "tonight", "point": 7.1, "lo": 5.9, "hi": 8.3},
        ],
        "resolutions_today": [],
        "coverage": {"n_resolved": 10, "n_covered": 8, "coverage_pct": 80.0},
    }


def _hypothesis_items(cutoff="2026-06-28"):
    return [
        {
            "sk": "HYPOTHESIS#1",
            "hypothesis_id": "h1",
            "hypothesis": "Protein intake correlates with next-day deep sleep",
            "status": "pending",
            "confidence": "medium",
            "created_at": "2026-07-01T00:00:00",
        },
        {
            "sk": "HYPOTHESIS#2",
            "hypothesis_id": "h2",
            "hypothesis": "Late caffeine correlates with worse HRV",
            "status": "confirmed",
            "last_checked": "2026-07-04",
            "last_evidence": "effect size 0.6, CI excludes 0",
        },
        {
            "sk": "HYPOTHESIS#3",
            "hypothesis_id": "h3",
            "hypothesis": "Private test hypothesis",
            "status": "pending",
            "public": False,
        },
    ]


def _integrator_item():
    return {
        "generated_at": "2026-07-04T09:00:00",
        "disagreements": [
            {
                "topic": "sleep vs training load",
                "coaches_involved": ["sleep", "training"],
                "nakamura_call": "defer to the HRV trend as the tiebreaker",
            }
        ],
    }


def _calibration_summary(n=12):
    if n == 0:
        return {
            "n": 0,
            "confirmed": 0,
            "refuted": 0,
            "accuracy_pct": None,
            "brier": None,
            "brier_skill": None,
            "calibration": "insufficient_data",
            "label": "nascent",
        }
    return {
        "n": n,
        "confirmed": 9,
        "refuted": n - 9,
        "accuracy_pct": 75.0,
        "brier": 0.18,
        "brier_skill": 0.1,
        "calibration": "well-calibrated",
        "label": "reliable",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section builders — graceful degradation
# ─────────────────────────────────────────────────────────────────────────────


class TestGatherForecastSection:
    def test_none_when_unavailable(self):
        assert eng.gather_forecast_section(None) is None

    def test_shape_when_available(self):
        section = eng.gather_forecast_section(_forecast_summary())
        assert section["issued_date"] == "2026-07-05"
        assert len(section["expectations"]) == 2
        assert section["expectations"][0]["point"] == 64.2
        assert section["coverage"]["coverage_pct"] == 80.0


class TestGatherHypothesesSection:
    def test_none_when_no_items(self):
        assert eng.gather_hypotheses_section([], "2026-06-28") is None

    def test_none_when_all_private(self):
        items = [{"sk": "HYPOTHESIS#1", "status": "pending", "public": False}]
        assert eng.gather_hypotheses_section(items, "2026-06-28") is None

    def test_excludes_private_counts_and_status(self):
        section = eng.gather_hypotheses_section(_hypothesis_items(), "2026-06-28")
        assert section["total"] == 2  # the public: False one is excluded
        assert section["by_status"] == {"pending": 1, "confirmed": 1}
        assert section["active_count"] == 1

    def test_recently_resolved_respects_cutoff(self):
        # cutoff after the resolution date -> not "this week"
        section = eng.gather_hypotheses_section(_hypothesis_items(), cutoff_str="2026-07-05")
        assert section["recently_resolved"] == []
        # cutoff before the resolution date -> included
        section2 = eng.gather_hypotheses_section(_hypothesis_items(), cutoff_str="2026-06-28")
        assert len(section2["recently_resolved"]) == 1
        assert section2["recently_resolved"][0]["hypothesis_id"] == "h2"


class TestGatherCoachConsensusSection:
    def test_none_when_unavailable(self):
        assert eng.gather_coach_consensus_section(None) is None

    def test_shape_with_disagreements(self):
        section = eng.gather_coach_consensus_section(_integrator_item())
        assert section["disagreement_count"] == 1
        assert section["disagreements"][0]["topic"] == "sleep vs training load"
        assert section["disagreements"][0]["coaches"] == ["sleep", "training"]

    def test_present_but_empty_when_no_current_disputes(self):
        section = eng.gather_coach_consensus_section({"generated_at": "2026-07-04", "disagreements": []})
        assert section is not None
        assert section["disagreement_count"] == 0


class TestGatherCalibrationSection:
    def test_none_when_n_zero_post_reset(self):
        # the exact documented post-reset empty state
        assert eng.gather_calibration_section(_calibration_summary(n=0)) is None
        assert eng.gather_calibration_section(None) is None

    def test_shape_when_graded(self):
        section = eng.gather_calibration_section(_calibration_summary(n=12))
        assert section["n"] == 12
        assert section["calibration"] == "well-calibrated"
        assert section["brier"] == 0.18


# ─────────────────────────────────────────────────────────────────────────────
# Highlight + assembly
# ─────────────────────────────────────────────────────────────────────────────


class TestPickHighlight:
    def test_none_when_nothing_available(self):
        assert eng.pick_highlight(None, None, None, None) is None

    def test_hypothesis_resolution_wins_first(self):
        hyp = eng.gather_hypotheses_section(_hypothesis_items(), "2026-06-28")
        cal = eng.gather_calibration_section(_calibration_summary(12))
        h = eng.pick_highlight(None, hyp, None, cal)
        assert h["kind"] == "hypothesis_resolution"

    def test_forecast_resolution_next(self):
        forecast = eng.gather_forecast_section(_forecast_summary())
        forecast["resolutions_this_run"] = [{"metric": "recovery_pct", "covered": False, "actual": 40.0}]
        cal = eng.gather_calibration_section(_calibration_summary(12))
        h = eng.pick_highlight(forecast, None, None, cal)
        assert h["kind"] == "forecast_resolution"
        assert h["detail"]["covered"] is False  # a miss is prioritized over a hit

    def test_calibration_next_at_n_5_or_more(self):
        cal = eng.gather_calibration_section(_calibration_summary(12))
        h = eng.pick_highlight(None, None, None, cal)
        assert h["kind"] == "calibration"

    def test_calibration_skipped_under_n_5(self):
        cal = {
            "n": 3,
            "confirmed": 2,
            "refuted": 1,
            "accuracy_pct": 66.7,
            "brier": 0.2,
            "brier_skill": None,
            "calibration": "insufficient_data",
            "label": "nascent",
        }
        coaches = eng.gather_coach_consensus_section(_integrator_item())
        h = eng.pick_highlight(None, None, coaches, cal)
        assert h["kind"] == "coach_disagreement"

    def test_coach_disagreement_last(self):
        coaches = eng.gather_coach_consensus_section(_integrator_item())
        h = eng.pick_highlight(None, None, coaches, None)
        assert h["kind"] == "coach_disagreement"


class TestAssembleState:
    def test_sections_available_flags(self):
        forecast = eng.gather_forecast_section(_forecast_summary())
        state = eng.assemble_state(forecast, None, None, None, "2026-07-05")
        assert state["sections_available"] == {"forecast": True, "hypotheses": False, "coaches": False, "calibration": False}
        assert state["hypotheses"] is None
        assert state["as_of"] == "2026-07-05"

    def test_all_present(self):
        forecast = eng.gather_forecast_section(_forecast_summary())
        hyp = eng.gather_hypotheses_section(_hypothesis_items(), "2026-06-28")
        coaches = eng.gather_coach_consensus_section(_integrator_item())
        cal = eng.gather_calibration_section(_calibration_summary(12))
        state = eng.assemble_state(forecast, hyp, coaches, cal, "2026-07-05")
        assert all(state["sections_available"].values())
        assert state["highlight"]["kind"] == "hypothesis_resolution"


# ─────────────────────────────────────────────────────────────────────────────
# Narration — Bedrock always mocked, never called for real
# ─────────────────────────────────────────────────────────────────────────────


def _full_state():
    forecast = eng.gather_forecast_section(_forecast_summary())
    coaches = eng.gather_coach_consensus_section(_integrator_item())
    cal = eng.gather_calibration_section(_calibration_summary(12))
    return eng.assemble_state(forecast, None, coaches, cal, "2026-07-05")


class _FakeBedrockResponse:
    def __init__(self, text):
        self.text = text

    def as_dict(self):
        return {"content": [{"type": "text", "text": self.text}]}


class TestNarrate:
    def test_budget_tier_paused_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)  # tier 2 == state_of_matthew cutoff (ADR-125 reader-narrative band)
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is False
        assert result["reason"] == "budget_tier"
        assert result["narrative"]  # still produces something

    def test_grounded_success(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        grounded_text = (
            "The forecast engine expects recovery near 64.2%, with an interval of 55.0 to 73.4. "
            "Across 12 graded predictions the platform is well-calibrated, with a Brier score of 0.18. "
            "One coach disagreement remains open about sleep vs training load."
        )
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrockResponse(grounded_text).as_dict())
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is True
        assert result["narrative"] == grounded_text
        assert result["reason"] is None

    def test_fabricated_number_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        bad_text = "The forecast engine expects recovery near 947.6% next week."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrockResponse(bad_text).as_dict())
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is False
        assert result["reason"] == "grounding_gate"
        assert result["narrative"] != bad_text

    def test_causal_language_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        causal_text = "Poor sleep causes lower recovery this week."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrockResponse(causal_text).as_dict())
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is False
        assert result["reason"] == "grounding_gate"

    def test_bedrock_error_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

        def _boom(body, model_name=None):
            raise RuntimeError("throttled")

        monkeypatch.setattr(bedrock_client, "invoke", _boom)
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is False
        assert result["reason"] == "bedrock_error"

    def test_empty_response_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: {"content": [{"type": "text", "text": "   "}]})
        state = _full_state()
        result = eng.narrate(state)
        assert result["narrated"] is False
        assert result["reason"] == "empty_response"


class TestDeterministicFallbackNarrative:
    def test_empty_state_has_honest_message(self):
        state = eng.assemble_state(None, None, None, None, "2026-07-05")
        text = eng.deterministic_fallback_narrative(state)
        assert "not enough" in text.lower()

    def test_uses_only_state_fields(self):
        state = _full_state()
        text = eng.deterministic_fallback_narrative(state)
        assert "64.2" in text
        assert "12" in text  # calibration n


class TestCausalLanguage:
    def test_detects_banned_phrase(self):
        assert eng._causal_language("This causes that.") != []

    def test_clean_text_passes(self):
        assert eng._causal_language("Recovery and sleep tend to move together this week.") == []


# ─────────────────────────────────────────────────────────────────────────────
# DDB record shape + fetch seams
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildSummaryItem:
    def test_shape(self):
        state = _full_state()
        narration = {"narrative": "text", "narrated": True, "model": "claude-haiku-4-5-20251001", "reason": None}
        item = eng.build_summary_item(state, narration, "2026-07-05")
        assert item["pk"] == eng.STATE_PK
        assert item["sk"] == "DATE#2026-07-05"
        assert item["record_type"] == "state_of_matthew_brief"
        assert item["narrative"] == "text"
        assert item["narrated"] is True
        assert item["sections_available"]["forecast"] is True
        assert item["hypotheses"] is None  # graceful degrade preserved into storage


def _FakeTable(query_responses=None, get_item_response=None):
    """Query/get_item return canned rows in call order; put_item captured
    (via the base class's default .puts log)."""
    queue = list(query_responses or [])

    def _query_hook(_table, **kw):
        return queue.pop(0) if queue else {"Items": []}

    def _get_item_hook(_table, key, **kw):
        return {"Item": get_item_response} if get_item_response else {}

    return FakeDdbTable(query_hook=_query_hook, get_item_hook=_get_item_hook)


class TestFetchSeams:
    def test_fetch_forecast_summary_none_when_empty(self, monkeypatch):
        monkeypatch.setattr(eng, "table", _FakeTable(query_responses=[{"Items": []}]))
        assert eng.fetch_forecast_summary() is None

    def test_fetch_forecast_summary_returns_latest(self, monkeypatch):
        monkeypatch.setattr(eng, "table", _FakeTable(query_responses=[{"Items": [_forecast_summary()]}]))
        result = eng.fetch_forecast_summary()
        assert result["date"] == "2026-07-05"

    def test_fetch_coach_consensus_none_when_absent(self, monkeypatch):
        monkeypatch.setattr(eng, "table", _FakeTable(get_item_response=None))
        assert eng.fetch_coach_consensus() is None

    def test_fetch_calibration_summary_aggregates_all_sources(self, monkeypatch):
        # 8 coach queries (all empty) + 1 hypothesis-ledger query with a resolved pair
        responses = [{"Items": []} for _ in eng.COACH_IDS] + [{"Items": [{"stated_confidence": "high", "outcome": "confirmed"}]}]
        fake = _FakeTable(query_responses=responses)
        monkeypatch.setattr(eng, "table", fake)
        summary = eng.fetch_calibration_summary()
        assert summary["n"] == 1
        assert summary["confirmed"] == 1


class TestLambdaHandler:
    def test_writes_a_record_and_degrades_gracefully(self, monkeypatch):
        # Only the forecast + calibration inputs are available this run.
        monkeypatch.setattr(eng, "fetch_forecast_summary", lambda: _forecast_summary())
        monkeypatch.setattr(eng, "fetch_hypotheses", lambda: [])
        monkeypatch.setattr(eng, "fetch_coach_consensus", lambda: None)
        monkeypatch.setattr(eng, "fetch_calibration_summary", lambda: _calibration_summary(12))
        monkeypatch.setattr(eng, "narrate", lambda state: {"narrative": "stub", "narrated": False, "model": None, "reason": "budget_tier"})

        fake = _FakeTable()
        monkeypatch.setattr(eng, "table", fake)

        result = eng.lambda_handler({}, None)

        assert result["sections_available"] == {"forecast": True, "hypotheses": False, "coaches": False, "calibration": True}
        assert len(fake.puts) == 1
        written = fake.puts[0]
        assert written["pk"] == eng.STATE_PK
        # None sections are stripped entirely before the DDB write (forecast_engine's
        # convention) — absence, not a null value, is how "omitted" is stored.
        assert written.get("hypotheses") is None
        assert written.get("coaches") is None
        assert "forecast" in written
        assert "calibration" in written
