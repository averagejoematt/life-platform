"""tests/test_wait_pr_green_cancel_diagnosis_3678.py — #3678 acceptance box 3,
surfaced where a driver actually reads it: `deploy/wait_pr_green.sh`.

A `cancel`-bucket PR check previously printed only `NONGREEN <name> CANCELLED` —
identical text whether GitHub evicted the job from a `cancel-in-progress`
concurrency group (a non-event; the next push's run replaces it) or a job's own
duration hit its configured `timeout-minutes` ceiling (a defect: raise/split the
ceiling, a re-run buys nothing). #3530 built exactly this discriminator for a
CI/CD ROLLUP; this is its sibling for a single PR check.

Zero new `gh` calls: `gh pr checks --json` already returns `startedAt`/
`completedAt` per check (proven live against PR #3680, 2026-09-07), the same two
timestamps the run-level discriminator reads — so the enrichment stays inside
`evaluate_checks_json`, the function `_no_gh_path()` proves never shells out to
`gh`. The only subprocess it adds is `python3 scripts/ci_run_verdicts.py`, which
reads this repo's own workflow YAML off local disk.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "deploy", "wait_pr_green.sh")
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import ci_job_timeouts as cjt  # noqa: E402

_FAST_LANE = "Collect + deploy-critical + format"
_FAST_LANE_CEILING_MINUTES = cjt.timeout_minutes_by_job_name()[_FAST_LANE]


def _write_fixture(checks):
    fd, path = tempfile.mkstemp(suffix=".json", dir=tempfile.gettempdir())
    with os.fdopen(fd, "w") as f:
        json.dump(checks, f)
    return path


def _no_gh_path():
    """Same proof `tests/test_wait_pr_green.py` uses: a `gh` stub that hard-fails
    if ever invoked, so a passing test here proves zero `gh` calls, not merely
    that none happened to fire."""
    stub_dir = tempfile.mkdtemp()
    stub = os.path.join(stub_dir, "gh")
    with open(stub, "w") as f:
        f.write('#!/usr/bin/env bash\necho "GH_WAS_CALLED $*" >&2\nexit 97\n')
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub_dir + os.pathsep + os.environ.get("PATH", "")


def _run(args, path_override=None):
    env = dict(os.environ)
    if path_override:
        env["PATH"] = path_override
    return subprocess.run(["bash", _SCRIPT] + args, capture_output=True, text=True, timeout=30, env=env)


def _cancelled_check(name, started_at, completed_at):
    return {"name": name, "state": "CANCELLED", "bucket": "cancel", "startedAt": started_at, "completedAt": completed_at}


def _baseline_pass(names):
    return [{"name": n, "state": "SUCCESS", "bucket": "pass"} for n in names]


def test_a_check_cancelled_at_its_own_ceiling_is_diagnosed_as_timeout():
    """MUST-FAIL PROOF's positive companion: this is the LIVE incident shape —
    22s over a 15m ceiling — reproduced at whatever ceiling the repo currently
    declares (`_FAST_LANE_CEILING_MINUTES`), so the test tracks #3678's own fix
    rather than pinning a stale number."""
    checks = [
        _cancelled_check(
            _FAST_LANE,
            "2026-09-07T18:00:00Z",
            f"2026-09-07T{18 + (_FAST_LANE_CEILING_MINUTES // 60):02d}:{int(_FAST_LANE_CEILING_MINUTES % 60):02d}:22Z",
        )
    ]
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive", "--expect", _FAST_LANE], path_override=_no_gh_path())
    assert p.returncode == 1, p.stdout + p.stderr
    assert f"NONGREEN {_FAST_LANE} CANCELLED" in p.stdout
    assert f"CANCEL-DIAGNOSIS {_FAST_LANE}: TIMEOUT" in p.stdout, p.stdout
    assert "GH_WAS_CALLED" not in p.stderr, "the diagnosis must never shell out to gh"


def test_a_check_cancelled_seconds_in_is_diagnosed_as_superseded():
    checks = [_cancelled_check(_FAST_LANE, "2026-09-07T18:00:00Z", "2026-09-07T18:00:08Z")]
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive", "--expect", _FAST_LANE], path_override=_no_gh_path())
    assert p.returncode == 1, p.stdout + p.stderr
    assert f"NONGREEN {_FAST_LANE} CANCELLED" in p.stdout
    assert f"CANCEL-DIAGNOSIS {_FAST_LANE}: SUPERSEDED" in p.stdout, p.stdout
    assert "GH_WAS_CALLED" not in p.stderr


def test_an_unregistered_check_name_diagnoses_indeterminate_never_crashes():
    checks = [_cancelled_check("A check with no declared timeout-minutes anywhere", "2026-09-07T18:00:00Z", "2026-09-07T18:20:00Z")]
    path = _write_fixture(checks)
    p = _run(
        ["--fixture", path, "--no-derive", "--expect", "A check with no declared timeout-minutes anywhere"], path_override=_no_gh_path()
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "CANCEL-DIAGNOSIS A check with no declared timeout-minutes anywhere: INDETERMINATE" in p.stdout


def test_a_fail_bucket_check_gets_no_cancel_diagnosis_line():
    """Enrichment is scoped to `bucket == cancel` only — an ordinary failing
    check must not sprout an unrelated diagnosis line."""
    checks = [{"name": _FAST_LANE, "state": "FAILURE", "bucket": "fail"}]
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive", "--expect", _FAST_LANE], path_override=_no_gh_path())
    assert p.returncode == 1, p.stdout + p.stderr
    assert "CANCEL-DIAGNOSIS" not in p.stdout


def test_the_verdict_and_exit_code_are_unchanged_by_the_diagnosis_line():
    """#3678 is enrichment, not a behaviour change: a green watch stays green,
    and a cancelled-and-expected check still fails the watch exactly as before —
    the diagnosis explains WHY, it never overrides the verdict."""
    baseline = _baseline_pass(
        [
            "Full unit suite (pre-merge, issue 3025)",
            "API-before-frontend sequencing check (#2831)",
            "gitleaks (PR commit range only, not full history)",
            "CodeQL analysis (python)",
            "CodeQL analysis (javascript-typescript)",
        ]
    )
    checks = baseline + [_cancelled_check(_FAST_LANE, "2026-09-07T18:00:00Z", "2026-09-07T18:00:05Z")]
    path = _write_fixture(checks)
    p = _run(["--fixture", path, "--no-derive"], path_override=_no_gh_path())
    assert p.returncode == 1, p.stdout + p.stderr
    assert "VERDICT FAIL" in p.stdout
