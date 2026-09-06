"""tests/test_wait_pr_green_conflicting_3653.py — #3653: a CONFLICTING PR must
not be reported as SWALLOWED-PUSH.

THE INCIDENT. `deploy/wait_pr_green.sh` diagnoses "zero checks attached past the
grace period" with `scripts/check_main_green.py --classify-sha`, which answers
"did any workflow run ever reference this sha". A PR that is CONFLICTING mints
zero check runs by construction (GitHub will not build a tree it cannot merge)
— the identical zero-checks signal a genuine event-swallow produces — but the
two states have OPPOSITE cures: a swallow needs close/reopen or a fresh push; a
conflicting PR needs `origin/main` merged into the branch. Observed twice
(#3595 lane; the driver's own 2026-09-05/06 census chain), where genuine
swallows and conflicts occurred the same night and had to be told apart by
hand because the script's one verdict string covered both.

THE FIX. `gh pr view --json mergeable,mergeStateStatus` is read BEFORE the
swallow classifier ever runs. `mergeable == "CONFLICTING"` short-circuits to a
distinct `CONFLICTING` verdict (exit 6) naming the merge as the cure; the
swallow classifier is never invoked in that state, so it cannot mislabel it.

HARNESS. Mirrors tests/test_wait_pr_green_swallow_3219.py's `gh` PATH stub,
extended to answer the new `gh pr view --json mergeable,mergeStateStatus`
query the fix adds. Real `deploy/wait_pr_green.sh`, real bash, no network.

BOTH DIRECTIONS ARE THE TEST, twice over:
  - a CONFLICTING PR gets the new verdict, not SWALLOWED-PUSH (the fix)
  - a genuine swallow STILL gets SWALLOWED-PUSH, unchanged (#3219's positive
    control retained — the fix must not blind the original detector)
"""

import json
import os
import stat
import subprocess
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "deploy", "wait_pr_green.sh")

FULL_SHA = "5213b364" + "a" * 32

EXPECTED_CHECK_NAMES = [
    "Collect + deploy-critical + format",
    "Full unit suite (pre-merge, issue 3025)",
]

# `gh` stub: serves `gh pr checks` from a scripted sequence (always empty here —
# the whole point is zero attached checks), `gh pr view --json headRefOid`,
# `gh pr view --json files`, and NOW `gh pr view --json mergeable,...`, whose
# payload the test controls via a file in the stub dir.
_GH_STUB = r"""#!/usr/bin/env bash
STUB_DIR="__STUB_DIR__"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  case "$*" in
    *mergeable*)  cat "${STUB_DIR}/mergeable_out.json" ;;
    *headRefOid*) echo "__SHA__" ;;
    *files*)      echo "deploy/wait_pr_green.sh" ;;
    *)            echo "UNSCRIPTED gh pr view: $*" >&2; exit 91 ;;
  esac
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "checks" ]; then
  echo "[]"
  exit 0
fi
echo "UNSCRIPTED gh: $*" >&2
exit 92
"""

_CLASSIFIER_STUB = r"""#!/usr/bin/env bash
echo "$@" >> "__STUB_DIR__/classify_argv"
cat "__STUB_DIR__/classify_out"
"""


