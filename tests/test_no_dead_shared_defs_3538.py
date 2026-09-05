"""tests/test_no_dead_shared_defs_3538.py — #3538: nothing dead rides in every bundle.

THE COST. ``lambdas/common`` and ``lambdas/ai`` are not ordinary packages: under the
one-bundle rule (#781, CONVENTIONS §1) their entire source tree is staged into EVERY
Lambda zip — ~104 of them. A public function nothing calls is not merely clutter, it is
carried ~104 times, appears in every reader's grep, and reads as API. #1239 established
the discipline and deleted eight such functions, but scoped its guard to the word
"intelligence": the two packages that ship the most widely had no guard at all.

WHAT IS FLAGGED. A top-level, non-underscore ``def``/``async def`` in ``lambdas/common``
or ``lambdas/ai`` with ZERO references across the live surface:

    lambdas/  mcp/  deploy/  scripts/  cdk/  and the harnesses in tests/ that are
    not themselves tests (tests/visual_qa.py, tests/visual_ai_qa.py, …)

``tests/test_*.py`` is deliberately NOT live surface — a function whose only caller is
its own unit test is the thing this guard exists to find. The harnesses ARE live: they
run in CI as gates, and excluding them would have made this guard delete working code
(see ``attributed_to`` below).

HOW A REFERENCE IS COUNTED — both ways, because either alone is wrong:
  * AST (``Name`` load, attribute access, ``import``/``from`` alias). A mention inside a
    COMMENT is not a reference; a text scan counts it and calls dead code live.
    ``budget_guard.hard_stopped`` is the live specimen: its only non-test "reference" in
    the repo is a sentence in scripts/gate_census_enforcement.py's prose.
  * String literals. ``getattr(mod, "name")`` is invisible to AST, and this repo does it:
    ``tests/visual_ai_qa.py`` reaches ``bedrock_client.attributed_to`` by string. An
    AST-only scan calls that function dead, and deleting it breaks the visual-QA gate —
    the exact "string/getattr dispatch is invisible to the scan" caveat #3538 carries.

THE ALLOWLIST IS SHRINK-ONLY. An entry for a def the scan no longer flags fails, so it
can only get smaller. Prefer deletion; an entry has to say what would call the function.
"""

import ast
import os
import pathlib

_TESTS = pathlib.Path(__file__).resolve().parent
_REPO = _TESTS.parent

SCAN_PACKAGES = ("lambdas/common", "lambdas/ai")
LIVE_DIRS = ("lambdas", "mcp", "deploy", "scripts", "cdk")

# "package/module.py:name" -> what actually calls it. Deletion is the default; an entry
# here is a claim about a live caller the AST+string scan cannot see.
#
# Three shared defs whose only callers are deploy-time tools are NOT flagged and need no
# entry, because deploy/ and scripts/ are live surface here: token_alarm_window
# .window_for_genesis (deploy/restart_pipeline.py, deploy/restart_verify.py),
# record_text.coach_output_text (deploy/backfill_recall_embeddings.py) and
# request_validator.validate_source (deploy/dedup_source_records.py). That they ride in
# the bundle unused at RUNTIME is a packaging question (#781), not a dead-code one.
_BATCH_REASON = (
    "ADR-132 / #409: bedrock_batch ships the batch-inference MECHANISM deliberately "
    "unwired. Bedrock's hard floor is 100 records per job per model and measured volume "
    "is ~62 model calls/day across ALL producers mixed across models, so no producer can "
    "honestly submit a batch today — the module's own docstring is the decision and names "
    "batch_preflight() as the gate a future adopter calls first. This is a documented "
    "latent capability with full tests, not a leftover; deleting it is an ADR-132 reversal, "
    "not a dead-code cleanup. Revisit when a producer clears the 100-record floor."
)

