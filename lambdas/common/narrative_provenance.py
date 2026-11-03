"""Provenance and publication eligibility for AI-written narrative (owner ruling 2026-11-03).

THE RULING. "Replace [the keyword filter] with a structured, source-aware publication policy that
prevents private journal-derived information from appearing in public coach narratives or APIs,
including paraphrases ... Use explicit provenance and publication eligibility, fail closed when
provenance is unknown ... Preserve private source material internally."

A keyword scrub (``common.journal_silence``, #5131) can only refuse the words it knows; a
paraphrase walks past it. So publication is no longer decided by what a text SAYS but by what it
was MADE FROM:

  * every producer of AI-written text records, on the row it writes, the source FAMILIES its
    generation context was assembled from (``stamp``), merging the provenance of any stored
    narrative it read as input (``merge_upstream``) — a line written from another coach's
    position inherits that position's sources;
  * a public read serves the text only when that record is KNOWN and names no private family
    (``eligibility``). No record (every row written before 2026-11-03), a malformed record, a
    family this registry does not classify, or a private family → WITHHELD. Fail closed.

The row is never changed: the private material stays stored for the owner's own tools (MCP,
Telegram), and the public read withholds it (``web.narrative_publication`` is the one wire
chokepoint). The #5131 scrub stays as defence in depth; it is no longer the policy.

THE REGISTRY. ``SOURCE_FAMILIES`` classifies every family a producer may name. ``PRIVATE`` is the
journal and everything journal-grade: the journal itself, anything DERIVED from it (its
enrichment, the mood read, the PERMA projection), the journal's PRESENCE or ABSENCE (whether and
when he writes — the silence-or-absence paraphrase class), the owner's other self-reports, and every
owner-only partition declared with no public projection in ``privacy.field_tiers.SOURCE_TIERS``.
``tests/test_narrative_publication_gate.py`` requires every ``SOURCE_TIERS`` key to be classified
here, so a new owner-only source cannot default into public narrative. A family missing from
this registry is not public: it is unknown, and unknown is withheld.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

PROVENANCE_KEY = "provenance"
SCHEMA_VERSION = 1

PUBLIC = "public"
PRIVATE = "private"

# The one family token for "an input whose own provenance is not recorded" — never classified,
# so anything carrying it is withheld until that input is regenerated with a record.
UNRECORDED = "unrecorded"

# The reader-facing reason. Deliberately the SAME for every withheld case and free of any hint of
# what the text was about or which source it came from (the owner's ruling: no private hint).
PUBLIC_WITHHELD_REASON = "withheld: this text's sources are not recorded as publishable"

# Internal reason codes (logs, owner tooling, tests) — never served.
ELIGIBLE = "eligible"
R_UNRECORDED = "unrecorded"
R_MALFORMED = "malformed"
R_PRIVATE = "private_source"
R_UNKNOWN = "unclassified_source"

SOURCE_FAMILIES: dict[str, str] = {
    # ── PRIVATE: the journal and everything journal-grade ─────────────────────────────────
    "notion": PRIVATE,  # the journal's full text (SOURCE#notion)
    "journal": PRIVATE,  # any journal-derived input: entries, enrichment, themes, quotes
    "journal_presence": PRIVATE,  # whether/when he journals — gaps, silence, last-entry dates (the paraphrase class)
    "journal_analysis": PRIVATE,  # the journal analyzer's derived read
    "journal_quotes": PRIVATE,  # quotes lifted from the journal
    "mood_read": PRIVATE,  # health.mood_read — the published coach brief's mood signal is journal-derived
    "diary_claims": PRIVATE,  # claims harvested from the owner's diary/vlog
    "diary_reactions": PRIVATE,  # coach reactions to diary entries
    "clinical": PRIVATE,  # the full clinical record (TIER_INTERNAL: AI context, never public)
    # ...and every other owner-only / internal partition in privacy.field_tiers.SOURCE_TIERS, derived
    # below (state of mind, PERMA, check-ins, pending writes, photos and every flag declared with no
    # public projection) — never hand-copied, so a new owner-only source is private the day it lands.
    "owner_thread": PRIVATE,  # the owner's own Telegram/chat coach conversation
    "interview": PRIVATE,  # milestone deep-interview briefs
    "platform_memory": PRIVATE,  # owner-curated memory notes
    # ── PUBLIC-eligible: measured, computed or already-public inputs ──────────────────────
    # Owner-only RAW partitions whose deliberate projections coach narrative has always served
    # (ADR-155 SEMANTICS: "public surfaces may serve only deliberate, gated projections").
    "macrofactor": PUBLIC,
    "hevy": PUBLIC,
    "strava": PUBLIC,
    "supplements": PUBLIC,
    "sick_days": PUBLIC,
    "reading": PUBLIC,
    "cgm_readings": PUBLIC,
    # ADR-155 owner-published + Tier-0 sources.
    "labs": PUBLIC,
    "dexa": PUBLIC,
    "measurements": PUBLIC,
    "whoop": PUBLIC,
    "withings": PUBLIC,
    "eightsleep": PUBLIC,
    "garmin": PUBLIC,
    "apple_health": PUBLIC,
    "habitify": PUBLIC,
    "weather": PUBLIC,
    "circadian": PUBLIC,
    # Platform-computed reads over the above.
    "computed_metrics": PUBLIC,
    "character_sheet": PUBLIC,
    "habit_scores": PUBLIC,
    "day_grade": PUBLIC,
    "readiness": PUBLIC,
    "adaptive_mode": PUBLIC,
    "experiments": PUBLIC,
    "instrument_presence": PUBLIC,
    "food_log_presence": PUBLIC,  # whether/when he logs food (served on /api/character absence)
    "training_log_presence": PUBLIC,  # whether/when he logs a workout (served on /api/character absence)
    "prediction_ledger": PUBLIC,  # graded call RESULTS (verdicts, dates); a claim's TEXT carries its row's own provenance
    "clinical_public_rules": PUBLIC,  # GUIDANCE#current.public_rules — the neutral rules ADR-155's amendment publishes
    "morning_note": PUBLIC,  # owner ruling 2026-09-26: the four words are Tier-0 public
    "owner_words": PUBLIC,  # #4584: his own published words, verbatim
    "persona": PUBLIC,  # the coach's own voice spec / persona registry (code, not data)
}


# A producer that knows its inputs as dotted FIELD names ("withings.weight_lbs",
# "journal.days_since") maps each to a family by its first segment through this table; a first
# segment not listed here is used as-is (and is withheld if this registry does not classify it).
FIELD_PREFIX_FAMILIES: dict[str, str] = {
    "journal": "journal_presence",  # the moves sheet's /api/character journal absence facts
    "food_log": "food_log_presence",
    "training_log": "training_log_presence",
    "nutrition": "macrofactor",
    "ai_context": "experiments",  # the experiment phase context (day n, start date)
    "profile": "experiments",  # the experiment profile (start weight, protein floor)
    "journey": "withings",  # lost-since-start, computed from the weigh-ins
}


def families_from_fields(fields: Iterable[Any]) -> list:
    """Source families for dotted field names (``"withings.weight_lbs vs profile.x"`` -> both)."""
    out = set()
    for f in fields or ():
        for token in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\.", str(f or "")):
            out.add(FIELD_PREFIX_FAMILIES.get(token, token))
    return sorted(out)


def _derive_owner_only() -> None:
    from privacy.field_tiers import SOURCE_TIERS, TIER_PUBLIC

    for source, tier in SOURCE_TIERS.items():
        if source not in SOURCE_FAMILIES and tier != TIER_PUBLIC:
            SOURCE_FAMILIES[source] = PRIVATE


_derive_owner_only()


def classify(family: Any) -> Optional[str]:
    """PUBLIC, PRIVATE, or None (unclassified — treated as not publishable)."""
    return SOURCE_FAMILIES.get(str(family or "").strip())


def _families(values: Iterable[Any]) -> list:
    return sorted({str(v).strip() for v in values or () if str(v or "").strip()})


def stamp(families: Iterable[Any], *, producer: str, upstream: Iterable[Any] = ()) -> dict:
    """The provenance record a producer writes on its row (key ``PROVENANCE_KEY``).

    ``families`` are the source families the generation context was assembled from; ``upstream``
    is any stored rows (or provenance records) of narrative the context READ — their families are
    merged in, and an upstream row with no record contributes ``UNRECORDED`` (so the new text is
    withheld until that input carries one)."""
    fams = set(_families(families))
    for up in upstream or ():
        fams |= set(merge_upstream(up))
    return {
        "v": SCHEMA_VERSION,
        "families": sorted(fams),
        "producer": str(producer),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }


def record_of(row_or_record: Any) -> Optional[dict]:
    """The provenance record of a stored row (or a record passed directly), or None."""
    if not isinstance(row_or_record, dict):
        return None
    rec = row_or_record.get(PROVENANCE_KEY) if PROVENANCE_KEY in row_or_record else row_or_record
    if isinstance(rec, dict) and "families" in rec:
        return rec
    return None


def merge_upstream(row_or_record: Any) -> list:
    """The families an input row contributes to text written from it (``[UNRECORDED]`` when it has none)."""
    rec = record_of(row_or_record)
    if rec is None or not isinstance(rec.get("families"), (list, tuple, set)):
        return [UNRECORDED]
    fams = _families(rec.get("families"))
    return fams or [UNRECORDED]


def eligibility(row_or_record: Any) -> tuple:
    """``(publishable, internal_reason)`` for a stored narrative row. Fail closed."""
    rec = record_of(row_or_record)
    if rec is None:
        return False, R_UNRECORDED
    try:
        version = int(rec.get("v"))
    except (TypeError, ValueError):
        return False, R_MALFORMED
    fams = rec.get("families")
    if version != SCHEMA_VERSION or not isinstance(fams, (list, tuple, set)):
        return False, R_MALFORMED
    fams = _families(fams)
    if not fams:
        return False, R_UNRECORDED
    classes = [classify(f) for f in fams]
    if PRIVATE in classes:
        return False, R_PRIVATE
    if any(c is None for c in classes):
        return False, R_UNKNOWN
    return True, ELIGIBLE


def is_publishable(row_or_record: Any) -> bool:
    return eligibility(row_or_record)[0]
