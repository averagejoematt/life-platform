#!/usr/bin/env python3
"""scripts/reader_surface.py — does a diff touch what a reader can see? (#4589, epic #4580)

WHY THIS EXISTS
---------------
The two AI checks in CI — the Claude-vision judge (`tests/visual_ai_qa.py`, run by
`tests/visual_qa.py --ai-qa`) and the reader-truth prose judge (`--reader-truth`) — read
the LIVE site. They ran on every deploy and every daily fire regardless of what changed,
so a diff that only touched an ingestion Lambda, a CDK alarm or a docs file paid Bedrock
to re-judge pages that diff could not have moved. The owner ruled (platform plan,
2026-10-03, decision 4): the two AI checks run only when reader pages change.

WHAT "THE READER SURFACE" IS — DERIVED, NOT A HAND LIST
-------------------------------------------------------
A screenshot taken minutes after a deploy can only differ because of code or data that
renders AT REQUEST TIME. A producer Lambda (the daily brief, a coach pipeline, a
chronicle) changes nothing on the page until its next scheduled run, so a deploy-time
judgement of a producer-only diff is the same judgement as of no diff at all. The surface
is therefore four sets, each read from the repo rather than typed here:

  1. `site/` — the static tree (`.github/workflows/site-deploy.yml`'s own path filter).
  2. The request-time import closure of the site's API Lambdas — every repo module
     reachable by import from `REQUEST_TIME_ENTRIES` (the handlers behind the `/api/*`
     origins in `cdk/stacks/serve_stack.py`). Walked with `ast`, lazy imports included,
     so a shared module the API imports is on the surface and a producer-only module is
     not. Nothing is listed by hand below the entry points.
  3. The judges themselves (`JUDGE_ENTRIES` + their import closures) and the CI wiring
     that runs them — a change to a judge must exercise the judge, the same rule as
     site-deploy.yml's "workflow edits must exercise themselves".
  4. The bundled config (`deploy/build_bundle.py::bundled_extra_paths`) — it ships with
     the site-API bundle and is read at request time (personas, coach specs) — and the
     two CDK stacks that hold the request path (`EDGE_PATHS`: CloudFront + the API origins).

FAIL DIRECTION
--------------
Every uncertainty resolves to RUN: an empty/unresolvable base, a base that is not an
ancestor of head, a git error, or an unreadable entry point. Skipping is only ever the
result of a diff that was actually computed and actually missed the surface. A skip is
never silent — the verdict line names the base, the head, the number of changed files
and why none of them counted.

The budget tier-3 pause is untouched: it lives inside the judges (`visual_ai_qa`'s
SKIPPED-BY-BUDGET path) and still applies whenever this script says RUN.

    python3 scripts/reader_surface.py --base <sha> [--head HEAD] [--github-output]
    python3 scripts/reader_surface.py --since-hours 24 [--github-output]
    python3 scripts/reader_surface.py --list            # print the derived surface
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SITE_PREFIX = "site/"

# The Lambdas behind the site's `/api/*` CloudFront origins (serve_stack.py: the two
# `add_function_url` constructs that CloudFront fronts). Entry points only — everything
# they can execute is derived from here by the import walk.
REQUEST_TIME_ENTRIES = (
    "lambdas/web/site_api_lambda.py",
    "lambdas/web/site_api_ai_lambda.py",
)

# The two AI judges and the harness that drives them. A judge edit must run the judge.
JUDGE_ENTRIES = (
    "tests/visual_qa.py",
    "tests/visual_ai_qa.py",
    "lambdas/operational/reader_truth_qa.py",
)

# The CI wiring that decides whether the judges run — editing the decision must exercise it.
WIRING_PATHS = (
    ".github/workflows/ci-cd.yml",
    ".github/workflows/visual-qa.yml",
    "scripts/reader_surface.py",
)

# The two CDK stacks that hold the site's request path: the CloudFront distribution and its
# behaviours/origins (web_stack.py) and the `/api/*` Function-URL Lambdas (serve_stack.py). A diff
# there can change what a reader is served without touching site/ or a handler.
EDGE_PATHS = (
    "cdk/stacks/web_stack.py",
    "cdk/stacks/serve_stack.py",
)

# Import roots, in the order the runtime resolves them: the Lambda bundle stages `lambdas/`
# at the zip root (ADR-146), and the test harnesses put `tests/` on sys.path.
_IMPORT_ROOTS = ("lambdas", "tests", "deploy", "")


def _resolve(dotted: str, roots: Iterable[str]) -> list:
    """Repo files a dotted import can bind to — the module file and every package
    `__init__` on the way. Empty for stdlib/third-party (not in the repo)."""
    parts = dotted.split(".")
    for root in roots:
        base = os.path.join(REPO, root) if root else REPO
        hits = []
        cur = base
        for i, part in enumerate(parts):
            pkg = os.path.join(cur, part)
            mod = pkg + ".py"
            if os.path.isfile(mod):
                hits.append(mod)
                break
            if os.path.isdir(pkg):
                init = os.path.join(pkg, "__init__.py")
                if os.path.isfile(init):
                    hits.append(init)
                cur = pkg
                if i == len(parts) - 1:
                    break
                continue
            break
        if hits:
            return hits
    return []


def _imports_of(path: str) -> list:
    """Every dotted name imported anywhere in `path` (module level, lazy, guarded)."""
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return []
    pkg_parts = os.path.relpath(os.path.dirname(path), REPO).split(os.sep)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # relative: resolve against this file's own package directory
                anchor = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                prefix = ".".join(p for p in anchor if p and p != ".")
                mod = ".".join(x for x in (prefix, node.module or "") if x)
                out.append(("__REL__", mod, [a.name for a in node.names]))
                continue
            mod = node.module or ""
            out.append(mod)
            out.extend(f"{mod}.{a.name}" for a in node.names if a.name != "*")
    return out


def import_closure(entries: Iterable[str]) -> set:
    """Repo-relative paths of every repo module reachable by import from `entries`.

    Raises FileNotFoundError when an entry point does not exist — a renamed API handler
    must fail loudly here, never shrink the surface to nothing.
    """
    seen: set = set()
    stack = []
    for e in entries:
        p = os.path.join(REPO, e)
        if not os.path.isfile(p):
            raise FileNotFoundError(f"reader-surface entry point missing: {e}")
        stack.append(p)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        here = os.path.relpath(os.path.dirname(path), REPO)
        roots = (here,) + _IMPORT_ROOTS
        for imp in _imports_of(path):
            if isinstance(imp, tuple):
                _, mod, names = imp
                cands = [mod] + [f"{mod}.{n}" for n in names]
                for c in cands:
                    for hit in _resolve(c, ("",)):
                        if hit not in seen:
                            stack.append(hit)
                continue
            for hit in _resolve(imp, roots):
                if hit not in seen:
                    stack.append(hit)
    return {os.path.relpath(p, REPO) for p in seen}


def bundled_config_paths() -> set:
    sys.path.insert(0, os.path.join(REPO, "deploy"))
    try:
        import build_bundle  # noqa: E402

        return {str(p) for p in build_bundle.bundled_extra_paths(REPO)}
    finally:
        sys.path.pop(0)


def reader_surface() -> dict:
    """{"site_prefix", "request_time", "judges", "wiring", "edge", "config"} — the derived surface."""
    return {
        "site_prefix": SITE_PREFIX,
        "request_time": import_closure(REQUEST_TIME_ENTRIES),
        "judges": import_closure(JUDGE_ENTRIES),
        "wiring": set(WIRING_PATHS),
        "edge": set(EDGE_PATHS),
        "config": bundled_config_paths(),
    }


def classify(changed: Iterable[str], surface: Optional[dict] = None) -> list:
    """[(path, which_set)] for every changed path on the reader surface."""
    surface = surface or reader_surface()
    hits = []
    for path in changed:
        path = path.strip()
        if not path:
            continue
        if path.startswith(surface["site_prefix"]):
            hits.append((path, "site"))
        elif path in surface["request_time"]:
            hits.append((path, "request-time API"))
        elif path in surface["judges"]:
            hits.append((path, "AI judge"))
        elif path in surface["wiring"]:
            hits.append((path, "judge wiring"))
        elif path in surface.get("edge", ()):
            hits.append((path, "site edge stack"))
        elif path in surface["config"]:
            hits.append((path, "bundled config"))
    return hits


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


def base_since(hours: float, head: str = "HEAD") -> str:
    """The newest commit on `head`'s first-parent line older than `hours` ago ('' if none)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        return _git("rev-list", "-1", "--first-parent", f"--before={cutoff}", head).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def decide(base: str, head: str = "HEAD") -> tuple:
    """(run: bool, reason: str). Every uncertainty resolves to run=True."""
    if not base:
        return True, "RUN — no diff base was resolved, so the AI checks run (an unknown diff is never a skip)"
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=REPO, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return True, f"RUN — base {base[:12]} is not a resolvable ancestor of {head}, so the AI checks run"
    try:
        changed = [p for p in _git("diff", "--name-only", base, head).splitlines() if p.strip()]
    except (subprocess.CalledProcessError, OSError) as e:
        return True, f"RUN — git diff {base[:12]}..{head} failed ({e}), so the AI checks run"
    try:
        hits = classify(changed)
    except Exception as e:  # noqa: BLE001 — a surface we cannot compute is never a skip
        return True, f"RUN — the reader surface could not be derived ({e}), so the AI checks run"
    if hits:
        shown = ", ".join(f"{p} ({kind})" for p, kind in hits[:8])
        more = f" and {len(hits) - 8} more" if len(hits) > 8 else ""
        return True, f"RUN — {len(hits)} reader-surface file(s) changed in {base[:12]}..{head}: {shown}{more}"
    return False, (
        f"SKIP — {len(changed)} file(s) changed in {base[:12]}..{head} and none is on the reader surface "
        "(site/, the site-API request-time import closure, the AI judges and their wiring, the site edge stacks, "
        "bundled config); "
        "the AI checks are skipped by the #4589 reader-surface gate and the deterministic sweep still runs"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=None, help="diff base sha (empty = unresolved → RUN)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--since-hours", type=float, default=None, help="base = newest first-parent commit older than N hours")
    ap.add_argument("--github-output", action="store_true", help="append run_ai=true|false and reason= to $GITHUB_OUTPUT")
    ap.add_argument("--list", action="store_true", help="print the derived surface and exit")
    args = ap.parse_args(argv)

    if args.list:
        s = reader_surface()
        print(f"site prefix: {s['site_prefix']}")
        for key in ("request_time", "judges", "wiring", "edge", "config"):
            print(f"{key} ({len(s[key])}):")
            for p in sorted(s[key]):
                print(f"  {p}")
        return 0

    base = args.base if args.base is not None else ""
    if args.since_hours is not None:
        base = base_since(args.since_hours, args.head)
    run, reason = decide(base, args.head)
    print(f"reader-surface gate (#4589): {reason}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if args.github_output and gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"run_ai={'true' if run else 'false'}\n")
            fh.write(f"reason={reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
