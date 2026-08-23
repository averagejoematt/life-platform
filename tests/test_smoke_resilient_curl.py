"""tests/test_smoke_resilient_curl.py — #1911: a timed-out request must not auto-rollback a good deploy.

THE INCIDENT (twice in two days, 2026-07-29 and 2026-07-30):

    2026-07-29   ✅ api_dep /api/horizons  16:10:07   →  ##[error] exit code 28  16:10:17
    2026-07-30   ✅ api_dep /api/horizons  18:00:00   →  ##[error] exit code 28  18:00:10

Both runs auto-rolled-back a correct, fully-gated, merged fix — the first putting a real
clinician's name back on a live public page for ~15 minutes (#1891), the second reverting
#1895's front-end belts.

Two independent defects produced that:

  1. **`set -e` + a bare command substitution.** `smoke_test_site.sh` runs under
     `set -euo pipefail`, so `status=$(curl ... --max-time 10 "$url")` aborts the ENTIRE
     script the moment curl exits 28. The check's own error branch never runs — hence no
     ❌ row, no URL, and a bare `exit code 28` that the deploy gate reads as a bad deploy.
     One timed-out request out of ~40 is weak evidence of a bad deploy, yet it was
     sufficient to revert merged work.

  2. **The failing endpoint was anonymous.** The log printed ✅ per pass and then the bare
     exit code, so the culprit had to be inferred from the api_dep sort order. That
     inference cost real diagnosis time in both incidents (and was initially mis-diagnosed
     as a transient flake — it was deterministic origin latency on /api/inference_receipt).

The structural test below is deliberately DERIVED, not enumerated: it scans the smoke for
any bare `$(curl ...)` rather than listing the call sites known today. Enumerated guards
are exactly what let the #1895 class recur three times — a hand-written list only covers
the instances someone remembered, and dies silently the moment a new call site is added.

Behavioral tests run the real lib under real bash with `curl` and `sleep` stubbed as shell
functions — no network, no wall-clock sleeps.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SMOKE = os.path.join(_REPO, "deploy", "smoke_test_site.sh")
_LIB = os.path.join(_REPO, "deploy", "lib", "resilient_curl.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


# ── Structural: the whole SET of call sites, derived ──────────────────────────


def test_lib_exists_and_is_sourced_by_the_smoke():
    assert os.path.exists(_LIB), "#1911: deploy/lib/resilient_curl.sh is missing"
    assert "lib/resilient_curl.sh" in _read(_SMOKE), "smoke_test_site.sh must source deploy/lib/resilient_curl.sh (#1911)"


def test_no_bare_curl_command_substitution_survives_in_the_smoke():
    """THE class guard. Any `X=$(curl ...)` is a latent `set -e` abort — the exact
    construct that killed both runs. Derived scan, so a NEW call site added next month
    fails here instead of surfacing as another anonymous rollback."""
    offenders = []
    for i, line in enumerate(_strip_comments(_read(_SMOKE)).splitlines(), 1):
        # $(curl ...) or `curl ...` inside a substitution, not routed through smoke_curl.
        if re.search(r"\$\(\s*curl\s", line) or re.search(r"=\s*`curl\s", line):
            offenders.append(f"  line {i}: {line.strip()[:100]}")
    assert not offenders, (
        "#1911: bare $(curl ...) in smoke_test_site.sh aborts the whole run under `set -e` "
        "on a timeout (exit 28) — route it through smoke_curl instead:\n" + "\n".join(offenders)
    )


def test_smoke_names_the_check_in_flight():
    """Both incidents required inferring the failing endpoint from sort order."""
    code = _read(_SMOKE)
    assert "CURRENT_CHECK" in code, "#1911: the smoke must track which check is in flight"
    assert re.search(r"trap\s+_smoke_on_exit\s+EXIT", code), "an EXIT trap must name the in-flight check when the run aborts"
    # The api_dep loop is where it fired: the dep must be named BEFORE the request.
    m = re.search(r"check_json_endpoint\(\)\s*\{(.*?)\n\}", code, re.S)
    assert m, "check_json_endpoint not found"
    body = m.group(1)
    assert body.index("CURRENT_CHECK") < body.index("smoke_curl"), "the api_dep must be named BEFORE its request, not only after a pass"


def test_retry_knobs_are_env_overridable_and_transport_scoped():
    code = _read(_LIB)
    for knob in ("SMOKE_CURL_ATTEMPTS", "SMOKE_CURL_RETRY_INTERVAL", "SMOKE_CURL_RETRY_CODES"):
        assert knob in code, f"{knob} must be env-overridable"
    codes = re.search(r'SMOKE_CURL_RETRY_CODES="\$\{SMOKE_CURL_RETRY_CODES:-([^}"]+)\}"', code)
    assert codes, "retry codes must be a documented, overridable list"
    assert "28" in codes.group(1).split(), "curl exit 28 (timeout) is the incident class — it must be retried"
    # No literal-digit sleeps (the #1526 no-fixed-sleep rule applies here too).
    # Two configurable sleeps are sanctioned: the transport-retry interval and
    # the #2978 confirm-before-fail delay — both env-overridable, never literals.
    sleeps = re.findall(r"\bsleep\s+(\S+)", _strip_comments(code))
    assert sorted(set(sleeps)) == [
        '"$SMOKE_CURL_RETRY_INTERVAL"',
        '"${SMOKE_CONFIRM_DELAY}"',
    ], f"only the two configurable sleeps are allowed, found: {sleeps}"


# ── Behavioral: real bash, curl/sleep stubbed ────────────────────────────────

_HARNESS = """
set -euo pipefail
export SMOKE_CURL_RC_FILE="$TMPDIR_T/rc"
export SMOKE_CURL_RETRY_LOG="$TMPDIR_T/retries"
export SMOKE_CURL_ATTEMPTS=%(attempts)d
export SMOKE_CURL_RETRY_INTERVAL=1
source '%(lib)s'
CURL_LOG="$TMPDIR_T/curl.log"; SLEEP_LOG="$TMPDIR_T/sleep.log"
: > "$CURL_LOG"; : > "$SLEEP_LOG"
# Stub curl: fail with %(fail_code)d until call #%(ok_after)d, then succeed.
curl() {
  echo call >> "$CURL_LOG"
  local n; n=$(wc -l < "$CURL_LOG" | tr -d ' ')
  if [ "$n" -ge %(ok_after)d ]; then echo "BODY-OK"; return 0; fi
  return %(fail_code)d
}
sleep() { echo "$1" >> "$SLEEP_LOG"; }
BODY=$(smoke_curl -s "https://example.invalid/x")
RC=$(smoke_curl_rc)
echo "REACHED=yes body=$BODY rc=$RC curls=$(wc -l < "$CURL_LOG" | tr -d ' ') sleeps=$(wc -l < "$SLEEP_LOG" | tr -d ' ') retries=$(smoke_curl_retry_count)"
"""


def _run(tmp_path, attempts=2, fail_code=28, ok_after=1):
    script = _HARNESS % {"lib": _LIB, "attempts": attempts, "fail_code": fail_code, "ok_after": ok_after}
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR_T": str(tmp_path)},
        timeout=30,
    )
    return proc


def _parse(proc):
    m = re.search(r"REACHED=yes body=(\S*) rc=(\d+) curls=(\d+) sleeps=(\d+) retries=(\d+)", proc.stdout)
    assert m, f"harness output unparseable:\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    return {"body": m.group(1), "rc": int(m.group(2)), "curls": int(m.group(3)), "sleeps": int(m.group(4)), "retries": int(m.group(5))}


def test_healthy_request_makes_one_call_and_never_sleeps(tmp_path):
    """The common case must stay exactly as fast as before the fix."""
    r = _parse(_run(tmp_path, ok_after=1))
    assert r["rc"] == 0 and r["body"] == "BODY-OK"
    assert r["curls"] == 1, "a healthy request must not retry"
    assert r["sleeps"] == 0 and r["retries"] == 0


def test_single_timeout_is_retried_and_recovers(tmp_path):
    """THE incident scenario. Pre-fix this aborted the whole run with exit 28 and
    auto-rolled-back a correct merged change; now it retries once and passes."""
    proc = _run(tmp_path, ok_after=2)
    r = _parse(proc)
    assert r["rc"] == 0, "a transient timeout must recover, not fail the deploy"
    assert r["curls"] == 2 and r["sleeps"] == 1
    assert r["retries"] == 1, "the retry must be COUNTED so a slow origin stays visible"
    assert "retrying once" in proc.stderr, "the retry must be announced on stderr (never stdout — stdout is captured)"


def test_persistent_timeout_still_fails_but_does_not_kill_the_caller(tmp_path):
    """The teeth: a genuinely dead endpoint must still fail. The DIFFERENCE from the
    incident is that the caller keeps running and can print a named ❌ row, instead of
    the script dying anonymously at `exit 28`."""
    proc = _run(tmp_path, ok_after=99)
    r = _parse(proc)
    assert proc.returncode == 0, "the harness must REACH its final echo — smoke_curl must not trip `set -e`"
    assert r["rc"] == 28, "the caller must still see the failure and fail its check"
    assert r["curls"] == 2, "bounded: exactly SMOKE_CURL_ATTEMPTS attempts, never an infinite loop"


def test_non_transport_exit_code_is_not_retried(tmp_path):
    """Retry the transport class only. A curl usage/protocol error is not flakiness."""
    r = _parse(_run(tmp_path, fail_code=22, ok_after=99))
    assert r["rc"] == 22
    assert r["curls"] == 1, "a non-transport exit code must fail on the first attempt"
    assert r["sleeps"] == 0


def test_rc_survives_the_command_substitution_subshell(tmp_path):
    """smoke_curl is called as $(smoke_curl ...), which runs in a SUBSHELL — a plain
    global would be lost. The rc must still reach the caller (this is why it round-trips
    through a file), otherwise every check would read a stale/zero code."""
    r = _parse(_run(tmp_path, ok_after=99))
    assert r["rc"] == 28, "the exit code must cross the subshell boundary"


def test_attempts_knob_of_one_disables_retry(tmp_path):
    r = _parse(_run(tmp_path, attempts=1, ok_after=99))
    assert r["curls"] == 1 and r["sleeps"] == 0


# ── The negative test: prove the OLD construct really did kill the run ────────


def test_bare_curl_substitution_would_abort_the_run(tmp_path):
    """Proves the guard fires. This reproduces the pre-fix construct verbatim; if bash
    ever stopped aborting here, the structural test above would be guarding nothing."""
    script = """
set -euo pipefail
curl() { return 28; }
status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://example.invalid/x")
echo "REACHED=yes"
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 28, f"expected the bare construct to abort with 28, got {proc.returncode}"
    assert "REACHED=yes" not in proc.stdout, "the pre-fix construct must abort BEFORE any error handling — that is the whole bug"
