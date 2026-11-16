"""#6088 — "your call beside the coaches": the reader-call route, built DARK, and the owner's isolation line.

Owner ruling 2026-11-16: "These actions must not alter my own historical evidence, grading records or experiments.
Develop and test privately." So beside the route's own behaviour this file carries the isolation proofs:

  (a) no branch of the route — success or any refusal or failure — writes a ``USER#matthew#…`` or ``COACH#…`` key:
      every request below runs against a fake table whose write log is checked after EVERY request;
  (b) the ledger export, /api/predictions and /api/calibration are byte-identical with and without reader tallies
      present in the table (``test_owner_record_reads_are_identical_with_and_without_reader_rows``);
  (c) replay, concurrent duplicates and a changed choice from one identity move the tally once;
  (d) an expired / forged / too-young / other-call / other-identity token and a filled honeypot write nothing;
  (e) a limiter error refuses, with no write.

Rows are built by the coaches' own writer (``coach.prediction_emission.build_prediction_record``) with synthetic
words, so the publication policy classifies them exactly as it would a live row. No live call's words appear here.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
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
    return f"{row['pk'][len('COACH#'):-len('_coach')]}-{row['prediction_id']}"


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
ALL_ROWS = (DIR_ROW, NUM_ROW, PRIVATE_ROW, GRADED_ROW, DUE_TODAY_ROW, SEALED_ROW)

OWNER_PREFIXES = ("USER#", "COACH#")


def _table(rows=ALL_ROWS, fail=()):
    raw = FakeTable(rows, fail)
    return raw, narrative_publication.PublicationTable(raw)


def _event(method="GET", *, ip="203.0.113.7", params=None, body=None):
    ev = {"requestContext": {"http": {"method": method}}, "headers": {"cloudfront-viewer-address": f"{ip}:4433"}}
    if params is not None:
        ev["queryStringParameters"] = params
    if body is not None:
        ev["body"] = body if isinstance(body, str) else json.dumps(body)
    return ev


def _ask(table, event, *, now=NOW, today=TODAY, live=True, raw=None):
    resp = rc.handle_reader_call(event, table=table, live=live, now=now, today=today, presence=lambda t: [], key_fn=lambda p, lg=None: KEY)
    if raw is not None:  # proof (a), after EVERY request in this file that is given its raw table
        owner = [w for w in raw.writes if str(w[1]).startswith(OWNER_PREFIXES)]
        assert not owner, f"the reader-call route wrote an owner partition: {owner}"
    return resp


def _body(resp):
    return json.loads(resp["body"])


@pytest.fixture(autouse=True)
def _genesis(monkeypatch):
    from web import site_api_common

    monkeypatch.setattr(site_api_common, "EXPERIMENT_START", GENESIS)


def _token(raw, table, call, ip="203.0.113.7", at=NOW):
    resp = _ask(table, _event(params={"call": call}, ip=ip), now=at, raw=raw)
    assert resp["statusCode"] == 200, resp
    return _body(resp)["token"]


def _tap(raw, table, call, choice, ip="203.0.113.7", at=NOW, delay=5, token=None, **extra):
    token = token if token is not None else _token(raw, table, call, ip=ip, at=at)
    return _ask(
        table, _event("POST", ip=ip, body={"call": call, "choice": choice, "token": token, "hp": "", **extra}), now=at + delay, raw=raw
    )


def _tally(raw):
    return {s[len(R.TALLY_SK_PREFIX) :]: v["count"] for (p, s), v in raw.reader_rows().items() if s.startswith(R.TALLY_SK_PREFIX)}


# ── the switch ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_switch_is_committed_off_and_off_touches_nothing():
    assert R.READER_CALL_LIVE is False, "the master switch is committed OFF until the owner's go"
    raw, table = _table()
    for ev in (_event(params={"call": _call_id(DIR_ROW)}), _event("POST", body={"call": _call_id(DIR_ROW), "choice": "up"}), _event()):
        resp = rc.handle_reader_call(ev, table=table, now=NOW, today=TODAY)  # live=None → the committed switch
        assert resp["statusCode"] == 404 and _body(resp)["error"] == rc.NOT_AVAILABLE
    assert raw.writes == [] and raw.reads == [], "off must not read, meter or write"


def test_the_route_is_mounted_for_get_and_post():
    from web import site_api_lambda as router

    assert router._SIMPLE_ROUTES["/api/reader_call"] == ({"GET", "POST"}, rc.handle_reader_call)
    assert "/api/reader_call" in router.ROUTES


# ── a tap, end to end ──────────────────────────────────────────────────────────────────────────────────


def test_a_tap_is_counted_and_the_split_comes_back():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    view = _body(_ask(table, _event(params={"call": call}), raw=raw))
    assert view["open"] is True and view["kind"] == "direction" and view["coach_choice"] == "down"
    assert [c["id"] for c in view["choices"]] == ["up", "down", "same"]
    assert view["tally"] == {"counts": {"up": 0, "down": 0, "same": 0}, "total": 0}
    assert view["copy"] == R.COPY and "not evidence" in view["note"]
    resp = _tap(raw, table, call, "same")
    assert resp["statusCode"] == 200 and _body(resp)["tally"] == {"counts": {"up": 0, "down": 0, "same": 1}, "total": 1}
    marker = next(v for (p, s), v in raw.reader_rows().items() if s.startswith(R.TAP_SK_PREFIX))
    assert set(marker) == {"pk", "sk", "tapped_at", "ttl"}, "the marker stores no choice, no address, no text"
    # due 2026-12-12 → TTL is the end of that day + the grace (2026-12-13T00:00Z = 1797120000)
    assert marker["ttl"] == 1_797_120_000 + R.DEDUP_GRACE_S


def test_a_number_call_offers_above_within_below_its_own_level():
    raw, table = _table()
    view = _body(_ask(table, _event(params={"call": _call_id(NUM_ROW)}), raw=raw))
    assert view["kind"] == "number" and view["coach_choice"] == "within"
    assert [c["label"] for c in view["choices"]] == ["Above 180 (by more than 1.5)", "Within 1.5 of 180", "Below 180 (by more than 1.5)"]
    assert _tap(raw, table, _call_id(NUM_ROW), "below")["statusCode"] == 200
    assert _tap(raw, table, _call_id(NUM_ROW), "sideways", ip="198.51.100.9")["statusCode"] == 400


# ── (c) one identity moves the tally once ──────────────────────────────────────────────────────────────


def test_replay_concurrency_a_changed_choice_and_one_ipv6_64_move_the_tally_once():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    assert _tap(raw, table, call, "up", token=token)["statusCode"] == 200
    assert _tap(raw, table, call, "up", token=token)["statusCode"] == 409  # replay of the same token
    assert _tap(raw, table, call, "down")["statusCode"] == 409  # a changed choice, fresh token
    # a different address inside the same IPv6 /64 is the same reader; a different /64 is not
    assert _tap(raw, table, call, "down", ip="[2001:db8:1:2::a]")["statusCode"] == 200
    assert _tap(raw, table, call, "down", ip="[2001:db8:1:2::ffff]")["statusCode"] == 409
    # concurrent duplicates from one fresh identity: exactly one wins the conditional marker
    tok = _token(raw, table, call, ip="198.51.100.20")
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _i: _tap(raw, table, call, "same", ip="198.51.100.20", token=tok)["statusCode"], range(8)))
    assert sorted(codes) == [200] + [409] * 7
    assert _tally(raw) == {"up": 1, "down": 1, "same": 1}


# ── (d) the bot check refuses without a write ──────────────────────────────────────────────────────────


def test_bad_tokens_and_a_filled_honeypot_are_refused_without_a_write():
    raw, table = _table()
    call, other = _call_id(DIR_ROW), _call_id(NUM_ROW)
    good = _token(raw, table, call)
    cases = {
        "forged": dict(token=good[:-1] + ("0" if good[-1] != "0" else "1")),
        "too_young": dict(token=good, delay=1),
        "expired": dict(token=good, delay=R.TOKEN_MAX_AGE_S + 1),
        "other_call": dict(token=_token(raw, table, other)),
        "other_identity": dict(token=_token(raw, table, call, ip="198.51.100.50")),
        "missing": dict(token=""),
        "malformed": dict(token="not-a-token"),
    }
    before = list(raw.writes)
    for name, kw in cases.items():
        resp = _tap(raw, table, call, "up", **kw)
        assert resp["statusCode"] == 403, (name, resp)
    hp = _tap(raw, table, call, "up", hp="https://spam.example")
    assert hp["statusCode"] == 400
    reader_writes = [w for w in raw.writes[len(before) :] if w[1].startswith(R.PK_PREFIX)]
    assert reader_writes == [], f"a refused tap wrote: {reader_writes}"
    assert _tally(raw) == {}


def test_the_token_rules_are_pure_and_bound_to_call_identity_and_instant():
    t = R.mint_token(KEY, "sleep-p1", "abc", NOW)
    assert R.check_token(KEY, t, "sleep-p1", "abc", NOW + R.TOKEN_MIN_AGE_S) is None
    assert R.check_token(KEY, t, "sleep-p1", "abc", NOW + R.TOKEN_MAX_AGE_S) is None
    assert R.check_token(KEY, t, "sleep-p1", "abc", NOW + R.TOKEN_MIN_AGE_S - 1) == "too_young"
    assert R.check_token(KEY, t, "sleep-p1", "abc", NOW + R.TOKEN_MAX_AGE_S + 1) == "expired"
    assert R.check_token(KEY, t, "sleep-p2", "abc", NOW + 5) == "forged"
    assert R.check_token(KEY, t, "sleep-p1", "abd", NOW + 5) == "forged"
    assert R.check_token(b"x" * 32, t, "sleep-p1", "abc", NOW + 5) == "forged"
    issued, mac = t.split(".")
    assert R.check_token(KEY, f"{int(issued) - 100}.{mac}", "sleep-p1", "abc", NOW + 5) == "forged"  # re-dated → forged


# ── (e) a limiter error refuses, no write ──────────────────────────────────────────────────────────────


def test_a_limiter_error_refuses_both_verbs_without_a_write():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    raw.fail = {("update_item", "RATE#")}
    assert _ask(table, _event(params={"call": call}), raw=raw)["statusCode"] == 429
    assert _tap(raw, table, call, "up", token=token)["statusCode"] == 429
    assert raw.reader_rows() == {}


def test_the_meter_limits_one_network():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    codes = [_ask(table, _event("POST", body={"call": call}), raw=raw)["statusCode"] for _ in range(rc.TAP_LIMIT_PER_HOUR + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {403}


# ── the two write-order failure halves ─────────────────────────────────────────────────────────────────


def test_a_failed_dedup_write_counts_nothing():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    raw.fail = {("put_item", R.PK_PREFIX)}
    resp = _tap(raw, table, call, "up", token=token)
    assert resp["statusCode"] == 503 and _body(resp)["recorded"] is False
    assert not any(w[0] == "update_item" and w[1].startswith(R.PK_PREFIX) for w in raw.writes), "no ADD after a failed marker"
    assert _tally(raw) == {}


def test_a_failed_tally_write_loses_the_tap_and_never_double_counts():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    raw.fail = {("update_item", R.PK_PREFIX)}
    resp = _tap(raw, table, call, "up", token=token)
    assert resp["statusCode"] == 503 and _body(resp)["recorded"] is False
    raw.fail = set()
    assert _tap(raw, table, call, "up")["statusCode"] == 409, "the marker stays: a retry is refused, not counted"
    assert _tally(raw) in ({}, {"up": 0}), "the lost tap is an under-count of one, never a count"
    assert not any(w[0] == "delete_item" for w in raw.writes)


# ── only a public, open, one-tap call ──────────────────────────────────────────────────────────────────


def test_only_a_public_open_direction_or_number_call_takes_a_tap():
    raw, table = _table()
    for row, status in ((PRIVATE_ROW, 404), (SEALED_ROW, 409)):
        assert _ask(table, _event(params={"call": _call_id(row)}), raw=raw)["statusCode"] == status
    for bad in ("sleep-pred_nope", "nosuchcoach-pred_x", "../etc", "x" * 300):
        assert _ask(table, _event(params={"call": bad}), raw=raw)["statusCode"] == 404, bad
    assert _body(_ask(table, _event(params={}), raw=raw)) == {"available": True}  # the bare probe the hook census reads
    # due today: the tally is frozen — the GET serves it, no token, and a POST with a genuine token is refused
    frozen_call = _call_id(DUE_TODAY_ROW)
    frozen = _body(_ask(table, _event(params={"call": frozen_call}), raw=raw))
    assert frozen["open"] is False and "token" not in frozen
    tok = _token_for_closed(frozen_call)
    resp = _ask(table, _event("POST", body={"call": frozen_call, "choice": "within", "token": tok}), now=NOW + 5, raw=raw)
    assert resp["statusCode"] == 409
    assert raw.reader_rows() == {}


def test_a_graded_call_shows_the_three_way_comparison_and_refuses_taps():
    raw, table = _table()
    call = _call_id(GRADED_ROW)
    raw.store[(R.PK_PREFIX + call, R.TALLY_SK_PREFIX + "up")] = {"pk": R.PK_PREFIX + call, "sk": "TALLY#up", "count": 3}
    raw.store[(R.PK_PREFIX + call, R.TALLY_SK_PREFIX + "down")] = {"pk": R.PK_PREFIX + call, "sk": "TALLY#down", "count": 5}
    view = _body(_ask(table, _event(params={"call": call}), raw=raw))
    assert view["open"] is False and "token" not in view
    assert view["graded"] == {"coach_status": "confirmed", "reading_side": "down"}
    assert view["tally"] == {"counts": {"up": 3, "down": 5, "same": 0}, "total": 8}
    tok = _token_for_closed(call)
    assert _ask(table, _event("POST", body={"call": call, "choice": "up", "token": tok}), now=NOW + 5, raw=raw)["statusCode"] == 409


def _token_for_closed(call):
    from common.client_ip import extract_client_ip, salted_ip_hash

    return R.mint_token(KEY, call, salted_ip_hash(extract_client_ip(_event())), NOW)


def test_the_fixture_rows_are_classified_as_the_tests_assume():
    """Each refusal above must be refused for the reason it names — not by accident of a malformed fixture."""
    from common import prediction_publication as PP

    for row in (DIR_ROW, NUM_ROW, GRADED_ROW, DUE_TODAY_ROW):
        assert PP.classify(row["pk"], row)[0] == PP.PUBLIC, row["claim_natural"]
        assert row["filing"]["verdict"] == "gradeable", row["claim_natural"]
    assert PP.classify(PRIVATE_ROW["pk"], PRIVATE_ROW)[0] == PP.PRIVATE
    assert PP.classify(SEALED_ROW["pk"], SEALED_ROW)[0] == PP.PUBLIC and SEALED_ROW["pre_registered"] is True
    assert (DIR_ROW["status"], NUM_ROW["status"], DUE_TODAY_ROW["status"], GRADED_ROW["status"]) == ("pending",) * 3 + ("confirmed",)


def test_the_reading_side_follows_the_graders_stored_fields():
    d, n = DIRECTION_SPEC, NUMBER_SPEC
    assert [R.reading_side(d, {"window": {"direction": x}}) for x in ("up", "down", "flat")] == ["up", "down", "same"]
    assert R.reading_side(d, {"actual_value": 0.2}) is None  # a legacy window-less grade names no side
    assert [R.reading_side(n, {"actual_value": v}) for v in (181.6, 181.5, 180, 178.5, 178.4)] == [
        "above",
        "within",
        "within",
        "within",
        "below",
    ]
    assert R.reading_side(n, {"actual_value": 3, "graded_as": "count"}) is None
    assert R.reading_side({"type": "machine", "threshold": 1}, {"actual_value": 2}) is None


# ── (b) the owner's record reads do not move ───────────────────────────────────────────────────────────


def _owner_reads(monkeypatch, table):
    from web import site_api_coach as coach_api, site_api_ledger_export as ledger

    monkeypatch.setattr(coach_api, "table", table)
    out = {}
    out["ledger_export"] = ledger.handle_ledger_export(
        {"queryStringParameters": {"size": "200"}}, fetch=lambda: ledger.fetch_rows(_table=table), today=TODAY
    )
    out["predictions"] = coach_api.handle_predictions({"queryStringParameters": {"status": "all"}})
    out["calibration"] = coach_api.handle_calibration({"queryStringParameters": {}})
    for name, resp in out.items():
        assert resp["statusCode"] == 200, (name, resp)
        body = json.loads(resp["body"])
        body.pop("_meta", None)  # served_at is the request instant, not content
        out[name] = json.dumps(body, sort_keys=True)
    return out


def test_owner_record_reads_are_identical_with_and_without_reader_rows(monkeypatch):
    _raw0, bare = _table()
    raw1, with_taps = _table()
    for i, choice in enumerate(("up", "down", "same", "down")):
        assert _tap(raw1, with_taps, _call_id(DIR_ROW), choice, ip=f"198.51.100.{i + 1}")["statusCode"] == 200
    assert _tap(raw1, with_taps, _call_id(NUM_ROW), "within")["statusCode"] == 200
    assert raw1.reader_rows(), "the comparison must actually carry reader rows"
    assert _owner_reads(monkeypatch, bare) == _owner_reads(monkeypatch, with_taps)
    # the control: the same comparison DOES see a row that lands in a coach's partition, so it is not blind
    raw2, touched = _table()
    extra = _row("His weight will rise over the next two weeks.", {**DIRECTION_SPEC, "condition": "up"})
    raw2.store[(extra["pk"], extra["sk"])] = extra
    assert _owner_reads(monkeypatch, bare) != _owner_reads(monkeypatch, touched)
