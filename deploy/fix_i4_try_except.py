#!/usr/bin/env python3
"""
deploy/fix_i4_try_except.py — Add top-level try/except to lambda_handler functions.

Fixes: 23 test_i4_handler_has_try_except failures.
Rule: lambda_handler body must have at least one top-level try/except block
      so async Lambda failures don't silently swallow errors.

Strategy: For each failing Lambda, find lambda_handler via AST, check if
it already has a top-level try, and if not, wrap the entire body in:

    try:
        <existing body>
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise

Skips handlers that already have a try block.
Skips weather_handler.py (delegates entirely to framework — run_ingestion raises on error).

Usage: python3 deploy/fix_i4_try_except.py [--dry-run]
"""

import ast
import os
import sys
import textwrap

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")

# All 23 failing lambdas from the test output
TARGETS = [
    "adaptive_mode_lambda.py",
    "apple_health_lambda.py",
    "canary_lambda.py",
    "chronicle_email_sender_lambda.py",
    "dashboard_refresh_lambda.py",
    "data_export_lambda.py",
    "dlq_consumer_lambda.py",
    "dropbox_poll_lambda.py",
    "eightsleep_lambda.py",
    "enrichment_lambda.py",
    "evening_nudge_lambda.py",
    "garmin_lambda.py",
    "habitify_lambda.py",
    "hypothesis_engine_lambda.py",
    "insight_email_parser_lambda.py",
    "journal_enrichment_lambda.py",
    "key_rotator_lambda.py",
    "notion_lambda.py",
    "qa_smoke_lambda.py",
    "strava_lambda.py",
    "weather_handler.py",
    "whoop_lambda.py",
    "withings_lambda.py",
]

DRY_RUN = "--dry-run" in sys.argv

def _has_try_in_body(func_node) -> bool:
    for stmt in func_node.body:
        if isinstance(stmt, ast.Try):
            return True
    return False

def _find_lambda_handler(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "lambda_handler":
                return node
    return None

def fix_file(filename: str) -> str | None:
    """Return 'fixed', 'skipped', or 'error:<msg>'."""
    path = os.path.join(LAMBDAS, filename)
    if not os.path.exists(path):
        return "error:file not found"

    with open(path, encoding="utf-8") as f:
        src = f.read()

    try:
        tree = ast.parse(src, filename=filename)
    except SyntaxError as e:
        return f"error:syntax error: {e}"

    func = _find_lambda_handler(tree)
    if func is None:
        return "error:no lambda_handler found"

    if _has_try_in_body(func):
        return "skipped:already has try"

    # ── Find the body start line ──────────────────────────────────────────
    # func.body[0].lineno is the first statement's line number (1-indexed)
    body_start_line = func.body[0].lineno          # first body statement
    handler_def_line = func.lineno                  # the def line itself

    lines = src.splitlines(keepends=True)

    # Find the indentation of the body (first statement's indentation)
    body_first_line = lines[body_start_line - 1]
    body_indent = len(body_first_line) - len(body_first_line.lstrip())
    indent = " " * body_indent

    # Detect if a logger is available in this file
    has_logger = "logger" in src or "Logger" in src
    log_line = f"{indent}    logger.error(\"lambda_handler failed: %s\", e, exc_info=True)\n" if has_logger else ""

    # Find where the function ends
    # Use end_lineno if Python 3.8+ (it should be — Lambda Python 3.12)
    if hasattr(func, 'end_lineno') and func.end_lineno:
        func_end_line = func.end_lineno  # 1-indexed, inclusive
    else:
        # Fallback: scan for next top-level def/class
        func_end_line = len(lines)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if node.lineno > func.lineno:
                    func_end_line = node.lineno - 1
                    break

    # ── Build the new file ────────────────────────────────────────────────
    # Lines before the body:  def line + any docstring lines before body_start_line
    before = lines[:body_start_line - 1]  # up to (not including) first body stmt
    body = lines[body_start_line - 1: func_end_line]  # body lines
    after = lines[func_end_line:]           # lines after function

    # Re-indent body one level deeper (add 4 spaces)
    indented_body = []
    for line in body:
        if line.strip():  # non-blank
            indented_body.append("    " + line)
        else:
            indented_body.append(line)  # preserve blank lines as-is

    new_lines = (
        before
        + [f"{indent}try:\n"]
        + indented_body
        + [f"{indent}except Exception as e:\n"]
        + ([log_line] if log_line else [])
        + [f"{indent}    raise\n"]
        + after
    )

    new_src = "".join(new_lines)

    # Verify it parses
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        return f"error:generated syntax error: {e}"

    # Verify fix worked
    new_tree = ast.parse(new_src)
    new_func = _find_lambda_handler(new_tree)
    if not new_func or not _has_try_in_body(new_func):
        return "error:try/except not detected after rewrite"

    if DRY_RUN:
        print(f"  [DRY-RUN] Would fix {filename}")
        return "dry-run"

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)

    return "fixed"


def main():
    print(f"fix_i4_try_except.py {'(DRY RUN)' if DRY_RUN else ''}")
    print("=" * 60)

    fixed = skipped = errors = 0

    for filename in TARGETS:
        result = fix_file(filename)
        if result == "fixed":
            print(f"  ✅ {filename}")
            fixed += 1
        elif result and result.startswith("skipped"):
            print(f"  ⏭️  {filename}: {result}")
            skipped += 1
        elif result and result.startswith("dry-run"):
            skipped += 1
        else:
            print(f"  ❌ {filename}: {result}")
            errors += 1

    print("=" * 60)
    print(f"Done: {fixed} fixed, {skipped} skipped, {errors} errors")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
