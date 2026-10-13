"""tests/test_function_length_guard_4880.py — #4880: the function-length ratchet (D3).

The craft review of 2026-10-13 (finding 5, ``docs/reviews/CRAFT_REVIEW_2026-10-13.md`` on
the #4773 branch) measured **156 functions over 150 lines** with no gate or ratchet bounding
function length at all. ``tests/test_module_size_guard.py`` bounds MODULES; a 600-line
function inside a 900-line module passes it. This is the function-sized sibling of that
guard, and it reuses its ratchet shape exactly:

  * A function over ``HARD_CEILING`` that is not in ``FUNCTION_LENGTH_COUNTS`` -> FAIL.
    Split it, or (only for a genuine dispatch/registry table) put a reasoned
    ``# function-length-exception: <reason>`` comment on the line directly above the
    ``def`` (or above its first decorator).
  * A function in ``FUNCTION_LENGTH_COUNTS`` that grows past its own recorded number -> FAIL.
  * Shrinking is always allowed, and LOWERING a recorded number after a real shrink is the
    ratchet tightening — always welcome, never forced (forcing it would make every
    line-removal PR edit this table, the cost the module guard declined on 2026-08-09).
  * An entry whose function has dropped to/under the ceiling, or no longer exists at that
    key (renamed, moved, deleted), MUST be pruned — a one-line deletion, never a deadlock,
    and leaving it in would licence a regrowth (or a new function of the same name) to the
    old size unpoliced. A rename re-surfaces as a NEW over-limit function anyway, so the
    PR that renames is already editing this table.
  * Generated files (the module guard's ``_GENERATED_RE`` header) are exempt.

THE UNIT is the module guard's #3537 LOGICAL line — a physical line inside the function's
span carrying at least one token that is not a comment, a blank or layout. A docstring is
code (a string expression) and is charged. Using the same token set
(``_NON_LOGICAL_TOKENS``, imported, not copied) means a comment explaining a fix can never
red this gate — the eb777b5b5 class #3537 closed for modules. A function's span runs from
its first decorator to its last line, nested functions included (a nested helper is also
measured on its own key).

WHY 156 IS NOT THE NUMBER BELOW. The review counted PHYSICAL spans (``end_lineno - lineno +
1``) over ``lambdas/`` + ``mcp/``: that reproduces 156 exactly on 2026-10-12. Over this
guard's scope (``lambdas/ mcp/ scripts/ deploy/``) the physical count is 184; in the logical
unit the gate enforces it is the size of ``FUNCTION_LENGTH_COUNTS``. ``python3
tests/test_function_length_guard_4880.py`` prints both, from source, so neither number is
ever hand-typed into a doc.

The table is named ``*_COUNTS`` on purpose: ``scripts/gate_census.py`` reads any module
binding named ``BASELINE`` / ``*_BASELINE`` as a gate registry and would mint one census
gate per entry.

Owner direction pending (#4880 box 4): whether function length becomes a written D2/D3 rule
in ``docs/ENGINEERING_STANDARDS.md``. Until then this is a ratchet on the existing debt only;
the standards doc is deliberately not edited here.
"""

import ast
import io
import os
import re
import subprocess
import sys
import tokenize

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from tests.test_module_size_guard import _GENERATED_RE, _NON_LOGICAL_TOKENS  # noqa: E402

# Logical lines. The review's threshold. Shrink-only: may be lowered, never raised.
HARD_CEILING = 150

# The scope #4880 names. tests/ is out (test bodies legitimately run long); cdk/ is out of
# this first cut (11 logical offenders on 2026-10-12, CDK stack constructors) — widening the
# scope is a one-line change plus their entries.
SCOPE_DIRS = ("lambdas", "mcp", "scripts", "deploy")
_EXCLUDE_SUBSTR = ("node_modules/", "cdk.out/")

_EXCEPTION_RE = re.compile(r"#\s*function-length-exception:\s*(\S.+)")
_GENERATED_SCAN_LINES = 40

