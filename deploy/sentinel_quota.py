#!/usr/bin/env python3
"""
deploy/sentinel_quota.py — GitHub Actions quota/billing observability
(#1334, #1453, #1613), extracted from drift_sentinel.py (#1665 size ceiling).

Reads the enhanced-billing usage API through the GH_BILLING_TOKEN user-scoped
PAT (the legacy /settings/billing/actions endpoint is 410 Gone, 2026-07-26)
and lists the top wall-clock-consuming workflows as a same-scope proxy.
See check_github_quota for the full warn semantics (visibility-aware 70%
line, paid-overage-always-warns).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# GitHub Pro's DOCUMENTED (public, not account-specific) included-Actions-minutes
# allowance — https://docs.github.com/billing/managing-billing-for-github-actions,
# checked 2026-07-18. The account's actual plan tier is NOT programmatically
# readable with the workflow's default token (see `check_github_quota` docstring),
# so this constant is the warn-threshold basis ONLY when the plan is Pro/Team; if
# the account is ever confirmed on a different tier this needs a matching update.
GITHUB_ACTIONS_INCLUDED_MINUTES = 3000
GITHUB_ACTIONS_WARN_PCT = 70


def _gh_api_json(path, timeout=30):
    """`gh api <path>` as parsed JSON; None (never raise) on any failure — billing
    endpoints are EXPECTED to fail with the workflow's default GITHUB_TOKEN (no
    billing scope), so the caller treats None as "unavailable", not an error.

    #1613: prefers GH_BILLING_TOKEN (the owner's user-scoped PAT, stored at
    Secrets Manager `life-platform/github-billing` + the GH_BILLING_TOKEN repo
    secret), then GH_POSTURE_TOKEN, over the ambient GH_TOKEN — the same
    preference pattern as `_gh_api_result` (#1320). Without this, wiring a
    scoped PAT into the workflow env changed nothing."""
    import subprocess

    env = dict(os.environ)
    token = env.get("GH_BILLING_TOKEN") or env.get("GH_POSTURE_TOKEN")
    if token:
        env["GH_TOKEN"] = token
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout, cwd=_ROOT, env=env)
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return None


def _gh_run_list_trailing(days=7, limit=200, timeout=60):
    """`gh run list` for the trailing N days, JSON-decoded. Raises on failure — the
    caller wraps this so a failure here shows up as a labeled sub-error, not a
    crash of the whole check."""
    import subprocess
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = subprocess.run(
        ["gh", "run", "list", "--limit", str(limit), "--created", f">={since}", "--json", "workflowName,startedAt,updatedAt"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_ROOT,
    )
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "gh run list failed")[:300])
    return json.loads(out.stdout or "[]")


def _run_duration_seconds(run):
    """Wall-clock duration of one `gh run list` record; None if timestamps are
    missing/unparseable (skipped, not counted as zero)."""
    try:
        start = datetime.fromisoformat(run["startedAt"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["updatedAt"].replace("Z", "+00:00"))
        return max((end - start).total_seconds(), 0)
    except Exception:  # noqa: BLE001
        return None


def check_github_quota():
    """GitHub Actions quota/billing observability (#1334, #1453).

    Two independent, both fail-soft, sub-checks:

    1. BILLING USAGE API — `GET /users/{owner}/settings/billing/usage?year=&month=`
       (#1613). The legacy `/settings/billing/actions` endpoint is 410 Gone
       (verified live 2026-07-26); the enhanced-billing replacement returns
       per-SKU `usageItems`, from which month-to-date Actions minutes =
       Σ quantity (product=actions, unitType=Minutes) and paid overage =
       Σ netAmount. Needs a user-scoped PAT — GH_BILLING_TOKEN via
       `_gh_api_json`'s token preference; the built-in GITHUB_TOKEN cannot carry
       it, and its failure is reported as an explicit
       `"billing_api": {"available": False, ...}`, never a flapping error.
    2. TOP-CONSUMING WORKFLOWS — a same-scope wall-clock proxy: sums each run's
       (updatedAt - startedAt) per workflow name over the trailing 7 days via
       `gh run list` (needs only `actions: read`, which the built-in token gets).
       This is NOT true billable minutes (Actions bills per-job, and parallel jobs
       in one workflow multiply wall-clock down, not up) — it's a same-direction
       proxy good enough to say "workflow X grew 3x this week," per #1453 AC2.

    `status` is "drift" only when real billing data warrants it — the proxy path
    never sets warn. Warn semantics (#1613, honest to the plan mechanics):
      * paid overage (Σ netAmount > 0) → always warn (real money is leaving);
      * minutes ≥ 70% of the included allowance → warn ONLY if the repo is
        private (or its visibility can't be read — conservative, the #1544
        failure was a silent private-repo cap). Public-repo standard-runner
        minutes are free and don't consume the allowance, so the same figure on
        a public repo is reported but explicitly warn-suppressed — otherwise the
        alarm would scream permanently while public and train us to ignore it.
    """
    result = {"billing_api": {"available": False}, "top_workflows_7d": []}

    repo = os.environ.get("GITHUB_REPOSITORY", "averagejoematt/life-platform")
    owner = repo.split("/")[0]
    now = datetime.now(timezone.utc)
    billing = _gh_api_json(f"users/{owner}/settings/billing/usage?year={now.year}&month={now.month}")
    if billing is None or not isinstance(billing.get("usageItems"), list):
        result["billing_api"] = {
            "available": False,
            "detail": (
                "billing usage API unavailable: GET /users/{owner}/settings/billing/usage needs a "
                "user-scoped PAT (GH_BILLING_TOKEN — Secrets Manager life-platform/github-billing, "
                "#1613); the workflow's built-in GITHUB_TOKEN cannot carry it. NB the legacy "
                "/settings/billing/actions endpoint is 410 Gone (2026-07-26). Falling back to the "
                "trailing-7d wall-clock proxy below."
            ),
        }
    else:
        month_prefix = f"{now.year:04d}-{now.month:02d}"
        items = [i for i in billing["usageItems"] if i.get("product") == "actions" and str(i.get("date", "")).startswith(month_prefix)]
        used = sum(float(i.get("quantity") or 0) for i in items if i.get("unitType") == "Minutes")
        paid_usd = sum(float(i.get("netAmount") or 0) for i in items)
        included = GITHUB_ACTIONS_INCLUDED_MINUTES
        pct = used / included * 100 if included else None
        repo_meta = _gh_api_json(f"repos/{repo}")
        repo_private = repo_meta.get("private") if isinstance(repo_meta, dict) else None
        result["billing_api"] = {
            "available": True,
            "total_minutes_used": round(used, 1),
            "included_minutes": included,
            "pct_used": round(pct, 1) if pct is not None else None,
            "paid_overage_usd": round(paid_usd, 2),
            "repo_private": repo_private,
        }
        if paid_usd > 0:
            result["warn"] = f"GitHub Actions paid overage this month: ${paid_usd:.2f} (minutes {used:.0f})"
        elif pct is not None and pct >= GITHUB_ACTIONS_WARN_PCT:
            if repo_private is False:
                result["billing_api"]["detail"] = (
                    f"minutes at {pct:.1f}% of the {included}-min allowance, but the repo is PUBLIC "
                    "(standard-runner minutes free, allowance not consumed) — warn suppressed. "
                    "This line re-arms automatically if the repo flips private."
                )
            else:
                result["warn"] = (
                    f"GitHub Actions minutes at {pct:.1f}% of the {included}-min allowance "
                    f"(warn threshold {GITHUB_ACTIONS_WARN_PCT}%"
                    + (", repo visibility unreadable — assuming private" if repo_private is None else "")
                    + ")"
                )

    try:
        runs = _gh_run_list_trailing()
        by_workflow: dict[str, float] = {}
        for r in runs:
            name = r.get("workflowName") or "(unnamed)"
            dur = _run_duration_seconds(r)
            if dur is not None:
                by_workflow[name] = by_workflow.get(name, 0) + dur
        top = sorted(by_workflow.items(), key=lambda kv: kv[1], reverse=True)[:10]
        result["top_workflows_7d"] = [{"workflow": name, "wall_clock_minutes": round(secs / 60, 1)} for name, secs in top]
    except Exception as e:  # noqa: BLE001
        result["top_workflows_error"] = str(e)[:300]

    result["status"] = "drift" if result.get("warn") else ("unavailable" if not result["billing_api"]["available"] else "clean")
    return result
