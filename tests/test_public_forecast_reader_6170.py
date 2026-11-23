"""#6170 — a reader can make a call against a RULES-BASED PLATFORM FORECAST (owner ruling 2026-11-22 §5).

The forecast partition (``USER#matthew#SOURCE#public_forecast``, #6156) becomes a valid reader-call target through the
SAME door (``/api/reader_call``) as a coach's call, addressed ``forecast:<prediction id>``. The owner's conditions, each
proved here on the real door over the governed ``PublicationTable``:

  * labelling — every reader-facing string says "rules-based platform forecast" and never "coach"; the row is never a
    coach's record, and never counted in any coach record or calibration total (the owner's record reads are
    byte-identical with and without forecast rows AND reader calls on them);
  * every existing control, unchanged, on the new target: the committed + runtime kill switch (SSM
    /life-platform/reader-call), the per-network meter (fail closed), the timing token bound to the call, the honeypot,
    the closing window (the midpoint rule) and the outcome lock, replay/dedup, isolation of reader rows (nothing written
    under ``USER#`` or ``COACH#`` — the forecast row itself included), and publication (a forecast the policy keeps
    private, i.e. every one while the stream is dark, is indistinguishable from a missing call);
  * the read route ``/api/platform_forecasts`` serves the same forecasts, empty while dark.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from coach import coach_record, public_forecast as F
from common import prediction_publication as PP, public_forecast_policy as FP
from reader_call_support import (
    DIR_ROW,
    GENESIS,
    KEY,
    NOW,
    TODAY,
    _ask,
    _body,
    _call_id,
    _event,
    _is_shut,
    _table,
    _tally,
    _tap,
    _token,
)
from test_reader_call_6088 import _owner_reads, _salted
from web import reader_call_rules as R, site_api_reader_call as rc

FILED = "2026-11-16"  # = reader_call_support.TODAY: filed this morning, target 23 November


def _payload(end, n=30):
    from datetime import datetime, timedelta

    e = datetime.strptime(end, "%Y-%m-%d")
    days = [
        {"date": (e - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d"), "value": 300.0 - 0.5 * i + (0.4 if i % 2 else -0.4), "present": True}
        for i in range(n)
    ]
    for d in days:
        d["gap"] = False
    return {"metric": "weight_lbs", "unit": "lb", "source_id": "withings", "as_of": end, "days": days}


def _forecast_row(filed=FILED, **extra):
    row, why = F.build("weight_trend", filed, _payload(F._day(filed, -1)), "https://example.invalid/api/series", filed, phase_stamp=False)
    assert why is None, why
    row = json.loads(json.dumps(row, default=float))  # plain numbers: the copy the assertions do arithmetic on
    row.update(extra)
    return row


def _wire(row):
    """The row as boto3's resource API hands it back: EVERY number a ``Decimal`` (never an int or a float). The table
    the routes read holds this form — a plain-number fixture is what let the first live row 500 the list (2026-11-23)."""
    return json.loads(json.dumps(row), parse_float=Decimal, parse_int=Decimal)


ROW = _forecast_row()
CALL = f"{FP.READER_SHORT}:{ROW['prediction_id']}"
GRADED = _forecast_row(
    "2026-10-26",
    status="confirmed",
    outcome_date="2026-11-02",
    outcome_notes=json.dumps({"actual_value": ROW["evaluation"]["threshold"] - 30.0}),
)
GRADED_CALL = f"{FP.READER_SHORT}:{GRADED['prediction_id']}"


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    from web import site_api_common

    monkeypatch.setattr(site_api_common, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(FP, "STREAM_LIVE", True)  # the publication gate lets the forecasts out (tests of dark set it back)


def _tables(*extra):
    from reader_call_support import ALL_ROWS

    return _table(rows=(*ALL_ROWS, _wire(ROW), _wire(GRADED), *(_wire(r) for r in extra)))


# ── the target and its label ───────────────────────────────────────────────────────────────────────────


def test_the_item_id_never_names_a_coach_and_the_literals_agree():
    from coach.prediction_point_grader import HEAD_TO_HEAD
    from web.site_api_coach_ledger import _CALIB_COACH_NAMES

    assert FP.READER_SHORT not in _CALIB_COACH_NAMES and FP.READER_SHORT not in coach_record.__dict__.get("COACH_IDS", ())
    assert R.HEAD_TO_HEAD == HEAD_TO_HEAD == FP.SCORING_RULE
    assert R.ITEM_ID_RE.match(CALL) and rc._short_and_pid(CALL) == (FP.READER_SHORT, ROW["prediction_id"])
    assert rc._short_and_pid(f"{FP.READER_SHORT}:pred_x_some_words") is None, "only the producer's id shape"


def test_an_open_forecast_asks_its_own_question_in_the_machine_voice():
    raw, table = _tables()
    view = _body(_ask(table, _event(params={"call": CALL}), raw=raw))
    spec = ROW["evaluation"]
    f, g = R._fmt(spec["threshold"]), R._fmt(spec["baseline_value"])
    assert view["available"] is True and view["kind"] == R.CLOSER and view["open"] is True
    assert view["question"] == (
        f"On 23 November, will the weight be closer to the forecast's {f} lb, or to {g} lb, where it stood before the forecast was made?"
    )
    assert [c["id"] for c in view["choices"]] == ["forecast", "no_change"]
    assert view["author"] == FP.RECORD and view["author_words"] == "Rules-based platform forecast"
    assert view["open_until"] == "2026-11-19" and view["result_due"] == "2026-11-23" and view["token"]
    words = json.dumps({k: v for k, v in view.items() if k != "token"}).lower()
    assert "coach" not in words, "a platform forecast is never attributed to a coach"
    for hidden in ("reader_calls", "graded"):
        assert hidden not in view
    resp = _tap(raw, table, CALL, "forecast")
    assert resp["statusCode"] == 200 and _body(resp)["your_call"] == "forecast"
    assert _tally(raw) == {"forecast": 1}
    assert raw.store[(ROW["pk"], ROW["sk"])] == _wire(ROW), "a reader's call never touches the forecast row"


def test_a_coach_calls_view_is_unchanged_by_the_forecast_target():
    raw, table = _tables()
    view = _body(_ask(table, _event(params={"call": _call_id(DIR_ROW)}), raw=raw))
    assert "author" not in view and "author_words" not in view and view["copy"] == R.COPY


# ── every existing control, on the new target ──────────────────────────────────────────────────────────


def test_the_kill_switch_shuts_the_forecast_target_before_any_read_or_write():
    raw, table = _tables()
    for ev in (_event(params={"call": CALL}), _event("POST", body={"call": CALL, "choice": "forecast"})):
        assert _is_shut(rc.handle_reader_call(ev, table=table, live=False, now=NOW, today=TODAY, runtime=lambda: True), ev)
        assert _is_shut(rc.handle_reader_call(ev, table=table, now=NOW, today=TODAY, runtime=lambda: False), ev)
    assert raw.writes == [] and raw.reads == []
    assert rc.SWITCH_PARAM == "/life-platform/reader-call", "the one kill switch covers both targets"


def test_the_meter_limits_one_network_and_a_limiter_error_refuses_on_the_forecast_target():
    raw, table = _tables()
    codes = [_ask(table, _event("POST", body={"call": CALL}), raw=raw)["statusCode"] for _ in range(rc.TAP_LIMIT_PER_HOUR + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {403}
    raw2, table2 = _tables()
    token = _token(raw2, table2, CALL)
    raw2.fail = {("update_item", "RATE#")}
    assert _ask(table2, _event(params={"call": CALL}), raw=raw2)["statusCode"] == 429
    assert _tap(raw2, table2, CALL, "forecast", token=token)["statusCode"] == 429
    assert raw2.reader_rows() == {}


def test_the_edge_rate_rule_covers_the_one_door_both_targets_use():
    import importlib.util
    import os

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cdk", "stacks", "web_edge_rate_rule.py")
    spec = importlib.util.spec_from_file_location("web_edge_rate_rule_6170", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "/api/reader_call" in mod.SITE_API_READER_POSTS
    from web import site_api_lambda as router

    assert router._SIMPLE_ROUTES["/api/platform_forecasts"][0] == {"GET"}, "the forecast list is read-only: no new write door"


def test_tokens_replay_and_honeypot_on_the_forecast_target():
    raw, table = _tables()
    coach_token = _token(raw, table, _call_id(DIR_ROW))
    assert _tap(raw, table, CALL, "forecast", token=coach_token)["statusCode"] == 403, "a token is bound to its call"
    assert _tap(raw, table, CALL, "forecast", hp="https://spam.example")["statusCode"] == 400
    assert _tap(raw, table, CALL, "sideways")["statusCode"] == 400
    token = _token(raw, table, CALL)
    assert _tap(raw, table, CALL, "no_change", token=token)["statusCode"] == 200
    assert _tap(raw, table, CALL, "no_change", token=token)["statusCode"] == 409, "a replay moves nothing"
    assert _tap(raw, table, CALL, "forecast", token=token)["statusCode"] == 409, "nor does a changed choice"
    assert _tally(raw) == {"no_change": 1}


def test_the_closing_window_and_the_outcome_lock_hold_on_the_forecast_target():
    raw, table = _tables()
    token = _token(raw, table, CALL)
    assert _tap(raw, table, CALL, "forecast", token=token, today="2026-11-20")["statusCode"] == 409, "after the last open day"
    late = _body(_ask(table, _event(params={"call": CALL}), today="2026-11-20", raw=raw))
    assert late["open"] is False and "token" not in late
    with_outcome = dict(ROW, outcome_value=280.0)  # pending, but an outcome field exists: closed whatever the status says
    raw2, table2 = _table(rows=(with_outcome,))
    assert _body(_ask(table2, _event(params={"call": CALL}), raw=raw2))["open"] is False
    assert _tally(raw) == {} and _tally(raw2) == {}


def test_a_graded_forecast_shows_the_forecast_the_guess_and_the_reader_calls_and_refuses_taps():
    raw, table = _tables()
    view = _body(_ask(table, _event(params={"call": GRADED_CALL}), raw=raw))
    assert view["open"] is False and "token" not in view
    assert view["graded"] == {"forecast_status": "confirmed", "forecast_choice": "forecast", "reading_side": "forecast"}
    assert view["reader_calls"] == {"counts": {"forecast": 0, "no_change": 0}, "total": 0}
    tok = R.mint_token(KEY, GRADED_CALL, _salted("203.0.113.7"), NOW)
    assert (
        _ask(table, _event("POST", body={"call": GRADED_CALL, "choice": "forecast", "token": tok}), now=NOW + 5, raw=raw)["statusCode"]
        == 409
    )


def test_a_private_forecast_reads_as_a_missing_call_and_the_list_is_empty(monkeypatch):
    """While the stream is dark the publication policy keeps EVERY forecast private: the door cannot tell it from a
    missing call, and /api/platform_forecasts serves nothing."""
    monkeypatch.setattr(FP, "STREAM_LIVE", False)
    assert PP.classify(ROW["pk"], ROW) == (PP.PRIVATE, FP.DARK_REASON)
    raw, table = _tables()
    ev = _event(params={"call": CALL})
    assert _is_shut(_ask(table, ev, raw=raw), ev)
    tok = R.mint_token(KEY, CALL, _salted("203.0.113.7"), NOW)
    assert _ask(table, _event("POST", body={"call": CALL, "choice": "forecast", "token": tok}), now=NOW + 5, raw=raw)["statusCode"] == 404
    assert raw.reader_rows() == {}
    assert _list(table)["forecasts"] == []


def test_a_forecast_shaped_row_anywhere_else_is_not_a_target():
    """Only the forecast partition's own row: a coach-partition row, or one missing the record/source fields, is refused."""
    raw, table = _table(rows=(dict(ROW, record="coach"),))
    ev = _event(params={"call": CALL})
    assert _is_shut(_ask(table, ev, raw=raw), ev)
    raw, table = _table(rows=(dict(ROW, coach_id="sleep_coach"),))
    assert _is_shut(_ask(table, ev, raw=raw), ev)


