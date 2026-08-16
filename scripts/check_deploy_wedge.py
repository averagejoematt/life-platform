#!/usr/bin/env python3
"""scripts/check_deploy_wedge.py — detect a wedged CI/CD deploy (#2052, fifth recurrence).

WHAT THIS EXISTS FOR
--------------------
Five times in eleven days a CI/CD run has parked forever behind a phantom entry in a
GitHub `concurrency` group. Three salts (`-v2`, `-v3`, `-v4`) and one redesign were
shipped against it — all of them BLIND, because nothing ever measured the wedge while
it was happening. This is the measurement.

The 2026-08-02 redesign (#2009) moved the deploy-serialisation invariant off the
workflow and onto the `deploy` job. Its own comment predicted the consolation:

    "If a phantom EVER appears again after this, it can only be in the deploy group —
     and that is a much narrower thing to reason about than 'no CI at all'."

It got narrower and LESS legible. Every documented tell for this class keys on
**"0 jobs"** (`reference_push_ci_silent_death`, CONVENTIONS §4d). After the redesign a
wedged run has FIVE GREEN JOBS and a blocked `Deploy` — so every tell is now blind, and
the run reads as "waiting for approval" while no approval will ever be possible.

THE MEASUREMENT (2026-08-02 recurrence + live captures 2026-08-03)
------------------------------------------------------------------
Three in-flight states, as the Actions REST API actually reports them:

    state                     run.status   Deploy job.status   pending_deployments
    ------------------------  -----------  ------------------  -------------------
    awaiting approval         waiting      waiting             NON-EMPTY
    queued behind a holder    pending      pending             []
    PHANTOM WEDGE             pending      pending             []

The last two rows are **byte-identical**. No amount of staring at a single run can tell
them apart — which is precisely why five recurrences were misdiagnosed, and why the old
"is anything else in the group?" tell was directionally right even though its "0 jobs"
trigger no longer fires.

So the discriminator is necessarily FLEET-level, and it is exactly one question:

    Does any OTHER in-flight run on the same ref actually HOLD the deploy group?

A run holds it iff its `Deploy` job is `in_progress` (deploying now) or `waiting` (parked
at the environment gate — a waiting job still occupies the concurrency slot). If a run's
Deploy has been blocked past the threshold and NOTHING holds the group, the entry that
is blocking it does not correspond to any real run: that is the phantom.

WHY THE APPROVAL GATE NEVER OPENS
---------------------------------
GitHub evaluates job-level `concurrency` BEFORE the environment protection rule. A
concurrency-blocked deploy job therefore never reaches the gate, so `pending_deployments`
stays empty and there is literally nothing to approve. Evidence: the wedged Deploy job
ran zero steps, was never assigned a runner (`runner_id=0`), and `pending_deployments`
was empty for the full 12+ minutes while all five dependencies were green.

THE SIXTH WEDGE (2026-08-09, #2467)
-----------------------------------
The all-day wedge was misclassified as phantom because the holder scan read ONE bounded
recent-run page: the REAL holders were two 8-day-old gated runs (30727225837/30723876315)
still `waiting` with Deploy parked at the production gate — and a job parked at the gate
occupies the job-level `ci-cd-deploy-<ref>` slot. The scan now enumerates every
non-completed run status explicitly, paginated to exhaustion, with NO recency bound
(collect() below), so a gate-parked run of ANY age is named as the holder before
"phantom" can be concluded. A stale gate holder (>= STALE_GATE_REJECT_HOURS at the gate)
gets REJECT recovery, never approve (that would deploy the old sha it was minted from)
and never leave-waiting (that holds the whole fleet hostage — "GitHub expires them at
30d" was measured false at day 8).

WHAT THIS DOES NOT DO
---------------------
It does not touch `ci-cd.yml`'s concurrency semantics. `cancel-in-progress: false` on the
deploy group is load-bearing — it is the no-two-concurrent-deploys invariant — and the
observed failure is a GitHub-side queue-entry leak, not a consequence of those semantics.
Replacing the group with a self-managed SSM/DDB lock trades an opaque leak for one we own,
but introduces a strictly worse failure: a deploy job cancelled mid-flight leaves the lock
HELD, and clearing it then requires an AWS write. Detection first, measured recurrences,
then decide. See the PR for the full argument.

Usage:
  python3 scripts/check_deploy_wedge.py                 # classify; exit 1 on a wedge
  python3 scripts/check_deploy_wedge.py --json          # machine-readable verdict
  python3 scripts/check_deploy_wedge.py --threshold 15  # minutes blocked before alarming
  python3 scripts/check_deploy_wedge.py --recover       # ESCAPE HATCH: see below

`--recover` performs the documented recovery for a CONFIRMED phantom wedge only: cancel
the wedged run, then re-dispatch `ci-cd.yml` with `deploy_all=true` (a workflow_dispatch
carries no push diff, so change-detection would otherwise deploy nothing). It refuses to
act on any other verdict. It does NOT deploy — the re-dispatched run still stops at the
production approval gate like any other.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

REPO = "averagejoematt/life-platform"
WORKFLOW = "ci-cd.yml"
DEPLOY_JOB = "Deploy"

# Minutes a Deploy job may sit blocked with nothing holding the group before we call it
# a wedge. The observed transition Plan-complete -> waiting/in_progress is seconds
# (2026-08-03 live capture: Plan completed 15:48:30Z, Deploy reached `waiting` 15:52:10Z).
# The 2026-08-02 wedge was reported at 12 min and cancelled at 17 min. 10 minutes clears
# ordinary hosted-runner queueing by an order of magnitude while catching the wedge well
# inside the window where the tree is still current.
DEFAULT_THRESHOLD_MIN = 10.0

# Hours at the production gate before an OPEN gate is an incident rather than the normal
# post-merge state. Kept identical to check_main_green.STRANDED_WAIT_HOURS on purpose —
# the two gates must not disagree about when a wait becomes stranded.
STRANDED_WAIT_HOURS = 2.0

# Hours at the gate after which a waiting run is a STALE holder (#2467). Approving it
# would deploy the old sha it was minted from; leaving it waiting keeps the job-level
# deploy slot occupied and wedges every later run (the 2026-08-09 all-day wedge — two
# 8-day-old gated runs). Posture: fresh (< this) → action the gate on Matthew's say-so;
# stale (>= this) → REJECT its pending deployment.
STALE_GATE_REJECT_HOURS = 24.0

# GitHub reports a concurrency-blocked job as `pending`; the web UI labels it "queued"
# and older API responses have used that spelling. Accept both — the issue body recorded
# the UI wording, and a classifier that only knew one spelling would silently no-op.
BLOCKED_JOB_STATUSES = frozenset({"pending", "queued"})

# A job in one of these states OCCUPIES the deploy concurrency slot.
HOLDING_JOB_STATUSES = frozenset({"in_progress", "waiting"})

# Verdict kinds — module constants so tests, the workflow and check_main_green share one
# vocabulary (the #1901 lesson: a decode contract that is retyped per consumer drifts).
HEALTHY = "healthy"
AWAITING_APPROVAL = "awaiting-approval"
STRANDED_APPROVAL = "stranded-approval"
QUEUED_BEHIND = "queued-behind"
PHANTOM_WEDGE = "phantom-wedge"
# (#2791) A missing/unparseable job timestamp is NOT "0 hours old". Before this state
# existed, `_parse_iso` returning None fed `(blocked_min or 0.0)` and silently read as a
# freshly-parked, healthy-looking wait — disarming the #2467 stale-holder detection for
# exactly the malformed-data case most likely to accompany a wedged state. This is the
# explicit alternative: age genuinely unknown, reported — never coerced to zero.
UNKNOWN_AGE = "unknown-age"

# Worst-first. The fleet verdict is the worst per-run verdict. UNKNOWN_AGE sits ABOVE
# STRANDED_APPROVAL on purpose — it must be at least as loud as a confirmed stale holder,
# never quieter (#2791): an unresolvable age cannot be ruled out as the #2467 shape.
_SEVERITY = [HEALTHY, AWAITING_APPROVAL, QUEUED_BEHIND, STRANDED_APPROVAL, UNKNOWN_AGE, PHANTOM_WEDGE]


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _minutes_since(ts: str | None, now: datetime) -> float | None:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 60.0


def deploy_job(jobs: list[dict]) -> dict | None:
    """The `Deploy` job for a run, or None if it has not been created yet.

    Matched exactly, not by prefix: "Deploy-critical tests" is a DIFFERENT job that
    runs early and always completes, and a prefix match would read it as the deploy.
    """
    for job in jobs or []:
        if job.get("name") == DEPLOY_JOB:
            return job
    return None


def holders(runs: list[dict], jobs_by_run: dict, ref: str, exclude_run_id) -> list[dict]:
    """In-flight runs on `ref` whose Deploy job actually occupies the concurrency slot.

    This is the whole discriminator. `ci-cd.yml` triggers only on push-to-main and
    workflow_dispatch, so `head_branch` is an exact proxy for the `github.ref` that
    names the group (`ci-cd-deploy-${{ github.ref }}`) — there is no pull_request
    trigger whose head_branch would diverge from its ref.
    """
    out = []
    for run in runs:
        if run.get("id") == exclude_run_id:
            continue
        if run.get("head_branch") != ref:
            continue
        if run.get("status") == "completed":
            continue
        job = deploy_job(jobs_by_run.get(str(run.get("id")), []))
        if job is not None and job.get("status") in HOLDING_JOB_STATUSES:
            out.append(run)
    return out


def classify_run(
    run: dict, jobs: list[dict], pending: list[dict], runs: list[dict], jobs_by_run: dict, now: datetime, threshold_min: float
) -> dict:
    """Classify ONE in-flight run's deploy state. Pure — fixture-tested offline."""
    run_id = run.get("id")
    verdict = {
        "run_id": run_id,
        "sha": (run.get("head_sha") or "")[:8],
        "ref": run.get("head_branch"),
        "run_status": run.get("status"),
        "kind": HEALTHY,
        "blocked_minutes": None,
        "holders": [],
        "detail": "",
    }

    if run.get("status") == "completed":
        verdict["detail"] = "run completed — no live deploy state"
        return verdict

    job = deploy_job(jobs)
    if job is None:
        # Validation jobs still running; the deploy job does not exist yet. Also the
        # shape of a run whose Plan concluded has_deploys=false (Deploy skipped).
        verdict["detail"] = "no Deploy job yet — validation still in flight"
        return verdict

    status = job.get("status")
    blocked_min = _minutes_since(job.get("started_at"), now)
    verdict["blocked_minutes"] = round(blocked_min, 1) if blocked_min is not None else None
    verdict["deploy_job_status"] = status

    if status == "in_progress":
        verdict["detail"] = "Deploy is running"
        return verdict

    if status == "completed":
        verdict["detail"] = f"Deploy already concluded ({job.get('conclusion')})"
        return verdict

    if status == "waiting":
        # The environment gate is OPEN. pending_deployments corroborates it; if it is
        # empty here GitHub is mid-transition, which is not an incident on its own.
        approvable = bool(pending)
        if blocked_min is None:
            # (#2791) `started_at` is missing or unparseable — age is genuinely UNKNOWN,
            # not zero. Coercing this to 0h via `(blocked_min or 0.0)` used to read as a
            # freshly-parked, normal wait forever — silently disarming the #2467
            # stale-holder detection for exactly the malformed-data case most likely to
            # accompany a wedged state. Report it, at least as loud as a stale holder.
            verdict["kind"] = UNKNOWN_AGE
            verdict["gate_open"] = True
            verdict["can_approve"] = approvable
            verdict["detail"] = (
                "Deploy is `waiting` at the `production` gate but its job `started_at` is missing "
                "or unparseable — how long it has been parked cannot be computed, so it can be "
                "neither cleared as fresh nor confirmed stale (#2791). Treat as AT LEAST as urgent "
                f"as a STALE gate holder (#2467): decode manually (`gh run view {run_id} --json "
                "jobs`) before approving or rejecting — do NOT assume it is safe to approve just "
                "because the age could not be computed."
            )
            return verdict
        wait_h = blocked_min / 60.0
        if wait_h >= STALE_GATE_REJECT_HOURS:
            # #2467: a run parked at the gate for this long is pinned to a stale sha,
            # and while it waits it OCCUPIES the job-level deploy slot — this exact
            # shape held the fleet hostage for 8 days and read as "phantom" to a
            # recency-bounded scan.
            verdict["kind"] = STRANDED_APPROVAL
            verdict["stale_holder"] = True
            verdict["detail"] = (
                f"Deploy has been parked at the `production` gate for {wait_h / 24.0:.1f} DAYS — a STALE gate "
                "holder (#2467). While it waits it occupies the job-level deploy slot and wedges every later run. "
                "Recovery: REJECT it — `bash deploy/reject_deployment.sh " + str(run_id) + "` "
                "(POST …/actions/runs/<id>/pending_deployments with state=rejected: the run dies, nothing stale "
                "deploys, the slot frees). Do NOT approve it — that deploys the old sha it was minted from — and "
                "do NOT leave it waiting: GitHub does not reliably expire it (measured alive at day 8)."
            )
        elif wait_h >= STRANDED_WAIT_HOURS:
            verdict["kind"] = STRANDED_APPROVAL
            verdict["detail"] = (
                f"Deploy has been at the `production` approval gate for {wait_h:.1f}h. "
                "The gate is OPEN — a human simply has not actioned it. "
                "Recovery: `bash deploy/approve_deployment.sh " + str(run_id) + "`. "
                "Do NOT cancel it: a cancelled run strands its deploy."
            )
        else:
            verdict["kind"] = AWAITING_APPROVAL
            verdict["detail"] = (
                f"Deploy awaiting production approval for {wait_h:.1f}h — normal post-merge state (stranded at {STRANDED_WAIT_HOURS:g}h)."
            )
        verdict["gate_open"] = True
        verdict["can_approve"] = approvable
        return verdict

    if status in BLOCKED_JOB_STATUSES:
        verdict["gate_open"] = False
        if blocked_min is not None and blocked_min < threshold_min:
            verdict["detail"] = (
                f"Deploy blocked {blocked_min:.1f}m — under the {threshold_min:g}m threshold, still plausibly ordinary queueing."
            )
            return verdict

        held_by = holders(runs, jobs_by_run, run.get("head_branch"), run_id)
        verdict["holders"] = [h.get("id") for h in held_by]

        if held_by:
            verdict["kind"] = QUEUED_BEHIND
            descs, stale_ids, unknown_ids = [], [], []
            for h in held_by:
                hid = h.get("id")
                hjob = deploy_job(jobs_by_run.get(str(hid), []))
                h_min = _minutes_since((hjob or {}).get("started_at"), now)
                if hjob is not None and hjob.get("status") == "waiting" and h_min is None:
                    # (#2791) a gate-parked holder with NO computable age must not
                    # silently fall through to "not stale" (the old `elif ... is not
                    # None` guard skipped it entirely) — it is genuinely unknown, and
                    # unknown cannot be ruled out as the #2467 stale-holder shape.
                    unknown_ids.append(hid)
                    descs.append(f"{hid} (Deploy parked at the gate — `started_at` missing/unparseable, UNKNOWN AGE, #2791)")
                elif hjob is not None and hjob.get("status") == "waiting" and h_min is not None and h_min >= STALE_GATE_REJECT_HOURS * 60.0:
                    stale_ids.append(hid)
                    descs.append(f"{hid} (Deploy parked at the gate {h_min / 1440.0:.1f}d — STALE holder, #2467)")
                elif h_min is not None and hjob is not None:
                    descs.append(f"{hid} (Deploy {hjob.get('status')} {h_min:.0f}m)")
                else:
                    descs.append(str(hid))
            verdict["detail"] = (
                f"Deploy blocked {blocked_min:.1f}m behind run {', '.join(descs)}, which really does hold "
                "the deploy group. This is the invariant working, NOT a wedge — resolve the "
                "holder and this run proceeds on its own."
            )
            if stale_ids:
                verdict["detail"] += (
                    " A STALE holder gets REJECTED — never approved (stale sha), never left waiting "
                    "(it holds the deploy slot): " + " ".join(f"`bash deploy/reject_deployment.sh {i}`" for i in stale_ids) + " (#2467)."
                )
            if unknown_ids:
                verdict["detail"] += (
                    " A holder with UNKNOWN age (missing/unparseable `started_at`) cannot be cleared as "
                    "fresh — decode manually before actioning: "
                    + " ".join(f"`gh run view {i} --json jobs`" for i in unknown_ids)
                    + " (#2791)."
                )
            if not stale_ids and not unknown_ids:
                verdict["detail"] += " Fresh holder: approve or let it finish (`bash deploy/approve_deployment.sh <run_id>`)."
            return verdict

        verdict["kind"] = PHANTOM_WEDGE
        verdict["detail"] = (
            f"PHANTOM WEDGE: Deploy has been blocked {blocked_min:.1f}m and NOTHING holds the "
            "deploy group — no other in-flight run on this ref has a Deploy that is in_progress "
            "or waiting. The blocking entry corresponds to no real run. `pending_deployments` is "
            "empty and will stay empty: GitHub evaluates concurrency BEFORE the environment rule, "
            "so this deploy never reaches the gate and there is nothing to approve. It reads as "
            "'waiting for approval' in the UI and it is not. "
            "Recovery: `gh run cancel " + str(run_id) + "` then "
            "`gh workflow run ci-cd.yml --ref main -f deploy_all=true` "
            "(or `python3 scripts/check_deploy_wedge.py --recover`)."
        )
        return verdict

    verdict["detail"] = f"Deploy in unrecognised status {status!r} — decode manually"
    return verdict


