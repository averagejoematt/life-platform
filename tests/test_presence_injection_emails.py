"""tests/test_presence_injection_emails.py — #967: presence-block coverage on the
four private-email narrative surfaces #921 missed (daily_debrief, monday_compass,
weekly_digest, monthly_digest).

Pins the contract (the exact seam daily_brief uses — one shared
engagement_core.presence_prompt_block, rendered from the STATE#current read,
fail-soft, empty when Matthew is present):

- each lambda's `_presence_block()` renders the ONE shared block from a dark
  engagement signal, returns "" when Matthew is present, and returns "" (never
  raises) when the DDB read fails
- the block actually lands in each surface's LLM prompt, so a dark stretch is
  never narrated as a normal day/week/month over the silence (ADR-104
  behavioral-absence semantics — the block reflects honest presence, it never
  fabricates activity)
- daily_debrief's ADR-104 grounding gate treats the gap numbers the model was
  HANDED (inside the presence block) as grounded vocabulary — and still rejects
  them as fabricated when no presence block was given

No real Bedrock, DDB, SES, or HTTP calls anywhere in this file.
"""

import json
import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import bedrock_client  # noqa: E402
import budget_guard  # noqa: E402
import daily_debrief_lambda as dd  # noqa: E402
import engagement_core as ec  # noqa: E402
import monday_compass_lambda as mc  # noqa: E402
import monthly_digest_lambda as md  # noqa: E402
import pytest  # noqa: E402
import weekly_digest_lambda as wd  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

MODULES = [dd, mc, wd, md]


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — the same dark signal shape #921's tests pin in
# tests/test_presence_severity_and_ack.py
# ─────────────────────────────────────────────────────────────────────────────


def _sig(**kw):
    base = {
        "presence_class": "dark",
        "gap_days": 15,
        "severity": "alarm",
        "last_food_log_date": "2026-06-15",
        "channels_quiet": ["food", "training", "habits", "journal"],
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
    }
    base.update(kw)
    return base


def _table_with_signal(sig):
    """Serves STATE#current for the engagement_state partition, {} otherwise."""

    def _hook(_table, key, **_kw):
        if key.get("pk", "").endswith("SOURCE#engagement_state") and key.get("sk") == "STATE#current":
            return {"Item": sig} if sig else {}
        return {}

    return FakeDdbTable(get_item_hook=_hook)


def _raising_table():
    def _hook(_table, key, **_kw):
        raise RuntimeError("DDB down")

    return FakeDdbTable(get_item_hook=_hook)


DARK_BLOCK = ec.presence_prompt_block(_sig())
assert DARK_BLOCK  # the fixture must render a non-empty block or every test is vacuous


# ─────────────────────────────────────────────────────────────────────────────
# The shared helper contract — identical across all four lambdas
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mod", MODULES, ids=lambda m: m.__name__)
class TestPresenceBlockHelper:
    def test_renders_shared_block_from_dark_signal(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "table", _table_with_signal(_sig()))
        blk = mod._presence_block()
        assert blk == DARK_BLOCK  # the ONE shared block, not a local variant
        assert "15 days" in blk

    def test_empty_when_present(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "table", _table_with_signal({"presence_class": "present", "returned": False}))
        assert mod._presence_block() == ""

    def test_empty_when_no_state_record(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "table", _table_with_signal(None))
        assert mod._presence_block() == ""

    def test_fail_soft_on_ddb_error(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "table", _raising_table())
        assert mod._presence_block() == ""


# ─────────────────────────────────────────────────────────────────────────────
# daily_debrief — injection + the grounding allow-list stays honest
# ─────────────────────────────────────────────────────────────────────────────


def _full_facts():
    return {
        "date": "2026-07-07",
        "day_grade": "B",
        "day_grade_score": 81,
        "recovery_pct": 62,
        "hrv_ms": 88,
        "rhr_bpm": 54,
    }


