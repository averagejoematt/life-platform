#!/usr/bin/env python3
"""
automerge.py — deterministic auto-merge gate for the remediation agent.

Runs as a workflow step AFTER agent.py. The agent (read-only role) opens PRs
labeled `auto-fix-safe`; it cannot merge (gh pr merge is in its disallowed_tools).
This gate is the ONLY thing that merges, and it is intentionally NOT an LLM — every
decision here is deterministic and auditable.

A PR is merged only if ALL hold:
  1. mode == auto (SSM /life-platform/remediation-mode) and budget tier < 3
  2. every changed file matches the ALLOWLIST (specific templates, not "any small diff")
  3. no changed file matches the DENYLIST (bedrock_client, budget_guard, auth/secrets,
     deploy scripts, workflows, the agent's own code, core/budget infra)
  4. diff is bounded (<= MAX_LINES, no new non-test files)
  5. lint + the offline unit-test subset pass on the PR branch (GITHUB_TOKEN PRs do
     NOT trigger ci-cd.yml, so we run the checks here BEFORE merging; CI re-runs them
     on main after merge, and the production deploy still requires manual approval).
     NB: the on-main re-run only covers files in ci-cd.yml's push `paths` filter —
     the ALLOWLIST files (cdk/**, ci/**, lambdas/**, tests/**) are all in that filter
     as of DEVOPS-01 (AUDIT 2026-06-30). Do not add an ALLOWLIST path that isn't also
     a CI push-path, or its post-merge validation silently disappears.
  6. under the per-day merge cap

Merged PRs that touch cdk/ are flagged "needs cdk deploy" — CI hot-deploys Lambda
CODE on merge (after the manual production-approval gate) but does NOT cdk deploy infra.

The gate updates the agent's report (/tmp/remediation_report.json): merged PRs move
from `prs` → `auto_fixed`; held PRs stay in `prs` with a held reason. agent.py defers
emailing in auto mode so this gate sends the single final email.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODE_PARAM = "/life-platform/remediation-mode"
BUDGET_PARAM = "/life-platform/budget-tier"
REPO = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")
LOG_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_PATH = os.environ.get("REMEDIATION_REPORT_PATH", "/tmp/remediation_report.json")
LABEL = "auto-fix-safe"

MAX_LINES = 60
MAX_PER_DAY = 3

# Specific change templates that are safe to auto-merge (the classes fixed this week).
# A file must match one of these prefixes to be eligible — narrow on purpose.
ALLOWLIST = (
    "cdk/stacks/role_policies.py",                 # missing-IAM grant
    "ci/lambda_map.json",                          # deploy-map drift / unmapped Lambda
    "cdk/stacks/monitoring_stack.py",              # alarm recalibration / stale-clear
    "lambdas/emails/freshness_checker_lambda.py",  # source list / SOURCE_STALE_HOURS
    "lambdas/operational/qa_smoke_lambda.py",      # QA-smoke check tweaks
    "tests/",                                       # accompanying test updates
)

# Never auto-merge — these need a human even if the diff looks small.
DENYLIST_SUBSTR = (
    "bedrock_client", "budget_guard", "secret", "credential", "auth",
    "deploy/", "setup_github_oidc", "setup_remediation_role",
    ".github/workflows/", "cdk/app.py", "cdk/stacks/core_stack.py",
    "remediation/",
)

_ssm = boto3.client("ssm", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)
_ses = boto3.client("sesv2", region_name=REGION)
SENDER = RECIPIENT = "awsdev@mattsusername.com"


def _param(name, default):
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except Exception:
        return default


def _gh(args, check=True):
    out = subprocess.run(["gh"] + args, capture_output=True, text=True, cwd=ROOT, timeout=180)
    if check and out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _decision(pr, action, reason, infra=False):
    return {"pr": pr.get("number"), "title": pr.get("title", ""),
            "url": pr.get("url", ""), "action": action, "reason": reason, "infra": infra}


def eligible(files):
    """Return (ok, reason). Every file must be allowlisted and none denylisted."""
    for f in files:
        path = f["path"]
        if any(s in path for s in DENYLIST_SUBSTR):
            return False, f"denylisted path: {path}"
        # Exact match for file entries; prefix match only for directory entries
        # ("tests/") — bare startswith let "role_policies.py.bak" ride through.
        if not any(path == p or (p.endswith("/") and path.startswith(p)) for p in ALLOWLIST):
            return False, f"not on allowlist: {path}"
        if f.get("additions", 0) and path.endswith(".py") and "/" not in path:
            return False, f"new top-level file: {path}"
    total = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
    if total > MAX_LINES:
        return False, f"diff too large: {total} > {MAX_LINES} lines"
    if not files:
        return False, "no files changed"
    return True, "ok"


def checks_pass(branch):
    """Run lint + the offline unit-test subset on the PR branch. Returns (ok, log)."""
    log = []

    def run(cmd, label):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=600)
        ok = r.returncode == 0
        log.append(f"{'PASS' if ok else 'FAIL'} {label}")
        if not ok:
            log.append((r.stdout + r.stderr)[-800:])
        return ok

    try:
        _gh(["pr", "checkout", branch])
    except Exception as e:
        return False, [f"FAIL checkout: {e}"]

    ok = True
    # Hard syntax/error lint (mirrors ci-cd.yml Lint job's fail-loud select).
    ok &= run(["flake8", "lambdas/", "mcp/", "cdk/", "--select=E9,F63,F7,F82",
               "--show-source"], "flake8 E9/F")
    # The offline consistency suite most relevant to auto-fix-safe classes.
    for tf in ("tests/test_role_policies.py", "tests/test_lambda_handlers.py",
               "tests/test_layer_version_consistency.py",
               "tests/test_iam_secrets_consistency.py", "tests/test_shared_modules.py"):
        if os.path.exists(os.path.join(ROOT, tf)):
            ok &= run(["python3", "-m", "pytest", tf, "-q", "--tb=line"], tf)
    return ok, log


def merges_today():
    """Count gate merges already recorded today (per-day cap)."""
    prefix = f"remediation-log/automerge/{datetime.now(timezone.utc):%Y/%m/%d}/"
    try:
        r = _s3.list_objects_v2(Bucket=LOG_BUCKET, Prefix=prefix)
        return sum(1 for o in r.get("Contents", []) if o["Key"].endswith(".merged.json"))
    except Exception:
        return 0


def audit(decision):
    suffix = "merged" if decision["action"] == "merged" else "held"
    key = (f"remediation-log/automerge/{datetime.now(timezone.utc):%Y/%m/%d}/"
           f"pr{decision['pr']}-{datetime.now(timezone.utc):%H%M%S}.{suffix}.json")
    try:
        _s3.put_object(Bucket=LOG_BUCKET, Key=key,
                       Body=json.dumps(decision, indent=2, default=str),
                       ContentType="application/json")
    except Exception as e:
        print(f"[warn] audit: {e}")


def process():
    decisions = []
    raw = _gh(["pr", "list", "--state", "open", "--label", LABEL,
               "--json", "number,title,url,headRefName,files"])
    prs = json.loads(raw or "[]")
    print(f"[gate] {len(prs)} open {LABEL} PR(s)")
    budget = checked_today = 0
    for pr in prs:
        n = pr["number"]
        files = pr.get("files", [])
        ok, reason = eligible(files)
        if not ok:
            d = _decision(pr, "held", f"ineligible — {reason}")
            decisions.append(d); audit(d)
            _gh(["pr", "comment", str(n), "--body",
                 f"🤖 auto-merge gate held this PR: {reason}. Left for human review."], check=False)
            continue
        if merges_today() + budget >= MAX_PER_DAY:
            d = _decision(pr, "held", f"daily merge cap ({MAX_PER_DAY}) reached")
            decisions.append(d); audit(d)
            continue
        passed, clog = checks_pass(pr["headRefName"])
        if not passed:
            d = _decision(pr, "held", "checks failed: " + "; ".join(clog[:6]))
            decisions.append(d); audit(d)
            _gh(["pr", "comment", str(n), "--body",
                 "🤖 auto-merge gate held this PR: lint/tests failed.\n\n```\n"
                 + "\n".join(clog[:12]) + "\n```"], check=False)
            continue
        infra = any(f["path"].startswith("cdk/") for f in files)
        try:
            _gh(["pr", "merge", str(n), "--squash", "--delete-branch"])
        except Exception as e:
            d = _decision(pr, "held", f"merge failed: {e}")
            decisions.append(d); audit(d)
            continue
        budget += 1
        d = _decision(pr, "merged",
                      "auto-merged (allowlist + lint/tests green)"
                      + ("; ⚠️ touches cdk/ — needs `cdk deploy` to apply" if infra
                         else "; CI will hot-deploy after production approval"),
                      infra=infra)
        decisions.append(d); audit(d)
        print(f"[gate] merged PR #{n} (infra={infra})")
    return decisions


def update_report_and_email(decisions, mode):
    try:
        with open(REPORT_PATH) as f:
            report = json.load(f)
    except Exception:
        report = {"auto_fixed": [], "prs": [], "needs_human": [], "stale": []}

    merged = [d for d in decisions if d["action"] == "merged"]
    held = [d for d in decisions if d["action"] != "merged"]
    merged_urls = {d["url"] for d in merged}
    # Move merged PRs out of "prs awaiting you" → "auto-fixed".
    report["prs"] = [p for p in report.get("prs", []) if p.get("pr") not in merged_urls]
    for d in merged:
        report.setdefault("auto_fixed", []).append(
            {"summary": d["title"] + (" [needs cdk deploy]" if d["infra"] else ""),
             "pr": d["url"]})

    def block(title, items, fmt):
        return (f"<h3>{title}</h3><ul>" + "".join(f"<li>{fmt(i)}</li>" for i in items)
                + "</ul>") if items else ""

    af = report.get("auto_fixed", [])
    prs = report.get("prs", [])
    nh = report.get("needs_human", [])
    stale = report.get("stale", [])
    needs_deploy = [d for d in merged if d["infra"]]
    subj = f"🤖 Remediation [auto]: {len(merged)} merged, {len(prs)} PRs, {len(nh)} need you"
    html = (
        f"<p><b>Mode:</b> {mode} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}</p>"
        + (f"<p>⚠️ <b>{len(needs_deploy)} merged change(s) touch infra and need a manual "
           "<code>cdk deploy</code> to apply.</b></p>" if needs_deploy else "")
        + block("✅ Auto-merged", af, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("🔀 PRs awaiting you", prs, lambda i: f"{i.get('summary','')} — {i.get('pr','')}")
        + block("⏸️ Held by gate (left for review)", held,
                lambda d: f"PR #{d['pr']} {d['title']} — {d['reason']}")
        + block("👤 Needs you", nh, lambda i: f"<b>{i.get('issue','')}</b>: {i.get('action','')}")
        + block("· Stale / ignored", stale, lambda i: str(i.get('summary', i)))
    )
    try:
        _ses.send_email(FromEmailAddress=SENDER, Destination={"ToAddresses": [RECIPIENT]},
                        Content={"Simple": {"Subject": {"Data": subj[:99]},
                                            "Body": {"Html": {"Data": html}}}})
        print(f"[gate] report emailed: {subj}")
    except Exception as e:
        print(f"[warn] SES: {e}")


def main():
    mode = _param(MODE_PARAM, "shadow")
    if mode != "auto":
        print(f"[gate] mode={mode} — no-op (gate only runs in auto)")
        return 0
    if int(_param(BUDGET_PARAM, "0") or 0) >= 3:
        print("[gate] budget tier 3 — skipping")
        return 0
    decisions = process()
    update_report_and_email(decisions, mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
