"""scripts/gate_census_mutations.py — the mechanised can-it-fail verdicts for census
family 5, the tree-sweeping structural pytest gates (#2999, epic #2578 slice 2).

WHY ITS OWN MODULE
──────────────────
`scripts/gate_census.py` sits at 1,164 lines against the 1,200-line hard ceiling
(`tests/test_module_size_guard.py`, #1665) and was never baselined — #2610's policy is
extraction, never a new BASELINE entry. A batch of verdicts does not fit. Same one-way
split shape as `gate_census_proofs.py` / `gate_census_structural.py`: this module has
ZERO dependency on `gate_census`, so there is no import cycle even when `gate_census.py`
runs directly as `__main__`. It exports plain dicts and `gate_census` builds its own
`Proof` from them.

WHY A HARNESS AND NOT PROSE
───────────────────────────
#2999's problem statement: "verdicts at 490-scale cannot be hand-driven ... where the
mutation can be generated and run automatically, the verdict is a build product, not a
session's attention." The other two verdict batches in this census (`PROVEN_CAN_FAIL`,
`SENTINEL_PROOFS`) are hand-written records of a mutation a human performed once. They
are honest, and they do not re-run — a gate that goes dark six months from now keeps its
`can-fail (proven)` stamp, which is precisely the "a stamp is a human claim" failure
(#973/#2619). Family 5 is the family where that can be fixed, because every gate in it
is a pytest file that sweeps the tracked tree, so its defect is a FILE you can write.

So each verdict here is a `MutationSpec` — the plant, the target, and the expected
direction — and `run_spec()` executes the whole control, in this order:

    1. BASELINE   run the target on the clean tree      -> must be GREEN
    2. MUTATED    plant the defect (git-add if the gate  -> must be RED
                  reads the tracked set), run again
    3. REVERTED   remove the plant, run again           -> must be GREEN again

A gate is ARMED only when all three hold. Step 1 is what stops a already-red target from
counting as a proof; step 3 is what stops a leaked plant from poisoning the next spec.
A RED in step 2 with no GREEN on either side proves nothing, and the runner says so
rather than reporting a verdict.

    python3 scripts/gate_census_mutations.py --run              # every spec
    python3 scripts/gate_census_mutations.py --run --gate test_xfail_hygiene.py
    python3 scripts/gate_census_mutations.py --list

WHAT A DARK RESULT IS, AND IS NOT
─────────────────────────────────
A spec that does not go red is a LEAD, not a `cannot-fail` verdict. The overwhelmingly
likely cause is that the plant missed the predicate (wrong directory, wrong suffix, the
gate reads the git index and the plant was not added). Only after the plant is confirmed
to sit inside the gate's declared scope is "the gate could not fail" the finding — and
then it gets an issue, per #2999's third acceptance box. Nothing here is allowed to
report a verdict it did not watch.

THE PLANT LITERALS ARE ASSEMBLED, ON PURPOSE
────────────────────────────────────────────
Several of the gates below sweep EVERY tracked file, including this one. Writing their
banned literal into this module verbatim would red them permanently — the harness would
become the defect it exists to plant. Those bodies are assembled from fragments by
`_lit()`, with the reason on each call site. This is not obfuscation for its own sake:
an un-assembled literal here is a self-inflicted repo-wide failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _lit(*parts: str) -> str:
    """Join fragments into a literal that must not appear verbatim in this file.

    See the module docstring: these are the banned strings the planted gates sweep the
    whole tracked tree for, this file included.
    """
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# The specs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MutationSpec:
    """One generated mutation. `plants` + `target` must be enough to re-run it."""

    gate_id: str  # the census id this proves, e.g. "structural::test_xfail_hygiene.py"
    target: str  # the pytest target, repo-relative
    detects: str  # one line: the defect class the plant introduces
    plants: tuple[tuple[str, str], ...]  # (repo-relative path, content)
    track: bool = True  # git-add the plants (the gate reads the tracked set)
    extra_args: tuple[str, ...] = field(default_factory=tuple)


_CONFLICT_BLOCK = "\n".join(
    [
        "# probe",
        # Assembled: tests/test_no_conflict_markers.py sweeps every tracked file for
        # exactly these three prefixes, and this module is a tracked file.
        _lit("<" * 7, " HEAD"),
        "left side",
        _lit("=" * 7),
        "right side",
        _lit(">" * 7, " branch"),
        "",
    ]
)

# Assembled: tests/test_no_private_markers_3043.py sweeps every tracked text file for a
# doc-status header declaring the file itself private, and only allowlists its own source.
_PRIVATE_MARKER_DOC = "# probe\n\n> **Status:** " + _lit("PRIV", "ATE") + " / internal. Do not surface.\n"

# Assembled: tests/test_no_tool_attribution_3005.py bans any MENTION of any of the three
# banned attribution forms (co-author trailer, session-link line, generated-with footer —
# #3328) on any tracked file outside CLAUDE.md and the guard itself. This plant is form 1.
_ATTRIBUTION_DOC = "# probe\n\n" + _lit("Co-Author", "ed-By") + ": Claude Opus 5 <noreply@anthropic.com>\n"

# Assembled: tests/test_timezone_discipline.py scans scripts/ as well as lambdas/, so the
# banned fixed-offset idiom cannot appear verbatim in this file. This one is not
# hypothetical — the first draft of this module wrote the idiom whole into a single
# fragment, and the harness's own BASELINE step caught it (`baseline is already RED`)
# before a single verdict was recorded. That is the control doing its job on its author.
_FIXED_OFFSET_PY = (
    '"""probe."""\n\n'
    "from datetime import timedelta, timezone\n"
    "from datetime import datetime\n\n\n"
    "def probe():\n"
    "    return datetime."
    + _lit(
        "now(timezone.utc) - timedelta(",
        "hours=8)",
    )
    + "\n"
)

_PACIFIC_FORK_PY = (
    '"""probe."""\n\n'
    "from datetime import datetime\n"
    "from zoneinfo import ZoneInfo\n\n\n"
    "def probe():\n"
    '    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()\n'
)

_PII_LOG_PY = (
    '"""probe."""\n\n'
    "import logging\n\n"
    "logger = logging.getLogger(__name__)\n\n\n"
    "def probe(email):\n"
    '    logger.info(f"sending to {email}")\n'
)

_UNTYPED_HANDLERS_PY = '"""probe."""\n\n' + "\n\n".join("def lambda_handler(event, context):\n    return {}" for _ in range(24))

_XFAIL_PY = '"""probe."""\n\n' "import pytest\n\n\n" "@pytest.mark.xfail\n" "def test_probe():\n" "    assert False\n"

# These carry a secret NAME, never a secret value (Secrets-Manager-only, per CLAUDE.md).
# The identifiers deliberately say `ID` rather than `SECRET`: ruff's flake8-bandit S105
# rules on the TARGET NAME, and `_..._SECRET_PY = "<string>"` reads to it as a hardcoded
# credential. Renaming keeps the gate honest instead of noqa-ing it.
#
# #3255 (2026-08-27) PROMOTED the masked form from DARK_CONTROLS to the armed spec.
# Until then, `test_secret_references.FALSE_POSITIVE_PATTERNS` dropped any LINE
# containing `SECRET_NAME`, so `_MASKED_ID_PY` — the exact wrong-default shape the
# guard's own docstring cites as its reason to exist — left the gate GREEN, and the
# armed spec had to use `_UNKNOWN_ID_PY`, a bare literal that dodges the mask. The gate
# now extracts string CONSTANTS from the AST, where identifiers are unrepresentable, so
# the hard shape is the one worth planting and `_UNKNOWN_ID_PY` is the easy subset of it.
_UNKNOWN_ID_PY = '"""probe."""\n\n' '_PROBE_ID = "life-platform/probe-2999-not-a-real-secret"\n'

_MASKED_ID_PY = (
    '"""probe — the documented root-cause shape (#3255): a wrong secret default."""\n\n'
    "import os\n\n"
    'SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/probe-2999-not-a-real-secret")\n'
)

