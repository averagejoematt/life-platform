"""tests/test_smoke_cache_aware.py — #1526: site smoke must not race the CloudFront invalidation.

2026-07-19 05:40 UTC (INCIDENT_LOG): a deploy shipped the #1395 static cores AND the
smoke guard asserting them in the SAME deploy; smoke fetched /coaching/ from a
CloudFront edge the invalidation hadn't reached yet, saw the cached pre-deploy page,
failed the brand-new static-core check, and auto-rollback reverted a HEALTHY deploy —
the second healthy-deploy rollback that night. The mechanism that lost the race was a
fixed `sleep 60` guess in site-deploy.yml's smoke job.

Two-layer contract pinned here (workflow-hygiene style, like test_site_deploy_workflow.py):

  1. Deterministic wait where the credentials live: deploy/sync_site_to_s3.sh blocks on
     `aws cloudfront wait invalidation-completed` after creating the invalidation, so the
     deploy-site job doesn't finish until the edges serve the new build. The wait is
     guarded — a waiter timeout WARNS but never fails a deploy whose invalidation exists.

  2. Cache-aware smoke as the second net: smoke_test_site.sh's content assertions route
     through deploy/lib/cache_aware_fetch.sh — a failed body assertion re-fetches within a
     SHARED bounded retry budget instead of failing straight into an auto-rollback. The
     common case stays one fetch + zero sleeps; there is no unconditional sleep anywhere.

The behavioral tests run the retry lib under real bash with `curl` and `sleep` stubbed as
shell functions — no network, no real invalidations, no wall-clock sleeps.
"""

import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SYNC = os.path.join(_REPO, "deploy", "sync_site_to_s3.sh")
_SMOKE = os.path.join(_REPO, "deploy", "smoke_test_site.sh")
_LIB = os.path.join(_REPO, "deploy", "lib", "cache_aware_fetch.sh")
_SITE_DEPLOY = os.path.join(_REPO, ".github", "workflows", "site-deploy.yml")
_OIDC_SETUP = os.path.join(_REPO, "deploy", "setup_github_oidc.sh")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    """Drop full-line and trailing comments; join shell line-continuations so
    multi-line `aws` commands match as one statement."""
    text = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())
    return text.replace("\\\n", " ")


# ── Layer 1: the deploy path waits for the invalidation it created ────────────


def test_sync_script_waits_for_invalidation_completed():
    code = _strip_comments(_read(_SYNC))
    create = code.find("cloudfront create-invalidation")
    wait = code.find("cloudfront wait invalidation-completed")
    assert create != -1, "sync_site_to_s3.sh no longer creates the invalidation?"
    assert (
        wait != -1
    ), "#1526: sync_site_to_s3.sh must block on `aws cloudfront wait invalidation-completed` after creating the invalidation"
    assert wait > create, "the invalidation-completed wait must come AFTER create-invalidation"
    assert re.search(
        r"if\s+aws\s+cloudfront\s+wait\s+invalidation-completed", code
    ), "the waiter must be guarded (if aws cloudfront wait ...) — a waiter timeout warns, it never fails a deploy whose invalidation exists"


def test_oidc_setup_grants_get_invalidation():
    """The waiter needs cloudfront:GetInvalidation. The LIVE deploy-role policy already
    grants it; the repo-side codification (setup_github_oidc.sh) must too, so a re-run
    of the setup script can never silently drop the waiter's permission."""
    code = _strip_comments(_read(_OIDC_SETUP))
    assert (
        "cloudfront:GetInvalidation" in code
    ), "setup_github_oidc.sh must grant cloudfront:GetInvalidation (the invalidation-completed waiter polls it)"


# ── Layer 2: cache-aware smoke (bounded retries, no fixed sleeps) ─────────────


def test_site_deploy_workflow_has_no_fixed_sleep_gate():
    """The fixed `sleep 60` was a guess and LOST the race on 2026-07-19. The wait is
    now deterministic in the deploy job (which holds the AWS credentials); the smoke
    job must not reintroduce a fixed-sleep propagation guess."""
    code = _strip_comments(_read(_SITE_DEPLOY))
    assert not re.search(
        r"\bsleep\s+\d", code
    ), "site-deploy.yml must not gate smoke on a fixed sleep — wait on the invalidation + bounded smoke retries instead"


def test_retry_lib_exists_with_bounded_shared_budget():
    assert os.path.exists(_LIB), "#1526: deploy/lib/cache_aware_fetch.sh (the bounded content-retry lib) is missing"
    code = _read(_LIB)
    assert "SMOKE_CONTENT_RETRY_BUDGET" in code, "retry budget must be env-overridable (SMOKE_CONTENT_RETRY_BUDGET)"
    assert "SMOKE_CONTENT_RETRY_INTERVAL" in code, "retry interval must be env-overridable (SMOKE_CONTENT_RETRY_INTERVAL)"
    assert "refetch_within_budget" in code and "assert_body_until" in code
    # The ONLY sleep allowed is the budgeted one inside refetch_within_budget.
    sleeps = re.findall(r"\bsleep\s+(\S+)", _strip_comments(code))
    assert sleeps == ['"$CONTENT_RETRY_INTERVAL"'], f"only the budgeted interval sleep is allowed in the retry lib, found: {sleeps}"