def classify_fleet(
    runs: list[dict], jobs_by_run: dict, pending_by_run: dict, now: datetime | None = None, threshold_min: float = DEFAULT_THRESHOLD_MIN
) -> dict:
    """Classify every in-flight run. Returns {"kind", "verdicts"}. Pure."""
    now = now or datetime.now(timezone.utc)
    verdicts = []
    for run in runs:
        if run.get("status") == "completed":
            continue
        rid = str(run.get("id"))
        verdicts.append(
            classify_run(
                run,
                jobs_by_run.get(rid, []),
                pending_by_run.get(rid, []),
                runs,
                jobs_by_run,
                now,
                threshold_min,
            )
        )

    worst = HEALTHY
    for v in verdicts:
        if _SEVERITY.index(v["kind"]) > _SEVERITY.index(worst):
            worst = v["kind"]
    return {"kind": worst, "verdicts": verdicts}


def render(state: dict) -> tuple[int, str]:
    """(exit_code, message). Exit 1 only for states that need a human NOW. Pure."""
    kind = state["kind"]
    lines: list[str] = []

    if kind == PHANTOM_WEDGE:
        lines.append("🛑 PHANTOM DEPLOY WEDGE (#2052 class) — the deploy will NEVER start on its own.")
    elif kind == UNKNOWN_AGE:
        lines.append(
            "🛑 UNKNOWN-AGE DEPLOY STATE (#2791) — a wait/holder timestamp is missing or unparseable; "
            "cannot rule out a #2467-class stale wedge."
        )
    elif kind == STRANDED_APPROVAL:
        lines.append("🛑 STRANDED PRODUCTION APPROVAL (#1901 class) — the gate is open and unactioned.")
    elif kind == QUEUED_BEHIND:
        lines.append("ℹ️  A deploy is queued behind a real holder — the serialisation invariant working as designed.")
    elif kind == AWAITING_APPROVAL:
        lines.append("ℹ️  A deploy is awaiting production approval — normal post-merge state.")
    else:
        lines.append("✅ No wedged deploy — every in-flight run's deploy path is progressing or unblocked.")

    for v in state["verdicts"]:
        if v["kind"] == HEALTHY:
            continue
        lines.append(f"   run {v['run_id']} sha {v['sha']} [{v['kind']}] — {v['detail']}")

    if kind == PHANTOM_WEDGE:
        lines.append(
            "   Note: 'nothing holds the group' is inferred from the in-flight run list. If a\n"
            "   hosted-runner outage is in progress, an ordinary queue can look the same — check\n"
            "   githubstatus.com before recovering. Everything else about this state is measured."
        )

    return (1 if kind in (PHANTOM_WEDGE, STRANDED_APPROVAL, UNKNOWN_AGE) else 0), "\n".join(lines)


