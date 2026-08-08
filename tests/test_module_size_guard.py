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
  * A BASELINED file that grows **past its own recorded count** -> FAIL (see below).
  * **Shrinking or deleting** a file is ALWAYS allowed. A ``BASELINE`` entry that no longer
    exists or was renamed does **NOT** fail this guard — the check stays a subset assertion
    on existence. This is deliberate: #1653 (lambdas/ packaging) MOVED many of these paths
    and #1654 SHRINKS god-modules, and neither refactor may be blocked by a stale line.
    The one thing that IS forced is pruning an entry once the file drops back under the
    ceiling — a one-line deletion, never a deadlock, and leaving it in would licence the
    file to regrow to its old size unpoliced.

THE PER-FILE RATCHET (2026-08-09) — why the recorded number is now an ``int``:

Every ``BASELINE`` value used to be a prose note (``"3016 lines"``) and ``_offenders()``
read ``if rel in BASELINE: continue``. Nothing anywhere compared a file against its own
recorded count, so a baselined file's growth was **completely unpoliced** — the registry
documented itself as shrink-only while 24 of its 28 entries had grown, several by 10-48%:

    lambdas/web/site_api_social.py        1829 -> 2708   (+879, +48%)
    cdk/stacks/role_policies.py           2848 -> 3211   (+363, +13%)
    cdk/stacks/monitoring_stack.py        1298 -> 1623   (+325, +25%)
    mcp/registry.py                       2103 -> 2409   (+306, +15%)
    lambdas/coach/coach_history_summarizer.py 1458 -> 1731 (+273, +19%)
    lambdas/emails/daily_brief_lambda.py  2472 -> 2737   (+265, +11%)
    …19 more, total drift +3,565 lines across 24 files

That is the same class as #2259's coverage gate: a number recorded in the repo that no
gate ever read. Making it enforcing turns 28 dead entries into 28 live per-file ratchets
and gives #1654 a mechanism instead of an aspiration.

The counts below were **re-baselined at measured on 2026-08-09** rather than held at the
2026-06 numbers — holding them would have demanded 24 module splits in one sitting. The
drift is recorded above and in the landing commit so the debt is visible, not reset in
silence. From here a baselined file may only shrink.