# ── the owner's record does not move ───────────────────────────────────────────────────────────────────


def test_owner_record_reads_are_identical_with_forecast_rows_and_reader_calls_on_them(monkeypatch):
    """Not in any coach's record, not in /api/predictions, not in /api/calibration, not in the calibration headline:
    byte-identical with and without the forecast rows AND the reader calls made on them."""
    from reader_call_support import ALL_ROWS

    _r0, bare = _table(rows=ALL_ROWS)
    raw1, with_forecasts = _tables()
    assert _tap(raw1, with_forecasts, CALL, "forecast")["statusCode"] == 200
    assert raw1.reader_rows() and any(k[0] == FP.FORECAST_PK for k in raw1.store)
    assert _owner_reads(monkeypatch, bare) == _owner_reads(monkeypatch, with_forecasts)


def test_the_coach_versus_guess_sample_never_sees_a_forecast_row():
    """coach_baseline's per-coach record (the coaches-versus-guess sample) reads COACH# partitions only."""
    from coach import coach_baseline
    from reader_call_support import ALL_ROWS

    raw0, _t0 = _table(rows=ALL_ROWS)
    raw1, _t1 = _table(rows=(*ALL_ROWS, ROW, GRADED))
    for short in ("sleep",):
        a = coach_baseline.for_coach(raw0, f"{short}_coach", genesis=GENESIS)
        b = coach_baseline.for_coach(raw1, f"{short}_coach", genesis=GENESIS)
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert not any(pk == FP.FORECAST_PK for op, pk in raw1.reads), "the coach record never reads the forecast partition"


