"""public_call_id.py — the public identity of a coach's call: opaque, stable, and never made of its words (owner ruling 2026-11-14).

THE DEFECT. A call's stored identity (``prediction_id`` / the ``PREDICTION#`` sort key) is a slug of its own sentence —
``pred_20261109_recovery_score_tomorrow_will_fall_betwee``. Served as ``prediction_id`` and built into page addresses
(``/system/ledger/<coach>-<id>/``), it carried the words of calls whose words are withheld. The narrative gate's taint
match (``web.narrative_publication``) emptied some of those ids on the wire and not others — which ids depended on what
the container had read — so ~250 of the ledger's ~425 rows reached the public with no id at all, could not be listed or
linked, and the listed count moved between builds (173 one hour, 177 the next).

THE IDENTITY. ``<YYYYMMDD>-<t>``: the UTC day the call was FIRST filed and that instant's microseconds-of-day in base 36,
read from the row's ``created_at`` — written once when the call is filed and never changed. The earliest ``created_at``
across every row sharing the call's stored key in its coach's partition (a re-write keeps the original's key), so a
re-grade never moves the address. Measured 2026-11-14: unique across all 493 calls of the cycle at the microsecond
(second-level stamps collide 165 times — batch filings). No text, no hash of text, no secret: nothing of the words is
in it, and nothing about it can be inverted to them. Coach-scoped, like the stored key (a docket bet is stamped on both
sides' rows under one key): pages address ``<coach>-<id>``.

THE CHOKEPOINT. ``remember`` is called by the ONE partition reader every public route uses
(``web.site_api_coach_ledger._query_partition``) for each ``PREDICTION#`` read, so the map is the rows the routes read.
``publicize`` runs on every public response before the existing wire guards: each ``prediction_id`` / ``item_id``, each
``counted_calls`` entry, a memory record's ``record_id`` and its list of linked ``predictions`` is replaced by its public
identity; a stored key the map cannot place is EMPTIED (fail closed — an unmapped slug is withheld wording, never a link),
and a non-call record id (an ask's slug) is emptied outright. The stored rows are untouched: the owner's tools, the graders and
every internal join keep the stored keys.

ONE ANSWER FOR ONE TABLE (#6111). The map used to be only what this container's routes had happened to read, so a route
that never read a coach's ledger through the partition reader (``/api/coaches``' ``latest_checked``, a coach page's
learning evidence) served ``""`` on a cold container and the id on a warm one. Now, in a Site API request, a coach's map
is built from the COMPLETE read of that coach's partition (``web.publication_snapshot`` — the same read the gate's
complete taint comes from), restricted to the calls the call publication policy passes; it is fresh within the
snapshot's TTL and re-read once in the request when a key is missing (a call filed since). A lookup without a coach, or
a membership check of an already-public id, reads every coach first. A filed call's id never changes (its first filing
instant is written once), so a kept map gives the answer a fresh read would.
"""

from __future__ import annotations

import re
import threading
from datetime import timezone
from typing import Any, Iterable, Optional

from common.pacific_time import parse_iso_utc

_LOCK = threading.Lock()
_ORIGINAL: dict[tuple[str, str], str] = {}  # (coach short id, stored key) -> earliest created_at (ISO)
_PUBLIC: dict[tuple[str, str], str] = {}  # (coach short id, stored key) -> public id
_BY_KEY: dict[str, set] = {}  # stored key -> {public ids} (a key filed by two coaches maps to two ids)
_ISSUED: set = set()  # every public id issued

_APPLIED: dict[str, int] = {}  # coach -> the snapshot read version its map was built from
_SOURCE: dict[str, Any] = {"raw": None}  # the raw table the map was built from (another table: the map starts over)

_PK = re.compile(r"^COACH#([a-z0-9]+)_coach$")
PUBLIC_ID = re.compile(r"^\d{8}-[0-9a-z]{1,8}(-\d+)?$")
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n: int) -> str:
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _B36[r] + out
        if not n:
            return out


def public_id(created_at: Any) -> Optional[str]:
    """``<YYYYMMDD>-<base36 microseconds of the UTC day>`` for an ISO instant; None when it does not parse."""
    t = parse_iso_utc(str(created_at or "").strip())
    if t is None:
        return None
    t = t.astimezone(timezone.utc)
    micros = ((t.hour * 60 + t.minute) * 60 + t.second) * 1_000_000 + t.microsecond
    return f"{t:%Y%m%d}-{_b36(micros)}"


