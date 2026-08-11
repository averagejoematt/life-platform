"""recall_consent.py — the consent gate on the WRITE side of semantic recall (#2587).

`semantic_recall` is the read side, `recall_indexer` (+ `deploy/backfill_recall_embeddings.py`)
the write side. Neither passed through `privacy/diary_consent.py`. That was survivable only
because the corpus happened to be chronicle-only: measured against live DynamoDB on
2026-08-11, all 19 rows are `kind=chronicle`, zero journal, zero coach_output. #2569's
reader fix (PR #2580) makes 60 journal rows and 851 coach outputs *eligible*, and
`backfill_recall_embeddings` stores `snippet=_snippet(doc["text"])` — a VERBATIM excerpt of
the entry body. `semantic_recall.retrieve()` then feeds whatever it finds into the coach
prompt, whose narrative is published. That is the exact crossing `diary_consent` exists to
forbid, on a road the gate was never placed on.

This module is that gate, at INDEX time.

WHY INDEX TIME, AND WHY "NOT INDEXED" RATHER THAN "INDEXED WITHOUT A SNIPPET".
`diary_consent.public_context()` returns ``None`` for a private entry — the entry does not
cross into a public reaction *at all*, not "crosses with its text removed". Three reasons to
keep that shape here:

  1. The embedding vector is itself a derivative of the verbatim body, and the corpus exists
     precisely to be matched and surfaced.
  2. Even with an empty snippet, a match still emits ``This period echoes the week of
     <date>`` plus a link into the coach prompt. That discloses that something happened on
     an uncleared date which resembles now — a claim the owner never cleared. Redaction of
     the snippet does not redact the assertion.
  3. Absence needs no downstream cooperation. A redacted-but-present row stays safe only for
     as long as every future consumer honours the redaction; `rank_precedents` already
     copies `snippet` through, `recall_card` re-exposes it, and the next field added to the
     row inherits no guard at all. Fail-closed by absence, not by discipline.

ALLUDE AND QUOTE ARE DIFFERENT PERMISSIONS — this module does not collapse them:

  * ``quote``  — the owner cleared ONE specific line and it grounds as a literal substring
                 of the body (`diary_consent` checks both). The stored snippet is THAT LINE
                 and nothing else. It is emphatically **not** ``_snippet(body)``: clearing a
                 line is not clearing the entry, and the pre-#2587 writer would have stored
                 the first 240 characters of the body for a quote-tier entry — a strictly
                 larger disclosure than the one that was granted.
  * ``allude`` — paraphrase only, NO verbatim text. The stored snippet is BUILT from the
                 sanctioned projection (`public_context`: coarse 8-way theme + channel),
                 field by field, never filtered from the source record — the same
                 construction discipline as `diary_consent.conversation_reference`. A coach
                 can then say the period echoes that entry and what it was broadly about,
                 which is what allude means, without a word of the entry reaching the prompt.
  * ``private`` — and anything unresolvable — is not indexed.

FAIL-CLOSED IN EVERY DIRECTION. A kind with no explicit policy entry is not indexable. A
diary-policy doc that arrives without its source record is not indexable (consent cannot be
resolved, so it is private — never "probably fine"). The precedence itself is NOT
re-implemented here: tier resolution is `diary_consent.resolve_consent` /
`diary_consent.public_context`, called, not copied.

NOT A REVOCATION SWEEP. This gate governs what ENTERS the corpus. It does not delete a row
that was indexed before a consent marker was withdrawn — the live corpus has zero journal
rows (audited above), so there is nothing to revoke today, and a delete path with no live
case to exercise it is worse than an explicit boundary. Revocation is an operator sweep if
and when a cleared entry is ever un-cleared.

Stdlib + two bundled pure modules, no AWS, no I/O — so the leak-proof invariant is
unit-testable with zero live calls.
"""

from __future__ import annotations

from typing import NamedTuple

from privacy import diary_consent

from ai import semantic_recall as sr

# ── exposure strengths, weakest → strongest ─────────────────────────────────
EXPOSURE_NONE = "none"  # do not index at all
EXPOSURE_ALLUDE = "allude"  # index; NO verbatim text may be stored
EXPOSURE_QUOTE = "quote"  # index; a verbatim excerpt is permitted

