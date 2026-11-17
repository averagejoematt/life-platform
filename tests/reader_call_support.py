"""tests/reader_call_support.py — the shared fakes and fixture rows for the reader-call tests (#6088, #6114).

Not a test module: an in-memory table that logs every write with its key (the isolation proofs read that log), boto3
Key conditions, the shared limiter's conditional ADD, and call rows built by the coaches' own writer
(``coach.prediction_emission.build_prediction_record``) with synthetic words, so the real publication policy classifies
them through the real governed ``PublicationTable``. No live call's words appear here.
"""

from __future__ import annotations

import json
import threading

from coach import prediction_emission
from web import narrative_publication, reader_call_rules as R, site_api_reader_call as rc

NOW = 1_794_830_400  # 2026-11-16T12:00:00Z — every clock in this file is this instant or an offset from it
TODAY = "2026-11-16"
GENESIS = "2026-09-06"
KEY = b"k" * 32

DIRECTION_CLAIM = "His weight will fall over the next two weeks."
NUMBER_CLAIM = "His weight will be 180 lb on November 30, give or take 1.5 lb."
PRIVATE_CLAIM = "His journal entries will get longer over the next two weeks."
DIRECTION_SPEC = {"type": "directional", "metric": "weight_lbs", "condition": "down", "evaluation_window_days": 14}
NUMBER_SPEC = {"type": "point", "metric": "weight_lbs", "threshold": 180, "tolerance": 1.5, "target_date": "2026-11-30"}


class _CCF(Exception):
    """Carries both shapes the code reads: ``str(e)`` (the route) and ``e.response`` (the shared limiter)."""

    def __init__(self):
        super().__init__("An error occurred (ConditionalCheckFailedException)")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """A bounded in-memory table: (pk, sk) store, boto3 Key conditions, the limiter's conditional ADD, and a log of
    every WRITE with its key — the log is what proof (a) reads. ``fail`` = {(op, pk_prefix)} raises a plain error."""

    def __init__(self, rows=(), fail=()):
        self.store = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.fail = set(fail)
        self.writes: list = []
        self.reads: list = []
        self._lock = threading.Lock()

    def _boom(self, op, pk):
        if any(op == o and str(pk).startswith(p) for o, p in self.fail):
            raise RuntimeError(f"ddb {op} unavailable")

    def get_item(self, Key=None, **_kw):
        self.reads.append(("get_item", Key["pk"]))
        self._boom("get_item", Key["pk"])
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kw):
        cond = kw.get("KeyConditionExpression")
        pk, prefix = _key_parts(cond, kw)
        self.reads.append(("query", pk))
        self._boom("query", pk)
        items = [dict(v) for (p, s), v in sorted(self.store.items()) if p == pk and str(s).startswith(prefix or "")]
        if kw.get("Select") == "COUNT":
            return {"Count": len(items), "Items": []}
        return {"Items": items, "Count": len(items)}

    def scan(self, **_kw):
        self.reads.append(("scan", None))
        return {"Items": [dict(v) for v in self.store.values()]}

    def put_item(self, Item=None, ConditionExpression=None, **_kw):
        with self._lock:
            self.writes.append(("put_item", Item["pk"], Item["sk"]))
            self._boom("put_item", Item["pk"])
            key = (Item["pk"], Item["sk"])
            if ConditionExpression == "attribute_not_exists(pk)" and key in self.store:
                raise _CCF()
            self.store[key] = dict(Item)
            return {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw):
        with self._lock:
            self.writes.append(("update_item", Key["pk"], Key["sk"]))
            self._boom("update_item", Key["pk"])
            names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
            item = self.store.setdefault((Key["pk"], Key["sk"]), dict(Key))
            attr = names.get("#c") or names.get("#n") or "count"
            inc = values.get(":inc", values.get(":one", 1))
            if ":headroom" in values and (item.get(attr) or 0) > values[":headroom"]:
                raise _CCF()
            item[attr] = (item.get(attr) or 0) + inc
            return {"Attributes": {attr: item[attr]}}

    def delete_item(self, Key=None, **_kw):  # pragma: no cover — the route never deletes; logged if it ever does
        self.writes.append(("delete_item", Key["pk"], Key["sk"]))

    def reader_rows(self):
        return {k: v for k, v in self.store.items() if k[0].startswith(R.PK_PREFIX)}


def _key_parts(cond, kw):
    if isinstance(cond, str):
        vals = kw.get("ExpressionAttributeValues") or {}
        return vals.get(":pk"), vals.get(":p") or vals.get(":prefix") or vals.get(":sk")
    pk = prefix = None

    def walk(node):
        nonlocal pk, prefix
        e = node.get_expression()
        if e["operator"] == "AND":
            for v in e["values"]:
                walk(v)
        elif e["operator"] == "=" and e["values"][0].name == "pk":
            pk = e["values"][1]
        elif e["operator"] == "begins_with":
            prefix = e["values"][1]

    walk(cond)
    return pk, prefix


