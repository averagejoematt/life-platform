"""
remediation/drift_report.py — surface the weekly drift sentinel (#394) in the agent's
curated report.

The drift sentinel (deploy/drift_sentinel.py) runs as a weekly step in the remediation
workflow and persists its findings to s3://<bucket>/drift-log/latest.json. This module
is the read side for agent.py's one curated report (the auto-mode email path in the
retired automerge.py went with the mode, #2833), so the drift status lands there:

  * as_signal(record)  → a needs-human signal when there is real drift (never auto-fix:
    infra drift is resolved by a human running `cdk deploy`, on the denylist by design).
  * status_html(record) → a one-line status rendered on EVERY report — a clean week
    reports explicitly clean (loud empty state), a drifted/degraded week is loud. AC4:
    the report is never silent about drift.
  * superseded_cfn_stacks(record, cfn) → the stacks a LATER deploy already fixed (#3508).
  * quota_html(record) → the GitHub Actions quota/billing glance (#1334, #1453),
    rendered on EVERY report the same way — real minutes-used-vs-allowance and a 70%
    warn line when the billing API is reachable, a labeled "unavailable" reason when
    it isn't (the workflow's default token lacks the `user` scope), plus the top
    wall-clock-consuming workflows over the trailing 7 days either way.
"""

from __future__ import annotations

import json
from datetime import date, datetime

LOG_KEY = "drift-log/latest.json"


