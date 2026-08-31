"""reader_truth_evidence.py — what a judge note ASSERTS, parsed (#3337).

Split from reader_truth_rulings.py 2026-08-30 (#3337). That file is the LEDGER —
one adjudication per measured false-positive class, each carrying the history that
earned it. This file is the EVIDENCE LAYER underneath it: the parsers that turn an
LLM note into the structured values a ruling may decide on — cited dates, cited day
numbers, claimed elapsed spans, quoted page copy, quoted payload field values — plus
the two phase comparisons every structural ruling is built from
(`out_of_phase_quantities`, `evidence_is_phase_anchors_only`).

WHY IT EXISTS AS ITS OWN MODULE. #3337's bar is that a ruling decides on `category`,
`surface`, the claim class, or PARSED EVIDENCE VALUES — never on how the judge worded
itself. That bar is only reachable if the parsing is a real, testable layer rather
than a regex inlined in each predicate: three rulings decided on adjectives precisely
because there was nowhere else for them to look. Keeping it separate also keeps the
ledger under the #1665 1,200-line ceiling by EXTRACTION rather than a baseline raise.

ONE RULE ABOUT SCOPE, LEARNED THE HARD WAY IN THIS PR: the quantities inside the copy a
judge QUOTES count as its evidence, exactly like the ones in its own sentences. The first
draft excluded them ("the quote is the claim, not the proof") and that inverted the gate:
a note reading "the home page says 'over the past three weeks' but we are on Day 6" then
cited nothing out of phase and would have been demoted to advisory — the archetypal TRUE
positive, silenced. The exclusion survives in exactly one narrow place, named at its call
site: the #3003 hedged-objection tiebreak ignores over-long SPANS (not dates, not day
numbers), which is the residue #3003 accepted in its own comment when it shipped.

A DATE WITHOUT A YEAR IS ONLY A DATE WHEN A YEAR IS SUPPLIED. `note_dates()`
takes an explicit `default_year`; with none, yearless "August 16" is skipped.
`reader_truth_rulings._note_dates` (the #2959 archive ruling) calls it with none, so its
behaviour is byte-identical to before the split; the #3337 rulings pass the cycle's year,
because "silent since August 16th" vs. a 2026-08-17 genesis is exactly the residue those
rulings must keep flaggable.
"""

import re
from datetime import date
from typing import Optional

# ── quoted page copy ──────────────────────────────────────────────────────────
# The model quotes page copy with the page's own typography — the live notes carry
# U+2011 NON-BREAKING HYPHEN in "Day‑1" while the rubric writes an ASCII hyphen, and
# curly quotes appear in both directions. Comparing raw strings would silently never
# match, which is the failure mode where a gate looks wired and is not.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTED_SPAN_RE = re.compile(r"[‘’']([^‘’']{4,})[‘’']|[“”\"]([^“”\"]{4,})[“”\"]")


def normalize_copy(s) -> str:
    """Casefold, unify every Unicode dash to '-', and collapse whitespace."""
    return " ".join(str(s or "").translate(_DASHES).casefold().split())


def quoted_spans(note) -> list:
    """The quoted page-copy spans inside a model note, in order.

    Apostrophes inside quoted prose ("What's different") make single-quote pairing
    ambiguous. That is fine and deliberate: an ambiguous parse yields spans that do
    not match the registry, and the all-spans-must-match rule in
    `is_durable_design_copy` then KEEPS the finding. The failure direction preserves
    the old behaviour rather than silencing it.
    """
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _QUOTED_SPAN_RE.finditer(note or "")]


# ── dates, day numbers, elapsed spans ─────────────────────────────────────────
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
MONTHS = {m: i + 1 for i, m in enumerate(_MONTH_NAMES)}
# "July 8, 2026", "August 17 2026", and (only with an explicit default_year) "August 16th".
_TEXT_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)
DAY_N_RE = re.compile(r"\bday\s+(\d{1,3})\b", re.I)

