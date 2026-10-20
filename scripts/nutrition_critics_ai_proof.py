#!/usr/bin/env python3
"""scripts/nutrition_critics_ai_proof.py — the live proof for the nutrition critics' model layer (#5114).

DRY RUN (the default) makes NO model call: it reads the budget tier, builds the critics block
from live DynamoDB reads (read-only) and prints, per critic, the verdict and the size of the
body the layer WOULD send, plus whether the tier lets it run today.

    python3 scripts/nutrition_critics_ai_proof.py                  # dry run, latest complete day
    python3 scripts/nutrition_critics_ai_proof.py --end-date 2026-10-18

LIVE (`--live`) runs the layer exactly as `get_deficit_sustainability` does — through
`bedrock_client.invoke`, gated by the `nutrition_critics` budget feature (band 1). It NEVER moves
the tier: at tier >= 1 it prints the paused record and exits 2, which is the honest outcome, not a
failure to work around. Up to three Haiku calls (~$0.006); the workstation dev AI cap applies.
Exit 0 = a non-degraded run (every critic narrated); 1 = ran with an error or a withheld narrative;
2 = paused by the budget tier.

    python3 scripts/nutrition_critics_ai_proof.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas", ROOT):
    sys.path.insert(0, str(_p))
for _k, _v in (("S3_BUCKET", "matthew-life-platform"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)


def _summary(block: dict) -> dict:
    return {
        "window_end": block.get("window_end"),
        "model_layer": block.get("model_layer"),
        "model_ran": block.get("model_ran"),
        "model_paused_reason": block.get("model_paused_reason"),
        "verdicts": [{k: v.get(k) for k in ("critic", "verdict", "metric", "provenance", "model")} for v in block.get("verdicts", [])],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--end-date", help="YYYY-MM-DD (default: the latest complete nutrition day)")
    ap.add_argument("--live", action="store_true", help="run the model layer (budget-gated; never forces the tier)")
    args = ap.parse_args(argv)

    from health import nutrition_critics, nutrition_critics_ai

    from mcp import nutrition_critics_inputs
    from mcp.tools_nutrition import _nutrition_through_date

    end = args.end_date or _nutrition_through_date()
    state = nutrition_critics_ai.gate()
    print(
        f"budget: tier {state['tier']}, {nutrition_critics_ai.BUDGET_FEATURE} pauses at tier {state['cutoff']} -> allowed={state['allowed']}"
    )
    if not args.live:
        resolved = nutrition_critics_inputs.resolve(end)
        block = nutrition_critics.block(resolved["inputs"])
        packets = nutrition_critics.build_packets(resolved["inputs"])
        for v in block["verdicts"]:
            body = nutrition_critics_ai.build_prompt(v, packets[v["critic"]])
            size = len(body["system"]) + len(body["messages"][0]["content"])
            print(f"  {v['critic']:<16} {v['verdict']:<8} would send ~{size} chars to {body['model']}")
        print("dry run: no model call made. Re-run with --live for the proof.")
        return 0
    block = nutrition_critics_inputs.block(end, model=True)
    print(json.dumps(_summary(block), indent=2, default=str))
    if not block.get("model_ran"):
        return 2 if (block.get("model_layer") or {}).get("state") == "paused" else 1
    return 0 if all((v.get("model") or {}).get("narrative") for v in block["verdicts"]) else 1


if __name__ == "__main__":
    sys.exit(main())
