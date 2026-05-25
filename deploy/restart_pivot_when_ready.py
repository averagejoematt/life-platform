#!/usr/bin/env python3
"""
restart_pivot_when_ready.py — Watchdog that polls DDB for the May 25 Withings
reading and auto-runs the restart pipeline with the real weight when it appears.

Started by launchd on a fixed schedule (e.g., Monday 7 AM PT). Polls every
3 minutes for up to 6 hours. When the genesis-date Withings reading exists,
runs `restart_pipeline.py --apply` with that weight as the override and exits.

Logs to docs/restart/_pivot_watchdog.log.

Usage (manual run):
    python3 deploy/restart_pivot_when_ready.py
    python3 deploy/restart_pivot_when_ready.py --genesis 2026-05-25 --max-minutes 360
"""
import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
POLL_INTERVAL_SECONDS = 180
DEFAULT_MAX_MINUTES = 360  # 6 hours of polling

LOG = REPO_ROOT / "docs" / "restart" / "_pivot_watchdog.log"


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    line = f"{ts}  {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
    print(line, end="")


def fetch_reading(genesis: str):
    ddb = boto3.resource("dynamodb", region_name=REGION)
    t = ddb.Table(TABLE)
    r = t.get_item(Key={"pk": f"USER#{USER}#SOURCE#withings", "sk": f"DATE#{genesis}"})
    return r.get("Item")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genesis", default=None,
                        help="Target genesis date YYYY-MM-DD. Default: read from constants.py")
    parser.add_argument("--max-minutes", type=int, default=DEFAULT_MAX_MINUTES,
                        help=f"Max polling duration in minutes. Default: {DEFAULT_MAX_MINUTES}")
    args = parser.parse_args()

    if args.genesis:
        genesis = args.genesis
    else:
        from lambdas.constants import EXPERIMENT_START_DATE
        genesis = EXPERIMENT_START_DATE

    log(f"watchdog starting. genesis={genesis} max_minutes={args.max_minutes} poll={POLL_INTERVAL_SECONDS}s")
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=args.max_minutes)

    while dt.datetime.now(dt.timezone.utc) < deadline:
        try:
            item = fetch_reading(genesis)
        except Exception as e:
            log(f"  DDB error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        if item:
            weight_lbs = float(item.get("weight_lbs"))
            weight_kg = float(item.get("weight_kg"))
            log(f"  FOUND reading for {genesis}: weight_lbs={weight_lbs} weight_kg={weight_kg}")
            log(f"  Running pipeline...")
            proc = subprocess.run(
                ["python3", "deploy/restart_pipeline.py",
                 "--genesis", genesis, "--apply"],
                cwd=REPO_ROOT, capture_output=True, text=True,
            )
            log(f"  pipeline exit={proc.returncode}")
            log(f"  stdout-tail: {proc.stdout[-2000:]}")
            if proc.returncode != 0:
                log(f"  STDERR: {proc.stderr[-1500:]}")
            log("watchdog done.")
            return 0
        log(f"  no reading yet for {genesis}, sleeping {POLL_INTERVAL_SECONDS}s")
        time.sleep(POLL_INTERVAL_SECONDS)

    log(f"watchdog deadline reached without finding a reading for {genesis}. Exit.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
