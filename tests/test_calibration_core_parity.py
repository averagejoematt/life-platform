"""#1396 — the extraction is enforced, not asserted.

`oss/calibration-core/` is the open, standalone copy of the calibration grader that
produces the numbers on /method/calibration. An extraction that is allowed to drift
is worse than no extraction at all: a third party would grade their own LLM coach
with a scorer that no longer matches the one this platform publishes, and the whole
"same scorecard my coaches get" claim would quietly become false.

So three copies exist and all three are pinned to one fixture
(`oss/calibration-core/vectors/calibration_vectors.json`, generated from the
deployed grader by `scripts/gen_calibration_vectors.py`):

  1. `lambdas/calibration_core.py`                    — deployed, the AUTHORITY
  2. `oss/calibration-core/src/calibration_core.py`   — the extracted package
  3. `oss/calibration-core/js/calibration-core.js`    — the browser port,
     vendored byte-for-byte to `site/assets/js/calibration-core.js`

This module covers 1 <-> 2 and the 3-is-vendored-unmodified invariant. The JS side
of the numeric contract is `tests/js/calibration_core.test.mjs` (run by `node --test`
in the v4 gate) and `oss/calibration-core/tests/calibration-core.test.mjs`.

ADR-105: exact equality, never a tolerance. Every value the grader reports is
already rounded at the source, so "close enough" would be hiding a real defect.
"""

import importlib.util
import json
import math
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import calibration_core as platform_core  # noqa: E402  — the deployed grader

OSS_DIR = os.path.join(ROOT, "oss", "calibration-core")
OSS_PY = os.path.join(OSS_DIR, "src", "calibration_core.py")
OSS_JS = os.path.join(OSS_DIR, "js", "calibration-core.js")
SITE_JS = os.path.join(ROOT, "site", "assets", "js", "calibration-core.js")
VECTORS_PATH = os.path.join(OSS_DIR, "vectors", "calibration_vectors.json")


