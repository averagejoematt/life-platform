#!/usr/bin/env python3
"""Re-derive the per-set time model from his measured Hevy sessions (#5799). READ-ONLY.

Reads the Hevy workout records (`USER#matthew#SOURCE#hevy`) since `--since` (default: the experiment start), resolves each
matched session's routine (`adherence.matched_routine_id` -> `routine_repo.get_current`), measures it with
`training.session_time.measure` and prints one line per session (date, role, measured / estimated lifting minutes, the
implied set seconds) and the `MEASURED_SET_SECONDS` record to paste into `lambdas/training/session_time.py`.

Minutes and seconds only: no load, no body data. Makes no writes.

    python3 scripts/derive_session_time_model.py [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))


def _records(since: str) -> list[dict]:
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
    kw = {"KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").gte(f"DATE#{since}")}
    out: list[dict] = []
    while True:
        page = table.query(**kw)
        out += [i for i in page["Items"] if "#WORKOUT#" in i["sk"]]
        if "LastEvaluatedKey" not in page:
            return out
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> int:
    from common.constants import EXPERIMENT_START_DATE
    from common.numeric import decimals_to_float
    from training import routine_repo, session_time

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=EXPERIMENT_START_DATE)
    args = ap.parse_args()
    with open(os.path.join(_REPO, "config", "movement_catalog.json"), encoding="utf-8") as f:
        movements = json.load(f)["movements"]
    samples: list[tuple[str, float]] = []
    for rec in sorted(_records(args.since), key=lambda r: r["sk"]):
        rid = (rec.get("adherence") or {}).get("matched_routine_id")
        ir = routine_repo.get_current(rid) if rid else None
        m = session_time.measure(decimals_to_float(rec), ir, movements)
        if not m:
            continue
        implied = m.get("implied_set_seconds")
        print(
            f"{rec['date']}  {str(m.get('session_role') or '-'):15s} measured {m['lifting_minutes']:6.1f} min  "
            f"estimate {m.get('estimate_minutes', '-')!s:>6} min  sets {m['lifting_sets']:3d}  implied set_seconds {implied}"
        )
        if implied is not None and m["lifting_sets"]:
            samples.append((rec["date"], implied))
    print(json.dumps(session_time.derive_set_seconds(samples), indent=4))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
