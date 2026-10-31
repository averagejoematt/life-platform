#!/usr/bin/env python3
"""coach_transcript_eval_5071.py — the planning-conversation order eval (#5071 acceptance box 5).

Runs `training.coach_context.order_violations` over REAL planning conversations kept in
tests/fixtures/coach_transcripts_5071/ (tool-call sequences read off the MCP Lambda's own
`Calling tool` log line, redacted to tool names, timestamps, manage_hevy_routine's `action` and
whether plan_next_session carried a routine id):

  * BEFORE — the top-level fixtures: conversations held before the contract was deployed
    (wave 2, CI/CD run 39286310627, 2026-10-19 16:53Z);
  * AFTER  — tests/fixtures/coach_transcripts_5071/after/: conversations held under the deployed
    contract and the coach-session skill's ORDER section. A fixture with ``continues`` is the same
    conversation resumed after a gap over 45 minutes (same Hevy routine id, compared off-repo); it is
    joined onto the conversation it continues, never scored on its own.

Three measures per conversation:
  * order violations (`coach_context.order_violations`);
  * context sources — the `coach_context.PRE_FLIGHT` members reached before the first planning call;
  * May frame on the payload — whether `plan_next_session` / `get_coach_session_packet` carried
    `coach_context.may_frame`: no before the deploy (the field did not exist), yes after when the
    window logged no `coach context could not be assembled` line (the attach helper's only failure
    path). Whether the chat then QUOTED the frame is in the owner's words, which are not logged and
    not kept here.

THE PACKET'S lift_history (#5501, option (a)). Since #5501 `get_coach_session_packet` carries per-lift history for
the day's programmed lifts, and `coach_context.PRE_FLIGHT` lets a packet call that CARRIED it satisfy the
exercise_history and exercise_notes members (`coach_context.call_tokens`). An order violation is therefore a planning
call reached before {get_exercise_history OR a packet call carrying lift_history} and {get_exercise_notes OR the same}.
A fixture records that on the packet call itself — ``{"tool": "get_coach_session_packet", "lift_history": "measured"}``
— read off the packet's own ``[#5501] coach packet lift_history state=<state>`` log line in the same request. A packet
call with no such field (every fixture captured before #5501 deployed) is scored exactly as before: it never claimed
the history.

PROJECTION (``--project-lift-history``): the real AFTER conversations re-scored as if each packet call had carried
lift_history (state measured) — labelled ``after (projected #5501)``, never a real conversation. It is what option (a)
does to the same call sequences; the live proof is the first real conversation captured after the deploy.

FALLBACK (``--synthesized``): the earlier AFTER, kept and labelled as such — each BEFORE conversation
re-ordered to the contract by `to_contract`. It is what the contract asks for, not what happened.

    python3 scripts/coach_transcript_eval_5071.py               # the before/after table (real)
    python3 scripts/coach_transcript_eval_5071.py --markdown    # the same table as markdown
    python3 scripts/coach_transcript_eval_5071.py --json        # machine-readable
    python3 scripts/coach_transcript_eval_5071.py --synthesized # the to_contract fallback
    python3 scripts/coach_transcript_eval_5071.py --markdown --project-lift-history  # + the #5501 projection rows
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training import coach_context  # noqa: E402

FIXTURE_DIR = os.path.join(_REPO, "tests", "fixtures", "coach_transcripts_5071")
AFTER_DIR = os.path.join(FIXTURE_DIR, "after")
# Wave 2 (PR #5177) deployed the contract and the context attach: CI/CD run 39286310627, Deploy success at this instant.
CONTRACT_DEPLOYED_UTC = "2026-10-19T16:53:00Z"


def _tool(c: Any) -> str:
    return c if isinstance(c, str) else str((c or {}).get("tool") or "")


def to_contract(calls: list[Any]) -> list[Any]:
    """The same conversation in the contract's order: for each pre-flight member it never reached, or reached
    only after the first planning call, that member's first tool is called (once) before that call. Nothing else moves."""
    first = next((i for i, c in enumerate(calls) if coach_context.stage_of(c) is not None), len(calls))
    before = set().union(*(coach_context.call_tokens(c) for c in calls[:first]))
    tools = [ts[0] for ts in coach_context.PRE_FLIGHT.values() if not before.intersection(ts)]
    missing = [{"tool": t, "synthesized": "pre-flight, per the contract"} for t in dict.fromkeys(tools)]
    return calls[:first] + missing + calls[first:]


