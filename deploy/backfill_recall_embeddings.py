#!/usr/bin/env python3
"""backfill_recall_embeddings.py — #1384: one-time embed backfill for semantic recall.

Embeds the existing narrative archive (chronicle installments + coach outputs +
journal entries) into the recall-embeddings partition (Titan-v2 via the
bedrock_client chokepoint, ADR-062), so "when did I feel like this before?" has a
corpus to retrieve against. Spans resets (no phase filter) so cross-cycle memory
works from day one; each embedding item carries its source `cycle` stamp (AC5).

IDEMPOTENT (AC4): the sk is deterministic (DOC#<kind>#<date>) and each item stores
`text_sha`. A re-run skips any doc whose text is unchanged; `--force` re-embeds.
So this is safe to run as the single bulk pass AND as an incremental catch-up.

COST-LOGGED (AC4): dry-run (default) embeds NOTHING (zero spend) and just reports
what WOULD embed. `--apply` embeds + writes and prints a per-item line plus a rollup
with total input tokens (est.) and estimated USD — Titan v2 ≈ $0.02/1M tokens, so a
full backfill is pennies; the run is flagged as a single bulk pass in the summary.

Usage:
  python3 deploy/backfill_recall_embeddings.py                    # dry-run, all sources
  python3 deploy/backfill_recall_embeddings.py --apply            # embed + write
  python3 deploy/backfill_recall_embeddings.py --apply --kinds chronicle,journal
  python3 deploy/backfill_recall_embeddings.py --apply --force    # re-embed unchanged docs
  BEDROCK_SHADOW_MODE=1 python3 deploy/backfill_recall_embeddings.py --apply  # no-spend end-to-end
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
from ai import (
    bedrock_client as bc,  # noqa: E402
    recall_indexer as ri,  # noqa: E402
    semantic_recall as sr,  # noqa: E402
)
from boto3.dynamodb.conditions import Key  # noqa: E402
from common.record_text import coach_output_text, journal_text  # noqa: E402

# The doc-shaping helpers live in `ai.recall_indexer` (bundled) so the Lambda that indexes
# a week AT PUBLISH and this catch-up script share ONE definition — most importantly of
# `published_post_links`, whose previous single-caller life is what let #1827's dead
# `/chronicle/week-N/` slug reach all 17 live rows. Re-exported under the old names so
# this module's public surface (and the tests that load it by path) is unchanged.
_date_from_sk = ri.date_from_sk
_snippet = ri.snippet
published_post_links = ri.published_post_links
# The metadata repair pair moved into `ai.recall_indexer` too (#2366) so the publish-time
# Lambda's idempotency gate can self-repair a rotted link/cycle without an operator run —
# same motivation, same re-export contract.
metadata_drift = ri.metadata_drift
refresh_metadata = ri.refresh_metadata

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_PK_PREFIX = "USER#matthew#SOURCE#"

# Coach roster for OUTPUT# enumeration (COACH#<id>) — the canonical persona
# registry, so a coach add is a one-line change there, not here (#2334; was the
# orchestrator's routing-config keys, itself now registry-derived).
try:
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    DEFAULT_COACHES = sorted(OPERATIONAL_COACH_IDS)
except Exception:  # noqa: BLE001 — fall back to the known roster if the import path shifts
    # #2334 roster-copy waiver: fail-soft literal fallback for a standalone backfill
    # script — deriving it is the try-branch; this only serves when that import breaks.
    DEFAULT_COACHES = [
        "sleep_coach",
        "nutrition_coach",
        "mind_coach",
        "physical_coach",
        "glucose_coach",
        "labs_coach",
        "explorer_coach",
    ]


def _query_all(table, **kwargs):
    """Every item for a query, following LastEvaluatedKey.

    #2569 companion: the gatherers read a single 1MB page. `existing_rows` already
    paginates, so a truncated gather would have looked like "already indexed" for the
    head of a partition and silently dropped its tail — the same shape of invisible loss
    as reading the wrong attribute. Chronicle installments and coach outputs both carry
    multi-KB bodies, so the cap is reachable.
    """
    items = []
    while True:
        resp = table.query(**kwargs)
        items += list(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def gather_chronicle(table):
    """Chronicle installments — pk SOURCE#chronicle, sk DATE#<date>. One doc/week.

    Queried UNFILTERED (cross-reset recall is the point), but the reader link is derived
    from the PUBLISHED ordering (#1827) so every link that renders is a real page. The
    per-record shaping is `recall_indexer.chronicle_doc`, shared with the publish-time
    indexer so a week embedded by either path produces the identical row.
    """
    items = _query_all(table, KeyConditionExpression=Key("pk").eq(f"{USER_PK_PREFIX}chronicle") & Key("sk").begins_with("DATE#"))
    links = published_post_links(items)
    return [doc for doc in (ri.chronicle_doc(it, links) for it in items) if doc]


def gather_coach_outputs(table, coaches):
    """Coach outputs — pk COACH#<id>, sk OUTPUT#<date>#<type>."""
    docs = []
    for coach_id in coaches:
        for it in _query_all(table, KeyConditionExpression=Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#")):
            date = _date_from_sk(it.get("sk", ""), "OUTPUT#")
            # #2569: `output_text`/`text` were a guess — the writer
            # (`coach_state_updater._write_output_record`) puts the narrative under
            # `content`, so every one of the 851 live OUTPUT# rows was skipped as empty.
            text = coach_output_text(it)
            if not date or not text:
                continue
            docs.append(
                {
                    "kind": sr.KIND_COACH,
                    # namespace the sk by coach so two coaches' same-day outputs don't collide
                    "date": f"{date}#{coach_id}",
                    "doc_date": date,
                    "text": text,
                    "artifact_pk": it["pk"],
                    "artifact_sk": it["sk"],
                    "link": "/coaching/",
                    "cycle": it.get("cycle"),
                }
            )
    return docs


def gather_journal(table):
    """Journal entries — pk SOURCE#notion, sk DATE#<date>#journal#<template>.

    #2569: this read `content`/`body`/`text` — three attribute names that have never
    existed on a live journal row. The notion writer puts the body in `body_text` /
    `raw_text` (`common.record_text.JOURNAL_TEXT_FIELDS`, which the writer itself names
    its attributes from), so every entry failed the empty-text guard below and semantic
    recall indexed zero journal entries between #1384 shipping and this fix.
    """
    docs = []
    for it in _query_all(table, KeyConditionExpression=Key("pk").eq(f"{USER_PK_PREFIX}notion")):
        sk = it.get("sk", "")
        if "#journal#" not in sk:
            continue
        date = _date_from_sk(sk)
        text = journal_text(it)
        if not date or not text:
            continue
        docs.append(
            {
                "kind": sr.KIND_JOURNAL,
                "date": sk.split("DATE#", 1)[1],  # full sub-key so multiple entries/day are distinct
                "doc_date": date,
                "text": text,
                "artifact_pk": it["pk"],
                "artifact_sk": sk,
                "link": "/story/journal/",
                "cycle": it.get("cycle"),
            }
        )
    return docs


def existing_rows(table):
    """{sk: {text_sha, link, cycle}} for the current recall partition.

    `text_sha` is the embed-idempotency key; `link`/`cycle` ride along so a re-run can
    REFRESH stale METADATA without paying to re-embed unchanged text (#1827/#1828 — the
    17 live rows carry a dead link, and a row's frozen `cycle` drifts from the chronicle
    record every time a reset re-stamps it).
    """
    out = {}
    kwargs = {"KeyConditionExpression": Key("pk").eq(sr.RECALL_PK)}
    while True:
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            out[it.get("sk", "")] = {
                "text_sha": it.get("text_sha", ""),
                "link": it.get("link", "") or "",
                "cycle": it.get("cycle"),
            }
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="WRITE + embed (default is dry-run, zero spend)")
    ap.add_argument("--kinds", default="chronicle,coach_output,journal", help="comma list of kinds to embed")
    ap.add_argument("--coaches", default=",".join(DEFAULT_COACHES), help="coach ids for coach_output")
    ap.add_argument("--force", action="store_true", help="re-embed even if text_sha is unchanged")
    ap.add_argument("--limit", type=int, default=0, help="cap docs embedded (0 = no cap; eyeball a sample)")
    args = ap.parse_args()

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    coaches = [c.strip() for c in args.coaches.split(",") if c.strip()]
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

    docs = []
    if sr.KIND_CHRONICLE in kinds:
        docs += gather_chronicle(table)
    if sr.KIND_COACH in kinds:
        docs += gather_coach_outputs(table, coaches)
    if sr.KIND_JOURNAL in kinds:
        docs += gather_journal(table)

    rows = existing_rows(table)
    embedded = skipped = relinked = 0
    est_tokens = 0
    est_usd = 0.0
    for doc in docs:
        if args.limit and embedded >= args.limit:
            break
        sk = sr.sk_for(doc["kind"], doc["date"])
        new_sha = sr.sha_text(doc["text"])
        existing = rows.get(sk)
        if not args.force and existing is not None and existing.get("text_sha") == new_sha:
            # Text unchanged ⇒ no re-embed. But the METADATA can still be stale
            # (#1827 dead links, #1828 drifted cycle stamps) — refresh it for free.
            drift = metadata_drift(existing, doc)
            if drift:
                if args.apply:
                    refresh_metadata(table, sk, drift)
                    print(f"  metadata-refresh {sk}: {drift} (no re-embed, no spend)")
                else:
                    print(f"  [dry-run] would refresh metadata {sk}: {drift} (no re-embed, no spend)")
                relinked += 1
            else:
                skipped += 1
            continue
        # est tokens ~ chars/4 (only for the rollup; real spend meters at the chokepoint)
        est_tokens += max(1, len(doc["text"]) // 4)
        if not args.apply:
            print(f"  [dry-run] would embed {sk} ({doc['kind']} {doc.get('doc_date', doc['date'])})")
            embedded += 1
            continue
        vector = bc.embed_text(doc["text"])
        item = sr.make_embedding_item(
            kind=doc["kind"],
            date=doc["date"],
            doc_date=doc.get("doc_date", doc["date"]),
            text=doc["text"],
            vector=vector,
            cycle=doc.get("cycle"),
            artifact_pk=doc["artifact_pk"],
            artifact_sk=doc["artifact_sk"],
            link=doc.get("link", ""),
            snippet=_snippet(doc["text"]),
            model=bc.TITAN_EMBED_MODEL_ID,
            dims=len(vector),
            embedded_at=datetime.now(timezone.utc).isoformat(),
        )
        table.put_item(Item=item)
        embedded += 1
        print(f"  embedded {sk} ({len(vector)}-dim)")

    est_usd = est_tokens * bc._PRICES["titan"]["in"] / 1_000_000.0
    mode = "APPLIED (single bulk run)" if args.apply else "DRY-RUN (no spend)"
    print(
        f"\n{mode}: {embedded} embedded, {relinked} metadata-refreshed (link/cycle, no spend), "
        f"{skipped} skipped (unchanged), {len(docs)} scanned. "
        f"~{est_tokens} input tokens ≈ ${est_usd:.4f} (Titan v2 @ $0.02/1M). "
        f"Incremental re-runs are cheap; re-run after new chronicle/coach/journal writes."
    )


if __name__ == "__main__":
    main()
