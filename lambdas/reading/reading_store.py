"""reading_store.py — DynamoDB data access for the reading domain (spec §1–§3).

Single-table `life-platform`. All reads return JSON-safe (Decimals → float); all
writes cast floats → Decimal (boto3 requirement). Reading records are CROSS_PHASE
(durable identity data) so reads do NOT apply the experiment phase filter and
writes do NOT stamp a phase — a reset never touches the library.

The query helpers ARE the access patterns in spec §2:
  1. current reading + queue        → current_and_queue()        (GSI2)
  2. history over a date range       → history(start, end)        (GSI2)
  3. all notes for a book            → notes(book_id)             (main, begins_with)
  4. due recall prompts (sweep)      → due_recalls(now)           (GSI1, sparse)
  5. roundedness wheel               → wheel_distribution()       (GSI2 finished + BOOK# join)
  6. Lena's track record             → track_record()            (main, begins_with)
  7. Constellation graph             → idea(id) / idea_edges(id)  (main; enum = Phase E)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from numeric import decimals_to_float, floats_to_decimal

from reading import reading_keys as rk

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _put(item: dict) -> dict:
    table.put_item(Item=floats_to_decimal(item))
    return item


def _get(key: dict) -> dict | None:
    resp = table.get_item(Key=key)
    item = resp.get("Item")
    return decimals_to_float(item) if item else None


def _query(**kwargs) -> list:
    items: list = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return decimals_to_float(items)


# ══════════════════════════════════════════════════════════════════════════════
# WRITES
# ══════════════════════════════════════════════════════════════════════════════
def put_book(meta: dict) -> dict:
    """Write/overwrite a BOOK#<id>/META catalog item. `meta` must carry bookId."""
    item = dict(meta)
    item.update(rk.book_key(item["bookId"]))
    _put(item)
    return item


def add_book(meta: dict, *, initial_status: str = "want", enrich: bool = True, enricher=None, now: str | None = None) -> str:
    """Add a book to the library: enrich (LLM-tag) → write BOOK# → open a
    READING#/STATE relationship. Returns the bookId. Enrichment is fail-soft —
    a tagging failure still adds an un-tagged book (the engine can re-enrich).
    """
    now = now or _now_iso()
    bid = meta.get("bookId") or rk.book_id(
        isbn13=meta.get("isbn13"), olid=meta.get("olid"), title=meta.get("title"), author=meta.get("author")
    )
    book = dict(meta)
    book["bookId"] = bid

    if enrich:
        if enricher is None:
            from reading import reading_enrich  # lazy — keeps Bedrock out of import path

            enricher = reading_enrich.enrich_book
        tags = enricher(book) or {}
        for k, v in tags.items():
            if v is not None:
                book[k] = v
        book.setdefault("enrichedAt", now)

    book.setdefault("source", "manual")
    put_book(book)
    put_reading_state(bid, initial_status, now=now)
    return bid


def put_reading_state(book_id: str, status: str, *, fields: dict | None = None, now: str | None = None) -> dict:
    """Write the READING#<id>/STATE row and stamp GSI2 (status/time)."""
    if status not in rk.VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {rk.VALID_STATUSES}")
    now = now or _now_iso()
    item = {"bookId": book_id, "status": status, "statusChangedAt": now}
    item.update(fields or {})
    item.update(rk.reading_state_key(book_id))
    rk.stamp_state_gsi(item, status, now)
    _put(item)
    return item


def update_reading_status(book_id: str, status: str, *, abandon_reason: str | None = None, now: str | None = None, **extra) -> dict:
    """Transition a book's status (read-modify-write), restamp GSI2, and set the
    finished/abandoned timestamps. `abandon_reason` is REQUIRED on abandon
    (spec §1: the strongest negative signal)."""
    if status not in rk.VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    now = now or _now_iso()
    current = _get(rk.reading_state_key(book_id)) or {"bookId": book_id}
    current = {k: v for k, v in current.items() if k not in ("pk", "sk")}
    current["status"] = status
    current["statusChangedAt"] = now
    current.update(extra)
    if status == "reading" and not current.get("startedAt"):
        current["startedAt"] = now
    if status == "finished":
        current["finishedAt"] = now
    if status == "abandoned":
        if abandon_reason not in rk.VALID_ABANDON_REASONS:
            raise ValueError(f"abandon requires a reason in {rk.VALID_ABANDON_REASONS}; got {abandon_reason!r}")
        current["abandonedAt"] = now
        current["abandonReason"] = abandon_reason
    return put_reading_state(book_id, status, fields={k: v for k, v in current.items() if k not in ("status", "statusChangedAt")}, now=now)


