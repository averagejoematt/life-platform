"""tests/test_playwright_gated_skip_reporting.py — #3640: a test module gated
entirely behind a playwright import-or-skip guard skips silently in CI (no
playwright installed) and can only fail on a chromium machine, where CI never
runs it. The class: a gate that cannot fail where it runs and cannot pass where
it is run.

This does not add chromium to CI (a real runtime cost on every push for a
reusable workflow); it asserts the skip is NAMED, not silent — `scripts/
playwright_gated_tests.py::discover()` finds every gated module from source, and
`.github/workflows/ci-test.yml` actually invokes that discovery so every member
is called out by file in the CI log rather than disappearing into a skip count.

NB: this file deliberately never spells the literal marker string
`discover()` searches for (it would sweep itself into the very set it's
testing) — it is built from parts where a functional match is needed.
"""

import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Built from parts on purpose — see module docstring.
_MARKER = "importorskip(" + '"playwright'


def _load_discovery():
    path = os.path.join(REPO, "scripts", "playwright_gated_tests.py")
    spec = importlib.util.spec_from_file_location("_playwright_gated_tests", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _independent_scan():
    """A SECOND implementation of the same scan (never import the module under
    test for its own answer, per the fixture-must-be-the-wire discipline) — the
    guard this file exists to be."""
    out = []
    for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        with open(os.path.join(REPO, "tests", name), encoding="utf-8") as f:
            if _MARKER in f.read():
                out.append(name)
    return out


def test_discovery_matches_an_independent_source_scan():
    mod = _load_discovery()
    assert mod.discover() == _independent_scan()


def test_the_known_five_are_all_present_today():
    """Not a ceiling — a floor. If the family grows, the new member must also be
    named in CI (the next test) or this drifts loudly rather than silently."""
    mod = _load_discovery()
    names = set(mod.discover())
    expected = {
        "test_a11y_light_theme.py",
        "test_constellation_edge_cpts_1215.py",
        "test_pre_start_render.py",
        "test_sleep_device_disclosure_3451.py",
        "test_wave_tap_target.py",
    }
    assert names == expected, sorted(names)


def test_ci_test_workflow_actually_invokes_the_discovery_script():
    """The reporting step must exist and call the real discovery, not a second
    hand-typed file list that can drift from it."""
    path = os.path.join(REPO, ".github", "workflows", "ci-test.yml")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "scripts/playwright_gated_tests.py" in content, "ci-test.yml must invoke the discovery script so every skip is named, not silent"


def test_a_new_gated_module_is_caught_by_the_discovery_not_missed():
    """Negative control: planting a new gated file must show up in discover() —
    proving the scan is live source inspection, not a cached/hardcoded list."""
    import tempfile

    mod = _load_discovery()
    with tempfile.TemporaryDirectory() as tmp:
        tests_dir = os.path.join(tmp, "tests")
        os.makedirs(tests_dir)
        planted = os.path.join(tests_dir, "test_a_planted_playwright_module.py")
        with open(planted, "w", encoding="utf-8") as f:
            f.write("import pytest\n" f'pw = pytest.{_MARKER}.sync_api")\n')
        old_repo = mod.REPO
        try:
            mod.REPO = tmp
            assert "test_a_planted_playwright_module.py" in mod.discover()
        finally:
            mod.REPO = old_repo


def test_a_non_gated_module_is_not_swept_in_negative_control():
    """The flip side: a test file that does NOT use the playwright guard must
    never be swept into the set — proves the marker match isn't over-broad."""
    import tempfile

    mod = _load_discovery()
    with tempfile.TemporaryDirectory() as tmp:
        tests_dir = os.path.join(tmp, "tests")
        os.makedirs(tests_dir)
        plain = os.path.join(tests_dir, "test_a_plain_module.py")
        with open(plain, "w", encoding="utf-8") as f:
            f.write("def test_nothing():\n    assert True\n")
        old_repo = mod.REPO
        try:
            mod.REPO = tmp
            assert mod.discover() == []
        finally:
            mod.REPO = old_repo