# "4 days", "7-day average", "three weeks", "90 consecutive days", "2 months".
# The trailing lookahead is load-bearing: without it "August 17 is Day 1" parsed as a
# 17-DAY SPAN (the quantity 17, two words of slack, the word "Day"), which read the
# phase's own anchor as a 17-day claim and kept the #3199 wire note gating. A unit
# followed by a number is a "Day N" reference, never a span.
_WORD_NUMBERS = {
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
}
_SPAN_RE = re.compile(
    r"\b(\d{1,4}|" + "|".join(_WORD_NUMBERS) + r")[\s\-]+(?:\w+[\s\-]+){0,2}?(day|week|month)s?\b(?!\s*\d)",
    re.I,
)
_SPAN_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}


def note_dates(note, default_year: Optional[str] = None) -> list:
    """Every date the note cites, as ISO strings — ISO literals + text forms.

    `default_year` supplies the year for a yearless "August 16"/"August 16th"; with
    none (the pre-#3337 behaviour every existing caller relies on) those are skipped.
    """
    out = list(ISO_DATE_RE.findall(note or ""))
    for mon, day, year in _TEXT_DATE_RE.findall(note or ""):
        y = year or (str(default_year) if default_year else "")
        if not y:
            continue
        try:
            out.append(date(int(y), MONTHS[mon.lower()], int(day)).isoformat())
        except ValueError:  # "February 31" in prose is not a date
            continue
    return out


def day_numbers(note) -> set:
    """Every "Day N" the note cites, as ints — quoted page copy included."""
    return {int(n) for n in DAY_N_RE.findall(note or "")}


def elapsed_spans(note) -> set:
    """Every claimed span the note states, normalized to DAYS.

    "4 days without an entry" → 4; "a 7-day average" → 7; "three weeks" → 21. The
    unit conversion is what lets one comparison ("does this span fit inside the
    cycle?") cover the phrasings the rubric's own examples use.
    """
    spans = set()
    for qty, unit in _SPAN_RE.findall(note or ""):
        q = qty.lower()
        n = _WORD_NUMBERS.get(q)
        if n is None:
            try:
                n = int(q)
            except ValueError:
                continue
        spans.add(n * _SPAN_UNIT_DAYS[unit.lower()])
    return spans


# ── payload field values the note quotes ──────────────────────────────────────
# The API surfaces carry snake_case date fields (`as_of_date`, `night_of`,
# `weight_as_of`) and the judge quotes them in two shapes, both live on the wire
# 2026-08-30: JSON-ish ("'as_of_date': '2026-08-29'") and prose ("weight_as_of is
# 2026-08-24"). A field NAME must be quoted or snake_case — otherwise "today is
# 2026-08-22" reads as a payload field named "today", which it is not.
_FIELD_DATE_RE = re.compile(
    r"['\"]?\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b['\"]?\s*(?::|\bis\b|=)\s*['\"]?(\d{4}-\d{2}-\d{2})",
    re.I,
)


def payload_field_dates(note) -> dict:
    """`{field_name: {iso_date, ...}}` for every payload date field the note quotes.

    A quoted field value is the payload's own datum, which is exactly the evidence a
    ruling is entitled to weigh.
    """
    out: dict = {}
    for field, value in _FIELD_DATE_RE.findall(note or ""):
        out.setdefault(field.lower(), set()).add(value)
    return out


def cites_payload_date_field(note) -> bool:
    """True when the note quotes a payload DATE FIELD by name — a claim about the data.

    The line between the two editorial rulings (#3003/#3199) and a real data finding,
    drawn structurally. Both of these are live wire notes from 2026-08-24 → 08-30, both
    cite only in-phase values, and both are TRUE:

      * `/api/glucose` e5eafd — "as_of_date is 2026-08-22, but the payload was generated
        on 2026-08-24 (Day 8)"; the deterministic plausibility pass independently FAILED
        on the same field with arithmetic two days later.
      * `/api/vitals` d1c6a0 — "weight_as_of is 2026-08-24 (6 days ago), but the API
        metadata states as_of_date is 2026-08-30"; a real 6-day scale gap.

    A note that names a payload date field is objecting to the DATA's own dating, which
    is never the "the copy is imprecise" class and never the "the objection restates the
    cycle window" class. Those rulings therefore refuse it outright. The wake-date
    convention (`is_wake_frame_correct`) is the one ruling that DOES read these fields —
    and it decides on their arithmetic, not on their presence.
    """
    return bool(payload_field_dates(note))


