"""
journal_quotes.py — the consent-per-line verbatim journal quote channel (#1568, ADR-142).

"From the journal, in his words." The Notion journal is deep background everywhere
else on the platform (the chronicle's never-quote rule in chronicle_prompt.py is
UNTOUCHED by this module). This is the one deliberate, narrow break in that wall:
during a journal-interview / vlog close Claude may nominate 0–2 lines as
quote-worthy, Matthew explicitly marks a line publishable, and ONLY marked lines
ever reach the public surface — dated, verbatim, labeled as his words, with a
receipts link to that day's data.

ADR-142 (the three-tier privacy model shared with #1483):
  verbatim-private     — the default for every journal line, forever. Unmarked
                         lines never cross; there is no bulk opt-in.
  theme-referenceable  — the allude tier (#1483, future): coarse laundered theme
                         only, never verbatim text.
  public-delta         — this channel: a single line Matthew explicitly marked,
                         published as the exact text he approved.

Single-SOT stance (documented per the issue-1568 AC1 decision): the DDB consent
record IS the source of truth for *publishability* — a consent event freezing the
exact approved text at mark time. Notion stays the source of truth for the journal
itself. A later Notion edit never mutates a published quote (consent attached to
the approved bytes, not to a mutable document), and revocation is an explicit
unmark, not a Notion-side edit the pipeline might miss.

Mark-time taboo gate (fail-closed, deterministic): the ELENA_PREQUEL_BRIEF
"abstract / omit" list, machine-enforced for the categories a regex can honestly
carry — substances (privacy_guard.VICE_KEYWORDS reused as the base set, widened
here with the alcohol family the serve-time gate deliberately leaves soft),
family-specifics, age disclosure (PhenoAge Option A: chronological age is never
public), private events (wedding/funeral/therapy/work-specifics), and the
privacy_guard real-name set. A line hitting ANY category is refused at mark time —
Claude must not even nominate it, and the tool will not store it regardless.

Pure module (no boto3, no I/O) so the gate is unit-testable hermetically — the
same pattern as diary_consent.py, which implements the ENTRY-level tier contract
for coach reactions (#1574). This module is the per-LINE channel beside it.
"""

import hashlib
import re
from datetime import date as _date, datetime, timedelta

import privacy_guard  # the deterministic substance/real-name base set (ADR-104)

SOURCE = "journal_quotes"
SK_PREFIX = "QUOTE#"
MAX_QUOTES_PER_DAY = 2  # the "0–2 lines per close" nomination cap, enforced at mark time
MAX_QUOTE_CHARS = 500
PUBLIC_LABEL = "from the journal, in his words"

# ── The mark-time taboo vocabulary (ELENA_PREQUEL_BRIEF "abstract / omit") ────
# Substances: privacy_guard.VICE_KEYWORDS is the enforced base (superset invariant
# tested), plus the alcohol family — deliberately soft at serve time for nutrition
# context, deliberately HARD here: a verbatim journal line about drinking is
# exactly what the brief says never ships.
SUBSTANCE_EXTRA = (
    "alcohol",
    "drunk",
    "hungover",
    "hangover",
    "vape",
    "vaping",
)

# Family-specifics: close-kin phrases and the in-law family from the brief
# ("respect family privacy"). Word-boundary matched.
FAMILY_KEYWORDS = (
    "sister-in-law",
    "brother-in-law",
    "mother-in-law",
    "father-in-law",
    "in-laws",
    "my sister",
    "my brother",
    "my mother",
    "my mom",
    "my dad",
    "my father",
    "my parents",
    "nephew",
    "niece",
)

# Private events / specifics the brief abstracts: cancelled events, illness
# details, therapy details, work events.
PRIVATE_EVENT_KEYWORDS = (
    "wedding",
    "funeral",
    "hawaii",
    "cancer",
    "chemo",
    "hospice",
    "diagnosis",
    "therapy",
    "therapist",
    "layoff",
    "laid off",
)

