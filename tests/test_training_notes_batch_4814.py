"""
tests/test_training_notes_batch_4814.py — the Hevy training-notes backfill adopts the Bedrock batch path (#4814, ADR-132).

`deploy/backfill_training_notes.py --apply` collects its uncached notes as `build_jsonl_record` records (recordId = the
note hash) and, at 100+ of them, answers them as ONE batch job through `bedrock_batch.run_or_fallback`. Pinned here (the
S3/Bedrock calls are faked, nothing reaches AWS; the output line is the shape `bedrock_batch`'s own tests archive):

  * box 1: records carry the note hash as recordId; the reply parse is `_parse_signals` (an off-taxonomy class is dropped,
    a truncated reply degrades) and a batch answer equals the on-demand answer for the same reply;
  * box 2: a batch-answered note lands in the hash cache and charges the bulk lane one call, exactly as on-demand; the cap
    is checked on the record count BEFORE submit (a job that would pass it submits nothing);
  * box 3: a route resolving to a model listed without Batch pins Haiku 4.5 for the job;
  * box 4: below the floor, or with --realtime, nothing is submitted and the output says `mode=realtime` and why.

Run:  python3 -m pytest tests/test_training_notes_batch_4814.py -v
"""

import importlib.util
import json
import os
import sys
import types

import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import (
    bedrock_batch as bb,  # noqa: E402
    model_routing as mr,  # noqa: E402
)
from bundle_stubs import stub_bundled_module  # noqa: E402
from training import (  # noqa: E402
    training_notes as tn,
    training_notes_llm as tnl,
)

_SER, _DESER = TypeSerializer(), TypeDeserializer()
TAXONOMY = tn.TAXONOMY


class WireTable:
    """Every item passes boto3's serializer going in and deserializer coming out (a float raises, as on DynamoDB)."""

    def __init__(self):
        self.store = {}

    def get_item(self, Key):
        raw = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": {k: _DESER.deserialize(v) for k, v in raw.items()}} if raw else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = {k: _SER.serialize(v) for k, v in Item.items()}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        cur = self.get_item(Key).get("Item") or {"pk": Key["pk"], "sk": Key["sk"]}
        cur["calls"] = int(cur.get("calls", 0)) + 1
        self.put_item(cur)


def _notes(n):
    return [f"Note number {i}: grip gave out before legs on set {i}" for i in range(n)]


def _reply(signals, stop="end_turn"):
    return {
        "stop_reason": stop,
        "content": [{"type": "text", "text": json.dumps(signals)}],
        "usage": {"input_tokens": 90, "output_tokens": 30},
    }


_GOOD = [{"class": "limiter", "summary": "grip limits before legs", "confidence": 0.85}]


def _line(rid, reply):
    return json.dumps({"recordId": rid, "modelInput": {}, "modelOutput": reply})


@pytest.fixture
def calls(monkeypatch):
    """Faked bedrock_batch seams + an open budget; records what was submitted."""
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0
    stub.allow = lambda feature: True
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)
    state = {"submitted": [], "lines": []}

    def _submit(records, model_name, in_uri, out_uri, role_arn, job_name=None):
        state["submitted"].append({"records": records, "model": model_name, "in": in_uri})
        return "arn:aws:bedrock:us-west-2:123:model-invocation-job/tn4814"

    monkeypatch.setattr(bb, "submit_batch", _submit)
    monkeypatch.setattr(bb, "batch_role_arn", lambda: "arn:aws:iam::123:role/life-platform-bedrock-batch")
    monkeypatch.setattr(
        bb, "wait_for_batch", lambda a, d, poll_interval=60.0: {"status": "Completed", "done": True, "succeeded": True, "message": ""}
    )
    monkeypatch.setattr(bb, "_read_output", lambda uri, key: bb.parse_output_jsonl("\n".join(state["lines"])))
    monkeypatch.setattr(bb, "_cleanup", lambda i, o, log: None)
    monkeypatch.setattr(bb, "_meter_batch_record", lambda usage, model_id: None)
    monkeypatch.setattr(bb, "_dev_cap_projected", lambda records, model_name: None)
    return state