def _row(claim, spec, *, coach="sleep_coach", day="2026-11-14", **extra):
    row = prediction_emission.build_prediction_record(coach, day, claim, spec, 0.6, "gradeable")
    row["pk"] = f"COACH#{coach}"
    row.update(extra)
    return row


def _call_id(row):
    """The call's PUBLIC item id, as /api/ledger_export serves it (#6120): ``<coach short id>:<public id>`` — the opaque id
    from the call's first-filed instant (``web.public_call_id.public_id``), never its stored, word-made key."""
    from web import public_call_id

    return f"{row['pk'][len('COACH#'):-len('_coach')]}:{public_call_id.public_id(row['created_at'])}"


DIR_ROW = _row(DIRECTION_CLAIM, DIRECTION_SPEC)
NUM_ROW = _row(NUMBER_CLAIM, NUMBER_SPEC)
PRIVATE_ROW = _row(PRIVATE_CLAIM, DIRECTION_SPEC)
GRADED_ROW = _row(
    "His weight will fall over the coming fortnight.",
    DIRECTION_SPEC,
    day="2026-10-01",
    status="confirmed",
    outcome_date="2026-10-15",
    outcome_notes=json.dumps({"actual_value": -0.01, "reason": "fell", "window": {"direction": "down"}}),
)
DUE_TODAY_ROW = _row(
    "His weight will be 181 lb on November 16, give or take 1.5 lb.",
    {**NUMBER_SPEC, "threshold": 181, "target_date": TODAY},
    day="2026-11-10",
)
SEALED_ROW = _row(
    "His weight will fall over the next fortnight.", DIRECTION_SPEC, pre_registered=True, pre_registered_at="2026-09-04T12:00:00Z"
)
#: Pending, no outcome, but its measured window ended on 3 November: the outcome can be read, so it is CLOSED.
WINDOW_ENDED_ROW = _row("His weight will fall over the next two weeks, from today.", DIRECTION_SPEC, day="2026-10-20")
ALL_ROWS = (DIR_ROW, NUM_ROW, PRIVATE_ROW, GRADED_ROW, DUE_TODAY_ROW, SEALED_ROW, WINDOW_ENDED_ROW)

OWNER_PREFIXES = ("USER#", "COACH#")


def _table(rows=ALL_ROWS, fail=()):
    raw = FakeTable(rows, fail)
    return raw, narrative_publication.PublicationTable(raw)


def _event(method="GET", *, ip="203.0.113.7", params=None, body=None):
    headers = {"cloudfront-viewer-address": f"{ip}:4433"}
    if method == "POST":
        headers["content-type"] = "application/json"
    ev = {"requestContext": {"http": {"method": method}}, "headers": headers}
    if params is not None:
        ev["queryStringParameters"] = params
    if body is not None:
        ev["body"] = body if isinstance(body, str) else json.dumps(body)
    return ev


def _body(resp):
    return json.loads(resp["body"])


def _ask(table, event, *, now=NOW, today=TODAY, live=True, runtime=lambda: True, raw=None):
    """One request, opened the way site_api_lambda opens it: the complete-read snapshot (#6120) against this table, so
    the public id resolves through the same policy-filtered map production uses; closed again afterwards."""
    from web import narrative_publication, publication_snapshot

    narrative_publication.begin_request()  # as site_api_lambda does: forget the previous request's table and taint
    publication_snapshot.begin_request(table)
    try:
        resp = rc.handle_reader_call(
            event, table=table, live=live, runtime=runtime, now=now, today=today, presence=lambda t: [], key_fn=lambda p, lg=None: KEY
        )
    finally:
        publication_snapshot.begin_request(None)
    if raw is not None:  # the isolation proof, after EVERY request it is given a raw table for
        owner = [w for w in raw.writes if str(w[1]).startswith(OWNER_PREFIXES)]
        assert not owner, f"the reader-call route wrote an owner partition: {owner}"
    return resp


def _token(raw, table, call, ip="203.0.113.7", at=NOW):
    resp = _ask(table, _event(params={"call": call}, ip=ip), now=at, raw=raw)
    assert resp["statusCode"] == 200, resp
    return _body(resp)["token"]


def _tap(raw, table, call, choice, ip="203.0.113.7", at=NOW, delay=5, token=None, today=TODAY, **extra):
    token = token if token is not None else _token(raw, table, call, ip=ip, at=at)
    body = {"call": call, "choice": choice, "token": token, "hp": "", **extra}
    return _ask(table, _event("POST", ip=ip, body=body), now=at + delay, today=today, raw=raw)


def _tally(raw):
    return {s[len(R.TALLY_SK_PREFIX) :]: v["count"] for (p, s), v in raw.reader_rows().items() if s.startswith(R.TALLY_SK_PREFIX)}


def _is_shut(resp, event) -> bool:
    """The shut / not-callable answer (#6114): a POST is refused 404 "not available"; a GET gets the uniform non-error
    ``{"available": false}`` so no call page logs a failed request."""
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    body = {k: v for k, v in _body(resp).items() if k != "_meta"}
    if method == "POST":
        return resp["statusCode"] == 404 and body.get("error") == rc.NOT_AVAILABLE
    return resp["statusCode"] == 200 and body == {"available": False}
