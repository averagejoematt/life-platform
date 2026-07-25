"""tests/test_theme_river_1381.py — the deterministic spine of the Theme River (#1381).

AC1: enriched-theme aggregation is a PURE function with NO AI at render time, and
its output is BYTE-STABLE for a fixed input fixture. The golden below is the whole
contract — if the aggregation drifts, this red is the first thing to see.

Also proves: theme normalization (case/whitespace/intra-entry dedup), window
exclusion, the honest-empty (n=0) and warming-up (n<floor) states never fabricate
a rising theme (AC4), and the single "earned glow" rising theme is picked
deterministically only once the river is flowing.
"""

import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import theme_river as tr  # noqa: E402


# A fixed 3-week window with case/whitespace variants, an intra-entry duplicate,
# an SK-only entry, an out-of-window entry, and a themeless day — all of which the
# aggregation must fold deterministically.
FIXTURE = [
    {"date": "2026-07-20", "enriched_themes": ["Work Pressure", "personal growth", "sleep"]},
    {"date": "2026-07-21", "enriched_themes": ["work pressure", "financial stress"]},
    {"date": "2026-07-23", "enriched_themes": ["personal growth", "work  pressure"]},
    {"date": "2026-07-27", "enriched_themes": ["personal growth", "family connection"]},
    {"date": "2026-07-28", "enriched_themes": ["work pressure", "personal growth", "family connection"]},
    {"date": "2026-08-03", "enriched_themes": ["personal growth", "personal growth", "creative expression"]},
    {"sk": "DATE#2026-08-05#journal#journal#1", "enriched_themes": ["family connection", "work pressure"]},
    {"date": "2026-06-01", "enriched_themes": ["out of window"]},
    {"date": "2026-07-22", "enriched_themes": []},
]

# The byte-stable golden (json.dumps(..., sort_keys=True)). Regenerate ONLY with a
# reviewed intent: `python3 -c "import sys;sys.path.insert(0,'lambdas');import
# theme_river,json;..."` — a silent change here is a silent change to a published
# public artifact.
GOLDEN = {
    "bands": [
        {"rising": False, "theme": "personal growth", "total": 5},
        {"rising": False, "theme": "work pressure", "total": 5},
        {"rising": False, "theme": "family connection", "total": 3},
        {"rising": False, "theme": "creative expression", "total": 1},
        {"rising": False, "theme": "financial stress", "total": 1},
        {"rising": False, "theme": "sleep", "total": 1},
    ],
    "n_days": 7,
    "n_entries": 7,
    "n_themes": 6,
    "provenance": {
        "field": "enriched_themes",
        "model": "claude-haiku-4-5-20251001",
        "schema_version": 2,
        "source": "journal_enrichment",
    },
    "rising_theme": None,
    "schema": "theme_river/1",
    "state": "warming_up",
    "warming_up_min_days": 14,
    "weeks": [
        {
            "counts": {"financial stress": 1, "personal growth": 2, "sleep": 1, "work pressure": 3},
            "end": "2026-07-26",
            "n_days": 3,
            "n_entries": 3,
            "start": "2026-07-20",
            "week": 0,
        },
        {
            "counts": {"family connection": 2, "personal growth": 2, "work pressure": 1},
            "end": "2026-08-02",
            "n_days": 2,
            "n_entries": 2,
            "start": "2026-07-27",
            "week": 1,
        },
        {
            "counts": {"creative expression": 1, "family connection": 1, "personal growth": 1, "work pressure": 1},
            "end": "2026-08-09",
            "n_days": 2,
            "n_entries": 2,
            "start": "2026-08-03",
            "week": 2,
        },
    ],
    "window": {"end": "2026-08-09", "start": "2026-07-20", "weeks": 3},
}


def _build(entries, start="2026-07-20", end="2026-08-09"):
    return tr.build_river(entries, start, end, model="claude-haiku-4-5-20251001", schema_version=2)


def test_byte_stable_golden():
    """AC1 spine: the aggregation is a fixed-point of its input — exact bytes."""
    got = _build(FIXTURE)
    assert json.dumps(got, sort_keys=True) == json.dumps(GOLDEN, sort_keys=True)


def test_deterministic_across_runs_and_input_order():
    """Re-running (and shuffling input order) yields identical bytes — no set-order leak."""
    a = json.dumps(_build(FIXTURE), sort_keys=True)
    b = json.dumps(_build(list(reversed(FIXTURE))), sort_keys=True)
    assert a == b


def test_normalization_collapses_case_and_whitespace():
    """'Work Pressure' / 'work  pressure' are one theme; intra-entry dups count once."""
    got = _build(FIXTURE)
    wp = next(band for band in got["bands"] if band["theme"] == "work pressure")
    assert wp["total"] == 5  # would be 6+ if the collapse/dedup failed
    assert got["n_themes"] == 6  # 'out of window' excluded, variants merged


def test_empty_is_honest_not_fabricated():
    """AC4: zero enriched days → empty state, no bands, no rising theme."""
    got = _build([])
    assert got["state"] == "empty"
    assert got["n_days"] == 0
    assert got["bands"] == []
    assert got["rising_theme"] is None


def test_warming_up_never_names_a_rising_theme():
    """AC4: below the floor the river is 'warming_up' and claims no shape."""
    got = _build(FIXTURE)
    assert got["state"] == "warming_up"
    assert got["rising_theme"] is None
    assert all(band["rising"] is False for band in got["bands"])


def test_flowing_picks_the_rising_theme_deterministically():
    """Past the floor, the single earned-glow theme is the largest last-week surge."""
    start = date(2026, 7, 20)
    entries = []
    for i in range(21):
        d = (start + timedelta(days=i)).isoformat()
        themes = ["work pressure", "personal growth"]
        if i >= 14:  # a clear final-week surge
            themes = themes + ["discipline", "discipline"]
        entries.append({"date": d, "enriched_themes": themes})
    got = _build(entries)
    assert got["state"] == "flowing"
    assert got["n_days"] == 21
    assert got["rising_theme"] == "discipline"
    disc = next(band for band in got["bands"] if band["theme"] == "discipline")
    assert disc["rising"] is True and disc["total"] == 7


def test_bands_fold_beyond_max_into_other():
    """More distinct themes than MAX_BANDS → the tail folds into a single 'other' band."""
    entries = []
    # 10 distinct themes, decreasing frequency so the ranking is unambiguous.
    for rank in range(10):
        name = f"theme{rank:02d}"
        for _ in range(10 - rank):
            entries.append({"date": "2026-07-20", "enriched_themes": [name]})
    # spread across days so counts accrue without intra-entry dedup collapsing them
    for idx, e in enumerate(entries):
        e["date"] = (date(2026, 7, 20) + timedelta(days=idx % 6)).isoformat()
    got = _build(entries)
    band_names = [band["theme"] for band in got["bands"]]
    assert len(band_names) == tr.MAX_BANDS + 1  # top-N + 'other'
    assert band_names[-1] == tr.OTHER_LABEL
    assert got["n_themes"] == 10
