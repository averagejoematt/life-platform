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
    from phase_filter import singleton_visible

    keys = sorted((i.get("date", ""), str(i.get("sk", ""))) for i in installments if singleton_visible(i) and i.get("date"))
    return {key: f"/journal/posts/week-{n + 1:02d}/" for n, key in enumerate(keys)}


def gather_chronicle(table):
    """Chronicle installments — pk SOURCE#chronicle, sk DATE#<date>. One doc/week.

    Queried UNFILTERED (cross-reset recall is the point), but the reader link is derived
    from the PUBLISHED ordering (#1827) so every link that renders is a real page.
    """
    docs = []
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PK_PREFIX}chronicle") & Key("sk").begins_with("DATE#"))
    items = list(resp.get("Items", []))
    links = published_post_links(items)
    for it in items:
        date = _date_from_sk(it.get("sk", ""))
        if not date:
            continue
        text = " ".join(s for s in (it.get("title", ""), it.get("subtitle", ""), it.get("content_markdown", "")) if s).strip()
        if not text:
            continue
        docs.append(
            {
                "kind": sr.KIND_CHRONICLE,
                "date": date,
                "text": text,
                "artifact_pk": it["pk"],
                "artifact_sk": it["sk"],
                # Published → its real post URL. Not published (wiped prior cycle) → no
                # link at all; `semantic_recall.render_precedent_line` then cites the
                # date alone rather than a URL that 404s or points at another week.
                "link": links.get((it.get("date", ""), str(it.get("sk", ""))), ""),
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


def metadata_drift(existing: dict, doc: dict) -> dict:
    """{attr: new_value} for the metadata that no longer matches the source record —
    `{}` when the stored row is already correct. Compares only what a re-run can fix
    without re-embedding: the reader `link` and the source `cycle` stamp."""
    drift = {}
    new_link = doc.get("link", "") or ""
    if (existing.get("link") or "") != new_link:
        drift["link"] = new_link
    old_cycle = existing.get("cycle")
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
    sets, removes, names, values = [], [], {}, {}
    for i, (attr, val) in enumerate(sorted(drift.items())):
        names[f"#a{i}"] = attr
        if val is None:
            removes.append(f"#a{i}")
        else:
            sets.append(f"#a{i} = :v{i}")
            values[f":v{i}"] = val
    expr = " ".join(filter(None, ["SET " + ", ".join(sets) if sets else "", "REMOVE " + ", ".join(removes) if removes else ""]))
    kwargs = {
        "Key": {"pk": sr.RECALL_PK, "sk": sk},
        "UpdateExpression": expr,
        "ExpressionAttributeNames": names,
    }
    if values:
        kwargs["ExpressionAttributeValues"] = values
    table.update_item(**kwargs)


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
