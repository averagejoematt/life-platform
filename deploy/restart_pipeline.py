#!/usr/bin/env python3
"""
restart_pipeline.py — ADR-058: One-command orchestrator that re-anchors the
experiment to a new genesis date and converges every surface (DDB, layer,
Lambdas, S3 chronicle, site copy, docs).

Usage:
    # Re-target the experiment to a new date:
    python3 deploy/restart_pipeline.py --genesis 2026-05-25 --dry-run
    python3 deploy/restart_pipeline.py --genesis 2026-05-25 --apply

    # Re-converge the current genesis without changing the date:
    python3 deploy/restart_pipeline.py --apply

Every sub-script is idempotent; the orchestrator can be safely re-run.

Steps (each can be skipped with --skip-<name>):
    1. fetch Withings reading for the target date (or fail)
    2. write config/user_goals.json + config/character_sheet.json
    3. regenerate lambdas/constants.py via sync_constants_from_config.py
    4. bump SHARED_LAYER_VERSION in cdk/stacks/constants.py
    5. bash deploy/build_layer.sh + cdk deploy (Core, Compute, Email)
    6. restart_phase_tag.py
    7. restart_intelligence_wipe.py
    8. restart_character_rebuild.py
    9. restart_chronicle_handler.py
   10. restart_site_copy_sync.py
   11. restart_docs_update.py
   12. final verification report

By default --dry-run runs every sub-script in dry-run mode so the operator
sees the total surface area before committing. --apply commits writes at
every step.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
LAYER_NAME = "life-platform-shared-utils"

USER_GOALS = REPO_ROOT / "config" / "user_goals.json"
CHAR_SHEET = REPO_ROOT / "config" / "character_sheet.json"
CDK_CONSTANTS = REPO_ROOT / "cdk" / "stacks" / "constants.py"


def fetch_withings_for(target_date: str) -> dict:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    r = t.get_item(Key={"pk": f"USER#{USER}#SOURCE#withings", "sk": f"DATE#{target_date}"})
    item = r.get("Item")
    if not item:
        raise RuntimeError(
            f"No Withings reading found for {target_date}. "
            f"Either wait for the morning sync or pass --override-weight-lbs."
        )
    return {
        "weight_lbs": float(item["weight_lbs"]),
        "weight_kg":  float(item["weight_kg"]),
        "measurement_utc": item.get("measurement_time_utc"),
    }


def update_ddb_profile(target_date: str, weight_lbs: float, apply: bool):
    """Update the DDB profile record (USER#matthew / PROFILE#v1) — the runtime
    source of truth that site_api_lambda etc. read from. The config JSON files
    are static; the DDB profile is what Lambdas actually see at request time.
    """
    if not apply:
        return
    from decimal import Decimal
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    t.update_item(
        Key={"pk": f"USER#{USER}", "sk": "PROFILE#v1"},
        UpdateExpression="SET journey_start_weight_lbs = :w, journey_start_date = :d, "
                          "baseline_weight_lbs = :w, baseline_date = :d",
        ExpressionAttributeValues={
            ":w": Decimal(str(weight_lbs)),
            ":d": target_date,
        },
    )


def bust_lambda_warm_cache(apply: bool):
    """Toggle an env var on site-api-style Lambdas to force a cold start.
    Required because they cache the DDB profile in-memory for the warm
    container lifetime — after a profile update, warm containers still
    return stale data until they cycle.
    """
    if not apply:
        return
    from datetime import datetime as _dt
    bust_val = _dt.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    targets = ["life-platform-site-api", "life-platform-site-api-ai", "site-stats-refresh"]
    lam = boto3.client("lambda", region_name=REGION)
    for fn in targets:
        try:
            cur = lam.get_function_configuration(FunctionName=fn)
            env = cur.get("Environment", {}).get("Variables", {})
            env["RESTART_CACHE_BUST"] = bust_val
            lam.update_function_configuration(FunctionName=fn, Environment={"Variables": env})
        except Exception:
            pass  # function may not exist; harmless


def update_configs(target_date: str, weight_lbs: float, weight_kg: float, measurement_utc: str, apply: bool):
    # user_goals.json
    cfg = json.loads(USER_GOALS.read_text())
    today_iso = date.today().isoformat()
    end_date = (date.fromisoformat(target_date) + (date.fromisoformat("2027-05-17") - date.fromisoformat("2026-05-18"))).isoformat()
    cfg["last_updated"] = today_iso
    cfg["timeline"]["start_date"] = target_date
    cfg["timeline"]["end_date"] = end_date
    cfg["timeline"]["start_weight_lbs"] = weight_lbs
    cfg["timeline"]["start_weight_kg"] = weight_kg
    cfg["timeline"]["baseline_source"] = "withings"
    if measurement_utc:
        cfg["timeline"]["baseline_measurement_utc"] = measurement_utc
    if apply:
        USER_GOALS.write_text(json.dumps(cfg, indent=2) + "\n")

    # character_sheet.json
    cs = json.loads(CHAR_SHEET.read_text())
    cs["_meta"]["last_updated"] = today_iso
    cs["baseline"]["start_date"] = target_date
    cs["baseline"]["start_weight_lbs"] = weight_lbs
    cs["baseline"]["start_weight_kg"] = weight_kg
    cs["baseline"]["baseline_source"] = "withings"
    if apply:
        CHAR_SHEET.write_text(json.dumps(cs, indent=2) + "\n")


def bump_layer_version(apply: bool) -> int:
    text = CDK_CONSTANTS.read_text()
    m = re.search(r"SHARED_LAYER_VERSION = (\d+)", text)
    if not m:
        raise RuntimeError("Could not find SHARED_LAYER_VERSION in cdk/stacks/constants.py")
    current = int(m.group(1))
    new_version = current + 1
    today_iso = date.today().isoformat()
    new_text = re.sub(
        r"SHARED_LAYER_VERSION = \d+.*",
        f"SHARED_LAYER_VERSION = {new_version}  # v{new_version}: ADR-058 restart pipeline ({today_iso})",
        text,
        count=1,
    )
    if apply:
        CDK_CONSTANTS.write_text(new_text)
    return new_version


def run_step(name: str, cmd: list[str], apply: bool, log: list[str]) -> int:
    print(f"\n──[ {name} ]──")
    print(f"    $ {' '.join(cmd)}")
    if not apply:
        # Inject --dry-run / drop --apply for sub-scripts
        cmd = [c for c in cmd if c != "--apply"]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    log.append(f"=== {name} === (exit {proc.returncode})")
    log.append(proc.stdout[-1500:] if proc.stdout else "")
    if proc.returncode != 0:
        log.append(f"STDERR: {proc.stderr[-800:]}")
    print(proc.stdout[-400:] if proc.stdout else "(no stdout)")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genesis", help="Target genesis date YYYY-MM-DD. Default: current genesis.")
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run for every sub-step)")
    parser.add_argument("--override-weight-lbs", type=float, help="Skip Withings fetch, use this weight")
    parser.add_argument("--override-weight-kg", type=float, help="Override kg too (computed from lbs if absent)")
    parser.add_argument("--skip-deploy", action="store_true", help="Skip CDK deploy step (use if you just deployed)")
    parser.add_argument("--skip-chronicle", action="store_true", help="Skip chronicle handler (rerunning is generally fine)")
    args = parser.parse_args()

    # Resolve target genesis
    if args.genesis:
        target = args.genesis
    else:
        from lambdas.constants import EXPERIMENT_START_DATE
        target = EXPERIMENT_START_DATE
    print(f"\n╔══ restart_pipeline ══╗")
    print(f"║ target genesis: {target}")
    print(f"║ mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"╚══════════════════════╝")

    # Step 1: fetch Withings reading
    if args.override_weight_lbs:
        wt = {
            "weight_lbs": args.override_weight_lbs,
            "weight_kg":  args.override_weight_kg or round(args.override_weight_lbs / 2.20462, 3),
            "measurement_utc": None,
        }
        print(f"\n[1] Withings override: {wt['weight_lbs']} lbs / {wt['weight_kg']} kg")
    else:
        print(f"\n[1] Fetching Withings reading for {target}...")
        try:
            wt = fetch_withings_for(target)
            print(f"    weight_lbs={wt['weight_lbs']} weight_kg={wt['weight_kg']} measurement={wt['measurement_utc']}")
        except RuntimeError as e:
            print(f"    ERROR: {e}")
            sys.exit(2)

    # Step 2: update configs + DDB profile
    print(f"\n[2] Updating config/user_goals.json + config/character_sheet.json + DDB PROFILE#v1")
    update_configs(target, wt["weight_lbs"], wt["weight_kg"], wt.get("measurement_utc"), args.apply)
    update_ddb_profile(target, wt["weight_lbs"], args.apply)
    print(f"    ({'wrote' if args.apply else 'would write'} configs + DDB profile)")

    # Step 3: regenerate constants
    log = []
    rc = run_step("sync_constants_from_config", ["python3", "deploy/sync_constants_from_config.py", "--apply"], args.apply, log)
    if rc and args.apply:
        sys.exit(rc)

    # Step 4 + 5: bump layer + build + deploy
    if not args.skip_deploy:
        print(f"\n[4] Bumping SHARED_LAYER_VERSION")
        new_v = bump_layer_version(args.apply)
        print(f"    → v{new_v}")
        if args.apply:
            print(f"\n[5] Building layer + CDK deploy")
            run_step("build_layer", ["bash", "deploy/build_layer.sh"], True, log)
            # Deploy ALL stacks from cdk/ working dir so CDK re-synths against
            # the freshly built layer-build/. Every stack imports the shared
            # layer, so all of them need to redeploy when constants change.
            cdk_proc = subprocess.run(
                ["npx", "cdk", "deploy", "--all", "--require-approval", "never"],
                cwd=REPO_ROOT / "cdk", capture_output=True, text=True,
            )
            log.append(f"=== cdk_deploy === (exit {cdk_proc.returncode})")
            log.append(cdk_proc.stdout[-2000:] if cdk_proc.stdout else "")
            if cdk_proc.returncode != 0:
                log.append(f"STDERR: {cdk_proc.stderr[-1000:]}")
            print(cdk_proc.stdout[-500:] if cdk_proc.stdout else "(no stdout)")
        else:
            print(f"\n[5] (dry-run) skipping CDK deploy")
    else:
        print(f"\n[4-5] CDK deploy skipped (--skip-deploy)")

    # Step 6-11: all the restart sub-scripts
    sub_scripts = [
        ("restart_phase_tag",         ["python3", "deploy/restart_phase_tag.py", "--apply"]),
        ("restart_intelligence_wipe", ["python3", "deploy/restart_intelligence_wipe.py", "--apply"]),
        ("restart_character_rebuild", ["python3", "deploy/restart_character_rebuild.py", "--apply"]),
        ("restart_site_copy_sync",    ["python3", "deploy/restart_site_copy_sync.py", "--apply"]),
        ("restart_docs_update",       ["python3", "deploy/restart_docs_update.py", "--apply"]),
    ]
    if not args.skip_chronicle:
        sub_scripts.insert(3, ("restart_chronicle_handler", ["python3", "deploy/restart_chronicle_handler.py", "--apply"]))

    for name, cmd in sub_scripts:
        run_step(name, cmd, args.apply, log)

    # Final: bust warm-container caches on read-path Lambdas
    print(f"\n[final] Busting warm-container caches on public-facing Lambdas")
    bust_lambda_warm_cache(args.apply)
    print(f"    ({'forced cold start' if args.apply else 'would force cold start'} on site-api / site-api-ai / site-stats-refresh)")

    # ADR-058 launch-eve audit: hard gate on rendered-surface verification.
    # Catches the class of bug where clean backend still produces a stale-
    # looking public site (hardcoded client JS, cached S3 JSON, missed
    # DDB partitions, etc.). Pass the verify only if apply is true — in
    # dry-run we don't expect the live site to reflect the pivot yet.
    if args.apply:
        print(f"\n[verify] restart_verify_rendered.py (hard gate)")
        import time
        time.sleep(30)  # let CloudFront invalidation propagate before we curl
        verify_rc = run_step("restart_verify_rendered",
                              ["python3", "deploy/restart_verify_rendered.py"],
                              True, log)
        if verify_rc != 0:
            print(f"\n⚠ VERIFY GATE FAILED — public surfaces still show stale tokens.")
            print(f"   Check docs/restart/_verify_rendered_report.txt for the failing URLs.")
            print(f"   Common causes: CloudFront cache not yet purged, Lambda warm-cache,")
            print(f"   newly-missed JS/HTML/JSON surface. Re-run after fixing.")

    # Final report
    report = REPO_ROOT / "docs" / "restart" / "_pipeline_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"restart_pipeline report — target={target} — mode={'APPLY' if args.apply else 'DRY-RUN'}\n"
        f"generated={datetime.now(timezone.utc).isoformat()}\n\n"
        f"baseline_weight_lbs = {wt['weight_lbs']}\n"
        f"baseline_weight_kg  = {wt['weight_kg']}\n\n"
        + "\n".join(log)
    )
    print(f"\n══ pipeline {'COMPLETE' if args.apply else 'DRY-RUN COMPLETE'} ══")
    print(f"Report: docs/restart/_pipeline_report.txt")
    if not args.apply:
        print(f"\nRe-run with --apply to commit.")


if __name__ == "__main__":
    main()
