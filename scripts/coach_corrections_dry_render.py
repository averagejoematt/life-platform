#!/usr/bin/env python3
"""coach_corrections_dry_render.py — which open corrections each coach sees, before vs after #6149.

READ-ONLY. One DynamoDB Query of the `coach_corrections` partition (through
`coach_corrections.list_corrections`, the module's own reader) and nothing else: no write,
no status change, no SSM, no Bedrock, no Telegram. The scoping is the module's own
(`open_corrections_for`) run against the rows already read, so this prints exactly what the
brief, the Telegram chat and the Claude coach-session packet would select.

  before  brief = `surface="coach_brief"`; chat = nothing; packet = nothing
  after   all three = `OWNER_FACING_SURFACES` (#6149), same per-coach bound, newest-first

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


def render(rows: list, *, with_text: bool = False) -> str:
    opened = [r for r in rows if r.get("status") == "open"]
    fake = _RowsTable(opened)
    lines = [f"open corrections: {len(opened)} (of {len(rows)} in the ledger)", ""]
    reached_after: set = set()
    for channel, roster, before, after in CHANNELS:
        lines.append(f"== {channel} ==")
        for coach in roster:
            b = cc.open_corrections_for(fake, coach=coach, **before) if before else []
            a = cc.open_corrections_for(fake, coach=coach, **after)
            reached_after.update(r.get("sk") for r in a)
            lines.append(f"  {coach}: before {len(b)} -> after {len(a)}")
            for r in a:
                tag = "" if any(r.get("sk") == x.get("sk") for x in b) else "  [NEW]"
                lines.append(_line(r, with_text) + tag)
        lines.append("")
    orphans = [r for r in opened if r.get("sk") not in reached_after]
    lines.append(
        f"== open corrections no channel selects after the change (no matching coach, or past the per-coach bound): {len(orphans)} =="
    )
    lines.extend(_line(r, with_text) for r in sorted(orphans, key=lambda r: r.get("sk", ""), reverse=True))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--with-text", action="store_true", help="include correction text (PRIVATE output — never commit or paste it)")
    args = ap.parse_args(argv)
    import boto3

    table = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ.get("TABLE_NAME", "life-platform"))
    print(render(cc.list_corrections(table, limit=10000), with_text=args.with_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
