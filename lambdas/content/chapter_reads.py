"""content/chapter_reads.py — the ONE predicate for "a chapter a writer may read" (#6199, G1).

WHY. A chapter row can be published and still be one no writer may read again: the owner withdrew it (``withdrawn``),
a reset tombstoned it (``tombstone``), or it was taken off the reading list (``unlisted``). Every place that hands a
stored chapter's text to a writer — as "the previous installment", the archive, the recap's grounding, the Panel's
script source or a rebuild's prologue — reads through ``writer_may_read``. A row it rejects is skipped as if absent.
A draft (any status but ``published``) is not part of the story either, so it is rejected too; a row with no status at
all is read as published (the "previously on" recap's long-standing rule — every such row in the table is tombstoned).

``withdrawn`` is an annotation the owner approves as a data step (``withdrawn: "<reason>"`` + ``withdrawn_at``); the
row's text, status and history stay untouched. Nothing in the pipeline writes it.

tests/test_chapter_reads_withdrawn.py guards the SET: every module under ``lambdas/`` and ``scripts/`` that reads a
chapter's ``content_markdown`` either calls ``writer_may_read`` or is registered there with the reason it is not a
writer-side read. A new reader fails CI until it does one or the other.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping

PUBLISHED = "published"
WITHDRAWN_ATTR = "withdrawn"


def writer_may_read(item: Any) -> bool:
    """True only for a published (or status-less) chapter row that is not withdrawn, tombstoned, hidden or unlisted."""
    if not isinstance(item, Mapping):
        return False
    if str(item.get("status") or PUBLISHED).strip().lower() != PUBLISHED:  # no status = an early row: the recap's rule
        return False
    return not any(item.get(flag) for flag in (WITHDRAWN_ATTR, "tombstone", "hidden", "unlisted"))


def is_withdrawn(item: Any) -> bool:
    """True when the owner withdrew the chapter — for a status-agnostic reader (the recall corpus keeps drafts and
    earlier cycles on purpose, but never a withdrawn chapter)."""
    return isinstance(item, Mapping) and bool(item.get(WITHDRAWN_ATTR))


def readable(items: Iterable[Any]) -> List[Any]:
    """The rows of ``items`` a writer may read, in their order."""
    return [it for it in items or () if writer_may_read(it)]
