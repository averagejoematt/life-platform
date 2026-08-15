"""recall_indexer.py — the WRITE side of semantic recall (#1384).

`semantic_recall` is the READ side: load the corpus, cosine-rank it, render precedents
into the coach prompt. Nothing in `lambdas/` ever WROTE to that corpus. The only writer
was `deploy/backfill_recall_embeddings.py`, an operator-run script — so the corpus was
exactly as fresh as the last time a human remembered to run it. Measured 2026-08-08: all
17 rows carried an `embedded_at` inside a single three-second window on 2026-07-25, the
newest `doc_date` was 2026-07-21, and both chronicle records dated after that freeze were
absent from it — 2026-08-02 reader-visible and genuinely missing, 2026-07-26 a wiped
prior-cycle record with no reader page. Every future week would have been missing too.

A retrieval index with no incremental writer does not go stale loudly; it just quietly
returns fewer precedents, which reads exactly like "there is no precedent". That is the
ADR-104 failure mode: manufactured absence.

This module closes the loop. It is the write half, kept OUT of `semantic_recall` so the
read path stays pure and unit-testable with no AWS and no Bedrock.

WHY AT PUBLISH, NOT AT DRAFT. An installment is stored as a `draft` first and only
becomes `published` when Matthew approves it (`chronicle_approve_lambda`). Indexing a
draft would be wrong three ways: the text can still change (`changes_requested` is the
documented signal to re-run the generator), the week may never publish at all, and the
reader link `/journal/posts/week-NN/` does not exist until it does. So the hook rides
alongside `_commit_recap` — the other on-publish side-effect — and for the same reason:
these are the things that become true when the week goes live, not when it is written.

LINKS ARE DERIVED, NOT GUESSED (#1827). `published_post_links` moved here from the
backfill so there is ONE definition of where an installment lives, shared by the script
and the Lambda. It stays pinned to `chronicle_render.journal_post_ref` by
`tests/test_recall_precedent_links_1827.py` — the parity test, not a restatement. An
installment with no published page gets NO link rather than another week's URL; the
renderer then cites the date alone, which is the honest form.

FAIL-SOFT, ALWAYS. Every entry point returns a status string and raises nothing. A
budget pause (band 2, ADR-125 — recall pauses with the reader narrative it decorates), a
missing record, an empty body or a Bedrock error all leave the corpus exactly as it was.
Indexing must never be able to block a week from publishing; a missed embed costs one
precedent, and `qa_smoke` reports the staleness rather than letting it pass silently.

Idempotent by construction (AC4): the sk is deterministic and `text_sha` gates the
re-embed, so re-running the hook on an already-indexed week is free and writes nothing.
"""

from __future__ import annotations

import logging

from ai import recall_consent as rc, semantic_recall as sr

logger = logging.getLogger(__name__)

# #2705: every FAILED below used to discard its exception. The freshness guard then
# reported THAT an installment was missing while nothing recorded WHY — 2026-08-11
# sat unindexed for four days and the cause had to be reverse-engineered from a bare
# `[recall] index 2026-08-11: failed` logged at INFO. Fail-soft is right; silent is not.

# Status strings returned by the indexing entry points. Callers log these; the two
# that mean "the corpus changed" are INDEXED (a row was embedded + written) and
# REPAIRED (stale metadata refreshed on an already-embedded row, no spend — #2366).
INDEXED = "indexed"
REPAIRED = "repaired"
UNCHANGED = "unchanged"
SKIPPED_BUDGET = "skipped:budget"
SKIPPED_NO_RECORD = "skipped:no-record"
SKIPPED_NOT_PUBLISHED = "skipped:not-published"
SKIPPED_NO_TEXT = "skipped:no-text"
# #2587: the doc's consent tier does not permit it in the corpus at all (an unmarked or
# private diary entry, a kind with no policy). Kept DISTINCT from the other skips: this
# one is the privacy gate doing its job, and a freshness sensor must not read it as a
# fault to be repaired.
SKIPPED_CONSENT = "skipped:consent"
# An embed or write that actually failed, kept DISTINCT from the "nothing to do" skips:
# the first is a fault the freshness guard should keep reporting, the rest are correct
# outcomes. Collapsing them would let a broken embedder read as a quiet no-op.
FAILED = "failed"

