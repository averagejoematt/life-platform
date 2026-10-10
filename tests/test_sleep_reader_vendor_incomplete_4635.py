"""#4635 (reader half) — the site's sleep reader reads Eight Sleep's `vendor_incomplete`.

PR #4666 made the Eight Sleep writer store the vendor's `incomplete` flag as
`vendor_incomplete` (True OR False as sent; absent on pre-#4635 rows = unknown).
`/api/sleep_detail` and `/api/sleep_correlations` still averaged every stored night,
so a night the vendor called "not final" (a provisional score; in 1 of 9 measured
cases a genuinely short record) counted as a full night's measurement.

The reader now follows the site's partial-day rule (#1084: a day that is not final
never enters a mean) and the per-row label precedent (circadian `measured`):
  - flagged True  -> left out of every average and correlation series; still in the
                     trend, labelled; the headline says when it is provisional.
  - False/absent  -> exactly today's behaviour (included, unlabelled).

The stored rows below are built by the REAL writer from the archived wire fixture
(`tests/fixtures/eightsleep_wire_4635.json`, the same night sent flagged then
unflagged) — the fixture is the wire, not an invented row shape. Every expected
number is counted by hand from those rows.
"""

from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from ingestion import eightsleep_lambda as es  # noqa: E402
from web import site_api_sleep as sleep_mod, site_api_vitals as vitals  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "eightsleep_wire_4635.json"), encoding="utf-8") as _fh:
    _WIRE = json.load(_fh)


def _wire_night():
    days = {d["day"] for d in _WIRE["flagged_fetch"]["raw"]["trends"]["days"]}
    nxt = {d["day"] for d in _WIRE["next_day_fetch"]["raw"]["trends"]["days"]}
    both = sorted(days & nxt)
    for day in both:
        a = next(d for d in _WIRE["flagged_fetch"]["raw"]["trends"]["days"] if d["day"] == day)
        if a.get("incomplete") is True:
            return day
    raise AssertionError("fixture no longer carries a flagged night sent twice")


_NIGHT = _wire_night()


def _stored(fetch, as_date):
    """The real writer's stored row for the fixture night, keyed at `as_date`."""
    rec = es.transform(copy.deepcopy(_WIRE[fetch]["raw"]), _NIGHT)[0]
    rec = dict(rec)
    rec["pk"] = "USER#matthew#SOURCE#eightsleep"
    rec["sk"] = f"DATE#{as_date}"
    rec["date"] = as_date
    return rec


# Three nights: an unflagged one (vendor said final), a pre-#4635 one (no flag at all),
# and — the latest — a flagged one (vendor said not final).
_FINAL = _stored("next_day_fetch", "2026-09-28")  # vendor_incomplete False, score 78
_OLD = {k: v for k, v in _stored("next_day_fetch", "2026-09-29").items() if k != "vendor_incomplete"}
_OLD["sleep_score"] = 70.0  # a distinct score so the average shows which rows it counted
_FLAGGED = _stored("flagged_fetch", "2026-09-30")  # vendor_incomplete True, provisional score 85


def _install(monkeypatch, eight_rows, extra=None):
    extra = extra or {}

    def fake(source, start, end, include_pilot=False):
        if source == "eightsleep":
            return [dict(r) for r in eight_rows]
        return list(extra.get(source, []))

    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-09-01")
    monkeypatch.setattr(vitals, "_query_source", fake)


def _detail(monkeypatch, rows):
    _install(monkeypatch, rows)
    resp = vitals.handle_sleep_detail()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def test_the_premise_flagged_unflagged_and_unknown_rows():
    assert _FLAGGED["vendor_incomplete"] is True and _FLAGGED["sleep_score"] == 85.0
    assert _FINAL["vendor_incomplete"] is False and _FINAL["sleep_score"] == 78.0
    assert "vendor_incomplete" not in _OLD
    assert sleep_mod._vendor_incomplete(_FLAGGED) is True
    assert sleep_mod._vendor_incomplete(_FINAL) is False
    assert sleep_mod._vendor_incomplete(_OLD) is None
    # A non-boolean is not a vendor statement — unknown, never coerced.
    assert sleep_mod._vendor_incomplete({"vendor_incomplete": "true"}) is None


def test_a_flagged_night_is_left_out_of_the_averages_and_says_so(monkeypatch):
    body = _detail(monkeypatch, [_FINAL, _OLD, _FLAGGED])
    sd = body["sleep_detail"]
    # Averages over the final + unknown nights only: (78 + 70) / 2 = 74.0, not (78+70+85)/3.
    assert sd["avg_score_window"] == 74.0
    eff = [_FINAL["sleep_efficiency_pct"], _OLD["sleep_efficiency_pct"]]
    assert sd["avg_efficiency_window"] == round(sum(eff) / 2, 1)
    assert sd["avg_window_nights"] == 2
    assert sd["nights_vendor_incomplete"] == 1
    assert sd["days_tracked"] == 3, "days_tracked still counts every stored night"
    # The latest (headline) night is the flagged one: it stays, labelled provisional.
    assert sd["as_of_date"] == "2026-09-30"
    assert sd["sleep_score"] == 85.0
    assert sd["vendor_incomplete"] is True
    assert sd["eightsleep"]["vendor_incomplete"] is True
    assert "provisional" in (sd["figure_scope"]["vendor_incomplete_note"] or "")


def test_the_trend_keeps_every_night_with_its_own_flag(monkeypatch):
    body = _detail(monkeypatch, [_FINAL, _OLD, _FLAGGED])
    flags = {row["date"]: row["eightsleep"]["vendor_incomplete"] for row in body["sleep_trend"]}
    assert flags == {"2026-09-28": False, "2026-09-29": None, "2026-09-30": True}


def test_rows_without_the_flag_behave_exactly_as_before(monkeypatch):
    """Old rows lack the flag: unknown, included, unlabelled — today's numbers."""
    old_a = dict(_OLD, sk="DATE#2026-09-28", date="2026-09-28", sleep_score=60.0)
    old_b = dict(_OLD, sk="DATE#2026-09-29", date="2026-09-29", sleep_score=80.0)
    body = _detail(monkeypatch, [old_a, old_b])
    sd = body["sleep_detail"]
    assert sd["avg_score_window"] == 70.0
    assert sd["avg_window_nights"] == 2 and sd["nights_vendor_incomplete"] == 0
    assert sd["vendor_incomplete"] is None
    assert sd["figure_scope"]["vendor_incomplete_note"] is None


def test_an_unflagged_latest_night_carries_no_provisional_note(monkeypatch):
    body = _detail(monkeypatch, [_FLAGGED, dict(_FINAL, sk="DATE#2026-10-01", date="2026-10-01")])
    sd = body["sleep_detail"]
    assert sd["vendor_incomplete"] is False
    assert sd["figure_scope"]["vendor_incomplete_note"] is None
    assert sd["avg_score_window"] == 78.0 and sd["nights_vendor_incomplete"] == 1


def test_a_flagged_night_is_left_out_of_the_correlation_series(monkeypatch):
    """B1 pairs Todoist load with the night's score — the flagged night's provisional
    score must not be one of the pairs; the final and unknown nights still are."""
    todoist = [{"sk": f"DATE#{d}", "date": d, "completed_count": 5} for d in ("2026-09-28", "2026-09-29", "2026-09-30")]
    _install(monkeypatch, [_FINAL, _OLD, _FLAGGED], extra={"todoist": todoist})
    body = json.loads(vitals.handle_sleep_correlations()["body"])
    b1 = next(c for c in body["cards"] if c["id"] == "B1")
    assert b1["n"] == 2, b1
