"""tests/test_titration_band_description_5099.py — the Habitify calorie-band habit's description follows the band (#5099).

The weekly titration (`mcp/titration_leg.py`) rewrites the description of the Habitify habit carrying the
`calories_in_band` core flag when the week it just wrote has a different band from the previous stored week, and only
then. Every number here is synthetic. The HTTP call is stubbed: nothing leaves the process. No clock is read.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
from urllib.error import HTTPError

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import band_description as bd  # noqa: E402

WEEK = "2026-11-02"
HID = "SYNTHETIC-HABIT-ID-1"
REGISTRY = {
    "Synthetic band habit": {"status": "active", "core": bd.CORE_ID, "habitify_id": HID},
    "Synthetic other habit": {"status": "active", "core": "weigh_in", "habitify_id": "SYNTHETIC-HABIT-ID-2"},
}


def rec(lo, hi, week="2026-10-26"):
    return {"week": week, "band_low": lo, "band_high": hi}


# ── the pure parts ────────────────────────────────────────────────────────────────────────
def test_the_text_is_the_owners_template_rendered_from_the_record():
    assert bd.render(1400, 1600, "2026-10-26") == (
        "1,400–1,600 kcal this week (wk of Oct 26). Floor and ceiling from the charter; "
        "under the floor is a miss, over the ceiling is a miss. Updated Mondays."
    )
    assert bd.render(1250, 1450, WEEK).startswith("1,250–1,450 kcal this week (wk of Nov 2).")


@pytest.mark.parametrize(
    "previous,decision,moved",
    [
        (rec(1400, 1600), rec(1400, 1600, WEEK), False),  # unchanged
        (rec(1400, 1600), rec(1250, 1450, WEEK), True),  # moved
        (rec(1400, 1600), rec(1400, 1650, WEEK), True),  # one end moved
        (None, rec(1400, 1600, WEEK), False),  # no previous week: not provably a move
        ({"week": "2026-10-26"}, rec(1400, 1600, WEEK), False),  # previous carried no band
        (rec(1400, 1600), {"week": WEEK, "band_low": None, "band_high": None}, False),  # the decision has no band
    ],
)
def test_the_band_moved_rule(previous, decision, moved):
    assert bd.band_moved(previous, decision) is moved


def test_the_habit_is_found_by_vendor_id_through_the_core_flag_never_the_name():
    assert bd.band_habit_id(REGISTRY) == HID
    renamed = {
        "A different display name entirely": REGISTRY["Synthetic band habit"],
        "Synthetic other habit": REGISTRY["Synthetic other habit"],
    }
    assert bd.band_habit_id(renamed) == HID
    no_id = {"Synthetic band habit": {"status": "active", "core": bd.CORE_ID}}
    assert bd.band_habit_id(no_id) is None
    two = {**REGISTRY, "Synthetic twin": {"status": "active", "core": bd.CORE_ID, "habitify_id": "SYNTHETIC-HABIT-ID-3"}}
    assert bd.band_habit_id(two) is None  # ambiguous: never a guess
    inactive = {"Synthetic band habit": {**REGISTRY["Synthetic band habit"], "status": "paused"}}
    assert bd.band_habit_id(inactive) is None
    assert bd.band_habit_id(None) is None


# ── the write ─────────────────────────────────────────────────────────────────────────────
class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"null"


def test_the_put_is_the_skills_v2_update_call_over_urllib():
    seen = []

    def opener(req, timeout=None):
        seen.append((req.full_url, req.get_method(), json.loads(req.data), req.get_header("X-api-key"), timeout))
        return _Resp()

    bd.put_description(HID, "text", "k", opener=opener)
    assert seen == [(f"https://api.habitify.me/v2/habits/{HID}", "PUT", {"description": "text"}, "k", bd.TIMEOUT_S)]


def test_the_put_retries_a_transient_5xx_and_raises_a_permanent_4xx():
    calls = []

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(req.full_url, 503, "x", {}, io.BytesIO(b""))
        return _Resp()

    bd.put_description(HID, "t", "k", opener=flaky, sleep=lambda s: None)
    assert len(calls) == 3

    def denied(req, timeout=None):
        raise HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b""))

    with pytest.raises(HTTPError):
        bd.put_description(HID, "t", "k", opener=denied, sleep=lambda s: None)


def test_sync_band_unchanged_makes_no_call():
    calls = []
    out = bd.sync(rec(1400, 1600), rec(1400, 1600, WEEK), REGISTRY, api_key_reader=lambda: "k", put=lambda *a: calls.append(a))
    assert out == "unchanged" and calls == []


def test_sync_band_moved_makes_one_call_with_the_rendered_text():
    calls = []
    out = bd.sync(rec(1400, 1600), rec(1250, 1450, WEEK), REGISTRY, api_key_reader=lambda: "k", put=lambda *a: calls.append(a))
    assert out == "updated"
    assert calls == [(HID, bd.render(1250, 1450, WEEK), "k")]


def test_sync_is_fail_soft_on_every_failure_and_logs_one_line(caplog):
    def boom(*a):
        raise RuntimeError("the vendor said something with 1,400 in it")

    with caplog.at_level("WARNING"):
        out = bd.sync(rec(1400, 1600), rec(1250, 1450, WEEK), REGISTRY, api_key_reader=lambda: "k", put=boom)
    assert out == "failed"
    lines = [r.getMessage() for r in caplog.records if bd.LOG_MARK in r.getMessage()]
    assert len(lines) == 1 and "RuntimeError" in lines[0] and "1,400" not in lines[0]  # the class, never the body

    def no_key():
        raise KeyError("secret")

    assert bd.sync(rec(1400, 1600), rec(1250, 1450, WEEK), REGISTRY, api_key_reader=no_key, put=lambda *a: None) == "failed"
    assert bd.sync(rec(1400, 1600), rec(1250, 1450, WEEK), {}, api_key_reader=lambda: "k", put=boom) == "no_habit"


# ── through the nightly leg ───────────────────────────────────────────────────────────────
class _Table:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        self.items[(Item["pk"], Item["sk"])] = Item


@pytest.fixture
def leg(monkeypatch):
    from health import titration as ti

    from mcp import core, titration_leg as tl

    table = _Table()
    monkeypatch.setattr(core, "table", table, raising=False)
    monkeypatch.setattr(core, "get_profile", lambda: {"habit_registry": REGISTRY})
    state = {"history": [rec(1400, 1600)], "band": (1400, 1600)}
    monkeypatch.setattr(tl, "gather", lambda today: {"week": WEEK, "history": state["history"]})
    monkeypatch.setattr(
        ti,
        "decide",
        lambda **kw: {
            "week": WEEK,
            "action": "hold",
            "step_kcal": 0,
            "reason_code": "in_band",
            "band_low": state["band"][0],
            "band_high": state["band"][1],
        },
    )
    puts = []
    monkeypatch.setattr(bd, "_api_key", lambda: "k")
    monkeypatch.setattr(bd, "put_description", lambda hid, text, key, *a, **kw: puts.append((hid, text, key)))
    return tl, state, puts, table


def test_the_leg_band_unchanged_writes_the_record_and_makes_no_call(leg):
    tl, state, puts, table = leg
    out = tl.run("2026-10-30")  # a Friday
    assert out["outcome"] == "written" and out["band_description"] == "unchanged" and puts == []


def test_the_leg_band_moved_makes_one_call_with_the_rendered_text(leg):
    tl, state, puts, table = leg
    state["band"] = (1250, 1450)
    out = tl.run("2026-10-30")
    assert out["outcome"] == "written" and out["band_description"] == "updated"
    assert puts == [(HID, bd.render(1250, 1450, WEEK), "k")]
    assert tl.run("2026-10-31")["outcome"] == "exists" and len(puts) == 1  # the weekend retry never repeats it


def test_the_leg_first_ever_record_makes_no_call(leg):
    tl, state, puts, table = leg
    state["history"] = []
    state["band"] = (1250, 1450)
    assert tl.run("2026-10-30")["band_description"] == "unchanged" and puts == []


def test_the_leg_a_failing_habitify_call_never_fails_the_titration_write(leg, monkeypatch):
    tl, state, puts, table = leg
    state["band"] = (1250, 1450)

    def boom(*a, **kw):
        raise HTTPError("u", 500, "x", {}, io.BytesIO(b""))

    monkeypatch.setattr(bd, "put_description", boom)
    out = tl.run("2026-10-30")
    assert out["outcome"] == "written" and out["band_description"] == "failed"
    assert len(table.items) == 1  # the record is on file


def test_the_leg_a_dry_run_never_calls_habitify(leg):
    tl, state, puts, table = leg
    state["band"] = (1250, 1450)
    assert tl.run("2026-10-30", dry_run=True)["outcome"] == "dry_run" and puts == [] and table.items == {}
