"""tests/test_flourishing.py — #1403: the PERMA fact layer over journal enrichment.

Guards: the aggregation projection (pure), the Decimal row writer + provenance
stamp, the Mind values_alignment mapping (ADR-104: journaled-zero is a real 20,
no row is None), the Relationships primary-input preference, the MCP trend tool
(EMA + provenance + anti-rumination framing), the taxonomy registration, and
the live config's rebalanced Mind weights. Red on the pre-#1403 tree.
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

import flourishing as fl  # noqa: E402


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


# ── values_alignment mapping (ADR-104) ────────────────────────────────────────


def test_values_alignment_mapping():
    assert fl.values_alignment_score(None, has_row=False) is None  # uninstrumented
    assert fl.values_alignment_score(0, has_row=True) == 20.0  # journaled zero = real low
    assert fl.values_alignment_score(1, has_row=True) == 60.0
    assert fl.values_alignment_score(2, has_row=True) == 80.0
    assert fl.values_alignment_score(3, has_row=True) == 100.0
    assert fl.values_alignment_score(7, has_row=True) == 100.0


# ── pillar wiring ─────────────────────────────────────────────────────────────


def test_relationships_prefers_flourishing_row_over_entry_fallback():
    import character_engine as ce

    cfg = {"pillars": {"relationships": {"components": {"social_interaction_frequency": {"weight": 1.0}}}}}
    data = {
        "flourishing": {"social_quality_score": 10.0, "enrichment_model": "claude-haiku-4-5"},
        # entry fallback says "alone" (0) — the row must win
        "journal_entries": [{"enriched_social_quality": "alone"}],
        "journal": {},
    }
    raw, details = ce.compute_relationships_raw(data, cfg)
    assert raw == 100.0
    assert "LLM-coded from journal text" in details["_flourishing_provenance"]


def test_relationships_fallback_still_works_without_row():
    import character_engine as ce

    cfg = {"pillars": {"relationships": {"components": {"social_interaction_frequency": {"weight": 1.0}}}}}
    data = {"journal_entries": [{"enriched_social_quality": "deep"}], "journal": {}}
    raw, details = ce.compute_relationships_raw(data, cfg)
    assert raw == 100.0
    assert "_flourishing_provenance" not in details


def test_mind_values_alignment_component_config_gated():
    import character_engine as ce

    cfg_with = {"pillars": {"mind": {"components": {"values_alignment": {"weight": 1.0}}}}}
    data = {"flourishing": {"values_lived_count": 2, "enrichment_model": "claude-haiku-4-5"}}
    raw, details = ce.compute_mind_raw(data, cfg_with)
    assert raw == 80.0
    assert "LLM-coded from journal text" in details["_flourishing_provenance"]

    # No flourishing row → component is None → zero coverage, no fabricated score.
    raw2, details2 = ce.compute_mind_raw({}, cfg_with)
    assert details2["_data_coverage"] == 0.0


# ── taxonomy + live config ────────────────────────────────────────────────────


def test_flourishing_registered_raw_timeseries():
    from phase_taxonomy import RAW_TIMESERIES, SOURCE_CLASS

    assert SOURCE_CLASS.get("flourishing") == RAW_TIMESERIES


def test_repo_config_carries_values_alignment_balanced():
    cfg = json.load(open(_REPO / "config" / "character_sheet.json"))
    comps = cfg["pillars"]["mind"]["components"]
    assert "values_alignment" in comps
    assert abs(sum(c["weight"] for c in comps.values()) - 1.0) < 1e-9


# ── the MCP trend tool ────────────────────────────────────────────────────────


def test_get_flourishing_trend_ema_provenance_and_framing(monkeypatch):
    from mcp import tools_journal as tj

    rows = [
        {
            "pk": "USER#matthew#SOURCE#flourishing",
            "sk": f"DATE#2026-07-{d:02d}",
            "date": f"2026-07-{d:02d}",
            "values_lived_count": Decimal(d % 3),
            "enrichment_model": "claude-haiku-4-5",
        }
        for d in range(1, 11)
    ]

    class _T:
        def query(self, **kw):
            return {"Items": rows}

    monkeypatch.setattr(tj, "table", _T())
    out = tj.tool_get_flourishing_trend({"days": 30})
    sig = out["signals"]["values_lived_count"]
    assert sig["n"] == 10 and sig["ema"] is not None
    assert sig["latest"]["date"] == "2026-07-10"
    assert "LLM-coded from journal text (model claude-haiku-4-5)" == out["provenance"]
    assert "tracking break" in out["_framing"]  # anti-rumination framing (review warning #1)
    assert out["signals"]["ownership_score"]["n"] == 0  # absent signal reported honestly
