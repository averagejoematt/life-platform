#!/usr/bin/env python3
"""
restart_verify.py — Post-pivot health check. Run this Monday morning (or any
time) to confirm the restart pipeline produced a healthy, consistent state.

Checks (each pass/fail):
  1. lambdas/common/constants.py genesis matches config/user_goals.json
  2. No function references the retired shared layer (#781)
  3. DDB PROFILE#v1 matches lambdas/common/constants.py baseline
  4. Live /api/journey returns started_date == genesis
  5. Live /api/journey returns start_weight == baseline (rounded)
  6. day_n(today) is >= 1 (we are at or past genesis)
  7. Withings record exists for genesis date
  8. Character sheet exists for at least one post-genesis day
  9. No habit streak > day_n (would indicate leak from pre-genesis data)
 10. pytest layer-retirement test passes (i2)
 11. Baked static/no-JS + OG proof (Home + Coaching) is fresh post-genesis (#1815)
 12. Plan literals (protein floor et al.) reconcile with config/user_goals.json (#1898)
 13. /api/predict_week is active once the genesis week begins (#1952 — the
     cycle-11 seed carried the wall-clock pre-genesis week_id and the #1198
     guard hid the opening-week hook; pre-genesis countdown => dark is correct)

Returns 0 if all checks pass, 1 if any fail.

Usage:
    python3 deploy/restart_verify.py
"""
import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "deploy"))

from lambdas.common.constants import (
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

    # 2. layer retirement (#781): nothing may reference the retired shared layer
    lam = boto3.client("lambda", region_name=REGION)
    attached = []
    for page in lam.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            if any(LAYER in l.get("Arn", "") for l in fn.get("Layers", [])):
                attached.append(fn["FunctionName"])
    check("No function references the retired shared layer", not attached, f"attached={attached[:5]}")

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
            "tests/test_integration_aws.py::test_i2_shared_layer_retired",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    pytest_ok = proc.returncode == 0
    check("pytest layer-retirement test passes", pytest_ok, proc.stdout.strip().splitlines()[-1] if proc.stdout else "no output")

    # 11. Static/no-JS + OG proof rebake (#1815). Home's <noscript> core + OG tags and
    # /coaching/'s OG title are BAKED (scripts/v4_build_home_proof.py, v4_build_coaching.py)
    # and only regenerate as a side effect of `deploy/sync_site_to_s3.sh` — which only runs
    # on a site/** push. If genesis has passed with no incidental site/** merge since, the
    # crawler/social/no-JS layer is still serving pre-start copy ("the experiment begins
    # Monday..."). Re-run the two generators here (offline-safe: they fall back to the
    # committed proof_snapshot.json if the live API is unreachable) and diff the result —
    # any change means the baked layer WAS stale and has now been rebaked in the working
    # tree; commit + push (touches site/**, so the standing site-deploy.yml auto-deploys
    # it) to actually publish the fix.
    watched = ["site/index.html", "site/coaching/index.html"]
    before = {}
    for rel in watched:
        p = REPO_ROOT / rel
        before[rel] = p.read_text(encoding="utf-8") if p.exists() else None
    rebake_errors = []
    # v4_apply_chrome.py MUST run last (same order as sync_site_to_s3.sh) — it
    # re-flattens the doors nav/footer/head-chrome to the single source, so a
    # generator alone would otherwise leave the page on its own stale inline
    # chrome and manufacture a false "changed" diff below.
    for script in ("scripts/v4_build_home_proof.py", "scripts/v4_build_coaching.py", "scripts/v4_apply_chrome.py"):
        r = subprocess.run(["python3", script], cwd=REPO_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            rebake_errors.append(f"{script}: exit {r.returncode}: {r.stderr.strip().splitlines()[-1] if r.stderr else ''}")
    changed = [rel for rel in watched if (REPO_ROOT / rel).exists() and (REPO_ROOT / rel).read_text(encoding="utf-8") != before[rel]]
    if rebake_errors:
        check("Static/OG proof rebake ran cleanly", False, "; ".join(rebake_errors))
    else:
        check(
            "Baked static/OG proof was already fresh (no rebake needed)",
            not changed,
            f"rebaked (now dirty in the working tree, commit+push to deploy): {changed}" if changed else "up to date",
        )

    # 12. #1898 — plan literals reconcile against config/user_goals.json.
    # A reset rewrites user_goals + the character_sheet BASELINE, but nothing swept
    # the plan FIGURES scattered through prompt-feeding and page-generating configs.
    # Cycle 11 shipped the wiped pilot's 190 g protein target: the character engine
    # graded against it, /method/game/ published "target grams 190", and
    # board_of_directors fed "(190g target)" into coach prompts — while the sealed
    # prereg said 170. Same class as the #1219 kept-chronicle figure check, hence the
    # same WARN-shaped surfacing here; the hard gate is
    # tests/test_plan_literal_reconciliation.py, which reds CI on divergence.
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_plan_literal_reconciliation.py", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        tail = (proc.stdout or proc.stderr).strip().splitlines()
        check(
            "Plan literals reconcile with config/user_goals.json (#1898)",
            proc.returncode == 0,
            tail[-1] if tail else "no output",
        )
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("Plan literals reconcile with config/user_goals.json (#1898)", False, f"check could not run: {e}")

    # 13. #1952 — predict-the-week must be LIVE once the genesis week begins.
    # Cycle 11 ran its whole opening week dark: the Sunday prep run stamped the
    # wall-clock (pre-genesis) ISO week and the #1198 fail-closed guard hid the
    # challenge for Days 1-6. Pre-genesis, dark is the correct countdown state.
    try:
        from build_genesis_predict_week import evaluate_predict_week_state

        try:
            with urllib.request.urlopen(f"{API}/api/predict_week?cb=verify", timeout=10) as r:
                active = bool(json.loads(r.read()).get("active"))
        except Exception:
            active = None
        today_pt = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        ok, detail = evaluate_predict_week_state(EXPERIMENT_START_DATE, today_pt, active)
        check("/api/predict_week live once the genesis week begins (#1952)", ok, detail)
    except Exception as e:  # never let the verifier itself crash the post-reset check
        check("/api/predict_week live once the genesis week begins (#1952)", False, f"check could not run: {e}")

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
