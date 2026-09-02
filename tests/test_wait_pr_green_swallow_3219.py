"""tests/test_wait_pr_green_swallow_3219.py — #3219: the watcher must NAME a
swallowed push instead of polling it for thirty minutes.

THE INCIDENT (Session E, 2026-08-26 — twice, on two PRs, in one session):

    PR      head sha    observed              truth
    #3215   5213b364    `0/7 green` for 311s  actions/runs?head_sha=… total_count=0
    #3214   769905bd    `0/7 green` for 373s  same

Both were genuine event swallows. Both were recovered by close/reopen. In both
cases the discriminating fact — zero runs of ANY workflow at the FULL head sha —
was available on the first poll, and the operator only learned it by running the
swallow-check out of band. `0/7 green` at 30s and `0/7 green` at 300s render
identically, so nothing in the watcher's own output ever said "go look".

BOTH DIRECTIONS ARE THE TEST. A watcher that cried swallow on ordinary attach
latency would be worse than the bug, so `test_late_attaching_checks_*` is not a
nice-to-have — it is the other half of the claim. Same for
`test_unparseable_classifier_output_*`: a diagnosis that cannot be made degrades
to waiting, never to a manufactured swallow.

HARNESS. `gh` is shadowed by a PATH stub that serves a scripted sequence of `gh pr
checks` payloads (one per poll, last one repeating), and the classifier is
shadowed via `WAIT_PR_GREEN_CLASSIFY_CMD`. No network, no real `gh`, no real
`check_main_green.py` run — but the REAL `deploy/wait_pr_green.sh` poll loop,
under real bash, with real timing.
"""

import json
import os
import stat
import subprocess
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "deploy", "wait_pr_green.sh")

# A real-shaped 40-char sha. #3215's actual head, extended — the length is the
# point (a 7-char prefix returns an empty run list and self-confirms a swallow).
FULL_SHA = "5213b364" + "a" * 32

# NOT named `EXPECTED_CHECK_NAMES`: `gate_census._REGISTRY_NAME` matches that name and expands
# the binding entry-by-entry, so a list of check names called `EXPECTED_CHECK_NAMES` injects six
# phantom "gates" into the #2578 inventory. Caught by measuring this PR's own census
# delta — the same class of noise #3220 (landing alongside this) exists to stop.
EXPECTED_CHECK_NAMES = [
    "Collect + deploy-critical + format",
    "Full unit suite (pre-merge, issue 3025)",
    "API-before-frontend sequencing check (#2831)",
    "gitleaks (PR commit range only, not full history)",
    "CodeQL analysis (python)",
    "CodeQL analysis (javascript-typescript)",
]


def _all_green():
    return [{"name": n, "state": "SUCCESS", "bucket": "pass"} for n in EXPECTED_CHECK_NAMES]


def _partially_attached():
    """Three of six attached, two green one running — the "checks are here and
    working" state that must never read like the empty one."""
    return [
        {"name": EXPECTED_CHECK_NAMES[0], "state": "SUCCESS", "bucket": "pass"},
        {"name": EXPECTED_CHECK_NAMES[1], "state": "SUCCESS", "bucket": "pass"},
        {"name": EXPECTED_CHECK_NAMES[2], "state": "IN_PROGRESS", "bucket": "pending"},
    ]


_GH_STUB = r"""#!/usr/bin/env bash
# Scripted `gh` stub. `pr checks` serves $STUB_DIR/checks_<n>.json in order,
# repeating the last one forever. Anything unscripted is a loud failure.
STUB_DIR="__STUB_DIR__"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  case "$*" in
    *headRefOid*) echo "__SHA__" ;;
    *files*)      echo "deploy/wait_pr_green.sh" ;;
    *)            echo "UNSCRIPTED gh pr view: $*" >&2; exit 91 ;;
  esac
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "checks" ]; then
  n=0
  [ -f "${STUB_DIR}/poll_count" ] && n="$(cat "${STUB_DIR}/poll_count")"
  echo $((n + 1)) > "${STUB_DIR}/poll_count"
  f="${STUB_DIR}/checks_${n}.json"
  if [ ! -f "${f}" ]; then
    last=0
    while [ -f "${STUB_DIR}/checks_$((last + 1)).json" ]; do last=$((last + 1)); done
    f="${STUB_DIR}/checks_${last}.json"
  fi
  cat "${f}"
  exit 0
fi
echo "UNSCRIPTED gh: $*" >&2
exit 92
"""

