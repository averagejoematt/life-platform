"""reader_checks.py — the deterministic reader CHECK classes (#4185, spec §2.5).

The served coach corpus stated premises the engine's own served facts contradict —
"six days without logs" on 20 of 20 logged days, a UTC bedtime read as "4:45 AM",
"106.9 grams" that matches no served field — and the Haiku judge let each one
through. ADR-105: deterministic computation before any LLM verdict. Every class
here is a pure function (text in, findings out, no I/O), and ``merge_into_report``
folds them into the coach quality gate's report so they ride the SAME
regenerate-or-hold path (ADR-108) as ``cycle_boundary_violations`` (#1973).

The eight classes, and where each applies:

  NARRATIVE classes — run on every text the quality gate judges:
    absence_premise          a gap/silence/"went dark" premise the served gap fact refutes
    unit_number_not_served   a figure WITH a unit (g, kcal, lb, %, ms, bpm, days, hours)
                             that is not on the generation's own allow-list — a unit voids
                             the benign-small-count exemption (grounded_generation)
    unlabeled_window_figure  an average / running average / EWMA / trend figure whose
                             sentence names no window ("over N days", "since", "through")
    raw_instant              a raw machine instant or ISO date in reader text, or a clock
                             time that is a served UTC instant read as local time
    banned_term              the READER RULES jargon list (§2.1A + §2.1F), in code

  READER-SLOT classes — run only when the text IS a reader slot (the brief names it
  via ``reader_slot``); the daily narrative is owner-directed BY DESIGN, so running
  these on it would hold every coach:
    audience_violation       ``audience_guard.is_owner_directed`` on the slot text
    first_sentence           sentence 1 > 25 words, > 160 chars, or carries no date word
                             and no "asked him"
    ask_cardinality          a ``public_ask`` with more than one imperative clause

Each check is ARMED only by the input it needs: ``unit_number_not_served`` needs the
allow-list (``grounding_allowlist`` in the brief — its absence means "no grounding
context", never a green), ``absence_premise`` needs a served gap fact, the UTC-clock
arm of ``raw_instant`` needs the served instants. An unarmed check returns nothing,
and says so in ``armed_checks`` — never a silent pass dressed as a verdict.
"""

from __future__ import annotations

import re
from datetime import date, timezone
from typing import Any, Callable, Optional

from ai import grounded_generation as _gg
from ai.quality_gate_contract import GROUNDING_ALLOWLIST_KEY
from common.pacific_time import PACIFIC, parse_day_key, parse_iso_utc

from coach.audience_guard import is_owner_directed

READER_SLOTS = frozenset({"public_summary", "public_ask", "headline_read", "daily"})

# The report key the findings land under, and the brief keys the checks read.
REPORT_KEY = "reader_check_findings"
SERVED_FACTS_KEY = "served_facts"  # §2.1D: the orchestrator copies served_facts into the brief
READER_SLOT_KEY = "reader_slot"

# Split on terminal punctuation FOLLOWED BY whitespace, so a decimal ("81.6%") never
# ends a sentence — the same shape grounded_generation uses.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _sentences(text: str) -> list:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def _finding(check: str, excerpt: str, detail: str, fix: str, **extra: Any) -> dict:
    return {"check": check, "type": check, "excerpt": excerpt.strip()[:240], "detail": detail, "fix": fix, **extra}


# ── check 1: audience_violation ─────────────────────────────────────────────
def audience_violation(text: str, **_: Any) -> list:
    """A reader slot that addresses the owner ("you", or "Matthew —" as a vocative)."""
    if not is_owner_directed(text):
        return []
    return [
        _finding(
            "audience_violation",
            text,
            "a reader slot addresses Matthew directly — a visitor is a witness, not the patient",
            "Rewrite in the third person for Matthew (he/his/Matthew) and the first person for the coach; report the ask, never command it.",
        )
    ]


