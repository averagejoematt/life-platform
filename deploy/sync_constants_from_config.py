#!/usr/bin/env python3
"""
sync_constants_from_config.py — Regenerates lambdas/constants.py from the
canonical config (config/user_goals.json). ADR-058.

The restart pipeline calls this whenever the genesis date or baseline weight
changes. The generated constants.py is what every Lambda actually imports;
the config files are the single source of truth.

Usage:
    python3 deploy/sync_constants_from_config.py            # dry-run: print diff
    python3 deploy/sync_constants_from_config.py --apply    # write file
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "user_goals.json"
CONSTANTS_PATH = REPO_ROOT / "lambdas" / "constants.py"


def derive_dow(date_str: str) -> str:
    return date.fromisoformat(date_str).strftime("%A")


def render(cfg: dict) -> str:
    timeline = cfg["timeline"]
    start_date = timeline["start_date"]
    start_lbs = timeline["start_weight_lbs"]
    start_kg = timeline.get("start_weight_kg")
    goal_lbs = cfg.get("targets", {}).get("weight", {}).get("goal_lbs", 185)
    dow = derive_dow(start_date)

    if start_kg is None:
        start_kg = round(float(start_lbs) / 2.20462, 3)

    return f'''"""
constants.py — Runtime constants shared across life-platform Lambdas.

GENERATED FILE. Do not edit by hand. Source of truth is config/user_goals.json.
Regenerate with: python3 deploy/sync_constants_from_config.py --apply

Part of the shared Lambda layer (ADR-058). Changes require layer rebuild
(`bash deploy/build_layer.sh`) before deploying dependent functions.
"""

from datetime import date

EXPERIMENT_START_DATE = "{start_date}"
EXPERIMENT_START_DOW = "{dow}"
EXPERIMENT_TZ = "America/Los_Angeles"

EXPERIMENT_PHASE_CURRENT = "experiment"
EXPERIMENT_PHASE_PRIOR = "pilot"

EXPERIMENT_BASELINE_WEIGHT_LBS = {start_lbs}
EXPERIMENT_BASELINE_WEIGHT_KG = {start_kg}

EXPERIMENT_GOAL_WEIGHT_LBS = {goal_lbs}


def day_n(today_iso: str) -> int:
    """1-indexed Day-N relative to EXPERIMENT_START_DATE. Returns 0 for pre-genesis dates."""
    d = date.fromisoformat(today_iso)
    start = date.fromisoformat(EXPERIMENT_START_DATE)
    delta = (d - start).days
    return delta + 1 if delta >= 0 else 0
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the file (default: dry-run / diff)")
    args = parser.parse_args()

    cfg = json.loads(CONFIG_PATH.read_text())
    new_content = render(cfg)
    current = CONSTANTS_PATH.read_text() if CONSTANTS_PATH.exists() else ""

    if new_content == current:
        print(f"[SYNC] {CONSTANTS_PATH.relative_to(REPO_ROOT)} already up to date.")
        return 0

    if args.apply:
        CONSTANTS_PATH.write_text(new_content)
        print(f"[SYNC] Wrote {CONSTANTS_PATH.relative_to(REPO_ROOT)} from {CONFIG_PATH.relative_to(REPO_ROOT)}")
    else:
        import difflib

        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{CONSTANTS_PATH.relative_to(REPO_ROOT)}",
            tofile=f"b/{CONSTANTS_PATH.relative_to(REPO_ROOT)}",
        )
        sys.stdout.write("".join(diff))
        print("\n[DRY-RUN] Pass --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