class TestDebriefInjection:
    def test_block_lands_in_system_prompt(self):
        body = dd.build_narration_body(_full_facts(), presence_block=DARK_BLOCK)
        assert DARK_BLOCK in body["system"]

    def test_no_block_no_change(self):
        assert DARK_BLOCK not in dd.build_narration_body(_full_facts())["system"]

    # 17 is deliberately NOT in the grounding gate's benign-numbers list (15 is),
    # so these two tests prove the allow-list moves with the block, not by luck.
    def test_gap_numbers_handed_to_model_are_grounded(self, monkeypatch):
        blk = ec.presence_prompt_block(_sig(gap_days=17))
        assert "17 days" in blk
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        text = "Recovery sat at 62 percent, but the bigger story: 17 days without a logged meal."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: {"content": [{"type": "text", "text": text}]})
        result = dd.narrate(_full_facts(), presence_block=blk)
        assert result["narrated"] is True and result["reason"] is None

    def test_gap_numbers_without_block_still_fabricated(self, monkeypatch):
        # The allow-list only grows by what the model was actually handed —
        # the same 17-day claim with NO presence block stays a fabrication.
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
        text = "Recovery sat at 62 percent, but the bigger story: 17 days without a logged meal."
        monkeypatch.setattr(bedrock_client, "invoke", lambda body, model_name=None: {"content": [{"type": "text", "text": text}]})
        result = dd.narrate(_full_facts())
        assert result["narrated"] is False and result["reason"] == "grounding_gate"


# ─────────────────────────────────────────────────────────────────────────────
# monday_compass — injection into the system prompt
# ─────────────────────────────────────────────────────────────────────────────


class TestCompassInjection:
    def test_block_lands_in_system_prompt(self, monkeypatch):
        monkeypatch.setattr(mc, "table", _table_with_signal(_sig()))
        system = mc.build_system_prompt("JOURNEY CONTEXT SENTINEL")
        assert DARK_BLOCK in system
        assert "JOURNEY CONTEXT SENTINEL" in system

    def test_unchanged_when_present(self, monkeypatch):
        monkeypatch.setattr(mc, "table", _table_with_signal({"presence_class": "present", "returned": False}))
        assert mc.build_system_prompt("JCTX") == mc.SYSTEM_PROMPT.format(journey_context="JCTX")


# ─────────────────────────────────────────────────────────────────────────────
# weekly / monthly digests — injection into the board user prompt
# ─────────────────────────────────────────────────────────────────────────────


def _capture_request(monkeypatch, mod):
    captured = {}

    def _fake_call(req, timeout=55, **_kw):
        captured["prompt"] = json.loads(req.data)["messages"][0]["content"]
        return {"content": [{"text": "board verdict"}]}

    monkeypatch.setattr(mod, "call_anthropic_with_retry", _fake_call)
    return captured


class TestWeeklyDigestInjection:
    def test_block_lands_in_board_prompt(self, monkeypatch):
        monkeypatch.setattr(wd, "table", _table_with_signal(_sig()))
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", False)
        captured = _capture_request(monkeypatch, wd)
        assert wd.call_haiku({}, {}) == "board verdict"
        assert DARK_BLOCK in captured["prompt"]

    def test_no_block_when_present(self, monkeypatch):
        monkeypatch.setattr(wd, "table", _table_with_signal({"presence_class": "present", "returned": False}))
        monkeypatch.setattr(wd, "_HAS_INSIGHT_WRITER", False)
        captured = _capture_request(monkeypatch, wd)
        wd.call_haiku({}, {})
        assert DARK_BLOCK not in captured["prompt"]


class TestMonthlyDigestInjection:
    def test_block_lands_in_board_prompt(self, monkeypatch):
        monkeypatch.setattr(md, "table", _table_with_signal(_sig()))
        monkeypatch.setattr(md, "_HAS_INSIGHT_WRITER", False)
        monkeypatch.setattr(md, "_build_monthly_prompt_from_config", lambda: None)  # offline: fallback prompt
        captured = _capture_request(monkeypatch, md)
        assert md.call_haiku_monthly({}, {}) == "board verdict"
        assert DARK_BLOCK in captured["prompt"]

    def test_no_block_when_present(self, monkeypatch):
        monkeypatch.setattr(md, "table", _table_with_signal({"presence_class": "present", "returned": False}))
        monkeypatch.setattr(md, "_HAS_INSIGHT_WRITER", False)
        monkeypatch.setattr(md, "_build_monthly_prompt_from_config", lambda: None)
        captured = _capture_request(monkeypatch, md)
        md.call_haiku_monthly({}, {})
        assert DARK_BLOCK not in captured["prompt"]