# Age disclosure — chronological age is never public (PhenoAge Option A).
AGE_PATTERNS = (
    re.compile(r"\b\d{1,3}\s*(?:years?[\s-]*old|y/?o)\b", re.IGNORECASE),
    re.compile(r"\bturn(?:ed|ing|s)?\s+\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\bage\s+\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\bi\W?m\s+\d{1,3}\b", re.IGNORECASE),  # "I'm 45"
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\s+birthday\b", re.IGNORECASE),
)


def _word(term):
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


def _norm(s):
    """Whitespace-collapse + casefold — the same normalisation diary_consent uses,
    so a quote can't dodge the gate (or grounding) on formatting."""
    return " ".join(str(s or "").split()).lower()


def find_mark_violations(text):
    """Every taboo hit in `text` as (category, term) — empty list = markable.

    Categories: substances / real_name (privacy_guard reused verbatim), plus
    family_specifics / private_event / age from the ELENA brief's omit list.
    """
    if not text or not str(text).strip():
        return [("empty", "")]
    hits = []
    for kind, term in privacy_guard.find_violations(text):
        hits.append(("substances" if kind == "vice" else kind, term))
    for kw in SUBSTANCE_EXTRA:
        if _word(kw).search(text):
            hits.append(("substances", kw))
    for kw in FAMILY_KEYWORDS:
        if _word(kw).search(text):
            hits.append(("family_specifics", kw))
    for kw in PRIVATE_EVENT_KEYWORDS:
        if _word(kw).search(text):
            hits.append(("private_event", kw))
    for pat in AGE_PATTERNS:
        m = pat.search(text)
        if m:
            hits.append(("age", m.group(0)))
    return hits


def is_markable(text):
    return not find_mark_violations(text)


def grounds_in(quote, body):
    """True iff `quote` appears verbatim (modulo whitespace/case) inside `body` —
    the ADR-104 grounding invariant: a published quote must be his actual words,
    never a paraphrase that reads like one."""
    q = _norm(quote)
    return bool(q) and q in _norm(body)


def quote_sk(date_str, quote):
    """Deterministic sort key: QUOTE#<date>#<10-hex of the normalised line>.
    Idempotent — re-marking the same line on the same day overwrites, never dupes."""
    digest = hashlib.sha256(_norm(quote).encode("utf-8")).hexdigest()[:10]
    return f"{SK_PREFIX}{date_str}#{digest}"


def shape_public(item):
    """The public projection of one marked-quote record — nothing but the fields
    the reader surface needs. The verbatim text itself is served all-or-nothing
    by the caller's content screen; this only shapes."""
    d = str(item.get("date") or "")
    return {
        "date": d,
        "quote": str(item.get("quote") or ""),
        "marked_at": item.get("marked_at"),
        "channel": item.get("channel") or "journal",
        "label": PUBLIC_LABEL,
        "receipts": f"/cockpit/?date={d}" if d else "/cockpit/",
    }


def _iso_week(date_str):
    try:
        y, w, _ = datetime.strptime(date_str, "%Y-%m-%d").date().isocalendar()
        return (y, w)
    except (ValueError, TypeError):
        return None


def featured_for_week(quotes, today):
    """The AT-MOST-ONE quote the home surface may feature this week (AC2's cap).

    Deterministic and stable within a week: among quotes whose journal DATE falls
    in `today`'s ISO week, the FIRST-MARKED one is featured for the whole week —
    marking a second line mid-week never rotates the slot. No quote this week →
    None → the home slot stays dormant.
    """
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, _date):
        return None
    this_week = today.isocalendar()[:2]
    candidates = [q for q in quotes if _iso_week(str(q.get("date") or "")) == this_week]
    if not candidates:
        return None
    return sorted(candidates, key=lambda q: str(q.get("marked_at") or "~"))[0]


def week_bounds(today):
    """(monday, sunday) of `today`'s ISO week — handy for tests/receipts copy."""
    monday = today - timedelta(days=today.isocalendar()[2] - 1)
    return monday, monday + timedelta(days=6)
