"""record_text.py — the ONE place that names the attribute a narrative record's text lives in.

#2569. `deploy/backfill_recall_embeddings.py::gather_journal` read a journal entry's body
from ``content`` / ``body`` / ``text``. The notion writer stores it in ``raw_text``
(always — at minimum the ``[template]`` label plus the property dump) and ``body_text``
(whenever the Notion page has free-writing body). None of the three names the reader
guessed has ever existed on a live row, so every journal record failed the reader's
``if not text: continue`` guard and **semantic recall never indexed a single journal
entry**. The corpus was chronicle-only by silent data loss, not by a scope decision.

The coach half of the same script was broken the same way and larger: it read
``output_text`` / ``text`` while ``coach.coach_state_updater._write_output_record``
writes the narrative to ``content``. Measured 2026-08-11 against live DynamoDB: 851
``OUTPUT#`` rows across the seven operational coaches, all carrying ``content``, none
carrying ``output_text`` or ``text`` — and a 19-row recall corpus that is 100%
``kind=chronicle``.

A second hardcoded guess at the read site is exactly how that recurs, so the field names
are NOT restated there. They live here once and the **writers** use these same constants
to name the attributes they put. `tests/test_recall_journal_field_2569.py` runs a record
through the real writer and asserts the reader below extracts its text, so renaming a
writer's attribute goes red at the reader instead of silently emptying a corpus.

Stdlib-only, no I/O — safe to import from an ingestion Lambda, a coach Lambda, and an
operator script alike.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ── journal (notion) ────────────────────────────────────────────────────────
# `ingestion.notion_lambda.parse_page` writes BOTH: `raw_text` unconditionally, and
# `body_text` only when the page body fetch succeeded and returned something. Preference
# order is the writer's own — `_archive_page_raw` archives `body_text or raw_text`,
# because the body is the human's free writing and `raw_text` wraps it in a template
# label plus a "--- Properties ---" dump.
JOURNAL_BODY_FIELD = "body_text"
JOURNAL_RAW_FIELD = "raw_text"
JOURNAL_TEXT_FIELDS: tuple[str, ...] = (JOURNAL_BODY_FIELD, JOURNAL_RAW_FIELD)

# ── coach outputs ───────────────────────────────────────────────────────────
# `coach.coach_state_updater._write_output_record` puts the generated narrative here, and
# every serving path (site_api_coach, the quality gate's history read) falls back to it.
COACH_OUTPUT_FIELD = "content"
COACH_OUTPUT_TEXT_FIELDS: tuple[str, ...] = (COACH_OUTPUT_FIELD,)


def first_text(item: Mapping[str, Any], fields: Sequence[str]) -> str:
    """First non-blank string among `fields` on `item`, stripped — "" when none carries text.

    Non-string values (a Decimal, a list, None) are treated as absent rather than
    coerced: a record whose text attribute holds a non-string is malformed, and
    ``str()``-ing it would embed ``"[]"`` as if it were prose.
    """
    for field in fields:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def journal_text(item: Mapping[str, Any]) -> str:
    """The embeddable/readable body of a notion journal record (`#journal#` sort key)."""
    return first_text(item, JOURNAL_TEXT_FIELDS)


def coach_output_text(item: Mapping[str, Any]) -> str:
    """The generated narrative of a coach `OUTPUT#` record."""
    return first_text(item, COACH_OUTPUT_TEXT_FIELDS)
