"""tests/test_module_size_guard.py — #1665: the module-size ratchet guard (D2).

docs/ENGINEERING_STANDARDS.md §2 sets a **~800-line smell / ~1,200-line hard ceiling**
on first-party source. A file over the hard ceiling is a maintainability finding: split
it into cohesive helper modules behind the same public entrypoint (no contract change).

This guard is the ratchet that stops the tree getting *worse* while the split work lands.
It FAILS CI when a source file crosses the hard ceiling, UNLESS one of:

  * it is **grandfathered** — already over the ceiling when this guard landed, recorded in
    the ``BASELINE`` registry below (the accepted-debt set that #1653/#1654 are draining);
  * it carries a **registered top-of-file exception comment** — the sanctioned escape hatch
    from §2 for a generated file or a registry/dispatch table where splitting hurts
    legibility (see ``_EXCEPTION_RE`` for the exact form); or
  * it is a **generated file** (a ``@generated`` / ``AUTO-GENERATED`` / ``DO NOT EDIT``
    header in the first few lines).

Ratchet semantics — the tree can only get better, never worse:

  * A NEW file over the ceiling with none of the three exemptions -> FAIL. Fix by splitting
    it, or (only for a real registry/generated case) add the top-of-file exception comment.
  * An EXISTING non-baselined file that crosses the ceiling -> FAIL (same fix).
  * **Shrinking or deleting** a file is ALWAYS allowed. A ``BASELINE`` entry that no longer
    exists, was renamed, or has dropped under the ceiling does **NOT** fail this guard — the
    check is a pure subset assertion, never equality. This is deliberate: #1653 (lambdas/
    packaging) will MOVE many of these paths and #1654 will SHRINK several god-modules, and
    neither refactor may be blocked by a stale registry line. Prune the now-stale entry in
    the same PR for hygiene, but nothing forces it (so the stories can't deadlock).

Scope = git-tracked ``*.py`` under the first-party source roots (``lambdas/``, ``mcp/``,
``scripts/``, ``deploy/``, ``cdk/``) — matching what ENGINEERING_STANDARDS §2 scopes.
``tests/`` is out of scope (test files legitimately run long), as is build output
(``cdk/node_modules``, ``cdk.out/``) which git never tracks anyway.

Relationship to ``tests/test_lambda_size_gate.py``: that older guard (ADR-080) is a
narrower, higher bar — ``*_lambda.py`` handlers over 2,000 lines. This guard is the broad
~1,200 ceiling across ALL first-party source. They coexist; neither subsumes the other.
"""

import os
import re
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# The hard ceiling from docs/ENGINEERING_STANDARDS.md §2 (~800 smell / ~1,200 finding).
HARD_CEILING = 1200

# First-party source roots the ceiling applies to (§2). tests/ is deliberately excluded.
SCOPE_DIRS = ("lambdas", "mcp", "scripts", "deploy", "cdk")

# Paths that are build output, never first-party source (git doesn't track them, but the
# filter keeps the guard honest if one is ever committed by mistake).
_EXCLUDE_SUBSTR = ("node_modules/", "cdk.out/")

# A registered top-of-file exception (the §2 escape hatch). Must appear within the first
# _EXCEPTION_SCAN_LINES lines AND name a reason. This is the ONLY sanctioned way a NEW file
# is allowed over the ceiling.
_EXCEPTION_RE = re.compile(r"#\s*module-size-exception:\s*(\S.+)")
# A generated-file header — generated source is exempt (it's not hand-maintained).
_GENERATED_RE = re.compile(r"@generated|AUTO-?GENERATED|DO NOT EDIT|GENERATED FILE", re.IGNORECASE)
_EXCEPTION_SCAN_LINES = 40


# ─────────────────────────────────────────────────────────────────────────────
# THE BASELINE. Files already over the ceiling when this guard landed (#1665).
# Accepted debt that #1653 (packaging) / #1654 (god-module breakup) are draining.
# Keyed on repo-root-relative path; the note is the line count at baseline time.
#
# This registry only ever SHRINKS. Removing a line (because the file was split, shrunk,
# renamed, or deleted) is the ratchet tightening and is always welcome. ADDING a line
# means a NEW file crossed the ceiling — do not do that to silence the guard; split the
# file, or (only for a genuine generated/registry case) use the top-of-file exception
# comment instead.
# ─────────────────────────────────────────────────────────────────────────────
BASELINE = {
    "lambdas/web/site_api_data.py": "3016 lines",
    "lambdas/emails/wednesday_chronicle_lambda.py": "2975 lines",
    "cdk/stacks/role_policies.py": "2848 lines",
    "lambdas/web/site_api_observatory.py": "2826 lines",
    "lambdas/emails/daily_brief_lambda.py": "2472 lines",
    "lambdas/web/site_api_intelligence.py": "2460 lines",
    "lambdas/web/site_api_vitals.py": "2407 lines",
    "lambdas/compute/daily_insight_compute_lambda.py": "2335 lines",
    "lambdas/emails/weekly_digest_lambda.py": "2195 lines",
    "lambdas/ai_calls.py": "2164 lines",
    "lambdas/character_engine.py": "2112 lines",
    "mcp/registry.py": "2103 lines",
    "lambdas/html_builder.py": "2038 lines",
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": "1972 lines",
    "lambdas/web/site_api_coach.py": "1967 lines",
    "mcp/tools_lifestyle.py": "1953 lines",
    "lambdas/web/site_api_ai_lambda.py": "1934 lines",
    "lambdas/emails/coach_panel_podcast_lambda.py": "1888 lines",
    "deploy/archive/onetime/daily_brief_lambda.py": "1881 lines",
    "lambdas/web/site_api_social.py": "1829 lines",
    "lambdas/ingestion/health_auto_export_lambda.py": "1772 lines",
    "deploy/sync_doc_metadata.py": "1754 lines",
    "lambdas/intelligence_common.py": "1597 lines",
    "lambdas/coach/coach_prediction_evaluator.py": "1543 lines",
    "lambdas/coach/coach_history_summarizer.py": "1458 lines",
    "lambdas/compute/hypothesis_engine_lambda.py": "1396 lines",
    "lambdas/ai_context.py": "1393 lines",
    "lambdas/output_writers.py": "1367 lines",
    "cdk/stacks/monitoring_stack.py": "1298 lines",
    "lambdas/coach/coach_narrative_orchestrator.py": "1250 lines",
    "lambdas/coach/coach_state_updater.py": "1228 lines",
    "lambdas/compute/daily_metrics_compute_lambda.py": "1225 lines",
    "mcp/tools_hevy_routine.py": "1218 lines",
}

