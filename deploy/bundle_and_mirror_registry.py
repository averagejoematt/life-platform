#!/usr/bin/env python3
"""deploy/bundle_and_mirror_registry.py — the SET for #3608.

THE DEFECT. "All deploy paths verifiably stage through one bundle" was never
actually TRUE, only asserted — and it was false: ``scripts/deploy.command``
(Finder-double-clickable) is `zip -j $ZIP mcp_server.py` followed directly by
`aws lambda update-function-code --function-name life-platform-mcp`, one file
replacing the ENTIRE function's code and stripping mcp/, common/, ai/ and every
bundled module. ``tests/test_deploy_bundle_paths.py`` named FOUR scripts by
hand (deploy_site_api.sh, deploy_lambda.sh, deploy_fleet.sh, CDK's
lambda_helpers.py) and missed this fifth, live, executable one — a hand-typed
enumeration is exactly the failure mode the Charter's registry primitive
(docs/CHARTER.md #1) exists to retire.

THE FIX, per the Charter's five primitives:
  1. **Registry** — this module. Two vocabularies:
       * ``BUNDLE_STAGING_SITES`` — every file that actually invokes
         ``aws lambda update-function-code`` (deploy/scripts/CI) or constructs a
         Lambda code asset (CDK), with its staging status.
       * ``CI_MIRROR_SITES`` — every local script/skill that claims to run the
         same checks CI runs, so a human (or an agent) can trust "green here"
         without pushing.
  2. **Derivation guard** — ``tests/test_bundle_and_mirror_registry_3608.py``
     re-derives both sets live (AST/regex over the real tree, never a copy of
     this file) and asserts equality — a NEW site outside the registry reds by
     name; this module's own hand-list is provably the same page.
  3. **Ratchet** — ``known_violation`` entries are dated and issue-tagged; the
     count may only shrink. This PR does NOT rewrite ``scripts/deploy.command``
     (#3608 is being landed as an instrument first: enumerate + guard the SET,
     not remediate a single script — remediation is a follow-up commit any
     agent can now do with the registry as ground truth and the shrink-only
     ratchet as the receipt).

Discovery is regex/AST over real source text, never a second hand list — the
registry below is what the discovery functions found, frozen with a date and a
status, not re-typed from memory.
"""

from __future__ import annotations

import ast
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ─────────────────────────────────────────────────────────────────────────────
# 1. Bundle-staging sites — every call site that can put code into a Lambda.
# ─────────────────────────────────────────────────────────────────────────────

# Directories scanned for shell/`.command` deploy scripts. deploy/archive/ is
# frozen history (dead scripts kept for incident forensics, never run) —
# excluded on purpose, same carve-out `tests/test_deploy_bundle_paths.py` uses.
_SHELL_SCAN_DIRS = ("deploy", "scripts")
_SHELL_EXCLUDE_MARKERS = (f"{os.sep}archive{os.sep}",)

# A REAL (non-comment) `aws lambda update-function-code` invocation. Matches
# the multi-line-backslash shell idiom every one of these scripts uses; a line
# is "real" if the first non-whitespace character is not `#`.
_UPDATE_FN_CODE_RE = re.compile(r"aws\s+lambda\s+update-function-code")


def _is_comment_line(line: str) -> bool:
    return line.strip().startswith("#")


def discover_shell_update_function_code_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every deploy/scripts .sh/.command file with a REAL (non-comment) call to
    `aws lambda update-function-code`, repo-relative path."""
    hits: set[str] = set()
    for scan_dir in _SHELL_SCAN_DIRS:
        base = os.path.join(repo_root, scan_dir)
        for root, dirs, files in os.walk(base):
            if any(marker in (root + os.sep) for marker in _SHELL_EXCLUDE_MARKERS):
                dirs[:] = []
                continue
            for fname in files:
                if not (fname.endswith(".sh") or fname.endswith(".command")):
                    continue
                full = os.path.join(root, fname)
                try:
                    with open(full, encoding="utf-8") as f:
                        lines = f.readlines()
                except (UnicodeDecodeError, OSError):
                    continue
                for line in lines:
                    if _is_comment_line(line):
                        continue
                    if _UPDATE_FN_CODE_RE.search(line):
                        hits.add(os.path.relpath(full, repo_root))
                        break
    return hits


def discover_workflow_update_function_code_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every `.github/workflows/*.yml` with a REAL `run:` step calling
    `aws lambda update-function-code` (YAML comments also start with `#`,
    same test as the shell scanner)."""
    hits: set[str] = set()
    wf_dir = os.path.join(repo_root, ".github", "workflows")
    if not os.path.isdir(wf_dir):
        return hits
    for fname in os.listdir(wf_dir):
        if not fname.endswith((".yml", ".yaml")):
            continue
        full = os.path.join(wf_dir, fname)
        try:
            with open(full, encoding="utf-8") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue
        for line in lines:
            if _is_comment_line(line):
                continue
            if _UPDATE_FN_CODE_RE.search(line):
                hits.add(os.path.relpath(full, repo_root))
                break
    return hits


