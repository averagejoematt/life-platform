"""tests/test_restart_verify_truth.py — #1097: the AI reader-truth gate in restart verify.

Pins (no AWS, no network, no Bedrock):
  - gate(): the pure verdict logic — only a HIGH finding blocks (exit 1, like the
    render gate); med/low warn; an all-batches-errored run is an ADVISORY skip,
    never a pass or a fail (the same semantics as the #1140 CI + nightly hooks).
  - SURFACES: every page path is on the verified 40-URL v4 surface (no retired
    /now/ slug — the #1143 rename class).
  - restart_pipeline wiring: the truth gate runs AFTER restart_verify_semantic,
    which runs after restart_verify_rendered (the issue's acceptance ordering).
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


truth = _load("restart_verify_truth")
pipeline = _load("restart_pipeline")
rendered = _load("restart_verify_rendered")


def _finding(severity: str, page: str = "/cockpit/", category: str = "temporal_contradiction", note: str = "n"):
    return {"page": page, "category": category, "severity": severity, "note": note}


# ── gate(): pure verdict logic ─────────────────────────────────────────────────


def test_high_finding_fails_and_blocks():
    status, rc, lines = truth.gate([_finding("high")], [], 8, "Day 1")
    assert (status, rc) == (truth.FAIL, 1)
    assert any("HIGH" in ln for ln in lines)


def test_high_finding_gates_even_with_batch_errors():
    status, rc, _ = truth.gate([_finding("high")], ["batch [/]: throttled"], 8, "Day 1")
    assert (status, rc) == (truth.FAIL, 1)


def test_med_and_low_warn_but_do_not_block():
    status, rc, lines = truth.gate([_finding("med"), _finding("low")], [], 8, "Day 1")
    assert (status, rc) == (truth.WARN, 0)
    assert any("2 low/med" in ln for ln in lines)


def test_clean_run_passes():
    status, rc, lines = truth.gate([], [], 8, "2d pre-start")
    assert (status, rc) == (truth.PASS, 0)
    assert any("no truth findings" in ln for ln in lines)


def test_all_batches_errored_is_advisory_skip_not_pass():
    # A missing verdict is advisory — never a silent green AND never a false red.
    status, rc, lines = truth.gate([], ["batch [/]: AccessDenied", "batch [/api/vitals]: timeout"], 8, "Day 1")
    assert (status, rc) == (truth.SKIP, 0)
    assert any("NOT a pass" in ln for ln in lines)
    assert sum("fail-soft" in ln for ln in lines) == 2  # every error stays visible


def test_finding_details_survive_into_the_report_lines():
    status, _, lines = truth.gate([_finding("high", page="/coaching/", note="Day 2 narrating a 30-day trend")], [], 8, "Day 2")
    assert status == truth.FAIL
    assert any("/coaching/" in ln and "30-day trend" in ln for ln in lines)


# ── SURFACES: verified paths only ──────────────────────────────────────────────


def test_surfaces_use_no_retired_slugs():
    paths = [p for p, _ in truth.SURFACES]
    assert "/now/" not in paths  # renamed to /cockpit/ by #1143 — a 301 would waste the AI read
    assert "/cockpit/" in paths


def test_surface_pages_are_on_the_verified_v4_surface():
    # Page paths must come from restart_verify_rendered's 40-URL registry —
    # the same discipline that caught the pre-v4 page-map drift (2026-07-10).
    for path, name in truth.SURFACES:
        if not path.startswith("/api/"):
            assert path in rendered.PAGES, f"{name} ({path}) is not on the verified v4 page surface"


# ── restart_pipeline wiring: ordering + blocking ───────────────────────────────


def test_truth_gate_runs_after_semantic_after_rendered():
    src = inspect.getsource(pipeline.main)
    i_rendered = src.index("restart_verify_rendered")
    i_semantic = src.index("restart_verify_semantic")
    i_truth = src.index("restart_verify_truth")
    assert i_rendered < i_semantic < i_truth


def test_truth_gate_failure_merges_into_verify_rc():
    # The acceptance criterion: a truth FAIL blocks the pipeline like the render
    # gate — i.e. it feeds the same verify_rc that gates the post-verify hooks
    # and the final nonzero exit.
    src = inspect.getsource(pipeline.main)
    assert "verify_rc = verify_rc or truth_rc" in src


# ── #1188: future-genesis reset — outgoing genesis == today's real date ──────────


def _labels(tokens):
    return [t[0] for t in tokens]


def test_old_genesis_iso_literal_waived_when_outgoing_equals_today():
    """A future-genesis reset (outgoing genesis == today) drops the ISO-literal
    token — it collides with every legitimate freshness stamp — but keeps the prose
    forms that still catch a real chronicle leak."""
    from datetime import date

    today = date.today().isoformat()
    labels = _labels(rendered._old_genesis_tokens(today))
    assert not any("literal" in lbl for lbl in labels), labels
    assert any("prose" in lbl for lbl in labels), labels


def test_old_genesis_iso_literal_enforced_for_a_past_genesis():
    """A normal (past-genesis) reset still forbids the outgoing ISO literal."""
    labels = _labels(rendered._old_genesis_tokens("2026-06-14"))
    assert any("literal" in lbl for lbl in labels), labels


def test_old_genesis_tokens_empty_when_missing_or_equals_current():
    assert rendered._old_genesis_tokens("") == []
    assert rendered._old_genesis_tokens(rendered.EXPERIMENT_START_DATE) == []