_CLASSIFIER_STUB = r"""#!/usr/bin/env bash
# Records the argv it was handed (so a test can assert the FULL sha reached it)
# and emits a canned classifier payload.
echo "$@" >> "__STUB_DIR__/classify_argv"
cat "__STUB_DIR__/classify_out"
"""


def _make_env(check_sequence, classifier_payload="", sha=FULL_SHA):
    """Returns (env, stub_dir). `check_sequence` is a list of `gh pr checks`
    payloads, served one per poll."""
    stub_dir = tempfile.mkdtemp()
    for i, checks in enumerate(check_sequence):
        with open(os.path.join(stub_dir, f"checks_{i}.json"), "w") as f:
            json.dump(checks, f)

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


# ── #3455: a scripted fake clock, decoupled from real wall-clock scheduling ──
#
# THE INCIDENT. Main run 33605871465 (2026-09-02) red-mained the docs-only
# #3454 merge: `test_indeterminate_is_named_and_is_not_a_swallow` simulates a
# 1s watcher budget, but `deploy/wait_pr_green.sh`'s poll loop used to read
# elapsed time via two real `date +%s` calls a loop-iteration apart. `date +%s`
# has 1-SECOND granularity, so under a loaded runner (the same job logged 2012s
# against its own 1950s duration budget that night) the fork+exec overhead of
# the SECOND call alone can straddle a whole-second boundary against the
# FIRST — making `elapsed >= timeout` true on the very first loop iteration,
# before the zero-check diagnosis these tests assert on ever runs. A bigger
# timeout constant only makes that race rarer, never closes it (the #3206
# time-dependent-gate-outside-its-window family) — so the script now reads
# elapsed time through an overridable `WAIT_PR_GREEN_TIME_CMD` (see
# `deploy/wait_pr_green.sh`'s `TIME_CMD`), and this stub scripts the EXACT
# sequence of values it returns, one per call, repeating the last forever.
# That decouples the assertion from real process-scheduling jitter entirely —
# it no longer matters how long the real `gh`/`jq`/classifier subprocess calls
# actually take.
_TIME_STUB = r"""#!/usr/bin/env bash
STUB_DIR="__STUB_DIR__"
n=0
[ -f "${STUB_DIR}/clock_count" ] && n="$(cat "${STUB_DIR}/clock_count")"
echo $((n + 1)) > "${STUB_DIR}/clock_count"
# #3455 proof hook: on request, stall for real between two adjacent clock
# reads — the exact gap that raced in the incident — to prove the SCRIPTED
# value (not real elapsed wall-clock time) is what the caller sees.
if [ -n "${WAIT_PR_GREEN_TEST_STALL_S:-}" ] && [ "$((n + 1))" -eq "${WAIT_PR_GREEN_TEST_STALL_AT_CALL:-2}" ]; then
  sleep "${WAIT_PR_GREEN_TEST_STALL_S}"
fi
f="${STUB_DIR}/clock_seq"
total=$(wc -l < "${f}")
if [ "${n}" -ge "${total}" ]; then
  idx="${total}"
else
  idx=$((n + 1))
fi
sed -n "${idx}p" "${f}"
"""