# ─────────────────────────────────────────────────────────────────────────────
# THE COUNTS. Every function over the ceiling when this guard landed (2026-10-12, #4880),
# keyed ``<repo-relative path>::<qualname>`` (``Class.method``, ``outer.inner``; a second
# def of the same qualname in one file gets ``#2``). The value is the function's MAXIMUM
# ALLOWED logical line count, measured, not rounded. Down-only, in membership and numbers.
# ─────────────────────────────────────────────────────────────────────────────
FUNCTION_LENGTH_COUNTS = {
    "deploy/archive/cleanup_gap_chronicles_2026_05_03.py::main": 224,
    "deploy/archive/onetime/daily_brief_lambda.py::gather_daily_data": 152,
    "deploy/archive/onetime/daily_brief_lambda.py::lambda_handler": 570,
    "deploy/archive/onetime/fix_public_stats.py::main": 208,
    "deploy/archive/onetime/qa_html.py::check_page": 163,
    "deploy/archive/publish_special_edition_chronicle_2026_05_03.py::main": 153,
    "deploy/derive_cfn_exec_boundary.py::build_policy": 178,
    "deploy/generate_review_bundle.py::build_bundle": 287,
    "deploy/restart_leadin_pages.py::render_post_html": 171,
    "deploy/restart_phase_tag.py::main": 160,
    "deploy/restart_pipeline.py::main": 376,
    "deploy/restart_verify.py::main": 400,
    "deploy/sentinel_github.py::check_github_config": 183,
    "lambdas/ai/ai_calls.py::_run_coach_v2_pipeline": 384,
    "lambdas/ai/ai_calls.py::call_board_of_directors": 190,
    "lambdas/ai/ai_calls.py::call_tldr_and_guidance": 192,
    "lambdas/coach/coach_calibration.py::apply_conversation_calibration": 162,
    "lambdas/coach/coach_history_summarizer.py::_build_compression_message": 196,
    "lambdas/coach/coach_narrative_orchestrator.py::_build_user_message": 172,
    "lambdas/coach/coach_observatory_renderer.py::_render_coach_card": 249,
    "lambdas/coach/critics.py::build_joints_packet": 155,
    "lambdas/compute/character_sheet_lambda.py::lambda_handler": 180,
    "lambdas/compute/daily_insight_compute_lambda.py::_compute_slow_drift": 167,
    "lambdas/compute/daily_insight_compute_lambda.py::lambda_handler": 233,
    "lambdas/compute/daily_metrics_compute_lambda.py::lambda_handler": 162,
    "lambdas/compute/dashboard_refresh_lambda.py::refresh_buddy": 234,
    "lambdas/content/brief_weekly_habits.py::_render_weekly_habit_review": 162,
    "lambdas/content/html_builder.py::_brief_character": 186,
    "lambdas/content/html_builder.py::_brief_journal_coaches": 229,
    "lambdas/content/html_builder.py::_brief_lifestyle": 232,
    "lambdas/content/html_builder.py::_brief_scorecards": 229,
    "lambdas/content/html_builder.py::_brief_training_body": 399,
    "lambdas/content/output_writers.py::write_buddy_json": 248,
    "lambdas/content/output_writers.py::write_clinical_json": 187,
    "lambdas/content/output_writers.py::write_dashboard_json": 195,
    "lambdas/content/site_writer.py::_compute_pulse": 161,
    "lambdas/emails/chronicle_data.py::build_data_packet": 372,
    "lambdas/emails/chronicle_data.py::gather_chronicle_data": 167,
    "lambdas/emails/chronicle_email_sender_lambda.py::_build_subscriber_email": 157,
    "lambdas/emails/chronicle_render.py::publish_to_journal": 332,
    "lambdas/emails/coach_panel_podcast_lambda.py::_run_intro": 155,
    "lambdas/emails/coach_panel_podcast_lambda.py::_run_weekly": 216,
    "lambdas/emails/daily_brief_lambda.py::gather_daily_data": 202,
    "lambdas/emails/daily_brief_lambda.py::lambda_handler": 896,
    "lambdas/emails/freshness_checker_lambda.py::lambda_handler": 477,
    "lambdas/emails/monthly_digest_render.py::build_html": 323,
    "lambdas/emails/partner_email_lambda.py::gather_all": 182,
    "lambdas/emails/wednesday_chronicle_lambda.py::_handler_core": 581,
    "lambdas/emails/weekly_digest_lambda.py::build_html": 679,
    "lambdas/health/character_engine.py::compute_character_sheet": 267,
    "lambdas/health/character_engine.py::evaluate_level_changes": 189,
    "lambdas/health/nutrition_critics.py::build_deficit_advocate_packet": 153,
    "lambdas/health/nutrition_critics.py::build_muscle_defense_packet": 163,
    "lambdas/ingestion/food_delivery_lambda.py::ingest_food_delivery_rows": 177,
    "lambdas/ingestion/health_auto_export_lambda.py::lambda_handler": 223,
    "lambdas/ingestion/health_auto_export_lambda.py::process_generic_metrics": 165,
    "lambdas/ingestion/health_auto_export_lambda.py::process_state_of_mind": 152,
    "lambdas/ingestion/hevy_backfill_lambda.py::lambda_handler": 163,
    "lambdas/ingestion/ingestion_framework.py::run_ingestion": 202,
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::build_prompt": 189,
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::gather_data_for_expert": 227,
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::generate_and_cache": 210,
    "lambdas/intelligence/intelligence_common.py::build_coach_preamble": 182,
    "lambdas/operational/pipeline_health_check_lambda.py::lambda_handler": 154,
    "lambdas/training/full_body_session.py::full_body_routines": 160,
    "lambdas/training/plan_engine.py::_tripwire_states": 259,
    "lambdas/training/plan_engine.py::constraint_block": 302,
    "lambdas/web/recap_card_lambda.py::render_for_date": 190,
    "lambdas/web/site_api_ai_lambda.py::_handle_board_followup": 181,
    "lambdas/web/site_api_autonomic.py::_compute_zone2_breakdown": 194,
    "lambdas/web/site_api_body.py::vitals": 174,
    "lambdas/web/site_api_budget.py::inference_receipt": 229,
    "lambdas/web/site_api_character.py::character": 186,
    "lambdas/web/site_api_coach_ledger.py::handle_predictions": 193,
    "lambdas/web/site_api_coach_narrative.py::handle_coach_analysis": 190,
    "lambdas/web/site_api_coach_narrative.py::handle_coach_timeline": 163,
    "lambdas/web/site_api_habits.py::habits": 286,
    "lambdas/web/site_api_journey.py::journey_timeline": 237,
    "lambdas/web/site_api_lambda.py::_dispatch_route": 296,
    "lambdas/web/site_api_ledger.py::discoveries": 190,
    "lambdas/web/site_api_mind.py::mind_overview": 222,
    "lambdas/web/site_api_nutrition.py::deficit_sustainability": 158,
    "lambdas/web/site_api_nutrition.py::nutrition_overview": 532,
    "lambdas/web/site_api_physical.py::physical_overview": 231,
    "lambdas/web/site_api_pulse.py::pulse": 450,
    "lambdas/web/site_api_rollups.py::observatory_week": 265,
    "lambdas/web/site_api_sleep.py::sleep_correlations": 169,
    "lambdas/web/site_api_sleep.py::sleep_detail": 225,
    "lambdas/web/site_api_status.py::status": 737,
    "lambdas/web/site_api_training.py::training_overview": 389,
    "mcp/tools_cgm.py::_get_fasting_glucose_validation": 327,
    "mcp/tools_correlation.py::tool_get_zone2_breakdown": 274,
    "mcp/tools_health.py::_get_hydration_score": 177,
    "mcp/tools_health.py::tool_get_readiness_score": 355,
    "mcp/tools_health.py::tool_get_weight_loss_progress": 183,
    "mcp/tools_hevy_routine.py::_action_draft_custom": 169,
    "mcp/tools_journal.py::tool_mark_journal_quote": 161,
    "mcp/tools_labs.py::tool_get_freshness_status": 257,
    "mcp/tools_lifestyle.py::_get_state_of_mind_trend": 176,
    "mcp/tools_lifestyle.py::tool_create_experiment": 207,
    "mcp/tools_lifestyle.py::tool_get_experiment_results": 166,
    "mcp/tools_nutrition.py::tool_get_deficit_sustainability": 211,
    "mcp/tools_plan.py::tool_plan_next_session": 253,
    "mcp/tools_training.py::_get_training_periodization": 296,
    "mcp/tools_training.py::_get_training_recommendation": 377,
    "scripts/apply_branch_protection.py::main": 165,
    "scripts/check_alarm_citations.py::render": 169,
    "scripts/coach_sim_analyze.py::write_report": 195,
    "scripts/generate_platform_model.py::render_doc": 208,
    "scripts/monthly_close.py::main": 159,
    "scripts/platform_model_alarms.py::extract_alarms": 151,
}