def _answer_all(state, notes, reply):
    state["lines"] = [_line(tn.note_hash(t), reply) for t in reversed(notes)]  # Bedrock returns them unordered


def test_a_batch_job_keys_records_by_note_hash_and_fills_cache_and_counter_like_on_demand(calls):
    table = WireTable()
    notes = _notes(120) + _notes(5)  # duplicates collapse: one record per distinct text
    _answer_all(calls, notes, _reply(_GOOD))
    res = tnl.bulk_prefetch(table, notes, TAXONOMY, realtime_fn=lambda mi: pytest.fail("no on-demand call expected"), log=lambda m: None)
    assert res["mode"] == "batch" and res["records"] == 120 and res["answered"] == 120
    sub = calls["submitted"]
    assert len(sub) == 1 and len(sub[0]["records"]) == 120
    assert {r["recordId"] for r in sub[0]["records"]} == {tn.note_hash(t) for t in notes}
    assert "model" not in sub[0]["records"][0]["modelInput"]  # routing key stripped, like invoke()
    # cache: every note now answers from the hash cache, signals round-tripped through the wire
    assert tnl.cache_get(table, tn.note_hash(notes[7]))[0]["class"] == "limiter"
    # counter: one bulk-lane call per answered note, the live lane untouched
    assert tnl.monthly_calls(table, lane="bulk") == 120 and tnl.monthly_calls(table, lane="live") == 0
    # and the sweep's llm_fn takes a cache hit with no model call
    fn = tnl.make_llm_fn(table, lane="bulk", precomputed=res["precomputed"])
    assert fn(notes[7], TAXONOMY)[0]["class"] == "limiter"


def test_a_batch_reply_equals_the_on_demand_reply_for_the_same_text():
    reply = _reply(_GOOD + [{"class": "not_a_real_class", "summary": "x", "confidence": 0.9}])
    assert tnl.signals_from_response(reply, TAXONOMY) == tnl._parse_signals(reply["content"][0]["text"], TAXONOMY)
    assert [s["class"] for s in tnl.signals_from_response(reply, TAXONOMY)] == ["limiter"]  # in-taxonomy filter held


def test_a_degraded_batch_answer_is_billed_counted_never_cached_and_not_rebilled(calls):
    table = WireTable()
    notes = _notes(100)
    bad = notes[3]
    _answer_all(calls, notes, _reply(_GOOD))
    calls["lines"] = [ln for ln in calls["lines"] if json.loads(ln)["recordId"] != tn.note_hash(bad)]
    calls["lines"].append(_line(tn.note_hash(bad), _reply(_GOOD, stop="max_tokens")))
    res = tnl.bulk_prefetch(table, notes, TAXONOMY, realtime_fn=lambda mi: pytest.fail("no on-demand call"), log=lambda m: None)
    assert res["answered"] == 99 and res["degraded"] == 1
    assert tnl.monthly_calls(table, lane="bulk") == 100  # the degraded call was billed
    assert tnl.cache_get(table, tn.note_hash(bad)) is None  # a degrade is never cached
    fn = tnl.make_llm_fn(table, lane="bulk", precomputed=res["precomputed"])
    with pytest.raises(tnl.TruncatedResponse):
        fn(bad, TAXONOMY)
    assert tnl.monthly_calls(table, lane="bulk") == 100  # re-raised, not re-billed


