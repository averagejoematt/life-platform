#!/usr/bin/env python3
"""deploy/bundle_and_mirror_registry.py — the SET for #3608.

THE DEFECT (fixed 2026-09-19, #3608 box 1 — kept here because the registry's
value is the history of what it caught). "All deploy paths verifiably stage
through one bundle" was never actually TRUE, only asserted — and it was
false: ``scripts/deploy.command``
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
     count may only shrink. It reached ZERO on 2026-09-19 (#3608 box 1):
     ``scripts/deploy.command`` was DELETED (``git rm``) rather than rewritten
     — it predated #781 by four months, was referenced by no live doc, and its
     only function (ship ``life-platform-mcp``) is already served by
     ``bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py``, which
     stages through ``deploy/build_bundle.py``. The ceiling below is now 0: the
     one-bundle claim is TRUE, and the next hand-zipped deploy path to land
     cannot be registered as an accepted violation, only fixed.

Discovery is regex/AST over real source text, never a second hand list — the
registry below is what the discovery functions found, frozen with a date and a
status, not re-typed from memory.
"""

from __future__ import annotations

import ast
import os
import re
import shlex

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ─────────────────────────────────────────────────────────────────────────────
# 1. Bundle-staging sites — every call site that can put code into a Lambda.
# ─────────────────────────────────────────────────────────────────────────────

# Directories scanned for shell/`.command` deploy scripts. deploy/archive/ is
# frozen history (dead scripts kept for incident forensics, never run) —
# excluded on purpose, same carve-out `tests/test_deploy_bundle_paths.py` uses.
_SHELL_SCAN_DIRS = ("deploy", "scripts")
_SHELL_EXCLUDE_MARKERS = (f"{os.sep}archive{os.sep}",)

# A REAL `aws lambda update-function-code` invocation, found by SHELL TOKENS
# rather than by the phrase (#3608 box 1). The 2026-09-06 version tested only
# "the first non-whitespace character is not `#`", which is blind in both
# directions: a trailing comment (`echo done  # aws lambda update-function-code`)
# and a quoted string (`echo "aws lambda update-function-code"`) both read as
# real call sites. `_line_invokes_update_function_code()` below lexes each line
# with shlex (comments stripped by the lexer, a quoted run folded into ONE
# token) and requires the three words to appear as three CONSECUTIVE bare
# tokens — which is what a call site is. A TEXT MATCH READS THE COMMENT
# EXPLAINING IT: this module's own prose says the phrase a dozen times and must
# never be evidence of itself.
#
# The regex stays as the cheap pre-filter; the token test is the decision.
_UPDATE_FN_CODE_RE = re.compile(r"aws\s+lambda\s+update-function-code")
_UPDATE_FN_CODE_TOKENS = ("aws", "lambda", "update-function-code")


def _is_comment_line(line: str) -> bool:
    return line.strip().startswith("#")


def _line_invokes_update_function_code(line: str) -> bool:
    """True iff `line` contains `aws lambda update-function-code` as three
    consecutive UNQUOTED shell tokens — a call site, not a mention.

    shlex in posix mode with comments=True drops everything after an unquoted
    `#` and folds a quoted run into a single token, so both false-positive
    shapes above disappear without a second hand-written rule.
    """
    if not _UPDATE_FN_CODE_RE.search(line):
        return False
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        # Unlexable fragment (an unbalanced quote, e.g. mid-heredoc). Fail OPEN:
        # report it as a call site. A guard that silently drops what it cannot
        # parse is the failure mode this whole registry exists to retire.
        return True
    n = len(_UPDATE_FN_CODE_TOKENS)
    return any(tuple(tokens[i : i + n]) == _UPDATE_FN_CODE_TOKENS for i in range(len(tokens) - n + 1))


