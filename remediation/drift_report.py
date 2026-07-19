"""
remediation/drift_report.py — surface the weekly drift sentinel (#394) in the agent's
curated report.

The drift sentinel (deploy/drift_sentinel.py) runs as a weekly step in the remediation
workflow and persists its findings to s3://<bucket>/drift-log/latest.json. This module
is the read side, shared by both email paths (agent.py in shadow/off, automerge.py in
auto) so the drift status lands in the ONE curated report:

  * as_signal(record)  → a needs-human signal when there is real drift (never auto-fix:
    infra drift is resolved by a human running `cdk deploy`, on the denylist by design).
  * status_html(record) → a one-line status rendered on EVERY report — a clean week
    reports explicitly clean (loud empty state), a drifted/degraded week is loud. AC4:
    the report is never silent about drift.
  * quota_html(record) → the GitHub Actions quota/billing glance (#1334, #1453),
    rendered on EVERY report the same way — real minutes-used-vs-allowance and a 70%
    warn line when the billing API is reachable, a labeled "unavailable" reason when
    it isn't (the workflow's default token lacks the `user` scope), plus the top
    wall-clock-consuming workflows over the trailing 7 days either way.
"""

from __future__ import annotations

import json

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


def as_signal(record):
    """The drift record as a triage signal — only when it's actually flagging drift.

    Degraded (a check couldn't run) and clean are NOT actionable signals — they show in
    the status line but don't spin up an agentic triage run."""
    if not record or record.get("status") != "drift":
        return None
    checks = record.get("checks", {})
    flagging = {k: v for k, v in checks.items() if v.get("status") == "drift"}
    return {
        "status": "drift",
        "date": record.get("date"),
        "summary": record.get("summary"),
        "flagging": flagging,
        # The fix is always operator-run `cdk deploy` / policy repair — never auto-fixable.
        "class": "needs-human",
    }


def status_html(record):
    """One-line HTML status for the report. Always renders when a record exists."""
    if not record:
        return ""
    status = record.get("status", "unknown")
    date = record.get("date", "?")
    summary = record.get("summary", "")
    icon = {"clean": "🟢", "drift": "🔴", "degraded": "🟡"}.get(status, "·")
    label = {"clean": "in sync", "drift": "DRIFT", "degraded": "degraded"}.get(status, status)
    html = f"<h3>{icon} Infra drift sentinel ({label}, checked {date})</h3>" f"<p>{summary}</p>"
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