# The successor blind spot, measured 2026-08-27 after #3255 landed: the SAME unknown id,
# assembled from two constants instead of written as one. Neither half full-matches a
# secret name, so no `ast.Constant` in the module is a reference and the gate stays green.
# In scope by every reading — it is a shipping Lambda module naming a secret that does not
# exist — and dark, which is what makes it a control rather than a broken plant.
_SPLIT_ID_PY = (
    '"""probe — an unknown secret id assembled from parts rather than written whole."""\n\n'
    '_PREFIX = "life-platform/"\n'
    '_PROBE_ID = _PREFIX + "probe-2999-not-a-real-secret"\n'
)

_DEAD_SYMBOL_PY = '"""probe."""\n\n\n' "def probe(client):\n" "    return client.write_action()\n"

_DEAD_ID_DOCSTRING_PY = '"""probe.\n\nSecret: life-platform/probe-2999-nope (Secrets Manager)\n"""\n'

_ORPHAN_PAGE_HTML = "<!doctype html>\n<html><head><title>probe</title></head><body><p>probe</p></body></html>\n"

_HARDCODED_TIER_PY = (
    '"""probe."""\n\n'
    "from ai.budget_guard import current_tier\n\n\n"
    "def probe():\n"
    "    if current_tier() >= 2:\n"
    "        return None\n"
    "    return 1\n"
)

_OVERSIZE_LAMBDA_PY = '"""probe."""\n\n' + "".join(f"X{i} = {i}\n" for i in range(2400))

# Assembled: tests/test_absence_coverage_3294.py sweeps lambdas/ + mcp/ for any module
# whose AST reads the raw `channels_quiet` field — the presence signal's unlicensed
# category-level absence list — and refuses a reader with no disposition. The literal is
# split so a sweep of scripts/ can never mistake this spec for a consumer.
_RAW_QUIET_READER_PY = '"""probe."""\n\n\ndef probe(sig):\n    return sig.get(' + _lit('"channels_qu', 'iet"') + ")\n"

