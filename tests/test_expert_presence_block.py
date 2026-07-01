"""The presence / quiet-stretch steering block for the observatory experts + the
integrator (the cockpit verdict path). This closes the gap the orchestrator wiring
missed: ai_expert_analyzer generates the cockpit's headline verdict + per-pillar
reads, and without this it would crown a flawless week over days Matthew logged
nothing. Empty when present; loud + honest when quiet or returned; never the cause.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))

import ai_expert_analyzer_lambda as az  # noqa: E402


def _sig(**kw):
    base = {
        "presence_class": "dark",
        "gap_days": 5,
        "last_food_log_date": "2026-06-24",
        "channels_quiet": ["food", "journal"],
        "passive_still_flowing": True,
        "planned_pause": False,
        "planned_pause_reason": "",
        "returned": False,
    }
    base.update(kw)
    return base


def test_empty_when_present(monkeypatch):
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {"presence_class": "present", "returned": False})
    assert az._presence_block() == ""
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    assert az._presence_block() == ""


def test_lull_block_names_the_gap_not_the_cause(monkeypatch):
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: _sig())
    blk = az._presence_block()
    assert "5 days" in blk and "2026-06-24" in blk
    assert "food, journal" in blk
    assert "wearables" in blk.lower()
    # The anti-flawless-week guard is the whole point.
    assert "zero missed targets" in blk.lower() or "perfect adherence" in blk.lower()
    # Never invents why.
    assert "invent" in blk.lower() and "invite the story" in blk.lower()


def test_planned_pause_framed_as_break(monkeypatch):
    monkeypatch.setattr(
        az, "_load_engagement_signal", lambda: _sig(presence_class="light", planned_pause=True, planned_pause_reason="travel")
    )
    blk = az._presence_block()
    assert "PLANNED pause" in blk and "travel" in blk


def test_return_block_supportive_with_delta(monkeypatch):
    monkeypatch.setattr(
        az,
        "_load_engagement_signal",
        lambda: _sig(presence_class="present", returned=True, resumed_after_days=5, weight_delta_over_gap=3.2),
    )
    blk = az._presence_block()
    assert "RETURNED" in blk and "5 days" in blk
    assert "+3.2 lb" in blk
    assert "supportive" in blk.lower() or "SUPPORTIVELY" in blk


def test_shared_prompt_includes_presence_when_quiet(monkeypatch):
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: _sig())
    sp = az._build_shared_system_prompt()
    assert "PRESENCE / QUIET STRETCH" in sp


def test_shared_prompt_omits_presence_when_present(monkeypatch):
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {"presence_class": "present"})
    sp = az._build_shared_system_prompt()
    assert "PRESENCE / QUIET STRETCH" not in sp