CHRONICLE_SOURCE = "chronicle"


def snippet(text: str, n: int = 240) -> str:
    """Whitespace-collapsed lead of the embedded text, for the precedent line.

    `make_embedding_item` caps the stored value at 280 chars; this trims earlier so the
    snippet ends on the source's own words rather than mid-token at the storage cap.
    """
    return " ".join((text or "").split())[:n]


def date_from_sk(sk: str, prefix: str = "DATE#") -> str:
    """Extract YYYY-MM-DD from a DATE#/OUTPUT# sort key (the token after the marker)."""
    if prefix not in sk:
        return ""
    return sk.split(prefix, 1)[1].split("#", 1)[0]


def published_post_links(installments) -> dict:
    """{(date, sk): "/journal/posts/week-NN/"} for the installments that are ACTUALLY
    PUBLISHED — #1827.

    The original backfill emitted `/chronicle/week-{week_number}/`, which is not a page
    on the live site (all 17 live rows 404'd, and the form was non-unique across cycles:
    `week-0` appeared 6 times). Installments publish at `/journal/posts/week-{seq:02d}/`
    where `seq` is the position in the (date, sk)-sorted list of VISIBLE installments —
    exactly `chronicle_render.publish_to_journal::_seq_for` / `journal_post_ref`, which
    `tests/test_recall_precedent_links_1827.py` pins this against.

    Visibility matters: only phase-visible installments are published, so a wiped
    prior-cycle installment gets NO url here. It stays in the recall corpus (cross-cycle
    memory is the point) but is cited by DATE alone — an honest absence beats a link to
    some other week's page.
    """
    from experiment.phase_filter import singleton_visible

    keys = sorted((i.get("date", ""), str(i.get("sk", ""))) for i in installments if singleton_visible(i) and i.get("date"))
    return {key: f"/journal/posts/week-{n + 1:02d}/" for n, key in enumerate(keys)}


def chronicle_doc(item: dict, links: dict) -> dict | None:
    """One chronicle installment record → the corpus doc shape, or None if it carries
    no embeddable text.

    Deliberately status-agnostic: the backfill embeds the whole archive regardless of
    publication state (cross-cycle memory is the point), and the publish-time caller
    applies its own status gate. The two callers differ in WHICH installments they
    offer, never in how a doc is built from one.
    """
    date = date_from_sk(str(item.get("sk", "")))
    if not date:
        return None
    text = " ".join(s for s in (item.get("title", ""), item.get("subtitle", ""), item.get("content_markdown", "")) if s).strip()
    if not text:
        return None
    return {
        "kind": sr.KIND_CHRONICLE,
        "date": date,
        "text": text,
        "artifact_pk": item["pk"],
        "artifact_sk": item["sk"],
        # Published → its real post URL. Not published (wiped prior cycle) → no link at
        # all; `semantic_recall.render_precedent_line` then cites the date alone rather
        # than a URL that 404s or points at another week.
        "link": links.get((item.get("date", ""), str(item.get("sk", ""))), ""),
        "cycle": item.get("cycle"),
    }


def metadata_drift(stored: dict, doc: dict) -> dict:
    """{attr: new_value} for the metadata that no longer matches the source record —
    `{}` when the stored row is already correct. Compares only what a refresh can fix
    without re-embedding: the reader `link` and the source `cycle` stamp.

    This is the repair half of the idempotency gate (#2366): `text_sha` correctly says
    "do not pay to re-embed", but the link scheme and cycle stamp can rot UNDER an
    unchanged text — #1827's retired `/chronicle/week-N/` slug sat on all 17 live rows
    precisely because the sha compare early-returned before anyone looked at the link.
    """
    drift: dict = {}
    new_link = doc.get("link", "") or ""
    if (stored.get("link") or "") != new_link:
        drift["link"] = new_link
    old_cycle = stored.get("cycle")
    new_cycle = doc.get("cycle")
    old_i = int(old_cycle) if old_cycle is not None else None
    new_i = int(new_cycle) if new_cycle is not None else None
    if old_i != new_i:
        drift["cycle"] = new_i
    return drift


