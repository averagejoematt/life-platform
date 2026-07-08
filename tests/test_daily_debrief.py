"""tests/test_daily_debrief.py — the daily ~2-minute "state of Matthew" audio
debrief (#734, epic #721).

Pins the contract:
- fact gathering reads ONLY already-computed records and drops absent fields
  (graceful degrade — no zero-fill)
- the ONE Haiku narration call never publishes a number or causal claim that
  isn't grounded in the pre-computed facts (ADR-104); a fabricated number, a
  causal phrase, a budget-tier pause, a Bedrock error, or an empty response all
  fall back to the SAME deterministic template narrative — which can only restate
  fields it was handed (fail-closed: an ungrounded sentence is dropped, not aired)
- the deterministic template never invents a number
- the RSS index + feed build newest-first with an <enclosure> per episode
- the handler is idempotent, self-gates on no data, and dry-runs without writing

No real Bedrock, DDB, or Google TTS calls anywhere in this file.
"""

import json
import os
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import bedrock_client  # noqa: E402
import budget_guard  # noqa: E402
import daily_debrief_lambda as dd  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


class _FakeBedrock:
    def __init__(self, text):
        self._text = text

    def as_dict(self):
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeTable:
    """Serves computed_metrics + habit_scores get_item; latest-date query."""

    def __init__(self, items=None, latest_date="2026-07-07"):
        self._items = items or {}
        self._latest = latest_date

    def get_item(self, Key):
        pk = Key["pk"]
        source = pk.split("SOURCE#")[-1]
        return {"Item": self._items.get(source)} if self._items.get(source) else {}

    def query(self, **kwargs):
        return {"Items": [{"date": self._latest, "sk": f"DATE#{self._latest}"}]}


class _FakeS3:
    def __init__(self, existing_index=None, mp3_exists=False):
        self.puts = {}
        self._index = existing_index
        self._mp3_exists = mp3_exists

    def head_object(self, Bucket, Key):
        if Key.endswith(".mp3") and not self._mp3_exists:
            raise RuntimeError("404")
        return {"ContentLength": 1234}

    def get_object(self, Bucket, Key):
        if Key.endswith("episodes.json") and self._index is not None:
            body = json.dumps({"episodes": self._index}).encode()

            class _B:
                def read(self_inner):
                    return body

            return {"Body": _B()}
        raise RuntimeError("404")

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts[Key] = Body


def _computed_metrics():
    return {
        "pk": dd.USER_PREFIX + "computed_metrics",
        "sk": "DATE#2026-07-07",
        "date": "2026-07-07",
        "day_grade_letter": "B",
        "day_grade_score": Decimal("81"),
        "recovery_pct": Decimal("62"),
        "hrv_ms": Decimal("88"),
        "rhr_bpm": Decimal("54"),
        "acwr": Decimal("1.1"),
        "zone": "optimal",
        "tier0_streak": Decimal("9"),
    }


def _habit_scores():
    return {
        "pk": dd.USER_PREFIX + "habit_scores",
        "sk": "DATE#2026-07-07",
        "date": "2026-07-07",
        "tier0_done": 5,
        "tier0_total": 6,
        "tier1_done": 2,
        "tier1_total": 4,
    }


