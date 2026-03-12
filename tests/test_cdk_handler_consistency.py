#!/usr/bin/env python3
"""
tests/test_cdk_handler_consistency.py — CDK handler/source consistency linter.

Prevents the class of bug from 2026-03-12 where CDK reconcile overwrote
live Lambda handler configs to values that didn't match the actual source files.

Root cause: operational_stack.py had handler="lambda_function.lambda_handler"
for three Lambdas whose source files were freshness_checker_lambda.py,
key_rotator_lambda.py, and insight_email_parser_lambda.py. CDK reconcile
"fixed" the live handlers to match this wrong value, breaking all three.

Validates (all offline — no AWS credentials needed):
  H1  Every handler= string in CDK stacks references a source_file= on the same call
  H2  Every source_file= in CDK stacks exists in lambdas/
  H3  The handler module name matches the source_file basename
      e.g. handler="freshness_checker_lambda.lambda_handler" → expects
           source_file contains "freshness_checker_lambda.py"
  H4  Every source file referenced defines def lambda_handler
  H5  No CDK stack references lambda_function.lambda_handler
      (generic placeholder never actually exists in this codebase)

Run:  python3 -m pytest tests/test_cdk_handler_consistency.py -v
      python3 tests/test_cdk_handler_consistency.py  (standalone)

v1.0.0 — 2026-03-12 (born from P0 alarm flood)
"""

import ast
import os
import re
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _stack_files():
    return [
        os.path.join(CDK_STACKS_DIR, f)
        for f in os.listdir(CDK_STACKS_DIR)
        if f.endswith(".py") and not f.startswith("__")
    ]


def _extract_create_lambda_calls(src):
    """
    Extract (handler, source_file) pairs from create_platform_lambda calls
    and inline _lambda.Function() calls in CDK stack source.

    Returns list of dicts: {handler, source_file, line, stack_file}
    """
    results = []

    # Find all handler="..." values
    handler_matches = list(re.finditer(r'handler\s*=\s*["\']([^"\']+)["\']', src))
    source_matches = list(re.finditer(r'source_file\s*=\s*["\']([^"\']+)["\']', src))

    for hm in handler_matches:
        handler_val = hm.group(1)
        handler_pos = hm.start()
        handler_line = src[:handler_pos].count('\n') + 1

        # Check surrounding context (±400 chars back) for noqa annotation
        context = src[max(0, handler_pos - 400):handler_pos + 200]
        if 'noqa: CDK_HANDLER_ORPHAN' in context:
            continue

        # Find the nearest source_file= within ±30 lines (≈±1500 chars)
        nearby_sources = [
            sm for sm in source_matches
            if abs(sm.start() - handler_pos) < 1500
        ]
        if not nearby_sources:
            # No source_file nearby — skip (inline _lambda.Function without source_file=)
            continue
        # Pick the closest one
        closest_src = min(nearby_sources, key=lambda sm: abs(sm.start() - handler_pos))
        source_val = closest_src.group(1)
        results.append({
            "handler": handler_val,
            "source_file": source_val,
            "line": handler_line,
        })

    return results


