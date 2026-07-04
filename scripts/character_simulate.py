#!/usr/bin/env python3
"""
character_simulate.py — ADR-104: READ-ONLY simulation of the character engine
over the real experiment window.

Pulls the same DDB inputs the character-sheet Lambda assembles (reusing its
assemble_data), runs the LOCAL engine + LOCAL config/character_sheet.json day
by day from genesis, and prints per-pillar raw/level trajectories. Writes
nothing — this is the tuning loop before deploy + restart_character_rebuild.

Usage:
    python3 scripts/character_simulate.py                 # genesis → yesterday
    python3 scripts/character_simulate.py --end 2026-07-02
    python3 scripts/character_simulate.py --live-config   # S3 config instead of local
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "compute"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

import character_engine  # noqa: E402
import character_sheet_lambda as csl  # noqa: E402
from constants import EXPERIMENT_START_DATE  # noqa: E402

PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--live-config", action="store_true", help="Use the S3 config instead of the local file")
    args = ap.parse_args()

    if args.live_config:
        config = character_engine.load_character_config(csl.s3, os.environ["S3_BUCKET"])
    else:
        config = json.loads((REPO_ROOT / "config" / "character_sheet.json").read_text())

    start = date.fromisoformat(EXPERIMENT_START_DATE)
    end = date.fromisoformat(args.end)
    print(
        f"Simulating {EXPERIMENT_START_DATE} → {args.end} | engine v{character_engine.ENGINE_VERSION} | config v{config['_meta']['version']}"
    )
    print(f"{'date':<11} " + " ".join(f"{p[:5]:>11}" for p in PILLARS) + "   char")
    print(f"{'':<11} " + " ".join(f"{'raw/lvl':>11}" for _ in PILLARS))

    prev_state = None
    histories = {p: [] for p in PILLARS}
    cursor = start
    final = None
    while cursor <= end:
        d = cursor.isoformat()
        data = csl.assemble_data(d)
        record = character_engine.compute_character_sheet(data, prev_state, histories, config)
        for p in PILLARS:
            histories[p].append(record[f"pillar_{p}"]["raw_score"])
        cells = []
        for p in PILLARS:
            pd = record[f"pillar_{p}"]
            hold = "*" if pd.get("coverage_hold") else " "
            cells.append(f"{pd['raw_score']:>5.0f}/{pd['level']:>3}{hold}")
        print(f"{d:<11} " + " ".join(f"{c:>11}" for c in cells) + f"   {record['character_level']:>4}")
        prev_state = record
        final = record
        cursor += timedelta(days=1)

    if final:
        print("\n— final day detail (drivers / absences) —")
        for p in PILLARS:
            pd = final[f"pillar_{p}"]
            drv = pd.get("drivers", {})
            bits = []
            if drv.get("top"):
                bits.append("top: " + ", ".join(drv["top"]))
            if drv.get("dragging"):
                bits.append("dragging: " + ", ".join(drv["dragging"]))
            if drv.get("absent"):
                bits.append("absent: " + ", ".join(drv["absent"]))
            if drv.get("no_data"):
                bits.append("no data: " + ", ".join(drv["no_data"]))
            cov = pd.get("data_coverage")
            print(
                f"  {p:<14} lvl {pd['level']:>3}  raw {pd['raw_score']:>5.1f}  cov {cov if cov is not None else '?'}  | " + "; ".join(bits)
            )
        print("  (* = coverage hold: day carried no leveling signal)")


if __name__ == "__main__":
    main()