ALLOWED_UNREFERENCED_SHARED_DEFS: dict[str, str] = {
    "lambdas/ai/bedrock_batch.py:build_jsonl_record": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:submit_batch": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:wait_for_batch": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:retrieve_results": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:run_or_fallback": _BATCH_REASON,
    "lambdas/ai/bedrock_batch.py:estimate_batch_savings": _BATCH_REASON,
    "lambdas/ai/ai_calls.py:call_training_coach_v2": (
        "one seat of a symmetric ADR-153 coach family (sleep / nutrition / training / mind, "
        "each a 3-line `_run_coach_v2_pipeline(<seat>, ...)` wrapper). The daily-brief tests "
        "patch it BY NAME as part of the brief's coach roster "
        "(tests/test_daily_brief_grounding_and_hold.py: 'ADR-153: call_training_coach_v2 "
        "stays mocked here even though the seat is...'), so removing one member breaks the "
        "roster and leaves an asymmetric family. Retiring a coach seat is a coaching-team "
        "decision, not a dead-code sweep."
    ),
    "lambdas/ai/bedrock_client.py:structured_output_config": (
        "half of a live CONTRACT test, not a leftover. #1385 AC4 "
        "(tests/test_whole_life_context_1385.py) uses it to build the body it then feeds "
        "through invoke() to prove the chokepoint FORWARDS `output_config` and STRIPS "
        "`model`. Delete the builder and the only proof that Bedrock Structured Outputs "
        "survive the chokepoint goes with it."
    ),
    "lambdas/common/send_guard.py:guarded_send_raw_email": (
        "a named member of a SAFETY SET. tests/test_ses_send_guard_set_2222.py declares "
        "GUARD_HELPERS = {guarded_send_email, guarded_send_raw_email} as the sanctioned "
        "gate every SES send must pass through, against SES_SEND_METHODS = {send_email, "
        "send_raw_email, send_templated_email}. Removing the raw-email helper because no "
        "sender uses it TODAY would mean the next raw-email sender has no sanctioned gate "
        "to use — shrinking a safety set is the #2610 anti-pattern, not a cleanup."
    ),
    "lambdas/common/input_manifest.py:reset_run_manifests": (
        "test-support for a LIVE contract class. tests/test_input_manifest_contract_3049.py"
        "::TestChokepoint calls it to clear the per-run manifest cache between cases; "
        "without it the whole class errors at setup and DIL-025's chokepoint contract goes "
        "dark. Same misplacement as prompt_cache's helpers — it belongs on the test side "
        "rather than in ~104 bundles, and moving it is its own change."
    ),
    "lambdas/common/quarter_utils.py:quarter_key": (
        "the INVERSE half of a round-trip contract: tests/test_quarter_utils.py"
        "::test_quarter_bounds_round_trip asserts quarter_key(quarter_bounds(q)[0]) == q and "
        "that the exclusive end lands in the NEXT quarter. quarter_bounds IS live "
        "(lambdas/compute/coach_memoir_lambda.py), so deleting its inverse would leave the "
        "live function's boundary math asserted only against hand-typed dates."
    ),
    "lambdas/ai/prompt_cache.py:clears_floor": (
        "the COMPUTATION of a live gate, not a leftover. "
        "tests/test_prompt_cache_decisions_3085.py asserts "
        "`clears_floor(the real prompt, the real model) == entry['engaged']` for every "
        "recorded caller — deleting it deletes the only thing that checks the "
        "CACHING_DECISIONS ledger against the models' actual minimum prefixes (#3085). It "
        "is misplaced (it belongs on the test side, where it would not ride ~104 bundles), "
        "not unused; moving it is a separate change with a real regression risk."
    ),
    "lambdas/ai/prompt_cache.py:cached_prefix_blocks": (
        "same class as clears_floor: the byte-stable prefix assembler the #2888 tests "
        "drive directly. Its production callers are the ones #2888/#3085 are still "
        "converting; the record of which callers have and have not engaged caching lives "
        "in CACHING_DECISIONS in this same module."
    ),
}


def _py_files(rel_dir: str):
    for root, _dirs, files in os.walk(_REPO / rel_dir):
        if "node_modules" in root or "cdk.out" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield pathlib.Path(root) / name


def _live_surface() -> list[pathlib.Path]:
    """Every file whose reference to a shared def counts as a live use. tests/test_*.py
    is excluded on purpose; the tests/ HARNESSES are included because CI runs them."""
    files: list[pathlib.Path] = []
    for rel in LIVE_DIRS:
        files += list(_py_files(rel))
    files += [p for p in _py_files("tests") if not p.name.startswith("test_")]
    return files