# ── check 2: absence_premise ────────────────────────────────────────────────
_COUNT = r"(\d+|" + "|".join(_NUMBER_WORDS) + r")"
_ABSENCE_RES = (
    re.compile(r"\b" + _COUNT + r"[- ]days?\b(?:\s+[a-z]+)?\s+(?:of\s+)?(gap|silence|without)\b", re.IGNORECASE),
    re.compile(r"\bwent\s+(?:dark|silent|quiet)\b", re.IGNORECASE),
    re.compile(r"\blogging\s+gap\b", re.IGNORECASE),
)
_SINCE_DATE_RE = re.compile(r"\bsince\s+(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _gap_fact(sentence: str, facts: dict) -> Optional[int]:
    """The served gap for the domain this sentence is about — journal vs food log."""
    if re.search(r"\bjournal", sentence, re.IGNORECASE):
        return _as_int(facts.get("journal_gap_days"))
    for key in ("gap_days", "lag_days"):
        if facts.get(key) is not None:
            return _as_int(facts.get(key))
    return None


def _last_log_date(facts: dict) -> Optional[date]:
    raw = facts.get("last_food_log_date") or facts.get("latest_date")
    return parse_day_key(str(raw)[:10]) if raw else None


def absence_premise(text: str, facts: Optional[dict] = None, **_: Any) -> list:
    """A narrated gap the engine's served gap fact contradicts.

    Armed only by a served gap fact (``gap_days``/``lag_days``/``journal_gap_days``) or a
    served last-log date. Fires when the served gap is ≤ 1 day (he is present), when a
    stated day-count disagrees with the served one, or when "since <date>" names a date
    that is not the served last log.
    """
    facts = facts or {}
    out = []
    last = _last_log_date(facts)
    for s in _sentences(text):
        gap = _gap_fact(s, facts)
        for rx in _ABSENCE_RES:
            m = rx.search(s)
            if not m or gap is None:
                continue
            stated = None
            if m.lastindex and m.lastindex >= 2:
                tok = m.group(1).lower()
                stated = int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok)
            if gap <= 1 or (stated is not None and stated != gap):
                out.append(
                    _finding(
                        "absence_premise",
                        s,
                        f"the text narrates a gap ({m.group(0)!r}) but the served gap is {gap} day(s)",
                        f"Drop the gap premise — the engine's served gap is {gap} day(s); state only the given days_logged / last log.",
                        claimed=m.group(0),
                        served_gap_days=gap,
                    )
                )
                break
        m = _SINCE_DATE_RE.search(s)
        if m and last is not None and re.search(r"gap|log|dark|silen|quiet|without", s, re.IGNORECASE):
            try:
                named = date(last.year, _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
            except ValueError:
                named = None
            if named is not None and named != last:
                out.append(
                    _finding(
                        "absence_premise",
                        s,
                        f"the text dates a gap 'since {m.group(1)} {m.group(2)}' but the served last log is {last.isoformat()}",
                        "Drop the 'since <date>' premise — cite only the served last-log date.",
                        claimed=m.group(0),
                        served_last_log=last.isoformat(),
                    )
                )
    return out


# ── check 3: unit_number_not_served ─────────────────────────────────────────
def unit_number_not_served(text: str, allowed: Optional[set] = None, **_: Any) -> list:
    """A figure written with a unit that is not on the generation's allow-list.

    Delegates to ``grounded_generation.fabricated_numbers(unit_voids_benign=True)`` — the
    SAME allow-list, rounding and tolerance semantics as the ADR-104 number gate — then
    keeps only the unit-bearing values (a unit-less invented number is the existing
    ``fabricated_number`` class, not this one). Unarmed without an allow-list.
    """
    if allowed is None:
        return []
    with_unit = _gg.unit_bearing_numbers(text)
    out = []
    for x in _gg.fabricated_numbers(text, allowed, unit_voids_benign=True):
        if x in with_unit:
            out.append(
                _finding(
                    "unit_number_not_served",
                    f"{x:g}",
                    f"the figure {x:g} (with a unit) appears in the text but in no served fact",
                    f"Remove {x:g} or replace it with the served figure — never compute, subtract or recall a number.",
                    claimed=x,
                )
            )
    return out


# ── check 4: unlabeled_window_figure ────────────────────────────────────────
_AVERAGE_RE = re.compile(r"\b(?:running\s+average|average[sd]?|averaging|ewma|trend(?:ing|s)?|mean)\b", re.IGNORECASE)
_FIGURE_RE = re.compile(r"\d")
_WINDOW_RE = re.compile(
    r"\b(?:over|across)\s+(?:the\s+)?(?:last\s+|past\s+|those\s+|these\s+)?(?:\d+|" + "|".join(_NUMBER_WORDS) + r"|twenty\S*)\s+(?:\w+\s+)?"
    r"(?:days?|nights?|weeks?|sessions?|weigh-ins?)\b"
    r"|\bsince\s+\w+|\bthrough\s+\w+"
    r"|\b(?:\d+|" + "|".join(_NUMBER_WORDS) + r")[- ](?:day|night|week)\b"
    r"|\b(?:this|last|past)\s+(?:week|month)\b",
    re.IGNORECASE,
)


# "a favorable data point, not a trend" DENIES a trend — it is not an average figure.
_NEGATED_TREND_RE = re.compile(r"\b(?:not|no|nor)\s+(?:an?\s+)?(?:\w+\s+)?trends?\b", re.IGNORECASE)


def unlabeled_window_figure(text: str, **_: Any) -> list:
    """An average/trend figure whose sentence names no window (the #1968 shape, generalised).

    A window is "over/across N days", "since …", "through …", "N-day", "this/last week".
    A date alone is NOT a window: "1,596 kcal EWMA … on the night of 2026-09-24" still
    leaves the average's span unnamed.
    """
    out = []
    for s in _sentences(text):
        if _AVERAGE_RE.search(_NEGATED_TREND_RE.sub("", s)) and _FIGURE_RE.search(s) and not _WINDOW_RE.search(s):
            out.append(
                _finding(
                    "unlabeled_window_figure",
                    s,
                    "an average/trend figure is stated with no window in its sentence",
                    'Name the window in the same sentence ("over the last 20 logged days", "through Friday, September 25") or drop the figure.',
                )
            )
    return out


# ── check 5: raw_instant ────────────────────────────────────────────────────
_RAW_INSTANT_RES = (
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?Z\b"),
    re.compile(r"T\d{2}:\d{2}"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
)
_CLOCK_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\b\.?")
_ONSET_CONTEXT_RE = re.compile(r"\b(?:onset|bed\s*time|bedtime|asleep|lights[- ]out|sleep\s+start|went\s+to\s+bed)\b", re.IGNORECASE)
# How close a stated clock time must sit to a UTC instant to be read as that instant,
# and how far from its Pacific rendering it must be to be wrong. 20 min is the resolution
# a coach rounds a median to ("~4:45"); an hour clears any PT rounding of the true time.
_UTC_MATCH_MIN = 20
_PT_CLEAR_MIN = 60


def _minute_gap(a: int, b: int) -> int:
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def _instant_minutes(instants: Any) -> list:
    """[(utc_minute_of_day, pt_minute_of_day)] for each parseable ISO-Z instant."""
    out = []
    for raw in instants or []:
        dt = parse_iso_utc(raw)
        if dt is None:
            continue
        utc, pt = dt.astimezone(timezone.utc), dt.astimezone(PACIFIC)
        out.append((utc.hour * 60 + utc.minute, pt.hour * 60 + pt.minute))
    return out


def raw_instant(text: str, facts: Optional[dict] = None, **_: Any) -> list:
    """A machine instant in reader text, or a UTC instant read as a local clock time.

    The literal arm needs no input: ``05:05Z``, ``T05:05``, ``2026-09-24``. The clock arm
    is armed by served ``utc_instants`` (e.g. ``sleep_trend[].sleep_start``): a stated
    "h:mm AM/PM" in a bedtime/onset sentence that matches a served instant's UTC clock and
    is an hour or more from that instant's Pacific clock is the timezone artifact.
    """
    out = []
    for rx in _RAW_INSTANT_RES:
        for m in rx.finditer(text or ""):
            out.append(
                _finding(
                    "raw_instant",
                    m.group(0),
                    f"a raw machine instant/date {m.group(0)!r} is in reader text",
                    'Write the day in words, Pacific time ("the night of Thursday, September 24", "9:45 PM PT") — never an ISO date or a Z instant.',
                    claimed=m.group(0),
                )
            )
    pairs = _instant_minutes((facts or {}).get("utc_instants"))
    if pairs:
        for s in _sentences(text):
            if not _ONSET_CONTEXT_RE.search(s):
                continue
            for m in _CLOCK_RE.finditer(s):
                h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3).lower()
                stated = (h + (12 if ap == "p" else 0)) * 60 + mi
                utc_hits = [p for p in pairs if _minute_gap(stated, p[0]) <= _UTC_MATCH_MIN]
                if utc_hits and all(_minute_gap(stated, p[1]) > _PT_CLEAR_MIN for p in utc_hits):
                    out.append(
                        _finding(
                            "raw_instant",
                            s,
                            f"the clock time {m.group(0).strip()!r} matches a served UTC instant read as local time, not its Pacific time",
                            "Convert every instant to Pacific time before citing it, or use the served avg_bedtime.",
                            claimed=m.group(0).strip(),
                        )
                    )
    return out


# ── check 6: banned_term ────────────────────────────────────────────────────
# §2.1A READER RULES ban list + §2.1F per-coach additions, moved out of the Haiku judge
# into code. Each entry: (pattern, the plain replacement the correction offers).
READER_BANNED_TERMS = (
    (r"\bEWMAs?\b", "running average"),
    (r"\bautocorrelat\w*", "one good night tends to follow another"),
    (r"\betiolog\w*", "the reason"),
    (r"\bmechanistic(?:ally)?\b", "plain cause-and-effect words"),
    (r"\b(?:un)?gat(?:e|es|ed|ing)\b", "a plain condition ('once …')"),
    (r"\bload-bearing\b", "plain words"),
    (r"\bcontingent\b", "plain words"),
    (r"\binteroception\w*", "noticing how he feels"),
    (r"\bgluconeogenesis\b", "plain words"),
    (r"\bcounter-regulatory\b", "plain words"),
    (r"\bslow-wave\b", "deep sleep"),
    (r"\bstandard deviations?\b", "plain words ('well above his usual')"),
    (r"\bn\s*=\s*\d+", "'21 days of data'"),
    (r"\bslopes?\b", "rising/falling"),
    (r"\bZone 2 hold\b", "easy cardio"),
    (r"\bcatabolic\b", "plain words"),
    (r"\bliquidation\b", "plain words"),
    (r"\bsubtherapeutic\b", "plain words"),
    (r"\bBMR\b", "plain words (the engine serves TDEE)"),
    (r"\bMifflin\b", "plain words (the engine serves TDEE)"),
    (r"\blogging gap\b", "the served days_logged"),
    (r"\bwent dark\b", "the served days_logged"),
    (r"\bopposing vectors\b", "plain words"),
    (r"\bemotional texture\b", "plain words"),
    (r"\bcontingent predictions\b", "plain words"),
    (r"\bprotein-primacy\b", "plain words"),
)
_BANNED_RES = tuple((re.compile(p, re.IGNORECASE), plain) for p, plain in READER_BANNED_TERMS)


def banned_term(text: str, **_: Any) -> list:
    """A READER RULES jargon term (one finding per distinct term)."""
    out, seen = [], set()
    for rx, plain in _BANNED_RES:
        for m in rx.finditer(text or ""):
            term = m.group(0).lower()
            if term in seen:
                continue
            seen.add(term)
            out.append(
                _finding(
                    "banned_term",
                    m.group(0),
                    f"the jargon term {m.group(0)!r} is on the READER RULES ban list",
                    f"Replace {m.group(0)!r} with {plain}.",
                    claimed=m.group(0),
                )
            )
    return out


# ── check 7: first_sentence ─────────────────────────────────────────────────
_DATE_WORD_RE = re.compile(r"\b(?:" + "|".join(_WEEKDAYS + _MONTHS) + r")\b|\basked him\b", re.IGNORECASE)
FIRST_SENTENCE_MAX_WORDS = 25
FIRST_SENTENCE_MAX_CHARS = 160


def first_sentence(text: str, **_: Any) -> list:
    """Sentence 1 of a reader slot: ≤ 25 words, ≤ 160 chars, a date word or "asked him"."""
    sents = _sentences(text)
    if not sents:
        return []
    s = sents[0]
    problems = []
    if len(s.split()) > FIRST_SENTENCE_MAX_WORDS:
        problems.append(f"{len(s.split())} words > {FIRST_SENTENCE_MAX_WORDS}")
    if len(s) > FIRST_SENTENCE_MAX_CHARS:
        problems.append(f"{len(s)} chars > {FIRST_SENTENCE_MAX_CHARS}")
    if not _DATE_WORD_RE.search(s):
        problems.append("no weekday/month word and no 'asked him'")
    if not problems:
        return []
    return [
        _finding(
            "first_sentence",
            s,
            "the first sentence fails the reader rule: " + "; ".join(problems),
            "Open with ≤ 25 words carrying the finding with its day in words, or the ask ('I've asked him to …').",
        )
    ]


# ── check 8: ask_cardinality ────────────────────────────────────────────────
# Verbs a coach's ask opens a clause with. A closed list keeps the check deterministic;
# a clause opening with anything else is not counted as an extra ask.
_ASK_VERBS = frozenset(
    (
        "add book bring check clarify confirm cut distinguish do drink eat focus get go hold identify increase keep "
        "lock log make measure move notice prioritize prioritise record reduce restart resume schedule send sleep spend "
        "start stop swap take track try walk weigh write"
    ).split()
)
_CLAUSE_SPLIT_RE = re.compile(r"\s*(?:;|,?\s+and\s+(?:to\s+)?|,?\s+then\s+|,?\s+also\s+|\.\s+)\s*", re.IGNORECASE)


def _ask_clauses(text: str) -> list:
    t = (text or "").strip()
    m = re.search(r"\basked him (?:to )?", t, re.IGNORECASE)
    body = t[m.end() :] if m else t
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(body) if c]
    return [c for c in clauses if c.split()[0].lower().strip(",.;:") in _ASK_VERBS]


