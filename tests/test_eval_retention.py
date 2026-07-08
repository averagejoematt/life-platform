"""test_eval_retention.py — the #812/#744 retention contract.

Pins: the record shape (JSON payload, no float→Decimal hazard), the fail-soft
guarantee (retain() NEVER raises into a generation path), the surface allow-list,
and the fetch() round-trip the harvest loop consumes. Fully offline.
"""

import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import eval_retention as er  # noqa: E402
import pytest  # noqa: E402


class _Table:
    def __init__(self, fail=False):
        self.items = []
        self.fail = fail

    def put_item(self, Item):
        if self.fail:
            raise RuntimeError("simulated DDB outage")
        self.items.append(Item)

    def query(self, **kw):
        return {"Items": list(self.items)}


@pytest.fixture
def table(monkeypatch):
    t = _Table()
    monkeypatch.setattr(er, "_table", t)
    return t


# ── record shape ─────────────────────────────────────────────────────────────
def test_build_record_shape(table):
    rec = er.build_record(
        "board_ask",
        "flagged_refused",
        draft="HRV climbed to 58 ms",
        final="I can't ground that number.",
        findings=[{"type": "fabricated_number", "claimed": 58.0, "detail": "58 not in input"}],
        allowed={64.0, 42.5},
        extra={"persona": "sleep_coach"},
    )
    assert rec["pk"] == "EVALRET#board_ask"
    assert rec["sk"].startswith("TS#")
    assert rec["record_type"] == "eval_retention"
    assert isinstance(rec["ttl"], int) and rec["ttl"] > 0
    payload = json.loads(rec["payload_json"])
    assert payload["draft"] == "HRV climbed to 58 ms"
    assert payload["allowed"] == [42.5, 64.0]
    assert payload["findings"][0]["claimed"] == 58.0
    assert payload["extra"]["persona"] == "sleep_coach"
    # No bare float ever reaches DDB attribute level (all inside the JSON string)
    assert all(not isinstance(v, float) for v in rec.values())


def test_build_record_rejects_unknown_surface():
    with pytest.raises(ValueError):
        er.build_record("daily_brief", "flagged")


def test_build_record_caps_text():
    rec = er.build_record("chronicle", "flagged_kept_best", draft="x" * 20000)
    assert len(json.loads(rec["payload_json"])["draft"]) == er._TEXT_CAP


# ── fail-soft: retain never raises ───────────────────────────────────────────
def test_retain_writes(table):
    assert er.retain("memoir", "flagged_dropped", draft="d", findings=[{"type": "memoir_gate", "detail": "empty"}]) is True
    assert len(table.items) == 1


def test_retain_is_fail_soft_on_ddb_error(monkeypatch):
    monkeypatch.setattr(er, "_table", _Table(fail=True))
    assert er.retain("memoir", "flagged_dropped", draft="d") is False  # no raise


def test_retain_is_fail_soft_on_bad_surface(table):
    assert er.retain("nope", "flagged") is False
    assert table.items == []


# ── fetch round-trip (what the harvest consumes) ─────────────────────────────
def test_fetch_round_trip(table):
    er.retain("state_of_matthew", "flagged_fallback", draft="Brier 0.18", final="fallback", allowed={73.6}, findings=[])
    got = er.fetch("state_of_matthew")
    assert len(got) == 1
    assert got[0]["draft"] == "Brier 0.18"
    assert got[0]["allowed"] == [73.6]
    assert got[0]["_created_at"]


def test_fetch_skips_stale_and_unparseable(table):
    er.retain("chronicle", "flagged_kept_best", draft="recent")
    old = er.build_record("chronicle", "flagged_kept_best", draft="ancient", now=datetime(2020, 1, 1, tzinfo=timezone.utc))
    table.items.append(old)
    table.items.append({"pk": "EVALRET#chronicle", "sk": "TS#corrupt", "created_at": "not-a-date", "payload_json": "{"})
    got = er.fetch("chronicle", since_days=35)
    assert [g["draft"] for g in got] == ["recent"]


# ── the surface list matches the harness ─────────────────────────────────────
def test_surfaces_match_harness():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import golden_surface_eval as h

    assert set(er.SURFACES) == set(h.SURFACES)