A file shrinking below its recorded count does not auto-tighten the entry (that would make
every line-removal PR edit this registry). Tightening a number after a real shrink is
welcome and always allowed — it is the ratchet doing its job.

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
# Keyed on repo-root-relative path; the value is the file's MAXIMUM ALLOWED line
# count — an int, and enforced (see test_baselined_files_do_not_grow).
#
# It is an int rather than a prose note deliberately. As a note ("3016 lines") nothing
# compared it against anything, and 24 of these 28 files grew a combined 3,565 lines
# with the guard reporting green the whole time. A number a gate cannot read is not a
# record, it is decoration.
#
# This registry only ever SHRINKS — both in membership and in the numbers. Lowering a
# value after a real split is the ratchet tightening and is always welcome. RAISING one
# is admitting the module grew: allowed only with a reason in the commit message, and
# never as the reflex fix for a red gate. ADDING a line means a NEW file crossed the
# ceiling — split it, or (for a genuine generated/registry case) use the top-of-file
# exception comment instead.
#
# Counts re-baselined at measured 2026-08-09 (the `now` column of the drift table in
# this module's docstring).
# ─────────────────────────────────────────────────────────────────────────────
BASELINE = {
    # site_api_data.py (baselined 3016) drained to 362 lines — pruned 2026-08-09. Leaving a
    # stale entry in would have licensed it to regrow 8x unpoliced, which is exactly the
    # hole this ratchet closes; test_baseline_has_no_stale_entries now forces the prune.
    # wednesday_chronicle_lambda.py (2975) split into chronicle_* helpers + a <1,200-line facade (#1654) — pruned.
    "cdk/stacks/role_policies.py": 3211,
    # site_api_observatory.py drained to a ~150-line facade by #1654 slice 3 — the handler
    # logic now lives in cohesive web/site_api_{nutrition,meals,training,physical,mind}.py
    # (each well under the ceiling). The pure-subset ratchet allows removing a shrunk entry.
    "lambdas/emails/daily_brief_lambda.py": 2737,
    "lambdas/web/site_api_social.py": 2708,
    # site_api_intelligence.py (2831 by the time the slice ran) drained to a ~180-line
    # facade by #1654's 4th and last named target — the handler logic now lives in
    # cohesive web/site_api_{status,pulse,discovery,foresight,budget}.py, each well
    # under the ceiling. The pure-subset ratchet allows removing a shrunk entry.
    # site_api_vitals.py (2559 by the time the slice ran) drained to a ~220-line facade
    # by #1654 — the handler logic now lives in cohesive
    # web/site_api_{body,journey,character,sleep,biomarkers}.py, each under the ceiling.
    "lambdas/compute/daily_insight_compute_lambda.py": 2352,
    "mcp/registry.py": 2409,
    "lambdas/ai/ai_calls.py": 2396,
    "lambdas/emails/weekly_digest_lambda.py": 2216,
    "lambdas/health/character_engine.py": 2117,
    "lambdas/content/html_builder.py": 2104,
    "lambdas/web/site_api_ai_lambda.py": 1991,
    "mcp/tools_lifestyle.py": 1989,
    "lambdas/emails/coach_panel_podcast_lambda.py": 1904,
    # site_api_coach.py (2664 by the time the slice ran) drained to a ~440-line facade by
    # #1654 — the handler logic now lives in cohesive web/site_api_coach_{profile,stance,
    # ledger,narrative}.py + web/site_api_thirdwall.py, each well under the ceiling. The
    # pure-subset ratchet allows removing a shrunk entry.
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": 1886,
    "deploy/archive/onetime/daily_brief_lambda.py": 1881,
    "lambdas/ingestion/health_auto_export_lambda.py": 1779,
    "deploy/sync_doc_metadata.py": 1807,
    "lambdas/intelligence/intelligence_common.py": 1741,
    "lambdas/coach/coach_history_summarizer.py": 1731,
    "lambdas/coach/coach_prediction_evaluator.py": 1638,
    "cdk/stacks/monitoring_stack.py": 1623,
    "lambdas/compute/hypothesis_engine_lambda.py": 1556,
    "lambdas/ai/ai_context.py": 1415,
    "lambdas/content/output_writers.py": 1387,
    # 1369 -> 1370 by #2299: one `from intelligence.weight_recency import week_ago_weight`
    # import. That module exists because the compute Lambda and the daily brief had two
    # different definitions of "last week's weight" and the compute one was wrong (it took
    # the OLDEST reading in a 14-day window). The single line buys one shared definition —
    # the ratchet's first real bump, and the shape it is meant to allow.
    "lambdas/compute/daily_metrics_compute_lambda.py": 1370,
    "lambdas/coach/coach_narrative_orchestrator.py": 1315,
    "lambdas/coach/coach_state_updater.py": 1268,
    "mcp/tools_hevy_routine.py": 1218,
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
    """Every BASELINE value must be a positive int — the number the ratchet compares against.

    This used to accept any non-empty string, which is how ``"3016 lines"`` sat in the
    registry for months as decoration. A prose note cannot be enforced; an int can.
    """
    bad = sorted(p for p, cap in BASELINE.items() if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0)
    assert not bad, "BASELINE values must be a positive int (the maximum allowed line count), not a note. " "Offending entries: %s" % bad


def _grown():
    """Baselined files that now exceed their own recorded count."""
    over = []
    for rel, cap in BASELINE.items():
        path = os.path.join(_REPO, rel)
        if not os.path.isfile(path):
            continue  # moved/deleted — the subset semantics above; never a failure
        n = _line_count(rel)
        if n > cap:
            over.append((rel, cap, n))
    return sorted(over, key=lambda t: t[1] - t[2])


def test_baselined_files_do_not_grow():
    """A baselined file may shrink freely and may not grow past its recorded count.

    This is the whole point of the registry and it was unenforced until 2026-08-09: the
    old code read ``if rel in BASELINE: continue``, so membership alone was a permanent
    exemption from any ceiling at all. 24 of 28 entries had drifted up a combined 3,565
    lines while this file reported green.
    """
    over = _grown()
    assert not over, (
        "Baselined file(s) grew past their recorded ceiling (#1665, enforcing since 2026-08-09):\n"
        + "\n".join(f"  {rel}: {n} lines, baseline {cap} (+{n - cap})" for rel, cap, n in over)
        + "\n\nThese are accepted DEBT, not a licence to grow. Put the new code in a cohesive "
        "helper module beside it (that is #1654's whole shape), or — if the growth is genuinely "
        "unavoidable — raise this file's number and say why in the commit message. Do not raise "
        "it reflexively to clear a red gate."
    )


def test_baseline_has_no_stale_entries():
    """A baselined file that dropped back under the ceiling must be pruned.

    Not hygiene — enforcement. site_api_data.py was baselined at 3016 and is now 362 lines;
    while the entry stood, it could have regrown to 3016 with every gate green. Pruning is a
    one-line deletion, so this can never deadlock a refactor the way an equality check would.
    """
    stale = sorted(
        (rel, _line_count(rel)) for rel in BASELINE if os.path.isfile(os.path.join(_REPO, rel)) and _line_count(rel) <= HARD_CEILING
    )
    assert not stale, (
        "BASELINE entr(ies) for file(s) now at/under the %d-line ceiling — delete the line(s), "
        "the ratchet has tightened:\n" % HARD_CEILING + "\n".join(f"  {rel}: {n} lines" for rel, n in stale)
    )


# ── B. THE LOGIC (synthetic, guard-red) — proves the classifier actually bites ──────────
def _classify(n_lines, *, in_baseline, has_exception, baseline_cap=None):
    """Pure decision function mirrored by _offenders + _grown, exercised without disk.

    ``baseline_cap`` is the file's recorded maximum. Passing ``in_baseline=True`` without
    a cap reproduces the pre-2026-08-09 behaviour (membership = blanket exemption) and is
    only used by the regression test that pins the old hole shut.
    """
    if n_lines <= HARD_CEILING:
        return "ok:under-ceiling"
    if in_baseline:
        if baseline_cap is not None and n_lines > baseline_cap:
            return "FAIL:grew-past-baseline"
        return "ok:baselined"
    if has_exception:
        return "ok:exception"
    return "FAIL"


def test_baselined_file_that_grew_fails():
    """The hole this ratchet closes: site_api_social.py's real 1829 -> 2708 drift."""
    assert _classify(2708, in_baseline=True, has_exception=False, baseline_cap=1829) == "FAIL:grew-past-baseline"


def test_baselined_file_that_shrank_passes():
    """Shrinking is always allowed and never forces a registry edit."""
    assert _classify(1500, in_baseline=True, has_exception=False, baseline_cap=1829) == "ok:baselined"


def test_baselined_file_exactly_at_its_cap_passes():
    """The comparison is strictly-greater — a file sitting on its number is not a red."""
    assert _classify(1829, in_baseline=True, has_exception=False, baseline_cap=1829) == "ok:baselined"


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
