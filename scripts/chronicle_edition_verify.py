#!/usr/bin/env python3
"""scripts/chronicle_edition_verify.py — prove a DEPLOYED chapter serves the approved edition's exact text (#6193).

Owner ruling 2026-11-22 (final approval §1): publish only after "verifying the deployed texts match the approved hashes,
except for explicitly permitted presentation metadata". This is that check, read-only, over the public site:

  1. ``/api/chapters`` serves the chapter's edition, and its text hashes to the SHA-256 given on the command line (the
     hash the owner approved — the approval record is bound to the same hash);
  2. ``/story/<chapter>/`` carries every approved word in its slot (#6193 B4): the text's title line is the page heading,
     its summary line is the header summary, and inside ``data-published-body`` the BODY's prose, block for block and
     word for word, after removing ONLY ``content.chapter_editions.PERMITTED_PRESENTATION`` (evidence figures and call
     cards between paragraphs, the dated record note, a dek printed once in the header, a signature line's class, the
     title line as the heading, the summary line as the header summary). Nothing else outside the body is compared: the
     edition line, dates, addresses, corrections and approval metadata are presentation;
  3. the page's edition line is the platform's words for the served dates;
  4. with ``--archival-sha256``: ``/story/<chapter>/first-edition/`` carries the approved archival text's prose exactly, is
     ``noindex`` and canonical to the chapter's address;
  5. the feed (``/rss.xml``) still lists the chapter ONCE, under its original guid — an edition is not a new item.

A WITHDRAWN edition (#6193 B7) is reported as such — "withdrawn on <day>; the chapter serves its first edition" — and
the page is checked to carry no edition line (exit 1: the approved text is not what is deployed, by the owner's act).

    python3 scripts/chronicle_edition_verify.py --chapter week-04 --sha256 <approved hash>
    python3 scripts/chronicle_edition_verify.py --chapter week-04 --sha256 <hash> --archival-sha256 <hash>

Exit: 0 verified · 1 a difference (each named) · 3 the site could not be read. Writes nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from typing import Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
from content import chapter_editions as CE  # noqa: E402

BASE_URL = "https://averagejoematt.com"
USER_AGENT = "Mozilla/5.0 (chronicle-edition-verify)"


def http_get(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the public site, https only
        return r.read().decode("utf-8")


def _dek(page: str) -> Optional[str]:
    m = re.search(r'<p class="dek">([\s\S]*?)</p>', page or "")
    return CE._norm(m.group(1)) if m else None


def _h1(page: str) -> Optional[str]:
    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", page or "")
    return CE._norm(m.group(1)) if m else None


def _withdrawn(chapters: dict, chapter_id: str, get: Callable[[str], str], base: str) -> list:
    gone = [w for w in chapters.get("edition_withdrawals") or [] if isinstance(w, dict) and w.get("chapter_id") == chapter_id]
    if not gone:
        return []
    out = [
        f"{chapter_id}: {w.get('kind')} {w.get('number')} was WITHDRAWN by the owner on {w.get('withdrawn_on')}"
        + ("; the chapter serves its first edition" if w.get("kind") == "edition" else "; its archival page is not served")
        for w in gone
    ]
    if any(w.get("kind") == "edition" for w in gone) and "data-edition-line" in get(f"{base}/story/{chapter_id}/"):
        out.append(f"/story/{chapter_id}/ still prints an edition line after the withdrawal (rebuild the site)")
    return out


def verify(get: Callable[[str], str], chapter_id: str, sha256: str, *, archival_sha256: Optional[str] = None, base: str = BASE_URL) -> list:
    """Every difference between the deployed chapter and the approved bytes; ``[]`` = verified."""
    problems: list = []
    chapters = json.loads(get(f"{base}/api/chapters"))
    served = next((e for e in chapters.get("editions") or [] if isinstance(e, dict) and e.get("chapter_id") == chapter_id), None)
    if served is None:
        return _withdrawn(chapters, chapter_id, get, base) or [
            f"/api/chapters serves no edition of {chapter_id} (switch off, not approved, or withheld by a gate)"
        ]
    if served.get("text_sha256") != sha256 or CE.text_sha256(str(served.get("text") or "")) != sha256:
        problems.append(f"the served edition is not the approved text (served {served.get('text_sha256')}, approved {sha256})")
    page = get(f"{base}/story/{chapter_id}/")
    problems += [f"/story/{chapter_id}/: {p}" for p in CE.verify_page(page, served.get("text") or "", sha256, dek=_dek(page), h1=_h1(page))]
    line = re.search(r"data-edition-line><b[^>]*>([^<]*)</b>", page)
    try:
        want_line = CE.edition_line(served["edition"], served["revised_on"], served["first_published"])
    except (CE.EditionError, KeyError, ValueError) as exc:
        want_line = None
        problems.append(f"the served edition's dates are malformed ({exc})")
    if not line or (want_line and CE._norm(line.group(1)) != want_line):
        problems.append(f"/story/{chapter_id}/: the edition line is missing or not the platform's words ({want_line!r})")
    if archival_sha256:
        a = served.get("archival")
        if not a:
            problems.append(f"no archival rendering of {chapter_id} is served")
        else:
            if a.get("text_sha256") != archival_sha256 or CE.text_sha256(str(a.get("text") or "")) != archival_sha256:
                problems.append("the served archival rendering is not the approved text")
            arch = get(f"{base}/story/{chapter_id}/first-edition/")
            for p in CE.verify_archival_page(arch, a.get("text") or "", h1=_h1(arch)):
                problems.append(f"/story/{chapter_id}/first-edition/: {p}")
            if a.get("note") and CE._norm(a["note"]) not in CE._norm(arch):
                problems.append(f"/story/{chapter_id}/first-edition/: the platform's archival note is missing")
            if not re.search(r'<meta name="robots" content="noindex', arch):
                problems.append(f"/story/{chapter_id}/first-edition/: not noindex")
            if f'<link rel="canonical" href="{base}/story/{chapter_id}/">' not in arch:
                problems.append(f"/story/{chapter_id}/first-edition/: not canonical to the chapter's address")
    feed = get(f"{base}/rss.xml")
    url = next(
        (w.get("url") for w in chapters.get("weeks") or [] if isinstance(w, dict) and w.get("url", "").rstrip("/").endswith(chapter_id)),
        None,
    )
    if url:
        n = feed.count(f'<guid isPermaLink="true">{base}{url}</guid>')
        if n != 1:
            problems.append(f"the feed lists {url} {n} time(s), not once under its original guid")
    return problems


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a deployed chapter serves the approved edition's exact text.")
    ap.add_argument("--chapter", required=True, help="the v9 page id, week-NN")
    ap.add_argument("--sha256", required=True, help="the SHA-256 of the approved edition text")
    ap.add_argument("--archival-sha256", default=None, help="also verify the archival first-edition page against this hash")
    ap.add_argument("--base-url", default=BASE_URL)
    args = ap.parse_args(argv)
    try:
        problems = verify(
            http_get,
            args.chapter,
            args.sha256.lower(),
            archival_sha256=(args.archival_sha256 or "").lower() or None,
            base=args.base_url.rstrip("/"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"UNREADABLE: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    for p in problems:
        print(f"✗ {p}")
    if problems:
        return 1
    print(f"✓ {args.chapter}: the deployed prose is the approved text ({args.sha256[:12]}…); only permitted presentation differs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