def _full_facts():
    return {
        "date": "2026-07-07",
        "day_grade": "B",
        "day_grade_score": 81,
        "recovery_pct": 62,
        "hrv_ms": 88,
        "rhr_bpm": 54,
        "training_load_acwr": 1.1,
        "training_load_zone": "optimal",
        "core_habits_done": 5,
        "core_habits_total": 6,
        "tier0_streak_days": 9,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fact gathering
# ─────────────────────────────────────────────────────────────────────────────


class TestGatherFacts:
    def test_assembles_present_fields(self, monkeypatch):
        monkeypatch.setattr(dd, "table", _FakeTable({"computed_metrics": _computed_metrics(), "habit_scores": _habit_scores()}))
        facts = dd.gather_facts("2026-07-07")
        assert facts["day_grade"] == "B"
        assert facts["recovery_pct"] == 62
        assert facts["hrv_ms"] == 88
        assert facts["training_load_zone"] == "optimal"
        assert facts["core_habits_done"] == 5 and facts["core_habits_total"] == 6
        assert facts["tier0_streak_days"] == 9

    def test_drops_absent_fields_no_zero_fill(self, monkeypatch):
        # Only a grade present — recovery/hrv/habits genuinely missing → omitted, not 0.
        monkeypatch.setattr(dd, "table", _FakeTable({"computed_metrics": {"day_grade_letter": "A", "date": "2026-07-07"}}))
        facts = dd.gather_facts("2026-07-07")
        assert facts["day_grade"] == "A"
        assert "recovery_pct" not in facts
        assert "core_habits_total" not in facts
        assert "training_load_zone" not in facts


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic template — grounded by construction
# ─────────────────────────────────────────────────────────────────────────────


class TestDeterministicFallback:
    def test_uses_only_fact_numbers(self):
        text = dd.deterministic_fallback_narrative(_full_facts())
        allowed = dd.allowed_numbers(_full_facts())
        assert not dd.grounding_findings(text, facts=None, allowed=allowed)
        assert not dd._causal_language(text)

    def test_empty_facts_has_honest_message(self):
        assert "not enough" in dd.deterministic_fallback_narrative({"date": "2026-07-07"}).lower()


# ─────────────────────────────────────────────────────────────────────────────
# Narration — the ADR-104 grounded gate
# ─────────────────────────────────────────────────────────────────────────────


class TestNarrate:
    def test_budget_tier_pause_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)  # daily_debrief cutoff (Band 2)
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "budget_tier"

    def test_grounded_success(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        good = "Yesterday landed at a B. Recovery sat at 62 percent, HRV 88, resting heart rate 54. Core habits held 5 of 6."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrock(good).as_dict())
        result = dd.narrate(_full_facts())
        assert result["narrated"] is True and result["reason"] is None

    def test_fabricated_number_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        bad = "Recovery sat at 62 percent and weight came in at 173 pounds."  # 173 is nowhere in the facts
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrock(bad).as_dict())
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "grounding_gate"

    def test_causal_language_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        causal = "Recovery hit 62 percent because the training load eased."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrock(causal).as_dict())
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "grounding_gate"

    def test_bedrock_error_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)

        def _boom(body, model_name=None):
            raise RuntimeError("bedrock down")

        monkeypatch.setattr(bedrock_client, "invoke", _boom)
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "bedrock_error"

    def test_empty_response_falls_back(self, monkeypatch):
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: _FakeBedrock("   ").as_dict())
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "empty_response"


# ─────────────────────────────────────────────────────────────────────────────
# RSS index + feed
# ─────────────────────────────────────────────────────────────────────────────


class TestIndexes:
    def test_feed_and_index_written_newest_first(self, monkeypatch):
        fake = _FakeS3()
        monkeypatch.setattr(dd, "s3", fake)
        episodes = [
            {"date": "2026-07-06", "title": "old", "url": "/podcast/debrief/2026-07-06.mp3", "bytes": 10, "excerpt": "x"},
            {"date": "2026-07-07", "title": "new", "url": "/podcast/debrief/2026-07-07.mp3", "bytes": 20, "excerpt": "y"},
        ]
        dd._write_indexes(episodes)
        idx = json.loads(fake.puts[f"{dd.PREFIX}/episodes.json"])
        assert [e["date"] for e in idx["episodes"]] == ["2026-07-07", "2026-07-06"]
        feed = fake.puts[f"{dd.PREFIX}/feed.xml"]
        assert feed.count("<enclosure") == 2
        assert "audio/mpeg" in feed and "itunes:" in feed


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────


class TestHandler:
    def test_skips_when_no_computed_facts(self, monkeypatch):
        monkeypatch.setattr(dd, "table", _FakeTable({}, latest_date="2026-07-07"))
        monkeypatch.setattr(dd, "s3", _FakeS3(mp3_exists=False))
        out = dd.lambda_handler({}, None)
        assert json.loads(out["body"]).get("skipped") == "no facts"

    def test_idempotent_when_already_published(self, monkeypatch):
        monkeypatch.setattr(dd, "table", _FakeTable({"computed_metrics": _computed_metrics()}))
        monkeypatch.setattr(dd, "s3", _FakeS3(mp3_exists=True))
        out = dd.lambda_handler({}, None)
        assert json.loads(out["body"]).get("already_published") is True

    def test_dry_run_writes_nothing(self, monkeypatch):
        fake = _FakeS3(mp3_exists=False)
        monkeypatch.setattr(dd, "table", _FakeTable({"computed_metrics": _computed_metrics(), "habit_scores": _habit_scores()}))
        monkeypatch.setattr(dd, "s3", fake)
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)  # force template, no bedrock
        out = dd.lambda_handler({"dry_run": True}, None)
        body = json.loads(out["body"])
        assert body["dry_run"] is True
        assert body["facts"]["day_grade"] == "B"
        assert fake.puts == {}  # nothing synthesized or indexed
