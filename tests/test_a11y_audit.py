#!/usr/bin/env python3
"""
test_a11y_audit.py — offline tests for the axe-core a11y gate (#1433).

Pure-logic coverage of tests/a11y_audit.py (gate classification, baseline
round-trip, the vendored-bundle/version pins). NO Playwright import anywhere
in this file — the browser-driving path is exercised by the sweep itself
(tests/visual_qa.py), and a layer-only import here would red the whole unit
suite at collection (memory: reference_test_layer_dep_import_collection_red).
"""

import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import a11y_audit  # noqa: E402


def _v(rule_id, impact, nodes=1):
    return {
        "id": rule_id,
        "impact": impact,
        "help": f"help for {rule_id}",
        "helpUrl": f"https://dequeuniversity.com/rules/axe/{rule_id}",
        "nodes": nodes,
        "targets": ["#x"],
    }


EMPTY = {"_meta": {}, "pages": {}}


# ── gate classification ───────────────────────────────────────────────────────


def test_new_critical_violation_gates_against_empty_baseline():
    """THE guard-red case: an injected critical violation on an unbaselined page
    must land in `new` (which visual_qa turns into a gating page FAIL)."""
    out = a11y_audit.gate_findings("/cockpit/", [_v("image-alt", "critical", nodes=2)], EMPTY)
    assert [v["id"] for v in out["new"]] == ["image-alt"]
    assert out["baselined"] == [] and out["advisory"] == [] and out["fixed"] == []


def test_new_serious_violation_gates_too():
    out = a11y_audit.gate_findings("/", [_v("color-contrast", "serious")], EMPTY)
    assert [v["id"] for v in out["new"]] == ["color-contrast"]


def test_minor_and_moderate_are_advisory_not_gating():
    out = a11y_audit.gate_findings("/", [_v("region", "moderate"), _v("meta-viewport-large", "minor")], EMPTY)
    assert out["new"] == []
    assert sorted(v["id"] for v in out["advisory"]) == ["meta-viewport-large", "region"]


def test_unknown_impact_never_gates():
    out = a11y_audit.gate_findings("/", [_v("weird-rule", None)], EMPTY)
    assert out["new"] == [] and [v["id"] for v in out["advisory"]] == ["weird-rule"]


def test_baselined_serious_is_recorded_not_gating():
    base = {"pages": {"/": [{"id": "color-contrast", "impact": "serious", "help": "x", "nodes": 3}]}}
    out = a11y_audit.gate_findings("/", [_v("color-contrast", "serious", nodes=5)], base)
    assert out["new"] == []
    assert [v["id"] for v in out["baselined"]] == ["color-contrast"]  # honest: recorded, never hidden


def test_baseline_is_per_page_not_global():
    """A rule baselined on one page must still gate on another page."""
    base = {"pages": {"/": [{"id": "image-alt", "impact": "critical", "help": "x", "nodes": 1}]}}
    out = a11y_audit.gate_findings("/cockpit/", [_v("image-alt", "critical")], base)
    assert [v["id"] for v in out["new"]] == ["image-alt"]


def test_node_count_change_on_baselined_rule_does_not_gate():
    """Gate key is (page, rule id) — node counts move with daily data and are
    deliberately not part of the key (the #1428 anti-flake lesson)."""
    base = {"pages": {"/": [{"id": "color-contrast", "impact": "serious", "help": "x", "nodes": 1}]}}
    out = a11y_audit.gate_findings("/", [_v("color-contrast", "serious", nodes=40)], base)
    assert out["new"] == []


def test_fixed_rules_are_surfaced_for_baseline_shrink():
    base = {"pages": {"/": [{"id": "image-alt", "impact": "critical", "help": "x", "nodes": 1}]}}
    out = a11y_audit.gate_findings("/", [], base)
    assert out["fixed"] == ["image-alt"]


# ── baseline round-trip (--update-baseline semantics) ─────────────────────────