def test_smoke_routes_content_assertions_through_the_retry_lib():
    code = _read(_SMOKE)
    assert "lib/cache_aware_fetch.sh" in code, "smoke_test_site.sh must source deploy/lib/cache_aware_fetch.sh (#1526)"
    stripped = _strip_comments(code)
    # The incident class: the static-core guard and the OG guard assert brand-new
    # same-deploy content — both must go through the bounded retry path.
    assert re.search(
        r"assert_body_until\s+\S+\s+\S+\s+_static_core_ok", stripped
    ), "the static-core guard (the check that fired on 2026-07-19) must be cache-aware"
    assert re.search(r"assert_body_until\s+\S+\s+\S+\s+_og_ok", stripped), "the data-driven OG guard must be cache-aware"
    # The page content-marker checks pass their URL so a failed needle can re-fetch.
    assert re.search(
        r"check_body_contains\(\)\s*{[^}]*url=", code, re.S
    ), "check_body_contains must accept a url and retry via the lib on a failed assertion"
    # No unconditional sleeps in the smoke path either.
    assert not re.search(
        r"\bsleep\s+\d", stripped
    ), "smoke_test_site.sh must not carry unconditional sleeps — retries are budgeted via the lib"


# ── Behavioral: the retry logic itself (bash, curl/sleep stubbed) ─────────────

_HARNESS = """
set -uo pipefail
export SMOKE_CONTENT_RETRY_BUDGET=%(budget)d
export SMOKE_CONTENT_RETRY_INTERVAL=%(interval)d
source '%(lib)s'
CURL_LOG="$TMPDIR_T/curl.log"; SLEEP_LOG="$TMPDIR_T/sleep.log"
: > "$CURL_LOG"; : > "$SLEEP_LOG"
curl() {
  echo call >> "$CURL_LOG"
  local n; n=$(wc -l < "$CURL_LOG")
  if [ "$n" -ge %(fresh_after)d ]; then echo "FRESH body"; else echo "STALE body"; fi
}
sleep() { echo "$1" >> "$SLEEP_LOG"; }
_check() { grep -q FRESH "$1"; }
BODY="$TMPDIR_T/body"
curl > "$BODY"
rc=0
assert_body_until "https://example.invalid/page/" "$BODY" _check || rc=$?
echo "rc=$rc curls=$(wc -l < "$CURL_LOG" | tr -d ' ') sleeps=$(wc -l < "$SLEEP_LOG" | tr -d ' ') budget=$CONTENT_RETRY_BUDGET"
%(extra)s
"""


def _run_harness(tmp_path, budget, interval, fresh_after, extra=""):
    script = _HARNESS % {"lib": _LIB, "budget": budget, "interval": interval, "fresh_after": fresh_after, "extra": extra}
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR_T": str(tmp_path)},
        timeout=30,
    )
    assert proc.returncode == 0, f"harness failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    m = re.search(r"rc=(\d+) curls=(\d+) sleeps=(\d+) budget=(\d+)", proc.stdout)
    assert m, f"harness output unparseable: {proc.stdout!r}"
    return tuple(int(g) for g in m.groups()), proc.stdout


def test_fresh_edge_passes_with_zero_sleeps(tmp_path):
    """Common case: content is already fresh — one fetch, no retries, budget untouched."""
    (rc, curls, sleeps, budget), _ = _run_harness(tmp_path, budget=90, interval=15, fresh_after=1)
    assert rc == 0
    assert curls == 1, "fresh content must not trigger any re-fetch"
    assert sleeps == 0, "the common case must not sleep at all (#1526: smoke stays fast)"
    assert budget == 90, "budget must be untouched when the first read is fresh"


def test_stale_edge_recovers_within_budget(tmp_path):
    """The incident scenario: the edge serves the pre-deploy page for a while, then the
    invalidation lands. Pre-#1526 this was an immediate FAIL → auto-rollback of a
    healthy deploy; now the assertion retries and passes."""
    (rc, curls, sleeps, budget), _ = _run_harness(tmp_path, budget=90, interval=15, fresh_after=3)
    assert rc == 0, "a stale-then-fresh edge must end in PASS, not an auto-rollback"
    assert curls == 3 and sleeps == 2
    assert budget == 90 - 2 * 15, "each retry must consume the shared budget"


def test_genuinely_missing_content_still_fails_bounded(tmp_path):
    """A real regression (content truly absent) must still FAIL — after a bounded number
    of retries, never an infinite loop, and the guard keeps its teeth."""
    (rc, curls, sleeps, budget), _ = _run_harness(tmp_path, budget=45, interval=15, fresh_after=999)
    assert rc == 1, "permanently-missing content must still fail the assertion"
    assert sleeps == 3 and curls == 4, "retries must stop when the budget is spent"
    assert budget < 15, "budget must be exhausted, not leaked"


def test_budget_is_shared_across_assertions(tmp_path):
    """The budget bounds the WHOLE run: once spent, later failing assertions fail fast
    (no per-assertion reset — worst case adds the budget once, not once per check)."""
    extra = (
        'BODY2="$TMPDIR_T/body2"; echo "STALE body" > "$BODY2"\n'
        '_never() { grep -q NOPE "$1"; }\n'
        "rc2=0\n"
        'assert_body_until "https://example.invalid/two/" "$BODY2" _never || rc2=$?\n'
        'echo "rc2=$rc2 sleeps2=$(wc -l < "$SLEEP_LOG" | tr -d \' \')"'
    )
    (rc, _, sleeps, budget), out = _run_harness(tmp_path, budget=30, interval=15, fresh_after=999, extra=extra)
    assert rc == 1 and budget < 15
    m = re.search(r"rc2=(\d+) sleeps2=(\d+)", out)
    assert m, out
    assert int(m.group(1)) == 1, "a failing assertion after budget exhaustion must still fail"
    assert int(m.group(2)) == sleeps, "no additional sleeps once the shared budget is spent"
