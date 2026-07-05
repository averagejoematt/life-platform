"""tests/test_tdee_deficit_chain_484.py — #484 (B-1, epic #461).

The MacroFactor TDEE/deficit chain was dead end-to-end: ingest wrote the adaptive
maintenance estimate to `expenditure_kcal`, but every reader looked for
`tdee`/`tdee_kcal`/`expenditure` — field names nothing ever wrote — so `tdee` and
`deficit` served None on every response.

These pin the fix: (1) the canonical resolver reads all name generations newest-first
with honest provenance, and (2) the summary ingester now writes the canonical
`tdee_kcal` alongside `expenditure_kcal`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from web.site_api_observatory import _mifflin_tdee, _resolve_mf_tdee  # noqa: E402

# ── the resolver ──────────────────────────────────────────────────────────────


def test_resolves_canonical_expenditure_kcal():
    tdee, source = _resolve_mf_tdee([{"date": "2026-07-01", "expenditure_kcal": 2650}])
    assert tdee == 2650.0
    assert source == "macrofactor_adaptive"


def test_resolves_legacy_field_generations():
    for field in ("tdee_kcal", "tdee", "expenditure"):
        tdee, source = _resolve_mf_tdee([{field: 2400}])
        assert tdee == 2400.0, field
        assert source == "macrofactor_adaptive"


def test_scans_backward_to_most_recent_populated_record():
    # Latest record lacks expenditure (empty future day); resolver falls back to the
    # most recent record that actually carries it.
    items = [
        {"date": "2026-06-29", "expenditure_kcal": 2600},
        {"date": "2026-06-30", "total_calories_kcal": 1800},  # no expenditure
        {"date": "2026-07-01", "total_calories_kcal": 1750},  # no expenditure
    ]
    tdee, source = _resolve_mf_tdee(items)
    assert tdee == 2600.0
    assert source == "macrofactor_adaptive"


def test_prefers_newest_when_multiple_carry_expenditure():
    items = [
        {"date": "2026-06-30", "expenditure_kcal": 2600},
        {"date": "2026-07-01", "expenditure_kcal": 2500},
    ]
    tdee, _ = _resolve_mf_tdee(items)
    assert tdee == 2500.0


def test_missing_zero_and_empty_yield_none():
    assert _resolve_mf_tdee([]) == (None, None)
    assert _resolve_mf_tdee(None) == (None, None)
    assert _resolve_mf_tdee([{"expenditure_kcal": 0}]) == (None, None)
    assert _resolve_mf_tdee([{"total_calories_kcal": 1800}]) == (None, None)


# ── the ingest mapping ────────────────────────────────────────────────────────


def test_summary_ingest_writes_canonical_tdee_kcal():
    from macrofactor_lambda import build_summary_day_items

    rows = [
        {
            "Date": "2026-07-01",
            "Calories (kcal)": "1750",
            "Protein (g)": "185",
            "Fat (g)": "55",
            "Carbs (g)": "150",
            "Expenditure": "2650",
        }
    ]
    items = build_summary_day_items(rows)
    item = items["2026-07-01"]
    assert item["expenditure_kcal"] == 2650.0
    # #484: the canonical name is written so ai_context / correlation readers converge.
    assert item["tdee_kcal"] == 2650.0


def test_summary_ingest_omits_tdee_when_no_expenditure():
    from macrofactor_lambda import build_summary_day_items

    rows = [{"Date": "2026-07-01", "Calories (kcal)": "1750", "Protein (g)": "185", "Fat (g)": "55", "Carbs (g)": "150"}]
    item = build_summary_day_items(rows)["2026-07-01"]
    assert "expenditure_kcal" not in item
    assert "tdee_kcal" not in item


# ── the labeled Mifflin estimate fallback ─────────────────────────────────────


def test_mifflin_estimate_from_weight():
    # 300 lb → ~136 kg; Mifflin-St Jeor × 1.55 ≈ a plausible TDEE for that mass.
    est = _mifflin_tdee(300)
    assert est is not None
    assert 3000 < est < 4200  # sanity band, not a magic number


def test_mifflin_none_on_missing_weight():
    assert _mifflin_tdee(None) is None
    assert _mifflin_tdee(0) is None
    assert _mifflin_tdee("nope") is None