def _public_top_level_defs() -> dict[str, tuple[str, int, int]]:
    """ "<module rel path>:<name>" -> (rel, first line, last line)."""
    out: dict[str, tuple[str, int, int]] = {}
    for rel_dir in SCAN_PACKAGES:
        for path in _py_files(rel_dir):
            rel = str(path.relative_to(_REPO))
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    out[f"{rel}:{node.name}"] = (rel, node.lineno, node.end_lineno or node.lineno)
    return out


def _referenced_names(path: pathlib.Path) -> set[str]:
    """Every name this file references — AST loads/attributes/imports, PLUS string
    literals (getattr dispatch).

    A `def` statement is NOT a reference (ast.FunctionDef carries its name as a plain
    string, not a Name node), so a function is never kept alive by its own definition.
    An intra-module CALL is: if `run_or_fallback` calls `submit_batch`, submit_batch is
    referenced. That under-reports a wholly-dead cluster and never over-reports, which
    is the right direction for a guard whose remedy is deletion.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    refs: set[str] = set()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return refs
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.add(node.value)  # getattr(mod, "name") / a dispatch table key
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                refs.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                refs.add(alias.name.split(".")[0])
    return refs


def scan_dead_shared_defs() -> dict[str, str]:
    """ "<module>:<name>" -> a human-readable size, for every unreferenced public def."""
    defs = _public_top_level_defs()
    wanted = {key.split(":", 1)[1] for key in defs}
    referenced: set[str] = set()
    for path in _live_surface():
        referenced |= _referenced_names(path) & wanted
    return {
        key: f"{end - start + 1} lines at {rel}:{start}"
        for key, (rel, start, end) in defs.items()
        if key.split(":", 1)[1] not in referenced
    }


def test_no_dead_public_def_ships_in_every_bundle():
    """A public def in lambdas/common or lambdas/ai that nothing outside its own unit
    test calls is dead weight in ~104 bundles — delete it, or register a caller."""
    dead = scan_dead_shared_defs()
    unregistered = {k: v for k, v in dead.items() if k not in ALLOWED_UNREFERENCED_SHARED_DEFS}
    assert not unregistered, (
        "Public def(s) in the every-bundle packages with no reference anywhere on the live\n"
        "surface (lambdas/ mcp/ deploy/ scripts/ cdk/ + the tests/ harnesses). Under the\n"
        "one-bundle rule these ship in ~104 Lambda zips and read as API. Delete them (with\n"
        "their unit tests), or add an entry to ALLOWED_UNREFERENCED_SHARED_DEFS naming what\n"
        "calls them:\n" + "\n".join(f"  {k}  ({v})" for k, v in sorted(unregistered.items()))
    )


def test_the_allowlist_has_no_dead_entries():
    dead = scan_dead_shared_defs()
    stale = sorted(k for k in ALLOWED_UNREFERENCED_SHARED_DEFS if k not in dead)
    assert not stale, f"ALLOWED_UNREFERENCED_SHARED_DEFS lists entr(ies) the scan no longer flags; delete them: {stale}"


def test_the_scan_counts_a_string_dispatch_as_a_reference():
    """The caveat that makes this guard safe to act on. ``tests/visual_ai_qa.py`` reaches
    ``bedrock_client.attributed_to`` through ``getattr(bedrock, "attributed_to", None)``.
    An AST-only scan reports it dead; deleting it breaks the visual-QA gate. Pin the
    live specimen, not a synthetic one — a synthetic proves the code path, this proves
    the repo still contains the hazard the code path exists for."""
    harness = _REPO / "tests" / "visual_ai_qa.py"
    assert (
        'getattr(bedrock, "attributed_to"' in harness.read_text()
    ), "the live string-dispatch specimen moved; re-verify this guard's string-literal branch against its replacement"
    assert "lambdas/ai/bedrock_client.py:attributed_to" not in scan_dead_shared_defs()


def test_the_scan_ignores_a_mention_in_a_COMMENT():
    """The inverse caveat. A grep-based scan counts prose. ``hard_stopped`` was named
    only in a sentence in scripts/gate_census_enforcement.py, which is why a text scan
    called it live while it had no caller at all."""
    src = "# hard_stopped is mentioned here in prose only\nx = 1\n"
    tree_refs = _referenced_names_from_source(src)
    assert "hard_stopped" not in tree_refs


def _referenced_names_from_source(src: str) -> set[str]:
    refs: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.add(node.value)
    return refs


# ─────────────────────────────────────────────────────────────────────────────
# The second half of #3538: no module may FORK a common.* symbol behind ImportError.
#
# Seven modules carried `try: from common.numeric import floats_to_decimal / except
# ImportError: def floats_to_decimal(obj): ...`. Under the one-bundle rule the import
# ALWAYS resolves, so the fallback is unreachable — and it had silently diverged from
# the canonical implementation, which since #1656 maps NaN/Inf to None. If the import
# path ever did break, six of the seven would have written NaN into DynamoDB instead of
# raising. A fork that cannot run is not a safety net; it is a second definition nobody
# tests and nobody updates.


def _import_error_redefinitions() -> dict[str, list[str]]:
    """ "<rel path>" -> the names re-defined inside an `except ImportError:` handler
    whose matching `try:` imported them from a `common.*` module."""
    found: dict[str, list[str]] = {}
    for rel_dir in ("lambdas", "mcp"):
        for path in _py_files(rel_dir):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                imported = {
                    alias.asname or alias.name
                    for stmt in node.body
                    if isinstance(stmt, ast.ImportFrom) and (stmt.module or "").split(".")[0] == "common"
                    for alias in stmt.names
                }
                if not imported:
                    continue
                for handler in node.handlers:
                    names = {n.id for n in ast.walk(handler.type) if isinstance(n, ast.Name)} if handler.type else set()
                    if "ImportError" not in names and "ModuleNotFoundError" not in names:
                        continue
                    for sub in ast.walk(handler):
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name in imported:
                            found.setdefault(str(path.relative_to(_REPO)), []).append(sub.name)
    return found


def test_no_module_forks_a_common_symbol_behind_an_import_error():
    """A `common.*` symbol has exactly one definition. See the block comment above."""
    forks = _import_error_redefinitions()
    assert not forks, (
        "Module(s) re-define a `common.*` symbol inside `except ImportError:`. The\n"
        "one-bundle rule (#781) means that import always resolves, so the fork is dead —\n"
        "and it drifts: the seven floats_to_decimal forks removed at #3538 had all lost\n"
        "the canonical NaN/Inf -> None branch, so if the import path ever DID break they\n"
        "would have written NaN to DynamoDB rather than failed. Import it, and let a\n"
        "broken import break loudly:\n" + "\n".join(f"  {rel}: {', '.join(names)}" for rel, names in sorted(forks.items()))
    )


def test_the_import_error_fork_scan_fires_on_the_shape_it_removed(tmp_path):
    """Mutation proof against a scanner that silently matches nothing — in the exact
    shape the seven removed forks had, TYPE_CHECKING guard and all."""
    import ast as _ast

    forked = (
        "from typing import TYPE_CHECKING\n"
        "try:\n"
        "    from common.numeric import floats_to_decimal  # noqa: F401\n"
        "except ImportError:\n"
        "    if not TYPE_CHECKING:\n"
        "\n"
        "        def floats_to_decimal(obj):\n"
        "            return obj\n"
    )
    tree = _ast.parse(forked)
    hits = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Try):
            imported = {
                a.name for s in node.body if isinstance(s, _ast.ImportFrom) and (s.module or "").split(".")[0] == "common" for a in s.names
            }
            for h in node.handlers:
                for sub in _ast.walk(h):
                    if isinstance(sub, _ast.FunctionDef) and sub.name in imported:
                        hits.append(sub.name)
    assert hits == ["floats_to_decimal"], "the detection shape itself must match the removed fork"

    # ...and the prescribed replacement — a bare import — must not be flagged.
    plain = _ast.parse("from common.numeric import floats_to_decimal\n")
    assert not [n for n in _ast.walk(plain) if isinstance(n, _ast.Try)]