def ask_cardinality(text: str, **_: Any) -> list:
    """More than one imperative clause in the one ask (or more than one "asked him")."""
    n_asked = len(re.findall(r"\basked him\b", text or "", re.IGNORECASE))
    clauses = _ask_clauses(text)
    if n_asked <= 1 and len(clauses) <= 1:
        return []
    return [
        _finding(
            "ask_cardinality",
            text,
            f"the ask carries {max(n_asked, len(clauses))} actions — a reader slot carries exactly one",
            "Keep exactly ONE ask, doable this week, stated once.",
            clauses=clauses,
        )
    ]


# THE registry — one entry per check class: (function, where it runs). "narrative" runs on
# every text the quality gate judges; "slot" runs only when the brief names a reader slot
# (and ask_cardinality only on public_ask). Every selection below is DERIVED from this
# dict, so a class can never be registered in one place and forgotten in another.
_CHECKS: dict[str, tuple[Callable[..., list], str]] = {
    "audience_violation": (audience_violation, "slot"),
    "absence_premise": (absence_premise, "narrative"),
    "unit_number_not_served": (unit_number_not_served, "narrative"),
    "unlabeled_window_figure": (unlabeled_window_figure, "narrative"),
    "raw_instant": (raw_instant, "narrative"),
    "banned_term": (banned_term, "narrative"),
    "first_sentence": (first_sentence, "slot"),
    "ask_cardinality": (ask_cardinality, "slot"),
}
CHECK_NAMES = tuple(_CHECKS)
NARRATIVE_CHECK_NAMES = tuple(n for n, (_, where) in _CHECKS.items() if where == "narrative")
SLOT_CHECK_NAMES = tuple(n for n, (_, where) in _CHECKS.items() if where == "slot")


