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


# ── theme dimension (#1991) ────────────────────────────────────────────────────


def test_theme_light_reads_pages_light_not_pages():
    """theme='light' must consult 'pages_light', never the dark 'pages' ledger —
    a rule baselined only under dark still gates under light on the same page."""
    base = {
        "pages": {"/cockpit/": [{"id": "color-contrast", "impact": "serious", "help": "x", "nodes": 2}]},
        "pages_light": {},
    }
    out = a11y_audit.gate_findings("/cockpit/", [_v("color-contrast", "serious")], base, theme="light")
    assert [v["id"] for v in out["new"]] == ["color-contrast"]  # NOT baselined under pages_light


def test_theme_light_baselined_entry_does_not_gate():
    base = {
        "pages": {},
        "pages_light": {"/cockpit/": [{"id": "color-contrast", "impact": "serious", "help": "x", "nodes": 2}]},
    }
    out = a11y_audit.gate_findings("/cockpit/", [_v("color-contrast", "serious")], base, theme="light")
    assert out["new"] == []
    assert [v["id"] for v in out["baselined"]] == ["color-contrast"]


def test_theme_defaults_to_dark_backward_compatible():
    """The default (no theme kwarg) must be byte-identical to theme='dark' —
    every pre-#1991 call site never passes theme."""
    base = {"pages": {"/": [{"id": "image-alt", "impact": "critical", "help": "x", "nodes": 1}]}, "pages_light": {}}
    violations = [_v("image-alt", "critical")]
    assert a11y_audit.gate_findings("/", violations, base) == a11y_audit.gate_findings("/", violations, base, theme="dark")