def log_session(
    book_id: str,
    *,
    minutes: float,
    pages: float | None = None,
    date: str | None = None,
    location: str | None = None,
    mood_snapshot: dict | None = None,
    now: str | None = None,
) -> dict:
    """Log a READING_SESSION input event, stamped onto GSI2 for history-by-date.
    `location`/`mood_snapshot` are PRIVATE (mind-body bridge inputs)."""
    now = now or _now_iso()
    date = date or now[:10]
    item = {"bookId": book_id, "date": date, "minutes": minutes, "ts": now}
    if pages is not None:
        item["pages"] = pages
    if location is not None:
        item["location"] = location
    if mood_snapshot is not None:
        item["moodSnapshot"] = mood_snapshot
    item.update(rk.session_key(book_id, now))
    rk.stamp_session_gsi(item, date)
    _put(item)
    return item


def add_note(book_id: str, *, note_id: str, type: str, text: str, public: bool = False, now: str | None = None) -> dict:
    """Add a READING_NOTE (highlight|reflection|synthesis). `public` gates whether
    the visibility projection will ever surface it."""
    now = now or _now_iso()
    item = {"bookId": book_id, "noteId": note_id, "type": type, "text": text, "public": bool(public), "createdAt": now}
    item.update(rk.note_key(book_id, note_id))
    _put(item)
    return item


def put_recall(
    book_id: str,
    *,
    prompt_id: str,
    prompt: str,
    interval_index: int = 0,
    next_due: str | None = None,
    performance_history: list | None = None,
    now: str | None = None,
) -> dict:
    """Write a RECALL# probe (PRIVATE). When next_due is set, GSI1 (sparse) makes
    it sweepable; when None (answered/retired) it drops out of the due index."""
    now = now or _now_iso()
    item = {
        "bookId": book_id,
        "promptId": prompt_id,
        "prompt": prompt,
        "intervalIndex": interval_index,
        "nextDue": next_due,
        "performanceHistory": performance_history or [],
        "createdAt": now,
    }
    item.update(rk.recall_key(book_id, prompt_id))
    rk.stamp_recall_due_gsi(item, next_due)
    _put(item)
    return item


def put_recommendation(rec: dict, *, now: str | None = None) -> dict:
    """Append a RECOMMENDATION# audit record (Lena's track record). `inputsSnapshot`
    is PRIVATE (snapshots his state)."""
    now = now or _now_iso()
    item = dict(rec)
    item.setdefault("ts", now)
    item.update(rk.rec_key(item["ts"]))
    _put(item)
    return item


def put_profile(profile: dict) -> dict:
    """Write the single READING#PROFILE/CURRENT calibration item."""
    item = dict(profile)
    item.update(rk.profile_key())
    _put(item)
    return item


def update_cover_key(book_id: str, cover_s3_key: str | None, cover_source: str, now: str | None = None) -> dict | None:
    """Set BOOK#<id>.coverS3Key + coverSource (called by the cover pipeline)."""
    book = _get(rk.book_key(book_id))
    if not book:
        return None
    book = {k: v for k, v in book.items() if k not in ("pk", "sk")}
    book["coverS3Key"] = cover_s3_key
    book["coverSource"] = cover_source
    book["coverUpdatedAt"] = now or _now_iso()
    return put_book(book)


# A small index of idea ids — DynamoDB can't `begins_with` a partition key, so the
# Constellation enumerates via this single index record (spec §2.7 deferred-enum).
_IDEA_INDEX_PK = "READING#IDEA_INDEX"
_IDEA_INDEX_SK = "CURRENT"


def put_idea(idea: dict, *, source_book_id: str | None = None) -> dict:
    item = dict(idea)
    item.update(rk.idea_key(item["ideaId"]))
    if source_book_id:
        srcs = set(item.get("sourceBookIds") or [])
        srcs.add(source_book_id)
        item["sourceBookIds"] = sorted(srcs)
    _put(item)
    _index_idea(item["ideaId"])
    return item


def _index_idea(idea_id: str) -> None:
    rec = _get({"pk": _IDEA_INDEX_PK, "sk": _IDEA_INDEX_SK}) or {}
    ids = set(rec.get("ideaIds") or [])
    if idea_id in ids:
        return
    ids.add(idea_id)
    table.put_item(Item={"pk": _IDEA_INDEX_PK, "sk": _IDEA_INDEX_SK, "ideaIds": sorted(ids)})


def idea_ids() -> list:
    rec = _get({"pk": _IDEA_INDEX_PK, "sk": _IDEA_INDEX_SK}) or {}
    return list(rec.get("ideaIds") or [])


def all_ideas() -> dict:
    """The whole Constellation: nodes + edges (enumerated via the idea index)."""
    nodes, edges = [], []
    for iid in idea_ids():
        node = idea(iid)
        if node:
            nodes.append(node)
            for e in idea_edges(iid):
                edges.append({"from": iid, "to": e.get("otherIdeaId"), "weight": e.get("weight"), "rationale": e.get("rationale")})
    return {"nodes": nodes, "edges": edges, "node_count": len(nodes)}


