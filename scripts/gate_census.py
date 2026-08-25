#!/usr/bin/env python3
"""scripts/gate_census.py — #2578: derive the armed-gate inventory FROM SOURCE, and
record which of those gates has been WATCHED failing.

WHY THIS IS A SCRIPT AND NOT A MARKDOWN TABLE
---------------------------------------------
The epic's own framing: "a hand-list is the same failure mode one level up." Six
measured instances in four days (#2564, #2573, #2590, #2589, the AnnAssign blindness,
#2619) were each found as a *side effect* of unrelated work — nothing in this platform
systematically asks a gate to prove it can fail. The first thing that has to stop being
guesswork is *how many gates there are*. This module is that count, derived.

WHAT THIS IS AND IS NOT
-----------------------
Two things, kept strictly apart:

  * **The census** (slice 1) — "how many gates exist, how many were screened, which
    could not be", with n on every line. Its detectors are syntactic; a risk flag is a
    LEAD requiring adjudication, never a defect, and the report says so.
  * **The verdicts** (slice 2) — the small set of gates that were made to fail ON
    PURPOSE and watched failing, recorded in ``PROVEN_CAN_FAIL`` with the command, the
    mutation and the observed exit status. A gate is never promoted to `can-fail` by
    reading it; reasoning that a gate *would* fail is precisely what produced the six
    dark gates this epic exists for.

Everything else reports ``unproven``, and the header prints that number too — 6 proven
against 421 found is the honest state, and rounding it up is the failure mode.
``ATTEMPTED_UNPROVEN`` carries the gates that were tried and could NOT be proved, with
the reason: an honest "could not prove" is a result, and skipping it silently is how an
untested assumption survives.

A risk flag here is a **lead requiring adjudication**, never a defect. The detectors are
syntactic. They are wrong in both directions and the report says so.

THE TAXONOMY (the six measured instances are the seed, not the scope)
---------------------------------------------------------------------
Shapes are named on ``Shape`` below. Three are statically detectable from source text;
three are not, and the census reports the undetectable ones as *unevaluated with a
reason* rather than omitting them — omitting them would make this instrument the seventh
instance of its own subject.

SELF-REFERENCE, DELIBERATE
--------------------------
Instance 5 in the taxonomy is "one type annotation on ``SOURCE_REGISTRY`` silently
disarmed three AST-walking gates" — each walked ``ast.Assign`` and never
``ast.AnnAssign``, returned empty, and passed. This module walks BOTH (see
``_module_level_bindings``), and ``tests/test_gate_census_2578.py`` mutation-proves that
it does, against a synthetic tree. A census that inherits the blindness it is counting
would be worth less than nothing.

USAGE
-----
    python3 scripts/gate_census.py                 # human report
    python3 scripts/gate_census.py --json out.json # machine-readable inventory
    python3 scripts/gate_census.py --family ci     # one family (LOGS the bound)

Exit status is 0 whatever it finds. This is an instrument, not a gate — making the
census itself gate main before its precision is known would red main on syntax.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Split out by the module-size ratchet (#1665): the #2639 error-bar machinery lives in
# gate_census_precision; re-exported here so the CLI report and tests keep one address.
from gate_census_precision import (  # noqa: F401
    FLAG_PRECISION,
    FlagPrecisionSample,
    _live_flag_count,
    _render_error_bars,
    _wilson_interval,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# The taxonomy. Six measured shapes, plus what this census can and cannot see.
# ─────────────────────────────────────────────────────────────────────────────
SHAPES: dict[str, dict[str, str]] = {
    "declared-unwired": {
        "seed": "#2564",
        "story": "class registered in a wiring registry; the sole production caller never "
        "supplies the input, so the finder returns [] on its first line",
        "detectable": "partial",
    },
    "rubric-scope-gap": {
        "seed": "#2573",
        "story": "gate runs and scores, but no criterion mentions the class it exists to "
        "catch — all three fabricated-number canaries scored 92/92/82 and PASSED",
        "detectable": "no",
    },
    "cross-gate-falsehood": {
        "seed": "#2590",
        "story": "the CORRECT use of gate A makes gate B report a falsehood",
        "detectable": "no",
    },
    "dark-observability": {
        "seed": "#2589",
        "story": "a log/metric line that recorded nothing because a third state exits " "before it; its 'no data' reads as a measurement",
        "detectable": "partial",
    },
    "vacuous-empty": {
        "seed": "the AnnAssign blindness (2026-08-13)",
        "story": "the derivation returns an empty population and the emptiness assertion "
        "passes vacuously; a deliberately independent cross-check that copied the "
        "same walk agreed on None, so both read green",
        "detectable": "yes",
    },
    "exempt-by-incompleteness": {
        "seed": "#2619",
        "story": "the only way to be exempt is to be incomplete — a doc missing its stamp " "was silently skipped rather than flagged",
        "detectable": "partial",
    },
    # ── shapes found while building this census, not in the seed six ──────────
    "swallowed-exit": {
        "seed": "memory: 'A CI gate that cannot fail'",
        "story": "the gate runs but its exit status is discarded — a pipe hands the step " "the tail's status, or `|| true` eats it",
        "detectable": "yes",
    },
    "declared-advisory": {
        "seed": "ADR-108 (promoted advisory->blocking), #1927",
        "story": "not dark, but not armed either: continue-on-error / advisory-by-design. "
        "Belongs in the census because 'armed' is what a green board implies",
        "detectable": "yes",
    },
    "stale-exemption": {
        "seed": "found by this census, 2026-08-13",
        "story": "an allowlist/denylist/size-baseline entry naming a path that no longer "
        "exists — the exemption outlived its subject, so the gate is carrying a "
        "hole nobody is standing in",
        "detectable": "yes",
    },
    "unreferenced-entrypoint": {
        "seed": "memory: 'Read the deploy-critical lane BY NAME' (red-mained 08-10)",
        "story": "a guard script exists and works, and nothing runs it — an unregistered " "job prints nothing, and absent != pass",
        "detectable": "yes",
    },
}


@dataclass
class Gate:
    """One enforcement point. `id` is stable across runs so the inventory can diff."""

    id: str
    family: str
    name: str
    source: str  # path:line
    screened: bool  # did any detector actually get to look at this?
    unscreened_reason: str = ""
    risk_flags: list[str] = field(default_factory=list)
    verdict: str = "unproven"  # unproven | can-fail (proven) | cannot-fail | not-applicable
    evidence: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Recorded mutation proofs (#2578 slice 2). This and ATTEMPTED_UNPROVEN below are the
# ONLY hand-written things in the file, and deliberately so: a verdict must cite the
# mutation that produced it. Every gate named in neither reports `unproven`, which
# stays the honest default.
#
# THE BAR, and why it is this high
# --------------------------------
# A gate is `can-fail (proven)` ONLY when the defect it exists to catch was introduced
# on purpose and the gate was WATCHED failing. Reasoning that it *would* fail is not a
# verdict — that reasoning is exactly what produced six dark gates in four days (#2564,
# #2573, #2590, #2589, the AnnAssign instance, #2619). Every record below carries the
# command a future reader re-runs, the mutation, and the observed exit status.
#
# SCOPE IS PART OF THE VERDICT
# ----------------------------
# Three of the six proofs found a gate that fires for a narrow class and is silent
# outside it. That is not a defect and not a pass — it is the answer to "what does
# green here actually mean", which is the question the epic asks. A verdict that
# recorded only `can-fail` and dropped `scope` would be the same green-board illusion
# in a new file, so `scope` is a required field, and `""` means "no narrowing found".
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Proof:
    """One mutation proof. `command` + `mutation` must be enough to re-run it."""

    gate_name: str  # the census `name` at proof time — a shifted id must not silently re-attach
    command: str  # what was run, verbatim enough to re-run
    mutation: str  # the defect introduced on purpose
    observed: str  # what was watched happening (exit codes, both directions)
    scope: str  # the narrowing found, or "" for none
    proved_on: str  # ISO date, so a stale proof is visible as stale


PROVEN_CAN_FAIL: dict[str, Proof] = {
    # ── high-consequence: the blocking privacy step on the push-to-main path ──────
    "ci::ci-lint.yml::lint::15": Proof(
        gate_name="lint / Content-policy scan (ENFORCED —",
        command=(
            "CONTENT_FILTER_JSON=<fixture> python3 scripts/content_policy_scan.py" " && python3 deploy/pii_surface_guard.py --tracked"
        ),
        mutation=(
            "planted the fixture vocabulary's one keyword twice: in a new site/ HTML file "
            "(the content_policy_scan arm) and in a new git-tracked config/*.json "
            "(the pii_surface_guard --tracked repo-hygiene arm). Fixture vocabulary "
            "injected via CONTENT_FILTER_JSON so the proof never reads, and never echoes, "
            "the real off-repo vocabulary (#2370)."
        ),
        observed=(
            "ARMED: content_policy_scan exit 1 ('FAIL — 1 violation(s)', keyword masked); "
            "pii_surface_guard exit 1 ('1 violation(s) on the tracked config/seed JSON "
            "surface'). Clean-tree baseline 0/0. Reverted: 0/0."
        ),
        scope=(
            "BOTH halves are no-ops when no content-filter channel source resolves. Re-run "
            "with `env -u CONTENT_FILTER_JSON AWS_ACCESS_KEY_ID=x AWS_SHARED_CREDENTIALS_FILE=/dev/null "
            "AWS_CONFIG_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true`: the IDENTICAL planted "
            "keyword yields exit 0 from both commands, content_policy_scan emitting "
            "'::warning title=content-policy-scan skipped::' and pii_surface_guard "
            "'repo-hygiene arm SKIPPED'. This is designed (#2370 fail-visible, not "
            "fail-closed, so a public fork cannot red-wall) — but it means this gate's green "
            "is only load-bearing while the CONTENT_FILTER_JSON repo secret is present. "
            "Also: the CI step runs ONLY the --tracked arm, so pii_surface_guard's always-on "
            "structural arms (SSN / card-like / non-allowlisted email) never run in ci-lint; "
            "those reach the tree through scan_site() on the deploy path."
        ),
        proved_on="2026-08-13",
    ),
    # ── high-consequence: the blocking type gate (ADR-107 tier 2) ────────────────
    "ci::ci-lint.yml::lint::7": Proof(
        gate_name="lint / Mypy gate (ENFORCED — clean-module set, ADR-080)",
        command="python -m mypy --config-file mypy.ini $(python tests/mypy_clean_set.py)   # 440 files",
        mutation=(
            "appended to lambdas/common/auth_breaker.py (a clean-set module), one error code "
            "at a time: (a) `def p() -> int: return _undefined_symbol` [name-defined]; "
            "(b) `s = 'x'; return s.no_such_attr` [attr-defined]; "
            "(c) `def p(x: int) -> str: return x` [return-value]."
        ),
        observed=(
            "RE-PROVED 2026-08-21 (#2638), all three now RED: (a) exit 1 [name-defined]. "
            "(b) exit 1 [attr-defined]. (c) exit 1 [return-value] — this was 'exit 0 — SILENT' "
            "when first proved on 2026-08-13, and #2638's tranche 1 enabled the code on "
            "2026-08-15. Clean baseline 'Success: no issues found in 440 source files', "
            "reverted likewise."
        ),
        scope=(
            "mypy.ini's `disable_error_code = assignment, arg-type, operator` — three codes, "
            "down from four. `return-value` LEFT the list on 2026-08-15 (#2638 tranche 1: all "
            "32 sites were annotations under-describing already-correct code, so no returned "
            "value moved), and the re-proof above confirms the gate now reds on it. The three "
            "that remain are documented and deliberate, with per-code counts over the clean set "
            "measured in mypy.ini and recomputable via scripts/mypy_disable_cost.py — so this "
            "is scope, not rot. Recorded because 'mypy is green' reads as 'types are checked'. "
            "Orthogonally narrow: ADR-107's 'mypy tier-2' names a FILE-SCOPE ratchet (which "
            "modules are checked), not an error-code one; neither implies the other."
        ),
        proved_on="2026-08-21",
    ),
    # ── the named lead from slice 1 ──────────────────────────────────────────────
    "ci::ci-lint.yml::lint::3": Proof(
        gate_name="lint / Run flake8",
        command=(
            "flake8 lambdas/ --count --show-source --statistics || true; "
            "flake8 mcp/ --count --show-source --statistics || true; "
            "flake8 lambdas/ mcp/ --count --select=E9,F63,F7,F82 --show-source --statistics"
        ),
        mutation=(
            "two new files under lambdas/common/, one at a time: (a) a reference to an "
            "undefined name [F821]; (b) `import json` left unused [F401] plus `if 1 == None:` "
            "[E711]."
        ),
        observed=(
            "(a) step exit 1, F821 reported by the enforcing third line. "
            "(b) step exit 0 — while `flake8 <that file>` on its own exits 1 and prints both "
            "F401 and E711. Clean baseline 0, reverted 0."
        ),
        scope=(
            "can fail for E9/F63/F7/F82 ONLY. The two full-tree runs are wrapped in `|| true`, "
            "so every style and unused-import finding in lambdas/ and mcp/ is advisory in CI. "
            "The in-file comment says so ('Fail on syntax errors and undefined names; pass on "
            "style warnings'), i.e. deliberate — but it is narrower than CLAUDE.md's stated "
            "`flake8 lambdas/ mcp/` reflex, and black+ruff (both fully enforcing) are what "
            "actually hold style."
        ),
        proved_on="2026-08-13",
    ),
    "ci::ci-lint.yml::lint::5": Proof(
        gate_name="lint / Format gate (black — ENFORCED, config in pyproject.toml)",
        command="black --check lambdas/ mcp/ cdk/ tests/ scripts/ deploy/   # black==26.3.1, the CI pin",
        mutation="a new lambdas/common/ file written with non-black spacing (`def probe( a,b ):`, 2-space indent).",
        observed=(
            "exit 1, 'would reformat …/_census_probe.py — 1 file would be reformatted, 1458 "
            "unchanged'. Baseline 0 (1458 unchanged). Reverted 0."
        ),
        scope=(
            "the proof MUST use the pinned black. Homebrew black 25.9.0 (what the pre-commit "
            "hook runs, #2570) is a different formatter from the pinned 26.3.1 this gate runs; "
            "a verdict taken with the unpinned binary would be a verdict on a different gate."
        ),
        proved_on="2026-08-13",
    ),
    # ── two structural guards the census flagged `vacuous-empty` (precision data) ─
    "structural::test_module_size_guard.py": Proof(
        gate_name="test_module_size_guard.py",
        command="python3 -m pytest tests/test_module_size_guard.py -q",
        mutation=(
            "both arms, separately, with BASELINE never edited: (a) a new git-tracked 1,300-line "
            "lambdas/common/ file with no baseline entry and no exception comment; (b) 40 comment "
            "lines appended to lambdas/emails/daily_brief_lambda.py, an existing BASELINE entry "
            "(file restored from a byte copy, not from git, so the proof works on a dirty tree)."
        ),
        observed=(
            "(a) exit 1, `test_no_new_oversize_module` FAILED. (b) exit 1, 2 failed / 15 passed "
            "(`test_headroom_census_is_derived_from_source` among them) — the per-file ratchet "
            "fires. Baseline 17 passed; reverted 17 passed."
        ),
        scope=(
            "git-tracked files only: the same 1,300-line file left UNTRACKED passes (17 passed). "
            "Correct by design — the guard polices committed source — but it means a local "
            "pre-commit run before `git add` cannot see the file it is about to admit."
        ),
        proved_on="2026-08-13",
    ),
    "structural::test_lambdas_packaging_guard.py": Proof(
        gate_name="test_lambdas_packaging_guard.py",
        command="python3 -m pytest tests/test_lambdas_packaging_guard.py -q",
        mutation=(
            "both ratchets: (a) `git add -N lambdas/_census_probe.py` — a loose module at the "
            "root; (b) `git mv lambdas/coach/__init__.py lambdas/coach/_init_moved.py`."
        ),
        observed=(
            "(a) exit 1, `test_no_loose_python_modules_at_the_lambdas_root` FAILED. "
            "(b) exit 1, `test_every_lambdas_package_has_an_init` FAILED. Baseline 3 passed; "
            "reverted 3 passed."
        ),
        scope="",
        proved_on="2026-08-13",
    ),
    # ── #2938: the gate that was PROVEN unable to fail, then repaired ────────────
    # This is the first entry recorded from a LIVE PRODUCTION OBSERVATION rather than a
    # deliberately planted mutation — the defect was already running when it was found.
    "ci::ci-cd.yml::visual-qa::4": Proof(
        gate_name="visual-qa / Run visual + AI-vision QA sweep",
        command="python3 tests/visual_qa.py --screenshot --ai-qa --ai-qa-max-tier 1 --reader-truth",
        mutation=(
            "NONE PLANTED — the cannot-fail state was observed live in run 32509917798 / job "
            "96909117231 (2026-08-21), a real fleet deploy. The 'mutation' was the standing "
            "config: the job installs only playwright, so `import bedrock_client` raises "
            "ModuleNotFoundError('boto3'). Re-create by dropping boto3 from the job's pip install."
        ),
        observed=(
            "PRE-FIX: both AI sections printed '⚠ AI-QA unavailable — could not import "
            "bedrock_client: No module named boto3' and the job still concluded SUCCESS (exit 0) "
            "— a declared-gating check that could not fail, on the deploy path, since 2026-06-05. "
            "POST-FIX: boto3 is installed in all three visual-qa copies, and run_sweep returns "
            "`failed == 0 and not ai_gate_failures`, so the same unavailable state now exits 1. "
            "The decision function is mutation-proved over all six status shapes in "
            "tests/test_ai_gate_must_run_2938.py (11 tests), including that a budget-tier pause "
            "still does NOT fail."
        ),
        scope=(
            "HONEST LIMIT: the post-fix RED has been proven at the decision-function level, not "
            "yet observed end-to-end in CI — this PR's own visual-qa job runs WITH boto3, so it "
            "goes green and cannot demonstrate the failure. Confirming the red end-to-end needs a "
            "deliberate run with boto3 removed, which is not worth wedging the deploy path for; "
            "the next genuine Bedrock outage will demonstrate it for free. Also note the "
            "deterministic half of this job (Playwright sweep, leak-token sweep) was armed and "
            "working throughout — only the two AI gates were dark."
        ),
        proved_on="2026-08-21",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Gates ATTEMPTED and NOT proved. A first-class result, not an omission: the whole
# failure mode this epic exists for is an enforcement point everyone assumes works.
# "I could not make it fail" recorded with the reason is a lead; skipping it silently
# is how the assumption survives. Nothing here is a claim that the gate is dark.
# ─────────────────────────────────────────────────────────────────────────────
ATTEMPTED_UNPROVEN: dict[str, str] = {
    "ci::ci-lint.yml::lint::10": (
        "Secret scan (gitleaks) — NOT PROVED. `gitleaks` is not installed on this machine and "
        "the gate's semantics are the ACTION's, not a binary's: gitleaks-action scans the "
        "pushed-commit RANGE on a push event and silently no-ops on workflow_dispatch (the "
        "#1336 follow-up comment in the workflow says so). Neither the range behaviour nor the "
        "dispatch no-op is reproducible locally, so any local exit code would be a verdict on a "
        "different gate. Needs a scratch repo + a real push event — slice 3."
    ),
    "qa::lambdas/operational/qa_smoke_lambda.py::check_hero_weight_arithmetic": (
        "NOT PROVED, and the attempt found a lead. The check is a live-site fetch wrapped around "
        "a pure assessor, `assess_hero_weight(journey)`, so the assessor is the mutable part. "
        "Importing it offline needs a chain of runtime env vars discovered one KeyError at a "
        "time (S3_BUCKET -> EMAIL_RECIPIENT -> ...); with S3_BUCKET/DDB_TABLE/AWS_REGION/"
        "EMAIL_RECIPIENT/EMAIL_SENDER/SITE_BASE_URL set it imports. But BOTH an arithmetically "
        "consistent payload {start 200, current 190, lost 10} and a deliberately inconsistent "
        "one {start 200, current 190, lost 42} returned the SAME (True, 'pre-start / no weigh-in "
        "— no weight claim to reconcile'): a pre-start branch short-circuits ahead of the "
        "arithmetic. Either my payload keys are wrong or the pre-start guard swallows the check "
        "during the cycle-13 pre-genesis window (the #931/#939 countdown state, and the "
        "'genesis-week present-None' class). Not filed as a defect — I could not distinguish "
        "the two inside the time-box. It is the first thing slice 3 should re-measure, and it "
        "is why NONE of the 21 qa-smoke checks carry a verdict here."
    ),
    "guard::deploy/check_deploy_drift.py": (
        "NOT ATTEMPTED as a mutation, deliberately. The defect this guard exists to catch is "
        "divergence between the CDK tree and DEPLOYED AWS state; introducing it means mutating "
        "live infrastructure, which #2578's guardrail and this worktree's brief both forbid. "
        "A verdict needs a stubbed CloudFormation client, i.e. a harness — slice 3."
    ),
}


def log(msg: str) -> None:
    """Every bound the sweep applies is announced. A census that quietly truncates is
    the same defect it is auditing (#2578 acceptance)."""
    print(f"[census] {msg}", file=sys.stderr)


def _tracked_files(root: Path) -> list[Path]:
    """Repo files, from git when available so untracked scratch never enters the count."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [root / line for line in out.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        log("git ls-files unavailable — falling back to os.walk (may include untracked files)")
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "cdk.out", "__pycache__", ".venv"}]
            found.extend(Path(dirpath) / f for f in filenames)
        return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# The AnnAssign-safe walk. Taxonomy instance 5 lives here.
# ─────────────────────────────────────────────────────────────────────────────
def _module_level_bindings(tree: ast.Module) -> list[tuple[str, ast.expr | None, int]]:
    """Every module-level name binding as (name, value, lineno).

    Handles BOTH ``NAME = ...`` (ast.Assign) and ``NAME: T = ...`` (ast.AnnAssign).
    Walking only ``ast.Assign`` is the exact blindness that disarmed three gates on
    2026-08-13 when one annotation was added to ``SOURCE_REGISTRY``; the census must
    not inherit it. `tests/test_gate_census_2578.py` mutation-proves this.
    """
    out: list[tuple[str, ast.expr | None, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.append((tgt.id, node.value, node.lineno))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.append((node.target.id, node.value, node.lineno))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Family 1 — CI steps. A workflow step is where "the board is green" is decided.
# ─────────────────────────────────────────────────────────────────────────────
_GATE_VERB = re.compile(
    r"\b(pytest|flake8|black|ruff|mypy|gitleaks|codeql|check_[a-z_]+\.py|"
    # #2746: `[a-z_]*_eval\.py` — the golden-brief/golden-surface harnesses are gates
    # by function and were invisible to every clause above, so the step named
    # "Deterministic verdict (gating, free)" sat in `steps_nongate` while advertising
    # itself as gating. Found by adjudicating #2639's residual, which is what that
    # residual is for. Same widen-the-derivation fix as #2639's own, one verb over.
    r"[a-z_]*_guard\.py|[a-z_]*_gate\.py|[a-z_]*_eval\.py|verify_[a-z_]+|smoke_test|audit|"
    r"--strict|--check|npx cdk diff|visual_qa|reader_truth|doc_index|playwright)\b",
    re.I,
)
# #2639: a step is a gate when it CAN FAIL THE BUILD, and the most direct evidence of
# that is the step deliberately exiting non-zero. `_GATE_VERB` recognises gates by the
# TOOL they run, which misses any step that enforces something in plain shell — and two
# real, enforcing steps in ci-lint.yml were invisible for exactly that reason:
#
#     Syntax check (py_compile)   ends `if [ "$FAILED" -gt 0 ]; then … exit 1; fi`
#     Check lambda_map coverage   ends `if [ $MISSING -gt 0 ]; then … exit 1; fi`
#
# Both were counted in `steps_nongate`, so the census reported 421 gates when the true
# number was at least 423. That is the census's own subject — a blind spot in the
# instrument built to find blind spots — and the fix has to WIDEN THE DERIVATION rather
# than add two rows, because a hand-added row is the failure this census exists to replace.
#
# Deliberately narrow: `exit 0` is not here (that is a SWALLOW idiom, below), and a bare
# `exit` with no code is not either. What counts is an explicit non-zero exit the step
# author wrote on purpose.
_GATE_ENFORCES = re.compile(
    r"\bexit\s+[1-9][0-9]*\b|\bsys\.exit\s*\(\s*[1-9]|\braise\s+SystemExit\s*\(\s*[1-9]|\|\|\s*exit\b",
    re.M,
)

# Idioms that discard a command's exit status. The pipe cases are the memory-file
# incident "a piped step exits with tail's status" made mechanical.
_SWALLOW = re.compile(r"\|\|\s*(true|:|echo)|\|\s*(tee|tail|head|grep|sed|awk|cat)\b|set \+e|exit 0\s*$", re.M)


def discover_ci_gates(root: Path) -> tuple[list[Gate], dict[str, int]]:
    import yaml  # local: keeps the module importable where PyYAML is absent

    gates: list[Gate] = []
    counters = {
        "workflows": 0,
        "jobs": 0,
        "steps_total": 0,
        "steps_nongate": 0,
        "steps_uses_action": 0,
        # #2639: the census's own false-negative measurement. `by_verb_only` and
        # `by_enforcement_only` are the two detectors' disjoint catches; the second is the
        # number of gates `_GATE_VERB` alone was missing, i.e. the error this issue found,
        # now reported as a number instead of discovered by hand.
        "by_verb_only": 0,
        "by_enforcement_only": 0,
        "by_both": 0,
    }
    nongate_labels: list[str] = []
    wf_dir = root / ".github" / "workflows"
    for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        counters["workflows"] += 1
        try:
            doc = yaml.safe_load(_read(wf)) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - malformed workflow
            gates.append(
                Gate(
                    id=f"ci::{wf.name}",
                    family="ci-step",
                    name=wf.name,
                    source=str(wf.relative_to(root)),
                    screened=False,
                    unscreened_reason=f"workflow YAML did not parse: {exc.__class__.__name__}",
                )
            )
            continue
        for job_name, job in (doc.get("jobs") or {}).items():
            counters["jobs"] += 1
            if not isinstance(job, dict):
                continue
            job_advisory = job.get("continue-on-error") is True
            for idx, step in enumerate(job.get("steps") or []):
                counters["steps_total"] += 1
                if not isinstance(step, dict):
                    continue
                run = step.get("run") or ""
                uses = step.get("uses") or ""
                label = step.get("name") or (uses or run.strip().splitlines()[0] if run.strip() else f"step{idx}")
                advisory = step.get("continue-on-error") is True or job_advisory

                if not run:
                    # A `uses:` step's gate logic lives in someone else's repo. It is
                    # COUNTED and reported unscreened — never dropped.
                    counters["steps_uses_action"] += 1
                    if uses and _GATE_VERB.search(str(uses)):
                        gates.append(
                            Gate(
                                id=f"ci::{wf.name}::{job_name}::{idx}",
                                family="ci-step",
                                name=f"{job_name} / {label}",
                                source=f"{wf.relative_to(root)}",
                                screened=False,
                                unscreened_reason=f"third-party action ({uses}) — gate logic is not in this repo",
                                risk_flags=["declared-advisory"] if advisory else [],
                            )
                        )
                    continue

                verb_hit = bool(_GATE_VERB.search(run))
                enforce_hit = bool(_GATE_ENFORCES.search(run))
                if not verb_hit and not enforce_hit and not advisory:
                    counters["steps_nongate"] += 1
                    # Kept so the report can SHOW its residual rather than assert a rate.
                    # Box 2 asks how many of these are really gates; that is adjudication,
                    # and an instrument that prints the list is what makes it possible.
                    nongate_labels.append(f"{wf.name}::{job_name} / {label}")
                    continue
                if verb_hit and enforce_hit:
                    counters["by_both"] += 1
                elif verb_hit:
                    counters["by_verb_only"] += 1
                else:
                    counters["by_enforcement_only"] += 1

                flags: list[str] = []
                if _SWALLOW.search(run):
                    flags.append("swallowed-exit")
                if advisory:
                    flags.append("declared-advisory")
                gates.append(
                    Gate(
                        id=f"ci::{wf.name}::{job_name}::{idx}",
                        family="ci-step",
                        name=f"{job_name} / {label}",
                        source=f"{wf.relative_to(root)}",
                        screened=True,
                        risk_flags=flags,
                        detail={"workflow": wf.name, "job": job_name, "if": str(step.get("if") or "")},
                    )
                )
    counters["nongate_sample"] = nongate_labels
    return gates, counters


# ─────────────────────────────────────────────────────────────────────────────
# Family 2 — guard entrypoints (python) and their shell siblings.
# ─────────────────────────────────────────────────────────────────────────────
_GUARD_NAME = re.compile(r"(^|/)(check_|verify_|.*_guard|.*_gate|.*guard_|pii_surface|.*_audit)[a-z0-9_]*\.py$", re.I)
_NONZERO_EXIT = re.compile(r"sys\.exit\(\s*(?!0\s*\))|SystemExit\(\s*(?!0)|exit\(1\)")


def discover_guard_scripts(root: Path, files: list[Path]) -> tuple[list[Gate], dict[str, int]]:
    gates: list[Gate] = []
    counters = {"candidates": 0, "no_nonzero_exit": 0, "shell_unscreened": 0}

    # The reference corpus is EVERY tracked non-doc file plus the git hooks. A narrower
    # corpus is how the first version of this detector produced 2 false positives out of
    # 3: `check_css_tokens.py` is run by `tests/test_css_tokens.py` (which imports the
    # module by STEM, not filename) and `verify_oidc_iam.py` by `deploy/drift_sentinel.py`
    # (a directory the corpus did not include). A caller-detector that does not read all
    # the callers is the same defect this census exists to find.
    hooks = list((root / ".git" / "hooks").glob("*")) if (root / ".git" / "hooks").is_dir() else []
    referenced_corpus = "\n".join(
        _read(p) for p in files + hooks if p.suffix in {".py", ".yml", ".yaml", ".sh", ".toml", ".cfg", ""} or p.name == "Makefile"
    )

    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.suffix == ".sh" and re.search(r"(smoke|verify|check|guard|rollback)", rel):
            # Shell gates are real gates; slice 1 has no shell detector. Counted,
            # reported unscreened, named in the report. NOT dropped.
            counters["shell_unscreened"] += 1
            gates.append(
                Gate(
                    id=f"guard::{rel}",
                    family="guard-script",
                    name=rel,
                    source=rel,
                    screened=False,
                    unscreened_reason="shell entrypoint — slice 1 ships no shell detector",
                )
            )
            continue
        if path.suffix != ".py" or not _GUARD_NAME.search(rel):
            continue
        if rel.startswith("tests/test_"):
            continue  # covered by the structural-test family
        counters["candidates"] += 1
        text = _read(path)
        if not _NONZERO_EXIT.search(text):
            counters["no_nonzero_exit"] += 1
            gates.append(
                Gate(
                    id=f"guard::{rel}",
                    family="guard-script",
                    name=rel,
                    source=rel,
                    screened=True,
                    risk_flags=["swallowed-exit"],
                    detail={"note": "no nonzero-exit path found — it may be a library, or it may be unable to fail"},
                )
            )
            continue
        flags = _static_source_flags(text)
        # Count references excluding the file's own text; match the module STEM as well
        # as the filename, since a python caller imports `check_css_tokens`, not
        # `check_css_tokens.py`.
        others = referenced_corpus.replace(text, "")
        if path.name not in others and rel not in others and re.search(rf"\b{re.escape(path.stem)}\b", others) is None:
            flags.append("unreferenced-entrypoint")
        gates.append(
            Gate(
                id=f"guard::{rel}",
                family="guard-script",
                name=rel,
                source=rel,
                screened=True,
                risk_flags=flags,
            )
        )
    return gates, counters


# ─────────────────────────────────────────────────────────────────────────────
# Family 3 — in-source gate registries, expanded ENTRY BY ENTRY.
# #2564's whole lesson is that the registry entry, not the registry, is the gate.
# ─────────────────────────────────────────────────────────────────────────────
_REGISTRY_NAME = re.compile(
    r"^_?(GATE_CLASSES|.*_CHECKS|.*_RULES|.*ALLOWLIST|.*DENYLIST|.*_EXEMPT.*|"
    r"BASELINE|.*_BASELINE|CHOKEPOINTS|.*_GATES|.*_GUARDS|GATE_.*|.*_CLASSES)$"
)
_REGISTRY_ROOTS = ("lambdas", "tests", "scripts", "deploy", "mcp")


def _literal_entries(value: ast.expr | None) -> list[str] | None:
    """Entry names of a dict/set/list/tuple/frozenset literal, or None if not literal."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"frozenset", "set", "dict"}:
        value = value.args[0] if value.args else None
    if isinstance(value, ast.Dict):
        return [k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
        return [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def discover_registry_gates(root: Path, files: list[Path]) -> tuple[list[Gate], dict[str, int]]:
    gates: list[Gate] = []
    counters = {"registries": 0, "non_literal_registries": 0, "entries": 0, "annassign_registries": 0}

    py = [p for p in files if p.suffix == ".py" and p.relative_to(root).parts[0] in _REGISTRY_ROOTS]
    corpus_by_file = {p: _read(p) for p in py}
    all_source = "\n".join(corpus_by_file.values())

    for path in py:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(corpus_by_file[path])
        except SyntaxError:
            continue
        annassign_names = {n.target.id for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        for name, value, lineno in _module_level_bindings(tree):
            if not _REGISTRY_NAME.match(name):
                continue
            counters["registries"] += 1
            if name in annassign_names:
                counters["annassign_registries"] += 1
            entries = _literal_entries(value)
            if entries is None:
                counters["non_literal_registries"] += 1
                gates.append(
                    Gate(
                        id=f"registry::{rel}::{name}",
                        family="registry",
                        name=f"{name} (whole registry)",
                        source=f"{rel}:{lineno}",
                        screened=False,
                        unscreened_reason="registry value is not a literal (comprehension/call/derived) — "
                        "entries cannot be enumerated statically",
                    )
                )
                continue
            # Module-level flags are recorded on the entry's `detail`, NOT on its
            # risk_flags: attaching one file's syntactic smell to all N of its entries
            # would multiply a single lead into N and make the histogram a lie about
            # how many distinct leads exist.
            module_flags = _static_source_flags(corpus_by_file[path])
            # Exemption DATA (allowlists, denylists, size baselines) and behavioural
            # registries fail differently, and conflating them is how the first run of
            # this detector reported 39 `declared-unwired` hits that were mostly a
            # filename in a size BASELINE — an entry that legitimately appears exactly
            # once. Exemption entries get the shape that actually applies to them:
            # a stale exemption, i.e. an exempted path that no longer exists.
            is_exemption_data = bool(re.search(r"ALLOWLIST|DENYLIST|BASELINE|_EXEMPT", name))
            for entry in entries:
                counters["entries"] += 1
                flags: list[str] = []
                if is_exemption_data:
                    if "/" in entry and Path(entry).suffix and not (root / entry).exists():
                        flags.append("stale-exemption")
                        counters["stale_exemptions"] = counters.get("stale_exemptions", 0) + 1
                    mentions = -1
                else:
                    # #2564's shape: an entry name that appears nowhere but its own
                    # registry and the test that reads the registry.
                    mentions = all_source.count(f'"{entry}"') + all_source.count(f"'{entry}'")
                    if mentions <= 1:
                        flags.append("declared-unwired")
                gates.append(
                    Gate(
                        id=f"registry::{rel}::{name}::{entry}",
                        family="registry",
                        name=f"{name}[{entry}]",
                        source=f"{rel}:{lineno}",
                        screened=True,
                        risk_flags=flags,
                        detail={
                            "registry": name,
                            "entry": entry,
                            "source_mentions": mentions,
                            "module_flags": module_flags,
                            "annassign_bound": name in annassign_names,
                        },
                    )
                )
    return gates, counters


# ─────────────────────────────────────────────────────────────────────────────
# Family 4 — the qa-smoke check registry (its own family: these are runtime checks
# whose green is emailed and alarmed on, not CI steps).
# ─────────────────────────────────────────────────────────────────────────────
def discover_qa_smoke_gates(root: Path) -> tuple[list[Gate], dict[str, int]]:
    gates: list[Gate] = []
    counters = {"modules": 0, "check_functions": 0, "unregistered": 0}
    qa_files = sorted((root / "lambdas" / "operational").glob("qa_*.py"))
    registry_text = "\n".join(_read(p) for p in qa_files)
    for path in qa_files:
        counters["modules"] += 1
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("check_") or node.name == "check_steps":
                continue
            counters["check_functions"] += 1
            flags: list[str] = []
            # registered = named somewhere other than its own `def` line
            if registry_text.count(node.name) <= 1:
                flags.append("unreferenced-entrypoint")
                counters["unregistered"] += 1
            body = ast.get_source_segment(text, node) or ""
            flags += _static_source_flags(body)
            gates.append(
                Gate(
                    id=f"qa::{rel}::{node.name}",
                    family="qa-smoke-check",
                    name=node.name,
                    source=f"{rel}:{node.lineno}",
                    screened=True,
                    risk_flags=sorted(set(flags)),
                )
            )
    return gates, counters


# ─────────────────────────────────────────────────────────────────────────────
# Family 5 — structural pytest gates (repo-shape ratchets).
# ─────────────────────────────────────────────────────────────────────────────
def discover_structural_test_gates(root: Path) -> tuple[list[Gate], dict[str, int]]:
    sys.path.insert(0, str(root / "tests"))
    try:
        from premerge_derivation import discover_tree_sweeping_test_files  # type: ignore
    except ImportError:  # pragma: no cover
        log("tests/premerge_derivation.py not importable — structural-test family SKIPPED (n unknown)")
        return [], {"importable": 0}
    names = sorted(discover_tree_sweeping_test_files(root / "tests"))
    gates: list[Gate] = []
    for name in names:
        text = _read(root / "tests" / name)
        gates.append(
            Gate(
                id=f"structural::{name}",
                family="structural-test",
                name=name,
                source=f"tests/{name}",
                screened=True,
                risk_flags=sorted(set(_static_source_flags(text))),
            )
        )
    return gates, {"importable": 1, "found": len(names)}


# ─────────────────────────────────────────────────────────────────────────────
# Family 6 — the drift-sentinel per-check registry (#3129). deploy/drift_sentinel.py's
# run_sweep() builds a `checks = {...}` dict whose entries are exactly what
# remediation/drift_report.py's as_signal() reads to decide needs-human triage
# (`flagging = {k: v for k, v in checks.items() if v.get("status") == "drift"}`) — each
# check_* function behind those entries is a real, armed gate. None of the other five
# families walk deploy/ for this shape, so a can-it-fail proof for e.g.
# check_codeql_alerts (#3112, the #2578 autopsy) had no registerable home and this
# whole family was invisible to the census.
#
# Derived the SAME two ways discover_qa_smoke_gates (Family 4) already proves out for
# an almost-identical shape: the check_* NAMING CONVENTION finds the candidate
# population, and "registered" means the name is referenced somewhere beyond its own
# definition/import line — i.e. actually wired into drift_sentinel.py's own
# registration surface, the same file whose run_sweep() dict drives the sweep. A
# check_* function that exists but was never wired in gets Family 4's exact shape
# (`unreferenced-entrypoint`): flagged, never dropped from the count.
#
# The module-size ratchet (#1665) forced drift_sentinel.py to extract four siblings —
# sentinel_github.py, sentinel_quota.py, sentinel_replication.py, sentinel_cadence.py —
# each re-imported by name (`from sentinel_github import (..., check_github_config, ...)`)
# so run_sweep() and every existing caller/test keep the `ds.check_*` names. A walker
# that only looks at drift_sentinel.py's own function defs would miss every check_*
# defined in those four modules entirely — this walks BOTH: local defs, and check_*
# names pulled in via `from <sibling> import (...)`, resolved back to the sibling's own
# file+line so the source points at the real definition, not the re-export site.
# session_postflight.py (#2/POSTFLIGHT REUSE in the module docstring) is deliberately
# OUT of scope here — it is REUSED, not one of the #1665-extracted siblings, and its
# three sub-checks are folded into drift_sentinel's own `check_postflight` gate, which
# this walker already finds as a local def.
_SENTINEL_SIBLINGS = ("sentinel_github", "sentinel_quota", "sentinel_replication", "sentinel_cadence")


def _sentinel_check_defs(text: str) -> dict[str, tuple[int, str]]:
    """Module-level `check_*` function defs in one file: name -> (lineno, source segment)."""
    out: dict[str, tuple[int, str]] = {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("check_"):
            out[node.name] = (node.lineno, ast.get_source_segment(text, node) or "")
    return out


def discover_sentinel_gates(root: Path) -> tuple[list[Gate], dict[str, int]]:
    gates: list[Gate] = []
    counters = {"local_check_functions": 0, "sibling_check_functions": 0, "unregistered": 0}
    deploy_dir = root / "deploy"
    main_rel = "deploy/drift_sentinel.py"
    main_text = _read(deploy_dir / "drift_sentinel.py")
    if not main_text:
        log("deploy/drift_sentinel.py unreadable — sentinel family SKIPPED (n unknown)")
        return [], {"importable": 0}
    try:
        main_tree = ast.parse(main_text)
    except SyntaxError:
        log("deploy/drift_sentinel.py did not parse — sentinel family SKIPPED (n unknown)")
        return [], {"importable": 0}

    def _registered(name: str) -> bool:
        # "Registered" = referenced somewhere beyond its own def/import line in
        # drift_sentinel.py — the file whose run_sweep() checks dict is what
        # remediation/drift_report.py actually reads. Same idiom as Family 4's
        # `registry_text.count(node.name) <= 1`.
        return main_text.count(name) > 1

    # Local check_* functions, defined directly in drift_sentinel.py.
    for name, (lineno, body) in sorted(_sentinel_check_defs(main_text).items()):
        counters["local_check_functions"] += 1
        flags: list[str] = [] if _registered(name) else ["unreferenced-entrypoint"]
        if "unreferenced-entrypoint" in flags:
            counters["unregistered"] += 1
        flags += _static_source_flags(body)
        gates.append(
            Gate(
                id=f"sentinel::{main_rel}::{name}",
                family="sentinel-check",
                name=name,
                source=f"{main_rel}:{lineno}",
                screened=True,
                risk_flags=sorted(set(flags)),
            )
        )

    # check_* names pulled in from the #1665-extracted siblings — resolved to their
    # OWN file+line, never the drift_sentinel.py re-export line.
    for node in main_tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.module in _SENTINEL_SIBLINGS):
            continue
        sib_rel = f"deploy/{node.module}.py"
        sib_text = _read(root / sib_rel)
        sib_defs = _sentinel_check_defs(sib_text) if sib_text else {}
        for alias in node.names:
            name = alias.name
            if not name.startswith("check_"):
                continue
            counters["sibling_check_functions"] += 1
            flags = [] if _registered(name) else ["unreferenced-entrypoint"]
            if "unreferenced-entrypoint" in flags:
                counters["unregistered"] += 1
            lineno, body = sib_defs.get(name, (None, ""))
            flags += _static_source_flags(body)
            gates.append(
                Gate(
                    id=f"sentinel::{sib_rel}::{name}",
                    family="sentinel-check",
                    name=name,
                    source=f"{sib_rel}:{lineno}" if lineno else sib_rel,
                    screened=bool(sib_text),
                    unscreened_reason="" if sib_text else f"{sib_rel} unreadable — imported name could not be resolved to a definition",
                    risk_flags=sorted(set(flags)),
                )
            )
    return gates, counters


# ─────────────────────────────────────────────────────────────────────────────
# The source-text detectors. Syntactic, imprecise, and honest about it.
# ─────────────────────────────────────────────────────────────────────────────
_USES_AST_ASSIGN = re.compile(r"ast\.Assign\b")
_USES_ANNASSIGN = re.compile(r"ast\.AnnAssign\b")
_EMPTY_ASSERT = re.compile(r"assert\s+not\s+\w|==\s*\[\]|==\s*set\(\)|==\s*\{\}|len\([^)]+\)\s*==\s*0")
_POPULATION_FLOOR = re.compile(r"len\([^)]+\)\s*>=?\s*[1-9]|assert\s+\w+,\s|\bhas gone blind\b|\bnot found\b")
_SKIP_ON_ABSENCE = re.compile(r"if\s+not\s+[\w.\[\]\"']+\s*:\s*(\n\s+)?(continue|return\b|pass\b)")


def _static_source_flags(text: str) -> list[str]:
    flags: list[str] = []
    if _USES_AST_ASSIGN.search(text) and not _USES_ANNASSIGN.search(text):
        # The 2026-08-13 instance, generalised: an AST walk that sees `X = {...}`
        # but not `X: T = {...}` returns an empty population and passes.
        flags.append("vacuous-empty")
    if _EMPTY_ASSERT.search(text) and not _POPULATION_FLOOR.search(text):
        # Asserts a derived collection is empty with no floor on the population —
        # if the derivation breaks, the assertion still passes.
        flags.append("vacuous-empty")
    if _SKIP_ON_ABSENCE.search(text):
        # #2619's shape: the exemption predicate is satisfied by the defect.
        flags.append("exempt-by-incompleteness")
    if re.search(r"\|\|\s*true|except\s+Exception:\s*(\n\s+)?pass", text):
        flags.append("swallowed-exit")
    return sorted(set(flags))


# ─────────────────────────────────────────────────────────────────────────────
# Assembly + report
# ─────────────────────────────────────────────────────────────────────────────
FAMILIES = ("ci", "guard", "registry", "qa", "structural", "sentinel")


def build_census(root: Path | None = None, families: Iterable[str] = FAMILIES) -> dict[str, Any]:
    root = root or REPO_ROOT
    families = tuple(families)
    dropped = [f for f in FAMILIES if f not in families]
    if dropped:
        log(f"BOUNDED SWEEP — families dropped by --family: {', '.join(dropped)}. Their n is NOT in this report.")

    files = _tracked_files(root)
    gates: list[Gate] = []
    counters: dict[str, dict[str, int]] = {}

    if "ci" in families:
        g, c = discover_ci_gates(root)
        gates += g
        counters["ci"] = c
    if "guard" in families:
        g, c = discover_guard_scripts(root, files)
        gates += g
        counters["guard"] = c
    if "registry" in families:
        g, c = discover_registry_gates(root, files)
        gates += g
        counters["registry"] = c
    if "qa" in families:
        g, c = discover_qa_smoke_gates(root)
        gates += g
        counters["qa"] = c
    if "structural" in families:
        g, c = discover_structural_test_gates(root)
        gates += g
        counters["structural"] = c
    if "sentinel" in families:
        g, c = discover_sentinel_gates(root)
        gates += g
        counters["sentinel"] = c

    # A verdict attaches by id, and a CI-step id is positional (`::<job>::<index>`), so
    # inserting one step into a workflow silently slides every later id onto a DIFFERENT
    # gate. The recorded `gate_name` is the cross-check: a proof whose name no longer
    # matches the gate at that id is REFUSED, not re-attached. Mismatches and ids that
    # match nothing are surfaced on the census (`orphan_proofs`) and asserted in
    # tests/test_gate_census_2578.py — a stale verdict is the failure this epic is about.
    matched: set[str] = set()
    mismatched: list[dict[str, str]] = []
    for gate in gates:
        proof = PROVEN_CAN_FAIL.get(gate.id)
        if proof is None:
            continue
        if proof.gate_name != gate.name:
            mismatched.append({"id": gate.id, "recorded_name": proof.gate_name, "current_name": gate.name})
            continue
        matched.add(gate.id)
        gate.verdict = "can-fail (proven)"
        gate.evidence = f"{proof.mutation} -> {proof.observed}"
        gate.detail["proof"] = asdict(proof)
    for gate in gates:
        note = ATTEMPTED_UNPROVEN.get(gate.id)
        if note:
            gate.verdict = "attempted-unproven"
            gate.evidence = note
    # On a BOUNDED run (--family) a proof for a dropped family is out of scope, not an
    # orphan. Reporting it as one would train the reader to ignore the line.
    full_run = not dropped
    orphans = (
        [
            {"id": gid, "recorded_name": PROVEN_CAN_FAIL[gid].gate_name, "current_name": "<no gate at this id>"}
            for gid in PROVEN_CAN_FAIL
            if gid not in matched and not any(m["id"] == gid for m in mismatched)
        ]
        if full_run
        else []
    )
    unattached_attempts = sorted(set(ATTEMPTED_UNPROVEN) - {g.id for g in gates}) if full_run else []

    return {
        "orphan_proofs": orphans + mismatched,
        "unattached_attempts": unattached_attempts,
        "attempted_unproven": ATTEMPTED_UNPROVEN,
        "shapes": SHAPES,
        "families_run": list(families),
        "families_dropped": dropped,
        "counters": counters,
        "annassign_exposure": annassign_exposure(root, files),
        "gates": [asdict(g) for g in gates],
    }


def annassign_exposure(root: Path, files: list[Path]) -> dict[str, Any]:
    """The 2026-08-13 instance, measured rather than anecdotal.

    Two populations, and their product is the exposure: (a) source files whose AST walk
    handles ``ast.Assign`` and never ``ast.AnnAssign`` — every one of them is blind to
    (b) module-level registries bound with an annotation. One annotation added to
    ``SOURCE_REGISTRY`` disarmed three gates at once; nothing in the repo could answer
    "how many more are one annotation away" until this number existed.
    """
    blind_walkers: list[str] = []
    annotated_registries: list[str] = []
    for path in files:
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        if _USES_AST_ASSIGN.search(text) and not _USES_ANNASSIGN.search(text):
            blind_walkers.append(rel)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id.isupper():
                annotated_registries.append(f"{rel}::{node.target.id}")
    return {
        "blind_walkers": sorted(blind_walkers),
        "n_blind_walkers": len(blind_walkers),
        "annotated_module_constants": sorted(annotated_registries),
        "n_annotated_module_constants": len(annotated_registries),
    }


def _wrap(text: str, width: int = 88, indent: str = " " * 16) -> str:
    """Soft-wrap a proof field so a long `observed` stays readable in a terminal."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return f"\n{indent}".join(out)


def render_report(census: dict[str, Any]) -> str:
    gates = census["gates"]
    n = len(gates)
    screened = [g for g in gates if g["screened"]]
    unscreened = [g for g in gates if not g["screened"]]
    flagged = [g for g in screened if g["risk_flags"]]
    proven = [g for g in gates if g["verdict"] == "can-fail (proven)"]
    attempted = [g for g in gates if g["verdict"] == "attempted-unproven"]
    orphan_proofs = census.get("orphan_proofs") or []
    unattached = census.get("unattached_attempts") or []

    lines: list[str] = []
    add = lines.append
    add("=" * 78)
    add("GATE CENSUS — #2578 (slice 1 inventory + static screen; slice 2 mutation verdicts)")
    add("=" * 78)
    add("")
    add(f"gates found                  n = {n}")
    add(f"  statically screened        n = {len(screened)}  ({len(screened) / n:.0%})" if n else "  (none)")
    add(f"  could NOT be screened      n = {len(unscreened)}")
    add(f"  carrying >=1 risk flag     n = {len(flagged)}")
    add(f"  verdict proven can-fail    n = {len(proven)}   <- each cites the mutation that produced it")
    add(f"  attempted, NOT proved      n = {len(attempted)}   <- recorded with the reason, never skipped")
    add(f"  no verdict attempted       n = {n - len(proven) - len(attempted)}")
    add("")
    add(_render_error_bars(census))
    add("")

    add("-- VERDICTS: proven able to fail (mutation introduced, failure watched) " + "-" * 6)
    if not proven:
        add("  (none recorded — PROVEN_CAN_FAIL is empty)")
    for g in sorted(proven, key=lambda x: x["id"]):
        p = g["detail"].get("proof") or {}
        add(f"  {g['id']}")
        add(f"      gate      {g['name']}  [{g['source']}]")
        add(f"      command   {p.get('command', '')}")
        add(f"      mutation  {_wrap(p.get('mutation', ''))}")
        add(f"      observed  {_wrap(p.get('observed', ''))}")
        add(f"      scope     {_wrap(p.get('scope') or 'none found — the gate fires for the whole class it names')}")
        add(f"      proved    {p.get('proved_on', '')}")
    add("")

    add("-- ATTEMPTED and NOT proved (a first-class result, not an omission) " + "-" * 10)
    if not attempted:
        add("  (none)")
    for g in sorted(attempted, key=lambda x: x["id"]):
        add(f"  {g['id']}")
        add(f"      {_wrap(g['evidence'], indent=' ' * 6)}")
    for gid in unattached:
        add(f"  {gid}   [no gate matches this id in the current sweep]")
        add(f"      {_wrap(ATTEMPTED_UNPROVEN[gid], indent=' ' * 6)}")
    add("")

    if orphan_proofs:
        add("-- !! STALE PROOFS: recorded verdict no longer matches the gate at that id " + "-" * 3)
        add("   A CI-step id is positional. These verdicts are REFUSED, not re-attached.")
        for o in orphan_proofs:
            add(f"  {o['id']}")
            add(f"      recorded gate: {o['recorded_name']}")
            add(f"      gate now here: {o['current_name']}")
        add("")

    add("-- by family " + "-" * 64)
    fam: dict[str, list[dict]] = {}
    for g in gates:
        fam.setdefault(g["family"], []).append(g)
    for name in sorted(fam):
        items = fam[name]
        fs = sum(1 for g in items if g["screened"])
        add(f"  {name:<18} n = {len(items):>4}   screened {fs:>4}   unscreened {len(items) - fs:>4}")
    add("")

    add("-- risk flags (leads for adjudication, NOT defects) " + "-" * 26)
    # Every DETECTABLE shape is printed, zeros included. A shape that simply vanishes
    # from the report when it finds nothing is indistinguishable from a shape whose
    # detector died — the exact confusion this census exists to end. The zeros are only
    # meaningful because each detector has a planted-positive proof in
    # tests/test_gate_census_2578.py.
    hist: dict[str, int] = {k: 0 for k, v in census["shapes"].items() if v["detectable"] != "no"}
    for g in screened:
        for f in g["risk_flags"]:
            hist[f] = hist.get(f, 0) + 1
    for f, c in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])):
        suffix = "   (detector proven live by a planted positive; zero here is a real result)" if c == 0 else ""
        add(f"  {f:<28} n = {c}{suffix}")
    add("")

    add("-- why gates could not be screened " + "-" * 43)
    reasons: dict[str, int] = {}
    for g in unscreened:
        reasons[g["unscreened_reason"]] = reasons.get(g["unscreened_reason"], 0) + 1
    for r, c in sorted(reasons.items(), key=lambda kv: -kv[1]):
        add(f"  n = {c:<5} {r}")
    if not reasons:
        add("  (none)")
    add("")

    add("-- failure shapes this census CANNOT see " + "-" * 37)
    for name, spec in SHAPES.items():
        if spec["detectable"] == "no":
            add(f"  {name:<28} ({spec['seed']}) — needs a semantic probe, not a syntactic one")
        elif spec["detectable"] == "partial":
            add(f"  {name:<28} ({spec['seed']}) — PARTIAL: syntactic proxy only, both-way error")
    add("")

    exp = census.get("annassign_exposure") or {}
    if exp:
        add("-- AnnAssign exposure (taxonomy instance 5, measured) " + "-" * 24)
        add(f"  source files whose AST walk sees `X = ...` but not `X: T = ...`   n = {exp['n_blind_walkers']}")
        add(f"  module-level CONSTANTS currently bound with an annotation         n = {exp['n_annotated_module_constants']}")
        add("  Every constant in the second set is invisible to every walker in the first.")
        for w in exp["blind_walkers"][:15]:
            add(f"    blind walker: {w}")
        if len(exp["blind_walkers"]) > 15:
            add(f"    ... and {len(exp['blind_walkers']) - 15} more (see --json; nothing is dropped from the count)")
        add("")

    add("-- raw discovery counters (what the sweep walked) " + "-" * 28)
    for family, c in census["counters"].items():
        add(f"  {family}: " + ", ".join(f"{k}={v}" for k, v in c.items()))
    if census["families_dropped"]:
        add(f"  DROPPED FAMILIES (bounded run): {census['families_dropped']}")
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Derive the armed-gate inventory from source (#2578).")
    ap.add_argument("--json", metavar="PATH", help="write the machine-readable inventory here")
    ap.add_argument("--family", action="append", choices=FAMILIES, help="restrict the sweep (the bound is LOGGED)")
    ap.add_argument("--flag", help="print only gates carrying this risk flag")
    args = ap.parse_args(argv)

    census = build_census(families=args.family or FAMILIES)
    print(render_report(census))

    if args.flag:
        hits = [g for g in census["gates"] if args.flag in g["risk_flags"]]
        print(f"-- gates flagged '{args.flag}' (n = {len(hits)}) " + "-" * 20)
        for g in hits:
            print(f"  {g['source']:<62} {g['name']}")
    if args.json:
        Path(args.json).write_text(json.dumps(census, indent=2, sort_keys=True), encoding="utf-8")
        log(f"inventory written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