# ── the phase comparisons every structural ruling is built from ───────────────


def cycle_day(start_date, today) -> Optional[int]:
    """`today`'s 1-indexed day number in the cycle, or None when either anchor is absent."""
    if not start_date or not today:
        return None
    try:
        n = (date.fromisoformat(str(today)) - date.fromisoformat(str(start_date))).days + 1
    except ValueError:
        return None
    return n if n >= 1 else None


def unquoted(note) -> str:
    """`note` with every quoted page-copy span blanked out — the judge's OWN sentences.

    Used in exactly ONE place (see `out_of_phase_quantities(spans_in_quotes=False)`),
    because reading a note this way by default inverts the gate — see the module
    docstring.
    """
    return _QUOTED_SPAN_RE.sub(" ", str(note or ""))


def out_of_phase_quantities(note, start_date, today, spans_in_quotes=True) -> list:
    """Every value the note cites that the phase cannot hold — the impossibility test.

    A `temporal_contradiction` is defined by the rubric as "an IMPOSSIBILITY your own
    arithmetic establishes against the phase". Structurally, establishing one requires
    CITING a value the phase makes impossible: a date outside [cycle start, today], a
    day number past today's, or a claimed elapsed span longer than the cycle. This
    returns those values as human-readable strings (so a ruling can say WHICH one kept
    a finding alive); an empty list means the note cites nothing out of phase.

    The whole note is read, quoted page copy included — see the module docstring: a
    judge quoting "over the past three weeks" on Day 6 IS citing an out-of-phase value.
    `spans_in_quotes=False` counts a claimed span only when the JUDGE states it in its
    own sentences, ignoring one that appears solely inside quoted page copy. Exactly one
    caller passes it — #3003's hedged-objection tiebreak — for exactly one measured
    reason: the #3258 wire note quotes the home page's "aimed at 185 lbs held for 90
    consecutive days", a forward-looking goal in the PAGE's words that the judge never
    restates, while the impossibility notes this test must spare ("A 57-day history is
    impossible") always say the number in the judge's own voice.

    Returns [] when the phase anchors are unknown — every caller treats "no phase" as
    "no structural channel available" and falls through to its fail-closed default,
    never as "nothing out of phase".
    """
    n = cycle_day(start_date, today)
    if n is None:
        return []
    start = str(start_date)
    today_s = str(today)
    out = []
    for d in note_dates(note, default_year=start[:4]):
        if d < start:
            out.append(f"date {d} < cycle start {start}")
        elif d > today_s:
            out.append(f"date {d} > today {today_s}")
    for m in sorted(day_numbers(note)):
        # +1: the rubric's own inclusive-counting allowance (a prose day count may
        # legitimately differ by one), applied to the judge's arithmetic too.
        if m > n + 1:
            out.append(f"Day {m} > today's Day {n}")
    for sp in sorted(elapsed_spans(note if spans_in_quotes else unquoted(note))):
        if sp > n:
            out.append(f"a {sp}-day span > the {n}-day cycle")
    return out


def evidence_is_phase_anchors_only(note, start_date, today) -> bool:
    """True when every value the note cites is one of the phase's OWN anchors.

    The anchors are the four facts the prompt itself injects: the cycle start date,
    today's date, Day 1, and today's day number (+-1 for inclusive counting; an elapsed
    span of n or n-1 days is the same restatement). A note whose entire evidence is
    those four has introduced NOTHING — it has restated the window it is objecting to.
    Any other value (a logged entry's date, a different day number, a longer span) means
    the objection carries evidence of its own and is a live finding.

    Requires at least one anchor to actually be cited: a note that asserts no temporal
    value at all is not "anchors-only", it is unparsed, and must never be adjudicated.
    """
    n = cycle_day(start_date, today)
    if n is None:
        return False
    dates = set(note_dates(note, default_year=str(start_date)[:4]))
    days = day_numbers(note)
    spans = elapsed_spans(note)
    if not (dates or days or spans):
        return False
    if dates - {str(start_date), str(today)}:
        return False
    if days - {1, n - 1, n, n + 1}:
        return False
    if spans - {n - 1, n}:
        return False
    return True


