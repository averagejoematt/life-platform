"""
tests/test_perf_trend.py — perf-vitals persistence + weekly regression trend (#1435).

Covers the PURE surface of tests/perf_trend.py (no AWS, no network, runs in the
offline unit subset):
  - snapshot_from_results  extracts per-page vitals, skips non-perf rows
  - run_key / iso_week      date-first S3 key + ISO-week label
  - build_trend            weekly medians + advisory step-change regression flags
  - trend_markdown         renders the ops/green-report block (#1435 E3)

Run with:   python3 -m pytest tests/test_perf_trend.py -v
"""

import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import perf_trend  # noqa: E402

NOW = datetime(2026, 7, 20, 14, 30, 5, tzinfo=timezone.utc)  # a Monday (ISO 2026-W30)


# ── snapshot_from_results ───────────────────────────────────────────────────────


def _result(path, lcp, cls, js, page=None):
    return {"path": path, "page": page or path, "perf": {"lcp_ms": lcp, "cls": cls, "js_bytes": js}}


def test_snapshot_extracts_per_page_vitals():
    results = [_result("/", 800, 0.05, 120_000), _result("/cockpit/", 1100, 0.20, 300_000)]
    snap = perf_trend.snapshot_from_results(results, now=NOW)
    assert snap["date"] == "2026-07-20"
    assert len(snap["pages"]) == 2
    home = next(p for p in snap["pages"] if p["path"] == "/")
    assert home["lcp_ms"] == 800 and home["cls"] == 0.05 and home["js_bytes"] == 120_000


def test_snapshot_skips_rows_without_perf():
    # The leak-token synthetic result has no `perf` dict; a fully-empty perf row is dropped too.
    results = [
        _result("/", 800, 0.05, 120_000),
        {"path": "(leak sweep)", "page": "Leak-token sweep", "status": "PASS"},
        {"path": "/blank", "page": "blank", "perf": {"lcp_ms": None, "cls": None, "js_bytes": 0}},
    ]
    snap = perf_trend.snapshot_from_results(results, now=NOW)
    assert [p["path"] for p in snap["pages"]] == ["/"]


def test_snapshot_carries_git_sha_and_run_id_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc1234")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    snap = perf_trend.snapshot_from_results([_result("/", 800, 0.05, 120_000)], now=NOW)
    assert snap["git_sha"] == "abc1234" and snap["run_id"] == "999"


# ── keys / week labels ──────────────────────────────────────────────────────────


def test_run_key_is_date_first_under_perf_runs_prefix():
    snap = perf_trend.snapshot_from_results([_result("/", 800, 0.05, 120_000)], now=NOW)
    key = perf_trend.run_key(snap)
    assert key.startswith("generated/qa_archive/perf/runs/2026-07-20/143005--")
    assert key.endswith(".json")


def test_iso_week_label():
    assert perf_trend.iso_week("2026-07-20") == "2026-W30"
    assert perf_trend.iso_week("2026-07-13") == "2026-W29"


# ── build_trend: weekly medians ─────────────────────────────────────────────────


def _snap(date_str, path, lcp, cls, js):
    return {
        "date": date_str,
        "captured_at": date_str + "T12:00:00+00:00",
        "pages": [{"path": path, "lcp_ms": lcp, "cls": cls, "js_bytes": js}],
    }


def test_build_trend_medians_per_week():
    # Two runs same week → median; different week → separate point.
    snaps = [
        _snap("2026-07-13", "/", 800, 0.05, 100_000),
        _snap("2026-07-14", "/", 900, 0.05, 100_000),  # same ISO week (W29) as above → median 850
        _snap("2026-07-20", "/", 1000, 0.05, 100_000),  # W30
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    series = trend["pages"]["/"]["metrics"]["lcp_ms"]
    weeks = {p["week"]: p["median"] for p in series}
    assert weeks["2026-W29"] == 850
    assert weeks["2026-W30"] == 1000


# ── build_trend: regression detection ───────────────────────────────────────────


def test_lcp_step_change_flags_regression():
    # Baseline ~800ms for weeks, then 1200ms latest → +50% and +400ms → flag.
    snaps = [
        _snap("2026-07-06", "/", 800, 0.05, 100_000),
        _snap("2026-07-13", "/", 800, 0.05, 100_000),
        _snap("2026-07-20", "/", 1200, 0.05, 100_000),
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    reg = trend["pages"]["/"]["regressions"]["lcp_ms"]
    assert reg is not None
    assert reg["latest"] == 1200 and reg["baseline"] == 800
    assert any(r["path"] == "/" and r["metric"] == "lcp_ms" for r in trend["regressions"])


def test_stable_series_no_regression():
    snaps = [
        _snap("2026-07-06", "/", 800, 0.05, 100_000),
        _snap("2026-07-13", "/", 820, 0.05, 100_000),
        _snap("2026-07-20", "/", 810, 0.06, 105_000),
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    assert trend["pages"]["/"]["regressions"]["lcp_ms"] is None
    assert trend["regressions"] == []


def test_small_absolute_lcp_jitter_does_not_flag():
    # 40ms → 70ms is +75% relative but only +30ms — under the 100ms abs floor → no flag.
    snaps = [
        _snap("2026-07-06", "/", 40, 0.01, 50_000),
        _snap("2026-07-13", "/", 40, 0.01, 50_000),
        _snap("2026-07-20", "/", 70, 0.01, 50_000),
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    assert trend["pages"]["/"]["regressions"]["lcp_ms"] is None


def test_cls_absolute_step_flags():
    snaps = [
        _snap("2026-07-06", "/", 800, 0.05, 100_000),
        _snap("2026-07-13", "/", 800, 0.05, 100_000),
        _snap("2026-07-20", "/", 800, 0.20, 100_000),  # +0.15 CLS → flag
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    assert trend["pages"]["/"]["regressions"]["cls"] is not None


def test_window_days_excludes_old_snapshots():
    snaps = [
        _snap("2026-01-01", "/", 5000, 0.9, 900_000),  # far outside a 56-day window
        _snap("2026-07-13", "/", 800, 0.05, 100_000),
        _snap("2026-07-20", "/", 810, 0.05, 100_000),
    ]
    trend = perf_trend.build_trend(snaps, now=NOW, window_days=56)
    assert trend["run_count"] == 2
    weeks = [p["week"] for p in trend["pages"]["/"]["metrics"]["lcp_ms"]]
    assert "2026-W01" not in weeks


# ── trend_markdown ──────────────────────────────────────────────────────────────


def test_trend_markdown_reports_regressions():
    snaps = [
        _snap("2026-07-06", "/cockpit/", 800, 0.05, 100_000),
        _snap("2026-07-13", "/cockpit/", 800, 0.05, 100_000),
        _snap("2026-07-20", "/cockpit/", 1400, 0.05, 100_000),
    ]
    trend = perf_trend.build_trend(snaps, now=NOW)
    md = perf_trend.trend_markdown(trend)
    assert "Perf trend" in md
    assert "/cockpit/" in md
    assert "advisory regression" in md.lower()


def test_trend_markdown_clean_when_no_regressions():
    snaps = [_snap("2026-07-13", "/", 800, 0.05, 100_000), _snap("2026-07-20", "/", 810, 0.05, 100_000)]
    md = perf_trend.trend_markdown(perf_trend.build_trend(snaps, now=NOW))
    assert "No advisory regressions" in md
