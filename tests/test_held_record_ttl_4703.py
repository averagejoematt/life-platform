#!/usr/bin/env python3
"""tests/test_held_record_ttl_4703.py — #4703: a held read must not delete itself.

The grounding gate (#2391/#2421) HOLDS a draft it cannot ground and promises the prior
cached record "keeps serving". Every analyzer record carries a ~1-cycle DynamoDB `ttl`
and the writer runs weekly, so one held Monday used to leave the prior `EXPERT#integrator`
to expire ~2 days later — `/api/weekly_priority` served null (live, 2026-10-06 onward).

Pinned here, against a TTL-honouring table double (an item past its `ttl` is gone):

  * the issue's own acceptance test — a hold planted 7 days after the prior write, read
    9 days after it: the prior record is still served by `/api/weekly_priority`, with its
    `generated_at`/`data_through` stamps (the #4188 label-its-age rule);
  * the same hold-renews contract on every record whose hold path promises the prior keeps
    serving: `EXPERT#<domain>`, `EXPERT#integrator_month`, `EXPERT#experiment_arc`, and the
    board-level records when held domain reads leave the synthesis below its 3-read floor;
  * the TTL is still the dead-pipeline backstop: no run (and a non-hold failure) renews
    nothing, so the record still expires — the existing
    `test_the_record_expires_so_a_dead_pipeline_cannot_serve_forever` stays true;
  * a renewal never creates a record, never prolongs a reset tombstone, never shortens.

Offline: the model seam is monkeypatched, DynamoDB is a dict; no AWS, no Bedrock.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "intelligence"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai_expert_analyzer_lambda as az  # noqa: E402
from common import retry_utils  # noqa: E402
from intelligence import held_record_ttl as held  # noqa: E402

T0 = datetime(2026, 9, 28, 14, 1, tzinfo=timezone.utc)  # the prior (passing) weekly write
FABRICATED = "You averaged 8412 steps across the week."  # a number in no prompt — the gate holds it


class _CondFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class TtlTable:
    """Dict-backed DDB double that HONOURS `ttl`: an item whose ttl is at or before the
    table's clock is gone, exactly as the production TTL sweep makes it. `update_item`
    evaluates renew_held's condition expression the way DynamoDB would."""

    def __init__(self, clock):
        self.clock = clock
        self.items: dict = {}
        self.puts: list = []

    def _live(self, key):
        item = self.items.get(key)
        if item is None:
            return None
        ttl = item.get("ttl")
        if ttl is not None and int(ttl) <= int(self.clock.timestamp()):
            del self.items[key]
            return None
        return item

    def put_item(self, Item=None, **kwargs):
        self.puts.append(dict(Item))
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(
        self, Key=None, UpdateExpression="", ConditionExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kw
    ):
        assert "attribute_exists(pk)" in ConditionExpression and "attribute_not_exists(tombstone)" in ConditionExpression
        row = self._live((Key["pk"], Key["sk"]))
        new_ttl = ExpressionAttributeValues[":ttl"]
        if row is None or row.get("tombstone") or ("ttl" in row and int(row["ttl"]) >= new_ttl):
            raise _CondFailed()
        row["ttl"] = new_ttl
        row["held_renewed_at"] = ExpressionAttributeValues[":at"]

    def get_item(self, Key=None, **kwargs):
        item = self._live((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        return {"Items": []}


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies) or [""]

    def __call__(self, req, timeout=None):
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {"content": [{"type": "text", "text": reply}]}


def _frozen(at):
    class _F(datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz else at.replace(tzinfo=None)

    return _F


@pytest.fixture
def table(monkeypatch):
    t = TtlTable(T0)
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    az._CANON_FACTS_CACHE.clear()
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: {})
    monkeypatch.setattr(az, "_load_engagement_signal", lambda: {})
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
    yield
    az._CANON_FACTS_CACHE.clear()


def _at(monkeypatch, table, days):
    """Move every clock — the table's TTL sweep and the renewal's `now` — to T0 + days."""
    when = T0 + timedelta(days=days)
    table.clock = when
    monkeypatch.setattr(held, "datetime", _frozen(when))
    return when


def _plant(table, sk, days=held.WEEKLY_TTL_DAYS, **fields):
    row = {
        "pk": az.CACHE_PK,
        "sk": sk,
        "analysis": "Last week's grounded read.",
        "generated_at": T0.isoformat(),
        "data_through": "2026-09-28",
        "ttl": held.ttl_from(T0, days),
        **fields,
    }
    table.items[(az.CACHE_PK, sk)] = row
    return row


def _model(monkeypatch, *replies):
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", FakeModel(*replies))


def _serve_weekly_priority(monkeypatch, table):
    from web import site_api_coach as C, site_api_coach_narrative as narr

    monkeypatch.setattr(C, "table", table)
    monkeypatch.setattr(narr, "pre_start_meta", lambda: None)
    return json.loads(C.handle_weekly_priority({"queryStringParameters": {}})["body"])


# ── the issue's acceptance test ─────────────────────────────────────────────
class TestAHeldWeeklyPriorityKeepsServing:
    def test_a_hold_leaves_the_prior_record_served_nine_days_later(self, table, monkeypatch):
        prior = _plant(table, "EXPERT#integrator")
        _at(monkeypatch, table, 7)  # the next weekly run
        _model(monkeypatch, json.dumps({"weekly_priority": FABRICATED, "cross_domain_notes": {}, "disagreements": []}))
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None, "precondition: the gate held"
        assert table.puts == [], "a hold writes no new record"

        _at(monkeypatch, table, 9)  # past the prior write's own 8-day ttl
        body = _serve_weekly_priority(monkeypatch, table)
        assert body["weekly_priority"] == prior["analysis"], f"the held week served null: {body}"
        # #4188: a read older than one weekly cycle is served WITH its age stamps.
        assert body["generated_at"] == prior["generated_at"]
        assert body["data_through"] == prior["data_through"]

    def test_control_without_a_run_the_prior_record_expires(self, table, monkeypatch):
        """The dead-pipeline backstop is intact: nothing ran, nothing renewed, gone."""
        _plant(table, "EXPERT#integrator")
        _at(monkeypatch, table, 9)
        assert _serve_weekly_priority(monkeypatch, table)["weekly_priority"] is None

    def test_a_synthesis_call_failure_is_not_a_hold_and_renews_nothing(self, table, monkeypatch):
        """Only the gate's HOLD promises the prior keeps serving; a model outage every week is
        a dead pipeline and must still expire."""
        _plant(table, "EXPERT#integrator")
        _at(monkeypatch, table, 7)

        def _down(*_a, **_k):
            raise RuntimeError("bedrock unreachable")

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _down)
        assert az.generate_synthesis({"sleep": "s", "training": "t"}) is None
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["ttl"] == held.ttl_from(T0, held.WEEKLY_TTL_DAYS)