def stored_key(row: dict) -> str:
    """The stored identity a re-write shares with its original (coach.coach_record.prediction_key's rule)."""
    pid = str(row.get("prediction_id") or "").strip()
    return pid or str(row.get("sk") or "").replace("PREDICTION#", "", 1).strip()


def coach_of_pk(pk: Any) -> Optional[str]:
    m = _PK.match(str(pk or ""))
    return m.group(1) if m else None


def remember(coach: str, rows: Iterable[Any]) -> None:
    """Record the public identity of every call in one coach's partition read (the earliest ``created_at`` wins).

    Two calls first filed at the same instant (a batch backfill can stamp one) share a base id; they are told apart by
    their stored keys' sort order — ``<base>``, ``<base>-2``, ``<base>-3`` — the same answer from any read of the partition.
    """
    if not coach:
        return
    with _LOCK:
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            key = stored_key(row)
            ca = str(row.get("created_at") or "").strip()
            if not key or not ca or not public_id(ca):
                continue
            k = (coach, key)
            if k not in _ORIGINAL or ca < _ORIGINAL[k]:
                _ORIGINAL[k] = ca
        # rebuild this coach's public ids from its originals (tie-break by stored key)
        groups: dict[str, list[str]] = {}
        for (c, key), ca in _ORIGINAL.items():
            if c == coach:
                groups.setdefault(public_id(ca) or "", []).append(key)
        for base, keys in groups.items():
            for i, key in enumerate(sorted(keys)):
                pub = base if i == 0 else f"{base}-{i + 1}"
                old = _PUBLIC.get((coach, key))
                if old and old != pub:
                    _BY_KEY.get(key, set()).discard(old)
                _PUBLIC[(coach, key)] = pub
                _BY_KEY.setdefault(key, set()).add(pub)
                _ISSUED.add(pub)


def remember_read(pk: Any, sk_prefix: Any, rows: list) -> list:
    """The partition reader's hook: a ``PREDICTION#`` read of a coach partition registers its calls; rows pass through."""
    coach = coach_of_pk(pk) if sk_prefix == "PREDICTION#" else None
    if coach:
        remember(coach, rows)
    return rows


def reset_map() -> None:
    """Forget every coach's map (not the request): a map read from one table never answers for another."""
    with _LOCK:
        _ORIGINAL.clear()
        _PUBLIC.clear()
        _BY_KEY.clear()
        _ISSUED.clear()
        _APPLIED.clear()


def reset() -> None:
    reset_map()
    _SOURCE["raw"] = None


def _forget(coach: str) -> None:
    """Drop one coach's map (a complete read replaces it, never merges into it)."""
    with _LOCK:
        for k in [k for k in _ORIGINAL if k[0] == coach]:
            del _ORIGINAL[k]
        for k in [k for k in _PUBLIC if k[0] == coach]:
            del _PUBLIC[k]
        _BY_KEY.clear()
        for (_c, key), pub in _PUBLIC.items():
            _BY_KEY.setdefault(key, set()).add(pub)
        _ISSUED.clear()
        _ISSUED.update(_PUBLIC.values())


def all_coaches() -> tuple:
    """Every coach whose partition can hold calls (``COACH#<short>_coach``): the operational and the retired seats."""
    from coach.persona_registry import OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS

    return tuple(sorted({c[: -len("_coach")] for c in (*OPERATIONAL_COACH_IDS, *RETIRED_COACH_IDS) if c.endswith("_coach")}))


def _ensure(coach: str, force: bool = False) -> None:
    _ensure_many((coach,), force)


def _ensure_all(force: bool = False) -> None:
    _ensure_many(all_coaches(), force)


def _refreshed(coach: str) -> bool:
    from web import publication_snapshot as S

    return S.coach_pk(coach) in S._REQ["refreshed"]


