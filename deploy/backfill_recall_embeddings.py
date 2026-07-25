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

import bedrock_client as bc  # noqa: E402
import boto3  # noqa: E402
import semantic_recall as sr  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_PK_PREFIX = "USER#matthew#SOURCE#"

# Coach roster for OUTPUT# enumeration (COACH#<id>), mirrored from the orchestrator's
# deterministic routing config so a coach add is a one-line change there, not here.
try:
    from coach.coach_narrative_orchestrator import COACH_DOMAINS as _COACH_DOMAINS

    DEFAULT_COACHES = sorted(_COACH_DOMAINS.keys())
except Exception:  # noqa: BLE001 — fall back to the known roster if the import path shifts
    DEFAULT_COACHES = [
        "sleep_coach",
        "training_coach",
        "nutrition_coach",
        "mind_coach",
        "physical_coach",
        "glucose_coach",
        "labs_coach",
        "explorer_coach",
    ]


def _date_from_sk(sk: str, prefix: str = "DATE#") -> str:
    """Extract YYYY-MM-DD from a DATE#/OUTPUT# sort key (the token after the marker)."""
    if prefix not in sk:
        return ""
    tail = sk.split(prefix, 1)[1]
    return tail.split("#", 1)[0]


def _snippet(text: str, n: int = 240) -> str:
    text = " ".join((text or "").split())
    return text[:n]


def gather_chronicle(table):
    """Chronicle installments — pk SOURCE#chronicle, sk DATE#<date>. One doc/week."""
    docs = []
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PK_PREFIX}chronicle") & Key("sk").begins_with("DATE#"))
    for it in resp.get("Items", []):
        date = _date_from_sk(it.get("sk", ""))
        if not date:
            continue
        text = " ".join(s for s in (it.get("title", ""), it.get("subtitle", ""), it.get("content_markdown", "")) if s).strip()
        if not text:
            continue
        wk = it.get("week_number")
        docs.append(
            {
                "kind": sr.KIND_CHRONICLE,
                "date": date,
                "text": text,
                "artifact_pk": it["pk"],
                "artifact_sk": it["sk"],
                "link": f"/chronicle/week-{int(wk)}/" if wk is not None else "/story/chronicle/",
                "cycle": it.get("cycle"),
            }
        )
    return docs


def gather_coach_outputs(table, coaches):
    """Coach outputs — pk COACH#<id>, sk OUTPUT#<date>#<type>."""
    docs = []
    for coach_id in coaches:
        resp = table.query(KeyConditionExpression=Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("OUTPUT#"))
        for it in resp.get("Items", []):
            date = _date_from_sk(it.get("sk", ""), "OUTPUT#")
            text = (it.get("output_text") or it.get("text") or "").strip()
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
    """Journal entries — pk SOURCE#notion, sk DATE#<date>#journal#<template>."""
    docs = []
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PK_PREFIX}notion"))
    for it in resp.get("Items", []):
        sk = it.get("sk", "")
        if "#journal#" not in sk:
            continue
        date = _date_from_sk(sk)
        text = (it.get("content") or it.get("body") or it.get("text") or "").strip()
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


def existing_shas(table):
    """{sk: text_sha} for the current recall partition — the idempotency ledger."""
    out = {}
    kwargs = {"KeyConditionExpression": Key("pk").eq(sr.RECALL_PK)}
    while True:
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            out[it.get("sk", "")] = it.get("text_sha", "")
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

    shas = existing_shas(table)
    embedded = skipped = 0
    est_tokens = 0
    est_usd = 0.0
    for doc in docs:
        if args.limit and embedded >= args.limit:
            break
        sk = sr.sk_for(doc["kind"], doc["date"])
        new_sha = sr.sha_text(doc["text"])
        if not args.force and shas.get(sk) == new_sha:
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
        f"\n{mode}: {embedded} embedded, {skipped} skipped (unchanged), {len(docs)} scanned. "
        f"~{est_tokens} input tokens ≈ ${est_usd:.4f} (Titan v2 @ $0.02/1M). "
        f"Incremental re-runs are cheap; re-run after new chronicle/coach/journal writes."
    )


if __name__ == "__main__":
    main()
