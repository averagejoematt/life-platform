"""tests/test_labs_fact_block_1993.py — #1993: labs fact extraction reads the REAL schema.

The old extractor in ai_expert_analyzer_lambda hunted top-level `*_flag` keys with
'H'/'L' values — a schema that has never existed (SCHEMA.md: a draw record stores a
nested `biomarkers` map + an `out_of_range` key list with `out_of_range_count` /
`total_biomarkers`). Against every real draw it returned flagged_count=0 and the
labs coach narrated the empty extraction as "zero results — a total sync failure"
while /api/labs served 8 draws / 26 flagged (ADR-104 breach).

These tests pin:
  L1  a real-schema draw record extracts its flagged biomarkers (fails against the
      old *_flag hunt, which finds nothing in this fixture)
  L2  an empty store is STRUCTURALLY distinct (store_empty=True) — the only case
      where "zero results" is an honest narration
  L3  draws present + everything in range = flagged_count 0 WITHOUT store_empty
      (an unremarkable panel, not a data failure)
  L4  declared out_of_range_count vs resolvable detail disagreement surfaces as
      extraction_incomplete — an extraction gap, never an empty store
  L5  qualitative values and missing units/refs don't crash the formatter
  W1  the analyzer's labs branch is wired to the schema-true builder and the
      *_flag hunt is gone from the module
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from intelligence.labs_facts import build_labs_fact_block  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _real_draw_record():
    """A draw record shaped exactly per SCHEMA.md's labs section (nested
    biomarkers map + out_of_range list — zero top-level *_flag keys)."""
    return {
        "pk": "USER#matthew#SOURCE#labs",
        "sk": "DATE#2026-04-03",
        "draw_date": "2026-04-03",
        "lab_provider": "function_health",
        "biomarkers": {
            "apob": {
                "value": 112.0,
                "value_numeric": 112.0,
                "unit": "mg/dL",
                "ref_text": "<90",
                "ref_low": None,
                "ref_high": 90.0,
                "flag": "high",
                "category": "lipids_advanced",
                "fh_category": "Out of Range",
            },
            "vitamin_d_25oh": {
                "value": 24.0,
                "value_numeric": 24.0,
                "unit": "ng/mL",
                "ref_text": "30-100",
                "ref_low": 30.0,
                "ref_high": 100.0,
                "flag": "low",
                "category": "vitamins",
                "fh_category": "Out of Range",
            },
            "hs_crp": {
                "value": 0.8,
                "value_numeric": 0.8,
                "unit": "mg/L",
                "ref_text": "<1.0",
                "flag": "normal",
                "category": "inflammation",
                "fh_category": "In Range",
            },
        },
        "out_of_range": ["apob", "vitamin_d_25oh"],
        "out_of_range_count": 2,
        "total_biomarkers": 3,
    }


# ── L1: the real schema extracts ─────────────────────────────────────────────


def test_real_schema_draw_extracts_flagged_markers():
    block = build_labs_fact_block([_real_draw_record()])
    assert block["store_empty"] is False
    assert block["total_draws"] == 1
    assert block["draw_date"] == "2026-04-03"
    assert block["total_biomarkers"] == 3
    # The regression the issue names: the *_flag hunt returned 0 here.
    assert block["flagged_count"] == 2
    assert len(block["flagged_markers"]) == 2
    joined = " | ".join(block["flagged_markers"])
    assert "Apob" in joined and "112.0" in joined and "HIGH" in joined
    assert "Vitamin D 25Oh" in joined and "LOW" in joined
    assert "extraction_incomplete" not in block


def test_latest_draw_wins_and_total_counts_all():
    older = _real_draw_record()
    older["sk"], older["draw_date"] = "DATE#2025-10-01", "2025-10-01"
    block = build_labs_fact_block([older, _real_draw_record()])
    assert block["total_draws"] == 2
    assert block["draw_date"] == "2026-04-03"


# ── L2: empty store is structural ────────────────────────────────────────────


def test_empty_store_is_structurally_distinct():
    for empty in ([], None):
        block = build_labs_fact_block(empty)
        assert block["store_empty"] is True
        assert block["total_draws"] == 0
        assert "note" in block


# ── L3: all-in-range draws are not a failure ─────────────────────────────────


def test_all_in_range_draw_is_zero_flagged_but_not_empty():
    rec = _real_draw_record()
    rec["out_of_range"] = []
    rec["out_of_range_count"] = 0
    block = build_labs_fact_block([rec])
    assert block["store_empty"] is False
    assert block["flagged_count"] == 0
    assert block["flagged_markers"] == []
    assert "extraction_incomplete" not in block


# ── L4: declaration vs detail disagreement = extraction gap ──────────────────


def test_declared_count_shortfall_surfaces_as_extraction_gap():
    rec = _real_draw_record()
    del rec["biomarkers"]["apob"]  # detail lookup can no longer resolve one key
    block = build_labs_fact_block([rec])
    assert block["store_empty"] is False
    assert block["flagged_count"] == 2  # the record's own declaration stands
    assert len(block["flagged_markers"]) == 1
    assert "extraction gap" in block["extraction_incomplete"]
    assert "never narrate" in block["extraction_incomplete"]


def test_missing_declared_count_falls_back_to_resolved():
    rec = _real_draw_record()
    del rec["out_of_range_count"]
    block = build_labs_fact_block([rec])
    assert block["flagged_count"] == 2
    assert "extraction_incomplete" not in block


# ── L5: formatter robustness ─────────────────────────────────────────────────


def test_qualitative_values_and_missing_fields_do_not_crash():
    rec = _real_draw_record()
    rec["biomarkers"]["lead_blood"] = {"value": "<10", "flag": "high"}  # no unit/ref
    rec["out_of_range"].append("lead_blood")
    rec["out_of_range_count"] = 3
    block = build_labs_fact_block([rec])
    assert block["flagged_count"] == 3
    assert any("Lead Blood: <10 (HIGH)" == m for m in block["flagged_markers"])


# ── W1: the analyzer is wired to the builder, the *_flag hunt is gone ────────


def test_analyzer_delegates_and_flag_hunt_is_gone():
    src = open(os.path.join(ROOT, "lambdas/intelligence/ai_expert_analyzer_lambda.py")).read()
    assert "build_labs_fact_block" in src
    assert 'endswith("_flag")' not in src and "endswith('_flag')" not in src