# ── Last-mile alerting (#2149) ───────────────────────────────────────────────
#
# Detection was proven by #2052; the last mile — getting a human alerted — was
# missing. A red scheduled workflow is a passive channel (nobody has the tab
# open). On a CONFIRMED wedge/stranded-approval this fires the SAME
# `repository_dispatch` `urgent_alarm` event `remediation_dispatcher_lambda.py`
# already fires for urgent CloudWatch alarms — `remediation-agent.yml` already
# listens for exactly that event type and sends the curated triage email. This
# piggybacks that existing channel; it does not invent a new one (no SES call,
# no new listener workflow, no new AWS surface — this workflow holds no AWS
# credentials at all and must not gain any just to write a marker).
#
# Throttle/dedup: this workflow runs every 15 minutes, so a single episode
# would otherwise refire ~36 times over a 9h wedge (the 2026-08-05 incident: 6
# reds over 9h even at the coarser hourly cadence a red run implies). State is
# kept GitHub-native — an issue carrying the `deploy-wedge-alert` label, same
# shape as the #1447 advisory-failure-issue pattern (`scripts/advisory_failure_
# issue.py`) — rather than an AWS-written SSM/DDB marker, which is exactly what
# that existing prior art already does for "don't re-notify every red run."

ALERT_KINDS = frozenset({STRANDED_APPROVAL, PHANTOM_WEDGE, UNKNOWN_AGE})
ALERT_EVENT_TYPE = "urgent_alarm"  # the exact type remediation-agent.yml already listens for
ALERT_LABEL = "deploy-wedge-alert"
ALERT_LABEL_COLOR = "B60205"
ALERT_LABEL_DESCRIPTION = "Tracks the throttle state for an active CI/CD deploy-wedge alert (#2149) — auto-closed on recovery"
# 24h re-arm: generous relative to the ~9h observed incident span, so ordinary
# throttling (not this fallback) is what collapses the normal case to 1 alert.
# The primary re-arm is immediate: a later HEALTHY/QUEUED_BEHIND run closes the
# tracking issue, so the NEXT distinct wedge (a new run id) alerts right away
# regardless of this window.
ALERT_REARM_HOURS = 24.0
ALERT_MARKER_PREFIX = "<!-- deploy-wedge-alert:"
ALERT_MARKER_SUFFIX = "-->"


