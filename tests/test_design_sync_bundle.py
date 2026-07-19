"""#1462 — scripts/design_sync_bundle.py, the v5 design-system export bundle builder.

Verifies the three acceptance criteria that make a produced bundle usable inside a
Claude Design session:

  1. the builder produces the four-directory bundle (assets/, foundations/, components/,
     reference/) from repo truth, and re-running it is a no-op (byte-identical output —
     deterministic, safe to re-run as the design-sync pipeline evolves).
  2. every foundations/ and components/ preview HTML carries a first-line
     `<!-- @dsCard group="…" -->` marker.
  3. the whole bundle carries zero absolute (`/…`) asset/nav references and zero literal
     references to the live production domain — a Claude Design session mounts the bundle
     at an unknown root, so anything absolute-path would 404 or point at the wrong site.

The RED proof (`test_verify_bundle_catches_a_broken_preview`) builds a real bundle, then
corrupts one on-disk preview file (strips its @dsCard marker and injects an absolute href)
and asserts `design_sync_bundle._verify_bundle` refuses it — proving the self-check is
load-bearing, not decorative. The corruption is done to a tempdir copy; nothing here
touches (or leaves behind) real repo state.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import design_sync_bundle as dsb  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def built_bundle():
    """Build the bundle once per test module into a throwaway tempdir (never scratch/ —
    keeps this test hermetic and parallel-safe alongside a human running the CLI)."""
    tmp = Path(tempfile.mkdtemp(prefix="design_sync_bundle_test_"))
    out = tmp / "bundle"
    dsb.build(REPO_ROOT, out)
    yield out
    shutil.rmtree(tmp, ignore_errors=True)


class TestFourDirectoryBundle:
    def test_produces_the_four_top_level_directories(self, built_bundle):
        for name in ("assets", "foundations", "components", "reference"):
            d = built_bundle / name
            assert d.is_dir(), f"missing top-level bundle dir: {name}"
            assert any(d.iterdir()), f"{name}/ was created but is empty"

    def test_assets_carries_the_evidence_inventory(self, built_bundle):
        assets = built_bundle / "assets"
        assert (assets / "css/tokens.css").is_file()
        assert (assets / "css/fonts.css").is_file()
        assert (assets / "icons/icons.svg").is_file()
        assert (assets / "fonts_base64.json").is_file()
        woff2 = sorted((assets / "fonts/v4").glob("*.woff2"))
        assert len(woff2) == 5, f"expected the 5 self-hosted woff2 files, found {len(woff2)}"

    def test_foundations_covers_the_required_set(self, built_bundle):
        names = {p.name for p in (built_bundle / "foundations").glob("*.html")}
        assert names == {
            "palette-dark.html",
            "palette-light.html",
            "type-triad.html",
            "spacing-radii.html",
            "pillar-colors.html",
            "breakpoints.html",
        }

    def test_components_covers_the_shared_kit(self, built_bundle):
        names = {p.name for p in (built_bundle / "components").glob("*.html")}
        expected = {
            "page-hero-loop-ribbon.html",
            "prose.html",
            "provenance.html",
            "tabset.html",
            "loop-diagram.html",
            "readout.html",
            "cb-cards.html",
            "confidence-grammar.html",
            "sigils-tier-emblems.html",
            "portraits.html",
            "icon-sheet.html",
            "chart-gallery.html",
        }
        assert expected <= names

    def test_reference_carries_representative_built_pages(self, built_bundle):
        names = {p.name for p in (built_bundle / "reference").glob("*.html")}
        assert len(names) >= 3

    def test_rerun_is_deterministic_byte_identical(self, tmp_path):
        """Re-running the builder against the same repo state must be a no-op — the
        pipeline (#1460 D2) diffs the bundle against the design project on every sync, so
        a non-deterministic builder would manufacture a phantom diff on every run."""
        out_a = tmp_path / "a"
        out_b = tmp_path / "b"
        dsb.build(REPO_ROOT, out_a)
        dsb.build(REPO_ROOT, out_b)

        files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
        assert files_a == files_b

        for rel in files_a:
            assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), f"non-deterministic output: {rel}"


class TestDsCardMarker:
    def test_every_foundation_preview_has_the_marker(self, built_bundle):
        for html_path in (built_bundle / "foundations").glob("*.html"):
            first_line = html_path.read_text(encoding="utf-8").split("\n", 1)[0]
            assert first_line.startswith('<!-- @dsCard group="'), f"{html_path.name}: missing/misplaced @dsCard marker"

    def test_every_component_preview_has_the_marker(self, built_bundle):
        for html_path in (built_bundle / "components").glob("*.html"):
            first_line = html_path.read_text(encoding="utf-8").split("\n", 1)[0]
            assert first_line.startswith('<!-- @dsCard group="'), f"{html_path.name}: missing/misplaced @dsCard marker"

    def test_marker_is_byte_zero_not_merely_present(self, built_bundle):
        # A marker anywhere in the file isn't the contract — it must be the literal first
        # line, since a design-project importer keys off line 0 without parsing the DOM.
        sample = built_bundle / "foundations" / "palette-dark.html"
        text = sample.read_text(encoding="utf-8")
        assert text.startswith('<!-- @dsCard group="foundations" -->\n')


class TestZeroAbsoluteRefs:
    def test_no_absolute_href_or_src_in_renderable_files(self, built_bundle):
        for path in built_bundle.rglob("*"):
            if not path.is_file() or path.suffix not in (".html", ".css", ".js", ".json"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not dsb._ABS_REF_RE.search(text), f"{path.relative_to(built_bundle)}: absolute href/src ref"
            assert not dsb._URL_ABS_RE.search(text), f"{path.relative_to(built_bundle)}: absolute url(...) ref"

    def test_no_literal_production_domain_reference(self, built_bundle):
        for path in built_bundle.rglob("*"):
            if not path.is_file() or path.suffix not in (".html", ".css", ".js", ".json", ".md"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not dsb._SITE_URL_RE.search(text), f"{path.relative_to(built_bundle)}: literal production-domain reference"

    def test_icons_svg_absolute_mention_is_the_one_documented_exception(self, built_bundle):
        """assets/icons.svg is copied byte-verbatim from site truth (design fidelity), and
        its own header COMMENT documents an absolute usage path for consuming code — that's
        the one known, intentional exception (see design_sync_bundle._verify_bundle's
        docstring note). Pin it explicitly so a real regression (a NEW absolute ref outside
        that comment) still fails loudly instead of hiding behind this exception."""
        icons_svg = (built_bundle / "assets/icons/icons.svg").read_text(encoding="utf-8")
        outside_comments = dsb._XML_COMMENT_RE.sub("", icons_svg)
        assert not dsb._ABS_REF_RE.search(outside_comments), "icons.svg has an absolute ref OUTSIDE its header comment"


class TestVerifyBundleSelfCheck:
    def test_verify_bundle_passes_on_a_real_build(self, built_bundle):
        dsb._verify_bundle(built_bundle)  # must not raise

    def test_verify_bundle_catches_a_broken_preview(self, built_bundle, tmp_path):
        """RED proof: deliberately corrupt an on-disk preview (strip the @dsCard marker,
        inject an absolute href) and assert the builder's self-check refuses it. Runs
        against a throwaway copy of the real bundle — the fixture's own directory is left
        untouched for the other tests in this module."""
        broken = tmp_path / "broken_bundle"
        shutil.copytree(built_bundle, broken)

        target = broken / "components" / "provenance.html"
        original = target.read_text(encoding="utf-8")
        assert original.startswith('<!-- @dsCard group="components" -->\n')

        corrupted = original.split("\n", 1)[1]  # drop the first line -> no @dsCard marker
        corrupted = corrupted.replace("<body>", '<body><a href="/data/">broken absolute nav link</a>', 1)
        target.write_text(corrupted, encoding="utf-8")

        with pytest.raises(AssertionError) as excinfo:
            dsb._verify_bundle(broken)
        message = str(excinfo.value)
        assert "provenance.html" in message
        assert "@dsCard" in message or "absolute" in message
