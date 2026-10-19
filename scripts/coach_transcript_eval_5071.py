#!/usr/bin/env python3
"""coach_transcript_eval_5071.py — the planning-conversation order eval (#5071 acceptance box 5).

Runs `training.coach_context.order_violations` over the real planning conversations kept in
tests/fixtures/coach_transcripts_5071/ (tool-call sequences read off the MCP Lambda's own
`Calling tool` log line) — BEFORE: the conversation as it happened — and over the same
conversation re-ordered to the contract by `to_contract` — AFTER. The AFTER is what the contract
asks for; it is proven live only by the next real planning conversation run under it.

    python3 scripts/coach_transcript_eval_5071.py          # the table
    python3 scripts/coach_transcript_eval_5071.py --json   # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training import coach_context  # noqa: E402

FIXTURE_DIR = os.path.join(_REPO, "tests", "fixtures", "coach_transcripts_5071")


def _tool(c: Any) -> str:
    return c if isinstance(c, str) else str((c or {}).get("tool") or "")


def to_contract(calls: list[Any]) -> list[Any]:
    """The same conversation in the contract's order: each pre-flight tool it never called, or called
    only after the first planning call, is called (once) before that call. Nothing else moves."""
    first = next((i for i, c in enumerate(calls) if coach_context.stage_of(c) is not None), len(calls))
    before = {_tool(c) for c in calls[:first]}
    tools = list(dict.fromkeys(t for ts in coach_context.PRE_FLIGHT.values() for t in ts))
    missing = [{"tool": t, "synthesized": "pre-flight, per the contract"} for t in tools if t not in before]
    return calls[:first] + missing + calls[first:]


def load_fixtures(path: str = FIXTURE_DIR) -> list[dict[str, Any]]:
    out = []
    for name in sorted(os.listdir(path)):
        if name.endswith(".json"):
            with open(os.path.join(path, name), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def evaluate(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fx in fixtures:
        calls = fx["tool_calls"]
        rows.append(
            {
                "conversation": fx["conversation"],
                "calls": len(calls),
                "before": coach_context.order_violations(calls),
                "after": coach_context.order_violations(to_contract(calls)),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = evaluate(load_fixtures())
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print(f"{r['conversation']} ({r['calls']} calls)")
        for label in ("before", "after"):
            v = r[label]
            detail = "; ".join(f"{x['code']}" + (f" missing={','.join(x['missing'])}" if x["missing"] else "") for x in v) or "none"
            print(f"  {label:6s} {len(v)} violation(s): {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