def _tracked_scope_py_files():
    out = subprocess.run(["git", "ls-files", "-z", *SCOPE_DIRS], cwd=_REPO, capture_output=True, text=True, check=True).stdout
    return sorted(rel for rel in out.split("\0") if rel.endswith(".py") and not any(s in rel for s in _EXCLUDE_SUBSTR))


def _code_lines(raw):
    """The set of physical line numbers carrying a logical token (#3537's unit).

    ``None`` when the source cannot be tokenized — the caller then charges every
    physical line (fail toward the STRICTER number, the module guard's rule).
    """
    lines = set()
    try:
        for tok in tokenize.tokenize(io.BytesIO(raw).readline):
            if tok.type in _NON_LOGICAL_TOKENS:
                continue
            lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError, IndentationError, UnicodeDecodeError):
        return None
    return lines


def measure_source(raw):
    """``[(qualname, logical_lines, physical_lines, exempt), ...]`` for every def in ``raw``.

    Pure over bytes, so the mutation controls run on synthetic source without touching
    the tree. An unparseable file yields ``[]`` — ``py_compile`` in CI owns that failure.
    """
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError):
        return []
    code = _code_lines(raw)
    src_lines = raw.decode("utf-8", errors="replace").splitlines()
    out, seen = [], {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                seen[qual] = seen.get(qual, 0) + 1
                key = qual if seen[qual] == 1 else f"{qual}#{seen[qual]}"
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                span = range(start, child.end_lineno + 1)
                logical = len(span) if code is None else sum(1 for ln in span if ln in code)
                above = src_lines[start - 2] if start >= 2 else ""
                out.append((key, logical, len(span), bool(_EXCEPTION_RE.search(above))))
                visit(child, f"{qual}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out


def _is_generated(raw):
    head = "\n".join(raw.decode("utf-8", errors="replace").splitlines()[:_GENERATED_SCAN_LINES])
    return bool(_GENERATED_RE.search(head))


def measure_files(files):
    """``{key: (logical, physical, exempt)}`` over ``[(rel, raw_bytes), ...]``."""
    found = {}
    for rel, raw in files:
        generated = _is_generated(raw)
        for qual, logical, physical, exempt in measure_source(raw):
            found[f"{rel}::{qual}"] = (logical, physical, exempt or generated)
    return found


def measure_tree():
    files = []
    for rel in _tracked_scope_py_files():
        path = os.path.join(_REPO, rel)
        if not os.path.isfile(path):
            continue  # tracked but deleted in the working tree
        with open(path, "rb") as fh:
            files.append((rel, fh.read()))
    return measure_files(files)


def verdicts(measured, counts, ceiling=HARD_CEILING):
    """The pure decision: ``{"new": [...], "grew": [...], "stale": [...]}``.

    new   — over the ceiling, not in ``counts``, not exempt: ``(key, n)``
    grew  — in ``counts`` and over its own recorded number: ``(key, cap, n)``
    stale — in ``counts`` but at/under the ceiling, or no longer present: ``(key, n|None)``
    """
    new = sorted((k, v[0]) for k, v in measured.items() if v[0] > ceiling and k not in counts and not v[2])
    grew = sorted((k, cap, measured[k][0]) for k, cap in counts.items() if k in measured and measured[k][0] > cap)
    stale = sorted((k, measured[k][0] if k in measured else None) for k in counts if k not in measured or measured[k][0] <= ceiling)
    return {"new": new, "grew": grew, "stale": stale}


_MEASURED = None


def _tree():
    global _MEASURED
    if _MEASURED is None:
        _MEASURED = measure_tree()
    return _MEASURED


_SPLIT_HINT = (
    "Split the function into named helpers (same public signature, no contract change). Only a "
    "genuine dispatch/registry table may instead carry `# function-length-exception: <reason>` on "
    "the line directly above its `def` (or first decorator). Never add a FUNCTION_LENGTH_COUNTS line "
    "to clear this red — that table is the debt as it stood on 2026-10-12 and only shrinks (#4880)."
)


# ── A. THE RATCHET (real tree) ─────────────────────────────────────────────────────────
def test_no_new_overlong_function():
    v = verdicts(_tree(), FUNCTION_LENGTH_COUNTS)
    assert not v["new"], (
        f"Function(s) over the {HARD_CEILING}-logical-line ceiling with no recorded count (#4880):\n"
        + "\n".join(f"  {k}: {n} lines" for k, n in v["new"])
        + "\n\n"
        + _SPLIT_HINT
    )


def test_recorded_functions_do_not_grow():
    v = verdicts(_tree(), FUNCTION_LENGTH_COUNTS)
    assert not v["grew"], (
        "Function(s) grew past their recorded count in FUNCTION_LENGTH_COUNTS (#4880):\n"
        + "\n".join(f"  {k}: {n} lines, recorded {cap} (+{n - cap})" for k, cap, n in v["grew"])
        + "\n\nDo NOT raise the number. Extract a helper out of the function and pay for the new lines "
        "out of what you removed; then LOWER its recorded count to the new measure."
    )


def test_counts_have_no_stale_entries():
    v = verdicts(_tree(), FUNCTION_LENGTH_COUNTS)
    assert not v["stale"], (
        "FUNCTION_LENGTH_COUNTS entr(ies) to delete — the function is now at/under the ceiling, or no "
        "longer exists at that key (renamed/moved/deleted; a renamed one re-appears as a new offender "
        "and must be split or carried under its new key at no more than its old number):\n"
        + "\n".join(f"  {k}: {'gone' if n is None else f'{n} lines'}" for k, n in v["stale"])
    )


def test_counts_are_positive_ints_above_the_ceiling():
    bad = sorted(k for k, c in FUNCTION_LENGTH_COUNTS.items() if not isinstance(c, int) or isinstance(c, bool) or c <= HARD_CEILING)
    assert not bad, f"FUNCTION_LENGTH_COUNTS values must be ints above {HARD_CEILING}: {bad}"


# ── B. THE MUTATION CONTROLS (synthetic, no tree write) ────────────────────────────────
def _synthetic_function(name, body_lines):
    return f"def {name}(x):\n" + "".join(f"    x = x + {i}\n" for i in range(body_lines - 1))


def test_a_151_line_function_in_a_scanned_module_reds():
    """#4880 box 3. A 151-logical-line function added to a real scanned module reds the
    gate against the REAL counts table; 150 does not (the boundary is strictly-greater)."""
    rel = "lambdas/web/site_api_lambda.py"
    with open(os.path.join(_REPO, rel), "rb") as fh:
        real = fh.read()
    assert rel in _tracked_scope_py_files() and not _is_generated(real), "the control needs a scanned, non-generated module"
    for n, should_red in ((HARD_CEILING + 1, True), (HARD_CEILING, False)):
        planted = real + b"\n\n" + _synthetic_function("_planted_4880", n).encode()
        measured = measure_files([(rel, planted)])
        assert measured[f"{rel}::_planted_4880"][0] == n
        new = verdicts(measured, FUNCTION_LENGTH_COUNTS)["new"]
        assert ((f"{rel}::_planted_4880", n) in new) is should_red, (n, new)


def test_a_recorded_function_that_grows_reds_and_one_that_shrinks_passes():
    key = "mod.py::f"
    assert verdicts({key: (201, 201, False)}, {key: 200})["grew"] == [(key, 200, 201)]
    assert verdicts({key: (200, 200, False)}, {key: 200}) == {"new": [], "grew": [], "stale": []}
    assert verdicts({key: (180, 180, False)}, {key: 200}) == {"new": [], "grew": [], "stale": []}
    # Lowering the recorded number after the shrink is the ratchet tightening: regrowth now reds.
    assert verdicts({key: (181, 181, False)}, {key: 180})["grew"] == [(key, 180, 181)]


def test_a_recorded_function_that_drops_under_or_vanishes_must_be_pruned():
    assert verdicts({"m::f": (150, 150, False)}, {"m::f": 200})["stale"] == [("m::f", 150)]
    assert verdicts({}, {"m::f": 200})["stale"] == [("m::f", None)]


def test_a_comment_cannot_move_the_count_and_a_statement_must():
    base = _synthetic_function("f", 20)
    n = measure_source(base.encode())[0][1]
    commented = base.replace("    x = x + 3\n", "    # why this step exists\n\n    x = x + 3  # trailing\n")
    assert measure_source(commented.encode())[0][1] == n
    assert measure_source((base + "    x = x + 99\n").encode())[0][1] == n + 1


def test_exception_comment_and_generated_header_exempt_and_need_a_reason():
    body = _synthetic_function("big", HARD_CEILING + 5)
    assert verdicts(measure_files([("m.py", ("# function-length-exception: dispatch table\n" + body).encode())]), {})["new"] == []
    assert verdicts(measure_files([("m.py", ("# function-length-exception:\n" + body).encode())]), {})["new"] != []
    assert verdicts(measure_files([("m.py", ("# AUTO-GENERATED by x\n" + body).encode())]), {})["new"] == []


def test_keys_are_qualified_and_duplicates_are_numbered():
    src = b"class C:\n    def m(self):\n        def inner():\n            pass\n\ndef f():\n    pass\n\ndef f():\n    pass\n"
    assert [k for k, *_ in measure_source(src)] == ["C.m", "C.m.inner", "f", "f#2"]


def test_decorators_are_charged_to_the_function():
    src = b"@a\n@b(\n    1,\n)\ndef f():\n    pass\n"
    assert measure_source(src)[0][1:3] == (6, 6)


def _report():
    measured = _tree()
    logical = sorted(((v[0], k) for k, v in measured.items() if v[0] > HARD_CEILING and not v[2]), reverse=True)
    physical = [k for k, v in measured.items() if v[1] > HARD_CEILING]
    review_scope = [k for k in physical if k.startswith(("lambdas/", "mcp/"))]
    print(f"function-length (#4880): ceiling {HARD_CEILING} logical lines, scope {' '.join(SCOPE_DIRS)}")
    print(f"  over the ceiling, logical unit (the gate): {len(logical)}; recorded: {len(FUNCTION_LENGTH_COUNTS)}")
    print(f"  over 150 by physical span: {len(physical)} ({len(review_scope)} in lambdas/ + mcp/, the review's 156 scope)")
    if "--counts" in sys.argv:
        for n, k in sorted(logical, key=lambda t: t[1]):
            print(f'    "{k}": {n},')
        return
    for n, k in logical:
        cap = FUNCTION_LENGTH_COUNTS.get(k)
        print(f"  {n:>5}  {'' if cap is None else cap - n:>8}  {k}")


if __name__ == "__main__":
    _report()