# Assembled: tests/test_direction_of_travel_ruling_3293.py sweeps lambdas/ + scripts/ +
# mcp/ for every module that reaches for the shared direction-of-travel ruling and is not
# named in its surface registry. `scripts/` is inside that sweep, so writing the module
# name verbatim here would make this harness a permanently-unregistered importer — the
# file would plant its own defect and never be able to revert it.
_UNREGISTERED_DIRECTION_SURFACE_PY = (
    '"""probe."""\n\n'
    "from web." + _lit("journey_", "direction") + " import classify_delta\n\n\n"
    "def probe(lost_lbs):\n"
    "    return classify_delta(lost_lbs)\n"
)

MUTATION_SPECS: dict[str, MutationSpec] = {
    "structural::test_no_conflict_markers.py": MutationSpec(
        gate_id="structural::test_no_conflict_markers.py",
        target="tests/test_no_conflict_markers.py",
        detects="an unresolved merge whose markers reached a tracked file (the #2200 incident)",
        plants=(("docs/_census_probe_2999.md", _CONFLICT_BLOCK),),
    ),
    "structural::test_root_clutter_guard.py": MutationSpec(
        gate_id="structural::test_root_clutter_guard.py",
        target="tests/test_root_clutter_guard.py",
        detects="a new, unlisted first-party top-level directory entering the git index (#1652 D1 ratchet)",
        plants=(("_census_probe_2999_dir/probe.txt", "probe\n"),),
    ),
    "structural::test_no_private_markers_3043.py": MutationSpec(
        gate_id="structural::test_no_private_markers_3043.py",
        target="tests/test_no_private_markers_3043.py",
        detects="a tracked file in a public repo declaring itself private (DIL-001)",
        plants=(("docs/_census_probe_2999.md", _PRIVATE_MARKER_DOC),),
    ),
    "structural::test_no_tool_attribution_3005.py": MutationSpec(
        gate_id="structural::test_no_tool_attribution_3005.py",
        target="tests/test_no_tool_attribution_3005.py",
        detects="a tracked instruction surface re-teaching the banned attribution trailer",
        plants=(("docs/_census_probe_2999.md", _ATTRIBUTION_DOC),),
    ),
    "structural::test_timezone_discipline.py": MutationSpec(
        gate_id="structural::test_timezone_discipline.py",
        target="tests/test_timezone_discipline.py",
        detects="fixed-offset Pacific math (PST pinned year-round — the 2026-06-12 DST bug class)",
        plants=(("lambdas/common/_census_probe_2999.py", _FIXED_OFFSET_PY),),
        track=False,
    ),
    "structural::test_time_invariant_helpers_1964.py": MutationSpec(
        gate_id="structural::test_time_invariant_helpers_1964.py",
        target="tests/test_time_invariant_helpers_1964.py",
        detects="a Pacific frame derived outside the canonical helper (#1964)",
        plants=(("lambdas/common/_census_probe_2999.py", _PACIFIC_FORK_PY),),
        track=False,
    ),
    "structural::test_pii_log_guard_2369.py": MutationSpec(
        gate_id="structural::test_pii_log_guard_2369.py",
        target="tests/test_pii_log_guard_2369.py",
        detects="a logging call interpolating a raw email address (#2369)",
        plants=(("lambdas/common/_census_probe_2999.py", _PII_LOG_PY),),
        track=False,
    ),
    "structural::test_handler_type_hints.py": MutationSpec(
        gate_id="structural::test_handler_type_hints.py",
        target="tests/test_handler_type_hints.py",
        detects="new untyped lambda_handler entry points pushing the count past its ratchet",
        plants=(("lambdas/common/_census_probe_2999.py", _UNTYPED_HANDLERS_PY),),
        track=False,
    ),
    "structural::test_xfail_hygiene.py": MutationSpec(
        gate_id="structural::test_xfail_hygiene.py",
        target="tests/test_xfail_hygiene.py",
        detects="a bare @pytest.mark.xfail that would silently absorb a real regression (#2375)",
        plants=(("tests/_census_probe_2999.py", _XFAIL_PY),),
        track=False,
    ),
    "structural::test_secret_references.py": MutationSpec(
        gate_id="structural::test_secret_references.py",
        target="tests/test_secret_references.py",
        detects=(
            "a Lambda naming a secret that exists in neither KNOWN_SECRETS nor DELETED_SECRETS (R13-F04), "
            'written in the canonical `SECRET_NAME = os.environ.get("SECRET_NAME", ...)` default form — '
            "the March-2026 wrong-default shape the guard's own docstring cites, promoted from DARK_CONTROLS "
            "by #3255"
        ),
        plants=(("lambdas/common/_census_probe_2999.py", _MASKED_ID_PY),),
        track=False,
    ),
    "structural::test_no_hardcoded_feature_tier.py": MutationSpec(
        gate_id="structural::test_no_hardcoded_feature_tier.py",
        target="tests/test_no_hardcoded_feature_tier.py",
        detects="a feature gated on a hardcoded numeric budget tier instead of budget_guard.allow (#1255)",
        plants=(("lambdas/common/_census_probe_2999.py", _HARDCODED_TIER_PY),),
        track=False,
    ),
    "structural::test_lambda_size_gate.py": MutationSpec(
        gate_id="structural::test_lambda_size_gate.py",
        target="tests/test_lambda_size_gate.py",
        detects="a new *_lambda.py god module over the 2000-line ceiling with no grandfather entry",
        plants=(("lambdas/common/_census_probe_2999_lambda.py", _OVERSIZE_LAMBDA_PY),),
        track=False,
    ),
    "structural::test_no_dead_intelligence_functions.py": MutationSpec(
        gate_id="structural::test_no_dead_intelligence_functions.py",
        target="tests/test_no_dead_intelligence_functions.py",
        detects="a shipping module calling one of the deleted intelligence symbols (#1123 dead-reference guard)",
        plants=(("lambdas/common/_census_probe_2999.py", _DEAD_SYMBOL_PY),),
        track=False,
    ),
    "structural::test_docstring_secret_ids_2653.py": MutationSpec(
        gate_id="structural::test_docstring_secret_ids_2653.py",
        target="tests/test_docstring_secret_ids_2653.py",
        detects="a Lambda docstring presenting a Secrets Manager id no CDK role policy grants (#2653)",
        plants=(("lambdas/common/_census_probe_2999.py", _DEAD_ID_DOCSTRING_PY),),
        track=False,
    ),
    "structural::test_site_orphans.py": MutationSpec(
        gate_id="structural::test_site_orphans.py",
        target="tests/test_site_orphans.py",
        detects="a site/ page reachable by URL but linked from nowhere and not declared unlisted",
        plants=(("site/_census_probe_2999/index.html", _ORPHAN_PAGE_HTML),),
        track=False,
    ),
    "structural::test_absence_coverage_3294.py": MutationSpec(
        gate_id="structural::test_absence_coverage_3294.py",
        target="tests/test_absence_coverage_3294.py",
        detects="a NEW consumer of the raw channels_quiet list with no disposition — the unwired-surface class that published two false absences (#3294)",
        plants=(("lambdas/common/_census_probe_2999.py", _RAW_QUIET_READER_PY),),
        track=False,
    ),
    "structural::test_direction_of_travel_ruling_3293.py": MutationSpec(
        gate_id="structural::test_direction_of_travel_ruling_3293.py",
        target="tests/test_direction_of_travel_ruling_3293.py",
        detects=(
            "a NEW surface reaching for the direction-of-travel ruling without joining the registry that "
            "watches it — the shape that left three of the family unfixed after #3285 (#3293)"
        ),
        plants=(("lambdas/web/_census_probe_2999.py", _UNREGISTERED_DIRECTION_SURFACE_PY),),
        track=False,
    ),
}


