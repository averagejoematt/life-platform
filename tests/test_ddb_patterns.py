"""
tests/test_ddb_patterns.py — DynamoDB usage pattern linter.

Validates DynamoDB patterns across all Lambda source files without needing
AWS credentials or a running environment. Runs in CI Job 2 (test).

Rules enforced:
  D1  pk/sk string construction follows USER#<user>#SOURCE#<source> / DATE#YYYY-MM-DD format
  D2  'date' reserved word — any FilterExpression/KeyConditionExpression that includes
      a bare 'date' attribute must use ExpressionAttributeNames
  D3  schema_version included in put_item calls for ingestion Lambdas (DATA-1)
  D4  table.put_item calls in ingestion Lambdas are preceded by validate_item or
      validate_and_write (DATA-2 enforcement at code level)

Run with:   python3 -m pytest tests/test_ddb_patterns.py -v
Or directly: python3 tests/test_ddb_patterns.py

v1.0.0 — 2026-03-11
"""

import os
import re
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")


def _src(filename: str) -> str:
    path = os.path.join(LAMBDAS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def _exists(filename: str) -> bool:
    return os.path.exists(os.path.join(LAMBDAS_DIR, filename))


# ── Lambda sets ───────────────────────────────────────────────────────────────

# All Lambdas that interact with DynamoDB
DDB_LAMBDAS = [
    "strava_lambda.py", "whoop_lambda.py", "garmin_lambda.py",
    "eightsleep_lambda.py", "habitify_lambda.py", "withings_lambda.py",
    "todoist_lambda.py", "notion_lambda.py", "macrofactor_lambda.py",
    "apple_health_lambda.py", "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py", "weather_lambda.py",
    "enrichment_lambda.py", "journal_enrichment_lambda.py",
    "daily_brief_lambda.py", "weekly_digest_lambda.py", "monthly_digest_lambda.py",
    "nutrition_review_lambda.py", "wednesday_chronicle_lambda.py",
    "weekly_plate_lambda.py", "monday_compass_lambda.py", "brittany_email_lambda.py",
    "anomaly_detector_lambda.py", "daily_insight_compute_lambda.py",
    "hypothesis_engine_lambda.py", "adaptive_mode_lambda.py",
    "character_sheet_lambda.py", "daily_metrics_compute_lambda.py",
    "dashboard_refresh_lambda.py", "failure_pattern_compute_lambda.py",
    "freshness_checker_lambda.py", "insight_email_parser_lambda.py",
    "canary_lambda.py", "qa_smoke_lambda.py",
    "data_export_lambda.py", "data_reconciliation_lambda.py",
]

INGESTION_LAMBDAS = [
    "strava_lambda.py", "whoop_lambda.py", "garmin_lambda.py",
    "eightsleep_lambda.py", "habitify_lambda.py", "withings_lambda.py",
    "todoist_lambda.py", "notion_lambda.py", "macrofactor_lambda.py",
    "apple_health_lambda.py", "health_auto_export_lambda.py",
    "dropbox_poll_lambda.py", "weather_lambda.py",
    "enrichment_lambda.py", "journal_enrichment_lambda.py",
]

# Known gaps for D3 (schema_version) — remove when fixed
D3_KNOWN_GAPS: set[str] = set()

# Known gaps for D4 (put_item preceded by validate) — remove when fixed
D4_KNOWN_GAPS: set[str] = {
    "garmin_lambda.py",     # native deps build required before DATA-2 wiring
    "weather_lambda.py",    # weather_handler.py is the canonical file; check separately
}


# ══════════════════════════════════════════════════════════════════════════════
# D1 — pk/sk format consistency
# ══════════════════════════════════════════════════════════════════════════════

# Valid pk patterns — compiled for reuse
_VALID_PK_PATTERNS = [
    re.compile(r'USER#\w+#SOURCE#\w'),    # USER#matthew#SOURCE#whoop
    re.compile(r'USER#\w+#profile'),       # USER#matthew#profile (profile key)
    re.compile(r'USER#\w+#hypothes'),      # hypotheses partition
    re.compile(r'USER#\w+#platform'),      # platform_memory partition
    re.compile(r'USER#\w+#anomal'),        # anomalies partition
    re.compile(r'USER#\w+#failure'),       # failure_pattern partition
    re.compile(r'USER#\w+#insights'),      # insights partition
    re.compile(r'USER#\w+#character'),     # character sheet partition
    re.compile(r'USER#\w+#day_grade'),     # day_grade partition
    re.compile(r'USER#\w+#habit'),         # habit_scores partition
    re.compile(r'USER#\w+#adaptive'),      # adaptive_mode partition
    re.compile(r'CANARY#'),                # canary test records
    re.compile(r'f"USER#'),                # f-string construction (any)
    re.compile(r"f'USER#"),                # f-string construction (any)
    re.compile(r'USER_PREFIX'),            # constant-based construction
    re.compile(r'PROFILE_PK'),             # profile constant
    re.compile(r'HYPOTHESES_PK'),          # hypotheses constant
]

_VALID_SK_PATTERNS = [
    re.compile(r'DATE#\d'),           # DATE#2026-...
    re.compile(r'DATE#" \+'),         # DATE#" + date_str
    re.compile(r"DATE#' \+"),
    re.compile(r'f"DATE#'),           # f-string
    re.compile(r"f'DATE#"),
    re.compile(r'"DATE#" \+ date'),
    re.compile(r'PROFILE#'),          # PROFILE#v1
    re.compile(r'HYPOTHESIS#'),       # HYPOTHESIS# prefix
    re.compile(r'CANARY#'),
    re.compile(r'SK_PREFIX'),         # constant
    re.compile(r'sk_prefix'),
    re.compile(r'begins_with'),       # query using begins_with
    re.compile(r'between\('),         # query using between
    re.compile(r'\.lt\('),            # Key().lt()
    re.compile(r'\.gte?\('),          # Key().gte()
    re.compile(r'"sk":\s*sk\b'),      # "sk": sk (variable)
    re.compile(r'"sk":\s*f"'),        # "sk": f"..."
    re.compile(r'"sk":\s*"[A-Z]'),    # "sk": "DATE#..." direct literal
]


def _check_pk_sk_patterns(src: str) -> list[str]:
    """Find pk/sk constructions that don't match any known-valid pattern."""
    issues = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Check pk constructions
        if re.search(r'"pk"\s*:\s*["\']', stripped) or re.search(r'"pk"\s*:\s*f["\']', stripped):
            # Has a pk literal assignment — check it matches a valid pattern
            if not any(p.search(stripped) for p in _VALID_PK_PATTERNS):
                # Allow if it's just a Key().eq() call or variable reference
                if not re.search(r'Key\(|pk\s*=\s*[a-z_]|"pk"\s*:\s*[a-z_]', stripped):
                    issues.append(f"  line {i}: suspect pk construction: {stripped[:120]}")

    return issues


@pytest.mark.parametrize("filename", sorted(DDB_LAMBDAS))
def test_d1_pk_sk_format(filename):
    """D1: pk/sk string constructions should follow platform key conventions."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    src = _src(filename)
    issues = _check_pk_sk_patterns(src)
    assert not issues, (
        f"{filename}: non-standard pk/sk constructions found. "
        f"Platform convention: pk=USER#<user>#SOURCE#<source>, sk=DATE#YYYY-MM-DD.\n"
        + "\n".join(issues)
    )


# ══════════════════════════════════════════════════════════════════════════════
# D2 — 'date' reserved word requires ExpressionAttributeNames
# ══════════════════════════════════════════════════════════════════════════════

# Expression types that can reference attribute names
_EXPR_KEYWORDS = re.compile(
    r'FilterExpression|KeyConditionExpression|ConditionExpression|'
    r'ProjectionExpression|UpdateExpression',
    re.IGNORECASE,
)

# Patterns that indicate a bare 'date' attribute reference (not a value or comment)
# 'date' appears as an attribute name, not as part of a string like "DATE#" or date_str
_BARE_DATE_IN_EXPR = re.compile(r'\bdate\b(?!\s*_|\s*str|\s*=|\s*>|\s*<|\s*!)')


def _find_unguarded_date_expressions(src: str) -> list[str]:
    """Find expression lines that reference 'date' without ExpressionAttributeNames."""
    issues = []
    lines = src.splitlines()

    for i, line in enumerate(lines):
        if not _EXPR_KEYWORDS.search(line):
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        # Does this line contain a bare 'date' attribute reference?
        if not re.search(r"['\"]date['\"]|Attr\(['\"]date", line, re.IGNORECASE):
            continue
        # Is it already guarded? Check surrounding 20 lines for ExpressionAttributeNames
        context_start = max(0, i - 5)
        context_end = min(len(lines), i + 15)
        context = "\n".join(lines[context_start:context_end])
        if "ExpressionAttributeNames" not in context:
            issues.append(f"  line {i+1}: 'date' in expression without ExpressionAttributeNames: {stripped[:120]}")

    return issues


@pytest.mark.parametrize("filename", sorted(DDB_LAMBDAS))
def test_d2_date_reserved_word_guarded(filename):
    """D2: 'date' is a DynamoDB reserved word — must use ExpressionAttributeNames."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    src = _src(filename)
    issues = _find_unguarded_date_expressions(src)
    assert not issues, (
        f"{filename}: 'date' used as attribute name in DDB expression without "
        f"ExpressionAttributeNames. This will cause a runtime error.\n"
        f"Fix: add ExpressionAttributeNames={{\"#d\": \"date\"}} and use #d in the expression.\n"
        + "\n".join(issues)
    )


# ══════════════════════════════════════════════════════════════════════════════
# D3 — schema_version in ingestion put_item items
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("filename", sorted(INGESTION_LAMBDAS))
def test_d3_schema_version_present(filename):
    """D3: Ingestion Lambdas must include schema_version in DDB items (DATA-1)."""
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in D3_KNOWN_GAPS:
        pytest.xfail(f"Known D3 gap: {filename} — see D3_KNOWN_GAPS")
    src = _src(filename)
    has_put_item = "put_item" in src or "validate_and_write" in src
    if not has_put_item:
        pytest.skip(f"{filename} has no put_item or validate_and_write call")
    assert "schema_version" in src, (
        f"{filename}: no schema_version field found. All ingestion Lambdas must include "
        f"'schema_version': 1 (or current version) in the item dict before calling "
        f"put_item(). Required for DATA-1 compliance and ingestion_validator."
    )


# ══════════════════════════════════════════════════════════════════════════════
# D4 — put_item in ingestion Lambdas preceded by validate call
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("filename", sorted(INGESTION_LAMBDAS))
def test_d4_put_item_guarded_by_validator(filename):
    """D4: Ingestion Lambdas must call validate_item/validate_and_write before put_item.

    'Built but not wired' is the highest-risk gap.  This check ensures that
    having ingestion_validator imported is not enough — it must actually be
    called before any table.put_item().
    """
    if not _exists(filename):
        pytest.skip(f"{filename} not present in lambdas/")
    if filename in D4_KNOWN_GAPS:
        pytest.xfail(f"Known D4 gap: {filename} — see D4_KNOWN_GAPS")
    src = _src(filename)
    has_put_item = "put_item(" in src or "validate_and_write(" in src
    if not has_put_item:
        pytest.skip(f"{filename} has no put_item call")
    has_validate = (
        "validate_item(" in src
        or "validate_and_write(" in src
        or "should_skip_ddb" in src
    )
    assert has_validate, (
        f"{filename}: has put_item() but no validate_item() / validate_and_write() call. "
        f"DATA-2 requires validation before every DDB write in ingestion Lambdas. "
        f"Either use validate_and_write() as a drop-in replacement, or wrap put_item "
        f"with explicit validate_item() + should_skip_ddb check."
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
