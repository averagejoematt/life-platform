"""#6088 / #6114 — "your call beside the coaches": the reader-call route and the owner's isolation line (ADR-169).

Owner rulings 2026-11-16: "These actions must not alter my own historical evidence, grading records or experiments."
Beside the route's behaviour this file carries the isolation proofs:

  (a) no branch of the route — success or any refusal or failure — writes a ``USER#matthew#…`` or ``COACH#…`` key:
      every request runs through ``_ask``, which checks the fake table's write log after EVERY request;
  (b) the ledger export, /api/predictions, /api/calibration and the calibration verification headline are
      byte-identical with and without reader rows (``test_owner_record_reads_are_identical_with_and_without_reader_rows``);
  (c) replay, concurrent duplicates and a changed choice from one identity move the count once;
  (d) an expired / forged / too-young / other-call / other-identity token and a filled honeypot write nothing;
  (e) a limiter error refuses, with no write.

The lock, the hidden split, the kill switch, the fuzzed door and eligibility are tests/test_reader_call_golive_6114.py.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from reader_call_support import (
    DIR_ROW,
    DIRECTION_SPEC,
    DUE_TODAY_ROW,
    GENESIS,
    GRADED_ROW,
    KEY,
    NOW,
    NUM_ROW,
    NUMBER_SPEC,
    PRIVATE_ROW,
    SEALED_ROW,
    TODAY,
    _ask,
    _body,
    _call_id,
    _event,
    _row,
    _table,
    _tally,
    _tap,
    _token,
)
from web import reader_call_rules as R, site_api_reader_call as rc


@pytest.fixture(autouse=True)
def _genesis(monkeypatch):
    from web import site_api_common

    monkeypatch.setattr(site_api_common, "EXPERIMENT_START", GENESIS)


def _strip_meta(d):
    return {k: v for k, v in d.items() if k != "_meta"}


# ── the switches ───────────────────────────────────────────────────────────────────────────────────────


def test_the_switch_is_committed_off_and_off_touches_nothing():
    assert R.READER_CALL_LIVE is False, "the master switch is committed OFF until the owner's go"
    raw, table = _table()
    reads = []
    for ev in (_event(params={"call": _call_id(DIR_ROW)}), _event("POST", body={"call": _call_id(DIR_ROW), "choice": "up"}), _event()):
        resp = rc.handle_reader_call(ev, table=table, now=NOW, today=TODAY, runtime=lambda: reads.append(1) or True)
        assert resp["statusCode"] == 404 and _body(resp)["error"] == rc.NOT_AVAILABLE
    assert raw.writes == [] and raw.reads == [], "off must not read, meter or write"
    assert reads == [], "with the committed switch off the runtime switch is not even read"


def test_the_route_is_mounted_for_get_and_post():
    from web import site_api_lambda as router

    assert router._SIMPLE_ROUTES["/api/reader_call"] == ({"GET", "POST"}, rc.handle_reader_call)
    assert "/api/reader_call" in router.ROUTES


# ── a call, end to end ─────────────────────────────────────────────────────────────────────────────────


def test_a_call_is_recorded_and_no_count_or_split_is_served_while_open():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    view = _body(_ask(table, _event(params={"call": call}), raw=raw))
    assert view["open"] is True and view["kind"] == "direction"
    assert view["question"] == "From 14 November to 28 November, will the weight go up, go down, or stay about the same?"
    assert [c["id"] for c in view["choices"]] == ["up", "down", "same"]
    assert view["closes_on_words"] == "28 November" and view["your_call"] is None
    for hidden in ("reader_calls", "graded", "coach_choice"):
        assert hidden not in view, f"{hidden} must not be served while the call is open"
    assert view["copy"] == R.COPY and "reader calls" in view["note"]
    resp = _tap(raw, table, call, "same")
    out = _strip_meta(_body(resp))
    assert resp["statusCode"] == 200 and out == {
        "recorded": True,
        "call": call,
        "your_call": "same",
        "closes_on": "2026-11-28",
        "closes_on_words": "28 November",
        "result_due_words": "12 December",  # closes when the window ends (28 Nov); graded from the due day (12 Dec)
    }
    again = _body(_ask(table, _event(params={"call": call}), raw=raw))
    assert again["your_call"] == "same" and "token" not in again and "reader_calls" not in again
    marker = next(v for (p, s), v in raw.reader_rows().items() if s.startswith(R.TAP_SK_PREFIX))
    assert set(marker) == {"pk", "sk", "choice", "tapped_at", "ttl"}, "the marker stores the reader's own choice, no address, no text"
    assert marker["pk"] == R.PK_PREFIX + call and call.startswith("sleep:")  # keyed by the public item id
    # due 2026-12-12 → TTL is the end of that day + the grace (2026-12-13T00:00Z = 1797120000)
    assert marker["ttl"] == 1_797_120_000 + R.DEDUP_GRACE_S
    assert _tally(raw) == {"same": 1}


def test_a_number_call_asks_about_its_own_level_on_its_target_day():
    raw, table = _table()
    view = _body(_ask(table, _event(params={"call": _call_id(NUM_ROW)}), raw=raw))
    assert view["kind"] == "number"
    assert view["question"] == "On 30 November, will the weight be above, within 1.5 of, or below 180 lb?"
    assert [c["label"] for c in view["choices"]] == [
        "Above 180 lb by more than 1.5",
        "Within 1.5 of 180 lb",
        "Below 180 lb by more than 1.5",
    ]
    assert _tap(raw, table, _call_id(NUM_ROW), "below")["statusCode"] == 200
    assert _tap(raw, table, _call_id(NUM_ROW), "sideways", ip="198.51.100.9")["statusCode"] == 400


# ── (c) one identity moves the count once ──────────────────────────────────────────────────────────────


def test_replay_concurrency_a_changed_choice_and_one_ipv6_64_move_the_count_once():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    assert _tap(raw, table, call, "up", token=token)["statusCode"] == 200
    assert _tap(raw, table, call, "up", token=token)["statusCode"] == 409  # replay of the same token
    assert _tap(raw, table, call, "down", token=token)["statusCode"] == 409  # a changed choice
    assert _tap(raw, table, call, "down", ip="[2001:db8:1:2::a]")["statusCode"] == 200
    tok64 = R.mint_token(KEY, call, _salted("[2001:db8:1:2::ffff]"), NOW)
    assert _tap(raw, table, call, "down", ip="[2001:db8:1:2::ffff]", token=tok64)["statusCode"] == 409  # same /64
    tok = _token(raw, table, call, ip="198.51.100.20")
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _i: _tap(raw, table, call, "same", ip="198.51.100.20", token=tok)["statusCode"], range(8)))
    assert sorted(codes) == [200] + [409] * 7
    assert _tally(raw) == {"up": 1, "down": 1, "same": 1}


def _salted(ip):
    from common.client_ip import extract_client_ip, salted_ip_hash

    return salted_ip_hash(extract_client_ip(_event(ip=ip)))


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
    before = len(raw.writes)
    for name, kw in cases.items():
        assert _tap(raw, table, call, "up", **kw)["statusCode"] == 403, name
    assert _tap(raw, table, call, "up", hp="https://spam.example")["statusCode"] == 400
    assert [w for w in raw.writes[before:] if w[1].startswith(R.PK_PREFIX)] == []
    assert _tally(raw) == {}


def test_the_token_rules_are_pure_and_bound_to_call_identity_and_instant():
    t = R.mint_token(KEY, "sleep:p1", "abc", NOW)
    assert R.check_token(KEY, t, "sleep:p1", "abc", NOW + R.TOKEN_MIN_AGE_S) is None
    assert R.check_token(KEY, t, "sleep:p1", "abc", NOW + R.TOKEN_MAX_AGE_S) is None
    assert R.check_token(KEY, t, "sleep:p1", "abc", NOW + R.TOKEN_MIN_AGE_S - 1) == "too_young"
    assert R.check_token(KEY, t, "sleep:p1", "abc", NOW + R.TOKEN_MAX_AGE_S + 1) == "expired"
    assert R.check_token(KEY, t, "sleep:p2", "abc", NOW + 5) == "forged"
    assert R.check_token(KEY, t, "sleep:p1", "abd", NOW + 5) == "forged"
    assert R.check_token(b"x" * 32, t, "sleep:p1", "abc", NOW + 5) == "forged"
    issued, mac = t.split(".")
    assert R.check_token(KEY, f"{int(issued) - 100}.{mac}", "sleep:p1", "abc", NOW + 5) == "forged"


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


def test_a_failed_count_write_loses_the_tap_and_never_double_counts():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    token = _token(raw, table, call)
    raw.fail = {("update_item", R.PK_PREFIX)}
    resp = _tap(raw, table, call, "up", token=token)
    assert resp["statusCode"] == 503 and _body(resp)["recorded"] is False
    raw.fail = set()
    assert _tap(raw, table, call, "up", token=R.mint_token(KEY, call, _salted("203.0.113.7"), NOW))["statusCode"] == 409
    assert _tally(raw) in ({}, {"up": 0}), "the lost tap is an under-count of one, never a count"
    assert not any(w[0] == "delete_item" for w in raw.writes)


# ── only an eligible call ──────────────────────────────────────────────────────────────────────────────


def test_only_a_public_eligible_call_is_served():
    raw, table = _table()
    for row, status in ((PRIVATE_ROW, 404), (SEALED_ROW, 409)):
        assert _ask(table, _event(params={"call": _call_id(row)}), raw=raw)["statusCode"] == status
    for bad in ("sleep:pred_nope", "nosuchcoach:pred_x", "../etc", "x" * 300, "sleep-" + DIR_ROW["prediction_id"]):
        assert _ask(table, _event(params={"call": bad}), raw=raw)["statusCode"] == 404, bad
    bare = _body(_ask(table, _event(params={}), raw=raw))
    assert _strip_meta(bare) == {"available": True}  # the bare probe the hook census reads
    assert raw.reader_rows() == {}


def test_a_graded_call_shows_the_three_way_comparison_and_refuses_taps():
    raw, table = _table()
    call = _call_id(GRADED_ROW)
    raw.store[(R.PK_PREFIX + call, R.TALLY_SK_PREFIX + "up")] = {"pk": R.PK_PREFIX + call, "sk": "TALLY#up", "count": 3}
    raw.store[(R.PK_PREFIX + call, R.TALLY_SK_PREFIX + "down")] = {"pk": R.PK_PREFIX + call, "sk": "TALLY#down", "count": 5}
    view = _body(_ask(table, _event(params={"call": call}), raw=raw))
    assert view["open"] is False and "token" not in view
    assert view["graded"] == {"coach_status": "confirmed", "coach_choice": "down", "reading_side": "down"}
    assert view["reader_calls"] == {"counts": {"up": 3, "down": 5, "same": 0}, "total": 8}
    tok = R.mint_token(KEY, call, _salted("203.0.113.7"), NOW)
    assert _ask(table, _event("POST", body={"call": call, "choice": "up", "token": tok}), now=NOW + 5, raw=raw)["statusCode"] == 409


def test_the_fixture_rows_are_classified_as_the_tests_assume():
    """Each refusal above must be refused for the reason it names — not by accident of a malformed fixture."""
    from common import prediction_publication as PP

    for row in (DIR_ROW, NUM_ROW, GRADED_ROW, DUE_TODAY_ROW):
        assert PP.classify(row["pk"], row)[0] == PP.PUBLIC, row["claim_natural"]
        assert row["filing"]["verdict"] == "gradeable", row["claim_natural"]
    assert PP.classify(PRIVATE_ROW["pk"], PRIVATE_ROW)[0] == PP.PRIVATE
    assert PP.classify(SEALED_ROW["pk"], SEALED_ROW)[0] == PP.PUBLIC and SEALED_ROW["pre_registered"] is True


def test_the_reading_side_follows_the_graders_stored_fields():
    d, n = DIRECTION_SPEC, NUMBER_SPEC
    assert [R.reading_side(d, {"window": {"direction": x}}) for x in ("up", "down", "flat")] == ["up", "down", "same"]
    assert R.reading_side(d, {"actual_value": 0.2}) is None
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
    from web import site_api_coach as coach_api, site_api_coach_ledger as ledger_mod, site_api_ledger_export as ledger, verification_fields

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
        out[name] = json.dumps(body, sort_keys=True, default=str)
    # the calibration headline function itself, over the same table (owner 2026-11-16: never enters the record)
    g = {
        "table": table,
        "_parallel_fetch": ledger_mod._parallel_fetch,
        "_query_partition": ledger_mod._query_partition,
        "EXPERIMENT_START": GENESIS,
    }
    jobs = {
        cid: (lambda pk=f"COACH#{full}": ledger_mod._query_partition(pk, "PREDICTION#", None, paginate=True, _g=g))
        for cid, full in ledger_mod._CALIB_COACH_ID_MAP.items()
    }
    fetched, headline = verification_fields.fetch_with_headline(jobs, ledger_mod._CALIB_COACH_ID_MAP, g)
    out["headline"] = json.dumps({"fetched": fetched, "headline": headline}, sort_keys=True, default=str)
    return out


def test_owner_record_reads_are_identical_with_and_without_reader_rows(monkeypatch):
    _raw0, bare = _table()
    raw1, with_calls = _table()
    for i, choice in enumerate(("up", "down", "same", "down")):
        assert _tap(raw1, with_calls, _call_id(DIR_ROW), choice, ip=f"198.51.100.{i + 1}")["statusCode"] == 200
    assert _tap(raw1, with_calls, _call_id(NUM_ROW), "within")["statusCode"] == 200
    assert raw1.reader_rows(), "the comparison must actually carry reader rows"
    assert _owner_reads(monkeypatch, bare) == _owner_reads(monkeypatch, with_calls)
    # the control: the same comparison DOES see a row that lands in a coach's partition, so it is not blind
    raw2, touched = _table()
    extra = _row("His weight will rise over the next two weeks.", {**DIRECTION_SPEC, "condition": "up"})
    raw2.store[(extra["pk"], extra["sk"])] = extra
    a, b = _owner_reads(monkeypatch, bare), _owner_reads(monkeypatch, touched)
    assert a["ledger_export"] != b["ledger_export"] and a["headline"] != b["headline"]