def discover_shell_update_function_code_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every deploy/scripts .sh/.command file with a REAL call to
    `aws lambda update-function-code` (three consecutive unquoted shell tokens,
    see `_line_invokes_update_function_code`), repo-relative path."""
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
                    if _line_invokes_update_function_code(line):
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
            if _line_invokes_update_function_code(line):
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


# The staging ROOTS — where the staging SITES above put their output (#3832).
#
# `discover_bundle_staging_sites()` answers "what can put code into a Lambda". This answers
# the different question a source-scanning guard needs: "which directories are MIRRORS of
# files the guard already covers". A guard that walks the filesystem (rather than the git
# index) sees those mirrors as new, independent findings — six phantoms on any machine that
# has run a CDK deploy, every one a copy of a file already registered.
#
# Derived from the CDK sources that CREATE the roots, so a renamed or added staging dir
# moves this set with it. NOT read from .gitignore: being ignored is a consequence of being
# a staging root, not the definition of one, and a guard keyed on .gitignore would also
# skip any other ignored path that happened to match.
_STAGING_ROOT_DECL = re.compile(r'["\']\.\.["\']\s*,\s*["\'](_[A-Za-z0-9_]*staging)["\']')
_STAGING_ROOT_SOURCES = ("cdk/stacks",)


def discover_bundle_staging_roots(repo_root: str = REPO_ROOT) -> set[str]:
    """Repo-relative staging output directories, e.g. {"cdk/_bundle_staging", "cdk/_mcp_staging"}.

    Derived by reading the CDK sources that build the paths (`os.path.join(dirname(__file__),
    "..", "_bundle_staging")`), never a literal list in a consumer.
    """
    roots: set = set()
    for rel_dir in _STAGING_ROOT_SOURCES:
        base = os.path.join(repo_root, rel_dir)
        if not os.path.isdir(base):
            continue
        parent = os.path.relpath(os.path.join(base, ".."), repo_root)
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py"):
                continue
            text = open(os.path.join(base, name), encoding="utf-8", errors="replace").read()
            for m in _STAGING_ROOT_DECL.finditer(text):
                roots.add(os.path.normpath(os.path.join(parent, m.group(1))))
    return roots


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

# Shrink-only ratchet. 2026-09-06 #3608 froze it at 1 (scripts/deploy.command);
# 2026-09-19 #3608 box 1 deleted that script and the count reached 0. Shrink only
# means it can never be raised again: a new hand-zipped deploy path is a FIX, not
# a registration. The dated name moves with the measurement so a stale import of
# the old ceiling fails loudly rather than silently re-admitting one violation.
MAX_KNOWN_VIOLATIONS_2026_09_19 = 0

# ─────────────────────────────────────────────────────────────────────────────
# 2. CI-mirror sites — local checks that claim to run what CI runs.
# ─────────────────────────────────────────────────────────────────────────────

# THE PREDICATE, widened 2026-09-19 (#3608 box 3 / epic #3493 devex ROW5).
#
# It used to be ONE clause: "the file's own prose claims parity with CI". That
# reads a CLAIM, so it only ever found the three files that happened to phrase
# it that way — and missed every local check that mirrors CI *structurally*
# without saying so: `deploy/restart_verify_gates.py` runs Docs CI's own gate
# set without pushing, `scripts/ci_job_timeouts.py` and
# `scripts/check_job_timeout_headroom.py` reason about the required check
# `Collect + deploy-critical + format` by name, `scripts/assert_pr_green.py`
# carries the whole required-check set. A mirror that forgets to boast is still
# a mirror, and it drifts the same way.
#
# A file is a CI-mirror site if ANY clause holds:
#   A. its own prose claims parity with CI (`_CI_MIRROR_PHRASE_RE`), or
#   B. it names a REQUIRED-CHECK CONTEXT string — derived live from
#      deploy/github_posture.json's ruleset, never typed here, so adding or
#      renaming a required check moves this predicate with it, or
#   C. it names a `.github/workflows/<name>.yml` PATH literal — it stands in
#      for a specific workflow file and must be re-read when that file changes.
#
# Clause C is the path form on purpose, not the bare filename. A bare
# `site-deploy.yml` in running prose ("the standing site-deploy.yml auto-deploys
# it", deploy/restart_verify.py:309) is a MENTION; measured on the 2026-09-19
# tree the bare-filename form yields 60 files against the path form's 29, and
# the 31 extra are all prose. Registering prose would make the registry a
# corpus of everything that ever named a workflow, which is the shape of a gate
# people learn to skip (#3851).
#
# Self-describing phrase patterns: a script/skill that CLAIMS parity with CI in
# its own text. Structural (grep the real files), not a copy of the list below.
_CI_MIRROR_PHRASE_RE = re.compile(
    r"mirrors?\s+the\s+ci|mirrors?\s+what\s+ci|same\s+checks?\s+as\s+ci|"
    r"ci\s+parity|reproduces?\s+ci|exactly\s+what\s+the\s+deploy-time\s+gates\s+run|"
    r"asserts?\s+the\s+expected\s+(set|check)\s+by\s+name",
    re.IGNORECASE,
)

# Clause C: a reference to a specific workflow FILE by path.
_WORKFLOW_PATH_RE = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")

_MIRROR_SCAN_ROOTS = ("deploy", "scripts", os.path.join(".claude", "skills"))


def required_check_contexts(repo_root: str = REPO_ROOT) -> tuple[str, ...]:
    """Clause B's vocabulary: the required-check CONTEXT strings, read live from
    deploy/github_posture.json (ADR-148's ruleset declaration).

    Derived, never typed: when the owner adds a third required check, every file
    that names it becomes a mirror site on the next run of the guard, and the
    guard reds until it is registered.
    """
    import json

    path = os.path.join(repo_root, "deploy", "github_posture.json")
    try:
        with open(path, encoding="utf-8") as f:
            posture = json.load(f)
    except (OSError, ValueError):
        return ()
    checks = posture.get("main_required_checks_ruleset", {}).get("required_status_checks", [])
    return tuple(c["context"] for c in checks if c.get("context"))


_SELF_PATH = os.path.abspath(__file__)


def discover_ci_mirror_sites(repo_root: str = REPO_ROOT) -> set[str]:
    """Every file under deploy/, scripts/, .claude/skills/ that mirrors CI under
    any of the three clauses documented above: a prose parity claim (A), a
    required-check context string (B), or a `.github/workflows/*.yml` path
    literal (C).

    Text is normalised (comment markers + runs of whitespace/newlines collapsed
    to one space) before matching so a phrase that a hand-wrapped comment block
    splits across lines (e.g. wait_pr_green.sh's own header) is still found —
    the claim is prose, not a wire format, so the matcher must not be line-strict.
    This module's OWN file is excluded: it QUOTES these claims to document the
    registry and must not become evidence of itself.
    """
    hits: set[str] = set()
    contexts = tuple(re.sub(r"\s+", " ", c).strip() for c in required_check_contexts(repo_root))
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
                if (
                    _CI_MIRROR_PHRASE_RE.search(normalized)  # A
                    or any(ctx in normalized for ctx in contexts)  # B
                    or _WORKFLOW_PATH_RE.search(text)  # C
                ):
                    hits.add(os.path.relpath(full, repo_root))
    return hits


CI_MIRROR_SITES: dict[str, dict[str, str]] = {
    "scripts/verify_citations.py": {
        "clause": "C",
        "claim": ".github/workflows/citation-network-check.yml",
        "notes": "the citation network re-resolution script names the monthly workflow that schedules it (#3621 box 4)",
    },
    ".claude/skills/deploy/SKILL.md": {
        "clause": "C",
        "claim": ".github/workflows/site-deploy.yml",
        "notes": "the /deploy skill restates site-deploy.yml's auto-deploy contract for the attended path",
    },
    ".claude/skills/qa/SKILL.md": {
        "clause": "A",
        "claim": "Exactly what the deploy-time gates run",
        "notes": "the /qa skill's tier1 mode explicitly claims deploy-gate parity for the visual/AI QA sweep",
    },
    ".claude/skills/wrap/SKILL.md": {
        "clause": "C",
        "claim": ".github/workflows/docs-ci.yml",
        "notes": "the wrap gate set stands in for docs-ci.yml's gate list",
    },
    "deploy/README.md": {
        "clause": "C",
        "claim": ".github/workflows/site-deploy.yml",
        "notes": "the deploy-surface index names site-deploy.yml as the automatic path",
    },
    "deploy/check_hae_webhook_ingress_drift.py": {
        "clause": "C",
        "claim": ".github/workflows/remediation-agent.yml",
        "notes": "the ingress drift check is the local read of what remediation-agent.yml schedules",
    },
    "deploy/deploy_convergence.py": {
        "clause": "C",
        "claim": ".github/workflows/site-deploy.yml",
        "notes": "converges the attended sync with what site-deploy.yml ships",
    },
    "deploy/drift_sentinel.py": {
        "clause": "C",
        "claim": ".github/workflows/remediation-agent.yml",
        "notes": "the sentinel's cadence leg stands in for remediation-agent.yml's schedule",
    },
    "deploy/generate_review_bundle.py": {
        "clause": "C",
        "claim": ".github/workflows/ci-cd.yml",
        "notes": "bundles the CI surface ci-cd.yml defines for review",
    },
    "deploy/lib/pinned_formatters.sh": {
        "clause": "C",
        "claim": ".github/workflows/ci-lint.yml",
        "notes": "the ONE local black/ruff invocation pinned to ci-lint.yml's versions (#3608 box 3: a pin mirror, never boasted)",
    },
    "deploy/restart_verify_gates.py": {
        "clause": "C",
        "claim": ".github/workflows/docs-ci.yml",
        "notes": "restart_verify's NON-PUSH gate leg — runs Docs CI's own gate set locally (the member epic #3493 devex ROW5 names)",
    },
    "deploy/restart_verify_truth.py": {
        "clause": "A",
        "claim": "Mirrors the CI + nightly hooks exactly: only a HIGH finding gates",
        "notes": "restart_verify.py's truth leg — reader-truth QA run locally without pushing",
    },
    "deploy/sentinel_cadence.py": {
        "clause": "C",
        "claim": ".github/workflows/remediation-agent.yml",
        "notes": "cadence freshness for the remediation-agent.yml schedule",
    },
    "deploy/sentinel_github.py": {
        "clause": "C",
        "claim": ".github/workflows/site-deploy.yml",
        "notes": "PUSH_TRIGGER_GLOBS is the local model of ci-cd/docs-ci/site-deploy path filters (#3608 box 2's derivation source)",
    },
    "deploy/setup_remediation_role.sh": {
        "clause": "C",
        "claim": ".github/workflows/remediation-agent.yml",
        "notes": "provisions the role remediation-agent.yml assumes",
    },
    "deploy/write_lane_posture.py": {
        "clause": "C",
        "claim": ".github/workflows/pr-checks.yml",
        "notes": "#3608 box 4 — writes typical_seconds from the fast-lane's own emitted wall-clock; it stands in for that workflow's timing",
    },
    "deploy/verify_doc_facts_derivable.py": {
        "clause": "C",
        "claim": ".github/workflows/ci-cd.yml",
        "notes": "local stand-in for ci-cd.yml/docs-ci.yml's doc-fact gates",
    },
    "deploy/wait_pr_green.sh": {
        "clause": "A",
        "claim": "assert the expected set BY NAME, not just scan whatever showed up",
        "notes": "the #3103 ONE blessed PR-check watcher — the local read of what CI's required-check set says",
    },
    "scripts/assert_pr_green.py": {
        "clause": "B",
        "claim": "Collect + deploy-critical + format",
        "notes": "carries the ADR-148 required-check set by name",
    },
    "scripts/check_api_before_frontend.py": {
        "clause": "C",
        "claim": ".github/workflows/site-deploy.yml",
        "notes": "models the ci-cd.yml/site-deploy.yml ordering race locally",
    },
    "scripts/check_cron_freshness.py": {
        "clause": "C",
        "claim": ".github/workflows/cron-freshness.yml",
        "notes": "the local read of cron-freshness.yml's sweep",
    },
    "scripts/check_job_timeout_headroom.py": {
        "clause": "B",
        "claim": "Collect + deploy-critical + format",
        "notes": "#3678 — grades the required check's timeout against its observed band",
    },
    "scripts/ci_job_timeouts.py": {
        "clause": "B",
        "claim": "Collect + deploy-critical + format",
        "notes": "the timeout registry keyed on the required check's context name",
    },
    "scripts/coverage_gap_warn.py": {
        "clause": "C",
        "claim": ".github/workflows/ci-cd.yml",
        "notes": "warns on the coverage floor ci-cd.yml enforces",
    },
    "scripts/fresh_eyes_discovery.py": {
        "clause": "C",
        "claim": ".github/workflows/fresh-eyes.yml",
        "notes": "the local run of what fresh-eyes.yml schedules",
    },
    "scripts/gate_census_mutations.py": {
        "clause": "C",
        "claim": ".github/workflows/_census_probe_2999.yml",
        "notes": "plants a synthetic workflow path to mutation-prove the workflow-reading gates",
    },
    "scripts/gate_census_proofs.py": {
        "clause": "B",
        "claim": "Collect + deploy-critical + format",
        "notes": "proof records keyed on CI job/check names",
    },
    "scripts/harvest_eval_fixtures.py": {
        "clause": "C",
        "claim": ".github/workflows/eval-harvest.yml",
        "notes": "the local run of eval-harvest.yml",
    },
    "scripts/operating_calendar.py": {
        "clause": "C",
        "claim": ".github/workflows/operating-calendar.yml",
        "notes": "the calendar registry operating-calendar.yml renders",
    },
    "scripts/playwright_gated_tests.py": {
        "clause": "C",
        "claim": ".github/workflows/ci-test.yml",
        "notes": "the gated-test selection ci-test.yml applies",
    },
    "scripts/surface_drift_gate.py": {
        "clause": "C",
        "claim": ".github/workflows/surface-drift.yml",
        "notes": "the local run of surface-drift.yml's gate",
    },
    "scripts/verify_bundle_boot.py": {
        "clause": "C",
        "claim": ".github/workflows/pr-checks.yml",
        "notes": "the boot check pr-checks.yml runs pre-merge",
    },
}

# Frozen 2026-09-19 (#3608 box 3): 31 members, up from 3 under the prose-only
# predicate. Clause mix measured, not asserted — A=3 (a prose parity claim),
# B=4 (names a required-check context), C=24 (names a workflow path literal).
#
# 31 rather than 30 because the widened guard caught THIS issue's own new file:
# deploy/write_lane_posture.py (box 4) names pr-checks.yml by path, and the
# equality assertion redded by name until it was registered. That is the
# derivation guard working on its author, one commit after it landed.
MIRROR_CLAUSE_BASELINE_2026_09_19 = {"A": 3, "B": 4, "C": 25}


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
