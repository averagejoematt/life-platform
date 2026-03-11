"""
tests/test_wiring_coverage.py — Safety module wiring linter + causal language scanner.

Validates that every Lambda in the platform has the required safety modules wired.
Runs in CI Job 2 (test) alongside test_role_policies.py — no AWS credentials needed.

THREE categories of checks:

  W1  platform_logger   — ALL Lambdas must import get_logger (OBS-1)
  W2  ingestion_validator — ALL ingestion Lambdas must call validate_item/validate_and_write (DATA-2)
  W3  ai_output_validator — ALL email + AI-compute Lambdas must import validate_ai_output (AI-3)
  W4  causal language    — No prompt strings may use causal framing ("causes", "proves", etc.)

KNOWN GAPS (documented here; update this list as each gap is closed):
  These are currently unwired but tracked — they fail CI until fixed.
  Remove from the known-gap list when wired; the test will then enforce permanently.

Run with:   python3 -m pytest tests/test_wiring_coverage.py -v
Or directly: python3 tests/test_wiring_coverage.py

v1.0.0 — 2026-03-11
"""

import os
import re
import sys
import pytest

# ── Project root ─────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")


def _src(filename: str) -> str:
    path = os.path.join(LAMBDAS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _exists(filename: str) -> bool:
    return os.path.exists(os.path.join(LAMBDAS_DIR, filename))


# ══════════════════════════════════════════════════════════════════════════════
# Lambda categorisation
# Source of truth: ci/lambda_map.json — keep in sync if Lambdas are added.
# ══════════════════════════════════════════════════════════════════════════════

# Every deployable Lambda (filename only, relative to lambdas/)
ALL_LAMBDAS = [
    # Ingestion
    "strava_lambda.py", "whoop_lambda.py", "garmin_lambda.py",
    "eightsleep_lambda.py", "habitify_lambda.py", "withings_lambda.py",
    "todoist_lambda.py", "notion_lambda.py", "macrofactor_lambda.py",
    "apple_health_lambda.py", "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py", "weather_handler.py",
    "enrichment_lambda.py", "journal_enrichment_lambda.py",
    # Email
    "daily_brief_lambda.py", "weekly_digest_lambda.py", "monthly_digest_lambda.py",
    "nutrition_review_lambda.py", "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py", "monday_compass_lambda.py", "brittany_email_lambda.py",
    # AI-compute
    "anomaly_detector_lambda.py", "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py", "adaptive_mode_lambda.py",
    # Non-AI compute / operational
    "character_sheet_lambda.py", "daily_metrics_compute_lambda.py",
    "dashboard_refresh_lambda.py", "failure_pattern_compute_lambda.py",
    "freshness_checker_lambda.py", "insight_email_parser_lambda.py",
    "canary_lambda.py", "qa_smoke_lambda.py", "dlq_consumer_lambda.py",
    "key_rotator_lambda.py", "pip_audit_lambda.py",
    "data_export_lambda.py", "data_reconciliation_lambda.py",
]

# Ingestion Lambdas — must wire ingestion_validator (DATA-2)
INGESTION_LAMBDAS = [
    "strava_lambda.py", "whoop_lambda.py", "garmin_lambda.py",
    "eightsleep_lambda.py", "habitify_lambda.py", "withings_lambda.py",
    "todoist_lambda.py", "notion_lambda.py", "macrofactor_lambda.py",
    "apple_health_lambda.py", "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py", "weather_handler.py",
    "enrichment_lambda.py", "journal_enrichment_lambda.py",
]

# Email + AI-compute Lambdas — must wire ai_output_validator (AI-3)
AI_OUTPUT_LAMBDAS = [
    # Email
    "daily_brief_lambda.py", "weekly_digest_lambda.py", "monthly_digest_lambda.py",
    "nutrition_review_lambda.py", "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py", "monday_compass_lambda.py", "brittany_email_lambda.py",
    # AI-compute
    "anomaly_detector_lambda.py", "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py", "adaptive_mode_lambda.py",
]

# Lambdas with inline prompt strings (not sourced from ai_calls.py)
# These are scanned for causal language.  Add any new Lambda that builds
# its own prompt strings here.
PROMPT_LAMBDAS = [
    "weekly_digest_lambda.py", "monthly_digest_lambda.py",
    "nutrition_review_lambda.py", "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py", "monday_compass_lambda.py", "brittany_email_lambda.py",
    "anomaly_detector_lambda.py", "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py", "adaptive_mode_lambda.py",
    "ai_calls.py",  # The main prompt module — always checked
]

# ── Known gaps (update as each is closed) ────────────────────────────────────
# W1 platform_logger gaps:
W1_KNOWN_GAPS: set[str] = set()  # All Lambdas should have this — no known gaps

# W2 ingestion_validator gaps:
W2_KNOWN_GAPS: set[str] = {
    # Add filenames here if a Lambda is not yet wired (document the Jira ticket)
    # e.g. "garmin_lambda.py",  # DATA-2: garmin native-deps build required first
}

# W3 ai_output_validator gaps:
W3_KNOWN_GAPS: set[str] = set()  # All AI-output Lambdas wired as of v3.6.9


# ══════════════════════════════════════════════════════════════════════════════
# W1 — platform_logger wired in every Lambda
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("filename", sorted(ALL_LAMBDAS))
def test_w1_platform_logger_imported(filename):
    """W1: Every Lambda must import get_logger from platform_logger (OBS-1)."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in W1_KNOWN_GAPS:
        pytest.xfail(f"Known W1 gap: {filename} — see W1_KNOWN_GAPS")
    src = _src(filename)
    has_logger = (
        "from platform_logger import" in src
        or "platform_logger" in src
        or "get_logger(" in src
    )
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
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in W2_KNOWN_GAPS:
        pytest.xfail(f"Known W2 gap: {filename} — see W2_KNOWN_GAPS")
    src = _src(filename)
    has_validator = (
        "from ingestion_validator import" in src
        or "ingestion_validator" in src
        or "validate_item(" in src
        or "validate_and_write(" in src
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
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in W3_KNOWN_GAPS:
        pytest.xfail(f"Known W3 gap: {filename} — see W3_KNOWN_GAPS")
    src = _src(filename)
    # Valid wiring patterns:
    # (a) imports from ai_calls which has the middleware built in
    # (b) imports validate_ai_output directly
    # (c) standalone _HAS_AI_VALIDATOR pattern
    has_via_ai_calls   = "from ai_calls import" in src or "import ai_calls" in src
    has_direct         = "from ai_output_validator import" in src or "validate_ai_output" in src
    has_standalone     = "_HAS_AI_VALIDATOR" in src and "validate_ai_output" in src
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
    r'\bcauses\s+your\b',           # "causes your sleep to"
    r'\bproves\s+that\b',           # "proves that the pattern"
    r'\bbecause\s+your\b',          # "because your recovery"
    r'\bis\s+why\s+your\b',         # "is why your HRV"
    r'\bdirectly\s+causing\b',      # "directly causing fatigue"
    r'\bproven\s+to\s+cause\b',     # "proven to cause"
    r'\bcausally\s+linked\b',       # "causally linked to"
    r'\bthis\s+data\s+clearly\s+caus',  # "this data clearly causes"
]

# Lines containing these strings are allowlisted (meta-commentary about causal language)
_CAUSAL_ALLOWLIST = [
    "causal language",   # comments about the principle
    "correlative",       # already framing as correlation
    "not proven causal", # explicit caveat
    "correlation",       # already using correct framing
    "causal_chain",      # variable name (legacy, renamed)
    "causal →",          # ADR/doc reference
    "causal framing",    # meta-commentary
    "non-causal",
    "likely_connection",
    "# ",                # comment lines
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
        pytest.skip(f"{filename} not present in lambdas/")
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
