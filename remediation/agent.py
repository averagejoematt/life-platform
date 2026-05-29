#!/usr/bin/env python3
"""
agent.py — self-healing remediation agent (runs in GitHub Actions).

Flow per run:
  1. Gate on SSM /life-platform/remediation-mode (off|shadow|auto) + budget tier.
  2. Gather the last 24h of signals deterministically (alarms, QA/freshness/cost,
     failed CI runs, DLQ) — cheap boto3/gh, no LLM.
  3. Hand the signals + docs/REMEDIATION_TAXONOMY.md to Claude (Agent SDK, on
     Bedrock) with a scoped toolset. Claude classifies each into A/B/C/D and:
       - Bucket A (auto-fix-safe): fix in a branch, open a PR labeled auto-fix-safe
         (auto-merge only happens in `auto` mode via the workflow's merge gate).
       - Bucket B (fix-via-pr): open a PR labeled needs-review.
       - Bucket C (needs-human): no change — include the specific action in the report.
       - Bucket D (stale): collapse.
       - Operational remediations (clear stale alarm / drain stale DLQ msg / re-run
         gap-fill): done directly via the scoped role.
  4. Claude emits a JSON summary; we render + email it (SES) and write the audit log.

Triggered by: schedule (daily sweep) or repository_dispatch (urgent_alarm).
Auth: AWS OIDC (Bedrock + read-only diagnosis + scoped ops). Model: Sonnet 4.6.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODE_PARAM = "/life-platform/remediation-mode"
BUDGET_PARAM = "/life-platform/budget-tier"
REPO = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")
SENDER = RECIPIENT = "awsdev@mattsusername.com"
LOG_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ssm = boto3.client("ssm", region_name=REGION)
_cw = boto3.client("cloudwatch", region_name=REGION)
_logs = boto3.client("logs", region_name=REGION)
_sqs = boto3.client("sqs", region_name=REGION)
_ses = boto3.client("sesv2", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)


def _param(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return default


def gate():
    """Return the active mode, or None to skip the run."""
    mode = _param(MODE_PARAM, "shadow")
    if mode == "off":
        print("remediation-mode=off — no-op")
        return None
    if int(_param(BUDGET_PARAM, "0") or 0) >= 3:
        print("budget tier 3 — skipping remediation to protect the ceiling")
        return None
    return mode


# ── Signal gathering (deterministic, no LLM) ────────────────────────────────

def gather_signals(event_payload):
    """Collect the last 24h of technical signals into a structured dict."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    signals = {"alarms": [], "ci_failures": [], "dlq": [], "urgent": None}

    # CloudWatch alarms currently in ALARM + recent transitions
    try:
        alarms = _cw.describe_alarms(StateValue="ALARM", MaxRecords=100).get("MetricAlarms", [])
        for a in alarms:
            signals["alarms"].append({
                "name": a["AlarmName"],
                "reason": a.get("StateReason", "")[:300],
                "metric": a.get("MetricName"),
                "namespace": a.get("Namespace"),
                "updated": str(a.get("StateUpdatedTimestamp", "")),
            })
    except Exception as e:
        print(f"[warn] describe-alarms: {e}")

    # Recent failed CI runs
    try:
        out = subprocess.run(
            ["gh", "run", "list", "--branch", "main", "--status", "failure",
             "--limit", "5", "--json", "databaseId,headSha,displayTitle,conclusion,createdAt"],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        if out.returncode == 0:
            signals["ci_failures"] = json.loads(out.stdout or "[]")
    except Exception as e:
        print(f"[warn] gh run list: {e}")

    # Ingestion DLQ depth (peek count only; the agent inspects details if non-zero)
    try:
        url = f"https://sqs.{REGION}.amazonaws.com/{os.environ.get('CDK_ACCOUNT','205930651321')}/life-platform-ingestion-dlq"
        attrs = _sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
        signals["dlq"] = {"depth": int(attrs["Attributes"]["ApproximateNumberOfMessages"]), "url": url}
    except Exception as e:
        print(f"[warn] dlq depth: {e}")

    # Event-driven urgent payload (from repository_dispatch)
    if event_payload:
        signals["urgent"] = event_payload
    return signals


# ── The agent run (Agent SDK on Bedrock) ────────────────────────────────────

def build_prompt(mode, signals):
    taxonomy = open(os.path.join(ROOT, "docs", "REMEDIATION_TAXONOMY.md")).read()
    base = open(os.path.join(os.path.dirname(__file__), "prompt.md")).read()
    return (
        base
        + f"\n\n## Mode: {mode}\n"
        + "\n## Taxonomy (authoritative classification rubric)\n" + taxonomy
        + "\n\n## Signals to triage (last 24h)\n```json\n"
        + json.dumps(signals, indent=2, default=str) + "\n```\n"
        + "\nProduce your work, then end with a single ```json fenced block matching "
        + "the REPORT schema in the instructions."
    )


async def run_agent(prompt):
    """Invoke Claude via the Agent SDK on Bedrock and return its captured text.

    Headless safety: `bypassPermissions` (no interactive prompts — `acceptEdits`
    hangs/errors on Bash/gh tools headlessly). The REAL blast-radius guard is the
    IAM role (read-only AWS + SES + scoped S3-log) and the GITHUB_TOKEN scope
    (contents + pull-requests write only) — the agent literally cannot deploy or
    mutate AWS. `disallowed_tools` is best-effort defense-in-depth. We accumulate
    text across all messages and tolerate the SDK's ResultMessage protocol /
    end-of-stream exceptions so a partial run still produces a report."""
    from claude_agent_sdk import query, ClaudeAgentOptions  # installed in the workflow
    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        disallowed_tools=[
            "Bash(git merge *)", "Bash(git push --force*)", "Bash(gh pr merge *)",
            "Bash(aws lambda update*)", "Bash(aws iam *)", "Bash(cdk deploy*)",
            "Bash(npx cdk deploy*)",
        ],
        cwd=ROOT,
        max_turns=int(os.environ.get("REMEDIATION_MAX_TURNS", "16")),
    )
    chunks = []
    try:
        async for message in query(prompt=prompt, options=options):
            # Final ResultMessage carries is_error + result; capture, don't crash.
            if hasattr(message, "is_error"):
                res = getattr(message, "result", None)
                if isinstance(res, str):
                    chunks.append(res)
                if getattr(message, "is_error", False):
                    print(f"[warn] agent result flagged error "
                          f"(subtype={getattr(message, 'subtype', None)})")
                break
            # AssistantMessage: pull text from content blocks.
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for blk in content:
                    t = getattr(blk, "text", None)
                    if isinstance(t, str):
                        chunks.append(t)
    except Exception as e:
        print(f"[warn] agent stream ended with: {e} — using captured output")
    return "\n".join(chunks)