# ── the rest of the set: every "prior cached record keeps serving" path ─────
class TestEveryHoldPathRenews:
    @pytest.fixture
    def week_notes(self, table):
        pk = az.USER_PREFIX + "field_notes"
        notes = [{"pk": pk, "sk": f"WEEK#{wk}", "week": wk, "ai_present": "A quiet week."} for wk in ("2026-W38", "2026-W39")]
        table.query = lambda **kw: {"Items": [dict(n) for n in notes]}
        return notes

    def test_a_held_month_rollup_keeps_serving(self, table, monkeypatch, week_notes):
        _plant(table, "EXPERT#integrator_month", days=held.ROLLUP_TTL_DAYS, narrative="Last month.")
        monkeypatch.setattr(az, "_week_behavioral_presence", lambda wk: None)
        _at(monkeypatch, table, 7)
        _model(monkeypatch, json.dumps({"narrative": FABRICATED, "headline": "h"}))
        assert az.generate_month_rollup() is None and table.puts == []
        _at(monkeypatch, table, 11)  # past the prior write's own 10-day ttl
        assert table.get_item(Key={"pk": az.CACHE_PK, "sk": "EXPERT#integrator_month"}).get("Item"), "the held rollup expired"

    def test_a_held_experiment_arc_keeps_serving(self, table, monkeypatch, week_notes):
        _plant(table, "EXPERT#experiment_arc", days=held.ROLLUP_TTL_DAYS, arc="The arc so far.")
        monkeypatch.setattr(az, "_week_behavioral_presence", lambda wk: None)
        _at(monkeypatch, table, 7)
        _model(monkeypatch, json.dumps({"arc": FABRICATED, "throughline": "t", "chapters": []}))
        assert az.generate_experiment_arc() is None and table.puts == []
        _at(monkeypatch, table, 11)
        assert table.get_item(Key={"pk": az.CACHE_PK, "sk": "EXPERT#experiment_arc"}).get("Item"), "the held arc expired"

    def test_held_domain_reads_renew_themselves_and_the_board_records(self, table, monkeypatch):
        """Every domain read held → each EXPERT#<domain> keeps serving, and the synthesis
        (never attempted below its 3-read floor) keeps the board-level records serving too."""
        for key in az.EXPERTS:
            _plant(table, f"EXPERT#{key}")
        for sk, days in held.BOARD_RECORDS:
            _plant(table, sk, days=days)
        monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: "SYS")
        monkeypatch.setattr(az.coach_presence_gate, "absent_or_empty", lambda *a, **k: ({}, None))
        monkeypatch.setattr(az, "generate_and_cache", lambda key, shared_system=None: "")  # the #2391 hold return
        _at(monkeypatch, table, 7)
        out = json.loads(az.lambda_handler({}, None)["body"])
        assert all(out[k]["status"] == "skipped_empty" for k in az.EXPERTS)
        _at(monkeypatch, table, 11)
        gone = [
            sk
            for sk in [f"EXPERT#{k}" for k in az.EXPERTS] + [sk for sk, _ in held.BOARD_RECORDS]
            if not table.get_item(Key={"pk": az.CACHE_PK, "sk": sk}).get("Item")
        ]
        assert gone == [], f"held records expired: {gone}"


