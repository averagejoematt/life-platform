"""tests/test_garmin_read_sweep_4976.py — the Garmin retirement sweep, READ side (#4976, #4978).

Garmin's direct feed is retired (#4640). Its stored rows stay and stay readable (capture-all,
docs/CONVENTIONS.md); what changes is that no prompt, tool or page treats it as a current
source of truth. One fixture test per site the sweep touched that is not already pinned in its
own suite (readiness: tests/test_mcp_tools_health_behavior.py; device agreement:
tests/test_device_agreement.py; Zone 2 milestone: tests/test_process_milestones_1628.py; the
training recommendation: tests/test_mcp_tools_training_behavior.py).

Mutation controls run for this lane (each assertion below moved when its site was reverted):
  * the prompt-text tests — restore the "Garmin is the step count source of truth" line;
  * the board test — put "garmin" back in any member's data_sources;
  * the VO2 tests — read `vo2_max` off the garmin rows directly (the pre-#4976 arc):
    the Apple point vanishes and `source` reads "Garmin".
"""

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import metric_truth  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402
from web import site_api_vitals_depth as vd  # noqa: E402


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


# ── prompts: no stale "Garmin is the steps truth" instruction ───────────────────────────────

STALE_PROMPT_SITES = ("lambdas/intelligence/intelligence_common.py", "lambdas/ai/ai_calls.py")


def test_no_prompt_names_garmin_as_the_steps_truth():
    for rel in STALE_PROMPT_SITES:
        src = _read(rel)
        assert "Garmin is the step count source of truth" not in src, rel
        assert "Garmin — SOT" not in src, rel
        # the replacement sends the model to the resolver's answer, not a device choice
        assert "steps resolver" in src, rel


# ── config/board_of_directors.json: data_sources are current ────────────────────────────────


def test_no_board_member_lists_garmin_as_a_data_source():
    board = json.loads(_read("config/board_of_directors.json"))
    offenders = [mid for mid, m in board["members"].items() if "garmin" in (m.get("data_sources") or [])]
    assert not offenders, f"members still list garmin: {offenders}"


# ── VO2 max arc: through the metric-truth resolver ──────────────────────────────────────────


def _q(rows_by_source):
    asked = []

    def fn(source, start, end, include_pilot=False):
        asked.append(source)
        return list(rows_by_source.get(source, []))

    fn.asked = asked
    return fn


def test_vo2_facet_is_apple_first_and_keeps_garmin_history_readable():
    facet = reg.metric_truth("vo2_max")
    assert facet["truth_source"] == "apple_health"
    assert facet["fallback_order"] == ("apple_health", "garmin")  # history stays readable
    assert facet["field_by_source"] == {"apple_health": "vo2max", "garmin": "vo2_max"}


def test_vo2_arc_reads_through_the_resolver_apple_wins_and_garmin_history_stays(monkeypatch):
    garmin = [
        {"sk": "DATE#2026-04-02", "date": "2026-04-02", "vo2_max": 30.8},
        {"sk": "DATE#2026-05-19", "date": "2026-05-19", "vo2_max": 33.3},
        {"sk": "DATE#2026-10-15", "date": "2026-10-15", "vo2_max": 99.0},  # a same-day garmin value loses to Apple
    ]
    apple = [{"sk": "DATE#2026-10-15", "date": "2026-10-15", "vo2max": 34.6}]
    fake = _q({"garmin": garmin, "apple_health": apple})
    monkeypatch.setattr(vd, "_query_source", fake)
    vo = vd._vo2max_arc()
    assert set(fake.asked) == set(metric_truth.sources_for("vo2_max"))
    assert [(p["date"], p["value"], p["source"]) for p in vo["series"]] == [
        ("2026-04-02", 30.8, "garmin"),
        ("2026-05-19", 33.3, "garmin"),
        ("2026-10-15", 34.6, "apple_health"),
    ]
    assert vo["current"] == 34.6 and vo["source"] == reg.source_label("apple_health")
    assert vo["sources"] == [reg.source_label("garmin"), reg.source_label("apple_health")]
    assert vo["mixed_devices"] is True


def test_vo2_arc_on_garmin_history_alone_is_one_device(monkeypatch):
    monkeypatch.setattr(vd, "_query_source", _q({"garmin": [{"sk": "DATE#2026-05-19", "date": "2026-05-19", "vo2_max": 33.3}]}))
    vo = vd._vo2max_arc()
    assert vo["source"] == reg.source_label("garmin") and vo["mixed_devices"] is False


# ── capture-all: the read side never writes ─────────────────────────────────────────────────

READ_ONLY_SITES = (
    "lambdas/web/site_api_vitals_depth.py",
    "lambdas/web/site_api_freshness.py",
    "mcp/tools_health.py",
    "lambdas/common/metric_truth.py",
)


def test_the_swept_read_sites_never_write_a_row():
    """Historic garmin rows are untouched: none of the re-pointed read sites carries a write call."""
    writes = ("put_item(", "update_item(", "delete_item(", "batch_write_item(", "batch_writer(")
    offenders = [(rel, w) for rel in READ_ONLY_SITES for w in writes if w in _read(rel)]
    assert not offenders, offenders
