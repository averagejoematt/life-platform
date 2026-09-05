#!/usr/bin/env python3
"""scripts/check_main_green.py — the /wrap green-main gate (#1327, stranded-aware per #1901).

A session may not close declaring victory over a red main it never looked at:
on 2026-07-18 a wrap wrote "main GREEN (1c641b6a)" while that sha's own push
run had concluded FAILURE. This gate makes the check mechanical.

#1901 taught it the two STRANDED DEPLOY states, which the #1327 version read
straight past:

  * **Stranded production approval** — a run sits at the `production` approval
    gate with `status=waiting`. Because ci-cd.yml sets
    `concurrency: cancel-in-progress: false`, every later run queues behind it
    (0 jobs, `pending`) — which reads exactly like the phantom-concurrency
    class (`reference_push_ci_silent_death`) but has the OPPOSITE fix.
    Tell: phantom = 0 jobs AND no other run in the group; stranded gate =
    0-job runs queued BEHIND an older run in `waiting`. (Observed 2026-07-28:
    run 30324990970 held the gate ~15h; the #1653 merge queued behind it and
    never started.)
  * **Stranded Plan (R8-ST6)** — the run FAILED, but the only red job is
    "Plan deployments" and "Deploy" was skipped, everything else green: the
    IAM-review gate is holding deploys until a pending `cdk_deploy.sh` runs
    from main. This is not an ordinary red — every subsequent merge's deploy
    strands too, invisibly, until the CDK deploy clears it.

#2052 adds the THIRD stranded state, which the two above cannot express:

  * **Phantom deploy wedge** — the run's `Deploy` job is blocked in the
    `ci-cd-deploy-<ref>` concurrency group by an entry that corresponds to no
    real run. Since the #2009 redesign this no longer presents as `0 jobs`:
    the run shows FIVE GREEN JOBS and sits `pending`, which reads as "waiting
    for approval" — but `pending_deployments` is empty and will stay empty,
    because GitHub evaluates concurrency BEFORE the environment rule, so the
    gate never opens and there is nothing to approve. Every tell documented
    for the older phantom class keys on "0 jobs" and is therefore now blind.
    Detection lives in `scripts/check_deploy_wedge.py` (it needs per-run JOB
    state, which `gh run list` does not carry); this gate consumes its verdict.
    Distinguishing it from the stranded-approval class above is NOT possible
    from a single run — the two are byte-identical — it turns entirely on
    whether any other in-flight run actually holds the deploy group.

Verdicts:
  * green                → exit 0
  * green + a YOUNG waiting run (< ~2h at the approval gate) → exit 0 with a
    notice (a manual production approval pending is the pipeline's normal
    post-merge state, not an incident — until it ages past the threshold)
  * stranded-approval / stranded-plan / stranded-deploy-wedge / red /
    no-verdict → print the decode contract and exit 1. The wrap may proceed
    ONLY by writing the one-line decode into the handover (e.g. `**Main:**
    stranded — run 303… waiting at the production gate since 03:06Z, #1901
    class`) and re-running with --decoded to acknowledge.

A phantom deploy wedge outranks every other verdict INCLUDING green: while it
holds, no deploy can start, so the last completed run's success is a stale
fact about a pipeline that is no longer able to ship.

#2590 adds the FOURTH non-verdict state — the one created by obeying #2467:

  * **Rejected-and-superseded** — a gated run whose `production` deployment was
    REJECTED (the prescribed action for a run whose sha is already an ancestor
    of main) concludes `failure` with `Deploy` as the sole red job, because the
    job never executed. Read literally that is a red main, so following #2467
    made the wrap's own (e2) gate report a falsehood — five times on
    2026-08-11/12 (32734614d, b177805f6, aad9ae137, c78c93369, c16c75783).
    It self-heals only when a later run succeeds, so in a session that rejects
    several runs and defers the deploy to the end, the false-red window is the
    whole session.
    Derivation: the run's OWN approval record —
    `GET /repos/{o}/{r}/actions/runs/{id}/approvals` → `[{state: "rejected"}]`
    (the `…/deployments` endpoint 404s on this repo; `approvals` is the
    run-scoped source of truth and carries the operator's reason). NOT from
    "Deploy failed with no log" — a genuinely broken Deploy job has the same job
    shape and MUST still read red. The job shape is only the second half of the
    conjunction: rejected AND `Deploy` is the sole failing job.
    Such a run is skipped the same way a cancelled one is, but — unlike
    cancelled — it is REPORTED, with its sha and the rejection reason, so the
    operator sees the lease was actioned rather than the gate being blind.

#3530 corrects the oldest assumption in this file — that a `cancelled` rollup is
a superseded push and therefore carries no signal:

  * **Cancelled-carrying-a-real-failure** — since #2009 the WORKFLOW-level
    concurrency group carries `${{ github.run_id }}` (`ci-cd.yml:129`), so it is
    unique per run and NOTHING supersedes a CI/CD run any more. The one canceller
    left is the `deploy` job's own group `ci-cd-deploy-<ref>` (`ci-cd.yml:861`):
    GitHub allows one pending entry per group, so a newer run's Deploy EVICTS the
    older run's still-pending Deploy, the evicted job concludes `cancelled`, and
    the whole run rolls up `cancelled` — regardless of what the validation jobs
    above it already concluded. Live 2026-09-04: runs 33843452894 and 33843742114
    both rolled up `cancelled` with `test / Unit Tests` FAILED (the ADR-080
    coverage gate) and this gate walked past both to an older `success`.
    The verdict comes from the run's own JOBS, never the rollup —
    `scripts/ci_run_verdicts.py` owns that predicate and BOTH readers import it
    (`check_ci_warnings.py` is the other). It is deliberately not restated here:
    #3212 happened because a classification lived inside one consumer and the
    other could not reach it.

A cancelled run is skipped ONLY when its own jobs prove it superseded; a
cancelled run whose jobs could not be read is INDETERMINATE and is not skipped
either ("could not verify" must never read as "no verdict here"). The newest
run that actually finished AND carries a verdict is the completed-run verdict.

#2826 gives `head_coverage()` (above) a SCHEDULED consumer, because #2762 only
ever ran it inside a session's `/wrap` gate — an unattended merge (dependabot-
automerge, remediation automerge) whose push is swallowed had no detector
until a human happened to run this file. `--head-coverage-check` (see
`main_head_coverage()` below) is invoked from `deploy-wedge-watch.yml`'s
existing 15-minute cron.

The naive wiring — "uncovered ⇒ page" — was tried and rejected LIVE in this
same session: main's HEAD (8cbf075f) touched only `CLAUDE.md` and
`handovers/HANDOVER_LATEST.md`, neither in ci-cd.yml's `paths:` filter, so
`head_coverage()` correctly read `uncovered` — but `Docs CI` HAD run at that
sha (`gh api .../actions/runs?head_sha=...` — total_count 1). That is an
ordinary, EXPECTED path-filter skip, not a swallowed push, and ci-cd.yml's own
`paths:` block (see the DEVOPS-01 comment at 0bffc1ec) already documents this
exact shape as "indistinguishable from a swallowed push" by `head_coverage()`
alone. Wiring the naive version into a 15-minute cron would page on every
docs-only or wrap commit — most of them — and be muted inside a week.

`classify_zero_run_head()` is the discriminator, run only when `head_coverage`
says `uncovered`:

  swallowed        — ZERO runs of ANY workflow reference head_sha (nothing ran
                      at all — #2662 class), OR some other workflow(s) ran but
                      the commit's changed paths DO intersect ci-cd.yml's
                      `paths:` filter (ci-cd.yml should have run and did not,
                      even though siblings did — a partial swallow)
  path-filter-skip  — some other workflow(s) ran, and the changed paths do NOT
                      intersect the filter — the expected, silent shape
  indeterminate     — the changed-files read failed; neither verdict is provable

`main_head_coverage()` maps these to three DISTINCT exit codes so the check
can never fail dark (the #2753 class this epic exists to close): an execution
error (API read failure) returns 2, never 0 — "could not verify" must never
read as "coverage OK", and must not be conflated with a CONFIRMED swallow (1)
either, since only the latter should page.

#3212 wires that discriminator into its OTHER consumer — `main()`, the gate a
session actually runs at boot and at wrap. Until then `classify_zero_run_head`
was reachable ONLY from the scheduled `--head-coverage-check` path, so `main()`
printed the #2762 swallowed-push text on every `uncovered` HEAD without ever
asking. A session's own wrap commit is docs-only BY CONSTRUCTION, so the gate
red-flagged every wrap and the documented remedy was to wave it through with
`--decoded` — training for waving through the real thing. Live-proved at
Session E boot: the same repo state, the same file, two different answers for
main's HEAD 57baffd9 (bare `main()` said swallowed-push, exit 1;
`--head-coverage-check` said path-filter skip and named the five sibling
workflows that HAD run, exit 0 — the second is correct).

The fix is shared plumbing, not a second copy: `diagnose_uncovered_head()` is
the one impure fetch+classify step, and BOTH consumers call it. `render()`
maps the four states honestly — `path-filter-skip` and `bot-push-no-dispatch`
do not fail the gate, `swallowed` keeps the #2762 recovery text verbatim, and
`indeterminate` (including "nobody ran the discriminator") stays non-green
while explicitly NOT claiming a confirmed swallow. Every run prints one
machine-readable `HEAD-COVERAGE: <state> <sha8>` line, keyed off the same
state constants, so `wrap_gates.py` (and a handover decode line) can QUOTE the
concluded state instead of paraphrasing prose.

Usage:
  python3 scripts/check_main_green.py                    # gate: not-green main → exit 1
  python3 scripts/check_main_green.py --decoded           # operator wrote the decode line → exit 0 with reminder
  python3 scripts/check_main_green.py --head-coverage-check  # #2826 scheduled consumer (see above)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# The #3530 cancelled-run predicate lives in ONE module both readers import.
# `scripts/` is on sys.path when this file is run as a script, but NOT when a
# test loads it via importlib.spec_from_file_location (which several do), so the
# directory is put there explicitly rather than relying on the caller's cwd.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import ci_run_verdicts as civ  # noqa: E402 — must follow the sys.path insert above

# A run parked at the production approval gate is normal right after a merge
# (the approval is manual by design) — it becomes an incident when it ages.
STRANDED_WAIT_HOURS = 2.0

# How many consecutive `failure` runs to probe for the rejected shape before
# giving up and treating the next one as the verdict (#2590). A merge session
# that rejects a run per merge stacks several in a row; an unbounded walk would
# turn one gate check into dozens of API calls.
REJECTION_PROBE_LIMIT = 8

# #3530: how many leading `cancelled` runs to probe for their real job verdict
# before giving up. Same reasoning as REJECTION_PROBE_LIMIT — a merge train can
# stack several evicted-Deploy cancels in a row, but the walk stops at the first
# run that carries a verdict, so this is a bound on a pathological history, not
# the normal cost (2026-09-04's worst real case was 2).
CANCELLED_PROBE_LIMIT = 8

# Repo root, for reading ci-cd.yml's own `paths:` filter (#2826) — never guess
# a relative path from the caller's cwd.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Verdict kinds (module constants so tests and consumers share the vocabulary).
GREEN = "green"
RED = "red"
STRANDED_APPROVAL = "stranded-approval"
STRANDED_PLAN = "stranded-plan"
STRANDED_DEPLOY_WEDGE = "stranded-deploy-wedge"
NO_VERDICT = "no-verdict"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_hours(run: dict, now: datetime) -> float | None:
    created = _parse_iso(run.get("createdAt"))
    if created is None:
        return None
    return (now - created).total_seconds() / 3600.0


def latest_completed_run(runs: list[dict], rejected_ids: object = None, cancelled_verdicts: dict | None = None) -> dict | None:
    """Newest completed run that actually carries a verdict.

    Pure — unit-tested offline. `runs` is newest-first, as `gh run list`
    returns them.

    `rejected_ids` (#2590) is the set of run ids whose `failure` is a REJECTED
    production deployment rather than a broken pipeline — not a verdict.

    `cancelled_verdicts` (#3530) maps a run id to one of
    `ci_run_verdicts.CANCELLED_*`. A `cancelled` run is skipped ONLY when its
    entry says SUPERSEDED; CARRIES_FAILURE and INDETERMINATE both stop the walk,
    because the first is a red and the second is unproven. An id ABSENT from the
    map means nobody probed that run, which preserves the pre-#3530 skip for pure
    callers that supply no job data — every live caller here probes, and
    `tests/test_cancelled_not_superseded_3530.py` pins that it does.
    """
    skip = set(rejected_ids or ())
    verdicts = cancelled_verdicts or {}
    for r in runs:
        if r.get("status") != "completed":
            continue
        if r.get("conclusion") == "cancelled" and civ.cancelled_is_skippable(verdicts.get(r.get("databaseId"))):
            continue
        if r.get("databaseId") in skip:
            continue
        return r
    return None


def scan_cancelled(runs: list[dict], probe_jobs, max_probes: int = CANCELLED_PROBE_LIMIT) -> tuple[dict, list[dict]]:
    """#3530: classify every leading `cancelled` run from its OWN jobs.

    Pure by injection — `probe_jobs(run) -> jobs | None` is the only impure part
    and is faked in tests. Returns `(verdicts, notes)` where `verdicts` maps run
    id → a `ci_run_verdicts.CANCELLED_*` constant (feed it to
    `latest_completed_run` / `classify_pipeline`) and `notes` is a
    newest-first list of `{"run", "verdict", "failing"}` for reporting — every
    cancelled run the gate saw is named, including the ones it skipped.

    The walk stops at the first cancelled run that is NOT superseded (it is the
    verdict; nothing older matters) and at the first non-`failure`,
    non-`cancelled` completed run. `failure` runs are walked THROUGH rather than
    stopped at, because `scan_rejections` may yet classify them as rejected
    non-verdicts and land on an older cancelled run.
    """
    verdicts: dict = {}
    notes: list[dict] = []
    probes = 0
    for r in runs:
        if r.get("status") != "completed":
            continue
        conclusion = r.get("conclusion")
        if conclusion == "cancelled":
            if probes >= max_probes:
                break
            probes += 1
            jobs = probe_jobs(r)
            verdict = civ.classify_cancelled_run(jobs)
            verdicts[r.get("databaseId")] = verdict
            notes.append({"run": r, "verdict": verdict, "failing": civ.failing_job_names(jobs)})
            if not civ.cancelled_is_skippable(verdict):
                break
            continue
        if conclusion == "failure":
            continue
        break
    return verdicts, notes


def head_coverage(runs: list[dict], head_sha: str | None) -> dict:
    """#2762: does ANY run vouch for main's actual HEAD? Pure.

    The swallowed-push shape: a push to main that mints ZERO workflow runs (the
    #2662 class) leaves the newest completed run pointing at an OLDER sha, and
    the completed-run verdict vouches green for a HEAD it never saw. States:

      covered   — a completed, non-cancelled run exists AT head_sha
      pending   — run(s) exist at head_sha but none completed yet (normal post-merge)
      uncovered — NO run of any status references head_sha: the swallowed push
      unknown   — head_sha unavailable (caller could not read the remote branch)
    """
    if not head_sha:
        return {"state": "unknown", "pending": None}
    at_head = [r for r in runs if (r.get("headSha") or "") == head_sha]
    done = [r for r in at_head if r.get("status") == "completed" and r.get("conclusion") != "cancelled"]
    if done:
        return {"state": "covered", "pending": None}
    if at_head:
        return {"state": "pending", "pending": at_head[0]}
    return {"state": "uncovered", "pending": None}


# ── #2826: the swallowed-push / path-filter-skip discriminator ──────────────
#
# `head_coverage() == "uncovered"` means no ci-cd.yml run references head_sha —
# but ci-cd.yml's OWN `paths:` filter can legitimately decline a push (a
# docs-only or handover-only commit, e.g.), and that is indistinguishable from
# a genuine swallow using ci-cd.yml's run list alone. The discriminator below
# is fleet-level (queries runs of ALL workflows at head_sha, not just ci-cd.yml)
# — same shape as check_deploy_wedge.holders() needing a fleet view to tell a
# real holder from a phantom.

CI_CD_WORKFLOW_FILE = "ci-cd.yml"


def ci_cd_push_paths(yaml_text: str) -> list[str]:
    """The push `paths:` filter from ci-cd.yml's own trigger block. Pure —
    parses YAML text the caller supplies (never reads the file itself, so this
    is independently testable against a frozen fixture).

    NB: PyYAML's default (YAML 1.1) resolver reads the bare `on:` key as the
    boolean `True`, not the string `"on"` — a real gotcha every workflow-
    parsing script in this repo (`gate_census.py`, `apply_branch_protection.py`)
    has to account for. Both spellings are checked so this does not silently
    return `[]` if PyYAML's behavior ever changes.
    """
    import yaml  # local: keeps the module importable where PyYAML is absent

    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return []
    on = doc.get("on")
    if on is None:
        on = doc.get(True)
    push = (on or {}).get("push") or {}
    return [p for p in (push.get("paths") or []) if isinstance(p, str)]


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Translate ONE GitHub Actions path-filter glob to a regex. Not a general
    glob engine — covers exactly the constructs ci-cd.yml's filter actually
    uses: `dir/**` (any depth under dir, including nothing), a bare `*` within
    one path segment, and literal filenames/extensions."""
    parts = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def path_matches_ci_filter(changed_paths: list[str], patterns: list[str]) -> bool:
    """True iff any changed path matches any of ci-cd.yml's `paths:` globs. Pure.

    An EMPTY `patterns` list means "could not read the filter" (not "the
    filter matches nothing") — fail toward treating the push as IN-SCOPE, so a
    parse failure can never manufacture a false path-filter-skip.
    """
    if not patterns:
        return True
    regexes = [_pattern_to_regex(p) for p in patterns]
    return any(rx.match(path) for path in changed_paths for rx in regexes)


# Verdict kinds for classify_zero_run_head — module constants so tests and the
# CLI share one vocabulary (the #1901 lesson: a decode contract retyped per
# consumer drifts).
ZR_SWALLOWED = "swallowed"
ZR_PATH_FILTER_SKIP = "path-filter-skip"
ZR_INDETERMINATE = "indeterminate"
# #2826 follow-up (2026-08-20): a push made with GITHUB_TOKEN never dispatches
# workflows — GitHub suppresses it by design to prevent recursion. The nightly
# `chore(reconcile)` commit is exactly this shape AND touches lambdas/** (it
# regenerates lambdas/web/platform_counts.py's literals — site_api_common.py's,
# before #3101 moved them), so without this state it reads as
# a PARTIAL SWALLOW and the 15-minute cron fires after every single merge.
ZR_BOT_PUSH_NO_DISPATCH = "bot-push-no-dispatch"
BOT_COMMITTERS = {"github-actions[bot]", "web-flow"}

# #3212: the two zero-run states that are EXPECTED and must not fail the gate.
# Consumers key off these constants — never off matching a workflow name or a
# phrase in the reason text (the #3199 lesson: every phrase-matched suppressor
# in this repo has failed in the field).
ZR_NOT_A_FAILURE = frozenset({ZR_PATH_FILTER_SKIP, ZR_BOT_PUSH_NO_DISPATCH})

# #3212: the one machine-readable line every run prints, so a consumer
# (wrap_gates.py's draft marker line, a handover decode) can QUOTE the state
# the gate concluded instead of paraphrasing its prose. Format:
#   HEAD-COVERAGE: <state> <sha8>
HEAD_COVERAGE_PREFIX = "HEAD-COVERAGE:"


def head_coverage_state_name(state: dict) -> str:
    """The ONE name for what this run concluded about main's HEAD.

    `covered` / `pending` / `unknown` come straight from `head_coverage()`; an
    `uncovered` HEAD resolves to the #2826 discriminator's verdict, and to
    `indeterminate` when no discriminator verdict is present at all (a caller
    that never ran it knows nothing — it must never inherit a confirmed
    swallow, which is exactly the #3212 bug).
    """
    cov = (state.get("head_cov") or {}).get("state")
    if cov != "uncovered":
        return cov or "unknown"
    return ((state.get("head_zr") or {}).get("state")) or ZR_INDETERMINATE


def head_coverage_ok(state: dict) -> bool:
    """True iff HEAD's coverage does not, by itself, disqualify a green."""
    name = head_coverage_state_name(state)
    return name in ("covered", "pending", "unknown") or name in ZR_NOT_A_FAILURE


def classify_zero_run_head(
    all_runs_at_head: list[dict],
    changed_paths: list[str] | None,
    ci_paths: list[str],
    committer_login: str | None = None,
) -> dict:
    """Given `head_coverage() == "uncovered"`, decide swallowed-push vs an
    expected path-filter-skip. Pure — the only impure part (fetching
    `all_runs_at_head`/`changed_paths`/`ci_paths`) lives in the caller.

    `all_runs_at_head` — runs of ANY workflow at head_sha (NOT filtered to
    ci-cd.yml; `head_coverage` already proved no ci-cd.yml run exists there).

      swallowed         — zero runs of ANY workflow at head_sha (nothing ran,
                           period — the #2662 class), OR other workflow(s) DID
                           run but the diff intersects ci-cd.yml's own filter
                           (it should have run too and did not — a PARTIAL
                           swallow, not an expected skip)
      path-filter-skip   — other workflow(s) ran, and the diff touches none of
                            ci-cd.yml's `paths:` filter — the expected shape
                            (observed live: 8cbf075f, CLAUDE.md + a handover)
      indeterminate       — `changed_paths` is None (the commit's file list
                            could not be read) — neither verdict is provable;
                            NEVER silently folded into either
    """
    # A GITHUB_TOKEN push cannot dispatch workflows (GitHub anti-recursion), so a
    # zero-run HEAD is EXPECTED here and must never page — checked before every
    # other branch because it holds regardless of what the diff touched.
    if committer_login and committer_login in BOT_COMMITTERS:
        return {
            "state": ZR_BOT_PUSH_NO_DISPATCH,
            "reason": f"HEAD was pushed by {committer_login}; a GITHUB_TOKEN push never dispatches workflows",
        }
    if not all_runs_at_head:
        return {"state": ZR_SWALLOWED, "reason": "no workflow run of any kind references head_sha"}
    names = sorted({r.get("name") or r.get("path") or "?" for r in all_runs_at_head})
    if changed_paths is None:
        return {"state": ZR_INDETERMINATE, "reason": f"could not read the commit's changed files (other workflow(s) ran: {names})"}
    if path_matches_ci_filter(changed_paths, ci_paths):
        return {
            "state": ZR_SWALLOWED,
            "reason": f"other workflow(s) ran ({names}) but NOT ci-cd.yml, even though the diff touches its `paths:` filter",
        }
    return {
        "state": ZR_PATH_FILTER_SKIP,
        "reason": f"the diff touches none of ci-cd.yml's `paths:` filter; other workflow(s) ran instead: {names}",
    }


def latest_main_conclusion(runs: list[dict]) -> tuple[str | None, str | None]:
    """(conclusion, headSha) of the newest non-cancelled completed run.

    Kept as the #1327 public surface (tests/test_unred_main_1327.py).
    """
    run = latest_completed_run(runs)
    if run is None:
        return None, None
    return run.get("conclusion"), run.get("headSha")


def waiting_runs(runs: list[dict]) -> list[dict]:
    """Runs parked at an environment approval gate (`status=waiting`)."""
    return [r for r in runs if r.get("status") == "waiting"]


def _job_shape(jobs: list[dict]) -> tuple[bool, bool, bool]:
    """(plan_failed, deploy_skipped, other_job_failed) for a run's job list."""
    plan_failed = deploy_skipped = other_failed = False
    for j in jobs:
        name = j.get("name", "")
        concl = j.get("conclusion")
        if name.startswith("Plan"):
            plan_failed = plan_failed or concl == "failure"
        elif name == "Deploy":
            deploy_skipped = deploy_skipped or concl == "skipped"
        elif concl == "failure":
            other_failed = True
    return plan_failed, deploy_skipped, other_failed


def is_plan_red_deploy_skipped(jobs: list[dict]) -> bool:
    """True iff the failure is the PURE R8-ST6 stranded-Plan shape:

    "Plan deployments" failed, "Deploy" was skipped, and NO other job failed
    (the "Notify failure" job succeeding is part of the shape, not a failure).
    A run where Unit Tests (or anything else) also failed is an ordinary red —
    it needs a fix, not just the pending CDK deploy — though its deploy path
    is STILL stranded (classify_pipeline carries that as `deploy_also_stranded`).
    """
    plan_failed, deploy_skipped, other_failed = _job_shape(jobs)
    return plan_failed and deploy_skipped and not other_failed


def _deploy_is_sole_failure(jobs: list[dict]) -> bool:
    """True iff `Deploy` failed and no other job did (skips are not failures)."""
    deploy_failed = other_failed = False
    for j in jobs:
        concl = j.get("conclusion")
        if j.get("name") == "Deploy":
            deploy_failed = deploy_failed or concl == "failure"
        elif concl == "failure":
            other_failed = True
    return deploy_failed and not other_failed


def is_deploy_rejection(jobs: list[dict] | None, approvals: list[dict] | None) -> bool:
    """True iff this run's `failure` is a REJECTED production deployment (#2590).

    The load-bearing half is the FIRST clause: the verdict is derived from the
    run's own approval record (`…/actions/runs/{id}/approvals`), never from the
    job shape alone. A genuinely broken `Deploy` job presents with the identical
    job shape (sole red, and often no log if it died in setup) — it is
    `approved` (or has no approval record at all) and must still read RED.

    The job-shape clause is the second half of a conjunction, not a fallback: a
    run that was rejected AND had something else genuinely fail is a real red,
    because the rejection is then not the whole story.
    """
    states = {(a or {}).get("state") for a in (approvals or [])}
    if "rejected" not in states or "approved" in states:
        return False
    return _deploy_is_sole_failure(jobs or [])


def rejection_reason(approvals: list[dict] | None) -> str:
    """The operator's own one-line reason from the rejecting approval record."""
    for a in approvals or []:
        if (a or {}).get("state") == "rejected":
            comment = (a.get("comment") or "").strip()
            if comment:
                return comment.splitlines()[0]
    return "no reason recorded"


def scan_rejections(
    runs: list[dict], probe, max_probes: int = REJECTION_PROBE_LIMIT, cancelled_verdicts: dict | None = None
) -> tuple[list[dict], list[dict] | None]:
    """Walk newest-first, classifying each `failure` run as rejected or real.

    Pure by injection — `probe(run) -> (jobs, approvals)` is the only impure
    part and is faked in tests. Returns
    `(rejected, verdict_jobs)` where `rejected` is `[{"run", "reason"}, …]` in
    newest-first order and `verdict_jobs` is the job list of the run that ends
    the walk (needed downstream to split ordinary red from the R8-ST6 shape).

    A probe that fails (returns `(None, None)`) yields `is_deploy_rejection`
    False — i.e. it degrades to "ordinary red", never to a false green.

    `cancelled_verdicts` (#3530) comes from `scan_cancelled`. A cancelled run
    that is NOT superseded ends the walk with `verdict_jobs = None` — it is the
    verdict run, and its own shape is a cancelled rollup, never the R8-ST6
    Plan-red shape `verdict_jobs` exists to detect.
    """
    rejected: list[dict] = []
    verdicts = cancelled_verdicts or {}
    probes = 0
    for r in runs:
        if r.get("status") != "completed":
            continue
        if r.get("conclusion") == "cancelled":
            if civ.cancelled_is_skippable(verdicts.get(r.get("databaseId"))):
                continue
            return rejected, None
        if r.get("conclusion") != "failure":
            return rejected, None
        if probes >= max_probes:
            return rejected, None
        probes += 1
        jobs, approvals = probe(r)
        if is_deploy_rejection(jobs, approvals):
            rejected.append({"run": r, "reason": rejection_reason(approvals)})
            continue
        return rejected, jobs
    return rejected, None


def classify_pipeline(
    runs: list[dict],
    latest_failure_jobs: list[dict] | None = None,
    now: datetime | None = None,
    deploy_wedge: dict | None = None,
    rejected: list[dict] | None = None,
    cancelled_verdicts: dict | None = None,
    cancelled_notes: list[dict] | None = None,
) -> dict:
    """Classify main's pipeline state. Pure — fixture-tested offline (#1901/#2052).

    Returns {"kind", "sha", "run", "waiting", "overdue_waiting"} where kind is one of
    GREEN / RED / STRANDED_APPROVAL / STRANDED_PLAN / STRANDED_DEPLOY_WEDGE / NO_VERDICT.

    `deploy_wedge` is the verdict dict from `check_deploy_wedge.classify_fleet` (the
    caller supplies it — this gate reads `gh run list`, which carries no per-run job
    state, so it cannot detect the wedge itself).

    Precedence: a phantom deploy wedge outranks everything — while it holds, NO deploy
    can start and no approval is even possible, so a green completed run is a stale
    fact. Then an OVERDUE waiting run (it blocks every later run regardless of the last
    completed verdict). A young waiting run does not change the verdict — it is
    reported alongside it.
    """
    now = now or datetime.now(timezone.utc)
    waiting = waiting_runs(runs)
    overdue = [r for r in waiting if (_age_hours(r, now) or 0.0) >= STRANDED_WAIT_HOURS]

    plan_failed = deploy_skipped = other_failed = False
    if latest_failure_jobs:
        plan_failed, deploy_skipped, other_failed = _job_shape(latest_failure_jobs)

    wedged = [v for v in (deploy_wedge or {}).get("verdicts", []) if v.get("kind") == "phantom-wedge"]

    rejected = rejected or []
    completed = latest_completed_run(
        runs,
        rejected_ids={(e.get("run") or {}).get("databaseId") for e in rejected},
        cancelled_verdicts=cancelled_verdicts,
    )
    if wedged:
        kind = STRANDED_DEPLOY_WEDGE
    elif overdue:
        kind = STRANDED_APPROVAL
    elif completed is None:
        kind = NO_VERDICT
    elif completed.get("conclusion") == "success":
        kind = GREEN
    elif completed.get("conclusion") == "failure" and plan_failed and deploy_skipped and not other_failed:
        kind = STRANDED_PLAN
    else:
        kind = RED

    return {
        "kind": kind,
        "sha": (completed or {}).get("headSha"),
        "run": completed,
        "waiting": waiting,
        "overdue_waiting": overdue,
        "wedged": wedged,
        "rejected": rejected,
        # #3530: every cancelled run the walk saw, and what its OWN jobs said.
        "cancelled_notes": cancelled_notes or [],
        # An ordinary red can STILL have a stranded deploy path (Plan red +
        # Deploy skipped alongside another failure, e.g. live 2026-08-02).
        "deploy_also_stranded": kind == RED and plan_failed and deploy_skipped,
    }


def _fmt_run(r: dict, now: datetime) -> str:
    age = _age_hours(r, now)
    age_s = f"{age:.1f}h" if age is not None else "?"
    return f"run {r.get('databaseId')} sha {(r.get('headSha') or '')[:8]} (waiting {age_s})"


def _rejection_notices(state: dict) -> list[str]:
    """Rejected-and-superseded runs are SKIPPED but never SWALLOWED (#2590).

    The operator has to be able to tell "the gate is blind to a red" from "the
    lease was actioned", so every skipped run is named with its sha and the
    reason the rejecting operator typed.
    """
    lines = []
    for entry in state.get("rejected") or []:
        r = entry.get("run") or {}
        lines.append(
            f"ℹ️  run {r.get('databaseId')} sha {(r.get('headSha') or '')[:8]} — production deployment REJECTED "
            f"and superseded (#2467 lease actioned), not a red main: {entry.get('reason')}"
        )
    return lines


def _cancelled_notices(state: dict) -> list[str]:
    """#3530: name every cancelled run the walk classified — skipped or not.

    Same discipline as `_rejection_notices`: a run the gate walks past has to be
    visible, so "that cancel really was a supersession" can never be confused
    with "the gate is blind to a red hiding behind a cancelled rollup".
    """
    return [civ.describe_cancelled(n.get("run") or {}, n.get("verdict"), n.get("failing")) for n in state.get("cancelled_notes") or []]


def render(state: dict, now: datetime | None = None) -> tuple[int, str]:
    """(exit_code, message) for a classified pipeline state. Pure."""
    now = now or datetime.now(timezone.utc)
    kind = state["kind"]
    sha8 = (state.get("sha") or "")[:8]
    lines: list[str] = []
    notices = _rejection_notices(state) + _cancelled_notices(state)

    if kind == STRANDED_DEPLOY_WEDGE:
        lines.append("🛑 PHANTOM DEPLOY WEDGE (#2052 class) — main's deploy path is dead; a green completed run is a stale fact:")
        for v in state.get("wedged", []):
            lines.append(
                f"   run {v.get('run_id')} sha {v.get('sha')} — Deploy blocked {v.get('blocked_minutes')}m with NOTHING holding the deploy group."
            )
        lines.append(
            "   This is NOT the #1901 stranded-approval class even though it looks identical:\n"
            "   `pending_deployments` is EMPTY and stays empty — GitHub evaluates the job's\n"
            "   `concurrency` BEFORE the `production` environment rule, so the gate never opens\n"
            "   and there is nothing to approve. Waiting for it is waiting forever. Since #2009\n"
            "   moved the group onto the `deploy` job, the run shows five GREEN jobs, so every\n"
            "   documented '0 jobs' tell for this class is blind.\n"
            "   Recovery: `python3 scripts/check_deploy_wedge.py --recover` (cancels the wedged\n"
            "   run, re-dispatches ci-cd.yml with deploy_all=true — a dispatch carries no push\n"
            "   diff, so change detection would otherwise deploy nothing). Do NOT salt the\n"
            "   concurrency group: three salts failed across recurrences 1-3 (CONVENTIONS §4d)."
        )
        return 1, "\n".join(lines + notices)

    if kind == STRANDED_APPROVAL:
        lines.append("🛑 STRANDED PRODUCTION APPROVAL (#1901 class) — main is NOT green and NOT ordinarily red:")
        for r in state["overdue_waiting"]:
            lines.append(f"   {_fmt_run(r, now)} is parked at the `production` approval gate.")
        lines.append(
            "   Every later CI/CD run queues behind it (status=pending, 0 jobs) because\n"
            "   concurrency is cancel-in-progress:false. This is NOT the phantom-concurrency\n"
            "   class (reference_push_ci_silent_death) — tell: phantom = 0 jobs AND no other\n"
            "   run in the group; stranded gate = 0-job runs queued BEHIND an older `waiting` run.\n"
            "   Recovery: action the gate — `bash deploy/approve_deployment.sh` (approve/reject\n"
            "   on Matthew's say-so). Do NOT cancel the waiting run: a cancelled run STRANDS its\n"
            "   deploy → recover with a `deploy_all=true` workflow_dispatch of ci-cd.yml."
        )
        return 1, "\n".join(lines + notices)

    if kind == STRANDED_PLAN:
        lines.append(
            f"🛑 STRANDED DEPLOY — R8-ST6 Plan-red at {sha8} (#1901 class), not an ordinary red:\n"
            "   Only the `Plan deployments` job failed (the IAM-review gate) and `Deploy` was\n"
            "   SKIPPED; lint/tests are green. Every ci-cd deploy strands until the pending IAM\n"
            "   change deploys from main (`bash deploy/cdk_deploy.sh <Stack>` — needs Matthew's\n"
            "   in-the-moment ask), then recover the stranded fleet half with a `deploy_all=true`\n"
            "   workflow_dispatch of ci-cd.yml."
        )
    elif kind == GREEN:
        lines.append(f"✅ main GREEN — latest completed CI/CD run ({sha8}) succeeded.")
        cov = (state.get("head_cov") or {}).get("state")
        head8 = (state.get("head_sha") or "")[:8]
        if cov == "uncovered":
            # #3212: NO CI/CD run at HEAD has FOUR causes, and only one of them
            # is an incident. The verdict comes from the #2826 discriminator's
            # returned state constant — never from the text of its reason.
            zr = state.get("head_zr") or {}
            zr_state = zr.get("state") or ZR_INDETERMINATE
            reason = zr.get("reason") or "the #2826 discriminator was never run for this HEAD, so nothing was ruled out"
            if zr_state == ZR_PATH_FILTER_SKIP:
                lines.append(
                    f"ℹ️  HEAD {head8} minted no CI/CD run of its own — an EXPECTED path-filter skip (#2826), not a\n"
                    f"   swallowed push: {reason}.\n"
                    f"   ci-cd.yml declined the push by its own `paths:` filter, so the green above vouches for {sha8},\n"
                    "   the newest sha that filter actually governed."
                )
            elif zr_state == ZR_BOT_PUSH_NO_DISPATCH:
                lines.append(
                    f"ℹ️  HEAD {head8} minted no CI/CD run of its own — EXPECTED, not a swallowed push: {reason}.\n"
                    "   GitHub suppresses workflow dispatch for GITHUB_TOKEN pushes by design (anti-recursion), so a\n"
                    f"   zero-run HEAD is the normal shape here; the green above vouches for {sha8}."
                )
            elif zr_state == ZR_SWALLOWED:
                lines.append(
                    f"🛑 …but that vouches ONLY for {sha8}: main's HEAD is {head8} and NO CI/CD run of any status\n"
                    "   references it — the swallowed-push shape (#2762). Re-push or workflow_dispatch ci-cd.yml so\n"
                    "   HEAD earns its own verdict; a green over an unwatched HEAD is not green.\n"
                    f"   Confirmed by the #2826 discriminator: {reason}."
                )
            else:
                lines.append(
                    f"⚠️  main's HEAD is {head8} and no CI/CD run references it, but whether that is a swallowed push\n"
                    f"   or an expected path-filter skip could NOT be determined: {reason}.\n"
                    "   This is not a confirmed swallow and it is not an OK either — re-run once the read recovers, or\n"
                    "   decode it by hand (`gh api repos/…/actions/runs?head_sha=<full sha>`)."
                )
        elif cov == "pending":
            lines.append(f"ℹ️  HEAD {head8} has its run in flight — the green above vouches for {sha8} until it completes.")
        elif cov == "unknown" and state.get("head_sha_error"):
            lines.append(f"⚠️  could not read main's HEAD from the API ({state.get('head_sha_error')}) — HEAD coverage unverified.")
    elif kind == NO_VERDICT:
        lines.append("⚠️  no completed non-cancelled CI/CD run found on main — wait for the in-flight run or decode manually.")
    else:
        concl = ((state.get("run") or {}).get("conclusion") or "red").upper()
        lines.append(f"❌ main is {concl} at {sha8}.")
        if concl == "CANCELLED":
            # #3530: the rollup is `cancelled`, but this run was NOT skipped, so
            # its jobs said something. Say WHICH, or the operator reads the word
            # "cancelled" and reaches for the old superseded-push reflex.
            verdict_id = (state.get("run") or {}).get("databaseId")
            note = next((n for n in state.get("cancelled_notes") or [] if (n.get("run") or {}).get("databaseId") == verdict_id), None)
            failing = ", ".join((note or {}).get("failing") or []) or "unnamed job(s)"
            if (note or {}).get("verdict") == civ.CANCELLED_INDETERMINATE:
                lines.append(
                    "   Its job list could NOT be read, so whether the cancel superseded a clean run or\n"
                    "   hid a real failure is unproven — that is not a green, and it is not a skip either (#3530)."
                )
            else:
                lines.append(
                    f"   A `cancelled` rollup is NOT a superseded push on this repo (#3530): the run's own jobs\n"
                    f"   carry a real failure — {failing}. Since #2009 the workflow concurrency group is unique\n"
                    "   per run; the only canceller left is the `ci-cd-deploy-<ref>` group evicting a PENDING\n"
                    "   Deploy, which cannot un-fail the validation jobs that already ran above it.\n"
                    "   Fix the failing job — do not wait for it to be superseded away."
                )
        if state.get("deploy_also_stranded"):
            lines.append(
                "   ⚠️  AND the deploy path is stranded (#1901): `Plan deployments` failed and\n"
                "   `Deploy` was skipped alongside the other red — fixing the failing job alone\n"
                "   will not deploy anything until the R8-ST6 Plan-red clears (pending\n"
                "   `bash deploy/cdk_deploy.sh <Stack>`, then a `deploy_all=true` dispatch)."
            )

    lines.extend(notices)

    # Young waiting runs ride along as a notice on any verdict.
    for r in state["waiting"]:
        if r in state["overdue_waiting"]:
            continue
        lines.append(
            f"ℹ️  {_fmt_run(r, now)} is awaiting production approval (normal post-merge; "
            f"becomes the #1901 stranded class at {STRANDED_WAIT_HOURS:g}h — action it via deploy/approve_deployment.sh)."
        )

    # #3212: name the concluded state in one machine-readable line so a consumer
    # can quote the tool rather than paraphrase it. Emitted whenever HEAD coverage
    # was evaluated at all — including on a red main, where it is context.
    if state.get("head_cov"):
        lines.append(f"{HEAD_COVERAGE_PREFIX} {head_coverage_state_name(state)} {(state.get('head_sha') or '')[:8] or '?'}")

    green_ok = kind == GREEN and head_coverage_ok(state)
    return (0 if green_ok else 1), "\n".join(lines)


REPO = "averagejoematt/life-platform"


def _gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


def diagnose_uncovered_head(head_sha: str) -> dict:
    """The impure half of the #2826 discriminator: fetch the fleet-level facts an
    `uncovered` HEAD needs, then classify. Returns `classify_zero_run_head`'s
    dict plus a `warnings` list of degrade notes for the caller to print.

    Shared by BOTH consumers — `main()` (the boot/wrap gate) and
    `main_head_coverage()` (the 15-minute cron) — deliberately: #3212 exists
    because the classification step lived inside one consumer, so the other
    could not reach it. A second copy would reproduce the bug on the next
    divergence.

    Never raises. An API read failure degrades to ZR_INDETERMINATE — never to a
    manufactured swallow, and never to a false path-filter-skip.
    """
    warnings: list[str] = []
    try:
        all_runs = _gh_json(["api", f"repos/{REPO}/actions/runs?head_sha={head_sha}&per_page=100"])["workflow_runs"]
    except Exception as e:  # noqa: BLE001 - execution error, never a false verdict either way
        return {
            "state": ZR_INDETERMINATE,
            "reason": f"could not read the all-workflow run list at {head_sha[:8]} ({str(e)[:80]})",
            "warnings": warnings,
        }

    changed_paths = None
    committer_login = None
    try:
        commit = _gh_json(["api", f"repos/{REPO}/commits/{head_sha}"])
        changed_paths = [f.get("filename") for f in (commit.get("files") or []) if f.get("filename")]
        # Same payload — no extra request. Used to spot a GITHUB_TOKEN push,
        # which never dispatches workflows (the reconcile-commit false positive).
        committer_login = ((commit.get("committer") or {}).get("login")) or ((commit.get("author") or {}).get("login"))
    except Exception as e:  # noqa: BLE001 - degrades to indeterminate via classify_zero_run_head, never to a false OK
        warnings.append(f"could not read changed files for {head_sha[:8]} ({str(e)[:80]}) — paths treated as unreadable.")

    try:
        with open(os.path.join(_REPO_ROOT, ".github", "workflows", CI_CD_WORKFLOW_FILE)) as f:
            ci_paths = ci_cd_push_paths(f.read())
    except Exception as e:  # noqa: BLE001 - an empty filter reads as "everything matches" (fail toward in-scope)
        warnings.append(f"could not read ci-cd.yml's `paths:` filter ({str(e)[:80]}) — treating as unrestricted.")
        ci_paths = []

    verdict = classify_zero_run_head(all_runs, changed_paths, ci_paths, committer_login=committer_login)
    verdict["warnings"] = warnings
    return verdict


def main() -> int:
    decoded = "--decoded" in sys.argv
    try:
        runs = _gh_json(
            [
                "run",
                "list",
                "--branch",
                "main",
                "--workflow",
                "CI/CD",
                "--limit",
                "20",
                "--json",
                "status,conclusion,headSha,databaseId,createdAt",
            ]
        )
    except Exception as e:
        print(f"⚠️  check_main_green: could not read run list ({e}) — decode manually (gh run list --branch main)")
        return 1

    # #2590: walk the failures newest-first, splitting REJECTED production
    # deployments (not verdicts) from real reds. The jobs of the run that ends
    # the walk are also what splits ordinary red from the R8-ST6 stranded-Plan
    # shape, so one probe serves both.
    def _probe(run: dict) -> tuple[list[dict] | None, list[dict] | None]:
        run_id = run.get("databaseId")
        if not run_id:
            return None, None
        jobs = approvals = None
        try:
            jobs = _gh_json(["run", "view", str(run_id), "--json", "jobs"]).get("jobs")
        except Exception as e:  # noqa: BLE001 - degrade to ordinary red, never to a false green
            print(f"⚠️  check_main_green: could not read jobs for run {run_id} ({e}) — treating as ordinary red")
        try:
            approvals = _gh_json(["api", f"repos/{REPO}/actions/runs/{run_id}/approvals"])
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  check_main_green: could not read approvals for run {run_id} ({e}) — treating as ordinary red")
        return jobs, approvals

    # #3530: a `cancelled` rollup is not a verdict-free supersession here — read
    # each one's OWN jobs before deciding whether it can be walked past.
    def _probe_jobs(run: dict) -> list[dict] | None:
        return civ.fetch_run_jobs(_gh_json, REPO, run.get("databaseId"))

    cancelled_verdicts, cancelled_notes = scan_cancelled(runs, _probe_jobs)

    rejected, jobs = scan_rejections(runs, _probe, cancelled_verdicts=cancelled_verdicts)

    # #2052: the phantom deploy wedge needs per-run JOB state, which `gh run list`
    # does not carry. Best-effort — a detector failure must never turn a readable
    # green/red verdict into a hard error, so it degrades to "wedge unknown".
    wedge = None
    try:
        import check_deploy_wedge  # noqa: PLC0415 - optional, same directory

        in_flight, jobs_by_run, pending_by_run = check_deploy_wedge.collect()
        wedge = check_deploy_wedge.classify_fleet(in_flight, jobs_by_run, pending_by_run)
    except Exception as e:  # noqa: BLE001
        print(
            f"⚠️  check_main_green: deploy-wedge detection unavailable ({e}) — run scripts/check_deploy_wedge.py by hand if a deploy looks stuck."
        )

    state = classify_pipeline(
        runs,
        latest_failure_jobs=jobs,
        deploy_wedge=wedge,
        rejected=rejected,
        cancelled_verdicts=cancelled_verdicts,
        cancelled_notes=cancelled_notes,
    )
    # #2762: the verdict must vouch for the sha main actually points at — read the
    # REMOTE head (never the local checkout, which may be stale or on a branch).
    try:
        state["head_sha"] = _gh_json(["api", f"repos/{REPO}/branches/main"])["commit"]["sha"]
    except Exception as e:  # noqa: BLE001 — fail-soft: coverage unverified, never a hard error
        state["head_sha"] = None
        state["head_sha_error"] = str(e)[:80]
    state["head_cov"] = head_coverage(runs, state["head_sha"])
    # #3212: an `uncovered` HEAD is FOUR different things — ask the #2826
    # discriminator instead of printing the swallowed-push text on all four.
    if state["head_cov"]["state"] == "uncovered" and state["head_sha"]:
        zr = diagnose_uncovered_head(state["head_sha"])
        for warning in zr.pop("warnings", []):
            print(f"⚠️  check_main_green: {warning}")
        state["head_zr"] = zr
    code, message = render(state)
    print(message)
    if code == 0:
        return 0
    if decoded:
        print("   --decoded acknowledged: the handover MUST carry the one-line `**Main:** …` decode.")
        return 0
    print(
        "   The wrap may not declare 'main GREEN'. Either fix it, or write the decode line\n"
        "   into the handover — `**Main:** <stranded|red> — <one-line cause>` — and re-run with --decoded."
    )
    return 1


def main_head_coverage() -> int:
    """#2826: the SCHEDULED consumer of `head_coverage()` — run unattended from
    `deploy-wedge-watch.yml`'s 15-minute cron so a swallowed push pages without
    waiting for a session to happen to run `main()`'s `/wrap` gate.

    Exit codes are deliberately THREE-WAY so this check cannot fail dark (the
    #2753 class the epic exists to close — an execution error must never read
    as "coverage OK", and must not be conflated with a CONFIRMED swallow either,
    since only the latter should page):

      0 = OK             — covered, pending, a proven path-filter-skip, or a
                            bot (GITHUB_TOKEN) push that cannot dispatch at all
      1 = SWALLOWED PUSH  — confirmed: the caller (the workflow step) should
                            fail loudly
      2 = INDETERMINATE   — an API read failed or the paths data was
                            unreadable; neither OK nor a confirmed swallow was
                            provable. Still non-zero (never silently "OK") but
                            distinct from exit 1 so an operator reading the run
                            history does not mistake "the check itself broke"
                            for "a push was actually swallowed."
    """
    try:
        ci_runs = _gh_json(
            [
                "run",
                "list",
                "--branch",
                "main",
                "--workflow",
                "CI/CD",
                "--limit",
                "20",
                "--json",
                "status,conclusion,headSha,databaseId,createdAt",
            ]
        )
    except Exception as e:  # noqa: BLE001 - execution error, never a false "OK"
        print(f"⚠️  head-coverage-check: could not read the CI/CD run list ({e}) — INDETERMINATE, not OK.")
        return 2

    try:
        head_sha = _gh_json(["api", f"repos/{REPO}/branches/main"])["commit"]["sha"]
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  head-coverage-check: could not read main's HEAD ({e}) — INDETERMINATE, not OK.")
        return 2

    def _named(concluded: str, code: int) -> int:
        # #3212: same machine-readable line the wrap gate prints, so both
        # consumers name their conclusion in one quotable vocabulary.
        print(f"{HEAD_COVERAGE_PREFIX} {concluded} {head_sha[:8]}")
        return code

    cov = head_coverage(ci_runs, head_sha)
    if cov["state"] != "uncovered":
        print(f"✅ head-coverage-check: HEAD {head_sha[:8]} is {cov['state']} — no action needed.")
        return _named(cov["state"], 0)

    # #3212: one shared fetch+classify step, called by BOTH consumers.
    verdict = diagnose_uncovered_head(head_sha)
    for warning in verdict.get("warnings", []):
        print(f"⚠️  head-coverage-check: {warning}")
    state = verdict["state"]
    if state == ZR_BOT_PUSH_NO_DISPATCH:
        print(f"✅ head-coverage-check: {head_sha[:8]} minted no CI/CD run — expected: {verdict['reason']}")
        return _named(state, 0)
    if state == ZR_PATH_FILTER_SKIP:
        print(f"✅ head-coverage-check: {head_sha[:8]} minted no CI/CD run — expected path-filter skip: {verdict['reason']}")
        return _named(state, 0)
    if state == ZR_SWALLOWED:
        print(f"🛑 SWALLOWED PUSH (#2826 class) at {head_sha[:8]}: {verdict['reason']}")
        print("   Recovery: workflow_dispatch ci-cd.yml on main (or re-push) so HEAD earns a real verdict.")
        return _named(state, 1)
    print(f"⚠️  head-coverage-check: {head_sha[:8]} — {verdict['reason']} — INDETERMINATE, not OK, not a confirmed swallow.")
    return _named(ZR_INDETERMINATE, 2)


def main_classify_sha(head_sha: str) -> int:
    """`--classify-sha <FULL-40-CHAR-SHA>` — print `diagnose_uncovered_head`'s
    verdict as JSON on stdout, for a NON-python consumer (#3219).

    Exists so `deploy/wait_pr_green.sh` can reach the #2826/#3212 classification
    instead of reimplementing it in bash. #3212 happened because that logic lived
    inside one consumer and the other could not call it; a bash re-derivation
    would be the same bug a third time. This adds no classification of its own —
    it is a stdout adapter over `diagnose_uncovered_head`, which owns both the
    full-40-char runs query and `classify_zero_run_head`.

    Refuses a short sha OUTRIGHT rather than querying with it: GitHub's Actions
    API returns an empty run list for a 7-char prefix, which would read as
    `swallowed` and self-confirm the very bug the caller is asking about.

    Exit: 0 = a verdict was produced (READ THE `state` FIELD — this is an
    instrument, not a gate; `swallowed` is still exit 0 here and it is the
    caller that decides what to do about it). 2 = the input was unusable.
    """
    if len(head_sha) != 40 or not all(c in "0123456789abcdef" for c in head_sha.lower()):
        print(
            json.dumps(
                {"state": ZR_INDETERMINATE, "reason": f"'{head_sha}' is not a full 40-char sha — refusing to query with a prefix (#3103)"}
            )
        )
        return 2
    print(json.dumps(diagnose_uncovered_head(head_sha)))
    return 0


if __name__ == "__main__":
    if "--head-coverage-check" in sys.argv:
        sys.exit(main_head_coverage())
    if "--classify-sha" in sys.argv:
        _i = sys.argv.index("--classify-sha")
        sys.exit(main_classify_sha(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(main())