# ── the read route ─────────────────────────────────────────────────────────────────────────────────────


def _list(table):
    from web.site_api_platform_forecasts import handle_platform_forecasts

    resp = handle_platform_forecasts({}, table=table, today=TODAY)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_the_route_serves_each_forecast_labelled_with_its_guess_and_never_a_coach():
    from web.site_api_platform_forecasts import FIELDS

    raw, table = _tables()
    body = _list(table)
    got = {f["id"]: f for f in body["forecasts"]}
    assert set(got) == {ROW["prediction_id"], GRADED["prediction_id"]}
    f = got[ROW["prediction_id"]]
    assert tuple(f) == FIELDS
    assert f["call"] == CALL and f["label"] == "rules-based platform forecast" and f["author_words"] == "Rules-based platform forecast"
    assert f["forecast"] == ROW["evaluation"]["threshold"] and f["guess"]["value"] == ROW["evaluation"]["baseline_value"]
    assert f["scoring"]["rule"] == FP.SCORING_RULE and f["reader_calls_close"] == "2026-11-19" and f["graded"] is None
    assert got[GRADED["prediction_id"]]["graded"]["reading_side"] == "forecast"
    assert "coach" not in json.dumps(body).lower()
    assert raw.writes == [] and {pk for _op, pk in raw.reads} == {FP.FORECAST_PK}, "one partition, read only"


