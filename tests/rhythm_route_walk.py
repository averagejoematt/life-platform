#!/usr/bin/env python3
"""tests/rhythm_route_walk.py — walk every site-API GET handler against a table that
holds ONE heart-rhythm channel row (#4972), in a fresh interpreter.

Run by `tests/test_rhythm_channel_privacy_4972.py` as a subprocess, so the handlers'
module-level caches never carry the fixture into (or out of) the rest of the suite.

Every DynamoDB read any handler makes — query, get_item, scan, batch_get_item, on the
shared `site_api_common.table` and on every `web.*` module's own `table` binding — answers
with the channel row, whatever partition it asked for. S3, HTTP and Bedrock are dead
(raise), so a handler serves only what the table gave it. Prints one JSON document:
`{"routes": N, "answered": N, "raised": {...}, "leaks": {route: [tokens]}}`.

`--plant` is the mutation control: it re-binds ONE real public route (`/api/vitals`) to a
reader that also serves the first row its table query returns — the shape of a reader that
forgot to pick fields. The test asserts the walk catches it.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for k, v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
    ("AWS_ACCESS_KEY_ID", "testing"),
    ("AWS_SECRET_ACCESS_KEY", "testing"),
):
    os.environ.setdefault(k, v)

from health.rhythm_channel import CHANNEL_FIELDS  # noqa: E402

# Sentinel VALUES as well as field names: a leak under a renamed key still reds.
SENTINELS = ("RHYTHMSENTINELCLASS", "RHYTHMSENTINELMED", "RHYTHMSENTINELDOSE", "RHYTHMSENTINELDEVICE")
FIXTURE_ROWS = [
    {
        "pk": "USER#matthew#SOURCE#clinical",
        "sk": "RHYTHM#ECG#2026-10-17T08:12:03#apple-watch",
        "source": "clinical",
        "channel": "rhythm",
        "event_kind": "ecg",
        "event_date": "2026-10-17",
        "date": "2026-10-17",
        "rhythm_ecg_classification": "RHYTHMSENTINELCLASS",
        "rhythm_ecg_avg_hr_bpm": Decimal("71"),
        "rhythm_ecg_sample_start": "2026-10-17T08:12:03-07:00",
        "rhythm_ecg_device": "RHYTHMSENTINELDEVICE",
        "cross_device_same_day": True,
        "rhythm_notification_kind": "high",
        "rhythm_notification_kind_inferred": True,
        "rhythm_notification_at": "2026-10-17T03:00:00-07:00",
        "rhythm_notification_bpm": Decimal("131"),
        "rhythm_notification_threshold_bpm": Decimal("120"),
        "rhythm_notification_device": "RHYTHMSENTINELDEVICE",
        "rhythm_med_name": "RHYTHMSENTINELMED",
        "rhythm_med_dose_text": "RHYTHMSENTINELDOSE",
        "rhythm_med_at": "2026-10-17T07:30:00-07:00",
        "rhythm_med_status": "taken",
    }
]
TOKENS = tuple(CHANNEL_FIELDS) + SENTINELS + ("RHYTHM#",)


STATS = {"queries": 0, "index_queries": 0, "unparsed_queries": 0, "partitions": set()}


class _Dead(Exception):
    pass


def _requested_pk(kce, eav, ean):
    """The partition key a query asked for — from a string KeyConditionExpression or a
    boto3 `Key(...)` condition object. None when it cannot be read (then nothing matches)."""
    if isinstance(kce, str):
        names = {k: v for k, v in (ean or {}).items()}
        m = re.search(r"([#\w]+)\s*=\s*(:\w+)", kce)
        while m:
            attr = names.get(m.group(1), m.group(1))
            if attr == "pk":
                return (eav or {}).get(m.group(2))
            m = re.search(r"([#\w]+)\s*=\s*(:\w+)", kce[m.end() :])
        return None
    get_expr = getattr(kce, "get_expression", None)
    if get_expr is None:
        return None
    expr = get_expr()
    op, values = expr.get("operator"), expr.get("values") or ()
    if op == "AND":
        for v in values:
            pk = _requested_pk(v, eav, ean)
            if pk is not None:
                return pk
        return None
    if op == "=" and len(values) == 2 and getattr(values[0], "name", None) == "pk":
        return values[1]
    return None


class RhythmTable:
    """A table holding the channel row at its REAL key (`USER#matthew#SOURCE#clinical`).

    A query answers it only when it asks for that partition (the sort-key condition is
    ignored — over-inclusive on purpose); a get_item only at its exact key; a scan always
    (a scan reaches every partition). Writes are accepted silently."""

    name = "life-platform"

    def _rows(self, pk=None, sk=None):
        rows = [dict(r) for r in FIXTURE_ROWS]
        if pk is not None:
            rows = [r for r in rows if r["pk"] == pk]
        if sk is not None:
            rows = [r for r in rows if r["sk"] == sk]
        return rows

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExpressionAttributeNames=None, IndexName=None, **_kw):
        STATS["queries"] += 1
        if IndexName:
            # A GSI query (ADR-097's reading keyspace): the channel row carries no GSI key,
            # so no index query can return it — the real table answers the same way.
            STATS["index_queries"] += 1
            return {"Items": [], "Count": 0}
        pk = _requested_pk(KeyConditionExpression, ExpressionAttributeValues, ExpressionAttributeNames)
        if pk is None:
            STATS["unparsed_queries"] += 1
        else:
            STATS["partitions"].add(str(pk).split("#SOURCE#")[-1])
        rows = self._rows(pk) if pk is not None else []
        return {"Items": rows, "Count": len(rows)}

    def scan(self, **_kw):
        rows = self._rows()
        return {"Items": rows, "Count": len(rows)}

    def get_item(self, Key=None, **_kw):
        rows = self._rows((Key or {}).get("pk"), (Key or {}).get("sk"))
        return {"Item": rows[0]} if rows else {}

    def batch_get_item(self, RequestItems=None, **_kw):
        out = []
        for spec in (RequestItems or {}).values():
            for key in spec.get("Keys") or []:
                out.extend(self._rows(key.get("pk"), key.get("sk")))
        return {"Responses": {"life-platform": out}}

    def put_item(self, **_kw):
        return {}

    def update_item(self, **_kw):
        return {"Attributes": {}}

    def delete_item(self, **_kw):
        return {}


class _DeadClient:
    def __getattr__(self, name):
        if name == "exceptions":
            raise AttributeError(name)

        def _raise(*_a, **_k):
            raise _Dead(f"external call {name} disabled in the route walk")

        return _raise


def _wire():
    import urllib.request

    import boto3

    table = RhythmTable()
    boto3.client = lambda *a, **k: _DeadClient()  # type: ignore[assignment]

    class _Res:
        def Table(self, _name):  # noqa: N802 — boto3's spelling
            return table

    boto3.resource = lambda *a, **k: _Res()  # type: ignore[assignment]
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(_Dead("http disabled"))  # type: ignore[assignment]

    from web import site_api_lambda as L

    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith(("web.", "common.", "intelligence.", "health.", "ai.")) or mod is None:
            continue
        for attr in ("table", "_table", "TABLE", "ddb_table"):
            if hasattr(getattr(mod, attr, None), "query"):
                setattr(mod, attr, table)
        for attr in ("s3", "s3_client", "_s3", "S3", "bedrock", "_bedrock", "cloudwatch", "cw"):
            if attr in vars(mod) and not isinstance(vars(mod)[attr], type):
                setattr(mod, attr, _DeadClient())
    try:
        from ai import bedrock_client

        bedrock_client.invoke = lambda *a, **k: (_ for _ in ()).throw(_Dead("bedrock disabled"))
    except ImportError:
        pass
    return L, table


def route_paths(L) -> list:
    paths = set(L.ROUTES) | set(getattr(L, "_SIMPLE_ROUTES", {}))
    paths |= set(re.findall(r'path (?:==|\.startswith\() ?"(/api/[^"]+)"', inspect.getsource(L._dispatch_route)))
    return sorted(paths)


def walk(plant: bool = False) -> dict:
    L, table = _wire()
    if plant:
        real = L.ROUTES["/api/vitals"]

        def handle_vitals_planted(*a, **k):
            resp = real(*a, **k)
            body = json.loads(resp["body"]) if isinstance(resp, dict) and isinstance(resp.get("body"), str) else {}
            items = table.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": "USER#matthew#SOURCE#clinical"})[
                "Items"
            ]
            body["planted"] = [{"classification": i.get("rhythm_ecg_classification")} for i in items]
            return {"statusCode": 200, "body": json.dumps(body, default=str)}

        L.ROUTES["/api/vitals"] = handle_vitals_planted
        L._SIMPLE_ROUTES.pop("/api/vitals", None)
    result = {"routes": 0, "answered": 0, "raised": {}, "leaks": {}}
    for path in route_paths(L):
        result["routes"] += 1
        for qs in QUERY_VARIANTS:
            _one(L, path, qs, result)
    return result


# Pass 1 is the bare request; pass 2 asks for the channel by every parameter name a
# generic "serve a source / field" route would take.
QUERY_VARIANTS = (
    {},
    {"source": "clinical", "metric": "rhythm_ecg_classification", "field": "rhythm_ecg_classification", "date": "2026-10-17"},
)


def _one(L, path, qs, result):
    event = {
        "rawPath": path,
        "path": path,
        "httpMethod": "GET",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "queryStringParameters": dict(qs),
    }
    key = path + ("?" + "&".join(f"{k}={v}" for k, v in qs.items()) if qs else "")
    try:
        resp = L._dispatch_route(event, path, "GET")
        if resp is None and callable(L.ROUTES.get(path)):
            resp = L.ROUTES[path]()
    except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
        result["raised"][key] = type(e).__name__
        return
    if resp is None:
        return
    result["answered"] += 1
    blob = json.dumps(resp, default=str)
    hits = sorted({t for t in TOKENS if t in blob})
    if hits:
        result["leaks"][key] = hits


if __name__ == "__main__":
    import io
    import logging

    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; keep stdout for the one JSON line
    try:
        out = walk(plant="--plant" in sys.argv)
        out["queries"] = STATS["queries"]
        out["unparsed_queries"] = STATS["unparsed_queries"]
        out["index_queries"] = STATS["index_queries"]
        out["partitions_asked"] = sorted(STATS["partitions"])
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(out))
