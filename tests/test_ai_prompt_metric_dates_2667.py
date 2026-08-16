"""#2667 — every metric in the AI prompt carries its own as-of date.

The bug bash (2026-08-14) caught both AI endpoints narrating the latest stored
weight as "as of today" when the newest record was two days old — `_latest_item`
had no age concept and the prompt rendered every metric under a bare CURRENT
DATA header. Structural, not weight-specific: ANY stale source was narrated as
current (ADR-104).

Pinned here, ON THE ASSEMBLED PROMPT, never on model output (the grounding
lesson): the recency reader records the row date; the one annotation renderer
dates every line; a metric past its source's own registry `stale_hours` carries
the STALE form; and both prompt surfaces (ask's CURRENT DATA, the board facts
block) render through the same annotator so they cannot phrase honesty
differently.
"""

import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import (
    site_api_ai_context as ctxmod,  # noqa: E402
    site_api_ai_lambda as ai,  # noqa: E402
)
from web.site_api_common import PT  # noqa: E402


def _today() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(PT) - timedelta(days=n)).strftime("%Y-%m-%d")


# ── the ONE annotation renderer ───────────────────────────────────────────────


def test_same_day_reading_gets_no_annotation():
    assert ctxmod.age_annotation(_today(), "withings") == ""


def test_recent_but_not_today_names_its_date():
    d = _days_ago(2)
    ann = ctxmod.age_annotation(d, "withings")  # withings stale_hours=168 — 2d is fresh-enough
    assert ann == f" (as of {d})"


def test_past_registry_stale_hours_carries_the_stale_form():
    d = _days_ago(8)  # 192h > withings' 168h registry threshold
    ann = ctxmod.age_annotation(d, "withings")
    assert "STALE" in ann and d in ann and "NOT current" in ann


def test_threshold_comes_from_the_registry_not_a_hand_literal():
    """whoop (48h) and withings (168h) must diverge at 3 days — the threshold is
    the source's own facet, never one shared number."""
    d = _days_ago(3)
    assert "STALE" in ctxmod.age_annotation(d, "whoop")
    assert "STALE" not in ctxmod.age_annotation(d, "withings")


def test_unknown_date_is_marked_not_current_never_implied_fresh():
    ann = ctxmod.age_annotation(None, "withings")
    assert "not current" in ann


# ── the recency reader records WHEN ───────────────────────────────────────────


class _T:
    def __init__(self, items):
        self._items = items

    def query(self, **kw):
        return {"Items": self._items}


def test_latest_item_records_the_row_date_from_the_sk(monkeypatch):
    monkeypatch.setattr(ai, "table", _T([{"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{_days_ago(5)}", "weight_lbs": 300}]))
    item = ctxmod._latest_item("withings")
    assert item[ctxmod._AS_OF] == _days_ago(5)


def test_latest_item_dates_a_subkeyed_row_by_its_date_segment(monkeypatch):
    sk = f"DATE#{_days_ago(1)}#WORKOUT#abc123"
    monkeypatch.setattr(ai, "table", _T([{"pk": "USER#matthew#SOURCE#whoop", "sk": sk, "hrv": 40}]))
    assert ctxmod._latest_item("whoop")[ctxmod._AS_OF] == _days_ago(1)


# ── both prompt surfaces render the dates ─────────────────────────────────────

_STALE_D = None  # filled per test


def _ctx(weight_as_of, vitals_as_of):
    return {
        "weight_lbs": 300.5,
        "hrv_ms": 41.0,
        "rhr_bpm": 60.0,
        "recovery_pct": 55.0,
        "sleep_hours": 7.1,
        "start_weight": 322.0,
        "goal_weight": 185,
        "reads": {},
        "as_of": {"weight": weight_as_of, "vitals": vitals_as_of},
    }


def test_ask_prompt_dates_every_dated_metric_line():
    d_w, d_v = _days_ago(5), _days_ago(1)
    prompt = ai._ask_build_prompt(_ctx(d_w, d_v))
    weight_line = next(line for line in prompt.split("\n") if line.strip().startswith("Weight:"))
    assert f"(as of {d_w})" in weight_line
    for label in ("HRV:", "RHR:", "Whoop recovery score:", "Sleep:"):
        line = next(ln for ln in prompt.split("\n") if ln.strip().startswith(label))
        assert f"(as of {d_v})" in line, f"{label} line undated: {line!r}"
    # the model-side rule rides with the data
    assert "NEVER present a reading marked STALE as current" in prompt


def test_ask_prompt_marks_a_stale_vitals_read_stale():
    prompt = ai._ask_build_prompt(_ctx(_today(), _days_ago(4)))  # whoop 96h > 48h
    hrv_line = next(line for line in prompt.split("\n") if line.strip().startswith("HRV:"))
    assert "STALE" in hrv_line and "NOT current" in hrv_line


def test_board_facts_block_dates_through_the_same_renderer():
    d_w = _days_ago(8)  # withings stale
    block = ctxmod._board_facts_block(_ctx(d_w, _today()))
    assert f"as of {d_w}" in block and "STALE" in block
    assert "whoop recovery score: 55%" in block or "whoop recovery score: 55" in block
    # fresh vitals stay annotation-free — honesty is signal, not decoration
    assert block.count("STALE") == 1


def test_fresh_everything_renders_clean():
    block = ctxmod._board_facts_block(_ctx(_today(), _today()))
    assert "as of" not in block and "STALE" not in block
