"""The journal's silence is never reader copy (#4583, #4580).

ONE pattern, read by two gates: the Story Desk (``content/story_desk.py``: journal presence is NOT a story, and
the story-auditor's privacy class "journal content or journal-silence probing" is BLOCKING) and the daily
coach-moves gate (``coach/coach_moves_sheet.py``). Live 2026-10-18 the front page served a coach line reading
"... yet 39 days of journal silence. My read is the block was never nutritional ..." because only the desk applied it.
"""

from __future__ import annotations

import re
from typing import Any

_GAP = (
    r"(?:silen(?:t|ce)|quiet|blank|empty|dark|absen(?:t|ce)|gaps?|missing|missed|unwritten|unused|untouched|dry|dormant|"
    r"no\s+entr(?:y|ies)|not\s+(?:been\s+)?(?:written|used|opened|kept|filled)|stopped|lapsed?)"
)
_J = r"(?:journal\w*|diar(?:y|ies))"
_WORDS = r"(?:\W+\w+){0,6}?\W+"

JOURNAL_SILENCE = re.compile(
    rf"\b{_J}{_WORDS}{_GAP}\b|\b{_GAP}{_WORDS}{_J}\b"
    rf"|\bno\s+{_J}|\bblank\s+page\b"
    r"|\b(?:hasn['’]?t|has\s+not|haven['’]?t|have\s+not|hadn['’]?t|didn['’]?t|did\s+not)\s+(?:written|journal(?:ed|led)|logged\s+a\s+journal)\b"
    r"|\bnot\s+(?:written|journal(?:ed|led))\s+(?:in|a\s+word)\b",
    re.IGNORECASE,
)


def mentions_journal_silence(text: Any) -> bool:
    return bool(JOURNAL_SILENCE.search(str(text or "")))
