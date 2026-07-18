"""tests/test_unred_main_1327.py — un-red main, structurally (#1327).

Replays the SDLC-review finding: over 100 main runs, 19 green / 38 failure /
43 cancelled — every sampled failure was ONE documented-transient Withings DLQ
message, the PLATFORM_FACTS hand literal redded main again two days after being
written up, and a wrap declared "main GREEN" over a failed run.

Three structural fixes, each pinned here offline (no AWS, no gh):
  1. I9 is transient-aware — a PRE-EXISTING DLQ message warns, a deploy-window
     message fails.
  2. The shared-fact truth test is discovery-first (no hand-literal bump per
     alarm PR).
  3. /wrap has a mechanical green-main gate (scripts/check_main_green.py) whose
     verdict logic skips cancelled/superseded runs.

Every test here FAILS on the pre-#1327 tree (missing symbols / old semantics).
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── 1. transient-aware DLQ split ─────────────────────────────────────────────
def test_dlq_preexisting_message_does_not_fail_the_deploy():
    """The 38-red class: one message from hours/days before the deploy is a
    transient (warn-lane), not a deploy failure."""
    ia = _load(os.path.join(_REPO, "tests", "test_integration_aws.py"), "ia_1327")
    now = 1_800_000_000.0
    six_hours_old = int((now - 6 * 3600) * 1000)
    fresh, stale = ia._dlq_split_fresh_stale([six_hours_old], now)
    assert fresh == 0 and stale == 1  # pre-existing → no red


def test_dlq_deploy_window_message_fails_the_deploy():
    """A message that arrived during/after the deploy is the deploy's problem."""
    ia = _load(os.path.join(_REPO, "tests", "test_integration_aws.py"), "ia_1327")
    now = 1_800_000_000.0
    five_min_old = int((now - 300) * 1000)
    six_hours_old = int((now - 6 * 3600) * 1000)
    fresh, stale = ia._dlq_split_fresh_stale([five_min_old, six_hours_old], now)
    assert fresh == 1 and stale == 1  # the fresh one reds; the old one only warns


def test_ci_invokes_the_transient_aware_i9():
    """ci-cd.yml must call the NEW node id — a renamed test with a stale workflow
    reference reds the whole post-deploy job with a collection error (#781 class)."""
    with open(os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")) as f:
        wf = f.read()
    assert "test_i9_dlq_no_deploy_caused_messages" in wf
    assert "test_i9_dlq_empty" not in wf


# ── 2. discovery-first shared facts ──────────────────────────────────────────
def test_shared_fact_test_is_discovery_first():
    """The truth test must compare against _apply_auto_discovered facts, not the
    raw hand literal (the `assert 69 == 67` red-main class)."""
    with open(os.path.join(_REPO, "tests", "test_platform_stats_truth.py")) as f:
        src = f.read()
    assert "_apply_auto_discovered" in src, "shared-fact test still compares raw PLATFORM_FACTS literals"


# ── 3. the wrap green-main gate ──────────────────────────────────────────────
def _gate():
    return _load(os.path.join(_REPO, "scripts", "check_main_green.py"), "check_main_green")


def test_gate_verdict_skips_cancelled_superseded_runs():
    g = _gate()
    runs = [
        {"status": "completed", "conclusion": "cancelled", "headSha": "aaa111"},
        {"status": "in_progress", "conclusion": "", "headSha": "bbb222"},
        {"status": "completed", "conclusion": "success", "headSha": "ccc333"},
        {"status": "completed", "conclusion": "failure", "headSha": "ddd444"},
    ]
    conclusion, sha = g.latest_main_conclusion(runs)
    assert (conclusion, sha) == ("success", "ccc333")


def test_gate_verdict_surfaces_a_red_main():
    g = _gate()
    runs = [
        {"status": "completed", "conclusion": "failure", "headSha": "eee555"},
        {"status": "completed", "conclusion": "success", "headSha": "fff666"},
    ]
    conclusion, sha = g.latest_main_conclusion(runs)
    assert conclusion == "failure" and sha == "eee555"


def test_gate_verdict_none_when_nothing_finished():
    g = _gate()
    assert g.latest_main_conclusion([{"status": "in_progress", "conclusion": ""}]) == (None, None)


def test_wrap_skill_wires_the_gate():
    """The /wrap driver must actually run the gate — a script nobody invokes is
    not a gate."""
    with open(os.path.join(_REPO, ".claude", "commands", "wrap.md")) as f:
        wrap = f.read()
    assert "check_main_green.py" in wrap
    assert "**Main:**" in wrap
