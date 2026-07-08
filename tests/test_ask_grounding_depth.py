"""#387 — /api/ask grounds on the drivers the platform already computes.

The ask box used to fetch only a handful of latest numbers, so it answered
honestly but uselessly ("I can't tell you what drove it — share a few days of
data..."). These tests pin the fix: the prompt carries the precomputed reads
(mode factors, momentum, month deltas, FDR correlations, presence), instructs
narrate-don't-recalculate, forbids asking the reader for Matthew's data, and
derives the source count instead of hardcoding "19 data sources".

All offline — pure prompt-builder calls + source-level assertions.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402

_AI_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas/web/site_api_ai_lambda.py")
AI_SRC = open(_AI_PATH).read()


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


_READS = {
    "adaptive_mode": {
        "label": "Steady",
        "score": 72.0,
        "factors": {"journal": "no entries in 14d", "t0_habits": "3 of 4 complete yesterday"},
    },
    "momentum": "holding after a strong fortnight",
    "improving": ["hrv", "sleep_duration"],
    "declining": ["steps"],
    "strongest_habits": ["walk", "protein"],
    "weakest_habits": ["journal"],
    "weekly_rate_lbs": -1.4,
    "protein": {"avg_7d_g": 152.0, "target_g": 170.0, "floor_g": 140.0},
    "month_deltas": [
        {
            "label": "Recovery",
            "this_month_avg": 62.1,
            "prior_month_avg": 58.4,
            "delta": 3.7,
            "unit": "%",
            "direction": "improved",
        }
    ],
    "correlations": [{"a": "sleep_duration", "b": "recovery_score", "r": 0.61, "n_days": 45}],
    "presence": {"class": "quiet", "gap_days": 5, "passive_still_flowing": True},
}


def test_reads_block_renders_every_read():
    block = _ai()._ask_reads_block(_READS)
    assert "Steady" in block and "72/100" in block
    assert "journal: no entries in 14d" in block
    assert "Momentum read: holding after a strong fortnight" in block
    assert "Improving (7d): hrv, sleep_duration" in block
    assert "Declining (7d): steps" in block
    assert "Weight trend: -1.4 lbs/week" in block
    assert "152g 7-day avg intake (target 170g, floor 140g)" in block
    assert "Recovery 62.1 vs 58.4 prior" in block
    assert "r=+0.61, n=45 days" in block
    assert "quiet stretch (quiet) — 5 days since the last manual log; passive devices still flowing" in block


def test_reads_block_empty_when_no_reads():
    assert _ai()._ask_reads_block({}) == ""


_READS_HEADER = "COMPUTED READS (precomputed by the platform's analysis pipeline):"


def test_prompt_includes_computed_reads_section():
    prompt = _ai()._ask_build_prompt({"reads": _READS})
    assert _READS_HEADER in prompt
    assert "r=+0.61" in prompt


def test_prompt_omits_section_when_reads_missing():
    prompt = _ai()._ask_build_prompt({})
    assert _READS_HEADER not in prompt
    # The honesty rules still stand without reads.
    assert "NO ARITHMETIC" in prompt


def test_prompt_rules_forbid_arithmetic_and_asking_reader():
    prompt = _ai()._ask_build_prompt({"reads": _READS})
    assert "NO ARITHMETIC" in prompt
    assert "NEVER ask the reader to supply or track Matthew's data" in prompt
    assert "correlative framing" in prompt.lower() or "correlative" in prompt


def test_source_count_is_derived_not_hardcoded():
    ai = _ai()
    import source_registry as reg

    assert "19 data sources" not in AI_SRC  # the drifted literal is gone
    assert "~19 sources" not in AI_SRC
    assert ai._LIVE_SOURCE_COUNT == len(reg.public_board_sources())
    prompt = ai._ask_build_prompt({})
    assert f"{ai._LIVE_SOURCE_COUNT} live data sources" in prompt


def test_coach_system_uses_derived_count():
    ai = _ai()
    sys_block = ai._coach_system("sleep_coach")
    assert f"{ai._LIVE_SOURCE_COUNT} live sources" in sys_block
    assert "~19" not in sys_block


def test_fetch_computed_reads_fail_soft(monkeypatch):
    """Every block failing must yield an empty reads dict, never an exception —
    a broken compute can't take the ask box down."""
    ai = _ai()

    def _boom(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(ai, "_latest_item", _boom)

    def _boom_hook(*a, **k):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(ai, "table", FakeDdbTable(query_hook=_boom_hook, get_item_hook=_boom_hook))
    assert ai._ask_fetch_computed_reads() == {}
