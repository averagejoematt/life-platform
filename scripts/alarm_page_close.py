#!/usr/bin/env python3
"""scripts/alarm_page_close.py — the monthly close's alarm-page block (#4034 box 5).

Imported by `scripts/monthly_close.py` (a few-line hook, so the close script stays under its
size ceiling). Reads — never writes — `remediation-log/signal_ledger.json` through the SAME
module that writes it (`remediation/signal_identity.py`), and prints:

  * pages-sent    needs-human hand-offs first sent this month (one per signal id, i.e. one per
                  (alarm-or-check, StateTransitionedTimestamp) — a carried line is not a page)
  * pages-acted-on  those whose episode got a citation stamped after it went red
  * the ratio
  * DEMOTE candidates: every CDK alarm (deploy/alarm_discovery.py — the doc-sync inventory)
                  with ZERO acted-on pages in the trailing 90 days, awaiting the owner's ruling.
                  While the ledger has observed less than 90 days this list is labelled
                  PROVISIONAL — an alarm cannot be judged on history nobody recorded.

and FAILS the close (a `_problem`) when the ledger's merger is past its dead-man bar or the
ledger cannot be read — a pages-sent count over a gap is not a count.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "remediation"), os.path.join(_ROOT, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_SHOW_DEMOTE = 25


def alarm_inventory() -> set:
    from alarm_discovery import _auto_discover_alarm_names

    return set(_auto_discover_alarm_names() or ())


def page_block_lines(s3, month_start, month_end_exclusive, now=None, inventory=None):
    """(lines, problems) — problems are (label, message) pairs for monthly_close._problem."""
    import signal_identity as si

    now = now or datetime.now(timezone.utc)
    lines = ["\n[pages] Alarm pages (#4034 — remediation-log/signal_ledger.json, one page per signal id)"]
    try:
        ledger, _etag = si.load(s3, BUCKET)
    except Exception as e:  # noqa: BLE001
        return lines, [("UNAVAILABLE", f"signal ledger unreadable ({type(e).__name__}: {e}) — pages-sent cannot be counted")]
    problems = []
    age = si.merger_age_hours(ledger, now)
    if age is None:
        problems.append(("UNAVAILABLE", "signal ledger has never been merged — no page has an identity record yet"))
    elif age > si.MERGER_STALE_HOURS:
        problems.append(
            ("FAIL", f"signal ledger merger last ran {age / 24:.1f}d ago (> {si.MERGER_STALE_HOURS}h) — the count below has a gap")
        )
    inventory = alarm_inventory() if inventory is None else inventory
    acct = si.page_accounting(ledger, month_start, month_end_exclusive, inventory, now)
    ratio = "n/a (no pages)" if acct["ratio"] is None else f"{acct['ratio'] * 100:.0f}%"
    lines.append(f"  pages sent {acct['pages_sent']} · acted on {acct['pages_acted_on']} · ratio {ratio}")
    tag = f"PROVISIONAL — ledger covers {acct['coverage_days']:.0f} of {acct['window_days']}d" if acct["provisional"] else "90d window"
    demote = acct["demote_candidates"]
    lines.append(
        f"  DEMOTE candidates (zero acted-on pages in {acct['window_days']}d; {tag}; owner ruling required): {len(demote)} of {len(inventory)}"
    )
    for name in demote[:_SHOW_DEMOTE]:
        lines.append(f"    - {name}")
    if len(demote) > _SHOW_DEMOTE:
        lines.append(f"    ... and {len(demote) - _SHOW_DEMOTE} more (python3 scripts/alarm_page_close.py --all)")
    return lines, problems


if __name__ == "__main__":  # pragma: no cover — read-only operator view
    import boto3

    today = datetime.now(timezone.utc).date()
    _SHOW_DEMOTE = 10_000 if "--all" in sys.argv else _SHOW_DEMOTE
    out, probs = page_block_lines(boto3.client("s3"), today.replace(day=1), today)
    print("\n".join(out))
    for label, msg in probs:
        print(f"  !! {label} — {msg}")