def _ensure_many(coaches: Iterable[str], force: bool = False) -> None:
    """Each coach's map built from the complete read of its partition (``web.publication_snapshot``: fresh within its
    TTL, or — with ``force`` — re-read once in this request); a no-op outside a request opened with a table."""
    from web import publication_snapshot as S

    if not S.active():
        return
    coaches = [c for c in dict.fromkeys(coaches) if c]
    S.ensure([S.coach_pk(c) for c in coaches], force)
    if _SOURCE["raw"] is not S._STATE["raw"]:
        reset_map()
        _SOURCE["raw"] = S._STATE["raw"]
    for c in coaches:
        got = S.calls(S.coach_pk(c))
        if got is not None and _APPLIED.get(c) != got[0]:
            _forget(c)
            remember(c, got[1])
            _APPLIED[c] = got[0]


def of(coach: Optional[str], key: Any) -> Optional[str]:
    """The public identity of ``key`` filed by ``coach``; without a coach, only when the key names exactly one call."""
    k = str(key or "").strip()
    if not k:
        return None
    if PUBLIC_ID.match(k):
        _ensure_all()  # membership is only an answer against every coach's complete map
    if k in _ISSUED:
        return k  # already public (a payload built from an already-publicized one) — by membership, never by shape
    if coach:
        _ensure(coach)
        p = _PUBLIC.get((coach, k))
        if p is None and not _refreshed(coach):
            _ensure(coach, force=True)  # a call filed since the map was read
            p = _PUBLIC.get((coach, k))
        if p:
            return p
    _ensure_all()
    ids = _BY_KEY.get(k) or set()
    if not ids:
        _ensure_all(force=True)
        ids = _BY_KEY.get(k) or set()
    return next(iter(ids)) if len(ids) == 1 else None


def _coach_short(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    if s.endswith("_coach"):
        s = s[: -len("_coach")]
    return s or None


_ID_KEYS = ("prediction_id", "item_id")
_LIST_KEYS = ("counted_calls",)


def _item_id(value: str) -> str:
    coach, _, key = value.partition(":")
    pub = of(coach, key) if key else None
    return f"{coach}:{pub}" if pub else ""


def _counted(value: Any) -> str:
    s = str(value or "")
    coach, _, key = s.partition("-")
    pub = of(coach, key) if key else None
    return f"{coach}-{pub}" if pub else ""


def _record_id(value: str, coach: Optional[str]) -> str:
    """A memory record's id: a call's (``PREDICTION#<key>``) becomes ``PREDICTION#<public id>``; any other family's id is
    a slug of its own words too (an ask's ``COMMITMENT#commit_<date>_<words>``) and no page reads it — emptied."""
    fam, sep, key = value.partition("#")
    if sep and fam == "PREDICTION":
        pub = of(coach, key)
        return f"PREDICTION#{pub}" if pub else ""
    return ""


def publicize(node: Any, coach: Optional[str] = None) -> Any:
    """Every public call identity in a JSON-shaped payload replaced by its opaque public id (see the module docstring)."""
    if isinstance(node, dict):
        here = _coach_short(node.get("coach_id")) or coach
        out = {}
        for k, v in node.items():
            if k == "prediction_id" and isinstance(v, str):
                out[k] = (of(here, v) or "") if v else v
            elif k == "item_id" and isinstance(v, str):
                out[k] = _item_id(v) if v else v
            elif k in _LIST_KEYS and isinstance(v, list):
                out[k] = [_counted(x) for x in v]
            elif k == "record_id" and isinstance(v, str):
                out[k] = _record_id(v, here)
            elif k == "predictions" and isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                out[k] = [of(here, x) or "" for x in v]  # a record's linked calls, by stored key
            else:
                out[k] = publicize(v, here)
        return out
    if isinstance(node, list):
        return [publicize(v, coach) for v in node]
    return node


def publicize_response(result: Any) -> Any:
    """A handler result (``{statusCode, body, ...}``) with its JSON body publicized. Non-JSON bodies pass untouched."""
    import json

    if not isinstance(result, dict) or result.get("isBase64Encoded"):
        return result
    body = result.get("body")
    if not isinstance(body, str) or not body.lstrip().startswith(("{", "[")):
        return result
    if not any(k in body for k in ('"prediction_id"', '"item_id"', '"counted_calls"', '"record_id"', '"predictions"')):
        return result
    try:
        parsed = json.loads(body)
    except ValueError:
        return result
    return {**result, "body": json.dumps(publicize(parsed), ensure_ascii=False, default=str)}
