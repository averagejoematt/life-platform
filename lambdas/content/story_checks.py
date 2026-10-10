"""content/story_checks.py — the Story Desk's output gates (#4531, #4535, #4538).

Every installment the desk writes — a chronicle post or a Panel episode — passes these
before it can be staged. Each check returns a list of findings (empty = pass); a writer
regenerates once with the findings, and a second failure stops the week rather than
shipping it. Pure functions: no boto3, no model calls.

  * ``completeness``   — the text ends where the writer ended it (#4535: two installments
                         shipped cut off because nothing read ``stop_reason`` or looked at
                         the last sentence and the footer).
  * ``reader_surface`` — THE shared reader-surface check (#4538): no cycle / reset / attempt
                         counts (owner ruling 2026-09-26; ADR-157 point 5 extended from recap
                         cards to the story door) and no off-record specifics (a family member
                         or partner, his employer or colleagues). Every publishing path calls
                         this one function at its own chokepoint — the chronicle handler, the
                         "previously on" recap and the Panel (desk and legacy writers) — so a
                         writer that bypasses the desk cannot bypass the door.
  * ``story_door``     — ``reader_surface`` plus the desk writers' own findings: the
                         machinery's vocabulary, and the absence phrasings that read an
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

# The rule is keyed on STRUCTURE — a number standing next to the restart vocabulary — never on one phrase
# (owner rulings 2026-09-19 "remove attempt 17" and 2026-09-26 "no 17th start, 16 earlier starts, attempt count or
# reset count on any reader surface"; ADR-157 point 5). Five shapes, each with its own pattern below:
#   ordinal + noun      "the fifteenth reset", "16th start", "his third try at this"
#   cardinal + nouns    "fifteen resets", "16 earlier starts", "a 17-attempt history"
#   noun + number       "attempt 17", "ATTEMPT #17", "reset number 15", "cycle seventeen", "#attempt17"
#   a count of times    "for the fifteenth time", "started 16 times", "17th time's the charm"
#   a tally             "16 lost · 0 kept", "sixteen times the weight came off"
# A bare "reset" (a recovery reset, a reset week) is fine — only a COUNT is not.
_UNITS = r"one|two|three|four|five|six|seven|eight|nine"
_TENS = r"twenty|thirty|forty|fifty"
_CARD_WORDS = (
    rf"(?:{_TENS})(?:[- ](?:{_UNITS}))?|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|dozen"
)
_ORD_WORDS = (
    rf"(?:{_TENS})[- ](?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)|"
    r"second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|"
    r"fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|thirtieth|fortieth|fiftieth"
)
_ORDINALS = rf"{_ORD_WORDS}|\d+(?:st|nd|rd|th)"
_CARDINALS = rf"{_CARD_WORDS}|\d+"
# An ordinal counts ONE thing ("the 17th start"); a cardinal counts several ("16 starts"). Holding each to its own
# grammatical number is what lets a verb through: "October 4th starts cold", "the five start times".
_NOUN_ONE = r"reset|restart|relaunch|attempt|start|try|cycle|launch|false start|do-over|iteration|beginning|go-round"
_NOUN_MANY = r"resets|restarts|relaunches|attempts|starts|tries|cycles|launches|false starts|do-overs|iterations|beginnings|go-rounds"

# A numbered label is not a tally: "Day 3 starts", "week two tries his patience", "set 4 starts".
_LABELS = ("day", "week", "month", "session", "episode", "set", "phase", "round", "at", "chapter", "block", "stage", "step", "lap", "mile")
_LABELLED = "".join(rf"(?<!\b{w}\s)" for w in _LABELS)
# Nor is the tail of a date, a clock time or a decimal: "9/6 starts", "5:30 starts", "2026-09-06 starts".
_NOT_A_FRAGMENT = r"(?<![\d/:.,-])"
# "to reset 3 …", "will attempt 5 …": the vocabulary used as a verb takes an object, not a serial number.
_NOT_A_VERB = "".join(rf"(?<!\b{w}\s)" for w in ("to", "will", "would", "can", "could", "might", "ll"))
# A number that measures something else: "the cycle two days ago", "a reset three weeks in", "attempt 5 reps".
_MEASURE = (
    r"days?|weeks?|months?|years?|hours?|hrs?|minutes?|mins?|seconds?|times?|nights?|lbs?|pounds?|kg|kilos?|reps?|sets?|"
    r"sessions?|workouts?|miles?|km|steps?|calories|kcal|grams?|g|percent|points?|more"
)
_RESTARTED = r"started|restarted|reset|relaunched|begun|began"
_FLAGS = re.IGNORECASE

_COUNT_PATTERNS = [
    # ordinal + noun
    re.compile(
        rf"\b(?P<num>{_ORDINALS})\s+(?:(?:real|actual|official|failed|new|fresh|counted|public)\s+)?(?P<noun>{_NOUN_ONE})\b", _FLAGS
    ),
    re.compile(rf"\b(?P<num>{_ORDINALS})\s+go\s+(?:at|around)\b", _FLAGS),
    # cardinal + nouns
    re.compile(
        rf"{_LABELLED}{_NOT_A_FRAGMENT}\b(?P<num>{_CARDINALS})(?:,\s*maybe\s+(?:{_CARDINALS}))?\s+"
        rf"(?:(?:prior|previous|earlier|failed|false|abandoned|other|counted)\s+)?(?P<noun>{_NOUN_MANY})\b",
        _FLAGS,
    ),
    re.compile(rf"{_NOT_A_FRAGMENT}\b(?P<num>{_CARDINALS})-(?P<noun>{_NOUN_ONE})\b", _FLAGS),
    # noun + number — marked ("reset number 15", "start #17") or bare ("attempt 17", "cycle seventeen", "#attempt17").
    # Bare, the number is at most two digits: a restart count is small, and "attempt 225" is a barbell.
    re.compile(rf"\b(?:{_NOUN_ONE}|{_NOUN_MANY})\s+(?:number|no\.?|#)\s*(?P<num>\d+|{_CARD_WORDS})\b", _FLAGS),
    re.compile(
        rf"{_NOT_A_VERB}\b(?P<noun>reset|restart|relaunch|attempt|cycle)(?:\s*#?\s*(?P<num>\d{{1,2}})|\s+(?P<word>{_CARD_WORDS}))\b"
        rf"(?![.:/,]\d)(?!\s*(?:{_MEASURE})\b)",
        _FLAGS,
    ),
    # a count of times
    re.compile(
        rf"\bfor the (?P<num>{_ORDINALS}) time\b"
        r"(?!\s+(?:this\s+(?:week|month|morning)|today|tonight|in\s+(?:a|as\s+many|\w+)\s+(?:days?|weeks?|nights?|mornings?|sessions?)))",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?:{_RESTARTED})\s+(?:(?:over|again|this)\s+)?(?:(?:some|about|around|at least|nearly|almost)\s+)?(?P<num>{_CARDINALS})\s+times\b"
        r"(?!\s+(?:this|that|a|per|each)\s+(?:week|month|day))",
        _FLAGS,
    ),
    re.compile(rf"\b(?P<num>{_CARDINALS})\s+times\s+(?:he|matt(?:hew)?)(?:\s+(?:has|had)|['’][sd])?\s+(?:{_RESTARTED}|tried)\b", _FLAGS),
    re.compile(rf"\bthe\s+(?P<num>{_ORDINALS})\s+time\s+he(?:\s+(?:has|had)|['’][sd])?\s+(?:{_RESTARTED}|tried)\b", _FLAGS),
    re.compile(rf"\b(?P<num>{_ORDINALS})\s+time(?:['’]s|\s+is|\s+was)?\s+(?:the\s+|a\s+)?charm\b", _FLAGS),
    # a tally of the earlier ones
    re.compile(
        rf"\b(?P<num>{_CARDINALS})\s+(?:lost|failed|abandoned|quit)\s*(?:[·•|,;/—–-]|and|but)\s*"
        rf"(?:{_CARDINALS}|zero|none|no|nothing)\s+(?:kept|stayed off|finished|completed|held|stuck)\b",
        _FLAGS,
    ),
    re.compile(
        rf"\b(?P<num>{_CARDINALS}|zero)\s+times\s+(?:the\s+weight|it)\s+(?:came\s+off|came\s+back|stayed\s+off|held)\b",
        _FLAGS,
    ),
]

_MONTH_BEFORE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+(?:the\s+)?$",
    re.IGNORECASE,
)
_SLEEP_AFTER = re.compile(r"\s+(?:of\s+(?:rem|sleep|deep|light|breath\w*)|per\s+night|a\s+night)\b", re.IGNORECASE)
_LIFT_AFTER = re.compile(r"\s+(?:at|on|with)\s+\d", re.IGNORECASE)
# A constructed surface — a card, a caption, a hashtag line: no free prose — can afford to refuse the word itself.
_FRAME_WORD = re.compile(r"\battempts?\b", re.IGNORECASE)


def _is_a_legitimate_number(text: str, m: "re.Match[str]") -> bool:
    """True when the number beside the vocabulary is a date, a year, a sleep stage count or a barbell —
    the false positives a hold-severity chokepoint cannot afford (a held week costs a week)."""
    groups = m.groupdict()
    num, noun = groups.get("num") or "", (groups.get("noun") or "").lower()
    if num.isdigit() and 1900 <= int(num) <= 2100:
        return True  # "2026 starts"
    if num and _MONTH_BEFORE.search(text[: m.start("num")]):
        return True  # "October 4 starts cold", "the September 6th start"
    after = text[m.end() :]
    if noun.startswith("cycle") and _SLEEP_AFTER.match(after):
        return True  # "5 cycles of REM"
    if noun in ("attempt", "attempts", "try", "tries") and _LIFT_AFTER.match(after):
        return True  # "two attempts at 225", "his second try at 315"
    return False


def _count_findings(text: str) -> List[str]:
    """Every cycle/reset/attempt count in ``text`` — the count half of ``reader_surface``, one finding per phrase."""
    seen: Set[str] = set()
    for pat in _COUNT_PATTERNS:
        for m in pat.finditer(text or ""):
            if not _is_a_legitimate_number(text, m):
                seen.add(m.group(0))
    return [
        f"story-door: a cycle/attempt count is not reader copy (owner ruling 2026-09-26): {p!r}"
        for p in sorted(seen, key=(text or "").index)
    ]


# Off the record (#4538). The journal is deep background: its weather may inform a writer, its specifics may not
# reach a reader — and the specifics that identify are the people around him and his working life. One label,
# stated once, rides on every journal-derived input a writer is shown (``emails/chronicle_data`` is the one live
# reader of journal text; the desk's dossier counts entries and never reads them).
OFF_RECORD_JOURNAL_HEADER = (
    "=== JOURNAL (OFF THE RECORD — never quote directly; no third party named or described, "
    "no employer, colleague or career specifics) ==="
)
_HIS = r"(?:his|matt(?:hew)?['’]s)"
_OFF_RECORD = [
    (
        "a third party",
        re.compile(
            rf"\b{_HIS}\s+(?:wife|husband|girlfriend|boyfriend|fianc[eé]e?|partner|ex-wife|ex-girlfriend|mother|father|mom|mum|dad|"
            r"brother|sister|son|daughter|kids?|children|parents?|family|roommate|in-laws?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "his working life",
        re.compile(rf"\b{_HIS}\s+(?:employer|boss|manager|co-?workers?|colleagues?|clients?|day job|workplace|career)\b", re.IGNORECASE),
    ),
    # a named employer: "his job at Initech", "a role at Globex" — the capital is the tell, so this one is case-sensitive
    ("his working life", re.compile(r"\b(?:[Jj]ob|[Rr]ole|[Pp]osition|[Ee]mployed|[Cc]areer)\s+(?:at|with)\s+[A-Z][\w&.-]+")),
]

# The machinery's own vocabulary is not reader copy: no reader knows the desk, the dossier or the ledger.
_BACKSTAGE = re.compile(r"\b(?:the desk|desk (?:flagged|noted|says)|dossier|story budget|season ledger|the ledger)\b", re.IGNORECASE)

# Terms the reader-vocabulary registry (site/data/glossary.json) rules "cut": a Lambda cannot read the site tree, so
# this is a copy, and tests/test_story_door_pace_flag_4674.py holds it inside the registry's cut terms (#4674).
# A word gap matches any spelling a writer or a field name reaches for: "pace flag", "pace_flag", "pace-flag" (the
# non-breaking and en-dash hyphens too).
_CUT_TERMS = ("pace flag",)
_CUT_RES = tuple(
    (t, re.compile(r"(?<![A-Za-z0-9])" + re.escape(t).replace(r"\ ", r"[\s_\-\u2010\u2011\u2013]+") + r"(?![A-Za-z0-9])", re.I))
    for t in _CUT_TERMS
)

# An export lag narrated as a behaviour (#4532). The dossier marks such days NOT_YET_EXPORTED;
# these phrasings are what a writer reaches for when it reads that as silence.
_ABSENCE_AS_BEHAVIOUR = [
    re.compile(r"\b(?:food|meal|nutrition)\s+log(?:ging)?\s+(?:went|has gone|had gone|goes)\s+(?:dark|quiet|silent)\b", re.IGNORECASE),
    re.compile(r"\bstopped\s+logging\b", re.IGNORECASE),
    re.compile(r"\bnot a technical gap\b", re.IGNORECASE),
]


def reader_surface(text: str, *, constructed: bool = False) -> List[str]:
    """THE shared reader-surface check (#4538): findings for a cycle/reset/attempt count (ordinal or cardinal,
    title or body), for off-record specifics, and for a term the reader-vocabulary registry cuts (#4674). Pure and
    deterministic, so every publishing path can afford it at its own chokepoint: the chronicle handler, the recap,
    the Panel's per-line gate and its titles.

    ``constructed=True`` is for a surface with no free prose — a card, a caption, a hashtag line (the recap
    cards' own rule, ``web/recap_layouts``): there the frame word itself is refused, count or no count."""
    findings = _count_findings(text)
    if constructed:
        for m in _FRAME_WORD.finditer(text or ""):
            findings.append(f"story-door: the frame is the experiment, not an attempt at it (owner ruling 2026-09-19): {m.group(0)!r}")
    for what, pat in _OFF_RECORD:
        for m in pat.finditer(text or ""):
            findings.append(f"off-record: {what} stays out of reader copy: {m.group(0)!r}")
    # #4674: a registry-cut term at the final publish check, not only the desk writers' door — the chronicle handler,
    # the recap and the Panel's titles, excerpts and spoken lines all pass through here.
    for term, rx in _CUT_RES:
        for m in rx.finditer(text or ""):
            findings.append(f"vocabulary: {m.group(0)!r} is a term the site does not use with readers ({term!r} is cut in the registry)")
    return findings


def story_door(text: str, *, not_yet_exported: Iterable[str] = ()) -> List[str]:
    """``reader_surface`` plus the desk writers' own findings: backstage words, or an export lag told as silence.

    ``not_yet_exported`` is the dossier's list of sources whose window is not fully landed; the
    absence phrasings are only findings when such a source exists (a real, landed gap may be
    reported — as a fact with its dates, never as a motive)."""
    findings = reader_surface(text)
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
