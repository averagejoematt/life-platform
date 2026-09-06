#!/usr/bin/env python3
"""
check_proof_freshness.py — #3515: a deploy-time assertion that every baked
static/no-JS "proof" page (Home, Cockpit, Coaching, Story, Data, Protocols)
carries an "as of <date>" stamp no older than MAX_AGE_DAYS.

Why this exists: `scripts/v4_build_evidence.py` (the Data/Protocols pillar
generator) was NOT in `deploy/sync_site_to_s3.sh`'s builder list, so its
baked <noscript> core + OG tags only ever reflected whatever date the
generator last happened to be run by hand — the crawler/unfurl/no-JS view of
two of the five doors sat 33 days and two experiment resets stale while the
other three doors (rebuilt by their own generators every sync) stayed fresh.
Being IN the builder list fixes freshness going forward; this guard is the
belt-and-suspenders check that catches the NEXT time a builder silently drops
out of the deploy path (or a generator's best-effort offline fallback keeps
serving a stale baked block for longer than is honest).

Usage:
    python3 scripts/check_proof_freshness.py            # checks site/ in the repo
    python3 scripts/check_proof_freshness.py --root DIR # checks an alternate tree

Exit 0 if every proof page's every "as of" stamp is within MAX_AGE_DAYS of
today (Pacific, matching the site's own day frame, #1955); exit 1 and print
each stale finding otherwise.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
from common.pacific_time import pacific_today  # noqa: E402

MAX_AGE_DAYS = 7

# The pages carrying a #729/#730/#788/#804/#1395 baked static-proof block. A
# page missing from this list is simply not checked (never a false failure);
# a page listed here but absent from the tree (offline build, page removed) is
# also skipped rather than treated as an error — this guard is about STALE
# dates, not about page existence (other checks own that).
PROOF_PAGES = (
    "site/index.html",
    "site/cockpit/index.html",
    "site/coaching/index.html",
    "site/story/index.html",
    "site/data/index.html",
    "site/protocols/index.html",
)

_ASOF_RE = re.compile(r"as of (\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def find_stale(root: Path, pages=PROOF_PAGES, max_age_days: int = MAX_AGE_DAYS, today: str | None = None) -> list[str]:
    """Return one human-readable finding per stale "as of" stamp found.

    `today` is injectable (tests) — defaults to the live Pacific date so the
    real deploy-time check needs no argument.
    """
    today_d = datetime.date.fromisoformat(today or pacific_today())
    findings: list[str] = []
    for rel in pages:
        p = root / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        seen: set[str] = set()
        for m in _ASOF_RE.finditer(text):
            stamp = m.group(1)
            if stamp in seen:
                continue
            seen.add(stamp)
            try:
                stamp_d = datetime.date.fromisoformat(stamp)
            except ValueError:
                continue
            age = (today_d - stamp_d).days
            if age > max_age_days:
                findings.append(f"{rel}: 'as of {stamp}' is {age}d old (> {max_age_days}d) — rebuild before publish")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, help="repo root to check (default: this script's repo)")
    ap.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    findings = find_stale(root, max_age_days=args.max_age_days)
    if findings:
        print(f"❌ {len(findings)} stale baked 'as of' stamp(s):", file=sys.stderr)
        for f in findings:
            print(f"   {f}", file=sys.stderr)
        return 1
    print("✓ all baked proof pages carry a fresh 'as of' stamp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
