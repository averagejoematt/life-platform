"""withheld_outputs.py — the words of every coach OUTPUT row the narrative-provenance policy withholds (#6193).

THE GAP. ``narrative_publication.is_tainted`` checks a text against the withheld GRADED record (predictions, commitments,
learnings, the docket — ``publication_snapshot``). A coach's daily output rows (``COACH#<seat>`` / ``OUTPUT#<day>#…``:
``public_summary``, ``content``, …) are outside that set by design: the Site API empties a withheld output row's text AT
THE READ (``gate_item``), so on a site route its words never reach a response, and there is nothing to scrub at the wire.
A chapter EDITION is different: its prose is written off the page and proposed whole, so a sentence copied word for word
from a withheld daily output passed the gate while the same policy withholds that row from every public page and API.

THE RULE (owner ruling 2026-11-22: passages that depend exclusively on withheld daily summaries are removed; "Do not use a
global privacy bypass"). For the publication gate of an edition (``content.chapter_editions.gate_findings``' ``tainted``),
a text is ALSO refused when it is, or carries a ``SHINGLE``-word run of, the free text of an OUTPUT row the policy
withholds — the same normalisation, the same run length and the same decision (``narrative_publication._decide``, the
owner's by-record exceptions included) as the graded record. It is NOT added to the Site API's wire scrub: that would
change every public response, and a site route already empties those rows at the read.

FAIL CLOSED. Every coach partition's OUTPUT rows are read whole (all pages); one failed read and there is no answer —
``load`` raises and the caller refuses (the gates report "could not be read" and nothing is published). The result is
cached ``TTL_S`` per table, like the graded record.
"""

from __future__ import annotations

import time
from typing import Any, Callable

TTL_S = 900  # = publication_snapshot.TTL_S: the publication reads age together
#: The withheld narrative families this set covers, by sort-key prefix (graded families are the snapshot's).
SK_PREFIXES = ("OUTPUT#",)
_CACHE: dict = {"table": None, "at": None, "sets": None}


def reset() -> None:
    _CACHE.update(table=None, at=None, sets=None)


def _raw(table: Any) -> Any:
    from web import narrative_publication as NPub  # noqa: PLC0415

    return table.wrapped if isinstance(table, NPub.PublicationTable) else table


def digest(rows_by_pk: dict) -> tuple:
    """``(exact, shingles)`` of every free-text value of every WITHHELD row — pure (rows in, hashes out)."""
    from common import narrative_allowlist as NA, narrative_provenance as NP  # noqa: PLC0415

    from web import narrative_publication as NPub  # noqa: PLC0415

    exact: set = set()
    shingles: set = set()
    with NA.closed():
        for pk, rows in rows_by_pk.items():
            for row in rows:
                if not NPub.is_narrative_row(pk, row.get("sk")) or NPub._decide(row, pk)[0]:
                    continue
                for key, value in row.items():
                    if key in NPub.TAINT_SKIP_KEYS or key == NP.PROVENANCE_KEY:
                        continue
                    for text in NPub._prose_strings(value, key):
                        e, sh = NPub._text_hashes(text)
                        if e is not None:
                            exact.add(e)
                            shingles.update(sh)
    return frozenset(exact), frozenset(shingles)


def read(table: Any) -> dict:
    """``{pk: [rows]}`` — every OUTPUT row of every coach partition, whole. Raises on any failed or partial read."""
    from web import publication_snapshot as PS  # noqa: PLC0415

    raw = _raw(table)
    out: dict = {}
    for pk in PS.partitions():
        if pk == PS.DOCKET_PK:
            continue
        out[pk] = []
        for prefix in SK_PREFIXES:
            out[pk] += PS._query_pages(raw, pk, prefix)
    return out


def load(table: Any) -> tuple:
    """The withheld output words of ``table`` (cached ``TTL_S``). Raises when they cannot be read."""
    now = time.monotonic()
    raw = _raw(table)
    if _CACHE["table"] is raw and _CACHE["sets"] is not None and now - _CACHE["at"] < TTL_S:
        return _CACHE["sets"]
    sets = digest(read(raw))
    _CACHE.update(table=raw, at=now, sets=sets)
    return sets


def matcher(sets: tuple) -> Callable[[Any], bool]:
    """``text -> bool``: the text is, or carries a ``SHINGLE``-word run of, a withheld output's words. The owner's
    approved words (``narrative_allowlist.is_approved_text``) pass exactly as they do the graded record."""
    from common import narrative_allowlist as NA  # noqa: PLC0415

    from web import narrative_publication as NPub  # noqa: PLC0415

    exact, shingles = sets

    def hit(text: Any) -> bool:
        if not isinstance(text, str) or not exact or NA.is_approved_text(text):
            return False
        words = NPub._norm_words(text)
        if len(words) < NPub.EXACT_MIN_WORDS:
            return False
        if hash(words) in exact:
            return True
        return any(hash(words[i : i + NPub.SHINGLE]) in shingles for i in range(len(words) - NPub.SHINGLE + 1))

    return hit


def with_outputs(tainted: Callable[[str], bool], table: Any) -> Callable[[str], bool]:
    """``tainted`` (the graded record) OR the withheld outputs of ``table`` — the edition gate's one ``tainted``. The
    outputs are read lazily at the first check and raise if unreadable (the gate then refuses, fail closed)."""

    def both(text: str) -> bool:
        return bool(tainted(text)) or matcher(load(table))(text)

    return both