def test_an_unanswered_record_falls_back_on_demand_and_is_charged_once(calls):
    table = WireTable()
    notes = _notes(100)
    _answer_all(calls, notes[1:], _reply(_GOOD))  # the job never answers notes[0]
    seen = []
    res = tnl.bulk_prefetch(table, notes, TAXONOMY, realtime_fn=lambda mi: seen.append(mi) or _reply(_GOOD), log=lambda m: None)
    assert res["mode"] == "batch+realtime" and len(seen) == 1 and res["answered"] == 100
    assert tnl.monthly_calls(table, lane="bulk") == 100


def test_the_cap_is_checked_on_the_record_count_before_submit(calls):
    table = WireTable()
    res = tnl.bulk_prefetch(table, _notes(120), TAXONOMY, monthly_cap=119, log=lambda m: None)
    assert res["mode"] == "realtime" and "monthly cap 119" in res["reason"]
    assert calls["submitted"] == []  # nothing staged, nothing billed
    ok = tnl.bulk_prefetch(
        table, _notes(100), TAXONOMY, monthly_cap=100, run=lambda *a, **k: {"mode": "batch", "reason": "r", "results": [], "job_arn": "a"}
    )
    assert ok["mode"] == "batch"  # exactly at the cap still goes


def test_below_the_floor_or_with_realtime_nothing_is_submitted_and_says_why(calls):
    table = WireTable()
    below = tnl.bulk_prefetch(table, _notes(99), TAXONOMY)
    assert below["mode"] == "realtime" and f"< {bb.MIN_RECORDS_PER_JOB}" in below["reason"]
    forced = tnl.bulk_prefetch(table, _notes(150), TAXONOMY, force_realtime=True)
    assert forced["mode"] == "realtime" and "--realtime" in forced["reason"]
    assert calls["submitted"] == []


def test_cached_notes_are_not_records(calls):
    table = WireTable()
    notes = _notes(110)
    for t in notes[:20]:
        tnl.cache_put(table, tn.note_hash(t), [])
    assert len(tnl.uncached_notes(table, notes)) == 90
    assert tnl.bulk_prefetch(table, notes, TAXONOMY)["mode"] == "realtime"  # 90 < 100: under the floor once cached notes drop out


def test_a_model_listed_without_batch_is_pinned_to_haiku_4_5(monkeypatch, calls):
    monkeypatch.setattr(mr, "model_for", lambda route, env=None: "claude-haiku-5-5")
    assert tnl.batch_model() == mr.BATCH_FALLBACK_MODEL == "claude-haiku-4-5-20251001"
    monkeypatch.setattr(mr, "model_for", lambda route, env=None: "claude-haiku-4-5-20251001")
    assert tnl.batch_model() == "claude-haiku-4-5-20251001"
    monkeypatch.setattr(mr, "model_for", lambda route, env=None: "claude-haiku-5-5")
    table = WireTable()
    notes = _notes(100)
    _answer_all(calls, notes, _reply(_GOOD))
    tnl.bulk_prefetch(table, notes, TAXONOMY, log=lambda m: None)
    assert calls["submitted"][0]["model"] == "claude-haiku-4-5-20251001"


def test_the_backfill_script_prints_mode_and_returns_the_degrade_map(capsys):
    spec = importlib.util.spec_from_file_location("backfill_tn_4814", os.path.join(ROOT, "deploy", "backfill_training_notes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    workouts = [
        {
            "date": "2026-09-01",
            "exercises": [{"title": "Row", "notes": "grip gave out"}, {"title": "Curl", "notes": " "}],
        }
    ]
    seen = {}

    def fake(table, notes, taxonomy, **kw):
        seen.update(notes=list(notes), kw=kw)
        return {"mode": "realtime", "reason": "1 records < 100-record Bedrock batch floor", "records": 1, "precomputed": {"h": "x"}}

    out = mod.batch_prefetch(None, workouts, force_realtime=True, prefetch=fake)
    printed = capsys.readouterr().out
    assert seen["notes"] == ["grip gave out"] and seen["kw"]["force_realtime"] is True
    assert "mode=realtime" in printed and "floor" in printed and out == {"h": "x"}
