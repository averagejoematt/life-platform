"""#2978 — confirm-before-fail: the deploy-race class's one primitive.

The shape-(a) record: five CLOSED per-symptom issues (#1526 #1931 #1917 #2051
#1911) read as class closure while the measured rate worsened to 1 per 1.5 days
— smoke/visual-QA measuring the edge mid-invalidation, a cold Lambda's first
hit, an asset race, an empty first readout, each redding (and auto-rolling-back)
a green deploy. The structural answer is the pattern the reader-truth gate
already proved (#2741): a deterministic FAIL only gates after it REPRODUCES on
one re-probe — and every confirmed transient is COUNTED AND PRINTED (ADR-104),
so the race rate stays measurable for this issue's 30-day re-measure.

Three surfaces, all mutation-proved here:
  - tests/visual_qa.confirm_before_fail (pure function, sleeper injected);
  - deploy/lib/resilient_curl.sh::smoke_confirm (real bash, sleep stubbed);
  - scripts/incident_log_patterns.py's sub-shape split (the umbrella's rate can
    now be measured without the semantic-oracle rows inflating it).
"""

import os
import subprocess
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_TESTS_DIR)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import visual_qa  # noqa: E402  (playwright import is lazy — safe headless)
from incident_log_patterns import CLASSES  # noqa: E402

_LIB = os.path.join(_REPO, "deploy", "lib", "resilient_curl.sh")


def _no_sleep(_):
    pass


# ── the pure primitive ────────────────────────────────────────────────────────


def test_pass_result_returns_untouched_and_never_reprobes():
    calls = []
    first = {"status": "PASS", "path": "/x/", "issues": [], "warnings": []}
    out = visual_qa.confirm_before_fail(first, lambda: calls.append(1), sleeper=_no_sleep)
    assert out is first and calls == []


def test_transient_fail_becomes_pass_with_visible_evidence():
    first = {"status": "FAIL", "path": "/x/", "issues": ["3 broken API call(s): 500 /api/vitals"], "warnings": []}
    second = {"status": "PASS", "path": "/x/", "issues": [], "warnings": []}
    slept = []
    out = visual_qa.confirm_before_fail(first, lambda: second, sleeper=slept.append)
    assert out["status"] == "PASS"
    assert out.get("confirmed_transient") is True
    # ADR-104: the transient is visible, and carries the first probe's evidence
    assert any("confirmed-transient" in w and "/api/vitals" in w for w in out["warnings"])
    assert slept, "the confirm must wait a bounded delay before re-probing"


def test_reproduced_fail_still_fails_and_says_it_reproduced():
    first = {"status": "FAIL", "path": "/x/", "issues": ["broken bind"], "warnings": []}
    second = {"status": "FAIL", "path": "/x/", "issues": ["broken bind"], "warnings": []}
    out = visual_qa.confirm_before_fail(first, lambda: second, sleeper=_no_sleep)
    assert out["status"] == "FAIL", "a genuinely broken deploy must still fail (#2978 mutation proof)"
    assert any("reproduced" in i for i in out["issues"])


def test_confirm_disabled_keeps_the_original_fail():
    calls = []
    first = {"status": "FAIL", "path": "/x/", "issues": ["broken"], "warnings": []}
    out = visual_qa.confirm_before_fail(first, lambda: calls.append(1), sleeper=_no_sleep, attempts=0)
    assert out is first and calls == []


# ── the bash half (real bash, sleep stubbed — no wall clock) ──────────────────


def _bash(script):
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


def _harness(body):
    return f"""
set -uo pipefail
export SMOKE_CONFIRM_LOG=$(mktemp)
source '{_LIB}'
sleep() {{ :; }}   # stub — the delay is behavior under test elsewhere, not here
{body}
"""


def test_smoke_confirm_passes_when_reprobe_passes_and_counts_it():
    p = _bash(_harness("""
tries=0
probe() { tries=$((tries+1)); [[ $tries -ge 2 ]]; }
probe || smoke_confirm probe || { echo VERDICT=fail; exit 0; }
echo "VERDICT=pass count=$(smoke_confirm_transient_count)"
"""))
    assert "VERDICT=pass count=1" in p.stdout, p.stdout + p.stderr


def test_smoke_confirm_reproduced_failure_still_fails():
    p = _bash(_harness("""
probe() { return 1; }
probe || smoke_confirm probe || { echo "VERDICT=fail count=$(smoke_confirm_transient_count)"; exit 0; }
echo VERDICT=pass
"""))
    assert "VERDICT=fail count=0" in p.stdout, p.stdout + p.stderr


def test_smoke_confirm_disabled_never_confirms():
    p = _bash(_harness("""
export SMOKE_CONFIRM_ATTEMPTS=0
probe() { return 1; }
if smoke_confirm probe; then echo VERDICT=confirmed; else echo VERDICT=declined; fi
"""))
    assert "VERDICT=declined" in p.stdout, p.stdout + p.stderr


def test_smoke_script_wires_the_confirm_into_every_check_family():
    smoke = open(os.path.join(_REPO, "deploy", "smoke_test_site.sh"), encoding="utf-8").read()
    for probe in ("_probe_status", "_probe_redirect", "_probe_header"):
        assert f"smoke_confirm {probe}" in smoke, f"{probe} lost its #2978 confirm path"
    assert "smoke_confirm_transient_count" in smoke, "the transient count must reach the smoke summary (ADR-104)"


# ── the classifier split ──────────────────────────────────────────────────────


def test_incident_classifier_separates_the_two_sub_shapes():
    race_key = "QA false positive — deploy-race (#2978)"
    oracle_key = "QA false positive — semantic oracle (#2959)"
    assert race_key in CLASSES and oracle_key in CLASSES
    race_row = "site smoke red on a stale edge — invalidation race; auto-rollback reverted a healthy deploy"
    oracle_row = "reader-truth oracle raised a sanctioned content shape as a high finding; rubric miscalibration"
    assert any(k in race_row for k in CLASSES[race_key])
    assert not any(k in race_row for k in CLASSES[oracle_key])
    assert any(k in oracle_row for k in CLASSES[oracle_key])
    assert not any(k in oracle_row for k in CLASSES[race_key])
