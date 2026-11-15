#!/usr/bin/env python3
"""scripts/rate_policy_dry_run.py — the adaptive loss-rate band proposal on synthetic profiles (#5861 L5).

No AWS, no clock, no writes: each profile below is made up, and each is run through `health.rate_policy.propose_band`.
The proposal is read by no live path; the live rate band and kcal target are unchanged.

    python3 scripts/rate_policy_dry_run.py [--profiles path.json] [--json]

`--profiles` takes a JSON object {name: {signal: value}} with `propose_band`'s keyword names.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_REPO, "lambdas"), _REPO]

from health import rate_policy  # noqa: E402

SYNTHETIC_PROFILES: dict[str, dict] = {
    "a_top_tier_all_clear": {"body_fat_tier": "report_only", "observed_pct_bw_per_wk": 1.0, "fatigue_level": "normal"},
    "b_top_tier_strength_down": {
        "body_fat_tier": "report_only",
        "observed_pct_bw_per_wk": 1.3,
        "anchor_e1rm_change_pct": {"bench": -6.0, "squat": -7.0, "row": -1.0, "hinge": 0.5},
    },
    "c_middle_tier_adherence_break": {
        "body_fat_tier": "brake",
        "protein_floor_days_missed_7d": 4,
        "intake_adherence_pct": 45.0,
    },
    "d_lowest_tier_three_signals": {
        "body_fat_tier": "full",
        "fatigue_level": "high",
        "recovery_low": True,
        "hunger_high_days_7d": 5,
    },
    "e_unknown_everything": {},
}
"""Made-up signal profiles for the demonstration; none is anyone's data."""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profiles", help="JSON file {name: {signal: value}}; default: the synthetic profiles above")
    ap.add_argument("--json", action="store_true", help="print the full proposals as JSON")
    args = ap.parse_args(argv)
    profiles = SYNTHETIC_PROFILES
    if args.profiles:
        with open(args.profiles, encoding="utf-8") as fh:
            profiles = json.load(fh)
    out = rate_policy.dry_run(profiles)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    for name, p in out.items():
        lo, hi = p["band_pct_bw_per_wk"]
        print(f"{name}: {p['band_name']} {lo:g}-{hi:g} %BW/wk  driver={p['driver']}  observed={p['observed_vs_band']}")
        print(f"    {p['reason']}")
        if p["owner_decision"]:
            print(f"    owner decision: {p['owner_decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