_REGISTER_HINT = (
    "To register a genuine generated file or registry/dispatch table that must exceed the "
    "ceiling, add a top-of-file comment within the first %d lines:\n"
    "    # module-size-exception: <reason>\n"
    "Otherwise split the module into cohesive helpers behind the same public entrypoint "
    "(no contract change). See docs/ENGINEERING_STANDARDS.md §2." % _EXCEPTION_SCAN_LINES
)


def _tracked_scope_py_files():
    """Git-tracked ``*.py`` under the first-party source roots (build output filtered)."""
    out = subprocess.run(
        ["git", "ls-files", "-z", *SCOPE_DIRS],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = []
    for rel in out.split("\0"):
        if not rel or not rel.endswith(".py"):
            continue
        if any(sub in rel for sub in _EXCLUDE_SUBSTR):
            continue
        files.append(rel)
    return sorted(files)


def _line_count(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8", errors="replace") as fh:
        return len(fh.read().splitlines())


def _head(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8", errors="replace") as fh:
        lines = []
        for i, line in enumerate(fh):
            if i >= _EXCEPTION_SCAN_LINES:
                break
            lines.append(line)
    return "".join(lines)


def _has_registered_exception(rel):
    head = _head(rel)
    return bool(_EXCEPTION_RE.search(head)) or bool(_GENERATED_RE.search(head))


def _offenders():
    """Files over the ceiling that are NOT exempt (baseline / exception / generated)."""
    bad = []
    for rel in _tracked_scope_py_files():
        n = _line_count(rel)
        if n <= HARD_CEILING:
            continue
        if rel in BASELINE:
            continue
        if _has_registered_exception(rel):
            continue
        bad.append((rel, n))
    return sorted(bad)


# ── A. THE RATCHET (real tree) ──────────────────────────────────────────────────────────
def test_no_new_oversize_module():
    """A new/changed first-party file over the ceiling must be split or registered (D2)."""
    offenders = _offenders()
    assert not offenders, (
        "Source file(s) over the %d-line hard ceiling with no baseline/exception (#1665):\n" % HARD_CEILING
        + "\n".join(f"  {rel}: {n} lines" for rel, n in offenders)
        + "\n\n"
        + _REGISTER_HINT
    )


def test_baseline_entries_are_documented():
    """Every BASELINE entry states its line count at baseline — a bare set rots silently."""
    missing = sorted(p for p, note in BASELINE.items() if not (note and note.strip()))
    assert not missing, "BASELINE entries need a non-empty note (line count at baseline): %s" % missing


# ── B. THE LOGIC (synthetic, guard-red) — proves the classifier actually bites ──────────
def _classify(n_lines, *, in_baseline, has_exception):
    """Pure decision function mirrored by _offenders, exercised without touching disk."""
    if n_lines <= HARD_CEILING:
        return "ok:under-ceiling"
    if in_baseline:
        return "ok:baselined"
    if has_exception:
        return "ok:exception"
    return "FAIL"


def test_new_oversize_file_fails():
    """A fresh file over the ceiling, not baselined and not exception-marked, is caught."""
    assert _classify(1300, in_baseline=False, has_exception=False) == "FAIL"


def test_under_ceiling_file_passes():
    """A file at/under the ceiling is fine regardless of baseline/exception state."""
    assert _classify(1200, in_baseline=False, has_exception=False) == "ok:under-ceiling"


def test_exception_comment_exempts():
    """A registered top-of-file exception comment lets a file exceed the ceiling."""
    assert _classify(5000, in_baseline=False, has_exception=True) == "ok:exception"


def test_baselined_file_passes():
    """A grandfathered file over the ceiling passes (accepted debt, drained by #1653/#1654)."""
    assert _classify(3016, in_baseline=True, has_exception=False) == "ok:baselined"


def test_exception_regex_needs_a_reason():
    """`# module-size-exception:` with no reason does NOT count — the reason is required."""
    assert _EXCEPTION_RE.search("# module-size-exception: generated by v4_build_x.py")
    assert not _EXCEPTION_RE.search("# module-size-exception:")
    assert not _EXCEPTION_RE.search("# module-size-exception:    ")


def test_generated_header_exempts():
    """A generated-file header is recognized as an exemption without a manual comment."""
    for marker in ("# @generated by tool", "# AUTO-GENERATED — do not edit", "# GENERATED FILE"):
        assert _GENERATED_RE.search(marker)