def test_update_baseline_roundtrip_and_shrink(tmp_path):
    p = str(tmp_path / "a11y_baseline.json")
    a11y_audit.update_baseline({"/": [_v("image-alt", "critical")], "/cockpit/": [_v("color-contrast", "serious")]}, path=p)
    base = a11y_audit.load_baseline(p)
    assert set(base["pages"]) == {"/", "/cockpit/"}
    assert base["_meta"]["axe_version"] == a11y_audit.AXE_VERSION
    # a violation observed after capture is baselined (not gating)
    assert a11y_audit.gate_findings("/", [_v("image-alt", "critical")], base)["new"] == []
    # fixing a page then re-capturing SHRINKS the ledger (page entry removed)
    a11y_audit.update_baseline({"/": []}, path=p)
    base2 = a11y_audit.load_baseline(p)
    assert "/" not in base2["pages"]
    assert set(base2["pages"]) == {"/cockpit/"}  # un-swept page preserved


def test_update_baseline_preserves_pages_not_swept(tmp_path):
    """A --page/--max-tier run must never wipe the rest of the ledger."""
    p = str(tmp_path / "b.json")
    a11y_audit.update_baseline({"/a/": [_v("r1", "serious")], "/b/": [_v("r2", "critical")]}, path=p)
    a11y_audit.update_baseline({"/a/": [_v("r3", "serious")]}, path=p)
    base = a11y_audit.load_baseline(p)
    assert [r["id"] for r in base["pages"]["/b/"]] == ["r2"]
    assert [r["id"] for r in base["pages"]["/a/"]] == ["r3"]


def test_update_baseline_writes_sorted_reviewable_entries(tmp_path):
    p = str(tmp_path / "c.json")
    a11y_audit.update_baseline({"/z/": [_v("b-rule", "serious"), _v("a-rule", "critical")], "/a/": [_v("x", "serious")]}, path=p)
    with open(p) as f:
        raw = json.load(f)
    assert list(raw["pages"]) == ["/a/", "/z/"]
    assert [r["id"] for r in raw["pages"]["/z/"]] == ["a-rule", "b-rule"]
    # trimmed to the stable gate-relevant fields only (no volatile CSS targets)
    assert set(raw["pages"]["/z/"][0]) == {"id", "impact", "help", "nodes"}


def test_missing_baseline_file_is_empty_baseline(tmp_path):
    base = a11y_audit.load_baseline(str(tmp_path / "nope.json"))
    assert base["pages"] == {}


def test_summarize_counts_by_impact():
    base = {
        "pages": {
            "/": [{"id": "a", "impact": "serious"}, {"id": "b", "impact": "moderate"}],
            "/x/": [{"id": "a", "impact": "serious"}],
        }
    }
    assert a11y_audit.summarize(base) == {"serious": 2, "moderate": 1}


# ── the committed artifacts: vendored bundle + day-one baseline ───────────────


def test_vendored_axe_bundle_pinned_and_licensed():
    with open(a11y_audit.AXE_JS_PATH, encoding="utf-8") as f:
        head = f.read(4096)
    assert f"axe v{a11y_audit.AXE_VERSION}" in head, "AXE_VERSION must match the vendored bundle header — bump both together"
    assert "Mozilla Public" in head and "MPL" in head, "the MPL-2.0 license header must be preserved in the vendored file"
    assert "sha256" in head, "the vendoring header must pin the bundle checksum"


def test_committed_baseline_exists_and_matches_pinned_axe_version():
    base = a11y_audit.load_baseline()
    assert base["_meta"].get("axe_version") == a11y_audit.AXE_VERSION, (
        "tests/a11y_baseline.json was captured under a different axe version — re-capture via "
        "`python3 tests/visual_qa.py --update-baseline` in the same PR as the bump (#1433)"
    )
    # every committed entry is well-formed (the gate reads only these fields)
    for page, rows in base["pages"].items():
        assert page.startswith("/")
        for r in rows:
            assert set(r) == {"id", "impact", "help", "nodes"}, f"malformed baseline row on {page}: {r}"


def test_visual_qa_wiring_defaults_off_for_direct_capture_callers():
    """capture_page's a11y is opt-in (None default) so site_review/pr_render_gate
    are unchanged; run_sweep's is on by default (the sweep is the gate, #1433)."""
    import visual_qa

    cp = inspect.signature(visual_qa.capture_page).parameters
    assert cp["a11y_baseline"].default is None
    rs = inspect.signature(visual_qa.run_sweep).parameters
    assert rs["a11y"].default is True
    assert rs["update_a11y_baseline"].default is False
