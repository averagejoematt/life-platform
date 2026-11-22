"""content/public_text_rules.py — the text rules the v9 site build gate enforces on every rendered page, in ONE place (#6177).

The build gate (``scripts/check_www_build.py`` scan, through ``scripts/www_verbatim.py``) refuses a page that carries:

  * an ISO date outside a verbatim quotation (``ISO_DATE``) — dates are written in words (owner ruling 2026-11-02);
  * a fixture sentinel (``SENTINELS``);
  * a raw coach identifier rendered as text (#5568 / #5572) — the gate derives the exact ids from the build's snapshot;
    before a snapshot exists, ``RAW_IDENTIFIER`` (any snake_case token, a ``*_coach`` persona id included) is the
    stricter superset.

Both the gate and the chapter-corrections proposal (``content.chapter_corrections.new_proposal``) import these, so a
correction the gate would reject is refused when it is proposed — not after it is approved, when it failed every site
build for hours (2026-11-22: a coach id in an evidence path, then ``/data/day/<ISO>/`` paths). Pure; no I/O.
"""

from __future__ import annotations

import re

ISO_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
SENTINELS = ("SENTINEL", "DO-NOT-PUBLISH", "POISON-HELD")
RAW_IDENTIFIER = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w-])")


def text_issues(text: str) -> list[str]:
    """Why the build gate would refuse ``text`` rendered as page copy (empty = it would pass these rules)."""
    t = str(text or "")
    out: list[str] = []
    dates = list(dict.fromkeys(ISO_DATE.findall(t)))
    if dates:
        out.append(f"an ISO date ({', '.join(dates[:3])}) — dates are written in words on the site, links included")
    out.extend(f"the fixture sentinel {s!r}" for s in SENTINELS if s in t)
    ids = list(dict.fromkeys(RAW_IDENTIFIER.findall(t)))
    if ids:
        out.append(f"an internal identifier ({', '.join(ids[:3])}) — name the coach or page in words")
    return out
