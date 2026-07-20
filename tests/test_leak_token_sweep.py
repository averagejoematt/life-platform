#!/usr/bin/env python3
"""
test_leak_token_sweep.py — offline tests for the shared leak-token sweep
core (tests/leak_token_sweep.py, #1448) and its two callers.

No Playwright import anywhere in this file (memory:
reference_test_layer_dep_import_collection_red) — importing tests/visual_qa.py
is safe because it imports `playwright.sync_api` lazily inside run_sweep(),
not at module scope. No network calls: sweep()/run_leak_token_sweep() are
exercised with fetch monkeypatched.

Coverage:
  - FORBIDDEN_TOKENS / check_body: representative hits + allowed-prefix skips.
  - tokens_for_daily_run / days_since_genesis / RESET_WINDOW_LABELS: the #1448
    guard against the daily sweep redding on a mature cycle's real content
    (Day 45, Character Level 12, ...) once the reset-window checks no longer
    apply.
  - sweep(): HTTP-error reporting + the allowed-503 waiver.
  - visual_qa.run_leak_token_sweep(): formats sweep() hits into issue strings
    and reports ok=True on a clean run.
  - deploy/restart_verify_rendered.py still exposes PAGES / JSON_ENDPOINTS /
    FORBIDDEN_TOKENS / _old_genesis_tokens / EXPERIMENT_START_DATE unchanged
    (the reset-time path's public surface, pinned by test_restart_verify_truth.py
    too — this file adds the FORBIDDEN_TOKENS/JSON_ENDPOINTS identity check).
  - deploy/sync_doc_metadata.py's AST discoverer still finds JSON_ENDPOINTS
    after the move (it now falls back to tests/leak_token_sweep.py).
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import leak_token_sweep as lts  # noqa: E402


def _load(rel_path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── FORBIDDEN_TOKENS / check_body ───────────────────────────────────────────


def test_tombstone_leak_flags_public_json():
    hits = lts.check_body("/api/journey", '{"tombstone": true, "x": 1}')
    assert any(label == "Tombstone leak" for label, _ in hits)


def test_sentinel_value_flags_anywhere():
    hits = lts.check_body("/data/vitals/", "<p>reading: 999.0</p>")
    assert any(label == "999.0 sentinel" for label, _ in hits)


def test_cycle1_genesis_literal_allowed_on_cycle_compare():
    body = '{"geneses": ["2026-04-01", "2026-06-14"]}'
    assert not any(label == "Cycle-1 genesis literal" for label, _ in lts.check_body("/api/cycle_compare", body))
    assert any(label == "Cycle-1 genesis literal" for label, _ in lts.check_body("/cockpit/", body))


def test_day_30_plus_counter_flags_stale_day_count():
    hits = lts.check_body("/cockpit/", "<p>Day 45 of the experiment</p>")
    assert any(label == "Day-30+ counter" for label, _ in hits)


def test_day_under_30_does_not_flag():
    hits = lts.check_body("/cockpit/", "<p>Day 12 of the experiment</p>")
    assert not any(label == "Day-30+ counter" for label, _ in hits)


def test_check_body_custom_tokens_subset_only_checks_given_tokens():
    body = "<p>Day 45</p>"
    restricted = [t for t in lts.FORBIDDEN_TOKENS if t[0] != "Day-30+ counter"]
    assert not lts.check_body("/cockpit/", body, tokens=restricted)
    assert lts.check_body("/cockpit/", body, tokens=lts.FORBIDDEN_TOKENS)


# ── #1448: the daily-sweep reset-window guard ───────────────────────────────


def test_reset_window_labels_are_a_subset_of_forbidden_tokens():
    labels = {t[0] for t in lts.FORBIDDEN_TOKENS}
    assert lts.RESET_WINDOW_LABELS <= labels


def test_tokens_for_daily_run_full_list_when_cycle_is_young():
    # genesis "today" in the module's own frame → days_since_genesis == 0
    assert lts.tokens_for_daily_run(today=lts.EXPERIMENT_START_DATE) == lts.FORBIDDEN_TOKENS


def test_tokens_for_daily_run_drops_reset_window_once_mature():
    from datetime import date, timedelta

    mature = (date.fromisoformat(lts.EXPERIMENT_START_DATE) + timedelta(days=lts.RESET_WINDOW_DAYS + 5)).isoformat()
    tokens = lts.tokens_for_daily_run(today=mature)
    labels = {t[0] for t in tokens}
    assert labels.isdisjoint(lts.RESET_WINDOW_LABELS)
    # the timeless entries must still be present
    assert "Tombstone leak" in labels
    assert "999.0 sentinel" in labels


def test_tokens_for_daily_run_keeps_full_list_pre_start():
    from datetime import date, timedelta

    pre_start = (date.fromisoformat(lts.EXPERIMENT_START_DATE) - timedelta(days=10)).isoformat()
    assert lts.tokens_for_daily_run(today=pre_start) == lts.FORBIDDEN_TOKENS


def test_days_since_genesis_negative_pre_start():
    from datetime import date, timedelta

    pre_start = (date.fromisoformat(lts.EXPERIMENT_START_DATE) - timedelta(days=3)).isoformat()
    assert lts.days_since_genesis(today=pre_start) == -3


# ── sweep() ──────────────────────────────────────────────────────────────────


def test_sweep_reports_http_error(monkeypatch):
    monkeypatch.setattr(lts, "fetch", lambda url, timeout=15: (500, ""))
    results = lts.sweep("https://x.example", ["/broken/"])
    assert results[0]["hits"] == [("HTTP error", ["500"])]


def test_sweep_allows_expected_503():
    def fake_fetch(url, timeout=15):
        return 503, "character not yet computed today"

    import unittest.mock as mock

    with mock.patch.object(lts, "fetch", side_effect=fake_fetch):
        results = lts.sweep("https://x.example", [], ["/api/character"], allow_503_paths={"/api/character"})
    assert results[0]["hits"] == []
    assert results[0]["http_status"] == 503


def test_sweep_flags_a_clean_and_a_dirty_page():
    import unittest.mock as mock

    bodies = {"/clean/": (200, "<p>all good</p>"), "/dirty/": (200, '{"tombstone": true}')}

    def fake_fetch(url, timeout=15):
        for path, resp in bodies.items():
            if url.endswith(path):
                return resp
        raise AssertionError(url)

    with mock.patch.object(lts, "fetch", side_effect=fake_fetch):
        results = lts.sweep("https://x.example", ["/clean/", "/dirty/"])
    by_path = {r["path"]: r for r in results}
    assert by_path["/clean/"]["hits"] == []
    assert any(label == "Tombstone leak" for label, _ in by_path["/dirty/"]["hits"])


# ── restart_verify_rendered.py's public surface is unchanged ───────────────


def test_restart_verify_rendered_reexports_the_shared_module_unchanged():
    rendered = _load("deploy/restart_verify_rendered.py", "_rvr_reexport_check")
    assert rendered.FORBIDDEN_TOKENS == lts.FORBIDDEN_TOKENS
    assert rendered.JSON_ENDPOINTS == lts.JSON_ENDPOINTS
    assert rendered._old_genesis_tokens is lts.old_genesis_tokens


# ── doc-sync discovery still finds JSON_ENDPOINTS after the move ───────────


def test_sync_doc_metadata_discovers_json_endpoints_via_leak_token_sweep():
    sync = _load("deploy/sync_doc_metadata.py", "_sync_doc_metadata_leak_check")
    counts = sync._auto_discover_restart_url_counts()
    assert counts is not None
    pages, endpoints = counts
    assert endpoints == len(lts.JSON_ENDPOINTS)
    assert pages >= 10


# ── visual_qa.run_leak_token_sweep() (#1448) ────────────────────────────────
# Playwright import in visual_qa.py is lazy (inside run_sweep), so importing
# the module here is safe and layer-import-free.

import visual_qa  # noqa: E402


def test_run_leak_token_sweep_ok_when_clean(monkeypatch):
    monkeypatch.setattr(
        visual_qa.leak_token_sweep,
        "sweep",
        lambda base_url, pages, json_endpoints, tokens=None, allow_503_paths=(): [
            {"path": "/", "url": base_url + "/", "http_status": 200, "hits": []}
        ],
    )
    result = visual_qa.run_leak_token_sweep(base_url="https://x.example")
    assert result == {"ok": True, "checked": 1, "issues": []}


def test_run_leak_token_sweep_flags_and_formats_issues(monkeypatch):
    monkeypatch.setattr(
        visual_qa.leak_token_sweep,
        "sweep",
        lambda base_url, pages, json_endpoints, tokens=None, allow_503_paths=(): [
            {
                "path": "/api/journey",
                "url": base_url + "/api/journey",
                "http_status": 200,
                "hits": [("Tombstone leak", ['"tombstone": true'])],
            }
        ],
    )
    result = visual_qa.run_leak_token_sweep(base_url="https://x.example")
    assert result["ok"] is False
    assert result["checked"] == 1
    assert result["issues"] == ['/api/journey — [Tombstone leak] "tombstone": true']


def test_run_sweep_has_leak_scan_flag_defaulting_true():
    import inspect

    sig = inspect.signature(visual_qa.run_sweep)
    assert sig.parameters["leak_scan"].default is True


def test_cli_exposes_no_leak_scan_escape_hatch():
    import subprocess

    out = subprocess.run(
        [sys.executable, os.path.join(_REPO, "tests", "visual_qa.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "--no-leak-scan" in out.stdout