def parse_report(text):
    """Extract the trailing ```json REPORT block; tolerate prose around it."""
    if "```json" in text:
        seg = text.rsplit("```json", 1)[1].split("```", 1)[0]
        try:
            return json.loads(seg.strip())
        except Exception:
            pass
    return {"auto_fixed": [], "prs": [], "needs_human": [], "stale": [],
            "_raw": text[-1500:]}


# ── Reporting ────────────────────────────────────────────────────────────────

def email_report(report, mode):
    def block(title, items, fmt):
        if not items:
            return ""
        return f"<h3>{title}</h3><ul>" + "".join(f"<li>{fmt(i)}</li>" for i in items) + "</ul>"
    af = report.get("auto_fixed", [])
    prs = report.get("prs", [])
    nh = report.get("needs_human", [])
    stale = report.get("stale", [])
    subj = f"🤖 Remediation [{mode}]: {len(af)} fixed, {len(prs)} PRs, {len(nh)} need you"
    html = (
        f"<p><b>Mode:</b> {mode} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}</p>"
        + block("✅ Auto-fixed", af, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("🔀 PRs awaiting you", prs, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("👤 Needs you", nh, lambda i: f"<b>{i.get('issue','')}</b>: {i.get('action','')}")
        + block("· Stale / ignored", stale, lambda i: str(i.get('summary', i)))
        + ("<p><i>No actionable signals.</i></p>" if not (af or prs or nh) else "")
    )
    try:
        _ses.send_email(
            FromEmailAddress=SENDER, Destination={"ToAddresses": [RECIPIENT]},
            Content={"Simple": {"Subject": {"Data": subj[:99]},
                                "Body": {"Html": {"Data": html}}}},
        )
        print(f"report emailed: {subj}")
    except Exception as e:
        print(f"[warn] SES send: {e}")


def audit_log(report, signals, mode):
    try:
        key = f"remediation-log/{datetime.now(timezone.utc):%Y/%m/%d/%H%M%S}.json"
        _s3.put_object(Bucket=LOG_BUCKET, Key=key,
                       Body=json.dumps({"mode": mode, "signals": signals, "report": report},
                                       indent=2, default=str),
                       ContentType="application/json")
    except Exception as e:
        print(f"[warn] audit log: {e}")


def main():
    mode = gate()
    if not mode:
        return 0
    event_payload = json.loads(os.environ.get("DISPATCH_PAYLOAD", "null") or "null")
    signals = gather_signals(event_payload)
    if not (signals["alarms"] or signals["ci_failures"]
            or (signals["dlq"] or {}).get("depth") or signals["urgent"]):
        print("no actionable signals — clean run")
        email_report({}, mode)
        return 0
    prompt = build_prompt(mode, signals)
    text = asyncio.run(run_agent(prompt))
    # Prefer the file the agent wrote (robust); fall back to parsing the stream.
    report = None
    report_path = os.environ.get("REMEDIATION_REPORT_PATH", "/tmp/remediation_report.json")
    try:
        with open(report_path) as f:
            report = json.load(f)
    except Exception:
        report = parse_report(text)
    email_report(report, mode)
    audit_log(report, signals, mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
