"""
tests/test_wiring_coverage.py — Safety module wiring linter + causal language scanner.

Validates that every Lambda in the platform has the required safety modules wired.
Runs in CI Job 2 (test) alongside test_role_policies.py — no AWS credentials needed.

THREE categories of checks:

  W1  platform_logger   — ALL Lambdas must import get_logger (OBS-1)
  W2  ingestion_validator — ALL ingestion Lambdas must call validate_item/validate_and_write (DATA-2)
  W3  ai_output_validator — ALL email + AI-compute Lambdas must import validate_ai_output (AI-3)
  W4  causal language    — No prompt strings may use causal framing ("causes", "proves", etc.)

#2825: ``ALL_LAMBDAS`` used to be a hand-list frozen at 40 of ~106 CDK-defined
Lambdas — ~67 deployed Lambdas (all 12 coach/* engine+chat Lambdas, site-api,
telegram webhook/worker, chronicle-email-sender) had ZERO W1/W2/W3 coverage,
and the list carried a phantom (``weather_handler.py``, renamed to
``weather_lambda.py`` in d50ef4d28) whose checks silently `pytest.skip()`'d to
green. ``ALL_LAMBDAS`` is now DERIVED — an AST walk of `cdk/stacks/*.py`'s
``create_platform_lambda(source_file=...)`` call sites (plus the two hand-
rolled raw ``_lambda.Function(...)`` constructs), in the style of
`tests/test_heartbeat_completeness.py`'s `scheduled_lambdas()`. See
`_derive_all_lambdas()` below for the exact scope (Python sources under
`lambdas/` only — `mcp_server.py` and the Node.js OG-image generator are
different domains, deliberately out of scope, not oversights).

`_exists()` failure is now a hard FAIL, never a skip — a derived entry that
resolves to no file on disk is real drift (a rename on one side of the
CDK/lambdas boundary), and `INGESTION_LAMBDAS`/`AI_OUTPUT_LAMBDAS`/
`PROMPT_LAMBDAS` below stay hand-curated *subsets* of `ALL_LAMBDAS` (deriving
those too — "is this Lambda ingestion? does it call AI?" — is a judgment call
outside this issue's scope; tracked as follow-on debt, not fixed here).

KNOWN GAPS (dated, reasoned, shrink-only — the ratchet primitive, charter #3):
  Each entry is `filename: "YYYY-MM-DD: reason"`. New entries only ever come
  OUT once wired; a gap surfaced by widening ALL_LAMBDAS is recorded here, not
  mass-fixed and not silently exempted. Remove the line when the Lambda is
  wired; the test then enforces it permanently.

Run with:   python3 -m pytest tests/test_wiring_coverage.py -v
Or directly: python3 tests/test_wiring_coverage.py

v1.0.0 — 2026-03-11
v2.0.0 — 2026-08-19 (#2825): ALL_LAMBDAS derived from CDK AST walk, phantom fixed, skip→fail
"""

import ast
import os
import re
import sys

import pytest

# #416 / ADR-117: deploy-critical lane (safety-module + MCP-tool wiring coverage).
pytestmark = pytest.mark.deploy_critical

# ── Project root ─────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")
CDK_STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")


# P3.1 (2026-05-25): subpkg-aware flat-name resolution
def _build_lambda_index():
    idx = {}
    for root, _, files in os.walk(LAMBDAS_DIR):
        if "__pycache__" in root:
            continue
        for fname in files:
            if fname.endswith(".py"):
                idx[fname] = os.path.join(root, fname)
    return idx


_LAMBDA_INDEX = _build_lambda_index()


def _src(filename: str) -> str:
    path = _LAMBDA_INDEX.get(filename) or os.path.join(LAMBDAS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _exists(filename: str) -> bool:
    return filename in _LAMBDA_INDEX or os.path.exists(os.path.join(LAMBDAS_DIR, filename))


# ══════════════════════════════════════════════════════════════════════════════
# #2825 — ALL_LAMBDAS derived from a CDK AST walk (never a hand list again)
# ══════════════════════════════════════════════════════════════════════════════

_SKIP_STACK_FILES = {"lambda_helpers.py"}  # the generic construction helper, not a Lambda call site


def _is_call_to(node: ast.Call, name: str) -> bool:
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)


