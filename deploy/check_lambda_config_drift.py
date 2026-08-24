#!/usr/bin/env python3
"""
deploy/check_lambda_config_drift.py — flag DEPLOYED Lambda config that has drifted
from the CDK source of truth (timeout / memory).

Born 2026-06-19: the ai-expert-analyzer timeout fix (120→600s) was committed to CDK
(#150) but `cdk deploy` was never run, so the live function kept timing out daily and
dumping to the ingestion DLQ — emailing a "DLQ permanent failure" alert every day for
days. The existing post_cdk_reconcile_smoke.sh checks *handler* drift but not
timeout/memory, so this whole class hid in plain sight. This closes that gap.

What it does (offline AST parse + one read-only AWS call per function):
  1. Walk cdk/stacks/*.py, find every create_platform_lambda(...) call, and read the
     effective timeout_seconds / memory_mb (explicit literal, else the helper defaults
     120s / 256MB).
  2. For each, fetch the live Lambda config and compare.
  3. Print a table of any drift; exit non-zero if drift is found (so CI / a nightly
     cron can gate on it).

Usage:
  python3 deploy/check_lambda_config_drift.py            # check all, exit 1 on drift
  python3 deploy/check_lambda_config_drift.py --json     # machine-readable

Only literal kwargs are compared; calls that compute timeout/memory from a variable are
listed as "unparseable" (informational, not a failure).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys

REGION = os.environ.get("AWS_REGION", "us-west-2")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")

# Stacks that deploy outside the home region (mirrors drift_sentinel.STACKS /
# cdk/app.py). Without this, every web_stack lambda (us-east-1, e.g.
# email-subscriber) reads as "NOT DEPLOYED" from a us-west-2 client — the false
# positive the 2026-07-26 sentinel sweep surfaced.
# backup_stack.py holds no Lambdas today, but the entry is required for parity with
# cdk/app.py (tests/test_drift_checker_stack_regions.py) — and if a restore-helper
# function is ever added there, it starts out checked against the right region.
STACK_FILE_REGION = {"web_stack.py": "us-east-1", "backup_stack.py": "us-east-2"}

# Mirrors cdk/stacks/lambda_helpers.py::create_platform_lambda defaults.
DEFAULT_TIMEOUT = 120
DEFAULT_MEMORY = 256


def _literal(node):
    """Return a literal int/str from an AST node, or None if not a literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return node.value
    return None


def parse_cdk_lambdas() -> tuple[list[dict], list[str]]:
    """AST-parse every create_platform_lambda(...) call in cdk/stacks/*.py.

    Returns (specs, unparseable) where specs = [{function_name, timeout, memory}].
    """
    specs: list[dict] = []
    unparseable: list[str] = []
    for fname in sorted(os.listdir(STACKS_DIR)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(STACKS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=fname)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
            if name != "create_platform_lambda":
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            function_name = _literal(kw.get("function_name"))
            if not isinstance(function_name, str):
                unparseable.append(f"{fname}:{getattr(node, 'lineno', '?')} (non-literal function_name)")
                continue
            timeout = DEFAULT_TIMEOUT
            memory = DEFAULT_MEMORY
            if "timeout_seconds" in kw:
                v = _literal(kw["timeout_seconds"])
                if v is None:
                    unparseable.append(f"{function_name} (non-literal timeout_seconds)")
                else:
                    timeout = v
            if "memory_mb" in kw:
                v = _literal(kw["memory_mb"])
                if v is None:
                    unparseable.append(f"{function_name} (non-literal memory_mb)")
                else:
                    memory = v
            specs.append(
                {
                    "function_name": function_name,
                    "timeout": timeout,
                    "memory": memory,
                    "region": STACK_FILE_REGION.get(fname, REGION),
                }
            )
    return specs, unparseable


def check(specs: list[dict]) -> list[dict]:
    """Compare each CDK spec to the live Lambda config. Returns drift records."""
    import boto3

    clients = {}
    drift = []
    for s in specs:
        fn = s["function_name"]
        region = s.get("region", REGION)
        if region not in clients:
            clients[region] = boto3.client("lambda", region_name=region)
        lam = clients[region]
        try:
            cfg = lam.get_function_configuration(FunctionName=fn)
        except lam.exceptions.ResourceNotFoundException:
            drift.append({**s, "live_timeout": None, "live_memory": None, "issue": "NOT DEPLOYED"})
            continue
        except Exception as e:  # noqa: BLE001 — surface any AWS error as drift-unknown, don't crash the sweep
            drift.append({**s, "live_timeout": None, "live_memory": None, "issue": f"read error: {e}"})
            continue
        lt, lm = cfg.get("Timeout"), cfg.get("MemorySize")
        issues = []
        if lt != s["timeout"]:
            issues.append(f"timeout cdk={s['timeout']}s live={lt}s")
        if lm != s["memory"]:
            issues.append(f"memory cdk={s['memory']}MB live={lm}MB")
        if issues:
            drift.append({**s, "live_timeout": lt, "live_memory": lm, "issue": "; ".join(issues)})
    return drift


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    specs, unparseable = parse_cdk_lambdas()
    drift = check(specs)

    if args.json:
        print(json.dumps({"checked": len(specs), "drift": drift, "unparseable": unparseable}, indent=2))
    else:
        # Honest scope: specs now span 2 regions (STACK_FILE_REGION, #1816) — a bare
        # "in {REGION}" claim using only the module-level default silently implied
        # single-region coverage even after web_stack's us-east-1 Lambdas joined the
        # spec set. Summarize the ACTUAL per-region breakdown instead.
        region_counts: dict[str, int] = {}
        for s in specs:
            r = s.get("region", REGION)
            region_counts[r] = region_counts.get(r, 0) + 1
        if not specs:
            print("Checked 0 CDK-defined Lambdas.")
        elif len(region_counts) == 1:
            (only_region,) = region_counts
            print(f"Checked {len(specs)} CDK-defined Lambdas in {only_region}.")
        else:
            breakdown = ", ".join(f"{count} {region}" for region, count in sorted(region_counts.items(), key=lambda kv: (-kv[1], kv[0])))
            print(f"Checked {len(specs)} CDK-defined Lambdas ({breakdown}).")
        if unparseable:
            print(f"\n(informational) {len(unparseable)} non-literal config(s), not compared:")
            for u in unparseable:
                print(f"  - {u}")
        if not drift:
            print("\n✅ No timeout/memory drift — deployed config matches CDK.")
        else:
            print(f"\n❌ {len(drift)} function(s) drifted from CDK:")
            for d in drift:
                print(f"  - {d['function_name']}: {d['issue']}")
            print("\nFix: run `cd cdk && npx cdk deploy <stack> --require-approval never`,")
            print("or for a single function: `aws lambda update-function-configuration --function-name <fn> ...`")

    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
