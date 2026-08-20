#!/usr/bin/env python3
"""
check_api_before_frontend.py — pre-merge structural fix for #2831.

THE CLASS. site/** merges auto-deploy with NO approval gate (#750,
.github/workflows/site-deploy.yml); the site-api Lambda deploy is a SEPARATE
pipeline gated behind manual production approval (.github/workflows/ci-cd.yml).
A PR that adds a new `/api/...` route AND the site/ page that consumes it in
the SAME PR ships the page (live in minutes) before the API is confirmed
live (could be hours). This fired >=5 times with only reflex-level fixes —
07-09 (#900, x2 rollbacks — the canonical shape), 07-12 (edge-cache flavor),
07-19 (IAM-gate flavor), 07-23 (#1704, the log's own words: "a recurrence of
the 2026-07-09 API-before-frontend class"), 08-02 (#2040, gate-registration
flavor) — see docs/INCIDENT_LOG.md for the dated rows. The only prior
machinery was tests/visual_qa.py's `pending_deploy_apis` — a bare, manually
hand-edited `set()` literal, empty by default, that someone had to remember
to populate DURING an incident and empty again AFTER the deploy (the #2050
pattern). Nothing ran BEFORE merge.

THE FIX. This script is a PR-time (not deploy-time) check
(.github/workflows/pr-checks.yml): it detects a PR touching both
`lambdas/web/` and `site/`, finds any NEWLY ADDED site-api route, and checks
whether a touched site/ file actually references it. If so, the PR must
declare in deploy/api_deploy_sequencing.json either:
  - a `sequenced_routes` entry ("the API is already deployed, no risk"), or
  - a `pending_deploy_routes` entry (the #2050 pattern, generalized) — the
    SAME registry tests/visual_qa.py and deploy/smoke_test_site.sh read to
    downgrade that route's 404 from a gating failure to a warning until it's
    re-armed post-deploy.
An undeclared at-risk route fails the check with the exact remediation.

Usage:
  python3 scripts/check_api_before_frontend.py --base-ref origin/main --head-ref HEAD

The comparison logic (extract_declared_routes / diff_new_routes / find_at_risk_routes /
evaluate) is pure — no git, no filesystem — so it's exercised directly by
tests/test_api_before_frontend_2831.py, including a replay of the #1704
incident shape. main() is the thin git-facing wrapper.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_API_LAMBDA_PATH = "lambdas/web/site_api_lambda.py"
REGISTRY_PATH = os.path.join(REPO_ROOT, "deploy", "api_deploy_sequencing.json")

# The two module-level route tables in site_api_lambda.py — see its ROUTES
# (GET dispatch) and _SIMPLE_ROUTES (method-tagged dispatch, mostly POST)
# assignments. Both are `{"/api/...": <value>}` dict literals with string
# keys; this check only needs the keys.
ROUTE_TABLE_NAMES = {"ROUTES", "_SIMPLE_ROUTES"}


def extract_declared_routes(source: str) -> set[str]:
    """AST-parse site_api_lambda.py-shaped source; return every string key of
    the module-level ROUTES / _SIMPLE_ROUTES dict literals. Returns an empty
    set (not an error) for unparsable/absent source — a brand-new file or a
    base ref where the file didn't exist yet both look like "no routes"."""
    if not source:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id in ROUTE_TABLE_NAMES for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found.add(key.value)
    return found


def diff_new_routes(base_source: str | None, head_source: str) -> set[str]:
    """Routes present in head but not base — i.e. added by this PR."""
    return extract_declared_routes(head_source) - extract_declared_routes(base_source or "")


def find_at_risk_routes(new_routes: set[str], site_file_contents: dict[str, str]) -> set[str]:
    """Which newly-added routes a TOUCHED site/ file actually references.

    Plain substring search over touched-file text (JS/HTML): a page fetching
    a new endpoint contains the literal path string ('/api/broadcast') either
    in a fetch() call or a data-endpoint attribute. Cheap and exactly what
    the #1704/#2040 incidents needed to catch — no JS AST required.
    """
    combined = "\n".join(site_file_contents.values())
    return {r for r in new_routes if r in combined}


@dataclass
class CheckResult:
    ok: bool
    reason: str
    at_risk_routes: set[str] = field(default_factory=set)
    undeclared_routes: set[str] = field(default_factory=set)


