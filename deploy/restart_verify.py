#!/usr/bin/env python3
"""
restart_verify.py — Post-pivot health check. Run this Monday morning (or any
time) to confirm the restart pipeline produced a healthy, consistent state.

Checks (each pass/fail):
  1. lambdas/constants.py genesis matches config/user_goals.json
  2. CDK SHARED_LAYER_VERSION matches the latest published AWS layer
  3. DDB PROFILE#v1 matches lambdas/constants.py baseline
  4. Live /api/journey returns started_date == genesis
  5. Live /api/journey returns start_weight == baseline (rounded)
  6. day_n(today) is >= 1 (we are at or past genesis)
  7. Withings record exists for genesis date
  8. Character sheet exists for at least one post-genesis day
  9. No habit streak > day_n (would indicate leak from pre-genesis data)
 10. pytest layer-consistency tests pass (i2, lv1-6)

Returns 0 if all checks pass, 1 if any fail.

Usage:
    python3 deploy/restart_verify.py
"""
import json
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_START_DATE,
    day_n,
)

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
LAYER = "life-platform-shared-utils"
API = "https://averagejoematt.com"

PASS = "\033[32m✓\033[0m"  # noqa: S105 — ANSI green-checkmark constant, not a secret
FAIL = "\033[31m✗\033[0m"


checks = []  # list of (name, passed, detail)


def check(name: str, ok: bool, detail: str = ""):
    checks.append((name, ok, detail))
    icon = PASS if ok else FAIL
    print(f"  {icon}  {name}{('  — ' + detail) if detail else ''}")


def main():
    print(f"\nrestart_verify — checking pipeline state against genesis={EXPERIMENT_START_DATE}\n")

    # 1. constants ↔ config consistency
    cfg = json.loads((REPO_ROOT / "config" / "user_goals.json").read_text())
    cfg_start = cfg["timeline"]["start_date"]
    cfg_w = float(cfg["timeline"]["start_weight_lbs"])
    check(
        "constants.py genesis matches config", cfg_start == EXPERIMENT_START_DATE, f"config={cfg_start} constants={EXPERIMENT_START_DATE}"
    )
    check(
        "constants.py baseline matches config",
        abs(cfg_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 0.01,
        f"config={cfg_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
    )

    # 2. layer version
    lam = boto3.client("lambda", region_name=REGION)
    versions = lam.list_layer_versions(LayerName=LAYER)["LayerVersions"]
    aws_latest = versions[0]["Version"]
    cdk_text = (REPO_ROOT / "cdk" / "stacks" / "constants.py").read_text()
    import re

    m = re.search(r"SHARED_LAYER_VERSION = (\d+)", cdk_text)
    cdk_v = int(m.group(1)) if m else None
    check("CDK SHARED_LAYER_VERSION matches AWS latest", cdk_v == aws_latest, f"cdk={cdk_v} aws={aws_latest}")

    # 3. DDB profile consistency
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    p = t.get_item(Key={"pk": f"USER#{USER}", "sk": "PROFILE#v1"}).get("Item", {})
    profile_date = p.get("journey_start_date", "")
    profile_w = float(p.get("journey_start_weight_lbs", 0))
    check("DDB profile date matches genesis", profile_date == EXPERIMENT_START_DATE, f"profile={profile_date}")
    check(
        "DDB profile weight matches baseline",
        abs(profile_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 0.01,
        f"profile={profile_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
    )

    # 4 + 5. Live /api/journey
    try:
        with urllib.request.urlopen(f"{API}/api/journey?cb=verify", timeout=10) as r:
            j = json.loads(r.read())["journey"]
        check("/api/journey started_date matches genesis", j.get("started_date") == EXPERIMENT_START_DATE, f"api={j.get('started_date')}")
        api_w = float(j.get("start_weight_lbs") or 0)
        check(
            "/api/journey start_weight matches baseline",
            abs(api_w - EXPERIMENT_BASELINE_WEIGHT_LBS) < 1.5,
            f"api={api_w} constants={EXPERIMENT_BASELINE_WEIGHT_LBS}",
        )
    except Exception as e:
        check("/api/journey reachable", False, f"error: {e}")

    # 6. day_n
    today = date.today().isoformat()
    d = day_n(today)
    check("day_n(today) >= 1 (past genesis)", d >= 1, f"day_n({today}) = {d}")

    # 7. Withings record for genesis
    w_record = t.get_item(Key={"pk": f"USER#{USER}#SOURCE#withings", "sk": f"DATE#{EXPERIMENT_START_DATE}"}).get("Item")
    check(
        f"Withings record exists for genesis ({EXPERIMENT_START_DATE})",
        w_record is not None,
        f"weight_lbs={w_record.get('weight_lbs') if w_record else '(missing)'}",
    )

    # 8. Post-genesis character sheet exists
    cs = t.query(
        KeyConditionExpression="pk = :p AND sk >= :s",
        ExpressionAttributeValues={
            ":p": f"USER#{USER}#SOURCE#character_sheet",
            ":s": f"DATE#{EXPERIMENT_START_DATE}",
        },
    )
    fresh_sheets = [it for it in cs.get("Items", []) if not it.get("tombstone")]
    check(
        "At least 1 post-genesis character sheet exists (untombstoned)", len(fresh_sheets) >= 1, f"found {len(fresh_sheets)} fresh sheet(s)"
    )

    # 9. No habit streak > day_n (would be a pre-genesis leak)
    # Quick check via DDB rather than MCP (avoids MCP scope issues).
    hs = t.query(
        KeyConditionExpression="pk = :p AND sk >= :s",
        ExpressionAttributeValues={
            ":p": f"USER#{USER}#SOURCE#habit_scores",
            ":s": f"DATE#{EXPERIMENT_START_DATE}",
        },
    )
    fresh_habits = [it for it in hs.get("Items", []) if not it.get("tombstone")]
    max_streak = 0
    for h in fresh_habits:
        for k, v in h.items():
            if isinstance(v, dict) and "streak" in str(k).lower():
                continue
            if "streak" in str(k).lower() and isinstance(v, (int, float)) and v > max_streak:
                max_streak = int(v)
    check("No habit streak > day_n (no pre-genesis leak)", max_streak <= max(d, 1), f"max_streak_in_habit_scores={max_streak} day_n={d}")

    # 10. Layer-consistency pytest
    proc = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "tests/test_integration_aws.py::test_i2_lambda_layer_version_current",
            "tests/test_layer_version_consistency.py",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    pytest_ok = proc.returncode == 0
    check("pytest layer-consistency tests pass", pytest_ok, proc.stdout.strip().splitlines()[-1] if proc.stdout else "no output")

    # Summary
    total = len(checks)
    passed = sum(1 for _, ok, _ in checks if ok)
    failed = total - passed
    print("\n══ summary ══")
    print(f"  {passed}/{total} checks passed")
    if failed:
        print("\nFailures:")
        for name, ok, detail in checks:
            if not ok:
                print(f"  ✗  {name}  — {detail}")
        sys.exit(1)
    print(f"\n  GENESIS = {EXPERIMENT_START_DATE} · Day {d} · baseline {EXPERIMENT_BASELINE_WEIGHT_LBS} lbs · all healthy.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
