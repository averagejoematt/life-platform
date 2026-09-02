"""tests/test_methods_registry.py — #544 the Methods page registry.

Two things this guards:
  1. The registry's shape is a clean per-stat lookup (a future provenance popover,
     #584, needs to resolve a stat id to one dict without special-casing).
  2. The anti-drift tripwire: every entry's recorded fingerprint must match the LIVE
     CLOSURE hash of the function it documents (#3449 — the fingerprint hashes not
     just the function's own source but its bound defaults and every helper/constant
     it reads by name in its own module). If this test goes red, a documented
     stats_core/calibration_core function (or a helper/constant it depends on)
     changed and its registry entry (formula/window/limitations) needs a human
     re-read before the fingerprint is updated.

Also exercises the generator (scripts/v4_build_methods.py) end-to-end against a
temp directory, so a rendering regression is caught without touching the real
site/ tree.
"""

import html
import importlib
import importlib.util
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from experiment import methods_registry as mr  # noqa: E402


def _build_module(source, name):
    """A throwaway module loaded from a REAL temp .py file — lets a test mutate
    exactly ONE hashed input (a function's own body, a helper it calls, or a
    module-level constant) without touching any real repo file.

    A real file (rather than an in-memory `exec`) means `inspect.getsource`
    (which `_fingerprint`/`_closure_sources` call) just works — no linecache
    priming needed, and no bare `exec()` for a lint rule to flag.
    """
    tmp_dir = tempfile.mkdtemp(prefix="test_methods_registry_")
    path = os.path.join(tmp_dir, f"{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            "A documented stats_core/calibration_core function (or a helper/constant "
            "it depends on) changed without its methods_registry.py entry being "
            f"re-reviewed: {stale}"
        )

    def test_fingerprint_distinguishes_different_functions(self):
        # Distinctness, NOT edit-sensitivity (#3449 — this test used to be named
        # test_fingerprint_actually_changes_on_edit, which claims a property this
        # check never exercised: no function here is ever edited, only compared
        # against two OTHER real functions). Still a useful sanity check that
        # _fingerprint isn't a no-op returning one constant for everything.
        from common import stats_core
        from experiment import calibration_core

        fp_a = mr._fingerprint(stats_core.pearson_r)
        fp_b = mr._fingerprint(stats_core.brier_score)
        fp_c = mr._fingerprint(calibration_core.score_pairs)
        assert fp_a and fp_b and fp_c
        assert len({fp_a, fp_b, fp_c}) == 3

    def test_fingerprint_changes_on_direct_edit(self):
        """The positive control for the direct-edit path (#3449 AC4): mutating a
        function's OWN body changes its fingerprint. This is the property the
        old, misnamed test never actually checked — kept here under its correct
        name so the direct-edit path stays proven as the closure mechanism grows."""
        v1 = _build_module("def target(x):\n    return x + 1\n", "direct_edit_v1")
        v2 = _build_module("def target(x):\n    return x + 2\n", "direct_edit_v2")
        assert mr._fingerprint(v1.target) != mr._fingerprint(v2.target)

    def test_fingerprint_reacts_to_helper_function_edit(self):
        """The #3449 closure-blind-spot fix, proof 1 of 2 (the `_block_resample`
        case): a helper called by bare name from the fingerprinted function
        changes the fingerprint even though the fingerprinted function's OWN
        source text is byte-identical across both versions."""
        src_v1 = "def _helper(x):\n    return x * 2\n\n" "def target(x):\n    return _helper(x) + 1\n"
        src_v2 = "def _helper(x):\n    return x * 3\n\n" "def target(x):\n    return _helper(x) + 1\n"
        v1 = _build_module(src_v1, "helper_edit_v1")
        v2 = _build_module(src_v2, "helper_edit_v2")

        assert inspect.getsource(v1.target) == inspect.getsource(v2.target)  # unchanged
        assert mr._fingerprint(v1.target) != mr._fingerprint(v2.target)  # still catches it

    def test_fingerprint_reacts_to_module_constant_read_in_body(self):
        """The #3449 closure-blind-spot fix, proof 2 of 2 (the `_Z_CRIT` case): a
        module-level constant read BY NAME inside the function body changes the
        fingerprint even though the function's own source text is unchanged."""
        src_v1 = "THRESHOLD = 10\n\n" "def target(x):\n    return x > THRESHOLD\n"
        src_v2 = "THRESHOLD = 99\n\n" "def target(x):\n    return x > THRESHOLD\n"
        v1 = _build_module(src_v1, "const_read_v1")
        v2 = _build_module(src_v2, "const_read_v2")

        assert inspect.getsource(v1.target) == inspect.getsource(v2.target)
        assert mr._fingerprint(v1.target) != mr._fingerprint(v2.target)

    def test_fingerprint_reacts_to_default_bound_constant_edit(self):
        """The exact empirical finding from #3449: `DEFAULT_SEED = 1337` changing
        to a different value passed the OLD source-only fingerprint green, because
        `seed=DEFAULT_SEED` is evaluated ONCE at def time — the literal signature
        text never changes, only the bound value in `__defaults__` does, and the
        old fingerprint never looked at `__defaults__` at all."""
        src_v1 = "SEED = 1337\n\n" "def target(x, seed=SEED):\n    return x + seed\n"
        src_v2 = "SEED = 4242\n\n" "def target(x, seed=SEED):\n    return x + seed\n"
        v1 = _build_module(src_v1, "default_bound_v1")
        v2 = _build_module(src_v2, "default_bound_v2")

        assert inspect.getsource(v1.target) == inspect.getsource(v2.target)
        assert v1.target.__defaults__ != v2.target.__defaults__
        assert mr._fingerprint(v1.target) != mr._fingerprint(v2.target)


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