def _load_oss():
    """Load the extracted package by path — both modules are named calibration_core."""
    spec = importlib.util.spec_from_file_location("oss_calibration_core_under_test", OSS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


oss_core = _load_oss()

with open(VECTORS_PATH, "r", encoding="utf-8") as _fh:
    VECTORS = json.load(_fh)


def _exact(a, b, ctx=""):
    """Structural equality with bit-exact floats — 0.2059 must not pass as 0.20590001."""
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and math.isnan(a):
            assert isinstance(b, float) and math.isnan(b), ctx
            return
        assert a == b, f"{ctx}: {a!r} != {b!r}"
        return
    if isinstance(a, dict):
        assert isinstance(b, dict), f"{ctx}: {type(b)} is not a dict"
        assert set(a) == set(b), f"{ctx}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            _exact(a[k], b[k], f"{ctx}.{k}")
        return
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{ctx}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _exact(x, y, f"{ctx}[{i}]")
        return
    assert a == b and type(a) is type(b), f"{ctx}: {a!r} != {b!r}"


# ── 1 <-> 2: the extracted package vs. the deployed grader ────────────────


@pytest.mark.parametrize("case", VECTORS["core_cases"], ids=lambda c: c["id"])
def test_extracted_package_matches_platform_score_pairs(case):
    pairs = [tuple(p) for p in case["pairs"]]
    platform = platform_core.score_pairs(pairs, n_bins=case["n_bins"])
    extracted = oss_core.score_pairs(pairs, n_bins=case["n_bins"])
    _exact(extracted, platform, f"{case['id']} (package vs platform)")
    _exact(platform, case["expected"], f"{case['id']} (platform vs committed vector)")


@pytest.mark.parametrize("case", VECTORS["confidence_cases"], ids=lambda c: repr(c["input"]))
def test_extracted_package_matches_platform_normalize_confidence(case):
    _exact(oss_core.normalize_confidence(case["input"]), platform_core.normalize_confidence(case["input"]), repr(case["input"]))


@pytest.mark.parametrize("case", VECTORS["outcome_cases"], ids=lambda c: repr(c["input"]))
def test_extracted_package_matches_platform_outcome_to_binary(case):
    assert oss_core.outcome_to_binary(case["input"]) == platform_core.outcome_to_binary(case["input"])


@pytest.mark.parametrize("case", VECTORS["record_cases"], ids=lambda c: c["id"])
def test_extracted_package_matches_platform_record_extractors(case):
    name = {
        "prediction_records": "pairs_from_prediction_records",
        "calibration_rows": "pairs_from_calibration_rows",
        "forecast_resolution_rows": "pairs_from_forecast_resolution_rows",
    }[case["kind"]]
    platform = [list(p) for p in getattr(platform_core, name)(case["records"])]
    extracted = [list(p) for p in getattr(oss_core, name)(case["records"])]
    _exact(extracted, platform, case["id"])
    _exact(platform, case["expected_pairs"], f"{case['id']} (committed vector)")


def test_every_public_platform_symbol_survives_the_extraction():
    """A function the platform grades with but the package lacks is a silent hole."""
    missing = [
        name
        for name in dir(platform_core)
        if not name.startswith("_") and callable(getattr(platform_core, name)) and not hasattr(oss_core, name)
    ]
    assert missing == [], f"extracted package is missing platform grader symbols: {missing}"
    assert platform_core.WORD_CONFIDENCE == oss_core.WORD_CONFIDENCE


# ── 3: the browser port is vendored, not forked ──────────────────────────


def test_site_js_is_a_byte_identical_vendored_copy():
    """site/assets/js/calibration-core.js must be the package file, unedited.

    Editing the vendored copy in place is how a hosted tool silently stops
    agreeing with the package it advertises. Re-vendor instead::

        cp oss/calibration-core/js/calibration-core.js site/assets/js/calibration-core.js
    """
    with open(OSS_JS, "rb") as fh:
        pkg = fh.read()
    with open(SITE_JS, "rb") as fh:
        vendored = fh.read()
    assert vendored == pkg, (
        "site/assets/js/calibration-core.js has drifted from oss/calibration-core/js/calibration-core.js — "
        "re-vendor with: cp oss/calibration-core/js/calibration-core.js site/assets/js/calibration-core.js"
    )


# ── the fixture itself ───────────────────────────────────────────────────


def test_vectors_file_is_regenerable():
    """The committed fixture must be exactly what the generator produces today.

    If the platform grader's behaviour changes, this goes red and forces the
    change to be re-published through the open package rather than diverging
    from it in silence.
    """
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "gen_calibration_vectors.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    diff = subprocess.run(["git", "diff", "--stat", "--", VECTORS_PATH], capture_output=True, text=True, cwd=ROOT)
    assert diff.stdout.strip() == "", (
        "oss/calibration-core/vectors/calibration_vectors.json is stale against the platform grader — "
        f"run `python3 scripts/gen_calibration_vectors.py` and commit the result.\n{diff.stdout}"
    )


def test_extracted_package_has_no_platform_imports():
    """The whole point of the extraction: it must stand alone.

    No `stats_core`, no `boto3`, no relative imports into this repo — a third
    party clones the package directory and it runs.
    """
    with open(OSS_PY, "r", encoding="utf-8") as fh:
        src = fh.read()
    banned = ["import stats_core", "import boto3", "from lambdas", "import constants", "import bedrock_client"]
    for token in banned:
        assert token not in src, f"extracted package must not depend on the platform: found {token!r}"


def test_demo_datasets_carry_provenance_and_no_private_surface():
    """The demo ledger is the ALREADY-PUBLIC surface only, and says so.

    The repo is public. A demo dataset is exactly the place a private field
    would leak by accident, so every file states its source and whether it is
    real or synthetic, and nothing may carry a chronological age.
    """
    demo_dir = os.path.join(OSS_DIR, "demo")
    names = sorted(n for n in os.listdir(demo_dir) if n.endswith(".json"))
    assert names, "the package must ship at least one demo dataset"
    for name in names:
        with open(os.path.join(demo_dir, name), "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        prov = payload.get("provenance")
        assert isinstance(prov, dict), f"{name}: missing provenance block"
        assert isinstance(prov.get("synthetic"), bool), f"{name}: provenance must say synthetic true/false"
        if not prov["synthetic"]:
            assert str(prov.get("source_url", "")).startswith(
                "https://averagejoematt.com/api/"
            ), f"{name}: a non-synthetic demo dataset must cite the public endpoint it came from"
        blob = json.dumps(payload).lower()
        for forbidden in ("chronological_age", "date_of_birth", "birthdate"):
            assert forbidden not in blob, f"{name}: demo dataset must never carry {forbidden}"


def test_worked_example_scorecard_is_not_stale():
    """The synthetic demo ships its own expected scorecard — pin it to the scorer.

    The tool page uses this ledger as its first-paint walkthrough, and the
    package README quotes its numbers. If the scorer moves and the committed
    scorecard doesn't, the README starts lying.
    """
    with open(os.path.join(OSS_DIR, "demo", "worked_example.json"), "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    pairs = platform_core.pairs_from_prediction_records([{"confidence": r["confidence"], "status": r["outcome"]} for r in payload["rows"]])
    _exact(platform_core.score_pairs(pairs), payload["expected_scorecard"], "worked_example.expected_scorecard")


def test_site_demo_artifact_is_derived_from_the_package_demos():
    """site/data/calibration_demo.json must be regenerable from oss/calibration-core/demo/.

    The hosted tool and the open package have to be teaching the SAME ledgers —
    a site artifact that drifts would demo a schema the package doesn't ship.
    Regenerate with `python3 scripts/v4_build_grade_your_coach.py`.
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location(
        "v4_build_grade_your_coach_under_test", os.path.join(ROOT, "scripts", "v4_build_grade_your_coach.py")
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    with open(os.path.join(ROOT, "site", "data", "calibration_demo.json"), "r", encoding="utf-8") as fh:
        committed = json.load(fh)
    assert committed == builder.build_demo_payload(), (
        "site/data/calibration_demo.json is stale against oss/calibration-core/demo/ — "
        "run `python3 scripts/v4_build_grade_your_coach.py` and commit the result"
    )


def test_the_tool_page_ships_the_hooks_its_controller_binds():
    """A generated page whose ids drift from the controller renders a dead tool.

    Cheap structural pin: every element id grade_your_coach.js looks up must
    exist in the committed HTML, and the page must load the module.
    """
    page = os.path.join(ROOT, "site", "method", "grade-your-coach", "index.html")
    with open(page, "r", encoding="utf-8") as fh:
        html = fh.read()
    for hook in ("gyc-input", "gyc-readout", "gyc-grade", "gyc-clear", "gyc-demo-matthew", "gyc-demo-example", "gyc-prov"):
        assert f'id="{hook}"' in html, f"/method/grade-your-coach/ is missing the #{hook} hook its controller binds"
    assert "/assets/js/grade_your_coach.js" in html, "the tool page must load its controller module"

    with open(os.path.join(ROOT, "site", "assets", "js", "grade_your_coach.js"), "r", encoding="utf-8") as fh:
        controller = fh.read()
    assert 'from "/assets/js/calibration-core.js"' in controller, "the controller must import the vendored scorer, not reimplement it"
    # The privacy promise the page makes in its own copy has to be structurally true:
    # exactly one network call, and it is the static demo artifact. Comment lines are
    # stripped first so prose about fetch() doesn't count as a call.
    code = "\n".join(ln for ln in controller.splitlines() if not ln.lstrip().startswith("//"))
    calls = code.count("fetch(")
    assert calls == 1 and "fetch(DEMO_URL" in code, (
        f"grade_your_coach.js must make exactly one network call — fetch(DEMO_URL) — but found {calls}. "
        "The page promises the pasted ledger never leaves the browser; a second request would break that."
    )
    for leak in ("XMLHttpRequest", "navigator.sendBeacon", "new WebSocket", "new EventSource"):
        assert leak not in code, f"grade_your_coach.js must not use {leak} — the pasted ledger never leaves the page"