# ── per-kind policy ─────────────────────────────────────────────────────────
# WHICH consent regime governs a corpus kind. This is a decision per kind, not a
# blanket rule, because the kinds are not alike:
#
#   published_artifact — the doc IS a public page that already passed its own
#       publication gate (a chronicle installment is only indexed at status
#       ``published``; a coach output is served on /coaching/). A verbatim excerpt of
#       text the reader can already open discloses nothing new.
#   diary_consent — the doc is Matthew-private writing whose exposure is decided
#       per ENTRY by the owner's marker (`diary_consent`).
#
# A kind that is not a key here is NOT INDEXABLE (see `decide`). That is the
# excluded-by-default property: adding a kind to `semantic_recall.KINDS` without an
# entry below turns it off rather than silently opting it in, and
# `tests/test_recall_consent_2587.py` fails until the decision is written down.
POLICY_PUBLISHED_ARTIFACT = "published_artifact"
POLICY_DIARY_CONSENT = "diary_consent"

KIND_POLICY: dict[str, str] = {
    sr.KIND_CHRONICLE: POLICY_PUBLISHED_ARTIFACT,
    sr.KIND_COACH: POLICY_PUBLISHED_ARTIFACT,
    sr.KIND_JOURNAL: POLICY_DIARY_CONSENT,
}

# The doc key carrying the SOURCE DynamoDB record for a diary-policy doc. The gatherer
# attaches it; without it consent cannot be resolved and the doc is withheld.
RECORD_KEY = "record"

SNIPPET_CHARS = 240


class Decision(NamedTuple):
    """The index-time verdict for one corpus doc.

    `indexable` — may a row be written at all.
    `exposure`  — the strength that was actually granted (never higher than the tier).
    `snippet`   — the ONLY text that may be stored on the row. "" for allude-with-no
                  describable projection, and always "" when `indexable` is False.
    `reason`    — a short, loggable explanation; the operator-visible audit trail.
    """

    indexable: bool
    exposure: str
    snippet: str
    reason: str


def _collapse(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Whitespace-collapsed lead — same shaping as `recall_indexer.snippet`, inlined so
    this privacy hot path has no import edge back into the writer it guards."""
    return " ".join(str(text or "").split())[:limit]


def _allude_projection(ctx: dict) -> str:
    """The non-verbatim descriptor stored for an allude-tier entry.

    BUILT from the sanctioned `public_context` projection key by key — theme and channel,
    both already laundered to the coarse public vocabulary — never filtered from the
    source record, so no private field can ride along even if the entry schema grows.
    """
    theme = str((ctx or {}).get("theme") or "other")
    channel = str((ctx or {}).get("channel") or "journal")
    return f"journal entry ({channel}) — theme: {theme}. Allude tier: no verbatim text was cleared for public use."


def decide(kind: str, text: str, record=None) -> Decision:
    """The index-time consent verdict for one doc. Pure; never raises.

    `record` is the source DynamoDB item, required for a `diary_consent`-policy kind and
    ignored for a published-artifact kind.
    """
    policy = KIND_POLICY.get(str(kind or ""))
    if policy is None:
        return Decision(False, EXPOSURE_NONE, "", f"kind {kind!r} has no consent policy — excluded by default (#2587)")

    if policy == POLICY_PUBLISHED_ARTIFACT:
        return Decision(True, EXPOSURE_QUOTE, _collapse(text), f"kind {kind!r} is a published artifact — verbatim excerpt permitted")

    # POLICY_DIARY_CONSENT — the owner's per-entry marker decides, fail-closed.
    if not isinstance(record, dict) or not record:
        return Decision(False, EXPOSURE_NONE, "", "no source record — consent unresolvable, therefore private (#2587)")

    ctx = diary_consent.public_context(record)
    if ctx is None:
        return Decision(False, EXPOSURE_NONE, "", f"consent tier {diary_consent.resolve_consent(record)!r} — not indexed")

    # `public_context` has ALREADY degraded a quote-tier entry whose cleared line does not
    # ground down to allude strength, and only then carries the cleared line.
    if ctx.get("tier") == diary_consent.TIER_QUOTE and ctx.get("quote"):
        return Decision(True, EXPOSURE_QUOTE, _collapse(ctx["quote"]), "quote tier — the owner-cleared line only, not the entry body")
    return Decision(True, EXPOSURE_ALLUDE, _allude_projection(ctx), "allude tier — coarse theme only, no verbatim text")


def decide_doc(doc) -> Decision:
    """`decide` for a corpus doc as the gatherers shape it — the form BOTH writers call
    (`recall_indexer.index_document` and `deploy/backfill_recall_embeddings.py`), so the
    verdict cannot differ between the publish-time Lambda and the operator backfill."""
    doc = doc or {}
    return decide(doc.get("kind", ""), doc.get("text", ""), doc.get(RECORD_KEY))
