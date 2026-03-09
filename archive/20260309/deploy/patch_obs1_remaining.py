#!/usr/bin/env python3
"""
OBS-1 patch: Add platform_logger structured logging to 17 remaining Lambda files.

Run from project root:
  python3 deploy/patch_obs1_remaining.py

Applies two changes per file:
  1. Replace basic logging setup with try/except get_logger() pattern
  2. Add logger.set_date() or logger.set_correlation_id() at top of lambda_handler
"""

import re
import os
import sys

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")

# (filename, source_name, use_set_date)
# use_set_date=False → set_correlation_id (non-date-based Lambdas)
FILES = [
    ("apple_health_lambda.py",          "apple-health",            True),
    ("character_sheet_lambda.py",       "character-sheet-compute", True),
    ("daily_insight_compute_lambda.py", "daily-insight-compute",   True),
    ("daily_metrics_compute_lambda.py", "daily-metrics-compute",   True),
    ("dashboard_refresh_lambda.py",     "dashboard-refresh",       True),
    ("data_export_lambda.py",           "data-export",             True),
    ("data_reconciliation_lambda.py",   "data-reconciliation",     True),
    ("dlq_consumer_lambda.py",          "dlq-consumer",            False),
    ("dropbox_poll_lambda.py",          "dropbox-poll",            True),
    ("freshness_checker_lambda.py",     "freshness-checker",       True),
    ("hypothesis_engine_lambda.py",     "hypothesis-engine",       True),
    ("canary_lambda.py",                "canary",                  False),
    ("adaptive_mode_lambda.py",         "adaptive-mode-compute",   True),
    ("insight_email_parser_lambda.py",  "insight-email-parser",    True),
    ("key_rotator_lambda.py",           "key-rotator",             False),
    ("pip_audit_lambda.py",             "pip-audit",               False),
    ("qa_smoke_lambda.py",              "qa-smoke",                True),
]

OBS1_BLOCK = """\
# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("{source}")
except ImportError:
    logger = logging.getLogger("{source}")
    logger.setLevel(logging.INFO)\
"""


def patch_file(path, source_name, use_set_date):
    with open(path, "r") as f:
        content = f.read()

    original = content
    obs1_block = OBS1_BLOCK.format(source=source_name)

    # ── Step 1: Replace logger setup ─────────────────────────────────────────

    # Pattern A: logger = logging.getLogger(<anything>) + logger.setLevel(logging.INFO)
    pattern_a = re.compile(
        r'logger = logging\.getLogger\([^)]*\)\s*\nlogger\.setLevel\(logging\.INFO\)'
    )
    if pattern_a.search(content):
        content = pattern_a.sub(obs1_block, content, count=1)
    else:
        # Pattern B: no logger at all — add import logging + block after imports
        # Find the end of the import block (last import/from line)
        last_import_end = 0
        for m in re.finditer(r'^(?:import|from)\b[^\n]+\n', content, re.MULTILINE):
            last_import_end = m.end()

        if last_import_end == 0:
            print(f"  [WARN] Could not find import section — skipping logger block")
        else:
            insert = ''
            if 'import logging' not in content:
                insert += 'import logging\n'
            insert += '\n' + obs1_block + '\n'
            content = content[:last_import_end] + insert + content[last_import_end:]

    # ── Step 2: Add set_date / set_correlation_id inside lambda_handler ──────

    if use_set_date:
        obs1_call = '    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1\n'
    else:
        obs1_call = '    logger.set_correlation_id(context.aws_request_id if context else "unknown")  # OBS-1\n'

    # Only insert if not already present
    if '# OBS-1' not in content:
        handler_match = re.search(r'def lambda_handler\(event, context\):\n', content)
        if handler_match:
            insert_pos = handler_match.end()
            content = content[:insert_pos] + obs1_call + content[insert_pos:]
        else:
            print(f"  [WARN] Could not find lambda_handler")

    if content == original:
        print(f"  [SKIP] No changes needed")
        return False

    with open(path, "w") as f:
        f.write(content)
    return True


def main():
    changed = 0
    skipped = 0
    errors = 0

    for filename, source_name, use_set_date in FILES:
        path = os.path.join(LAMBDAS_DIR, filename)
        if not os.path.exists(path):
            print(f"  [MISS] File not found: {filename}")
            errors += 1
            continue

        print(f"Patching {filename} (source='{source_name}', set_date={use_set_date})")
        try:
            ok = patch_file(path, source_name, use_set_date)
            if ok:
                changed += 1
                print(f"  ✓ Done")
            else:
                skipped += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback; traceback.print_exc()
            errors += 1

    print(f"\nSummary: {changed} patched, {skipped} skipped (already done), {errors} errors")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