def _decimals(v, path=""):
    if isinstance(v, dict):
        return [p for k, x in v.items() for p in _decimals(x, f"{path}.{k}")]
    if isinstance(v, list):
        return [p for i, x in enumerate(v) for p in _decimals(x, f"{path}[{i}]")]
    return [path] if isinstance(v, Decimal) else []


def test_a_row_typed_as_dynamodb_returns_it_is_served_as_json_with_whole_numbers_whole():
    """Regression, 2026-11-23: the first live forecast row made the route answer 500 ("Object of type Decimal is not
    JSON serializable") — ``rule.version``, ``scoring.version`` and ``inputs.n`` left as the row's own ``Decimal``.
    Mutation run: with ``_int`` returning its argument unchanged this test fails at ``json.dumps``."""
    from web.site_api_platform_forecasts import served

    graded = _wire(dict(GRADED, outcome_notes={"actual_value": ROW["evaluation"]["threshold"] - 30.0}))  # notes as a map
    wire = _wire(ROW)
    for path in (".model.version", ".evaluation.scoring_version", ".lineage.n", ".evaluation.threshold", ".evaluation.baseline_value"):
        assert path in _decimals(wire), f"the fixture is not the wire: {path} is not a Decimal"
    for row in (wire, graded):
        f = served(row, GENESIS)
        assert f is not None and _decimals(f) == []
        assert json.loads(json.dumps(f)) == f, "the served shape is plain JSON"
        for whole in (f["rule"]["version"], f["scoring"]["version"], f["inputs"]["n"]):
            assert type(whole) is int, "a version or a count is a JSON integer (the page prints it as written)"
        for measured in (f["forecast"], f["guess"]["value"]):
            assert type(measured) is float
    f = served(wire, GENESIS)
    assert (f["rule"]["version"], f["scoring"]["version"], f["inputs"]["n"]) == (
        ROW["model"]["version"],
        ROW["evaluation"]["scoring_version"],
        ROW["lineage"]["n"],
    )
    assert f == served(ROW, GENESIS), "the same row in plain numbers serves the same shape"
    g = served(graded, GENESIS)["graded"]
    assert type(g["actual"]) is float and g["reading_side"] == "forecast"
    for bad in (Decimal("1.5"), Decimal("NaN"), True, "1", None):
        assert served(dict(wire, lineage=dict(wire["lineage"], n=bad)), GENESIS)["inputs"]["n"] is None, "never a rounded count"


def test_the_route_never_serves_a_coach_partition_row_or_a_row_that_is_not_the_forecasts_own():
    raw, table = _table(rows=(dict(ROW, pk="COACH#sleep_coach"),))
    assert _list(table)["forecasts"] == []
    raw, table = _table(rows=(dict(ROW, coach_id="sleep_coach"), dict(GRADED, record="coach")))
    assert _list(table)["forecasts"] == [], "only the forecast partition's own rows (coach_id empty, its own record)"
