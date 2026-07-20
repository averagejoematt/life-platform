"""#1467 — scripts/design_sync_capture.py, the reference-capture refresh leg of /design-sync.

Covers the acceptance criteria that don't need a browser or the network — the pure layer
(the live Playwright leg itself is exercised by running /design-sync for real):

  1. the capture SET derives from THE page registry (tests/qa_manifest.py): every tier-1
     door + the one data-dense surface — never a hand list that can drift
     (memory: reference_new_site_page_registries).
  2. every capture card carries the first-line `@dsCard group="reference"` marker, so
     captures render in the Design System pane alongside foundations/components.
  3. cards + the captures_base64.json manifest pass the bundle's own verification sweep
     (zero absolute refs, zero live-domain literals) — RED-proved by corrupting a card
     and asserting `_verify_bundle` refuses it.
  4. the module imports playwright/visual_qa lazily only — a module-level import would
     red the whole suite at collection in the no-Playwright unit-test environment
     (memory: reference_test_layer_dep_import_collection_red). Checked via AST, not
     sys.modules, so it can't false-fail based on test ordering.
"""

import ast
import base64
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import design_sync_bundle as dsb  # noqa: E402
import design_sync_capture as dsc  # noqa: E402
from qa_manifest import MANIFEST  # noqa: E402


class TestCaptureSetDerivation:
    def test_set_is_the_tier1_doors_plus_the_data_dense_surface(self):
        pages = dsc.capture_set(REPO_ROOT)
        tier1_paths = [p["path"] for p in MANIFEST if p["tier"] == 1]
        expected = tier1_paths + ([dsc.DATA_DENSE_PATH] if dsc.DATA_DENSE_PATH not in tier1_paths else [])
        assert [p["path"] for p in pages] == expected

    def test_covers_all_six_doors_and_is_registry_derived(self):
        paths = {p["path"] for p in dsc.capture_set(REPO_ROOT)}
        for door in ("/", "/cockpit/", "/story/", "/data/", "/protocols/", "/coaching/"):
            assert door in paths, f"door {door} missing from the capture set"
        assert dsc.DATA_DENSE_PATH in paths

    def test_data_dense_path_exists_in_the_manifest(self):
        assert dsc.DATA_DENSE_PATH in {
            p["path"] for p in MANIFEST
        }, "DATA_DENSE_PATH points at a route the manifest no longer has — capture_set() must raise, and this constant needs updating"

    def test_slugs_are_unique_and_home_is_named(self):
        pages = dsc.capture_set(REPO_ROOT)
        slugs = [p["slug"] for p in pages]
        assert len(slugs) == len(set(slugs))
        assert "home" in slugs  # "/" must not collapse to an empty slug
        for s in slugs:
            assert "/" not in s and s != ""


@pytest.fixture()
def fake_bundle(tmp_path):
    """A minimal bundle skeleton with a captures dir holding fake PNG bytes — enough for
    the card/manifest writers and the bundle-wide verification sweep, no browser."""
    ref = tmp_path / "reference"
    captures = ref / "captures"
    captures.mkdir(parents=True)
    (captures / "home.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-home")
    (captures / "data-sleep.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-sleep")
    return tmp_path


PAGE_HOME = {"path": "/", "name": "Home (loop dial)", "slug": "home"}
PAGE_SLEEP = {"path": "/data/sleep/", "name": "Data · Sleep", "slug": "data-sleep"}


class TestCaptureCards:
    def test_card_carries_the_first_line_dscard_marker(self, fake_bundle):
        card = dsc.write_capture_card(fake_bundle / "reference", PAGE_HOME, "2026-01-05")
        text = card.read_text(encoding="utf-8")
        assert text.startswith('<!-- @dsCard group="reference" -->\n')

    def test_card_references_the_png_relatively_and_shows_currency(self, fake_bundle):
        card = dsc.write_capture_card(fake_bundle / "reference", PAGE_SLEEP, "2026-01-05")
        text = card.read_text(encoding="utf-8")
        assert 'src="captures/data-sleep.png"' in text
        assert "captured 2026-01-05" in text  # a design session can see how fresh the capture is
        assert "/data/sleep/" in text  # the route as documentation text
        assert not dsb._ABS_REF_RE.search(text), "capture card leaked an absolute href/src"
        assert not dsb._SITE_URL_RE.search(text), "capture card leaked the live production domain"

    def test_manifest_round_trips_the_png_bytes(self, fake_bundle):
        out = dsc.write_captures_manifest(fake_bundle / "reference")
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert set(manifest) == {"home.png", "data-sleep.png"}
        assert base64.b64decode(manifest["home.png"]) == b"\x89PNG\r\n\x1a\nfake-home"

    def test_manifest_refuses_an_empty_captures_dir(self, tmp_path):
        ref = tmp_path / "reference"
        (ref / "captures").mkdir(parents=True)
        with pytest.raises(AssertionError):
            dsc.write_captures_manifest(ref)


class TestBundleVerificationOverCaptures:
    def test_cards_and_manifest_pass_the_bundle_sweep(self, fake_bundle):
        for pg in (PAGE_HOME, PAGE_SLEEP):
            dsc.write_capture_card(fake_bundle / "reference", pg, "2026-01-05")
        dsc.write_captures_manifest(fake_bundle / "reference")
        dsb._verify_bundle(fake_bundle)  # must not raise

    def test_red_proof_a_corrupted_card_is_refused(self, fake_bundle):
        card = dsc.write_capture_card(fake_bundle / "reference", PAGE_HOME, "2026-01-05")
        text = card.read_text(encoding="utf-8")
        corrupted = text.split("\n", 1)[1]  # strip the @dsCard marker
        corrupted = corrupted.replace("<body>", '<body><a href="/data/">absolute nav leak</a>', 1)
        card.write_text(corrupted, encoding="utf-8")
        with pytest.raises(AssertionError) as excinfo:
            dsb._verify_bundle(fake_bundle)
        assert "home-capture.html" in str(excinfo.value)

    def test_refresh_refuses_to_run_without_a_built_bundle(self, tmp_path):
        with pytest.raises(AssertionError, match="design_sync_bundle"):
            dsc.refresh(REPO_ROOT, tmp_path / "nonexistent")


class TestCollectionSafety:
    def test_no_module_level_playwright_or_visual_qa_import(self):
        """AST-checked (order-independent): playwright + visual_qa may only be imported
        inside function bodies — a top-level import reds the whole suite at collection
        in environments without the browser deps."""
        tree = ast.parse(Path(dsc.__file__).read_text(encoding="utf-8"))
        for node in tree.body:  # module level only — nested imports are the sanctioned pattern
            assert not isinstance(node, ast.ImportFrom) or (node.module or "").split(".")[0] not in (
                "playwright",
                "visual_qa",
            ), f"module-level import of {node.module} — must stay lazy"
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
                assert "playwright" not in names and "visual_qa" not in names, f"module-level import {names} — must stay lazy"