def _with_fake_clock(env, stub_dir, seq):
    """Wires the #3455 fake clock into `env`: the script's `${TIME_CMD}` calls
    will return exactly `seq[0], seq[1], ..., seq[-1], seq[-1], ...` regardless
    of real elapsed wall-clock time between calls. Mutates and returns `env`."""
    with open(os.path.join(stub_dir, "clock_seq"), "w") as f:
        f.write("\n".join(str(v) for v in seq) + "\n")
    clock = os.path.join(stub_dir, "fakeclock")
    with open(clock, "w") as f:
        f.write(_TIME_STUB.replace("__STUB_DIR__", stub_dir))
    os.chmod(clock, os.stat(clock).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env["WAIT_PR_GREEN_TIME_CMD"] = clock
    return env


def _run(env, *extra, interval="1", timeout="1"):
    """Runs the REAL script with the real poll loop, at second-scale budgets.

    The budgets are deliberately tiny (`tests/test_duration_budget_ratchet.py` —
    the unit suite is already over its 1500s budget, so a watcher test that
    actually waits out a 30-minute timeout is not affordable). Nothing about the
    logic under test is timing-sensitive beyond the grace comparison, which is
    exercised in both directions here: grace 0 (diagnose on the first empty poll)
    and grace 60 (far beyond the run's whole life)."""
    return subprocess.run(
        ["bash", _SCRIPT, "3215", "--interval", interval, "--timeout", timeout, *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


SWALLOWED = json.dumps({"state": "swallowed", "reason": "no workflow run of any kind references head_sha"})
PATH_SKIP = json.dumps({"state": "path-filter-skip", "reason": "the diff touches none of ci-cd.yml's `paths:` filter"})
BOT_PUSH = json.dumps({"state": "bot-push-no-dispatch", "reason": "HEAD was pushed by github-actions[bot]"})
INDETERMINATE = json.dumps({"state": "indeterminate", "reason": "could not read the commit's changed files"})


# ── Direction 1: a real swallow is NAMED, with its own exit code ──────────────


def test_zero_runs_past_the_grace_reports_swallowed_with_exit_5():
    """PRE-FIX THIS FAILED: the script exited 1 after the full timeout with
    `0/6 green` repeated, and the word "swallow" appeared nowhere except a
    parenthetical NOTE that only prints once polling has already stopped."""
    env, _ = _make_env([[]], SWALLOWED)
    r = _run(env, "--zero-check-grace", "0", timeout="30")
    out = r.stdout + r.stderr
    assert r.returncode == 5, f"expected the distinct swallow code 5, got {r.returncode}\n{out}"
    assert "SWALLOWED-PUSH" in out, out
    assert "no workflow run of any kind" in out


def test_swallow_verdict_prints_the_full_recovery_ladder():
    env, _ = _make_env([[]], SWALLOWED)
    r = _run(env, "--zero-check-grace", "0", timeout="30")
    out = r.stdout
    assert "close/reopen" in out, out
    assert "supersede-PR" in out
    assert "integration train" in out


def test_swallow_code_is_not_conflated_with_red_or_timeout():
    """1 already means "a check failed, or the timeout elapsed". A swallow needs a
    different ACTION (the recovery ladder, not fix-and-re-push), so it needs a
    different code — this pins that they cannot collide."""
    env, _ = _make_env([[]], SWALLOWED)
    swallow = _run(env, "--zero-check-grace", "0", timeout="30")

    red = [{"name": EXPECTED_CHECK_NAMES[0], "state": "FAILURE", "bucket": "fail"}] + [
        {"name": n, "state": "SUCCESS", "bucket": "pass"} for n in EXPECTED_CHECK_NAMES[1:]
    ]
    env2, _ = _make_env([red], SWALLOWED)
    failed = _run(env2, "--zero-check-grace", "0", timeout="30")

    assert swallow.returncode == 5
    assert failed.returncode == 1
    assert swallow.returncode != failed.returncode


def test_the_classifier_is_handed_the_full_40_char_sha_never_a_prefix():
    """Failure mode #1 in this script's own header: a short-sha runs query returns
    empty, which reads as "no runs" and SELF-CONFIRMS the bug being diagnosed."""
    env, stub_dir = _make_env([[]], SWALLOWED)
    _run(env, "--zero-check-grace", "0", timeout="30")
    argv = open(os.path.join(stub_dir, "classify_argv")).read().strip()
    assert argv == FULL_SHA, f"classifier got {argv!r}"
    assert len(argv) == 40


# ── Direction 2: normal attach latency must NEVER read as a swallow ───────────


def test_late_attaching_checks_still_proceed_and_are_not_called_swallowed():
    """The other half of the claim, and the more important one. Checks legitimately
    take time to attach; a watcher that bailed on the first empty poll would be
    worse than the bug #3219 fixes."""
    env, _ = _make_env([[], [], _partially_attached(), _all_green()], SWALLOWED)
    r = _run(env, "--zero-check-grace", "60", interval="0", timeout="30")  # grace far beyond this run's life
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"a late attach must still go green\n{out}"
    assert "SWALLOWED" not in out, out
    assert "All 6 expected checks are GREEN" in r.stdout


def test_diagnosis_never_runs_once_any_check_has_attached():
    """`saw_attach` latches. A PR whose checks arrived and then went quiet is a
    different animal — misdiagnosing it as a swallow would send the operator to
    close/reopen a PR whose run is mid-flight."""
    env, stub_dir = _make_env([_partially_attached(), [], [], [], [], [], []], SWALLOWED)
    r = _run(env, "--zero-check-grace", "0")
    assert r.returncode != 5, r.stdout
    assert not os.path.exists(os.path.join(stub_dir, "classify_argv")), "the classifier ran after checks had already attached"


# ── The other zero-run states are named, not lumped in ───────────────────────


# #3455: these four tests all depend on the zero-check diagnosis firing before
# the loop's own `elapsed >= timeout` check can race it (see the fake-clock
# header above) — each wires a scripted clock: call 1 (`start`) and call 2
# (the first loop `now`) both read 0, so the diagnosis's own `elapsed >= grace`
# (grace 0) fires deterministically on the first poll; call 3 reads 100, so the
# loop then exits via TIMEOUT on the very next iteration without depending on
# any real sleep. `interval="0"` avoids a real wait between iterations.
_CLOCK_DIAGNOSE_THEN_TIMEOUT = [0, 0, 100]


def test_path_filter_skip_is_named_and_polling_continues():
    env, stub_dir = _make_env([[]], PATH_SKIP)
    env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
    r = _run(env, "--zero-check-grace", "0", interval="0")
    out = r.stdout
    assert "DIAGNOSIS path-filter-skip" in out, out
    assert "SWALLOWED-PUSH" not in out
    assert r.returncode == 1, "a non-swallow keeps polling and ends at the ordinary timeout code"


def test_bot_push_no_dispatch_is_named_and_is_not_a_swallow():
    env, stub_dir = _make_env([[]], BOT_PUSH)
    env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
    r = _run(env, "--zero-check-grace", "0", interval="0")
    assert "DIAGNOSIS bot-push-no-dispatch" in r.stdout, r.stdout
    assert r.returncode != 5


def test_indeterminate_is_named_and_is_not_a_swallow():
    """#3455: main run 33605871465 (2026-09-02) red-mained the docs-only #3454
    merge here — a loaded runner let two adjacent real `date +%s` calls
    straddle a whole-second boundary, timing this test's 1s simulated budget
    out before "DIAGNOSIS indeterminate" was ever printed, while the exact
    same code passed locally (1.63s) and on every PR-lane run that night. The
    fake clock below makes the poll loop's own `elapsed` math independent of
    real process-scheduling jitter, closing the race structurally rather than
    widening the timeout (which would only make the same flake rarer)."""
    env, stub_dir = _make_env([[]], INDETERMINATE)
    env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
    r = _run(env, "--zero-check-grace", "0", interval="0")
    assert "DIAGNOSIS indeterminate" in r.stdout, r.stdout
    assert r.returncode != 5


def test_unparseable_classifier_output_never_manufactures_a_swallow():
    """An execution failure must degrade to the pre-#3219 behaviour (keep waiting),
    never to a confirmed swallow — the #2753/#3212 rule that a broken instrument
    is not a verdict."""
    env, stub_dir = _make_env([[]], "not json at all")
    env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
    r = _run(env, "--zero-check-grace", "0", interval="0")
    assert "diagnosis unavailable" in r.stdout, r.stdout
    assert r.returncode != 5


# ── #3455 proof: the race is closed, not just avoided by luck ────────────────


def test_diagnosis_survives_a_real_scheduling_stall_between_the_two_clock_reads():
    """Reproduces the EXACT gap that raced in main run 33605871465 (2026-09-02):
    a real delay between the `start` read and the loop's first `now` read. The
    #3455 fix makes what those reads RETURN a scripted constant, not a
    measurement of how much wall-clock time actually passed — so injecting a
    real 2-5s stall there (`WAIT_PR_GREEN_TEST_STALL_S`, `_TIME_STUB` above)
    must not change the outcome. Pre-fix (real `date +%s`), this exact gap is
    what let a loaded runner's fork+exec overhead alone push `elapsed` past a
    1s budget before the diagnosis this test asserts on ever ran."""
    for stall_s in ("2", "3.5", "5"):
        env, stub_dir = _make_env([[]], INDETERMINATE)
        env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
        env["WAIT_PR_GREEN_TEST_STALL_S"] = stall_s
        r = _run(env, "--zero-check-grace", "0", interval="0")
        assert "DIAGNOSIS indeterminate" in r.stdout, f"stall={stall_s}s: {r.stdout}"
        assert r.returncode != 5, f"stall={stall_s}s: {r.stdout}"


def test_diagnosis_is_deterministic_across_20_runs_under_a_scheduling_stall():
    """The acceptance bar (#3455): 20/20 passes under an injected scheduling
    delay. Uses a smaller per-run stall than the test above so the 20 reps stay
    cheap in CI (the suite is already near its own duration budget, per this
    incident's own trigger) — the fix's mechanism (a scripted, not measured,
    clock) is insensitive to the stall's MAGNITUDE, so a short stall proves the
    same structural closure as a long one."""
    for i in range(20):
        env, stub_dir = _make_env([[]], INDETERMINATE)
        env = _with_fake_clock(env, stub_dir, _CLOCK_DIAGNOSE_THEN_TIMEOUT)
        env["WAIT_PR_GREEN_TEST_STALL_S"] = "0.1"
        r = _run(env, "--zero-check-grace", "0", interval="0")
        assert "DIAGNOSIS indeterminate" in r.stdout, f"run {i}: {r.stdout}"
        assert r.returncode != 5, f"run {i}: {r.stdout}"


# ── The progress line: the two states must not render identically ────────────


def test_progress_line_says_no_checks_attached_when_none_are():
    env, _ = _make_env([[]], INDETERMINATE)
    r = _run(env, "--zero-check-grace", "99")
    assert "NO CHECKS ATTACHED YET" in r.stdout, r.stdout
    assert "0 of 6 expected are present" in r.stdout


def test_progress_line_says_how_many_attached_once_some_have():
    """PRE-FIX both states printed `0/6 green` — this asserts they now differ."""
    env, _ = _make_env([_partially_attached()], INDETERMINATE)
    r = _run(env, "--zero-check-grace", "99")
    assert "check(s) attached" in r.stdout, r.stdout
    assert "NO CHECKS ATTACHED YET" not in r.stdout


# ── The pure classifier adapter, sourced directly ────────────────────────────

_SOURCE_HARNESS = f"""
source '{_SCRIPT}' --source-only
classify_zero_check_diagnosis "$1"
echo "RC=$?"
"""


def _classify(payload):
    return subprocess.run(["bash", "-c", _SOURCE_HARNESS, "bash", payload], capture_output=True, text=True)


def test_pure_classifier_returns_5_only_for_swallowed():
    assert "RC=5" in _classify(SWALLOWED).stdout
    for other in (PATH_SKIP, BOT_PUSH, INDETERMINATE):
        assert "RC=0" in _classify(other).stdout, other


def test_pure_classifier_keys_off_the_state_field_not_a_phrase_in_the_reason():
    """Suppressor/classifier rules in this repo must be STRUCTURAL, never
    phrase-matched (memory: every phrase-matched member of the #2959/#3003/#3199
    family has failed in the field). A `path-filter-skip` whose reason text
    happens to contain the word "swallow" must still classify as not-a-swallow."""
    payload = json.dumps({"state": "path-filter-skip", "reason": "not a swallowed push; the diff touches none of the filter"})
    out = _classify(payload).stdout
    assert "RC=0" in out, out
    assert "SWALLOWED-PUSH" not in out


def test_pure_classifier_degrades_to_keep_polling_on_empty_input():
    out = _classify("").stdout
    assert "RC=0" in out
    assert "diagnosis unavailable" in out


# ── The adapter on the check_main_green.py side ──────────────────────────────


def test_classify_sha_cli_refuses_a_short_sha_rather_than_querying_with_it():
    r = subprocess.run(
        ["python3", os.path.join(_REPO, "scripts", "check_main_green.py"), "--classify-sha", "5213b364"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2, r.stdout
    payload = json.loads(r.stdout)
    assert payload["state"] == "indeterminate"
    assert "not a full 40-char sha" in payload["reason"]


def test_wait_pr_green_does_not_reimplement_the_classification():
    """#3212's whole lesson. A second copy of the swallowed/path-filter-skip/
    bot-push logic in bash is how that bug happened; this asserts the vocabulary
    only ever arrives from the classifier's JSON."""
    src = open(_SCRIPT).read()
    for reimplemented in ("path_matches_ci_filter", "BOT_COMMITTERS", "github-actions[bot]", "workflow_runs"):
        assert reimplemented not in src, f"wait_pr_green.sh re-derives {reimplemented} instead of asking check_main_green.py"
    assert "check_main_green.py --classify-sha" in src, "the delegation must be explicit in the script"
