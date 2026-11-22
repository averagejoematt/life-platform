#!/usr/bin/env python3
"""coach_corrections_dry_render.py — which open corrections each coach sees, before vs after #6149.

READ-ONLY. One DynamoDB Query of the `coach_corrections` partition (through
`coach_corrections.list_corrections`, the module's own reader) and one SSM GetParameter (the
current experiment cycle, `coach_checkin.read_cycle`, unless `--cycle` is given) — no write,
no status change, no Bedrock, no Telegram. The scoping is the module's own
(`open_corrections_for`) run against the rows already read, so this prints exactly what the
brief, the Telegram chat and the Claude coach-session packet would select.

  before  brief = `surface="coach_brief"`; chat = nothing; packet = nothing
  after   all three = `OWNER_FACING_SURFACES` (#6149), same per-coach bound, ranked
          (a) names the coach · (b) coach-less chat · (c) coach-less current-cycle ·
          (d) older-cycle non-baseline; an older-cycle stale-baseline row is never injected.
  `--never-injected` prints only the open rows no prompt will ever carry (`never_injected`).

Default output names each correction by its `sk`, surface and error class only. The
correction TEXT is printed only with `--with-text`, for the owner's private copy — never
paste that output into the repo, an issue or a PR (the repo is public).

  python3 scripts/coach_corrections_dry_render.py
  python3 scripts/coach_corrections_dry_render.py --with-text > <private path outside the repo>
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from coach import coach_corrections as cc  # noqa: E402
from coach.persona_registry import OPERATIONAL_COACH_IDS, TEXTING_PERSONA_IDS  # noqa: E402


class _RowsTable:
    """The rows already read, served back to `open_corrections_for` — so the scoping runs
    once per coach without re-querying the live table."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, **_kw):
        return {"Items": list(self._rows)}


# (channel, roster, before-scope, after-scope). A None before-scope = the channel read nothing.
CHANNELS = (
    ("brief", tuple(OPERATIONAL_COACH_IDS), {"surface": "coach_brief"}, {"surfaces": cc.OWNER_FACING_SURFACES}),
    ("telegram_chat", tuple(TEXTING_PERSONA_IDS), None, {"surfaces": cc.OWNER_FACING_SURFACES}),
    ("session_packet", ("training",), None, {"surfaces": cc.OWNER_FACING_SURFACES}),
)


def _line(row: dict, with_text: bool) -> str:
    ref = row.get("item_ref") or {}
    out = f"    {row.get('sk')}  surface={ref.get('surface')}  coach={ref.get('coach')}  class={row.get('error_class')}"
    if with_text:
        out += f"\n        text: {row.get('correction_text')}"
    return out


def render(rows: list, *, current_cycle, with_text: bool = False) -> str:
    opened = [r for r in rows if r.get("status") == "open"]
    fake = _RowsTable(opened)
    lines = [f"open corrections: {len(opened)} (of {len(rows)} in the ledger); current cycle: {current_cycle}", ""]
    reached_after: set = set()
    for channel, roster, before, after in CHANNELS:
        lines.append(f"== {channel} ==")
        for coach in roster:
            b = cc.open_corrections_for(fake, coach=coach, current_cycle=None, **before) if before else []
            a = cc.open_corrections_for(fake, coach=coach, current_cycle=current_cycle, **after)
            reached_after.update(r.get("sk") for r in a)
            ranks = [_rank(r, coach, current_cycle) for r in a]
            by_class = " ".join(f"{k}={ranks.count(k)}" for k in "abcd")
            lines.append(f"  {coach}: before {len(b)} -> after {len(a)}  ({by_class})")
            for r, k in zip(a, ranks):
                tag = "" if any(r.get("sk") == x.get("sk") for x in b) else "  [NEW]"
                lines.append(_line(r, with_text) + f"  rank={k}" + tag)
        lines.append("")
    orphans = [r for r in opened if r.get("sk") not in reached_after]
    lines.append(
        f"== open corrections no channel selects after the change (no matching coach, or past the per-coach bound): {len(orphans)} =="
    )
    lines.extend(_line(r, with_text) for r in sorted(orphans, key=lambda r: r.get("sk", ""), reverse=True))
    return "\n".join(lines)


def _rank(row: dict, coach: str, current_cycle) -> str:
    if current_cycle is None:
        return "-"
    return "abcd"[cc.injection_rank(row, coach=coach, current_cycle=current_cycle)]


def render_never_injected(rows: list, *, current_cycle: int, with_text: bool = False) -> str:
    never = cc.never_injected(_RowsTable([r for r in rows if r.get("status") == "open"]), current_cycle=current_cycle)
    head = f"open corrections no prompt will ever carry at cycle {current_cycle}: {len(never)} (candidates to close — owner's call)"
    return "\n".join([head] + [_line(r, with_text) for r in sorted(never, key=lambda r: r.get("sk", ""), reverse=True)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--with-text", action="store_true", help="include correction text (PRIVATE output — never commit or paste it)")
    ap.add_argument("--never-injected", action="store_true", help="list only the open rows no prompt will ever carry")
    ap.add_argument("--cycle", type=int, default=None, help="current experiment cycle (default: read SSM, read-only)")
    args = ap.parse_args(argv)
    import boto3
    from coach.coach_checkin import read_cycle

    cycle = args.cycle if args.cycle is not None else read_cycle()
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ.get("TABLE_NAME", "life-platform"))
    rows = cc.list_corrections(table, limit=10000)
    if args.never_injected:
        if cycle is None:
            print("current cycle unreadable — cannot judge staleness", file=sys.stderr)
            return 2
        print(render_never_injected(rows, current_cycle=cycle, with_text=args.with_text))
    else:
        print(render(rows, current_cycle=cycle, with_text=args.with_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