def alert_candidate(state: dict) -> dict | None:
    """The verdict that should page a human, or None. Pure."""
    for v in state.get("verdicts", []):
        if v.get("kind") in ALERT_KINDS:
            return v
    return None


def build_alert_marker(run_id, alerted_at_iso: str) -> str:
    """HTML-comment marker embedding throttle state in the tracking issue body —
    same shape as advisory_failure_issue.py's dedup marker, carrying state
    instead of only a slug."""
    payload = json.dumps({"run_id": run_id, "alerted_at": alerted_at_iso})
    return f"{ALERT_MARKER_PREFIX}{payload}{ALERT_MARKER_SUFFIX}"


def parse_alert_marker(body: str | None) -> dict | None:
    """Recover {"run_id", "alerted_at"} from a tracking issue body, or None if
    absent or malformed. Never raises — a corrupt/foreign issue body must not
    crash the classifier; it just reads as 'no prior state' (see
    should_fire_alert: that fails toward ALERTING, not toward silence)."""
    if not body:
        return None
    start = body.find(ALERT_MARKER_PREFIX)
    if start == -1:
        return None
    end = body.find(ALERT_MARKER_SUFFIX, start)
    if end == -1:
        return None
    raw = body[start + len(ALERT_MARKER_PREFIX) : end].strip()
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(state, dict) or "run_id" not in state or "alerted_at" not in state:
        return None
    return state


