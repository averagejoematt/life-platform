"""The table half of the call publication policy (owner ruling 2026-11-05; ``common.prediction_publication``).

``web.narrative_publication.PublicationTable`` — the handle every public site-API read goes through — hands every read
of a governed partition (a coach's, the docket's, the calibration ledger's) to this module, which OMITS every row of a
call that is not publication-eligible before any handler sees it. So no route can count, page, list, rank or join a
private call: every public total, denominator, accuracy and "N of M" is over eligible calls by construction, and a
route added tomorrow is governed the same way.

What a read keeps its meaning under:

  * ``Limit`` is a count of the rows the caller can see. A page that held private rows is filled from the pages after
    it (to ``MAX_FILL_PAGES``), and ``LastEvaluatedKey`` resumes right after the last row served — so which public rows
    a "newest 60" read returns never depends on how many private rows sat among them.
  * ``Select="COUNT"`` counts eligible rows only.
  * A projected read is widened to the attributes the policy reads (``prediction_publication.CLASSIFICATION_ATTRS``)
    and narrowed back, so a handler sees exactly the attributes it asked for.
  * ``get_item`` of a private call's row returns no ``Item`` — the row reads as absent.

A row that NAMES a call filed after the reviewed registry (a learning, a grade correction) is decided by that call,
read once through ``lookup`` and cached for ``LOOKUP_TTL_S``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from common import prediction_publication as PP

logger = logging.getLogger("site_api")

MAX_FILL_PAGES = 24
LOOKUP_TTL_S = 900
_LOOKUP_MAX = 4096
_LOOKUP_CACHE: dict = {}
_ALIAS = "#cpg_"


def _present(proj: str, names: dict) -> set:
    return {names.get(tok.strip(), tok.strip()).split(".")[0].split("[")[0] for tok in str(proj).split(",")}


def widen(kwargs: dict) -> tuple:
    """``(kwargs, added)``: a projected read with the policy's attributes added; ``added`` names what the caller did
    not ask for (removed again from every served item)."""
    proj = kwargs.get("ProjectionExpression")
    if not proj:
        return kwargs, frozenset()
    names = dict(kwargs.get("ExpressionAttributeNames") or {})
    present = _present(proj, names)
    extra, added = [], []
    for attr in PP.attrs_for_prefix(None):
        if attr in present:
            continue
        alias = f"{_ALIAS}{attr}"
        names[alias] = attr
        extra.append(alias)
        added.append(attr)
    if not extra:
        return kwargs, frozenset()
    return {**kwargs, "ProjectionExpression": ", ".join([proj] + extra), "ExpressionAttributeNames": names}, frozenset(added)


def _strip(item: Any, added: frozenset) -> Any:
    if not added or not isinstance(item, dict):
        return item
    return {k: v for k, v in item.items() if k not in added}


def make_lookup(raw: Any):
    """A cached reader of one call's row (``pk``, ``PREDICTION#<key>``) for the reference rule."""
    attrs = PP.CLASSIFICATION_ATTRS[PP.CALL]
    names = {f"{_ALIAS}{a}": a for a in attrs}

    def lookup(pk: str, key: str) -> Optional[dict]:
        ck = (str(pk), str(key))
        now = time.monotonic()
        hit = _LOOKUP_CACHE.get(ck)
        if hit is not None and now - hit[0] < LOOKUP_TTL_S:
            return hit[1]
        call_sk = PP.CALL_ROW_PREFIX + ck[1]  # a READ of the call's row (this module writes nothing)
        try:
            item = raw.get_item(
                Key={"pk": ck[0], "sk": call_sk},
                ProjectionExpression=", ".join(names),
                ExpressionAttributeNames=names,
            ).get("Item")
        except Exception as e:  # noqa: BLE001 — an unreadable call is not published (and not cached)
            logger.warning("[call_publication] lookup %s/%s failed: %s", ck[0], ck[1], type(e).__name__)
            return None
        if len(_LOOKUP_CACHE) >= _LOOKUP_MAX:
            _LOOKUP_CACHE.clear()
        _LOOKUP_CACHE[ck] = (now, item)
        return item

    return lookup


def _public(item: Any, pk_hint: Any, lookup) -> bool:
    if not isinstance(item, dict):
        return True
    return PP.row_is_public(item.get("pk", pk_hint), item, lookup)


def query(raw: Any, kwargs: dict, pk_hint: Any, lookup) -> dict:
    """``raw.query(**kwargs)`` with every non-eligible call's row omitted, ``Limit`` and ``COUNT`` kept honest."""
    kw, added = widen(dict(kwargs))
    limit = kw.pop("Limit", None)
    limit = int(limit) if limit else None
    count_only = kw.get("Select") == "COUNT"
    if count_only:
        kw.pop("Select", None)
    kept: list = []
    scanned = 0
    lek = None
    resp: dict = {}
    for page in range(MAX_FILL_PAGES):
        page_kw = dict(kw)
        if limit:
            page_kw["Limit"] = limit
        resp = raw.query(**page_kw) or {}
        items = list(resp.get("Items") or [])
        full = False
        for i, it in enumerate(items):
            scanned += 1
            if not _public(it, pk_hint, lookup):
                continue
            kept.append(it)
            if limit and len(kept) >= limit:
                full = True
                if (i < len(items) - 1 or resp.get("LastEvaluatedKey")) and isinstance(it, dict):
                    lek = {"pk": it.get("pk", pk_hint), "sk": it.get("sk")}
                break
        if full:
            break
        lek = resp.get("LastEvaluatedKey")
        if not lek or not limit:
            break
        kw["ExclusiveStartKey"] = lek
        if page == MAX_FILL_PAGES - 1:
            logger.error("[call_publication] %s: filled %d of %d rows in %d pages — stopping", pk_hint, len(kept), limit, MAX_FILL_PAGES)
    out = {k: v for k, v in resp.items() if k not in ("Items", "Count", "ScannedCount", "LastEvaluatedKey")}
    if not count_only:
        out["Items"] = [_strip(it, added) for it in kept]
    out["Count"] = len(kept)
    out["ScannedCount"] = scanned
    if lek:
        out["LastEvaluatedKey"] = lek
    return out


def scan(raw: Any, kwargs: dict, lookup) -> dict:
    kw, added = widen(dict(kwargs))
    resp = raw.scan(**kw) or {}
    if not isinstance(resp.get("Items"), list):
        return resp
    kept = [_strip(it, added) for it in resp["Items"] if _public(it, None, lookup)]
    return {**resp, "Items": kept, "Count": len(kept)}


def get_item(raw: Any, kwargs: dict, lookup) -> dict:
    key = kwargs.get("Key") or {}
    pk, sk = key.get("pk"), key.get("sk")
    if PP.kind_of(pk, sk) is None:
        return raw.get_item(**kwargs)
    kw, added = widen(dict(kwargs))
    resp = raw.get_item(**kw)
    if not isinstance(resp, dict) or not isinstance(resp.get("Item"), dict):
        return resp
    item = resp["Item"]
    if not PP.row_is_public(pk, {**item, "pk": item.get("pk", pk), "sk": item.get("sk", sk)}, lookup):
        return {k: v for k, v in resp.items() if k != "Item"}
    return {**resp, "Item": _strip(item, added)}