def _make_env(mergeable_json, classifier_payload, sha=FULL_SHA):
    stub_dir = tempfile.mkdtemp()
    with open(os.path.join(stub_dir, "mergeable_out.json"), "w") as f:
        json.dump(mergeable_json, f)

    gh = os.path.join(stub_dir, "gh")
    with open(gh, "w") as f:
        f.write(_GH_STUB.replace("__STUB_DIR__", stub_dir).replace("__SHA__", sha))
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    with open(os.path.join(stub_dir, "classify_out"), "w") as f:
        f.write(classifier_payload)
    classifier = os.path.join(stub_dir, "classify")
    with open(classifier, "w") as f:
        f.write(_CLASSIFIER_STUB.replace("__STUB_DIR__", stub_dir))
    os.chmod(classifier, os.stat(classifier).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    env = dict(os.environ)
    env["PATH"] = stub_dir + os.pathsep + env.get("PATH", "")
    env["WAIT_PR_GREEN_CLASSIFY_CMD"] = classifier
    return env, stub_dir


def _run(env, *extra, interval="0", timeout="30"):
    return subprocess.run(
        ["bash", _SCRIPT, "3215", "--interval", interval, "--timeout", timeout, "--zero-check-grace", "0", *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


SWALLOWED = json.dumps({"state": "swallowed", "reason": "no workflow run of any kind references head_sha"})
CONFLICTING_MERGEABLE = {"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}
MERGEABLE_MERGEABLE = {"mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED"}


# ── Direction 1: CONFLICTING gets its own verdict, not SWALLOWED-PUSH ─────────


def test_conflicting_pr_is_not_reported_as_swallowed_push():
    """PRE-FIX THIS FAILED: a CONFLICTING PR (zero checks by construction) was
    diagnosed by the swallow classifier and printed SWALLOWED-PUSH."""
    env, _ = _make_env(CONFLICTING_MERGEABLE, SWALLOWED)
    r = _run(env)
    out = r.stdout + r.stderr
    assert "SWALLOWED-PUSH" not in out, out
    assert "CONFLICTING" in out, out


def test_conflicting_pr_names_the_merge_as_the_cure():
    env, _ = _make_env(CONFLICTING_MERGEABLE, SWALLOWED)
    r = _run(env)
    assert "merge origin/main" in r.stdout, r.stdout
    # The swallow function's own 3-rung ladder (`1. close/reopen the PR`, `2.
    # supersede-PR`, `3. integration train`) must not be printed here — a
    # mention that close/reopen CANNOT fix this is fine (and expected); the
    # ladder itself, keyed on its unique "supersede-PR" rung, is not.
    assert "supersede-PR" not in r.stdout, "the swallow ladder must not be printed for a CONFLICTING PR"


def test_conflicting_pr_gets_a_distinct_exit_code():
    """6 must not collide with the swallow code (5) or the plain-fail/timeout
    code (1) — a caller branching on exit code needs to tell them apart."""
    env, _ = _make_env(CONFLICTING_MERGEABLE, SWALLOWED)
    r = _run(env)
    assert r.returncode == 6, f"expected exit 6 for CONFLICTING, got {r.returncode}\n{r.stdout}{r.stderr}"


def test_conflicting_pr_never_invokes_the_swallow_classifier():
    """The swallow classifier must not even run in this state — if it did, it
    would have no way to know the PR is conflicting and would say swallow."""
    env, stub_dir = _make_env(CONFLICTING_MERGEABLE, SWALLOWED)
    _run(env)
    assert not os.path.exists(
        os.path.join(stub_dir, "classify_argv")
    ), "the swallow classifier ran even though the CONFLICTING state was already known"


# ── Direction 2 (retained positive control): a genuine swallow is unaffected ──


def test_genuine_swallow_still_reports_swallowed_push():
    """The fix must not blind the original #3219 detector: a PR that is
    MERGEABLE (not conflicting) with zero attached checks is still a real
    swallow candidate and must still get SWALLOWED-PUSH at exit 5."""
    env, _ = _make_env(MERGEABLE_MERGEABLE, SWALLOWED)
    r = _run(env)
    out = r.stdout + r.stderr
    assert r.returncode == 5, f"expected the swallow code 5, got {r.returncode}\n{out}"
    assert "SWALLOWED-PUSH" in out, out
    assert "CONFLICTING" not in out, out


def test_unreadable_mergeable_state_degrades_to_the_swallow_path_not_a_manufactured_conflict():
    """An unreadable/absent mergeable field (old `gh`, a transient failure) must
    fall through to the pre-existing swallow diagnosis, never manufacture a
    false CONFLICTING verdict — same fail-closed discipline as the swallow
    classifier's own "unparseable output never manufactures a swallow" rule."""
    env, _ = _make_env({}, SWALLOWED)
    r = _run(env)
    out = r.stdout + r.stderr
    assert "CONFLICTING" not in out, out
    assert r.returncode == 5, out


# ── The pure discriminator, sourced directly ──────────────────────────────────

_SOURCE_HARNESS = f"""
source '{_SCRIPT}' --source-only
conflicting_verdict "$1"
echo "RC=$?"
"""


def _conflicting(payload):
    return subprocess.run(["bash", "-c", _SOURCE_HARNESS, "bash", json.dumps(payload)], capture_output=True, text=True)


def test_pure_discriminator_returns_6_only_for_conflicting():
    assert "RC=6" in _conflicting(CONFLICTING_MERGEABLE).stdout
    for other in (MERGEABLE_MERGEABLE, {}, {"mergeable": "UNKNOWN"}):
        r = _conflicting(other)
        assert "RC=0" in r.stdout, other
        assert "CONFLICTING" not in r.stdout, other