def should_fire_alert(run_id, now: datetime, last_state: dict | None, rearm_hours: float = ALERT_REARM_HOURS) -> bool:
    """The whole throttle decision. Pure, offline-tested.

    Fires when:
      - no marker exists yet (first alert of a fresh episode), OR
      - the marker names a DIFFERENT run id (a new episode — the previous
        wedge cleared/was recovered and a fresh one appeared), OR
      - the marker is for the SAME run id but was last alerted >= rearm_hours
        ago (the long-window fallback re-arm).

    Does NOT fire when the same run id was already alerted within the window —
    this is what collapses N reds over one episode into exactly 1 alert.
    """
    if last_state is None:
        return True
    if last_state.get("run_id") != run_id:
        return True
    alerted_at = _parse_iso(last_state.get("alerted_at"))
    if alerted_at is None:
        return True  # corrupt timestamp — fail toward alerting, not toward silence
    return (now - alerted_at).total_seconds() / 3600.0 >= rearm_hours


def build_dispatch_payload(verdict: dict, now: datetime) -> dict:
    """The repository_dispatch client_payload. Same top-level shape
    `remediation_dispatcher_lambda.py` already sends for a CloudWatch alarm
    (alarm_name/state/reason/timestamp) — `remediation/agent.py`'s existing
    `signals["urgent"]` handling needs no changes to consume this. `reason`
    carries the EXACT text check_deploy_wedge.py already prints: the run id,
    the gate age, and the one-line recovery command (`verdict["detail"]` —
    built in classify_run above)."""
    return {
        "alarm_name": "deploy-wedge-watch",
        "state": "ALARM",
        "reason": verdict.get("detail", ""),
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": verdict.get("run_id"),
        "kind": verdict.get("kind"),
        "blocked_minutes": verdict.get("blocked_minutes"),
    }


