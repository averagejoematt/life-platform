"""Dated corrections to historical coach words whose cited figures later changed (owner ruling 2026-11-10, item 4).

THE RULING. "CR2 historical reads — keep the four outdated-figure lead reads excluded. Investigate publishing them with
original text preserved and a clearly dated correction/annotation. Never silently rewrite historical coach statements."

THE DESIGN.
  * The words are never touched. An annotation pins the SHA-256 of the original field text; a row whose words differ
    is not the annotated row and is never served under it.
  * An annotation is a separate, dated, append-only record: it says what the read cited, what the source record shows
    now, when the platform's record changed, and why (late-logged entries; a vendor revision after the read). It
    carries no coach words and nothing from a private source — only the public figures the read itself cited.
  * Authorship is explicit: ``AUTHOR_ENGINE`` (derived by a record re-check, evidence named per correction) or
    ``AUTHOR_OWNER``. A later correction never edits an earlier one: it is a NEW entry naming the one it ``supersedes``
    (``tests/test_narrative_annotations.py`` pins every published entry's digest).
  * An annotated read is served ONLY as the pair (``annotated_words``): the words plus the rendered note. It is never
    in ``narrative_allowlist.APPROVED``, and ``narrative_allowlist.record_for`` refuses its key, so the narrative gate
    cannot publish the words alone.
  * Dark twice over: the pair is built only while ``CR2_PUBLIC`` is on inside the CR2 scope AND the owner has approved
    the annotation (``owner_approved``). Every entry below is unapproved; no route calls ``annotated_words`` yet.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, NamedTuple, Optional

AUTHOR_ENGINE = "engine"
AUTHOR_OWNER = "owner"
CAUSE_LATE_LOGGED = "late_logged_entries"
CAUSE_VENDOR_REVISION = "vendor_revision_after_read"
_CAUSE_WORDS = {
    CAUSE_LATE_LOGGED: "{n} more {entries} for that day {were} logged after the read was written",
    CAUSE_VENDOR_REVISION: "{vendor} revised the scored record after the read was written",
}


class Correction(NamedTuple):
    figure: str  # what the figure is, in reader words ("protein for 1 October")
    unit: str  # appended to both values in the note (" g", " hours", "")
    source_field: str  # the cited block's source_field
    as_cited: str
    record_now: str
    record_rewritten_at: str  # ISO-8601 UTC: when the platform's stored record took the current value
    cause: str
    cause_detail: dict  # the words' parameters (entries added; the vendor)
    evidence: str  # where the re-check read it (record keys, timestamps; never coach words)


class Annotation(NamedTuple):
    annotation_id: str
    pk: str
    sk: str
    field: str
    text_sha256: str  # the ORIGINAL words — preserved verbatim, never rewritten
    read_written_at: str
    annotated_at: str
    author: str
    method: str
    corrections: tuple
    conclusion_note: str  # "" when the read stated no conclusion the corrected figure changes
    owner_approved: bool
    supersedes: Optional[str] = None


_METHOD = (
    "record re-check 2026-11-10: the read's stored cited block against the current source row (read-only) and the "
    "versioned raw exports/fetches behind it"
)

ANNOTATIONS: tuple = (
    Annotation(
        annotation_id="ann-2026-11-10-lead-2026-10-02",
        pk="COACH#eli_marsh",
        sk="LEAD_DAILY#2026-10-02",
        field="text",
        text_sha256="b17633df3db211ed61653552144a573fb0d1d6c219183b54308c4cff01722f84",
        read_written_at="2026-10-02T17:07:37Z",
        annotated_at="2026-11-10",
        author=AUTHOR_ENGINE,
        method=_METHOD,
        corrections=(
            Correction(
                figure="protein for 1 October",
                unit=" g",
                source_field="macrofactor.total_protein_g",
                as_cited="166",
                record_now="186",
                record_rewritten_at="2026-10-06T04:03:25Z",
                cause=CAUSE_LATE_LOGGED,
                cause_detail={"n": 2},
                evidence=(
                    "MacroFactor export uploaded 2026-10-02T03:33Z: 9 entries / 166 g for 2026-10-01 (the read's input); "
                    "export uploaded 2026-10-06T04:03Z: 11 entries / 186 g; source row ingested_at 2026-10-06T04:03:25Z"
                ),
            ),
        ),
        conclusion_note="With the corrected figure the 170 g protein floor was met that day.",
        owner_approved=False,
    ),
    Annotation(
        annotation_id="ann-2026-11-10-lead-2026-10-07",
        pk="COACH#eli_marsh",
        sk="LEAD_DAILY#2026-10-07",
        field="text",
        text_sha256="5a2579bab931f98d1e679558d8618c76575691c5b513a50a3c00bd3e092d3240",
        read_written_at="2026-10-07T17:00:15Z",
        annotated_at="2026-11-10",
        author=AUTHOR_ENGINE,
        method=_METHOD,
        corrections=(
            Correction(
                figure="the recovery score on 7 October",
                unit="",
                source_field="whoop.recovery_score",
                as_cited="77",
                record_now="78",
                record_rewritten_at="2026-10-10T04:00:34Z",
                cause=CAUSE_VENDOR_REVISION,
                cause_detail={"vendor": "Whoop"},
                evidence="Whoop recovery/sleep records updated_at 2026-10-07T18:15:53Z (read written 17:00:15Z); source row re-fetched 2026-10-10T04:00Z",
            ),
            Correction(
                figure="sleep the night before 7 October",
                unit=" hours",
                source_field="whoop.sleep_duration_hours",
                as_cited="7.9",
                record_now="8.2",
                record_rewritten_at="2026-10-10T04:00:34Z",
                cause=CAUSE_VENDOR_REVISION,
                cause_detail={"vendor": "Whoop"},
                evidence="same Whoop sleep record, updated_at 2026-10-07T18:15:53Z; (in bed - awake) now 8.23 h",
            ),
        ),
        conclusion_note="",
        owner_approved=False,
    ),
    Annotation(
        annotation_id="ann-2026-11-10-lead-2026-10-17",
        pk="COACH#eli_marsh",
        sk="LEAD_DAILY#2026-10-17",
        field="text",
        text_sha256="4743d258c5e3c3180c3f84d09109f8bc683c5078258eada2adafa2852edb354e",
        read_written_at="2026-10-17T17:00:18Z",
        annotated_at="2026-11-10",
        author=AUTHOR_ENGINE,
        method=_METHOD,
        corrections=(
            Correction(
                figure="the recovery score on 17 October",
                unit="",
                source_field="whoop.recovery_score",
                as_cited="60",
                record_now="62",
                record_rewritten_at="2026-10-20T04:00:34Z",
                cause=CAUSE_VENDOR_REVISION,
                cause_detail={"vendor": "Whoop"},
                evidence="Whoop recovery/sleep records updated_at 2026-10-17T17:30:53Z (read written 17:00:18Z; the sleep record now ends 17:04:26Z); source row re-fetched 2026-10-20T04:00Z",
            ),
            Correction(
                figure="sleep the night before 17 October",
                unit=" hours",
                source_field="whoop.sleep_duration_hours",
                as_cited="7.4",
                record_now="8.8",
                record_rewritten_at="2026-10-20T04:00:34Z",
                cause=CAUSE_VENDOR_REVISION,
                cause_detail={"vendor": "Whoop"},
                evidence="same Whoop sleep record, updated_at 2026-10-17T17:30:53Z; (in bed - awake) now 8.84 h",
            ),
        ),
        conclusion_note="",
        owner_approved=False,
    ),
    Annotation(
        annotation_id="ann-2026-11-10-lead-2026-10-28",
        pk="COACH#eli_marsh",
        sk="LEAD_DAILY#2026-10-28",
        field="text",
        text_sha256="52e0906407fe7a8bd4b448c45f2b6638450c11b3d1c742ff3cc95fe54c994d4f",
        read_written_at="2026-10-28T17:00:56Z",
        annotated_at="2026-11-10",
        author=AUTHOR_ENGINE,
        method=_METHOD,
        corrections=(
            Correction(
                figure="protein for 27 October",
                unit=" g",
                source_field="macrofactor.total_protein_g",
                as_cited="111",
                record_now="139",
                record_rewritten_at="2026-11-03T06:54:39Z",
                cause=CAUSE_LATE_LOGGED,
                cause_detail={"n": 1},
                evidence=(
                    "MacroFactor export uploaded 2026-10-28T06:54Z: 8 entries / 111 g for 2026-10-27 (the read's input); "
                    "export uploaded 2026-11-03T06:54Z: 9 entries / 139 g; source row ingested_at 2026-11-03T06:54:39Z"
                ),
            ),
        ),
        conclusion_note="The corrected figure is still below the 170 g protein floor.",
        owner_approved=False,
    ),
)

INDEX: dict = {(a.pk, a.sk): a for a in ANNOTATIONS if not any(b.supersedes == a.annotation_id for b in ANNOTATIONS)}
KEYS: frozenset = frozenset((a.pk, a.sk) for a in ANNOTATIONS)


def digest(a: Annotation) -> str:
    """The content hash of one annotation — what the append-only test pins."""
    return hashlib.sha256(json.dumps(a._asdict(), sort_keys=True, default=lambda o: o._asdict()).encode("utf-8")).hexdigest()


def _day(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%B %Y')}"


def _cause_words(c: Correction) -> str:
    detail = dict(c.cause_detail)
    if c.cause == CAUSE_LATE_LOGGED:
        n = int(detail.get("n", 1))
        return _CAUSE_WORDS[c.cause].format(n=n, entries="entry" if n == 1 else "entries", were="was" if n == 1 else "were")
    return _CAUSE_WORDS[c.cause].format(**detail)


def render_note(a: Annotation) -> str:
    """The reader-facing correction, built from the record only (deterministic; no coach words)."""
    parts = [f"Correction added {_day(a.annotated_at)}. These words are shown exactly as written on {_day(a.read_written_at)}."]
    changes = [
        f"{c.figure} now reads {c.record_now}{c.unit}, not {c.as_cited}{c.unit} "
        f"({_cause_words(c)}; record updated {_day(c.record_rewritten_at)})"
        for c in a.corrections
    ]
    parts.append("Since then the record has changed: " + "; ".join(changes) + ".")
    if a.conclusion_note:
        parts.append(a.conclusion_note)
    return " ".join(parts)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def annotated_words(item: Any, pk: Any = None) -> Optional[dict]:
    """The one way an annotated read is published: ``{"words", "annotation"}`` together, or None (withheld).

    Fail closed at every step: CR2 on and in scope; an owner-approved annotation for this key; no provenance record of
    the row's own; the words byte-identical to the annotated original; no private activity named; the row's own cited
    block entirely public."""
    from common import narrative_allowlist as NA, narrative_provenance as NP

    if not NA.active() or not isinstance(item, dict) or NP.PROVENANCE_KEY in item:
        return None
    a = INDEX.get((str(item.get("pk", pk) or ""), str(item.get("sk") or "")))
    if a is None or not a.owner_approved:
        return None
    text = item.get(a.field)
    if not isinstance(text, str) or _sha(text) != a.text_sha256:
        return None
    from common import prediction_publication as PP

    if PP.words_name_private_activity(text):
        return None
    from coach.lead_daily_read import provenance_for

    families = list(provenance_for(item.get("cited") or [])["families"])
    if not NP.is_publishable({"v": NP.SCHEMA_VERSION, "families": families}):
        return None
    note = render_note(a)
    return {
        "words": text,
        "annotation": {
            "id": a.annotation_id,
            "kind": "correction",
            "annotated_at": a.annotated_at,
            "read_written_at": a.read_written_at,
            "author": a.author,
            "note": note,
            "corrections": [
                {k: c._asdict()[k] for k in ("figure", "unit", "as_cited", "record_now", "record_rewritten_at", "cause")}
                for c in a.corrections
            ],
            "supersedes": a.supersedes,
        },
    }