# ── the renewal's own boundaries ─────────────────────────────────────────────
class TestRenewalBoundaries:
    def test_it_never_creates_a_record(self, table, monkeypatch):
        _at(monkeypatch, table, 7)
        held.renew_held(table, az.CACHE_PK, "EXPERT#integrator", held.WEEKLY_TTL_DAYS)
        assert table.items == {}

    def test_it_never_prolongs_a_reset_tombstone(self, table, monkeypatch):
        _plant(table, "EXPERT#integrator", tombstone=True)
        _at(monkeypatch, table, 7)
        held.renew_held(table, az.CACHE_PK, "EXPERT#integrator", held.WEEKLY_TTL_DAYS)
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["ttl"] == held.ttl_from(T0, held.WEEKLY_TTL_DAYS)

    def test_it_never_shortens_a_newer_ttl(self, table, monkeypatch):
        _plant(table, "EXPERT#integrator", days=30)
        _at(monkeypatch, table, 1)
        held.renew_held(table, az.CACHE_PK, "EXPERT#integrator", held.WEEKLY_TTL_DAYS)
        assert table.items[(az.CACHE_PK, "EXPERT#integrator")]["ttl"] == held.ttl_from(T0, 30)

    def test_a_failing_renewal_never_breaks_the_hold(self, monkeypatch):
        class Broken:
            def update_item(self, **kw):
                raise RuntimeError("throttled")

        assert held.renew_held(Broken(), az.CACHE_PK, "EXPERT#integrator", held.WEEKLY_TTL_DAYS) is None
