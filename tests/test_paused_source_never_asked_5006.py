"""#5006 — a paused source (ADR-074 state) is never a coach check-in context and never
escalates freshness. Fixture registry: one dark manual source, paused vs un-paused."""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_checkin as cc  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402

_COACHES = ["sleep", "nutrition", "training", "mind", "physical", "glucose", "labs", "explorer"]


def _fixture(monkeypatch, paused):
    dark = {
        "label": "Dark thing",
        "capture_channel": "mcp",
        "stale_hours": 14 * 24,
    }
    if paused:
        dark["paused"] = True
    monkeypatch.setattr(reg, "SOURCE_REGISTRY", {"dark_src": dark, "live_src": {"label": "Live", "capture_channel": "mcp"}})


def _signal():
    """What mcp/tools_coach_checkin._manual_source_signal builds from manual_capture_sources()."""
    return [
        {
            "source": k,
            "label": m["label"],
            "days_since": 204 if k == "dark_src" else 1,
            "stale_days": max(1, round(m["stale_hours"] / 24)),
            "coach": "nutrition",
        }
        for k, m in reg.manual_capture_sources().items()
    ]


def test_paused_dark_source_is_never_selected(monkeypatch):
    _fixture(monkeypatch, paused=True)
    assert "dark_src" not in reg.manual_capture_sources()
    _, reason = cc.pick_asking_coach(_COACHES, _signal(), [])
    assert "Dark thing" not in reason and "rotation" in reason


def test_unpaused_dark_source_is_selected_again(monkeypatch):
    """Mutation control: un-pause and the guard lets it through."""
    _fixture(monkeypatch, paused=False)
    _, reason = cc.pick_asking_coach(_COACHES, _signal(), [])
    assert "Dark thing" in reason and "longest-dark" in reason


def test_include_paused_still_lists_it(monkeypatch):
    _fixture(monkeypatch, paused=True)
    assert "dark_src" in reg.manual_capture_sources(include_paused=True)


def test_freshness_state_ignores_paused_dark_source(monkeypatch):
    """The freshness reader (tools_labs.get_freshness_status) buckets on this state: `paused`
    is never counted stale (#2715). Same facet, so a paused manual source cannot go red."""
    from ingestion.source_state import resolve_source_state

    _fixture(monkeypatch, paused=True)
    assert resolve_source_state("dark_src", "2026-03-28", "2026-10-18") == "paused"
    _fixture(monkeypatch, paused=False)
    assert resolve_source_state("dark_src", "2026-03-28", "2026-10-18") == "stale"