def put_edge(idea_id: str, other_idea_id: str, *, weight: float, rationale: str = "") -> dict:
    item = {"weight": weight, "rationale": rationale, "otherIdeaId": other_idea_id}
    item.update(rk.edge_key(idea_id, other_idea_id))
    _put(item)
    return item


# ══════════════════════════════════════════════════════════════════════════════
# READS — the spec §2 access patterns
# ══════════════════════════════════════════════════════════════════════════════
def get_book(book_id: str) -> dict | None:
    return _strip(_get(rk.book_key(book_id)))


def get_reading_state(book_id: str) -> dict | None:
    return _strip(_get(rk.reading_state_key(book_id)))


def _strip(item: dict | None) -> dict | None:
    if not item:
        return item
    return {k: v for k, v in item.items() if k not in ("pk", "sk")}


def current_and_queue(statuses=("reading", "want")) -> dict:
    """§2.1 — current reading + queue, by status via GSI2."""
    out: dict[str, list] = {}
    for status in statuses:
        items = _query(
            IndexName=rk.GSI2_NAME,
            KeyConditionExpression=Key(rk.GSI2_PK_ATTR).eq(f"{rk.READING_STATUS_PREFIX}{status}"),
            ScanIndexForward=False,
        )
        out[status] = [_strip(i) for i in items]
    return out


def finished(start: str = "0000-00-00", end: str = "9999-12-31") -> list:
    """Finished books (used by the wheel) via GSI2."""
    items = _query(
        IndexName=rk.GSI2_NAME,
        KeyConditionExpression=Key(rk.GSI2_PK_ATTR).eq(f"{rk.READING_STATUS_PREFIX}finished") & Key(rk.GSI2_SK_ATTR).between(start, end),
    )
    return [_strip(i) for i in items]


def history(start_date: str, end_date: str) -> list:
    """§2.2 — reading-session history over a date range via GSI2 (input streak/trend)."""
    if start_date > end_date:
        return []
    items = _query(
        IndexName=rk.GSI2_NAME,
        KeyConditionExpression=Key(rk.GSI2_PK_ATTR).eq(rk.READING_SESSION_VALUE) & Key(rk.GSI2_SK_ATTR).between(start_date, end_date),
    )
    return [_strip(i) for i in items]


def notes(book_id: str) -> list:
    """§2.3 — all notes for a book via the main table (begins_with NOTE#)."""
    items = _query(
        KeyConditionExpression=Key("pk").eq(rk.READING_PK.format(book_id=book_id)) & Key("sk").begins_with(rk.SK_NOTE_PREFIX),
    )
    return [_strip(i) for i in items]


def due_recalls(now: str | None = None) -> list:
    """§2.4 — due recall prompts via the SPARSE GSI1 (GSI1SK <= now). Only active
    prompts project into this index, so the sweep never scans the table."""
    now = now or _now_iso()
    items = _query(
        IndexName=rk.GSI1_NAME,
        KeyConditionExpression=Key(rk.GSI1_PK_ATTR).eq(rk.RECALL_DUE_VALUE) & Key(rk.GSI1_SK_ATTR).lte(now),
    )
    return [_strip(i) for i in items]


def wheel_distribution() -> dict:
    """§2.5 — roundedness wheel: finished READING# joined to BOOK#.domainTags.
    Returns {domainTag: count}. (Caller may cache onto READING_PROFILE.)"""
    dist: dict[str, int] = {}
    for state in finished():
        book = get_book(state.get("bookId", ""))
        for tag in (book or {}).get("domainTags") or []:
            dist[tag] = dist.get(tag, 0) + 1
    return dist


def track_record(limit: int | None = None) -> list:
    """§2.6 — Lena's recommendation track record via the main table (begins_with REC#)."""
    items = _query(
        KeyConditionExpression=Key("pk").eq(rk.REC_PK) & Key("sk").begins_with(rk.SK_REC_PREFIX),
        ScanIndexForward=False,
    )
    items = [_strip(i) for i in items]
    return items[:limit] if limit else items


def get_profile() -> dict | None:
    return _strip(_get(rk.profile_key()))


def idea(idea_id: str) -> dict | None:
    """§2.7 — a Constellation node by exact id. (Whole-graph enumeration is Phase E;
    `PK begins_with READING#IDEA#` is not a valid DynamoDB query and is deferred.)"""
    return _strip(_get(rk.idea_key(idea_id)))


def idea_edges(idea_id: str) -> list:
    """Edges out of one idea via the main table (begins_with EDGE#)."""
    items = _query(
        KeyConditionExpression=Key("pk").eq(rk.IDEA_PK.format(idea_id=idea_id)) & Key("sk").begins_with(rk.SK_EDGE_PREFIX),
    )
    return [_strip(i) for i in items]