def reader_findings(
    text: str,
    *,
    facts: Optional[dict] = None,
    allowed: Optional[set] = None,
    slot: Optional[str] = None,
    checks: Optional[tuple] = None,
) -> list:
    """Run the applicable checks over ``text``. ``slot`` in READER_SLOTS adds the slot classes.

    ``checks`` restricts the run to a subset (the tests' mutation controls use it); by
    default the narrative classes always run and the slot classes run for a reader slot.
    """
    names = checks if checks is not None else NARRATIVE_CHECK_NAMES + (SLOT_CHECK_NAMES if slot in READER_SLOTS else ())
    if slot != "public_ask" and checks is None:
        names = tuple(n for n in names if n != "ask_cardinality")
    out: list = []
    for name in names:
        fn, _where = _CHECKS[name]
        out.extend(fn(text, facts=facts or {}, allowed=allowed))
    return out


def _brief_inputs(generation_brief: Any) -> tuple:
    """(allowed_or_None, facts, slot) from a quality-gate generation brief."""
    if not isinstance(generation_brief, dict):
        return None, {}, None
    allowed = None
    raw = generation_brief.get(GROUNDING_ALLOWLIST_KEY)
    if raw is not None:
        try:
            allowed = {float(n) for n in raw}
        except (TypeError, ValueError):
            allowed = None
    facts = generation_brief.get(SERVED_FACTS_KEY)
    return allowed, (facts if isinstance(facts, dict) else {}), generation_brief.get(READER_SLOT_KEY)


def merge_into_report(payload: dict, output_text: str, generation_brief: Any) -> list:
    """Fold the reader findings into a quality-gate report (ADR-108 regenerate-or-hold).

    Any finding sets ``passed=False``, lands under ``reader_check_findings`` (each named by
    ``check``), and appends its correction to ``suggestions`` — which
    ``ai_calls._quality_gate_correction_note`` already renders into the regeneration note.
    Returns the findings (empty = nothing merged, the report untouched).
    """
    allowed, facts, slot = _brief_inputs(generation_brief)
    findings = reader_findings(output_text, facts=facts, allowed=allowed, slot=slot)
    if findings:
        payload[REPORT_KEY] = findings
        payload["passed"] = False
        payload["suggestions"] = list(payload.get("suggestions") or []) + [f"[{f['check']}] {f['fix']}" for f in findings]
    return findings
