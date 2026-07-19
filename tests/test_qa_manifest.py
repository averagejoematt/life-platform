"""
test_qa_manifest.py — the #1426 completeness + derivation gates.

Two jobs:
  1. COMPLETENESS: every page-shaped file under site/ (legacy/ excluded by
     standing policy) has a qa_manifest entry or an EXEMPT reason; every
     manifest entry points at a real file. Adding an unregistered page reds CI
     here — the "new page = FOUR registries" trap dies at this gate.
  2. DERIVATION: the four consumers (visual_qa PAGES, restart_verify_rendered
     PAGES, smoke_test_site.sh page block, site-review PAGE_BINDINGS) actually
     derive from the manifest — no independent hand-maintained page list can
     quietly return.
"""

import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import qa_manifest  # noqa: E402


# ── 1. Completeness ───────────────────────────────────────────────────────────
def test_every_site_page_registered_or_exempt():
    unregistered, ghosts = qa_manifest.self_check()
    assert not unregistered, f"Unregistered site/ pages (add a tests/qa_manifest.py entry or an EXEMPT reason): {sorted(unregistered)}"
    assert not ghosts, f"Manifest entries with no file under site/: {sorted(ghosts)}"


def test_manifest_entries_well_formed():
    valid_classes = {"live-data", "narrative", "static", "utility", "generated"}
    for p in qa_manifest.MANIFEST:
        assert p["path"].startswith("/"), p["path"]
        assert p["tier"] in (1, 2, 3, 4), f"{p['path']}: tier {p['tier']}"
        assert p["content_class"] in valid_classes, f"{p['path']}: {p['content_class']}"
        assert isinstance(p["api_deps"], list) and isinstance(p["js_modules"], list), p["path"]
        assert p["smoke"].isdigit(), f"{p['path']}: smoke={p['smoke']}"


def test_tier1_pages_are_the_doors():
    tier1 = {p["path"] for p in qa_manifest.MANIFEST if p["tier"] == 1}
    assert tier1 == {"/", "/cockpit/", "/data/", "/story/", "/coaching/", "/protocols/"}


def test_tier1_and_tier2_pages_are_visually_swept():
    """Deploy-gating tiers must actually be in the Playwright sweep — a tier-1/2
    page with visual=None would claim coverage the sweep doesn't deliver.

    #1427 drained the tier-2 pending list to empty: every tier-1 and tier-2 page
    now carries a visual def (or visual_variants). No exemptions remain at this
    tier — a future tier-2 page that lands without a visual def reds here, by
    design (the "new page = FOUR registries" trap, applied to render coverage)."""
    for p in qa_manifest.MANIFEST:
        if p["tier"] == 1:
            assert p.get("visual"), f"tier-1 page {p['path']} missing a visual def"
        if p["tier"] == 2:
            assert p.get("visual") or p.get("visual_variants"), f"tier-2 page {p['path']} is not visually swept"


# ── 2. Derivation gates ───────────────────────────────────────────────────────
def test_visual_qa_pages_derive_from_manifest():
    import visual_qa

    assert visual_qa.PAGES == qa_manifest.visual_pages()
    # and no literal page list survives in the module source
    src = open(os.path.join(_HERE, "visual_qa.py")).read()
    assert (
        "EVIDENCE_TOPICS = [" not in src and '"path": "/cockpit/"' not in src
    ), "visual_qa.py has grown an independent page list again — pages belong in qa_manifest.py"


def test_restart_verify_rendered_derives_from_manifest():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rvr", os.path.join(_REPO, "deploy", "restart_verify_rendered.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.PAGES == qa_manifest.leak_scan_paths()
    assert len(m.PAGES) >= 70, "leak-scan surface shrank — the manifest facet should cover the full live surface"


def test_smoke_script_derives_from_manifest():
    src = open(os.path.join(_REPO, "deploy", "smoke_test_site.sh")).read()
    assert "qa_manifest.py" in src and "--emit smoke" in src, "smoke script must sweep pages from qa_manifest"
    # the old hand-maintained per-page block must not come back:
    assert not re.search(
        r'check_status "Evidence · vitals"', src
    ), "smoke_test_site.sh has grown hand-maintained page checks again — pages belong in qa_manifest.py"


def test_page_bindings_pages_known_to_manifest():
    import site_review_bindings as b

    manifest_paths = set(qa_manifest.PAGES_BY_PATH)
    for e in b.PAGE_BINDINGS:
        # fragment deep-links (e.g. /coaching/by-coach/#training_coach) bind the base page
        base = e["path"].split("#")[0]
        assert base in manifest_paths, f"PAGE_BINDINGS entry {base} not in qa_manifest — bindings may only bind registered pages"


def test_tier1_pages_have_bindings():
    import site_review_bindings as b

    bound = {e["path"] for e in b.PAGE_BINDINGS}
    for p in qa_manifest.MANIFEST:
        if p["tier"] == 1:
            assert p["path"] in bound, f"tier-1 page {p['path']} has no site-review binding"


def test_exemptions_carry_reasons():
    for path, reason in qa_manifest.EXEMPT.items():
        assert len(reason) > 15, f"EXEMPT[{path}] needs a real reason, not a token"


@pytest.mark.parametrize("emit", ["paths", "smoke", "leak"])
def test_emitters_run(emit):
    import subprocess

    r = subprocess.run(
        [sys.executable, os.path.join(_HERE, "qa_manifest.py"), "--emit", emit],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and len(r.stdout.splitlines()) >= 30, r.stderr
