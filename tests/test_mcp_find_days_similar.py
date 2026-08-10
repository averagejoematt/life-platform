"""tests/test_mcp_find_days_similar.py — find_days mode='similar' (#2351).

Nearest-neighbour day retrieval ("the days most like today") as deterministic
feature-vector arithmetic. Contracts pinned here, mapped to the issue's
acceptance criteria:

  * **Normalization is stated and stable** — per-feature z-score against the
    candidate window (population mean/std over the candidate days carrying the
    feature, target excluded); distance is the RMS z-difference. The expected
    scores in this file are hand-derived from that definition, so a silent
    change of method fails loudly.
  * **Absence is absence (ADR-104)** — a feature missing on the target day is
    dropped (with a reason), a candidate day missing a used feature is excluded
    from comparability and counted, never imputed to the mean.
  * **Honest n and an honest floor (ADR-105)** — every result reports
    n_candidate_days / n_comparable / per-feature n; nothing within the
    similarity floor means "no comparable days", not the least-bad five.
  * **"What happened next" is a described distribution** with its n — the next
    calendar day after each match, never a prediction.
  * **Deterministic** — same day + same history = same matches, same scores;
    ties break by date.

No AWS, no network: ``query_source`` is replaced with a fake returning fixture
rows (the same seam tests/test_mcp_tools_data_behavior.py uses).
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import tools_data as td  # noqa: E402


@pytest.fixture()
def fake_query_source(monkeypatch):
    def _install(items):
        calls: list[tuple] = []

        def _q(source, start_date, end_date, **kw):
            calls.append((source, start_date, end_date, kw))
            return [dict(i) for i in items]

        _q.calls = calls  # type: ignore[attr-defined]
        monkeypatch.setattr(td, "query_source", _q)
        return _q

    return _install


def _rows(values_by_date, extra_fields=None):
    rows = []
    for date, value in values_by_date:
        row = {"sk": f"DATE#{date}", "date": date, "hrv": value}
        if extra_fields:
            row.update(extra_fields.get(date, {}))
        rows.append(row)
    return rows


# 12 candidate days with hrv 40..62 step 2, plus the target day at hrv=51.
# Candidate mean = 51, population std = sqrt(47.6667) = 6.90411.
_HISTORY = [
    ("2026-07-01", 40),
    ("2026-07-02", 42),
    ("2026-07-03", 44),
    ("2026-07-04", 46),
    ("2026-07-05", 48),
    ("2026-07-06", 50),
    ("2026-07-07", 52),
    ("2026-07-08", 54),
    ("2026-07-09", 56),
    ("2026-07-10", 58),
    ("2026-07-11", 60),
    ("2026-07-12", 62),
]
_TARGET_ROW = ("2026-07-13", 51)

_SIMILAR_ARGS = {
    "mode": "similar",
    "source": "whoop",
    "start_date": "2026-07-01",
    "end_date": "2026-07-13",
    "target_date": "2026-07-13",
    "features": ["hrv"],
}


# ──────────────────────────────────────────────────────────────────────────────
# Mode dispatch
# ──────────────────────────────────────────────────────────────────────────────


def test_mode_defaults_to_filter_preserving_the_original_contract(fake_query_source):
    fake_query_source(_rows(_HISTORY))
    got = td.tool_find_days(
        {
            "source": "whoop",
            "start_date": "2026-07-01",
            "end_date": "2026-07-12",
            "filters": [{"field": "hrv", "op": ">=", "value": 60}],
        }
    )
    assert isinstance(got, list), "filter mode keeps returning the bare matched-day list"
    assert [m["date"] for m in got] == ["2026-07-11", "2026-07-12"]


def test_unknown_mode_is_rejected_with_the_valid_set(fake_query_source):
    fake_query_source([])
    with pytest.raises(ValueError, match=r"Unknown mode 'wibble'.*filter.*similar"):
        td.tool_find_days({**_SIMILAR_ARGS, "mode": "wibble"})


def test_similar_requires_target_date(fake_query_source):
    fake_query_source([])
    args = {k: v for k, v in _SIMILAR_ARGS.items() if k != "target_date"}
    with pytest.raises(ValueError, match="target_date"):
        td.tool_find_days(args)


def test_similar_requires_features_when_the_source_has_no_default(fake_query_source):
    fake_query_source([])
    args = {k: v for k, v in _SIMILAR_ARGS.items() if k != "features"}
    with pytest.raises(ValueError, match="'features' is required for source 'withings'"):
        td.tool_find_days({**args, "source": "withings"})


# ──────────────────────────────────────────────────────────────────────────────
# The arithmetic — hand-derived from the stated normalization
# ──────────────────────────────────────────────────────────────────────────────


def test_similar_ranks_by_rms_z_distance_with_date_ascending_tiebreak(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    got = td.tool_find_days(dict(_SIMILAR_ARGS))

    # Hand derivation: candidate mean 51, population std 6.90411. Target hrv 51
    # → target z = 0, so distance = |value − 51| / 6.90411. Nearest are 50 and
    # 52 (0.145 each — the tie breaks by date, 07-06 first), then 48/54 (0.435),
    # then 46 (0.724; 56 ties but 46's date sorts first).
    assert got["features_used"] == ["hrv"]
    assert got["n_candidate_days"] == 12
    assert got["n_comparable"] == 12
    assert [m["date"] for m in got["matches"]] == [
        "2026-07-06",
        "2026-07-07",
        "2026-07-05",
        "2026-07-08",
        "2026-07-04",
    ]
    assert [m["rms_z_distance"] for m in got["matches"]] == [0.145, 0.145, 0.435, 0.435, 0.724]
    assert got["matches"][0]["values"] == {"hrv": 50.0}
    assert got["target_values"] == {"hrv": 51.0}
    assert got["similarity_floor_rms_z"] == td.SIMILAR_MAX_RMS_Z
    assert "z-score" in got["method"] and "No AI" in got["method"]


def test_similar_is_deterministic_across_runs(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    first = td.tool_find_days(dict(_SIMILAR_ARGS))
    second = td.tool_find_days(dict(_SIMILAR_ARGS))
    assert first == second


def test_similar_k_is_clamped_to_at_least_one_and_honored(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    top_two = td.tool_find_days({**_SIMILAR_ARGS, "k": 2})
    assert [m["date"] for m in top_two["matches"]] == ["2026-07-06", "2026-07-07"]
    floor_one = td.tool_find_days({**_SIMILAR_ARGS, "k": 0})
    assert len(floor_one["matches"]) == 1


def test_what_happened_next_is_a_described_distribution_with_n(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    got = td.tool_find_days(dict(_SIMILAR_ARGS))

    # Next calendar days of the 5 matches: 07-07→52, 07-08→54, 07-06→50,
    # 07-09→56, 07-05→48. Sorted: [48, 50, 52, 54, 56].
    dist = got["what_happened_next"]["features"]["hrv"]
    assert dist == {"n": 5, "mean": 52.0, "median": 52.0, "min": 48.0, "max": 56.0}
    assert "not a prediction" in got["what_happened_next"]["note"]
    # Each match also carries its own next day so the sample is inspectable.
    assert got["matches"][0]["next_day"] == {"date": "2026-07-07", "values": {"hrv": 52.0}}


def test_similar_below_the_floor_answers_no_comparable_days(fake_query_source):
    # Target hrv 200 is ~21.6 SD from the candidate mean — nothing is "alike".
    fake_query_source(_rows(_HISTORY + [("2026-07-13", 200)]))
    got = td.tool_find_days(dict(_SIMILAR_ARGS))
    assert got["matches"] == []
    assert got["n_matches"] == 0
    assert got["n_comparable"] == 12, "the days exist; none is comparable"
    assert got["note"].startswith("No comparable days")
    assert "nearest candidate" in got["note"]


# ──────────────────────────────────────────────────────────────────────────────
# Absence semantics (ADR-104)
# ──────────────────────────────────────────────────────────────────────────────


def test_candidate_missing_a_used_feature_is_excluded_not_imputed(fake_query_source):
    # strain exists on 11 of 12 candidate days (missing on 07-03) and the target.
    strain = {date: {"strain": 8.0 + i * 0.5} for i, (date, _) in enumerate(_HISTORY) if date != "2026-07-03"}
    strain["2026-07-13"] = {"strain": 10.0}
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW], extra_fields=strain))
    got = td.tool_find_days({**_SIMILAR_ARGS, "features": ["hrv", "strain"]})

    assert got["features_used"] == ["hrv", "strain"]
    assert got["n_excluded_missing_features"] == 1
    assert got["n_comparable"] == 11
    assert "2026-07-03" not in [m["date"] for m in got["matches"]]


def test_feature_missing_on_the_target_day_is_dropped_with_a_reason(fake_query_source):
    strain = {date: {"strain": 8.0 + i * 0.5} for i, (date, _) in enumerate(_HISTORY)}
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW], extra_fields=strain))  # target has no strain
    got = td.tool_find_days({**_SIMILAR_ARGS, "features": ["hrv", "strain"]})
    assert got["features_used"] == ["hrv"]
    assert "missing on the target day" in got["features_dropped"]["strain"]


def test_zero_variance_feature_is_dropped(fake_query_source):
    flat = {date: {"strain": 5.0} for date, _ in _HISTORY + [_TARGET_ROW]}
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW], extra_fields=flat))
    got = td.tool_find_days({**_SIMILAR_ARGS, "features": ["hrv", "strain"]})
    assert got["features_used"] == ["hrv"]
    assert "zero variance" in got["features_dropped"]["strain"]


def test_feature_with_insufficient_history_is_dropped_with_its_n(fake_query_source):
    # strain on only 3 candidate days — below SIMILAR_MIN_FEATURE_N (10).
    sparse = {d: {"strain": v} for d, v in [("2026-07-01", 5.0), ("2026-07-02", 6.0), ("2026-07-03", 7.0), ("2026-07-13", 8.0)]}
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW], extra_fields=sparse))
    got = td.tool_find_days({**_SIMILAR_ARGS, "features": ["hrv", "strain"]})
    assert got["features_used"] == ["hrv"]
    assert got["features_dropped"]["strain"] == f"only 3 candidate day(s) carry it (floor: {td.SIMILAR_MIN_FEATURE_N})"


def test_no_usable_features_is_an_honest_empty_answer(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    got = td.tool_find_days({**_SIMILAR_ARGS, "features": ["nonexistent_metric"]})
    assert got["matches"] == []
    assert "No usable features" in got["note"]
    assert "nonexistent_metric" in got["features_dropped"]


def test_no_data_for_the_target_day_is_reported_not_computed_around(fake_query_source):
    fake_query_source(_rows(_HISTORY))  # window rows exist, target row does not
    got = td.tool_find_days(dict(_SIMILAR_ARGS))
    assert got["matches"] == []
    assert got["note"].startswith("No data for target_date 2026-07-13")


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────


def test_whoop_default_feature_vector_applies_and_reports_whats_absent(fake_query_source):
    fake_query_source(_rows(_HISTORY + [_TARGET_ROW]))
    args = {k: v for k, v in _SIMILAR_ARGS.items() if k != "features"}
    got = td.tool_find_days(args)
    assert got["features_used"] == ["hrv"], "only hrv exists in the fixture rows"
    dropped = set(got["features_dropped"])
    assert dropped == {"recovery_score", "resting_heart_rate", "strain", "sleep_duration_hours"}
