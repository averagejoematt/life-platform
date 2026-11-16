"""publication_snapshot.py — the COMPLETE withheld graded record, read once and shared by the publication steps (#6111).

ONE READ, TWO USES. Every graded-record row (``narrative_publication.COUNTED_SK_PREFIXES``) of every coach partition and
the dispute docket is read whole from the table the request reads. From that one read:

  * the COMPLETE TAINT — the hashes of every free-text value of every withheld graded row (the gate's own decision,
    ``narrative_publication._decide``, taken outside every scope). ``narrative_publication.is_tainted`` checks it beside
    the request's own reads, so a withheld call's words echoed in a partition the request never read (a daily read, an
    analysis, a brief) are emptied on a cold container exactly as on the warmest one;
  * the CALL ROWS each coach's public id map is built from (``web.public_call_id``) — the ``PREDICTION#`` rows the call
    publication policy passes (``common.prediction_publication.row_is_public``), exactly the rows a route reads.

FRESHNESS. A partition is re-read when older than ``TTL_S`` (the call policy's own lookup TTL, ``call_publication.
LOOKUP_TTL_S``) or, for one coach, once in a request when an id is missing (``ensure(..., force=True)``). The text →
hashes memo (``narrative_publication._text_hashes``) is container-wide and pure, so a refresh re-shingles only text it
has never seen: its cost is the read.

DETERMINISM. For the same stored rows and policy version every container makes the same decision, cold or warm, in any
request order. The one window in which two containers can differ is the ``TTL_S`` after a withheld graded row is
WRITTEN, and only for an echo of that new row in a partition the request does not read: the request that reads the row
taints it at once (the gate's per-request half).

FAIL CLOSED. A partition whose read fails keeps its last good read (logged ``stale``, with its age); a partition with no
good read at all makes the complete taint UNAVAILABLE — ``complete()`` raises ``SnapshotUnavailable`` and the Site API
refuses the response (503) rather than serve prose unchecked against other partitions. A process that never opened a
request with a table (the strict Lambdas, unit tests of the gate) has no snapshot: only its own reads taint.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Optional

logger = logging.getLogger("site_api")

TTL_S = 900  # = web.call_publication.LOOKUP_TTL_S: the gate's two caches age together
DOCKET_PK = "ENSEMBLE#docket"
_WORKERS = 8
_MAX_PAGES = 24


class SnapshotUnavailable(RuntimeError):
    """The complete taint has never been read in this container and cannot be read now."""


# pk -> {"at": monotonic, "version": int, "exact": frozenset, "shingles": frozenset, "calls": list}
_PARTS: dict = {}
_STATE: dict = {"raw": None, "version": 0, "exact": frozenset(), "shingles": frozenset(), "combined_of": None}
_REQ: dict = {"table": None, "checked": False, "refreshed": set(), "sets": None}
STATS: dict = {"reads": 0, "failures": 0, "stale_served": 0, "refused": 0}


def partitions() -> tuple:
    """Every partition the complete read covers: each coach seat (operational, retired, the lead) and the docket."""
    from coach.persona_registry import LEAD_PERSONA_ID, OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS

    coaches = sorted({*OPERATIONAL_COACH_IDS, *RETIRED_COACH_IDS, LEAD_PERSONA_ID})
    return tuple(f"COACH#{c}" for c in coaches) + (DOCKET_PK,)


def coach_pk(short: str) -> str:
    return f"COACH#{short}_coach"


def reset() -> None:
    _PARTS.clear()
    _STATE.update(raw=None, version=0, exact=frozenset(), shingles=frozenset(), combined_of=None)
    _REQ.update(table=None, checked=False, refreshed=set(), sets=None)
    for k in STATS:
        STATS[k] = 0


def begin_request(table: Any = None) -> None:
    """Open one request against ``table`` (None: no snapshot — only the request's own reads taint)."""
    _REQ.update(table=table, checked=False, refreshed=set(), sets=None)


def active() -> bool:
    return _REQ["table"] is not None


def _raw_table() -> Any:
    from web import narrative_publication as NPub

    t = NPub.request_table() or _REQ["table"]
    return t.wrapped if isinstance(t, NPub.PublicationTable) else t


def _query_pages(raw: Any, pk: str, prefix: str) -> list:
    """Every row of ``pk`` under ``prefix`` — all pages, or an error (a partial read is never a complete one)."""
    from boto3.dynamodb.conditions import Key

    kw: dict = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
    rows: list = []
    for _ in range(_MAX_PAGES):
        resp = raw.query(**kw) or {}
        for it in resp.get("Items") or []:
            if isinstance(it, dict) and str(it.get("pk", pk)) == pk and str(it.get("sk") or "").startswith(prefix):
                rows.append(it if "pk" in it else {**it, "pk": pk})
        last = resp.get("LastEvaluatedKey")
        if not last:
            return rows
        kw = {**kw, "ExclusiveStartKey": last}
    raise RuntimeError(f"{pk}/{prefix}: over {_MAX_PAGES} pages")


def _digest(raw: Any, pk: str, rows: list) -> dict:
    """One partition's read -> its taint hashes and its publishable call rows."""
    from common import narrative_allowlist as NA, narrative_provenance as NP, prediction_publication as PP

    from web import call_publication, narrative_publication as NPub

    exact: set = set()
    shingles: set = set()
    with NA.closed():
        for row in rows:
            if not NPub.is_narrative_row(pk, row.get("sk")) or not NPub._is_counted(row.get("sk")):
                continue
            if NPub._decide(row, pk)[0]:
                continue
            for key, value in row.items():
                if key in NPub.TAINT_SKIP_KEYS or key == NP.PROVENANCE_KEY:
                    continue
                for text in NPub._prose_strings(value, key):
                    e, sh = NPub._text_hashes(text)
                    if e is not None:
                        exact.add(e)
                        shingles.update(sh)
    calls: list = []
    if pk != DOCKET_PK:
        lookup = call_publication.make_lookup(raw)
        calls = [r for r in rows if str(r.get("sk") or "").startswith("PREDICTION#") and PP.row_is_public(pk, r, lookup)]
    return {"exact": frozenset(exact), "shingles": frozenset(shingles), "calls": calls}


def _read_partition(raw: Any, pk: str) -> list:
    from web import narrative_publication as NPub

    rows: list = []
    for prefix in NPub.COUNTED_SK_PREFIXES:
        rows += _query_pages(raw, pk, prefix)
    return rows


def ensure(pks: Optional[Iterable[str]] = None, force: bool = False) -> None:
    """Every partition in ``pks`` (default: all) fresh — re-read when missing, older than ``TTL_S`` or (``force``) not
    yet re-read in this request. Reads run concurrently; a failed read keeps the last good one (logged stale)."""
    if not active():
        return
    raw = _raw_table()
    if _STATE["raw"] is not raw:  # a snapshot read from one table never answers for another
        _PARTS.clear()
        _STATE.update(raw=raw, combined_of=None)
    now = time.monotonic()
    wanted = partitions() if pks is None else tuple(dict.fromkeys(pks))
    due = [pk for pk in wanted if pk not in _REQ["refreshed"] and (force or pk not in _PARTS or now - _PARTS[pk]["at"] >= TTL_S)]
    if not due:
        return

    def _one(pk: str) -> tuple:
        try:
            return pk, _read_partition(raw, pk), None
        except Exception as exc:  # noqa: BLE001 — handled below: last good read, or unavailable
            return pk, None, exc

    if len(due) == 1:
        results = [_one(due[0])]
    else:
        with ThreadPoolExecutor(min(_WORKERS, len(due))) as ex:
            results = list(ex.map(_one, due))
    for pk, rows, exc in results:
        _REQ["refreshed"].add(pk)
        if exc is not None:
            STATS["failures"] += 1
            held = _PARTS.get(pk)
            if held is not None:
                STATS["stale_served"] += 1
                logger.warning(
                    "[publication_snapshot] partition=%s read failed (%s); serving the last good read, stale_s=%.0f",
                    pk,
                    type(exc).__name__,
                    now - held["at"],
                )
            else:
                logger.error("[publication_snapshot] partition=%s read failed (%s); no good read held", pk, type(exc).__name__)
            continue
        STATS["reads"] += 1
        _REQ["sets"] = None
        _STATE["version"] += 1
        _PARTS[pk] = {"at": time.monotonic(), "version": _STATE["version"], **_digest(raw, pk, rows)}


def complete() -> tuple:
    """``(exact, shingles)`` of every withheld graded row in every partition — checked fresh once per request. Raises
    ``SnapshotUnavailable`` when a partition has no good read; ``(∅, ∅)`` outside a request opened with a table."""
    if not active():
        return frozenset(), frozenset()
    held = _REQ["sets"]
    if held is not None:
        return held
    if not _REQ["checked"]:
        _REQ["checked"] = True
        ensure()
    missing = [pk for pk in partitions() if pk not in _PARTS]
    if missing:
        STATS["refused"] += 1
        raise SnapshotUnavailable(f"no good read of {len(missing)} partition(s), e.g. {missing[0]}")
    key = tuple(sorted((pk, p["version"]) for pk, p in _PARTS.items()))
    if _STATE["combined_of"] != key:
        exact: set = set()
        shingles: set = set()
        for p in _PARTS.values():
            exact |= p["exact"]
            shingles |= p["shingles"]
        _STATE.update(exact=frozenset(exact), shingles=frozenset(shingles), combined_of=key)
    sets = (_STATE["exact"], _STATE["shingles"])
    _REQ["sets"] = sets
    return sets


def calls(pk: str) -> Optional[tuple]:
    """``(version, rows)``: the publishable call rows of one coach partition's last good read, or None."""
    p = _PARTS.get(pk)
    return (p["version"], p["calls"]) if p is not None else None
