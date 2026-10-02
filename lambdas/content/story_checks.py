"""content/story_checks.py — the Story Desk's output gates (#4531, #4535, #4538).

Every installment the desk writes — a chronicle post or a Panel episode — passes these
before it can be staged. Each check returns a list of findings (empty = pass); a writer
regenerates once with the findings, and a second failure stops the week rather than
shipping it. Pure functions: no boto3, no model calls.

  * ``completeness``   — the text ends where the writer ended it (#4535: two installments
                         shipped cut off because nothing read ``stop_reason`` or looked at
                         the last sentence and the footer).
  * ``story_door``     — no cycle / reset / attempt counts on a reader surface (owner
                         ruling 2026-09-26; ADR-157 point 5 extended from recap cards to the
                         story door, #4538), and none of the absence phrasings that read an
                         export lag as a behaviour.
  * ``ungrounded_numbers`` — every figure in the text exists in the week's dossier
                         (ADR-104: claims ⊆ what the writer was given).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Set

# ── completeness ─────────────────────────────────────────────────────────────

_TERMINAL = re.compile(r"[.!?…\"”’)\]*_]\s*$")


def completeness(text: str, *, stop_reason: Optional[str], footer_pattern: Optional[str] = None) -> List[str]:
    """Findings when a generated body is not a finished piece.

    ``stop_reason`` is the model's own verdict — anything but ``end_turn`` means the
    reply was cut, whatever the text looks like. ``footer_pattern`` (a regex) pins the
    closing line a format requires (the chronicle's ``*Week N of The Measured Life*``)."""
    findings: List[str] = []
    if stop_reason is not None and stop_reason != "end_turn":
        findings.append(f"incomplete: stop_reason={stop_reason} (the reply was cut before the writer finished)")
    body = (text or "").rstrip()
    if not body:
        return findings + ["incomplete: empty body"]
    if footer_pattern:
        if not re.search(footer_pattern, body[-300:]):
            findings.append(f"incomplete: the closing footer ({footer_pattern}) is missing")
        body = re.sub(footer_pattern + r"\s*$", "", body).rstrip().rstrip("-").rstrip()
    last = body.splitlines()[-1].strip() if body.splitlines() else ""
    if last and not _TERMINAL.search(last):
        findings.append(f"incomplete: the last line ends mid-sentence ({last[-60:]!r})")
    return findings


# ── the story door ───────────────────────────────────────────────────────────

_ORDINALS = (
    r"second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|"
    r"fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|\d+(?:st|nd|rd|th)"
)
_CARDINALS = (
    r"two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|dozen|\d+"
)
_COUNT_NOUNS = r"resets?|restarts?|attempts?|starts?|tries|try|cycles?|launch(?:es)?|false starts?|do-overs?"

# "the fifteenth reset", "16th start", "fifteen resets", "15 attempts", "cycle 17", "reset number 15",
# "for the fifteenth time". A bare "reset" (a recovery reset, a reset week) is fine — only a COUNT is not.
_COUNT_PATTERNS = [
    re.compile(rf"\b(?:{_ORDINALS})\s+(?:(?:real|actual|official|failed|new|fresh)\s+)?(?:{_COUNT_NOUNS})\b", re.IGNORECASE),
    re.compile(
        rf"\b(?:{_CARDINALS})(?:,\s*maybe\s+(?:{_CARDINALS}))?\s+(?:(?:prior|previous|earlier|failed|false)\s+)?(?:{_COUNT_NOUNS})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bcycle\s*(?:#\s*)?\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:reset|attempt|restart)\s+(?:number|no\.?|#)\s*\d+\b", re.IGNORECASE),
    re.compile(rf"\bfor the (?:{_ORDINALS}) time\b", re.IGNORECASE),
]
# Words that legitimately follow a small cardinal and would otherwise trip the 'starts' noun —
# "three starts to the week" is rare; "two tries" at a lift is fine only with a lift named. Kept narrow:
# the gate errs toward a regenerate, which costs one call, never toward a published count.

# The machinery's own vocabulary is not reader copy: no reader knows the desk, the dossier or the ledger.
_BACKSTAGE = re.compile(r"\b(?:the desk|desk (?:flagged|noted|says)|dossier|story budget|season ledger|the ledger)\b", re.IGNORECASE)

# An export lag narrated as a behaviour (#4532). The dossier marks such days NOT_YET_EXPORTED;
# these phrasings are what a writer reaches for when it reads that as silence.
_ABSENCE_AS_BEHAVIOUR = [
    re.compile(r"\b(?:food|meal|nutrition)\s+log(?:ging)?\s+(?:went|has gone|had gone|goes)\s+(?:dark|quiet|silent)\b", re.IGNORECASE),
    re.compile(r"\bstopped\s+logging\b", re.IGNORECASE),
    re.compile(r"\bnot a technical gap\b", re.IGNORECASE),
]


def story_door(text: str, *, not_yet_exported: Iterable[str] = ()) -> List[str]:
    """Reader-surface findings: a cycle/reset/attempt count, or an export lag told as silence.

    ``not_yet_exported`` is the dossier's list of sources whose window is not fully landed; the
    absence phrasings are only findings when such a source exists (a real, landed gap may be
    reported — as a fact with its dates, never as a motive)."""
    findings: List[str] = []
    for pat in _COUNT_PATTERNS:
        for m in pat.finditer(text or ""):
            findings.append(f"story-door: a cycle/attempt count is not reader copy (owner ruling 2026-09-26): {m.group(0)!r}")
    for m in _BACKSTAGE.finditer(text or ""):
        findings.append(f"backstage: {m.group(0)!r} is the machinery's word, not the reader's — say what the data shows")
    if list(not_yet_exported):
        for pat in _ABSENCE_AS_BEHAVIOUR:
            for m in pat.finditer(text or ""):
                findings.append(f"absence-as-behaviour: {m.group(0)!r} — the window is not fully exported yet; say 'not yet exported'")
    return findings


# ── number grounding ─────────────────────────────────────────────────────────

_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")
# Figures a writer may use without the dossier: small counts, the clock, and calendar words.
_ALWAYS_OK_MAX = 12


def _numeric_values(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            whole = m.group(1).replace(",", "")
            yield float(f"{whole}.{m.group(2)}") if m.group(2) else float(whole)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numeric_values(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _numeric_values(v)
    else:  # Decimal and friends
        try:
            yield float(obj)
        except (TypeError, ValueError):
            return


def allowed_numbers(*sources: Any) -> Set[str]:
    """Every rendering of every figure in the sources a writer may legitimately print:
    the value itself, its one-decimal and integer roundings, and the magnitude of a signed delta."""
    out: Set[str] = set()
    for src in sources:
        for v in _numeric_values(src):
            for x in (v, abs(v)):
                out.add(_fmt(x))
                out.add(_fmt(round(x, 1)))
                out.add(_fmt(round(x)))
                out.add(_fmt(int(x)))  # truncation: "56.8 ms" is fairly told as "56"
    return out


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.10g}"


def ungrounded_numbers(text: str, allowed: Set[str]) -> List[str]:
    """Findings for each figure in ``text`` that no dossier value renders to.

    Small integers (counts of days, sessions, coaches) and four-digit years are always allowed;
    so are clock times ("5:12 AM" — the minutes are part of a session's logged start)."""
    findings: List[str] = []
    scrubbed = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text or "")  # clock times
    for m in _NUM.finditer(scrubbed):
        whole = m.group(1).replace(",", "")
        raw = f"{whole}.{m.group(2)}" if m.group(2) else whole
        val = float(raw)
        if val <= _ALWAYS_OK_MAX or (1900 <= val <= 2100 and not m.group(2)):
            continue
        if _fmt(val) in allowed:
            continue
        findings.append(f"ungrounded number: {m.group(0)!r} is not in the week's dossier")
    return findings


def all_findings(
    text: str,
    *,
    stop_reason: Optional[str],
    allowed: Set[str],
    not_yet_exported: Iterable[str] = (),
    footer_pattern: Optional[str] = None,
) -> List[str]:
    """The full gate a staged installment must pass."""
    return (
        completeness(text, stop_reason=stop_reason, footer_pattern=footer_pattern)
        + story_door(text, not_yet_exported=not_yet_exported)
        + ungrounded_numbers(text, allowed)
    )