# ── Alert I/O (thin `gh` wrappers — prose-verified, not unit tested; every
# caller in maybe_alert() below is exception-safe so a filing hiccup can never
# turn a correctly-detected wedge into a false "healthy" exit code). ──────────


def _find_alert_issue():
    issues = _gh_api(f"repos/{REPO}/issues?state=open&labels={ALERT_LABEL}&per_page=10")
    for issue in issues:
        if "pull_request" in issue:
            continue
        return issue
    return None


def _ensure_alert_label():
    try:
        _gh_api(f"repos/{REPO}/labels/{ALERT_LABEL}")
    except subprocess.CalledProcessError:
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPO}/labels",
                "-f",
                f"name={ALERT_LABEL}",
                "-f",
                f"color={ALERT_LABEL_COLOR}",
                "-f",
                f"description={ALERT_LABEL_DESCRIPTION}",
            ],
            check=False,
            timeout=30,
        )


def _dispatch_urgent_alarm(payload: dict) -> None:
    body = json.dumps({"event_type": ALERT_EVENT_TYPE, "client_payload": payload})
    subprocess.run(
        ["gh", "api", f"repos/{REPO}/dispatches", "--method", "POST", "--input", "-"],
        input=body,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def _upsert_alert_issue(verdict: dict, now: datetime, existing) -> None:
    marker = build_alert_marker(verdict.get("run_id"), now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    title = "[auto-filed] CI/CD deploy wedge — production deploys are stalled"
    body = (
        "A CONFIRMED deploy wedge/stranded approval fired the urgent-alarm dispatch "
        f"(#2149) — see the remediation-agent curated email for the triage.\n\n{verdict.get('detail', '')}\n\n{marker}\n"
    )
    if existing is None:
        _ensure_alert_label()
        subprocess.run(
            ["gh", "api", f"repos/{REPO}/issues", "-f", f"title={title}", "-f", f"body={body}", "-f", f"labels[]={ALERT_LABEL}"],
            check=False,
            timeout=30,
        )
    else:
        subprocess.run(
            ["gh", "api", f"repos/{REPO}/issues/{existing['number']}", "--method", "PATCH", "-f", f"body={body}"],
            check=False,
            timeout=30,
        )


def _close_alert_issue(existing, now: datetime) -> None:
    if existing is None:
        return
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    subprocess.run(
        [
            "gh",
            "api",
            f"repos/{REPO}/issues/{existing['number']}/comments",
            "-f",
            f"body=Recovered — {stamp}. Deploy wedge cleared; re-armed for the next episode.",
        ],
        check=False,
        timeout=30,
    )
    subprocess.run(
        ["gh", "api", f"repos/{REPO}/issues/{existing['number']}", "--method", "PATCH", "-f", "state=closed"],
        check=False,
        timeout=30,
    )


def maybe_alert(state: dict, now: datetime | None = None) -> str:
    """Best-effort — must NEVER raise. Alerting plumbing must not affect the
    detector's own exit code (render() already decided that from `state`
    alone). Returns a short status string for the run log."""
    now = now or datetime.now(timezone.utc)
    try:
        existing = _find_alert_issue()
    except Exception as e:  # noqa: BLE001 - read failure must not block detection
        return f"alert-skipped: could not read tracking issue ({e})"

    verdict = alert_candidate(state)
    try:
        if verdict is None:
            if existing is not None:
                _close_alert_issue(existing, now)
                return "alert-rearmed: closed tracking issue"
            return "alert-skip: healthy, no tracking issue"

        last = parse_alert_marker(existing.get("body") if existing else None)
        if not should_fire_alert(verdict.get("run_id"), now, last):
            return f"alert-throttled: run {verdict.get('run_id')} already alerted this episode"

        payload = build_dispatch_payload(verdict, now)
        _dispatch_urgent_alarm(payload)
        _upsert_alert_issue(verdict, now, existing)
        return f"alert-fired: run {verdict.get('run_id')} ({verdict.get('kind')})"
    except Exception as e:  # noqa: BLE001 - alerting is best-effort by design
        return f"alert-error: {e}"


def _gh_api(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60, check=True).stdout
    return json.loads(out)


# Every status the Actions API can report for a run that is not `completed`. The holder
# scan enumerates EACH of these explicitly, paginated to exhaustion (#2467): the old scan
# read one bounded recent-run page, so the 2026-08-09 wedge's REAL holders — two 8-day-old
# gated runs still `waiting` at the production gate — were invisible, and the wedge was
# misclassified as phantom. A recency-bounded window is not a holder scan.
IN_FLIGHT_RUN_STATUSES = ("waiting", "action_required", "in_progress", "queued", "requested", "pending")

_RUNS_PAGE_SIZE = 100
# A hard stop against a pathological API loop, NOT a recency window: 10 pages × 100 runs
# PER STATUS. Real in-flight run counts are single digits.
_RUNS_MAX_PAGES = 10


def _list_runs(status: str | None, page_size: int = _RUNS_PAGE_SIZE, max_pages: int = _RUNS_MAX_PAGES) -> list[dict]:
    """Runs of the workflow with `status` (None = any), paginated to exhaustion (#2467)."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        path = f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page={page_size}&page={page}"
        if status is not None:
            path += f"&status={status}"
        batch = _gh_api(path).get("workflow_runs", [])
        out.extend(batch)
        if len(batch) < page_size:
            break
    return out


def collect(limit: int = 20) -> tuple[list[dict], dict, dict]:
    """Fetch ALL in-flight runs + their jobs + pending_deployments from the live API.

    Two sweeps, merged by run id (#2467):
      1. the recent window (`limit` newest runs, any status) — catches a run GitHub is
         mid-transition on, whatever status string it happens to carry;
      2. an explicit, exhaustively-paginated enumeration of every non-completed status —
         so a gate-parked `waiting` run of ANY age is seen. This is the sweep the
         2026-08-09 wedge was missing: its two 8-day-old holders sat far outside any
         recent-run window, so the scan read "no holder" and called a real gate-park
         "phantom".
    """
    by_id: dict = {}
    for run in _list_runs(None, page_size=limit, max_pages=1):
        by_id[run.get("id")] = run
    for status in IN_FLIGHT_RUN_STATUSES:
        for run in _list_runs(status):
            by_id.setdefault(run.get("id"), run)
    in_flight = sorted(
        (r for r in by_id.values() if r.get("status") != "completed"),
        key=lambda r: str(r.get("created_at") or ""),
        reverse=True,
    )
    jobs_by_run: dict = {}
    pending_by_run: dict = {}
    for run in in_flight:
        rid = str(run.get("id"))
        jobs_by_run[rid] = _gh_api(f"repos/{REPO}/actions/runs/{rid}/jobs?per_page=100").get("jobs", [])
        try:
            pending_by_run[rid] = _gh_api(f"repos/{REPO}/actions/runs/{rid}/pending_deployments")
        except subprocess.CalledProcessError:
            pending_by_run[rid] = []
    return in_flight, jobs_by_run, pending_by_run


def recover(state: dict) -> int:
    """Escape hatch — the documented recovery, for a CONFIRMED phantom wedge only."""
    wedged = [v for v in state["verdicts"] if v["kind"] == PHANTOM_WEDGE]
    if not wedged:
        print(f"--recover refused: verdict is {state['kind']!r}, not {PHANTOM_WEDGE!r}. Nothing to recover.")
        return 1
    for v in wedged:
        print(f"Cancelling wedged run {v['run_id']} …")
        subprocess.run(["gh", "run", "cancel", str(v["run_id"]), "--repo", REPO], check=False, timeout=60)
    print("Re-dispatching ci-cd.yml with deploy_all=true (a dispatch has no push diff for change detection) …")
    subprocess.run(
        ["gh", "workflow", "run", WORKFLOW, "--repo", REPO, "--ref", "main", "-f", "deploy_all=true"],
        check=True,
        timeout=60,
    )
    print("Re-dispatched. It still stops at the production approval gate — approve with deploy/approve_deployment.sh.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect a wedged CI/CD deploy (#2052).")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_MIN, help="minutes blocked before alarming")
    ap.add_argument("--json", action="store_true", help="emit the verdict as JSON")
    ap.add_argument("--recover", action="store_true", help="cancel + re-dispatch on a CONFIRMED phantom wedge")
    ap.add_argument(
        "--alert",
        action="store_true",
        help="(#2149) on a CONFIRMED wedge, fire the throttled repository_dispatch urgent_alarm; no-op otherwise",
    )
    args = ap.parse_args()

    try:
        runs, jobs_by_run, pending_by_run = collect()
    except Exception as e:  # noqa: BLE001 - any API failure is "decode manually"
        print(f"⚠️  check_deploy_wedge: could not read the Actions API ({e}) — decode manually.")
        return 1

    state = classify_fleet(runs, jobs_by_run, pending_by_run, threshold_min=args.threshold)
    code, message = render(state)

    if args.json:
        print(json.dumps(state, indent=2, default=str))
    else:
        print(message)

    if args.alert:
        # Best-effort by construction (maybe_alert never raises) — the exit code
        # below is decided from `state` alone, same as without this flag.
        print(maybe_alert(state))

    if args.recover:
        return recover(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
