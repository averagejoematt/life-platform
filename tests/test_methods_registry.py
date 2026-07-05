"""tests/test_methods_registry.py — #544 the Methods page registry.

Two things this guards:
  1. The registry's shape is a clean per-stat lookup (a future provenance popover,
     #584, needs to resolve a stat id to one dict without special-casing).
  2. The anti-drift tripwire: every entry's recorded fingerprint must match the LIVE
     source hash of the function it documents. If this test goes red, a documented
     stats_core/calibration_core function changed and its registry entry (formula/
     window/limitations) needs a human re-read before the fingerprint is updated.

Also exercises the generator (scripts/v4_build_methods.py) end-to-end against a
temp directory, so a rendering regression is caught without touching the real
site/ tree.
"""

import html
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import methods_registry as mr  # noqa: E402

REQUIRED_FIELDS = {
    "id",
    "name",
    "module",
    "function",
    "category",
    "formula",
    "window",
    "limitations",
    "min_n",
    "used_by",
    "fingerprint",
    "recorded_fingerprint",
}


class TestRegistryShape:
    def test_nonempty_and_covers_both_modules(self):
        stats = mr.list_stats()
        assert len(stats) >= 10
        modules = {e["module"] for e in stats}
        assert "stats_core" in modules
        assert "calibration_core" in modules

    def test_every_entry_has_required_fields(self):
        for stat_id, entry in mr.get_registry().items():
            assert entry["id"] == stat_id
            assert REQUIRED_FIELDS.issubset(entry.keys()), f"{stat_id} missing fields"
            assert entry["name"] and entry["formula"] and entry["window"] and entry["limitations"]
            assert entry["category"] in mr.list_categories()

    def test_ids_are_unique_and_match_dict_keys(self):
        ids = [e["id"] for e in mr.list_stats()]
        assert len(ids) == len(set(ids))

    def test_get_stat_lookup(self):
        # The clean-lookup contract a future provenance popover (#584) would use.
        assert mr.get_stat("pearson_r") is not None
        assert mr.get_stat("pearson_r")["function"] == "pearson_r"
        assert mr.get_stat("does-not-exist") is None

    def test_categories_are_ordered_and_deduped(self):
        cats = mr.list_categories()
        assert len(cats) == len(set(cats))
        assert "Correlation" in cats
        assert "Calibration" in cats


class TestFingerprintDriftGate:
    def test_fingerprints_match_source(self):
        stale = mr.verify_fingerprints()
        assert stale == [], (
            "A documented stats_core/calibration_core function changed without its " f"methods_registry.py entry being re-reviewed: {stale}"
        )

    def test_fingerprint_actually_changes_on_edit(self):
        # Sanity check that _fingerprint isn't a no-op (e.g. always returning the same
        # constant) — hash two different-but-real functions and confirm they differ.
        import calibration_core
        import stats_core

        fp_a = mr._fingerprint(stats_core.pearson_r)
        fp_b = mr._fingerprint(stats_core.brier_score)
        fp_c = mr._fingerprint(calibration_core.score_pairs)
        assert fp_a and fp_b and fp_c
        assert len({fp_a, fp_b, fp_c}) == 3


class TestGenerator:
    def test_render_produces_html_for_every_stat(self, tmp_path):
        build = importlib.import_module("v4_build_methods")
        stats = build.list_stats()
        categories = build.list_categories()
        rendered = build.render(stats, categories)

        assert rendered.startswith("<!DOCTYPE html>")
        assert "<title>" in rendered and "Methods Registry" in rendered
        assert rendered.count("<html") == 1 and rendered.count("</html>") == 1
        for entry in stats:
            assert html.escape(entry["name"], quote=True) in rendered
            assert f'id="stat-{entry["id"]}"' in rendered

    def test_main_writes_index_html(self, tmp_path, monkeypatch):
        build = importlib.import_module("v4_build_methods")
        monkeypatch.setattr(build, "ROOT", tmp_path)
        rc = build.main()
        assert rc == 0
        out = tmp_path / "site" / "method" / build.SLUG / "index.html"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Pearson correlation" in content

    def test_esc_prevents_injection(self):
        build = importlib.import_module("v4_build_methods")
        assert "<script>" not in build.esc("<script>alert(1)</script>")