def discover_cdk_code_asset_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every `cdk/stacks/*.py` that constructs a Lambda code asset directly
    (`_lambda.Code.from_asset(...)` / `.from_bucket(...)` / `.from_inline(...)`),
    AST-matched on the attribute name so a rename of the aws_lambda import
    alias doesn't blind this. `lambda_helpers.py` itself is the ONE place that
    is SUPPOSED to define this (`staged_tree_asset()`) — it stays in the set,
    just with a different status below."""
    hits: set[str] = set()
    stacks_dir = os.path.join(repo_root, "cdk", "stacks")
    if not os.path.isdir(stacks_dir):
        return hits
    for fname in sorted(os.listdir(stacks_dir)):
        if not fname.endswith(".py"):
            continue
        full = os.path.join(stacks_dir, fname)
        try:
            tree = ast.parse(open(full, encoding="utf-8").read(), filename=fname)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("from_asset", "from_bucket", "from_inline")
            ):
                hits.add(os.path.relpath(full, repo_root))
                break
    return hits


def discover_bundle_staging_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """The full bundle-staging SET: every path that can put code into a Lambda."""
    return (
        discover_shell_update_function_code_sites(repo_root)
        | discover_workflow_update_function_code_sites(repo_root)
        | discover_cdk_code_asset_sites(repo_root)
    )


# The registry itself — frozen 2026-09-06, #3608. Status meanings:
#   sanctioned       — stages via deploy/build_bundle.py (grep-verified below).
#   known_violation  — does NOT stage via build_bundle.py. Dated, issue-tagged,
#                       shrink-only: this PR adds the guard, not the fix.
#   exempt           — a real code-asset/update-function-code site that is
#                       legitimately outside the one-bundle rule (documented why).
BUNDLE_STAGING_SITES: dict[str, dict[str, str]] = {
    "deploy/deploy_fleet.sh": {
        "status": "sanctioned",
        "notes": "python3 deploy/build_bundle.py --out ... / --mcp --out ... staged before every update-function-code call",
    },
    "deploy/deploy_site_api.sh": {
        "status": "sanctioned",
        "notes": "stages via deploy/build_bundle.py (#781/#794 — see tests/test_deploy_bundle_paths.py)",
    },
    "deploy/deploy_lambda.sh": {
        "status": "sanctioned",
        "notes": "stages via deploy/build_bundle.py (the single hot-deploy path CDK also matches)",
    },
    "deploy/deploy_mcp_split.sh": {
        "status": "sanctioned",
        "notes": "python3 deploy/build_bundle.py --mcp --out ... staged before update-function-code",
    },
    "deploy/rollback_lambda.sh": {
        "status": "exempt",
        "notes": (
            "re-ships a PRIOR artifact (s3://.../deploys/<fn>/previous.zip) that was itself staged via "
            "build_bundle.py by deploy_lambda.sh/deploy_fleet.sh when it was `latest.zip` — a rollback builds "
            "NOTHING new, so 'stages via build_bundle.py' does not apply to it"
        ),
    },
    "deploy/SMOKE_TEST_TEMPLATE.sh": {
        "status": "exempt",
        "notes": (
            "a copy-paste TEMPLATE (per its own header, 'Copy this block into every deploy script') — not sourced "
            "or invoked by any live deploy path (verified: no deploy/scripts .sh sources it); the update-function-code "
            "call inside its documented rollback() example never runs on its own"
        ),
    },
    "scripts/deploy.command": {
        "status": "known_violation",
        "notes": (
            "2026-09-06 #3608: `zip -j $ZIP mcp_server.py` then `aws lambda update-function-code "
            "--function-name life-platform-mcp` — ONE file, no build_bundle.py, strips mcp/ + common/ + ai/ + "
            "every bundled module. Last touched 72ef2ad24 (2026-03-06), four months before #781 retired the "
            "shared layer. NOT fixed by this PR (instrument-first per #3608's scope) — remediation is deleting "
            "it or rewriting it to call deploy/deploy_lambda.sh life-platform-mcp mcp_server.py."
        ),
    },
    ".github/workflows/ci-cd.yml": {
        "status": "sanctioned",
        "notes": (
            "two real call sites: the 'Fleet deploy' step (bash deploy/deploy_fleet.sh — sanctioned via that "
            "script) and the 'Deploy MCP server' step, which runs `python3 deploy/build_bundle.py --mcp --out ...` "
            "immediately before its own update-function-code call"
        ),
    },
    # ── CDK code-asset construction sites (discover_cdk_code_asset_sites) ──
    "cdk/stacks/lambda_helpers.py": {
        "status": "sanctioned",
        "notes": "staged_tree_asset() — THE default Lambda code asset, IS build_bundle.stage_tree()'s Code.from_asset() call",
    },
    "cdk/stacks/mcp_stack.py": {
        "status": "sanctioned",
        "notes": "build_bundle.stage_mcp(_stage) then _lambda.Code.from_asset(_stage) — the MCP bundle shape",
    },
    "cdk/stacks/web_stack.py": {
        "status": "exempt",
        "notes": (
            "life-platform-og-image is NODEJS_20_X (the .mjs handler at lambdas/ root), not a Python runtime — "
            "it shares no Python module with the common/ai/experiment/etc. bundle, so the one-Python-bundle rule "
            "does not apply to it; its Code.from_asset('../lambdas', exclude=['*.py', ...]) explicitly EXCLUDES "
            "every Python file"
        ),
    },
}

MAX_KNOWN_VIOLATIONS_2026_09_06 = 1  # scripts/deploy.command, 2026-09-06 #3608 — shrink only.

# ─────────────────────────────────────────────────────────────────────────────
# 2. CI-mirror sites — local checks that claim to run what CI runs.
# ─────────────────────────────────────────────────────────────────────────────

# Self-describing phrase patterns: a script/skill that CLAIMS parity with CI in
# its own text. Structural (grep the real files), not a copy of the list below.
_CI_MIRROR_PHRASE_RE = re.compile(
    r"mirrors?\s+the\s+ci|mirrors?\s+what\s+ci|same\s+checks?\s+as\s+ci|"
    r"ci\s+parity|reproduces?\s+ci|exactly\s+what\s+the\s+deploy-time\s+gates\s+run|"
    r"asserts?\s+the\s+expected\s+(set|check)\s+by\s+name",
    re.IGNORECASE,
)

_MIRROR_SCAN_ROOTS = ("deploy", "scripts", os.path.join(".claude", "skills"))


_SELF_PATH = os.path.abspath(__file__)


def discover_ci_mirror_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every file under deploy/, scripts/, .claude/skills/ whose own text
    claims it mirrors/reproduces a CI check set, or asserts an expected-check
    set BY NAME (the #3103 wait_pr_green.sh discipline).

    Text is normalised (comment markers + runs of whitespace/newlines collapsed
    to one space) before matching so a phrase that a hand-wrapped comment block
    splits across lines (e.g. wait_pr_green.sh's own header) is still found —
    the claim is prose, not a wire format, so the matcher must not be line-strict.
    This module's OWN file is excluded: it QUOTES these claims to document the
    registry and must not become evidence of itself.
    """
    hits: set[str] = set()
    for scan_root in _MIRROR_SCAN_ROOTS:
        base = os.path.join(repo_root, scan_root)
        for root, dirs, files in os.walk(base):
            if any(marker in (root + os.sep) for marker in _SHELL_EXCLUDE_MARKERS):
                dirs[:] = []
                continue
            for fname in files:
                if not fname.endswith((".py", ".sh", ".md")):
                    continue
                full = os.path.join(root, fname)
                if os.path.abspath(full) == _SELF_PATH:
                    continue
                try:
                    text = open(full, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                normalized = re.sub(r"[#\s]+", " ", text)
                if _CI_MIRROR_PHRASE_RE.search(normalized):
                    hits.add(os.path.relpath(full, repo_root))
    return hits


CI_MIRROR_SITES: dict[str, dict[str, str]] = {
    "deploy/restart_verify_truth.py": {
        "claim": "Mirrors the CI + nightly hooks exactly: only a HIGH finding gates",
        "notes": "restart_verify.py's truth leg — reader-truth QA run locally without pushing",
    },
    ".claude/skills/qa/SKILL.md": {
        "claim": "Exactly what the deploy-time gates run",
        "notes": "the /qa skill's tier1 mode explicitly claims deploy-gate parity for the visual/AI QA sweep",
    },
    "deploy/wait_pr_green.sh": {
        "claim": "assert the expected set BY NAME, not just scan whatever showed up",
        "notes": "the #3103 ONE blessed PR-check watcher — the local read of what CI's required-check set says",
    },
}


def main() -> None:
    """Print both discovered sets (for the guard test + human inspection)."""
    print("── bundle-staging sites ──")
    for p in sorted(discover_bundle_staging_sites()):
        print(f"  {p}")
    print("── CI-mirror sites ──")
    for p in sorted(discover_ci_mirror_sites()):
        print(f"  {p}")


if __name__ == "__main__":
    main()