def _kw(node: ast.Call, name: str):
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _module_string_constants(tree: ast.Module) -> dict:
    """Map NAME -> str for simple top-level `NAME = "literal"` assignments
    (mcp_stack.py's MCP_FUNCTION_NAME/WARMER_FUNCTION_NAME pattern)."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _resolve_str(node, constants: dict):
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _derive_all_lambdas() -> dict:
    """{basename: "stack_file:line"} for every Python Lambda wired via
    cdk/stacks/*.py — create_platform_lambda(source_file=...) calls plus the
    two hand-rolled raw `_lambda.Function(...)` constructs (the HAE webhook,
    handler-derived; the Node.js OG-image generator, excluded by runtime).

    Scoped to source files that resolve under lambdas/ — matching this
    module's own `_LAMBDA_INDEX` (which only ever walked LAMBDAS_DIR).
    `mcp_server.py` (the MCP entry point lives at repo root — a separate
    domain per ADR-146, not part of the lambdas/ package tree) is out of
    scope for the same reason, not an oversight.
    """
    out: dict[str, str] = {}
    unresolved: list[str] = []
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_STACK_FILES:
            continue
        path = os.path.join(CDK_STACKS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        constants = _module_string_constants(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_call_to(node, "create_platform_lambda"):
                src_val = _resolve_str(_kw(node, "source_file"), constants)
                if src_val is None:
                    unresolved.append(f"{fname}:{node.lineno} create_platform_lambda(...) — source_file not statically resolvable")
                    continue
                if not src_val.startswith("lambdas/"):
                    continue  # a different domain (e.g. mcp_server.py) — out of this ledger's scope
                out.setdefault(os.path.basename(src_val), f"{fname}:{node.lineno}")
            elif _is_call_to(node, "Function") and not _is_call_to(node, "create_platform_lambda"):
                # Raw aws_lambda.Function(...) construct — only two exist today.
                runtime_val = _kw(node, "runtime")
                runtime_str = ast.unparse(runtime_val) if runtime_val is not None else ""
                if "PYTHON" not in runtime_str:
                    continue  # Node.js/other runtime — not a Python wiring target
                handler_val = _resolve_str(_kw(node, "handler"), constants)
                if handler_val is None or "." not in handler_val:
                    unresolved.append(f"{fname}:{node.lineno} Function(...) — handler not statically resolvable")
                    continue
                # "ingestion.health_auto_export_lambda.lambda_handler" -> "health_auto_export_lambda.py"
                module_path = handler_val.rsplit(".", 1)[0]
                basename = module_path.split(".")[-1] + ".py"
                out.setdefault(basename, f"{fname}:{node.lineno}")

    assert not unresolved, (
        "cdk/stacks/*.py has a Lambda construct the #2825 enumerator could not "
        "statically resolve to a source file (a new wiring pattern? teach "
        "_derive_all_lambdas() about it — do NOT let it silently vanish from "
        "the wiring-coverage surface):\n  " + "\n  ".join(unresolved)
    )
    return out


_ALL_LAMBDA_SITES = _derive_all_lambdas()

# Every deployable Lambda (filename only, relative to lambdas/) — DERIVED, see above.
ALL_LAMBDAS = sorted(_ALL_LAMBDA_SITES)

# Ingestion Lambdas — must wire ingestion_validator (DATA-2)
INGESTION_LAMBDAS = [
    "strava_lambda.py",
    "whoop_lambda.py",
    "garmin_lambda.py",
    "eightsleep_lambda.py",
    "habitify_lambda.py",
    "withings_lambda.py",
    "todoist_lambda.py",
    "notion_lambda.py",
    "macrofactor_lambda.py",
    "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py",
    "weather_lambda.py",  # #2825: was the phantom "weather_handler.py" (renamed d50ef4d28)
    "enrichment_lambda.py",
    "journal_enrichment_lambda.py",
]

# Email + AI-compute Lambdas — must wire ai_output_validator (AI-3)
AI_OUTPUT_LAMBDAS = [
    # Email
    "daily_brief_lambda.py",
    "weekly_digest_lambda.py",
    "monthly_digest_lambda.py",
    "nutrition_review_lambda.py",
    "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py",
    "monday_compass_lambda.py",
    "partner_email_lambda.py",
    # AI-compute
    "anomaly_detector_lambda.py",
    "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py",
    "adaptive_mode_lambda.py",
]

# Lambdas with inline prompt strings (not sourced from ai_calls.py)
# These are scanned for causal language.  Add any new Lambda that builds
# its own prompt strings here.
PROMPT_LAMBDAS = [
    "weekly_digest_lambda.py",
    "monthly_digest_lambda.py",
    "nutrition_review_lambda.py",
    "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py",
    "monday_compass_lambda.py",
    "partner_email_lambda.py",
    "anomaly_detector_lambda.py",
    "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py",
    "adaptive_mode_lambda.py",
    "ai_calls.py",  # The main prompt module — always checked
]

# ── Known gaps (dated, reasoned, shrink-only — #2825 ratchet) ────────────────
# Format: filename -> "YYYY-MM-DD: reason". Entries only ever come OUT once
# wired; a gap surfaced by widening the scanned surface is recorded here, not
# silently exempted and not mass-fixed in the PR that found it.

# W1 platform_logger gaps.
# #2825 widened ALL_LAMBDAS from a 40-entry hand-list (39 real + 1 phantom) to
# the full CDK-derived surface (103). The 19 entries below are PRE-EXISTING —
# they use stdlib `logging.getLogger` (or nothing at all) instead of
# `platform_logger.get_logger` — and are newly IN SCOPE only because the
# surface widened, not newly broken. Verified by direct read, not assumed.
W1_KNOWN_GAPS: dict[str, str] = {
    "ai_expert_analyzer_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "ai_review_pack_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "coach_daily_reflection_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "coach_memoir_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "coach_nudge_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "cover_pipeline_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "evening_nudge_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "field_notes_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "food_delivery_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "inter_coach_dialogue_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "journal_analyzer_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "milestone_digest_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "og_image_lambda.py": "2026-08-19: no logging at all (Pillow-only writer) — #2825 widened-surface debt",
    "reading_recall_sweep_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "site_api_ai_lambda.py": "2026-08-19: stdlib logging.getLogger via web.site_api_common — #2825 widened-surface debt",
    "site_api_lambda.py": "2026-08-19: stdlib logging.getLogger via web.site_api_common — #2825 widened-surface debt",
    "site_stats_refresh_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "traffic_digest_lambda.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
    "voice_fidelity_harness.py": "2026-08-19: stdlib logging.getLogger, no platform_logger — #2825 widened-surface debt",
}

# W2 ingestion_validator gaps:
W2_KNOWN_GAPS: dict[str, str] = {
    # weather_lambda.py uses ingestion_framework.run_ingestion() which wraps validation
    # internally — the validator is called inside the framework, not directly by the Lambda.
    # (#2825: was recorded against the phantom "weather_handler.py"; renamed to match the
    # real file, weather_lambda.py, per commit d50ef4d28.)
    "weather_lambda.py": "2026-03-11: validated inside ingestion_framework.run_ingestion(), not directly",
    # dropbox_poll_lambda.py: uses conditional put_item path — validator not yet wired.
    "dropbox_poll_lambda.py": "2026-03-11: conditional put_item path — validator not yet wired",
    # enrichment_lambda.py: activity enrichment — validator wiring deferred (pre-existing gap).
    "enrichment_lambda.py": "2026-03-11: activity enrichment — validator wiring deferred",
    # health_auto_export_lambda.py: validator not yet wired (pre-existing gap).
    "health_auto_export_lambda.py": "2026-03-11: validator not yet wired (pre-existing gap)",
    # journal_enrichment_lambda.py: journal enrichment — validator wiring deferred.
    "journal_enrichment_lambda.py": "2026-03-11: journal enrichment — validator wiring deferred",
}

# W3 ai_output_validator gaps:
W3_KNOWN_GAPS: dict[str, str] = {
    # IC-8 makes a direct urllib Haiku call (not via ai_calls.py).
    # TODO: wrap IC-8 response with validate_ai_output (AI-3).
    "daily_insight_compute_lambda.py": "2026-03-11: IC-8 direct urllib Haiku call, not via ai_calls.py — TODO wrap with validate_ai_output",
    # adaptive_mode_lambda.py makes direct API calls — tracked for wiring.
    "adaptive_mode_lambda.py": "2026-03-11: makes direct API calls — tracked for wiring",
}


def test_all_lambdas_surface_is_derived_and_nonempty():
    """#2825: the derived surface itself must not be able to go quietly empty
    (cdk/stacks/ moved, the AST walk broke) — the same GUARD THE SET, NOT THE
    INSTANCE floor as test_pacific_today_guard_2414.py:195-209 and #2790's
    _floored_site_files(). >= 90 is comfortably under the live count (103 as
    of 2026-08-19) so ordinary fleet growth/shrinkage never flakes this."""
    assert len(ALL_LAMBDAS) >= 90, f"suspiciously small CDK-derived Lambda surface: {ALL_LAMBDAS}"
    for expected in (
        "site_api_lambda.py",
        "telegram_webhook_lambda.py",
        "telegram_worker_lambda.py",
        "chronicle_email_sender_lambda.py",
        "coach_state_updater.py",
        "weather_lambda.py",
    ):
        assert expected in ALL_LAMBDAS, f"derived ALL_LAMBDAS lost {expected}"
    assert "weather_handler.py" not in ALL_LAMBDAS, "the #2825 phantom must never resurface"


# ══════════════════════════════════════════════════════════════════════════════
# W1 — platform_logger wired in every Lambda
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("filename", sorted(ALL_LAMBDAS))
def test_w1_platform_logger_imported(filename):
    """W1: Every Lambda must import get_logger from platform_logger (OBS-1)."""
    if not _exists(filename):
        pytest.fail(
            f"{filename}: ALL_LAMBDAS names a file that does not exist under lambdas/ "
            f"(derived from cdk/stacks/ — see {_ALL_LAMBDA_SITES.get(filename, '?')}). "
            "A phantom entry must FAIL, never skip to green (#2825)."
        )
    if filename in W1_KNOWN_GAPS:
        pytest.xfail(f"Known W1 gap: {filename} — {W1_KNOWN_GAPS[filename]}")
    src = _src(filename)
    has_logger = "from platform_logger import" in src or "platform_logger" in src or "get_logger(" in src
    assert has_logger, (
        f"{filename}: platform_logger not imported. OBS-1 requires all Lambdas to use "
        f"structured logging via get_logger(). Add:\n"
        f"  try:\n"
        f"      from platform_logger import get_logger\n"
        f"      logger = get_logger('your-lambda-name')\n"
        f"  except ImportError:\n"
        f"      import logging; logger = logging.getLogger(__name__)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# W2 — ingestion_validator wired in ingestion Lambdas
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("filename", sorted(INGESTION_LAMBDAS))
def test_w2_ingestion_validator_wired(filename):
    """W2: Ingestion Lambdas must wire ingestion_validator before DDB writes (DATA-2)."""
    if not _exists(filename):
        pytest.fail(f"{filename}: INGESTION_LAMBDAS names a file that does not exist under lambdas/ (#2825 — must FAIL, not skip).")
    if filename in W2_KNOWN_GAPS:
        pytest.xfail(f"Known W2 gap: {filename} — {W2_KNOWN_GAPS[filename]}")
    src = _src(filename)
    has_validator = (
        "from ingestion_validator import" in src
        or "ingestion_validator" in src
        or "validate_item(" in src
        or "validate_and_write(" in src
        or "run_ingestion(" in src  # ingestion_framework wraps validation internally
    )
    assert has_validator, (
        f"{filename}: ingestion_validator not imported. DATA-2 requires all ingestion "
        f"Lambdas to call validate_item() or validate_and_write() before table.put_item(). "
        f"Add the import and wrap the DDB write:\n"
        f"  from ingestion_validator import validate_item\n"
        f"  result = validate_item(source, item, date_str)\n"
        f"  if result.should_skip_ddb:\n"
        f"      result.archive_to_s3(s3, bucket, item); return"
    )


# ══════════════════════════════════════════════════════════════════════════════
# W3 — ai_output_validator wired in AI-calling Lambdas
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("filename", sorted(AI_OUTPUT_LAMBDAS))
def test_w3_ai_output_validator_wired(filename):
    """W3: Email and AI-compute Lambdas must wire ai_output_validator (AI-3)."""
    if not _exists(filename):
        pytest.fail(f"{filename}: AI_OUTPUT_LAMBDAS names a file that does not exist under lambdas/ (#2825 — must FAIL, not skip).")
    if filename in W3_KNOWN_GAPS:
        pytest.xfail(f"Known W3 gap: {filename} — {W3_KNOWN_GAPS[filename]}")
    src = _src(filename)
    # Valid wiring patterns:
    # (a) imports from ai_calls which has the middleware built in
    # (b) imports validate_ai_output directly
    # (c) standalone _HAS_AI_VALIDATOR pattern
    has_via_ai_calls = "from ai_calls import" in src or "import ai_calls" in src
    has_direct = "from ai_output_validator import" in src or "validate_ai_output" in src
    has_standalone = "_HAS_AI_VALIDATOR" in src and "validate_ai_output" in src
    assert has_via_ai_calls or has_direct or has_standalone, (
        f"{filename}: ai_output_validator not wired. AI-3 requires all email and "
        f"AI-compute Lambdas to validate AI outputs. Either:\n"
        f"  (a) Use ai_calls wrappers (call_board_of_directors etc.) which include middleware, OR\n"
        f"  (b) Import validate_ai_output directly:\n"
        f"      from ai_output_validator import validate_ai_output, AIOutputType\n"
        f"      result = validate_ai_output(text, AIOutputType.YOUR_TYPE)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# W4 — No causal language in prompt strings
# ══════════════════════════════════════════════════════════════════════════════

# Patterns that indicate causal framing in prompts (case-insensitive)
# Allowlist patterns that are legitimate uses (e.g. discussing the principle)
_CAUSAL_PATTERNS = [
    r"\bcauses\s+your\b",  # "causes your sleep to"
    r"\bproves\s+that\b",  # "proves that the pattern"
    r"\bbecause\s+your\b",  # "because your recovery"
    r"\bis\s+why\s+your\b",  # "is why your HRV"
    r"\bdirectly\s+causing\b",  # "directly causing fatigue"
    r"\bproven\s+to\s+cause\b",  # "proven to cause"
    r"\bcausally\s+linked\b",  # "causally linked to"
    r"\bthis\s+data\s+clearly\s+caus",  # "this data clearly causes"
]

# Lines containing these strings are allowlisted (meta-commentary about causal language)
_CAUSAL_ALLOWLIST = [
    "causal language",  # comments about the principle
    "correlative",  # already framing as correlation
    "not proven causal",  # explicit caveat
    "correlation",  # already using correct framing
    "causal_chain",  # variable name (legacy, renamed)
    "causal →",  # ADR/doc reference
    "causal framing",  # meta-commentary
    "non-causal",
    "likely_connection",
    "# ",  # comment lines
]


def _line_is_allowlisted(line: str) -> bool:
    line_lower = line.lower()
    return any(allow.lower() in line_lower for allow in _CAUSAL_ALLOWLIST)


def _find_causal_violations(src: str, filename: str) -> list[str]:
    violations = []
    for i, line in enumerate(src.splitlines(), 1):
        if _line_is_allowlisted(line):
            continue
        for pattern in _CAUSAL_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append(f"  line {i}: {line.strip()[:120]}")
                break  # one violation per line is enough
    return violations


@pytest.mark.parametrize("filename", sorted(PROMPT_LAMBDAS))
def test_w4_no_causal_language_in_prompts(filename):
    """W4: No causal language in prompt strings — use correlative framing only.

    The platform principle is that all AI outputs must use correlative framing,
    not causal. Prompt strings that prime the model with causal language
    increase the likelihood of causal outputs slipping past ai_output_validator.
    """
    if not _exists(filename):
        pytest.fail(f"{filename}: PROMPT_LAMBDAS names a file that does not exist under lambdas/ (#2825 — must FAIL, not skip).")
    src = _src(filename)
    violations = _find_causal_violations(src, filename)
    assert not violations, (
        f"{filename}: causal language found in prompt strings. "
        f"Replace with correlative framing (e.g. 'correlates with', "
        f"'is associated with', 'tends to follow'):\n" + "\n".join(violations)
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