def spans_scoped_to_cycle_start(note, start_date) -> list:
    """Quoted page-copy spans that scope a claim to the cycle start and to nothing else.

    A qualifying span (a) cites at least one date, (b) cites ONLY the cycle start date,
    and (c) states no day number of its own. That is the "since genesis" claim class:
    copy whose window is exactly the cycle. A banner span ('DAY 9 · WEEK 2, SINCE
    AUGUST 17 2026') carries its own day number and is deliberately excluded — a wrong
    banner day is a real defect (#2941) and must never be adjudicated by this class.
    """
    out = []
    for span in quoted_spans(note):
        dates = set(note_dates(span, default_year=str(start_date)[:4]))
        if not dates or dates != {str(start_date)}:
            continue
        if day_numbers(span):
            continue
        out.append(span)
    return out


_CONVENTION_FIELDS = ("as_of_date", "night_of")


def payload_dating_is_the_convention(note, today):
    """True when the note's own quoted `as_of_date`/`night_of` values ARE the
    wake-date convention, dated fresh against the phase clock (#3337).

    night_of + 1 == as_of (a night is dated by the evening it began, the payload by
    the morning it serves) AND as_of is no more than one day behind `today` (the
    pipeline publishes through the last COMPLETE day). A genuinely stale payload
    fails the second test and keeps gating — that is the whole discriminator.
    `is_wake_frame_correct` is the one ruling entitled to read these fields, and it
    reads their ARITHMETIC, never their presence.
    """
    if not today:
        return False
    fields = payload_field_dates(note)
    values = {}
    for name in _CONVENTION_FIELDS:
        seen = fields.get(name) or set()
        if len(seen) != 1:  # absent, or the note cites two values for one field
            return False
        values[name] = date.fromisoformat(next(iter(seen)))
    if (values["as_of_date"] - values["night_of"]).days != 1:
        return False
    try:
        lag = (date.fromisoformat(str(today)) - values["as_of_date"]).days
    except ValueError:
        return False
    return 0 <= lag <= 1


# ── the judge's own structured verdict field (#3337, the #3258 durable fix) ────
#
# #3258 named it and deliberately did not ship it: "the durable fix … is the
# response contract — a per-finding `verdict: flag|withdrawn` field the judge
# fills, so a retraction has a structured place to live instead of leaking into
# prose", held back because no recorded payload carried the field. #3337 ships it
# as `basis`, on the only terms that are safe without a live Bedrock measurement
# from a worktree:
#
#   * ADDITIVE. `_normalize_finding` keeps the field only when it is one of the
#     three enum values; anything else, or an absent field, leaves the finding
#     exactly as it is today.
#   * IT MAY ONLY FIRE A RULING, NEVER VETO ONE. `basis == "impossibility"` is
#     not consulted anywhere — a judge that mislabels its own retraction as an
#     impossibility gets the same structural adjudication it gets today. So a
#     model that ignores the new field (the #2613/#2741 measured default, 3-of-3
#     and 25-of-60) costs nothing, and one that honours it decides on DATA.
JUDGE_BASIS_FIELD = "basis"
JUDGE_BASIS_VALUES = ("impossibility", "ambiguity", "withdrawn")


def judge_basis(finding):
    """The judge's own structured basis for a finding, or None (#3337).

    None is the fail-closed default in every caller: no field, no decision from
    this channel — the structural evidence predicates decide instead.
    """
    b = (finding or {}).get(JUDGE_BASIS_FIELD)
    return b if b in JUDGE_BASIS_VALUES else None


def tiebreak(ruling_id, finding, why):
    """Print that a legacy phrase regex BROKE A TIE a structural predicate allowed.

    The #3337 contract in one function: a phrase may never decide alone, so every
    call site has already established its structural precondition before reaching
    here. Printing makes the remaining lexical residue countable in the qa-smoke
    log group instead of invisible — the same "printed, never silently swallowed"
    posture every ruling in this file keeps.
    """
    note = str((finding or {}).get("note") or "")[:120]
    print(
        f"  ↩ reader-truth: {ruling_id} decided on a LOGGED TIEBREAK ({why}) on " f"{(finding or {}).get('page')} — #3337 residue: {note}"
    )
    return True