# The negative controls: plants that DO sit in a gate's declared scope and still leave it
# green. Each one is a measured blind spot, not a spare spec — `run_spec` is expected to
# return DARK, and `tests/test_gate_census_mutations_2999.py` fails if one starts passing
# (a silently-widened gate is as much a change of meaning as a silently-narrowed one).
DARK_CONTROLS: dict[str, MutationSpec] = {
    "structural::test_secret_references.py::assembled-id": MutationSpec(
        gate_id="structural::test_secret_references.py",
        target="tests/test_secret_references.py",
        detects=(
            "the SAME unknown secret name as the armed spec, assembled at runtime from two constants "
            '(`_PREFIX + "probe-..."`) instead of written as one literal. The scanner reads string '
            "CONSTANTS out of the AST, and neither half is a whole secret name, so a Lambda that builds "
            "its secret id by concatenation or f-string interpolation is audited by nothing. Measured "
            "2026-08-27, and it is the SUCCESSOR to the masked-line blind spot #3255 closed — that one is "
            "now the armed spec above."
        ),
        plants=(("lambdas/common/_census_probe_2999.py", _SPLIT_ID_PY),),
        track=False,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# The recorded verdicts, in `gate_census.Proof`'s shape (gate_census constructs the
# frozen dataclass from these dicts — same import contract as SENTINEL_PROOFS).
#
# Every `observed` below is the harness's own transcript from the run of 2026-08-27,
# copied verbatim, not paraphrased. Re-derive the whole batch with:
#     python3 scripts/gate_census_mutations.py --run
# ─────────────────────────────────────────────────────────────────────────────

_PROVED_ON = "2026-08-27"


def _command(target: str) -> str:
    return f"python3 scripts/gate_census_mutations.py --run --gate {Path(target).name}"


def _proof(gate_id: str, observed: str, scope: str, proved_on: str = _PROVED_ON) -> dict[str, Any]:
    # `proved_on` is per record: a gate re-measured after the batch (because its
    # predicates changed) carries the date it was actually watched, not the batch's.
    spec = MUTATION_SPECS[gate_id]
    return {
        "gate_name": Path(spec.target).name,
        "command": _command(spec.target),
        "mutation": spec.detects
        + f" — planted as {', '.join(rel for rel, _ in spec.plants)}"
        + (", git-added (the gate reads the tracked set)" if spec.track else ", untracked (the gate walks the filesystem)"),
        "observed": observed,
        "scope": scope,
        "proved_on": proved_on,
    }


STRUCTURAL_PROOFS: dict[str, dict[str, Any]] = {
    "structural::test_no_conflict_markers.py": _proof(
        "structural::test_no_conflict_markers.py",
        "baseline: 6 passed | mutated: 1 failed, 5 passed :: test_no_unresolved_conflict_markers_in_tracked_files | reverted: 6 passed",
        "Tracked files ONLY, and 26 binary suffixes are skipped. `=======` counts solely on a line of "
        "its own and the other two markers require a trailing space, so a hand-mangled marker "
        "(`<<<<<<<HEAD`, no space) is invisible. An unresolved conflict in the WORKING TREE is out of "
        "scope by design — this guard exists to stop one reaching main, not to police a local rebase.",
    ),
    "structural::test_root_clutter_guard.py": _proof(
        "structural::test_root_clutter_guard.py",
        "baseline: 4 passed | mutated: 1 failed, 3 passed :: test_no_unlisted_top_level_dir | reverted: 4 passed",
        "Directories only, and only via a tracked file inside one — a new tracked FILE at the repo root "
        "is not covered by this gate at all. Subset semantics, deliberately (#1652): deleting a "
        "top-level dir never reds it, so a stale ALLOWLIST entry is a hygiene item, not a failure.",
    ),
    "structural::test_no_private_markers_3043.py": _proof(
        "structural::test_no_private_markers_3043.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_tracked_file_carries_private_marker | reverted: 3 passed",
        "Two header FORMS only (`**Status:**`/`**Privacy tier:**` bolded, or the same two unbolded at "
        "line start) and `PRIVATE` is case-sensitive. A file that IS owner-private but does not say so "
        "in that exact header shape is not detected — this gate catches the self-declaration, never the "
        "sensitivity. Tracked text suffixes only.",
    ),
    "structural::test_no_tool_attribution_3005.py": _proof(
        "structural::test_no_tool_attribution_3005.py",
        "baseline: 8 passed, 1 skipped | mutated: 1 failed, 7 passed, 1 skipped :: test_no_tracked_file_instructs_the_trailer | reverted: 8 passed, 1 skipped",
        "ALL THREE of the owner decision's banned forms since #3328 (it shipped matching one, recorded "
        "here as a scope gap on 2026-08-27): the co-author trailer, the session-link line, AND the "
        "generated-with PR footer / session link. `_MENTION` sweeps the tracked surface for any mention "
        "of the three; `_TRAILER` sweeps reachable history since the ban date for the actual forms — "
        "including the footer, because a bare `gh pr merge --squash` can copy a PR body into the squash "
        "commit; and a PR-body sweep reads `pull_request.body` from $GITHUB_EVENT_PATH on `pull_request` "
        "runs (both pr-checks.yml jobs) and SKIPS with a stated reason everywhere else, never a silent "
        "pass. One independent predicate proof per form lives in the gate itself; this census plant "
        "exercises form 1 on the tracked surface. Residual limits: a PR body EDITED after its last push "
        "is not re-read until the next push (`edited` is not a default pull_request activity), and the "
        "session link is pinned to `/code/session` so `claude.ai/code/artifact/…` contact-sheet links "
        "under config/portraits/ stay legal.",
        proved_on="2026-08-30",
    ),
    "structural::test_timezone_discipline.py": _proof(
        "structural::test_timezone_discipline.py",
        "baseline: 1 passed | mutated: 1 failed :: test_no_fixed_offset_or_naive_mixed_pacific_math | reverted: 1 passed",
        "Two regexes, and only for offsets of 7 or 8 hours — the DST-pinning constants. It is a "
        "line-level grep, so any line containing `tzinfo` or `.date()` is exempted wholesale by "
        "LINE_EXEMPT_SUBSTRINGS, and a fixed offset assembled over two lines is invisible. Scans "
        "lambdas/ mcp/ deploy/ scripts/ remediation/ — cdk/ and tests/ are not swept.",
    ),
    "structural::test_time_invariant_helpers_1964.py": _proof(
        "structural::test_time_invariant_helpers_1964.py",
        "baseline: 19 passed | mutated: 1 failed, 18 passed :: test_no_pacific_frame_derived_outside_the_canonical_helper | reverted: 19 passed",
        "SCAN_ROOTS is lambdas/ + mcp/ (what ships in a bundle) — a Pacific fork in deploy/, scripts/ or "
        "cdk/ is out of scope. A RESIDUE allowlist of already-known sites is carried and is checked for "
        "rot by a sibling test, so the ratchet tightens rather than absorbing.",
    ),
    "structural::test_pii_log_guard_2369.py": _proof(
        "structural::test_pii_log_guard_2369.py",
        "baseline: 8 passed | mutated: 1 failed, 7 passed :: test_no_raw_pii_in_logging_calls | reverted: 8 passed",
        "Detection is by IDENTIFIER NAME at the log call site (an interpolated `email`/`dob`/`phone`), "
        "so the same value carried in a differently-named variable logs clean. lambdas/ + mcp/ only.",
    ),
    "structural::test_handler_type_hints.py": _proof(
        "structural::test_handler_type_hints.py",
        "baseline: 2 passed | mutated: 1 failed, 1 passed :: test_untyped_handler_count_at_or_below_baseline | reverted: 2 passed",
        "A COUNT ratchet with TOLERANCE=2, not a per-file rule — it can only fail when the total crosses "
        "BASELINE_UNTYPED + TOLERANCE, so new untyped handlers are absorbed silently until it does. "
        "MEASURED 2026-08-27: 68 untyped against a baseline of 66 + tolerance 2, i.e. headroom exactly "
        "ZERO. That is why the plant reds today and why it would NOT have redded at any point while the "
        "tolerance was unspent — the same absorption the file's own 2026-07-08 comment records happening "
        "once already. The green here means 'the count has not grown', never 'handlers are typed'.",
    ),
    "structural::test_xfail_hygiene.py": _proof(
        "structural::test_xfail_hygiene.py",
        "baseline: 1 passed | mutated: 1 failed :: test_every_xfail_marker_is_strict_or_names_its_nondeterminism | reverted: 1 passed",
        "tests/ only, and it rules on the MARKER's shape (bare / no literal `strict=` / `strict=False` "
        "without the nondeterminism tag). It never asks whether a `strict=True` xfail is still failing "
        "for the reason it claims — that is pytest's job, not this gate's.",
    ),
    "structural::test_secret_references.py": _proof(
        "structural::test_secret_references.py",
        "baseline: 7 passed | mutated: 1 failed, 6 passed :: test_sr1_all_secret_references_are_known | reverted: 7 passed",
        "The plant is now the guard's own stated origin shape — the wrong-default line "
        '`SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/todoits")` — and it REDS, which it '
        "did not before #3255 (2026-08-27). Until then FALSE_POSITIVE_PATTERNS dropped any LINE "
        "containing `SECRET_NAME` (and five sibling identifiers), masking 38 secret-literal lines "
        "against 33 that reached SR1 and leaving four real ids audited by nothing (google-tts x2, "
        "hevy-write, ritual-token-secret x2, site-api-origin-secret — all four provisioned in AWS, all "
        "four already in the IAM-layer registry, so the drift was in this gate alone). Extraction is now "
        "`ast.Constant` full-match: 0 suppressed, 69 references audited. SCOPE, and the SUCCESSOR BLIND "
        "SPOT: only a WHOLE secret-name literal is a reference, so an id assembled by concatenation or "
        "f-string interpolation is invisible — measured DARK 2026-08-27 and carried as this module's "
        "`::assembled-id` control. Comments, docstring mentions and prose are out of scope by design "
        "(docstring ids are tests/test_docstring_secret_ids_2653.py's gate). SR3 is a residual invariant "
        "on the extractor, NOT a near-miss-prefix typo detector: the only near-miss in the tree is the "
        "`LifePlatform/AI` EMF namespace at 67 sites, so closing that would take the suppression list "
        "#3255 just removed. Scans lambdas/ + mcp/ + mcp_server.py only.",
    ),
    "structural::test_no_hardcoded_feature_tier.py": _proof(
        "structural::test_no_hardcoded_feature_tier.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_lambda_hardcodes_a_soft_feature_tier_comparison | reverted: 3 passed",
        "Only a comparison whose operand is a zero-arg `current_tier()` call, and only for SOFT bands "
        "(the hard-stop tier is read from budget_guard so the gate moves with it). A module that copies "
        "the tier into a local first, or reads the SSM parameter directly, is not this gate's shape. "
        "budget_guard.py and bedrock_client.py are allowlisted by design.",
    ),
    "structural::test_lambda_size_gate.py": _proof(
        "structural::test_lambda_size_gate.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_no_new_lambda_god_modules | reverted: 3 passed",
        "`*_lambda.py` filenames ONLY, over 2000 lines, outside GRANDFATHERED. A 5,000-line shared "
        "module that is not named `*_lambda.py` is invisible here — it is `tests/test_module_size_guard.py`'s "
        "1200-line ceiling that covers that case, and the two guards are not substitutes (both are named "
        "in the two-module-size-guard rule).",
    ),
    "structural::test_no_dead_intelligence_functions.py": _proof(
        "structural::test_no_dead_intelligence_functions.py",
        "baseline: 2 passed | mutated: 1 failed, 1 passed :: test_no_live_module_references_deleted_symbols | reverted: 2 passed",
        "A CLOSED hand-list of eight deleted symbol names — this gate catches references to those eight "
        "and nothing else; the ninth deletion is uncovered until someone adds it. Matching is by bare "
        "attribute/name, so an unrelated method that happens to share a name would false-positive. "
        "Carries no population floor: if the lambdas/+mcp/ walk ever returned nothing, both assertions "
        "would pass green (adjudicated a TRUE POSITIVE in this PR's `vacuous-empty` re-sample).",
    ),
    "structural::test_docstring_secret_ids_2653.py": _proof(
        "structural::test_docstring_secret_ids_2653.py",
        "baseline: 11 passed, 1 skipped | mutated: 1 failed, 10 passed, 1 skipped :: test_no_docstring_names_a_secret_no_role_grants | reverted: 11 passed, 1 skipped",
        "MODULE docstrings only (`ast.get_docstring` on the module node) — a stale secret id in a "
        "function or class docstring, in a comment, or in code is out of scope. The line must also read "
        "as secret-ish, and a disclaimer within 110 chars AFTER the id clears it. Truth set is the CDK "
        "role grants, not Secrets Manager, so an id that is granted but does not exist still passes.",
    ),
    "structural::test_site_orphans.py": _proof(
        "structural::test_site_orphans.py",
        "baseline: 3 passed | mutated: 1 failed, 2 passed :: test_every_page_is_linked_or_explicitly_unlisted | reverted: 3 passed",
        'Reachability is a TEXT search for the URL in site/ HTML hrefs plus `"/dir/"` literals in '
        "site/assets/js — a page linked only through a computed path is 'orphaned' to this gate, and a "
        "page linked only from a dead page still counts as linked (there is no transitive walk from the "
        "home page). site/legacy/** is excluded on purpose (#1237).",
    ),
    "structural::test_absence_coverage_3294.py": dict(
        _proof(
            "structural::test_absence_coverage_3294.py",
            "baseline: 20 passed | mutated: 1 failed, 19 passed :: "
            "TestCoverageEnumeration::test_every_reader_has_a_disposition | reverted: 20 passed",
            "The enumeration is keyed on the FIELD NAME `channels_quiet` as an AST string constant in "
            "lambdas/ + mcp/ — a consumer that receives the list through an intermediary variable or a "
            "**kwargs projection never names the field and is invisible to it. Absence claims built from "
            "OTHER raw fields (channel_detail arithmetic, per-source gap_days) are out of this gate's "
            "scope; the licensing check itself adjudicates only what flows through sourced_quiet. The "
            "wire-replay half of the file (the four-absences artifact, the lift-glyph labels) was "
            "separately watched failing behaviourally against pre-fix main 2026-08-29: all three wired "
            "surfaces published all four labels, `NOTHING has been logged` included.",
        ),
        proved_on="2026-08-29",
    ),
    "structural::test_direction_of_travel_ruling_3293.py": dict(
        _proof(
            "structural::test_direction_of_travel_ruling_3293.py",
            "baseline: 33 passed | mutated: 1 failed, 32 passed :: "
            "test_the_registry_covers_every_module_that_imports_the_ruling | reverted: 33 passed",
            "SCOPED BY DESIGN, and the limit is stated in the guard file itself. The registry watches a "
            "hand-listed FIVE surfaces plus a staleness sweep for modules that name `journey_direction` "
            "in lambdas/ + scripts/ + mcp/. A brand-new surface that states a direction of travel WITHOUT "
            "touching the shared ruling — the exact shape of both #3293 defects — is invisible to it; "
            "catching that needs a direction-word lexicon, which is phrase-matching, and "
            "site_api_pulse.py already contains a CORRECT static 'up' next to a formatted number that "
            "such a scan would flag on day one. What this gate does cover is regression: any of the five "
            "ceasing to route through classify_delta. The behavioural half of the file (the recap card's "
            "three surfaces, the served /api/pulse payload) was separately watched failing against "
            "pre-fix main 2026-08-30: 24 failed / 9 passed, including the filed `direction: 'up'` with a "
            "null weigh-in and the `-5.2 lbs down` unfurl.",
        ),
        proved_on="2026-08-30",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# The runner
# ─────────────────────────────────────────────────────────────────────────────

GREEN, RED = "GREEN", "RED"


def _pytest(target: str, extra: tuple[str, ...] = ()) -> tuple[int, str]:
    """(exit code, the one-line pytest tally). The tally travels with the verdict so a
    recorded `observed` is a transcript, never a paraphrase."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider", *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    tally = ""
    for line in reversed((proc.stdout or "").splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            tally = line.strip()
            break
    failed = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.startswith("FAILED ")]
    if failed:
        tally = f"{tally} :: " + "; ".join(f.removeprefix("FAILED ").split(" - ")[0] for f in failed)
    return proc.returncode, tally


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _apply(spec: MutationSpec) -> None:
    for rel, body in spec.plants:
        path = REPO_ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        if spec.track:
            _git("add", "--", rel)


def _revert(spec: MutationSpec) -> None:
    for rel, _body in spec.plants:
        path = REPO_ROOT / rel
        if spec.track:
            _git("rm", "-f", "--cached", "--quiet", "--", rel)
        if path.exists():
            path.unlink()
        parent = path.parent
        # Only ever removes a directory the plant itself created.
        if parent != REPO_ROOT and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


def _dirty(spec: MutationSpec) -> list[str]:
    """Paths a spec is about to write that are not already clean — the precondition."""
    dirty = []
    for rel, _body in spec.plants:
        if (REPO_ROOT / rel).exists():
            dirty.append(rel)
        elif _git("ls-files", "--error-unmatch", "--", rel).returncode == 0:
            dirty.append(rel)
    return dirty


def run_spec(spec: MutationSpec) -> dict[str, Any]:
    """Baseline -> mutated -> reverted. ARMED only when GREEN, RED, GREEN."""
    collision = _dirty(spec)
    if collision:
        return {"gate_id": spec.gate_id, "verdict": "SKIPPED", "reason": f"plant path(s) already present: {collision}"}

    baseline, baseline_tally = _pytest(spec.target, spec.extra_args)
    if baseline != 0:
        return {
            "gate_id": spec.gate_id,
            "verdict": "INDETERMINATE",
            "reason": f"baseline is already RED (exit {baseline}): {baseline_tally}",
        }

    try:
        _apply(spec)
        mutated, mutated_tally = _pytest(spec.target, spec.extra_args)
    finally:
        _revert(spec)
    reverted, reverted_tally = _pytest(spec.target, spec.extra_args)

    if mutated == 0:
        verdict = "DARK"
        reason = "the plant did not red the target — a LEAD, not a cannot-fail verdict (re-check the plant's scope first)"
    elif reverted != 0:
        verdict = "INDETERMINATE"
        reason = f"the tree did not return GREEN after revert (exit {reverted}) — the RED cannot be attributed to the plant"
    else:
        verdict = "ARMED"
        reason = ""
    return {
        "gate_id": spec.gate_id,
        "target": spec.target,
        "verdict": verdict,
        "reason": reason,
        "baseline": baseline,
        "mutated": mutated,
        "reverted": reverted,
        "observed": f"baseline: {baseline_tally} | mutated: {mutated_tally} | reverted: {reverted_tally}",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the generated can-it-fail mutations for census family 5 (#2999).")
    ap.add_argument("--run", action="store_true", help="execute the mutations (baseline -> mutated -> reverted)")
    ap.add_argument("--list", action="store_true", help="print the spec registry without running anything")
    ap.add_argument("--gate", action="append", help="restrict to gate id(s) or target filename(s)")
    args = ap.parse_args(argv)

    selected = list(MUTATION_SPECS.values())
    if args.gate:
        wanted = set(args.gate)
        selected = [s for s in selected if s.gate_id in wanted or Path(s.target).name in wanted]
        if not selected:
            print(f"no spec matches {sorted(wanted)}", file=sys.stderr)
            return 2

    if args.list or not args.run:
        for spec in selected:
            print(f"{spec.gate_id}\n    target  {spec.target}\n    detects {spec.detects}")
        print(f"\n{len(selected)} spec(s). Add --run to execute.")
        return 0

    def _emit(spec: MutationSpec, result: dict[str, Any]) -> None:
        line = f"{result['verdict']:<14} {spec.gate_id}"
        if "baseline" in result:
            line += f"   baseline={result['baseline']} mutated={result['mutated']} reverted={result['reverted']}"
        print(line, flush=True)
        if result.get("observed"):
            print(f"               {result['observed']}", flush=True)
        if result.get("reason"):
            print(f"               {result['reason']}", flush=True)

    results = []
    for spec in selected:
        result = run_spec(spec)
        results.append(result)
        _emit(spec, result)

    controls = []
    if not args.gate:
        print("\n-- measured blind spots (a plant INSIDE scope that must stay DARK) --", flush=True)
        for key, spec in DARK_CONTROLS.items():
            result = run_spec(spec)
            result["control"] = key
            controls.append(result)
            _emit(spec, result)

    armed = sum(1 for r in results if r["verdict"] == "ARMED")
    still_dark = sum(1 for r in controls if r["verdict"] == "DARK")
    print(f"\nARMED {armed} / {len(results)} run; blind spots still DARK {still_dark} / {len(controls)}")
    # Exit non-zero when any spec failed to demonstrate its gate: a harness that always
    # exits 0 is the class of instrument this epic exists to find.
    return 0 if armed == len(results) and still_dark == len(controls) else 1


if __name__ == "__main__":
    raise SystemExit(main())