def refresh_metadata(table, sk: str, drift: dict) -> None:
    """Write ONLY the drifted metadata attributes — no embedding call, no spend. A
    `cycle` that went away (source record lost its stamp) is REMOVED, not zeroed, so
    `_cycle_label` makes no cycle claim rather than a false one."""
    sets: list = []
    removes: list = []
    names: dict = {}
    values: dict = {}
    for i, (attr, val) in enumerate(sorted(drift.items())):
        names[f"#a{i}"] = attr
        if val is None:
            removes.append(f"#a{i}")
        else:
            sets.append(f"#a{i} = :v{i}")
            values[f":v{i}"] = val
    expr = " ".join(filter(None, ["SET " + ", ".join(sets) if sets else "", "REMOVE " + ", ".join(removes) if removes else ""]))
    kwargs: dict = {
        "Key": {"pk": sr.RECALL_PK, "sk": sk},
        "UpdateExpression": expr,
        "ExpressionAttributeNames": names,
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    table.update_item(**kwargs)


def _budget_allows() -> bool:
    """Band-2 gate (ADR-125): recall pauses with the reader narrative it decorates.

    An absent budget_guard is treated as ALLOW — the module is bundled, so its absence
    means a test harness, not a live tier-3 platform.
    """
    try:
        from ai.budget_guard import allow as _allow

        return bool(_allow("semantic_recall"))
    except ImportError:
        return True


def index_document(table, doc: dict, *, embed=None, now=None, model: str = "", force: bool = False) -> str:
    """Embed one corpus doc and write its row — unless its text is already indexed.

    Idempotency is the `text_sha` compare against the stored row, the same key the
    backfill uses, so the script and this Lambda path cannot double-embed each other's
    work — but the gate REPAIRS before it early-returns (#2366): a matching text whose
    stored `link`/`cycle` no longer equal the derived values gets a metadata refresh
    (one update_item, no embed, no spend) instead of a blind UNCHANGED. Without this,
    a link-scheme change rots every existing row and only an operator `--force` (paying
    to re-embed unchanged text) could touch them again.

    Returns a status string; never raises. `embed`/`now` are injected so tests run with
    no Bedrock and no wall clock.

    GATE ORDER: the budget gate sits between the repair path and the embed, not at the
    top — the repair is free (no Bedrock call), so a band-2 pause (ADR-125) must not be
    able to hold the corpus in a known-rotted state. Only the embed costs money; only
    the embed is gated.
    """
    if not doc or not (doc.get("text") or "").strip():
        return SKIPPED_NO_TEXT

    # #2587 — the consent gate, BEFORE the idempotency read and before any spend. It sits
    # ahead of the sha compare deliberately: a doc that may not be in the corpus may not be
    # in the corpus regardless of what a stored row says, and the repair path below would
    # otherwise happily refresh metadata on a row that should never have existed.
    decision = rc.decide_doc(doc)
    if not decision.indexable:
        return SKIPPED_CONSENT

    sk = sr.sk_for(doc["kind"], doc["date"])
    new_sha = sr.sha_text(doc["text"])
    if not force:
        try:
            stored = (table.get_item(Key={"pk": sr.RECALL_PK, "sk": sk}) or {}).get("Item") or {}
        except Exception:  # noqa: BLE001 — an unreadable row is treated as absent, and re-embedding is idempotent
            stored = {}
        if stored.get("text_sha") == new_sha:
            drift = metadata_drift(stored, doc)
            if not drift:
                return UNCHANGED
            try:
                refresh_metadata(table, sk, drift)
            except Exception as e:  # noqa: BLE001 — a failed repair is a fault the freshness guard keeps reporting
                logger.error("[recall] metadata repair FAILED for %s %s: %s", doc.get("kind"), doc.get("date"), e)
                return FAILED
            return REPAIRED

    if not _budget_allows():
        return SKIPPED_BUDGET

    try:
        if embed is None:
            from ai import bedrock_client as _bc

            embed = _bc.embed_text
            model = model or _bc.TITAN_EMBED_MODEL_ID
        if now is None:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()

        vector = embed(doc["text"])
        table.put_item(
            Item=sr.make_embedding_item(
                kind=doc["kind"],
                date=doc["date"],
                doc_date=doc.get("doc_date", doc["date"]),
                text=doc["text"],
                vector=vector,
                cycle=doc.get("cycle"),
                artifact_pk=doc["artifact_pk"],
                artifact_sk=doc["artifact_sk"],
                link=doc.get("link", ""),
                # #2587: the snippet is what CONSENT permits, never the raw lead of the
                # body. For a quote-tier entry that is the single owner-cleared line; for
                # allude, a built theme descriptor with no verbatim text in it.
                snippet=decision.snippet,
                model=model,
                dims=len(vector),
                embedded_at=now,
            )
        )
    except Exception as e:  # noqa: BLE001 — indexing is never load-bearing; the freshness guard reports the gap
        logger.error("[recall] embed/write FAILED for %s %s: %s", doc.get("kind"), doc.get("date"), e)
        return FAILED
    return INDEXED


def recall_card_for_text(table, text: str, *, exclude_dates=None, embed=None):
    """The AC3 recall card for `text`, or None. Never raises.

    `semantic_recall.recall_card` has existed since #1384 with ZERO production callers —
    the reader-facing half of the story ("the chronicle gains a 'this week resembles the
    week of …' card") was written, tested, and never wired to anything. This is the
    function that gives it a caller.

    None is a first-class answer: no corpus, a paused budget, an embedding failure, or no
    precedent at/above the 0.75 cosine floor all return None, and the caller renders
    nothing. A card that appears only when there is a real match is the ADR-104 contract —
    the alternative, a card that always renders with whatever scored highest, would
    manufacture a resemblance for every week.

    Ordering note for the chronicle: this runs during the render, BEFORE the week is
    indexed at publish, so the corpus contains strictly earlier weeks. The week cannot
    match itself and no `exclude_dates` gymnastics are needed to prevent it.
    """
    if table is None or not (text or "").strip():
        return None
    if not _budget_allows():
        return None
    try:
        if embed is None:
            from ai import bedrock_client as _bc

            embed = _bc.embed_text
        # #2587: READER_KINDS, not the coach allowlist — this card renders into a
        # published chronicle installment, so it may only cite a kind that has a page a
        # reader can open. Same decision as `ask_retrieval.PUBLISHED_KINDS`, derived from
        # the same registry.
        return sr.recall_card(sr.retrieve(table, embed(text), exclude_dates=exclude_dates, resolve=True, kinds=sr.READER_KINDS))
    except Exception:  # noqa: BLE001 — a card is decoration; its absence is honest, its failure is not fatal
        return None


def index_chronicle_installment(table, chronicle_pk: str, date_str: str, *, sk: str = "", embed=None, now=None) -> str:
    """Index the published chronicle installment for `date_str`. Never raises.

    Reads the whole chronicle partition because the reader link is a POSITION in the
    published ordering (#1827) — it cannot be derived from one record alone. That is one
    Query against a ~20-item partition, on a weekly path.

    Only a `published` installment is indexed: a draft's text can still change and its
    post URL does not exist yet, so indexing one would put text into the coach's
    precedent pool that no reader can open and that may never ship.
    """
    from boto3.dynamodb.conditions import Key

    target_sk = sk or f"DATE#{date_str}"
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(chronicle_pk) & Key("sk").begins_with("DATE#"))
        items = list(resp.get("Items", []))
    except Exception as e:  # noqa: BLE001 — indexing must never block a publish
        logger.error("[recall] chronicle partition read FAILED for %s: %s", date_str, e)
        return FAILED

    item = next((i for i in items if str(i.get("sk", "")) == target_sk), None)
    if item is None:
        return SKIPPED_NO_RECORD
    if str(item.get("status", "")) != "published":
        return SKIPPED_NOT_PUBLISHED

    doc = chronicle_doc(item, published_post_links(items))
    if doc is None:
        return SKIPPED_NO_TEXT
    return index_document(table, doc, embed=embed, now=now)