def test_load_baseline_setdefaults_pages_light_for_legacy_files(tmp_path):
    """A pre-#1991 baseline file with no 'pages_light' key loads as an empty
    light ledger rather than KeyError-ing."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"_meta": {}, "pages": {"/": [{"id": "x", "impact": "serious", "help": "h", "nodes": 1}]}}))
    base = a11y_audit.load_baseline(str(p))
    assert base["pages_light"] == {}
    assert base["pages"]  # unchanged


def test_missing_baseline_file_has_empty_pages_light_too(tmp_path):
    base = a11y_audit.load_baseline(str(tmp_path / "nope.json"))
    assert base["pages"] == {} and base["pages_light"] == {}


def test_update_baseline_light_theme_writes_pages_light_and_preserves_pages(tmp_path):
    """update_baseline(theme='light') touches ONLY 'pages_light' — the dark
    'pages' ledger (and its capture record) is untouched, so #1991's baseline
    change is purely additive for every already-committed dark entry."""
    p = str(tmp_path / "b.json")
    a11y_audit.update_baseline({"/cockpit/": [_v("color-contrast", "serious")]}, path=p, theme="dark")
    dark_meta_before = a11y_audit.load_baseline(p)["_meta"]["captured_at"]

    a11y_audit.update_baseline({"/cockpit/": [_v("color-contrast", "serious", nodes=2)]}, path=p, theme="light")
    base = a11y_audit.load_baseline(p)

    # #3548: serious/critical rows also carry `issue` (UNTRIAGED — no prior to carry forward).
    assert set(base["pages"]["/cockpit/"][0]) == {"id", "impact", "help", "nodes", "issue"}
    assert base["pages"]["/cockpit/"][0]["issue"] == a11y_audit.UNTRIAGED
    assert base["pages"]["/cockpit/"][0]["nodes"] == 1  # dark entry untouched by the light write
    assert base["pages_light"]["/cockpit/"][0]["nodes"] == 2
    assert base["_meta"]["captured_at"] == dark_meta_before  # dark capture record preserved
    assert "captured_at_light" in base["_meta"] and "note_light" in base["_meta"]


def test_summarize_theme_light_counts_pages_light_only():
    base = {
        "pages": {"/": [{"id": "a", "impact": "serious"}]},
        "pages_light": {"/": [{"id": "a", "impact": "serious"}, {"id": "b", "impact": "moderate"}]},
    }
    assert a11y_audit.summarize(base, theme="light") == {"serious": 1, "moderate": 1}
    assert a11y_audit.summarize(base) == {"serious": 1}  # default (dark) unaffected


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
    # trimmed to the stable gate-relevant fields only (no volatile CSS targets);
    # #3548: serious/critical rows also carry `issue` (UNTRIAGED — no prior to carry forward).
    assert set(raw["pages"]["/z/"][0]) == {"id", "impact", "help", "nodes", "issue"}
    assert raw["pages"]["/z/"][0]["issue"] == a11y_audit.UNTRIAGED


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


# ── #1990 regression guard: the ledger re-arm actually restores gating ────────
#
# tests/a11y_baseline.json's dark "pages" ledger was re-captured against the
# live site with the real tests/visual_qa.py capture_page/run_sweep harness
# (#1990) — most baselined entries were stale (a color-contrast fix landed,
# the entry never shrank) so real gating was silently off on those pages.
# These tests prove the re-arm didn't just produce an empty diff: a page whose
# stale entry got removed must gate again on a genuinely new violation.


def test_gear_regression_guard_gates_after_rearm():
    """/gear/ is the issue's own headline staleness example (86 baselined
    nodes -> 0 live). Its dark entry is gone after the #1990 re-arm; a planted
    serious violation on it must now gate — proving restored coverage, not
    just a shrunk ledger."""
    base = a11y_audit.load_baseline()
    assert "/gear/" not in base["pages"], "expected /gear/'s stale ledger entry removed by the #1990 re-arm"
    out = a11y_audit.gate_findings("/gear/", [_v("color-contrast", "serious")], base)
    assert [v["id"] for v in out["new"]] == ["color-contrast"]


def test_method_game_regression_guard_gates_after_rearm():
    """#1990's own acceptance criteria flagged /method/game/ as NOT stale (a
    verifier claimed ~60 live serious nodes) and required either fixing it
    first or explicitly keeping its entry. Direct re-measurement against the
    live site with the real capture_page harness (which force-reveals
    motion-hidden sections before running axe — the harness step a simpler
    ad hoc check missed) found it genuinely clean, twice, repeatably. Honored
    per "measure first": its entry is removed, same as any other confirmed-
    clean page, and it must gate on a planted serious violation like any
    other re-armed page."""
    base = a11y_audit.load_baseline()
    assert "/method/game/" not in base["pages"], "expected /method/game/ clean per #1990's direct live re-measurement"
    out = a11y_audit.gate_findings("/method/game/", [_v("color-contrast", "serious")], base)
    assert [v["id"] for v in out["new"]] == ["color-contrast"]


def test_genuinely_live_pages_still_baselined_not_wiped_indiscriminately():
    """Sanity check on the #1990 re-arm: a page that direct measurement showed
    STILL carries live color-contrast debt (not "Day-1 emptiness" — re-verified
    mid-cycle-11 per the issue's own acceptance criteria) must still be
    baselined, so a shrink cannot pass by wiping the ledger wholesale.

    #3544 moved /data/{character,badges,vitals}/ off this list and onto
    ``test_recede_swept_pages_gate_after_the_3544_shrink`` below — NOT because the
    rule got weaker, but because the recede-grammar sweep (#3580, then this) actually
    fixed them and a direct re-measurement read zero color-contrast nodes on each,
    twice, at both viewports. /data/training/ is untouched by that sweep, still
    measures debt, and stays here as the "did you just wipe it?" anchor."""
    base = a11y_audit.load_baseline()
    for page_path in ("/data/training/",):
        ids = {r["id"] for r in base["pages"].get(page_path, [])}
        assert "color-contrast" in ids, f"{page_path} measured live during #1990's re-arm — its entry must survive"
        out = a11y_audit.gate_findings(page_path, [_v("color-contrast", "serious")], base)
        assert out["new"] == [], f"{page_path}'s still-live color-contrast rule must stay baselined (not re-gate)"


def test_recede_swept_pages_gate_after_the_3544_shrink():
    """#3544's third acceptance box, held as a test rather than as a claim.

    The three pages the recede-grammar sweep cleaned carried color-contrast as accepted
    debt in the dark desktop AND mobile ledgers — 61/40/10 and 60/39/11 nodes — which
    meant the gate could not fire on them at all. Direct re-measurement with the real
    tests/visual_qa.py harness (live pages, this branch's CSS served in place) read zero
    color-contrast nodes on each, so their rows are gone and a REAPPEARANCE is now a NEW
    serious violation that reds the sweep. If someone re-baselines the debt without
    fixing it, this reds."""
    base = a11y_audit.load_baseline()
    for page_path in ("/data/character/", "/data/badges/", "/data/vitals/"):
        for ledger, viewport in (("pages", "desktop"), ("pages_mobile", "mobile")):
            ids = {r["id"] for r in base[ledger].get(page_path, [])}
            assert "color-contrast" not in ids, f"{page_path} ({viewport}) was re-measured clean by #3544 — its row must not come back"
            out = a11y_audit.gate_findings(page_path, [_v("color-contrast", "serious")], base, viewport=viewport)
            assert [v["id"] for v in out["new"]] == ["color-contrast"], f"{page_path} ({viewport}) must gate on a planted violation"


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
    # every committed entry is well-formed (the gate reads only these fields) —
    # both the dark 'pages' ledger and the #1991 'pages_light' sibling.
    for key in a11y_audit.LEDGER_KEYS:  # #3277: all four ledgers, incl. the mobile pair
        for page, rows in base.get(key, {}).items():
            assert page.startswith("/")
            for r in rows:
                # #3548: serious/critical rows carry an additional `issue` field
                # (the ownership rule below); moderate/minor rows do not.
                required = {"id", "impact", "help", "nodes"}
                allowed = required | {"issue"}
                assert required <= set(r) <= allowed, f"malformed baseline row on {key}/{page}: {r}"
                if r.get("impact") in a11y_audit.GATING_IMPACTS:
                    assert "issue" in r, f"serious/critical row missing `issue` on {key}/{page}: {r}"


def test_visual_qa_wiring_defaults_off_for_direct_capture_callers():
    """capture_page's a11y is opt-in (None default) so site_review/pr_render_gate
    are unchanged; run_sweep's is on by default (the sweep is the gate, #1433)."""
    import visual_qa

    cp = inspect.signature(visual_qa.capture_page).parameters
    assert cp["a11y_baseline"].default is None
    rs = inspect.signature(visual_qa.run_sweep).parameters
    assert rs["a11y"].default is True


def test_visual_qa_color_scheme_defaults_to_dark_everywhere():
    """#1991: capture_page's theme and run_sweep's color_scheme both default to
    'dark' — every existing caller (which never passes either) is unchanged."""
    import visual_qa

    cp = inspect.signature(visual_qa.capture_page).parameters
    assert cp["theme"].default == "dark"
    rs = inspect.signature(visual_qa.run_sweep).parameters
    assert rs["color_scheme"].default == "dark"
    assert rs["update_a11y_baseline"].default is False


# ── #3277: the viewport axis — the mobile ledgers ────────────────────────────
# The gate used to run axe once, at the desktop context; a violation that exists
# only at 390px (scrollable-region-focusable on the block-scroll tables) was
# measured by no gate and absent from the ledger — indistinguishable from clean.

# The 15 pages the 2026-08-31 live re-measurement (chromium, 390x844, post-reveal,
# tests/a11y_audit.run_axe over all 92 sweep paths) found carrying
# scrollable-region-focusable — 33 nodes. WebKit on the same surface: 14 pages / 32
# nodes (identical except /data/vitals/, whose one node chromium sees and webkit does
# not) — the class is viewport-driven, not engine-driven.
MOBILE_SRF_PAGES_LIVE_2026_08_31 = (
    "/data/vitals/",
    "/story/attempts/",
    "/method/",
    "/method/game/",
    "/method/grade-your-coach/",
    "/data/labs/",
    "/data/habits/",
    "/method/cycles/",
    "/method/predictions/",
    "/method/calibration/",
    "/method/voicefidelity/",
    "/method/pipeline/",
    "/method/wrong/",
    "/method/verify/",
    "/method/inference/",
)


def test_viewport_keys_are_the_four_ledgers():
    assert a11y_audit._baseline_key("dark") == "pages"
    assert a11y_audit._baseline_key("light") == "pages_light"
    assert a11y_audit._baseline_key("dark", "mobile") == "pages_mobile"
    assert a11y_audit._baseline_key("light", "mobile") == "pages_light_mobile"
    assert a11y_audit._baseline_key("dark", "desktop") == "pages"  # explicit desktop == the default
    assert set(a11y_audit.LEDGER_KEYS) == {"pages", "pages_light", "pages_mobile", "pages_light_mobile"}


def test_mobile_viewport_reuses_the_existing_390_context_not_a_new_one():
    """Reuse, don't invent: the mobile axe pass runs at the SAME 390x844 every
    other mobile check in visual_qa (overflow, reveals, app-bar, tap targets) and
    the weekly WebKit context already use."""
    assert a11y_audit.MOBILE_VIEWPORT == {"width": 390, "height": 844}


def test_viewport_mobile_reads_pages_mobile_not_pages():
    """A rule baselined on desktop does NOT excuse it at 390px — the ledgers are
    independent, exactly like the theme axis (#1991)."""
    base = {"_meta": {}, "pages": {"/method/verify/": [_v("scrollable-region-focusable", "serious")]}, "pages_mobile": {}}
    out = a11y_audit.gate_findings("/method/verify/", [_v("scrollable-region-focusable", "serious")], base, viewport="mobile")
    assert [v["id"] for v in out["new"]] == ["scrollable-region-focusable"]
    # …and the desktop call site (no viewport) still reads "pages": baselined, not gating.
    out_desk = a11y_audit.gate_findings("/method/verify/", [_v("scrollable-region-focusable", "serious")], base)
    assert out_desk["new"] == [] and [v["id"] for v in out_desk["baselined"]] == ["scrollable-region-focusable"]


def test_viewport_mobile_baselined_entry_does_not_gate():
    base = {"_meta": {}, "pages": {}, "pages_mobile": {"/data/vitals/": [_v("color-contrast", "serious")]}}
    out = a11y_audit.gate_findings("/data/vitals/", [_v("color-contrast", "serious")], base, viewport="mobile")
    assert out["new"] == [] and [v["id"] for v in out["baselined"]] == ["color-contrast"]


def test_load_baseline_setdefaults_mobile_ledgers_for_legacy_files(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"_meta": {}, "pages": {"/": [_v("x", "serious")]}, "pages_light": {}}))
    base = a11y_audit.load_baseline(str(p))
    assert base["pages_mobile"] == {} and base["pages_light_mobile"] == {}
    assert a11y_audit.load_baseline(str(tmp_path / "missing.json"))["pages_light_mobile"] == {}


def test_update_baseline_mobile_writes_pages_mobile_and_preserves_the_other_three(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(
        json.dumps(
            {
                "_meta": {"captured_at": "2026-01-01T00:00:00+00:00", "note": "keep me"},
                "pages": {"/": [{"id": "keep", "impact": "serious", "help": "", "nodes": 1}]},
                "pages_light": {"/": [{"id": "keep-light", "impact": "serious", "help": "", "nodes": 1}]},
                "pages_light_mobile": {"/": [{"id": "keep-lm", "impact": "serious", "help": "", "nodes": 1}]},
            }
        )
    )
    out = a11y_audit.update_baseline({"/": [_v("color-contrast", "serious", 3)]}, path=str(p), viewport="mobile")
    assert [r["id"] for r in out["pages_mobile"]["/"]] == ["color-contrast"]
    assert [r["id"] for r in out["pages"]["/"]] == ["keep"]
    assert [r["id"] for r in out["pages_light"]["/"]] == ["keep-light"]
    assert [r["id"] for r in out["pages_light_mobile"]["/"]] == ["keep-lm"]
    assert out["_meta"]["captured_at"] == "2026-01-01T00:00:00+00:00" and out["_meta"]["note"] == "keep me"
    assert "captured_at_mobile" in out["_meta"] and "390x844" in out["_meta"]["note_mobile"]
    # light+mobile gets its own meta pair too
    out2 = a11y_audit.update_baseline({"/": []}, path=str(p), theme="light", viewport="mobile")
    assert "captured_at_light_mobile" in out2["_meta"] and "/" not in out2["pages_light_mobile"]


def test_summarize_viewport_mobile_counts_pages_mobile_only():
    base = {"pages": {"/": [{"impact": "serious"}] * 3}, "pages_mobile": {"/": [{"impact": "serious"}, {"impact": "minor"}]}}
    assert a11y_audit.summarize(base, viewport="mobile") == {"serious": 1, "minor": 1}
    assert a11y_audit.summarize(base) == {"serious": 3}


def test_committed_baseline_has_an_explicit_mobile_section():
    """#3277 acceptance: the ledger gains an explicit mobile section. Read the raw
    file, not load_baseline() — setdefault would fabricate the key."""
    with open(a11y_audit.BASELINE_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    assert "pages_mobile" in raw, "tests/a11y_baseline.json has no explicit pages_mobile ledger (#3277)"
    assert "captured_at_mobile" in raw["_meta"], "the mobile ledger must record when it was captured"
    assert raw["_meta"].get("note_mobile"), "the mobile ledger must state its own contract"


def test_scrollable_region_focusable_is_driven_to_zero_not_baselined():
    """The class is FIXED (motion.js scroll-region primitive), not accepted as debt:
    the rule must appear in NO ledger, so a reappearance on any page is a NEW
    serious violation — the mutation proof below is the armed gate."""
    base = a11y_audit.load_baseline()
    ledgers = {k: base[k] for k in a11y_audit.LEDGER_KEYS}  # the rule is NAMED in _meta's note_mobile — scan the ledgers only
    assert "scrollable-region-focusable" not in json.dumps(ledgers), "scrollable-region-focusable must be fixed, never baselined (#3277)"
    for page_path in MOBILE_SRF_PAGES_LIVE_2026_08_31:
        out = a11y_audit.gate_findings(page_path, [_v("scrollable-region-focusable", "serious", 3)], base, viewport="mobile")
        assert [v["id"] for v in out["new"]] == [
            "scrollable-region-focusable"
        ], f"{page_path}: a re-introduced scroll region must gate @390"


def test_visual_qa_runs_the_axe_gate_at_both_viewports_in_order():
    """capture_page must call the shared _a11y_gate helper once for "desktop" and
    once for "mobile", and the mobile call must come AFTER the 390px viewport is
    set and the mobile reveal pass has run — otherwise it audits the desktop DOM."""
    import visual_qa

    src = inspect.getsource(visual_qa.capture_page)
    i_desk = src.index('_a11y_gate(page, path, a11y_baseline, theme, "desktop"')
    i_vp = src.index('page.set_viewport_size({"width": 390, "height": 844})')
    i_mob = src.index('_a11y_gate(page, path, a11y_baseline, theme, "mobile"')
    assert i_desk < i_vp < i_mob, "mobile axe pass must run after the 390px viewport is set"
    assert "_scroll_and_reveal(page)" in src[i_vp:i_mob], "mobile axe pass must run after the mobile _scroll_and_reveal"
    assert '"a11y_mobile": a11y_mobile_result' in src


def test_the_three_gating_sweeps_get_the_mobile_pass_with_no_flag_to_forget():
    """The whole point of #3277 is that the GATING chain measures 390px. The mobile
    pass is unconditional inside capture_page (not behind --mobile, which only
    changes what the context is opened as), so all three gating invocations get it
    with no new workflow line — but only while none of them opts out of the audit."""
    import visual_qa

    root = os.path.dirname(os.path.dirname(os.path.abspath(a11y_audit.__file__)))
    for wf in ("ci-cd.yml", "site-deploy.yml", "visual-qa.yml"):
        with open(os.path.join(root, ".github", "workflows", wf), encoding="utf-8") as f:
            text = f.read()
        invocations = [ln for ln in text.splitlines() if "tests/visual_qa.py" in ln and ln.strip().startswith("python3")]
        assert invocations, f"{wf} no longer invokes tests/visual_qa.py — the gating chain moved (#3277)"
        for ln in invocations:
            assert "--no-a11y" not in ln, f"{wf} opts out of the axe audit — the 390px pass goes with it (#3277): {ln.strip()}"
    # the pass itself is not behind a flag: capture_page runs it whenever a baseline
    # is loaded, and run_sweep loads one unless --no-a11y was passed.
    src = inspect.getsource(visual_qa.capture_page)
    guard = src[src.index('page.set_viewport_size({"width": 390, "height": 844})') :]
    guard = guard[: guard.index('_a11y_gate(page, path, a11y_baseline, theme, "mobile"')]
    assert "if a11y_baseline is not None:" in guard, "the mobile axe pass must be gated ONLY on having a baseline"
    assert "mobile_only" not in guard and "--mobile" not in guard


def test_visual_qa_update_baseline_writes_both_viewports():
    import visual_qa

    src = inspect.getsource(visual_qa.run_sweep)
    assert '("desktop", "a11y"), ("mobile", "a11y_mobile")' in src, "--update-baseline must rewrite the mobile ledger from the mobile pass"


# ── #3548: every serious/critical baseline entry names an owning issue ──────
#
# Mirrors tests/truth_baseline_audit.py's #2956 rule for the reader-truth
# ledger: a debt ledger with no ownership requirement degrades into an excuse
# file. Scoped to serious/critical (GATING_IMPACTS) — moderate/minor debt is
# advisory by design and stays untracked, same line the gate itself draws.


def test_committed_baseline_has_no_untriaged_serious_entries():
    baseline = a11y_audit.load_baseline()
    untriaged = a11y_audit.untriaged_serious_entries(baseline)
    assert untriaged == [], (
        "tests/a11y_baseline.json has serious/critical entries with no `issue` field — "
        f"file/name the tracking issue for each before committing: {untriaged}"
    )


def test_untriaged_serious_entries_flags_a_planted_missing_issue():
    """Negative control: a planted serious entry with no `issue` field must be
    caught — proves the guard actually inspects the field, not a vacuous pass."""
    baseline = {
        "pages": {"/planted/": [_v("color-contrast", "serious")]},
        "pages_light": {},
        "pages_mobile": {},
        "pages_light_mobile": {},
    }
    out = a11y_audit.untriaged_serious_entries(baseline)
    assert out == [("pages", "/planted/", "color-contrast")]


def test_untriaged_serious_entries_accepts_a_real_issue_ref():
    baseline = {
        "pages": {"/planted/": [{**_v("color-contrast", "serious"), "issue": "#3673"}]},
        "pages_light": {},
        "pages_mobile": {},
        "pages_light_mobile": {},
    }
    assert a11y_audit.untriaged_serious_entries(baseline) == []


def test_untriaged_serious_entries_rejects_a_blank_or_placeholder_issue():
    for bad in ("", "   ", "UNTRIAGED", "3673", "issue #3673", "#abc"):
        baseline = {
            "pages": {"/planted/": [{**_v("color-contrast", "serious"), "issue": bad}]},
            "pages_light": {},
            "pages_mobile": {},
            "pages_light_mobile": {},
        }
        out = a11y_audit.untriaged_serious_entries(baseline)
        assert out == [("pages", "/planted/", "color-contrast")], f"issue={bad!r} should not satisfy the rule"


def test_untriaged_serious_entries_never_flags_moderate_or_minor_debt():
    """Moderate/minor rows are advisory by design (GATING_IMPACTS excludes them)
    — the ownership rule must not reach past the same line the gate itself draws."""
    baseline = {
        "pages": {"/planted/": [_v("heading-order", "moderate"), _v("empty-table-header", "minor")]},
        "pages_light": {},
        "pages_mobile": {},
        "pages_light_mobile": {},
    }
    assert a11y_audit.untriaged_serious_entries(baseline) == []


def test_update_baseline_carries_forward_an_existing_issue_ref(tmp_path):
    """#3548: without this, the NEXT --update-baseline after a human triages a
    row would silently wipe the `issue` field right back to UNTRIAGED — the
    ownership rule would then re-red on every legitimate re-sweep."""
    p = str(tmp_path / "d.json")
    a11y_audit.update_baseline({"/x/": [_v("color-contrast", "serious")]}, path=p)
    base = a11y_audit.load_baseline(p)
    assert base["pages"]["/x/"][0]["issue"] == a11y_audit.UNTRIAGED
    base["pages"]["/x/"][0]["issue"] = "#3673"  # the human triage step
    with open(p, "w") as f:
        json.dump(base, f)

    # A later re-sweep observes the SAME rule on the SAME page again.
    a11y_audit.update_baseline({"/x/": [_v("color-contrast", "serious", nodes=9)]}, path=p)
    base = a11y_audit.load_baseline(p)
    assert base["pages"]["/x/"][0]["issue"] == "#3673", "the human's triage must survive a re-sweep"
    assert base["pages"]["/x/"][0]["nodes"] == 9  # the fresh observation still lands


def test_update_baseline_does_not_carry_an_issue_ref_to_a_different_rule(tmp_path):
    """Negative control: the carry-forward is keyed by rule id — a DIFFERENT
    rule newly appearing on the same page must land UNTRIAGED, not inherit an
    unrelated rule's ownership by accident."""
    p = str(tmp_path / "e.json")
    a11y_audit.update_baseline({"/x/": [_v("color-contrast", "serious")]}, path=p)
    base = a11y_audit.load_baseline(p)
    base["pages"]["/x/"][0]["issue"] = "#3673"
    with open(p, "w") as f:
        json.dump(base, f)

    a11y_audit.update_baseline({"/x/": [_v("color-contrast", "serious"), _v("svg-img-alt", "serious")]}, path=p)
    base = a11y_audit.load_baseline(p)
    rows = {r["id"]: r["issue"] for r in base["pages"]["/x/"]}
    assert rows["color-contrast"] == "#3673"
    assert rows["svg-img-alt"] == a11y_audit.UNTRIAGED