def load_fixtures(path: str = FIXTURE_DIR) -> list[dict[str, Any]]:
    """Every ``*.json`` directly in ``path`` (sub-directories are not read), sorted by name."""
    out = []
    for name in sorted(os.listdir(path)):
        if name.endswith(".json"):
            with open(os.path.join(path, name), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def join_continuations(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per conversation: a ``continues`` fixture's calls appended to its parent's. A continuation whose
    parent is not in the set raises — it would otherwise be scored as a conversation of its own."""
    by_name = {
        fx["conversation"]: dict(fx, tool_calls=list(fx["tool_calls"]), continued_by=[]) for fx in fixtures if not fx.get("continues")
    }
    for fx in sorted((f for f in fixtures if f.get("continues")), key=lambda f: f["window_utc"][0]):
        parent = by_name.get(fx["continues"])
        if parent is None:
            raise ValueError(f"{fx['conversation']} continues {fx['continues']}, which is not in the set")
        parent["tool_calls"] += fx["tool_calls"]
        parent["continued_by"].append(fx["conversation"])
        parent["window_utc"] = [parent["window_utc"][0], fx["window_utc"][1]]
        parent["coach_context_failures_logged"] = (parent.get("coach_context_failures_logged") or 0) + (
            fx.get("coach_context_failures_logged") or 0
        )
    return sorted(by_name.values(), key=lambda f: f["window_utc"][0])


# The members that arrive only on the packet's `coach_context` — before the deploy the packet carried none of them.
PACKET_MEMBERS = tuple(m for m, tools in coach_context.PRE_FLIGHT.items() if tools == ("get_coach_session_packet",))


def context_sources(calls: list[Any], contract_live: bool = True) -> list[str]:
    """The `coach_context.PRE_FLIGHT` members reached before the first planning call (plan, draft or commit). Before
    the deploy (``contract_live=False``) a packet call reached none of `PACKET_MEMBERS`: the field did not exist."""
    first = next((i for i, c in enumerate(calls) if coach_context.stage_of(c) not in (None, "stage_2")), len(calls))
    seen = set().union(*(coach_context.call_tokens(c) for c in calls[:first]))
    reached = [m for m, tools in coach_context.PRE_FLIGHT.items() if seen.intersection(tools)]
    return reached if contract_live else [m for m in reached if m not in PACKET_MEMBERS]


def packet_before_planning(calls: list[Any]) -> bool:
    first = next((i for i, c in enumerate(calls) if coach_context.stage_of(c) not in (None, "stage_2")), len(calls))
    return any(_tool(c) == "get_coach_session_packet" for c in calls[:first])


def contract_live(fx: dict[str, Any]) -> bool:
    return fx["window_utc"][0] >= CONTRACT_DEPLOYED_UTC


def may_frame_on_payload(fx: dict[str, Any]) -> Optional[bool]:
    """False before the deploy (no such field), True after when no assembly failure was logged, None if unknown."""
    if not contract_live(fx):
        return False
    failures = fx.get("coach_context_failures_logged")
    return None if failures is None else failures == 0


def _row(fx: dict[str, Any], phase: str) -> dict[str, Any]:
    calls = fx["tool_calls"]
    return {
        "phase": phase,
        "conversation": fx["conversation"],
        "continued_by": fx.get("continued_by", []),
        "calls": len(calls),
        "violations": coach_context.order_violations(calls),
        "context_sources": context_sources(calls, contract_live(fx)),
        "packet_before_planning": packet_before_planning(calls),
        "may_frame_on_payload": may_frame_on_payload(fx),
    }


PROJECTED = "after (projected #5501)"


def project_lift_history(fx: dict[str, Any]) -> dict[str, Any]:
    """PROJECTION, not a conversation: the same calls, each packet call marked as having carried lift_history."""
    calls = [
        dict(c, lift_history="measured") if isinstance(c, dict) and c.get("tool") == "get_coach_session_packet" else c
        for c in fx["tool_calls"]
    ]
    return dict(fx, tool_calls=calls)


def evaluate_real(before: list[dict[str, Any]], after: list[dict[str, Any]], projected: bool = False) -> list[dict[str, Any]]:
    """The before/after rows over real conversations only — no synthesized call anywhere. ``projected`` appends the
    #5501 projection rows (`project_lift_history` over the AFTER set), each labelled as a projection."""
    joined = join_continuations(after)
    rows = [_row(fx, "before") for fx in join_continuations(before)] + [_row(fx, "after") for fx in joined]
    if projected:
        rows += [_row(project_lift_history(fx), PROJECTED) for fx in joined]
    return rows


def evaluate(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FALLBACK (synthesized AFTER): each conversation and the same conversation re-ordered by `to_contract`."""
    rows = []
    for fx in fixtures:
        calls = fx["tool_calls"]
        rows.append(
            {
                "conversation": fx["conversation"],
                "calls": len(calls),
                "before": coach_context.order_violations(calls),
                "after": coach_context.order_violations(to_contract(calls)),
                "after_is": "synthesized by to_contract, not a real conversation",
            }
        )
    return rows


def _violation_text(v: list[dict[str, Any]]) -> str:
    return "; ".join(x["code"] + (f" (missing {', '.join(x['missing'])})" if x["missing"] else "") for x in v) or "none"


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    n_members = len(coach_context.PRE_FLIGHT)
    for phase in dict.fromkeys(r["phase"] for r in rows):
        rs = [r for r in rows if r["phase"] == phase]
        out[phase] = {
            "conversations": len(rs),
            "with_violations": sum(1 for r in rs if r["violations"]),
            "violations": sum(len(r["violations"]) for r in rs),
            "context_sources_reached": f"{sum(len(r['context_sources']) for r in rs)}/{n_members * len(rs)}",
            "packet_first": sum(1 for r in rs if r["packet_before_planning"]),
            "may_frame_on_payload": sum(1 for r in rs if r["may_frame_on_payload"]),
            "per_member": {m: sum(1 for r in rs if m in r["context_sources"]) for m in coach_context.PRE_FLIGHT},
        }
    return out


def markdown(rows: list[dict[str, Any]]) -> str:
    n = len(coach_context.PRE_FLIGHT)
    yn = {True: "yes", False: "no", None: "unknown"}
    lines = [
        "| phase | conversation | calls | order violations | context sources before planning | May frame on payload |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        name = r["conversation"] + (f" (+ {', '.join(r['continued_by'])})" if r["continued_by"] else "")
        srcs = f"{len(r['context_sources'])}/{n}" + (f" ({', '.join(r['context_sources'])})" if r["context_sources"] else "")
        if r["packet_before_planning"] and not set(PACKET_MEMBERS) & set(r["context_sources"]):
            srcs += " (packet called first, but it carried no coach_context before the deploy)"
        lines.append(
            f"| {r['phase']} | {name} | {r['calls']} | {_violation_text(r['violations'])} | {srcs} | {yn[r['may_frame_on_payload']]} |"
        )
    s = summarize(rows)
    lines.append("")
    lines.append("| phase | conversations | with a violation | context sources reached | packet before planning | May frame on payload |")
    lines.append("|---|---|---|---|---|---|")
    for phase, p in s.items():
        lines.append(
            f"| {phase} | {p['conversations']} | {p['with_violations']} | {p['context_sources_reached']} | "
            f"{p['packet_first']}/{p['conversations']} | {p['may_frame_on_payload']}/{p['conversations']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--synthesized", action="store_true", help="FALLBACK: the to_contract re-ordering, not a real AFTER")
    ap.add_argument(
        "--project-lift-history", action="store_true", help="#5501: + the AFTER set re-scored as if the packet carried lift_history"
    )
    args = ap.parse_args(argv)
    if args.synthesized:
        rows = evaluate(load_fixtures())
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        print("FALLBACK: the AFTER below is SYNTHESIZED by to_contract, not a real conversation.")
        for r in rows:
            print(f"{r['conversation']} ({r['calls']} calls)")
            for label in ("before", "after"):
                print(f"  {label:6s} {len(r[label])} violation(s): {_violation_text(r[label])}")
        return 0
    rows = evaluate_real(load_fixtures(), load_fixtures(AFTER_DIR), projected=args.project_lift_history)
    if args.json:
        print(json.dumps({"rows": rows, "summary": summarize(rows)}, indent=2))
    elif args.markdown:
        print(markdown(rows))
    else:
        for r in rows:
            extra = f" + {', '.join(r['continued_by'])}" if r["continued_by"] else ""
            print(f"[{r['phase']}] {r['conversation']}{extra} ({r['calls']} calls)")
            print(f"  violations: {_violation_text(r['violations'])}")
            print(f"  context sources before planning: {', '.join(r['context_sources']) or 'none'}")
            print(f"  May frame on payload: {r['may_frame_on_payload']}")
        print(json.dumps(summarize(rows), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