def _all_cdk_pairs():
    """Return all (handler, source_file, line, stack_filename) across all CDK stacks."""
    pairs = []
    for stack_path in _stack_files():
        src = _read(stack_path)
        stack_name = os.path.basename(stack_path)
        for pair in _extract_create_lambda_calls(src):
            pair["stack"] = stack_name
            pairs.append(pair)
    return pairs


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_h1_handler_and_source_always_paired():
    """H1: Every handler= in CDK stacks has a nearby source_file=."""
    failures = []
    for stack_path in _stack_files():
        src = _read(stack_path)
        stack_name = os.path.basename(stack_path)
        handler_matches = list(re.finditer(r'handler\s*=\s*["\']([^"\']+)["\']', src))
        source_matches = list(re.finditer(r'source_file\s*=\s*["\']([^"\']+)["\']', src))

        for hm in handler_matches:
            handler_val = hm.group(1)
            handler_pos = hm.start()
            handler_line = src[:handler_pos].count('\n') + 1

            # Skip noqa-annotated orphans
            context = src[max(0, handler_pos - 400):handler_pos + 200]
            if 'noqa: CDK_HANDLER_ORPHAN' in context:
                continue

            nearby = [sm for sm in source_matches if abs(sm.start() - handler_pos) < 1500]
            if not nearby:
                failures.append(
                    f"{stack_name}:{handler_line} — handler='{handler_val}' has no nearby source_file= "
                    f"(within 30 lines). If this is an inline _lambda.Function, add a comment # noqa: CDK_HANDLER_ORPHAN"
                )

    assert not failures, (
        f"H1 FAIL: {len(failures)} handler(s) without source_file:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_h2_all_source_files_exist():
    """H2: Every source_file= in CDK stacks must exist in lambdas/."""
    failures = []
    for stack_path in _stack_files():
        src = _read(stack_path)
        stack_name = os.path.basename(stack_path)
        for m in re.finditer(r'source_file\s*=\s*["\']([^"\']+)["\']', src):
            source_val = m.group(1)
            line = src[:m.start()].count('\n') + 1
            full_path = os.path.join(ROOT, source_val)
            if not os.path.exists(full_path):
                failures.append(f"{stack_name}:{line} — source_file='{source_val}' does not exist")

    assert not failures, (
        f"H2 FAIL: {len(failures)} source_file(s) don't exist on disk:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_h3_handler_module_matches_source_file():
    """H3: handler module name must match source_file basename.

    handler='freshness_checker_lambda.lambda_handler'
        → module = 'freshness_checker_lambda'
        → source_file must contain 'freshness_checker_lambda.py'
    """
    failures = []
    for pair in _all_cdk_pairs():
        handler = pair["handler"]
        source_file = pair["source_file"]
        handler_module = handler.rsplit(".", 1)[0]
        source_basename = os.path.basename(source_file).replace(".py", "")
        if handler_module != source_basename:
            failures.append(
                f"{pair['stack']}:{pair['line']} — "
                f"handler module '{handler_module}' != source_file basename '{source_basename}'\n"
                f"    handler='{handler}'\n"
                f"    source_file='{source_file}'\n"
                f"    Fix: handler should be '{source_basename}.lambda_handler'"
            )

    assert not failures, (
        f"H3 FAIL: {len(failures)} handler/source_file mismatch(es) — "
        f"this is exactly the bug that caused the 2026-03-12 P0:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_h4_all_source_files_define_lambda_handler():
    """H4: Every source file referenced in CDK stacks must define def lambda_handler."""
    failures = []
    checked = set()
    for pair in _all_cdk_pairs():
        source_file = pair["source_file"]
        full_path = os.path.join(ROOT, source_file)
        if full_path in checked or not os.path.exists(full_path):
            continue
        checked.add(full_path)

        src = _read(full_path)
        if not re.search(r'^def lambda_handler', src, re.MULTILINE):
            failures.append(
                f"{pair['stack']}:{pair['line']} — {source_file} has no 'def lambda_handler' function"
            )

    assert not failures, (
        f"H4 FAIL: {len(failures)} Lambda source file(s) missing def lambda_handler:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_h5_no_generic_lambda_function_handler():
    """H5: No CDK stack should reference 'lambda_function.lambda_handler'.

    This is the generic placeholder name that was incorrectly committed to
    operational_stack.py. No Lambda in this codebase is named lambda_function.py.
    If you see this, you have the 2026-03-12 bug.
    """
    failures = []
    for stack_path in _stack_files():
        src = _read(stack_path)
        stack_name = os.path.basename(stack_path)
        for m in re.finditer(r'handler\s*=\s*["\']lambda_function\.lambda_handler["\']', src):
            line = src[:m.start()].count('\n') + 1
            failures.append(
                f"{stack_name}:{line} — handler='lambda_function.lambda_handler' is a generic "
                f"placeholder. Replace with the actual module name.\n"
                f"    e.g. handler='my_lambda.lambda_handler' for source lambdas/my_lambda.py"
            )

    assert not failures, (
        f"H5 FAIL: {len(failures)} 'lambda_function.lambda_handler' reference(s) found — "
        f"this is the root cause of the 2026-03-12 P0 alarm flood:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
