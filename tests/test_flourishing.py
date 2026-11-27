"""tests/test_flourishing.py — #1403: the PERMA fact layer over journal enrichment.

Guards: the aggregation projection (pure), the Decimal row writer + provenance
stamp, that no flourishing signal feeds a character score (#6293), the MCP trend
tool (EMA + provenance + anti-rumination framing), the taxonomy registration, and
the live config's rebalanced Mind weights.
"""

import json
import os
import pathlib
import sys
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import flourishing as fl  # noqa: E402


def _entry(**kw):
    return {"enriched_at": "2026-07-01T00:00:00", **kw}


# ── aggregation (pure) ────────────────────────────────────────────────────────


def test_aggregate_none_without_enrichment():
    assert fl.aggregate_entries([]) is None
    assert fl.aggregate_entries([{"raw_text": "unenriched"}]) is None


def test_aggregate_dedupes_values_case_insensitively():
    row = fl.aggregate_entries(
        [
            _entry(enriched_values_lived=["Discipline", "health"]),
            _entry(enriched_values_lived=["discipline", "Family"]),
        ]
    )
    assert row["values_lived_count"] == 3
    assert sorted(v.lower() for v in row["values_lived"]) == ["discipline", "family", "health"]


def test_aggregate_signal_shapes():
    row = fl.aggregate_entries(
        [
            _entry(
                enriched_gratitude=["a", "b"],
                enriched_flow=False,
                enriched_growth_signals=["x"],
                enriched_ownership=4,
                enriched_social_quality="meaningful",
            ),
            _entry(enriched_gratitude=["c"], enriched_flow=True, enriched_ownership=2, enriched_social_quality="deep"),
        ]
    )
    assert row["gratitude_count"] == 3
    assert row["flow"] == 1  # any flow that day
    assert row["growth_signals_count"] == 1
    assert row["ownership_score"] == 3.0
    assert row["social_quality_score"] == round((2 / 3 * 10 + 10) / 2, 2)


def test_aggregate_absent_signals_stay_absent():
    row = fl.aggregate_entries([_entry(enriched_values_lived=["health"])])
    assert "ownership_score" not in row and "social_quality_score" not in row and "flow" not in row


# ── the row writer (Decimal + provenance) ─────────────────────────────────────


class _PutTable:
    def __init__(self):
        self.item = None

    def put_item(self, Item):
        self.item = Item


def test_write_row_stamps_provenance_and_decimals():
    t = _PutTable()
    ok = fl.write_flourishing_row(
        t, "matthew", "2026-07-01", [_entry(enriched_values_lived=["health"], enriched_ownership=3)], "claude-haiku-4-5", 2
    )
    assert ok is True
    assert t.item["pk"] == "USER#matthew#SOURCE#flourishing"
    assert t.item["sk"] == "DATE#2026-07-01"
    assert t.item["enrichment_model"] == "claude-haiku-4-5"
    assert isinstance(t.item["values_lived_count"], Decimal)
    assert isinstance(t.item["ownership_score"], Decimal)


def test_write_row_skips_uninstrumented_day():
    t = _PutTable()
    assert fl.write_flourishing_row(t, "matthew", "2026-07-01", [{"raw_text": "x"}], "m", 2) is False
    assert t.item is None


# ── #6293: no flourishing signal feeds a character score ─────────────────────


def test_flourishing_row_feeds_neither_mind_nor_relationships():
    """Owner ruling 2026-11-26: the row stays stored and readable as interpretation; a model's count of values or its
    social-quality reading moves no score, even under a config that still lists the retired components."""
    from health import character_engine as ce

    stale_cfg = {
        "pillars": {
            "mind": {"components": {"values_alignment": {"weight": 1.0}, "state_of_mind_valence": {"weight": 1.0}}},
            "relationships": {"components": {"social_interaction_frequency": {"weight": 1.0}}},
        }
    }
    row = {"values_lived_count": 3, "social_quality_score": 10.0, "enrichment_model": "synthetic-model"}
    base = {"state_of_mind": {"som_avg_valence": 0.0}}
    with_row = dict(base, flourishing=row, journal_entries=[{"enriched_social_quality": "deep"}], journal={"themes": ["friends"]})
    assert ce.compute_mind_raw(with_row, stale_cfg) == ce.compute_mind_raw(base, stale_cfg)
    raw, details = ce.compute_relationships_raw(with_row, stale_cfg)
    assert raw == 50.0 and details["_not_instrumented"] is True
    assert not hasattr(fl, "values_alignment_score")


# ── taxonomy + live config ────────────────────────────────────────────────────


def test_flourishing_registered_raw_timeseries():
    from experiment.phase_taxonomy import RAW_TIMESERIES, SOURCE_CLASS

    assert SOURCE_CLASS.get("flourishing") == RAW_TIMESERIES


def test_repo_config_mind_has_no_journal_components_and_is_balanced():
    cfg = json.load(open(_REPO / "config" / "character_sheet.json"))
    comps = cfg["pillars"]["mind"]["components"]
    assert "values_alignment" not in comps and "journal_consistency" not in comps  # #6293
    assert abs(sum(c["weight"] for c in comps.values()) - 1.0) < 1e-9


# ── the MCP trend tool ────────────────────────────────────────────────────────


def test_get_flourishing_trend_ema_provenance_and_framing(monkeypatch):
    from health.flourishing import ema_series

    from mcp import tools_journal as tj

    # Gapped fixture (#3452 F1/F2): four widely-spaced rows (100+ day gaps
    # between them), not ten consecutive days — closer to the real production
    # density (20 rows over a 222-day window) than a tidy daily run. This is
    # what proves the recurrence is OBSERVATION-indexed rather than
    # calendar-indexed: a naive day-decayed EMA would erase a reading from
    # months back, but health.flourishing.ema_series only ever advances on
    # rows that carry a value, so this gapped series produces exactly the
    # same EMA as four adjacent days would.
    gapped_dates = ["2025-11-01", "2026-02-09", "2026-05-20", "2026-07-10"]
    rows = [
        {
            "pk": "USER#matthew#SOURCE#flourishing",
            "sk": f"DATE#{dt}",
            "date": dt,
            "values_lived_count": Decimal(i % 3),
            "enrichment_model": "claude-haiku-4-5",
        }
        for i, dt in enumerate(gapped_dates)
    ]

    class _T:
        def query(self, **kw):
            return {"Items": rows}

    monkeypatch.setattr(tj, "table", _T())
    out = tj.tool_get_flourishing_trend({"days": 365})
    sig = out["signals"]["values_lived_count"]
    assert sig["n"] == 4 and sig["ema"] is not None
    assert sig["latest"]["date"] == "2026-07-10"
    # Position-indexed: matches the same recurrence run directly over the
    # ordered values with the calendar gaps discarded entirely.
    assert sig["ema"] == ema_series([i % 3 for i in range(4)], span=14)
    assert "LLM-coded from journal text (model claude-haiku-4-5)" == out["provenance"]
    assert "tracking break" in out["_framing"]  # anti-rumination framing (review warning #1)
    assert out["signals"]["ownership_score"]["n"] == 0  # absent signal reported honestly
    # #3452: the payload names the semantics a bare "ema_span" integer can't —
    # gaps between entries are carried, not decayed by elapsed time.
    assert "observation-indexed" in out["ema_span_semantics"]