def load_registry(path: str = REGISTRY_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sequenced_routes": [], "pending_deploy_routes": []}


def declared_routes(registry: dict) -> set[str]:
    declared = set()
    for bucket in ("sequenced_routes", "pending_deploy_routes"):
        for entry in registry.get(bucket, []):
            route = entry.get("route") if isinstance(entry, dict) else None
            if route:
                declared.add(route)
    return declared


def evaluate(
    changed_files: list[str],
    base_routes_source: str | None,
    head_routes_source: str,
    site_file_contents: dict[str, str],
    registry: dict,
) -> CheckResult:
    """The full pure decision, given already-gathered inputs (no git calls)."""
    touches_web = any(f.startswith("lambdas/web/") for f in changed_files)
    touches_site = any(f.startswith("site/") for f in changed_files)
    if not (touches_web and touches_site):
        return CheckResult(ok=True, reason="PR does not touch both lambdas/web/ and site/ — no API-before-frontend risk")

    new_routes = diff_new_routes(base_routes_source, head_routes_source)
    if not new_routes:
        return CheckResult(
            ok=True, reason="touches both trees, but no new site-api route was added — existing routes are presumed already live"
        )

    at_risk = find_at_risk_routes(new_routes, site_file_contents)
    if not at_risk:
        return CheckResult(
            ok=True,
            reason=f"new route(s) {sorted(new_routes)} added, but no touched site/ file references them — no ordering risk this PR",
        )

    undeclared = at_risk - declared_routes(registry)
    if undeclared:
        return CheckResult(
            ok=False,
            reason=(
                f"new route(s) {sorted(undeclared)} are BOTH added in lambdas/web/ AND consumed by a touched site/ file "
                "in this PR — this is the #2831 class (site/** auto-deploys, site-api does not). Add a dated entry to "
                "deploy/api_deploy_sequencing.json before merging: a `sequenced_routes` entry if the API is already "
                "deployed, or a `pending_deploy_routes` entry to defer smoke/visual enforcement until the next "
                "post-deploy re-arm (the #2050 pattern)."
            ),
            at_risk_routes=at_risk,
            undeclared_routes=undeclared,
        )
    return CheckResult(
        ok=True, reason=f"at-risk route(s) {sorted(at_risk)} are declared in deploy/api_deploy_sequencing.json", at_risk_routes=at_risk
    )


# ── git-facing wrapper ───────────────────────────────────────────────────


def _git(args: list[str]) -> str | None:
    try:
        proc = subprocess.run(["git"] + args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _changed_files(base_ref: str, head_ref: str) -> list[str]:
    merge_base = _git(["merge-base", base_ref, head_ref])
    base_point = merge_base.strip() if merge_base else base_ref
    out = _git(["diff", "--name-only", f"{base_point}..{head_ref}"])
    return [line for line in (out or "").splitlines() if line.strip()]


def _file_at_ref(ref: str, path: str) -> str | None:
    return _git(["show", f"{ref}:{path}"])


def _file_at_worktree(path: str) -> str | None:
    full = os.path.join(REPO_ROOT, path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding="utf-8", errors="replace") as f:
        return f.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-ref", default=os.environ.get("PR_BASE_REF", "origin/main"))
    ap.add_argument("--head-ref", default="HEAD")
    args = ap.parse_args()

    merge_base = _git(["merge-base", args.base_ref, args.head_ref])
    base_point = merge_base.strip() if merge_base else args.base_ref

    changed = _changed_files(args.base_ref, args.head_ref)
    print(f"Changed files ({len(changed)}):")
    for f in changed[:100]:
        print(f"  {f}")

    base_routes_source = _file_at_ref(base_point, SITE_API_LAMBDA_PATH)
    head_routes_source = _file_at_worktree(SITE_API_LAMBDA_PATH) or _file_at_ref(args.head_ref, SITE_API_LAMBDA_PATH) or ""

    touched_site_files = [f for f in changed if f.startswith("site/") and (f.endswith(".js") or f.endswith(".html"))]
    site_file_contents = {}
    for f in touched_site_files:
        content = _file_at_worktree(f) or _file_at_ref(args.head_ref, f)
        if content:
            site_file_contents[f] = content

    registry = load_registry()
    result = evaluate(changed, base_routes_source, head_routes_source, site_file_contents, registry)

    if result.ok:
        print(f"✅ {result.reason}")
        return 0

    print(f"::error title=API-before-frontend sequencing required (#2831)::{result.reason}")
    print("Fix: edit deploy/api_deploy_sequencing.json and add an entry to sequenced_routes or pending_deploy_routes for:")
    for route in sorted(result.undeclared_routes):
        print(f'  {{"route": "{route}", "pr": <this PR number>, "date": "<today>", "reason": "<why>"}}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