def read_latest(s3, bucket):
    """Cheap S3 GET of the latest drift record; fail-soft to None."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=LOG_KEY)
        rec = json.loads(obj["Body"].read().decode())
        return rec if isinstance(rec, dict) else None
    except Exception as e:  # noqa: BLE001
        print(f"[warn] drift findings: {e}")
        return None


def _record_date(record):
    """The sentinel run date on a record, as a `date`. None when absent/unparseable."""
    raw = (record or {}).get("date")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _drifted_stack_names(record):
    """The stacks the cfn_drift check actually flagged (not the ones it found clean)."""
    cfn = ((record or {}).get("checks") or {}).get("cfn_drift") or {}
    stacks = cfn.get("stacks")
    if not isinstance(stacks, dict):
        return []
    return sorted(name for name, st in stacks.items() if isinstance(st, dict) and st.get("status") == "drift")


def superseded_cfn_stacks(record, cfn_client):
    """{stack_name: LastUpdatedTime} for every stack the record flagged as drifted that has
    been REDEPLOYED since the record was written (#3508).

    The agent reads `drift-log/latest.json`, which under the old Monday-only sentinel guard
    could be two days stale: the 2026-09-04 17:49Z report carried a 09-02 record naming six
    drifted stacks, all six of which had been redeployed at 16:32–16:36Z that same morning.
    A drift finding a later `cdk deploy` already answered is not a finding; presenting it as
    one costs a human the triage AND teaches them to discount the section.

    Comparison is by DATE, deliberately conservative: a redeploy later on the record's own
    day is not provably after the drift read, so only a strictly later day counts.
    """
    drifted = _drifted_stack_names(record)
    rec_date = _record_date(record)
    if not drifted or rec_date is None or cfn_client is None:
        return {}
    out = {}
    for name in drifted:
        try:
            stacks = cfn_client.describe_stacks(StackName=name).get("Stacks") or []
        except Exception as e:  # noqa: BLE001 — an unreadable stack is NOT a superseded one
            print(f"[warn] describe-stacks {name}: {e}")
            continue
        if not stacks:
            continue
        updated = stacks[0].get("LastUpdatedTime") or stacks[0].get("CreationTime")
        if isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except ValueError:
                continue
        if not isinstance(updated, datetime):
            continue
        if updated.date() > rec_date:
            out[name] = updated.isoformat()
    return out


def as_signal(record, cfn_client=None):
    """The drift record as a triage signal — only when it's actually flagging drift.

    Degraded (a check couldn't run) and clean are NOT actionable signals — they show in
    the status line but don't spin up an agentic triage run.

    #3508: `cfn_client` (optional) lets the signal drop a cfn_drift section that a later
    deploy already superseded. Every drifted stack redeployed after the record's date ->
    the section is stale, not actionable; ANY stack still un-redeployed keeps it, because a
    partially-answered finding is still a finding."""
    if not record or record.get("status") != "drift":
        return None
    checks = record.get("checks", {})
    flagging = {k: v for k, v in checks.items() if v.get("status") == "drift"}
    superseded = superseded_cfn_stacks(record, cfn_client)
    drifted = _drifted_stack_names(record)
    if "cfn_drift" in flagging and drifted and set(superseded) == set(drifted):
        flagging.pop("cfn_drift")
    if not flagging:
        # #3207 defence-in-depth: a record whose only non-clean surfaces are `pending`
        # must never spin up a needs-human triage run. If the top-level status ever says
        # drift while no check does, there is nothing for a human to act on here.
        return None
    return {
        "status": "drift",
        # #3508: the date is now stamped as `record_date` too, named for what it is — the
        # summary line reads as "now" otherwise, and this record may be days old.
        "date": record.get("date"),
        "record_date": record.get("date"),
        "summary": record.get("summary"),
        "flagging": flagging,
        "superseded_stacks": superseded,
        # The fix is always operator-run `cdk deploy` / policy repair — never auto-fixable.
        "class": "needs-human",
    }


def status_html(record, cfn_client=None):
    """One-line HTML status for the report. Always renders when a record exists.

    #3508: `cfn_client` (optional) adds an explicit superseded line, so a reader is never
    shown a stack as drifted when a later deploy has already answered it."""
    if not record:
        return ""
    status = record.get("status", "unknown")
    record_date = record.get("date", "?")
    summary = record.get("summary", "")
    icon = {"clean": "🟢", "drift": "🔴", "degraded": "🟡"}.get(status, "·")
    label = {"clean": "in sync", "drift": "DRIFT", "degraded": "degraded"}.get(status, status)
    html = f"<h3>{icon} Infra drift sentinel ({label}, checked {record_date})</h3>" f"<p>{summary}</p>"
    superseded = superseded_cfn_stacks(record, cfn_client)
    if superseded:
        named = ", ".join(f"<code>{k}</code> (redeployed {v})" for k, v in sorted(superseded.items()))
        html += (
            f"<p><b>already superseded (not actionable):</b> this record is from {record_date}; "
            f"{named}. Re-run the sentinel before acting on the stack list above.</p>"
        )
    # #1320 fail-soft honesty: a GitHub posture surface the current credential can't
    # read surfaces ONCE as a single needs-owner line (naming the exact fine-grained
    # PAT permission to add) — visible on every report, but never a red/drift signal.
    gaps = []
    for name in ("github_config", "github_push_runs"):
        check = (record.get("checks") or {}).get(name) or {}
        if check.get("needs_owner"):
            gaps.append(check["needs_owner"])
    if gaps:
        joined = " ".join(sorted(set(gaps)))
        html += f"<p><b>needs-owner (not an alarm):</b> {joined}</p>"
    # #3207: declared-but-not-yet-applied posture surfaces render as their OWN line —
    # named, with their blocker, and explicitly not an alarm. The 2026-08-26 sweep
    # reported D0.6's unapplied `main-required-fast-lane` as a critical regression whose
    # recommended fix (`apply_branch_protection.py --apply`) would have wedged the
    # post-merge reconcile push on every merge. Pending is not drift, and the report
    # says so instead of staying silent.
    pending = []
    for check in (record.get("checks") or {}).values():
        for surface, blocker in (check.get("pending") or {}).items():
            pending.append(f"<li><code>{surface}</code> — blocked on: {blocker}</li>")
    if pending:
        html += (
            "<p><b>pending, declared but not yet applied (not drift, no action recommended):</b></p>"
            "<ul>" + "".join(sorted(set(pending))) + "</ul>"
        )
    return html


def quota_html(record):
    """GitHub Actions quota/billing line for the report (#1334, #1453). Always
    renders when a `github_quota` check exists on the record — a clean/unavailable
    week still shows the monthly-glance facts, never silently omits them."""
    if not record:
        return ""
    gq = record.get("checks", {}).get("github_quota")
    if not gq:
        return ""
    billing = gq.get("billing_api", {})
    if billing.get("available"):
        pct = billing.get("pct_used")
        icon = "🔴" if gq.get("status") == "drift" else "🟢"
        line = f"{icon} {billing.get('total_minutes_used')}/{billing.get('included_minutes')} min used ({pct}%)"
        if gq.get("warn"):
            line += f" — <b>{gq['warn']}</b>"
    else:
        icon = "⚪"
        line = f"{icon} billing API unavailable: {billing.get('detail', 'unknown reason')}"
    top = gq.get("top_workflows_7d", [])[:5]
    top_html = ""
    if top:
        top_html = "<ul>" + "".join(f"<li>{w['workflow']}: {w['wall_clock_minutes']} min (7d wall-clock proxy)</li>" for w in top) + "</ul>"
    return f"<h3>GitHub Actions quota glance</h3><p>{line}</p>{top_html}"
