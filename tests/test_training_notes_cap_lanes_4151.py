"""#4151 — the note-signal layer was degraded: `cap_exceeded` on 25 of 28 sessions.

The cap is the training-notes Haiku MONTHLY CALL cap (`DEFAULT_MONTHLY_CAP`), not a note-length
or token cap. Measured 2026-09-23: the September counter stood at 301. About 277 of those calls
came from the attended historical backfill of 2026-09-19 (the hevy-backfill Lambda metered only
24 all month). That spend was possible because of a second defect: the hash cache could not
hold a non-empty extraction. `cache_put` wrote float `confidence` values, boto3 rejects floats,
and a bare `except: pass` swallowed the TypeError, so all 19 live CACHE rows had 0 signals. The
corpus is 566 noted sessions but only 111 distinct note texts. Every repeat was billed again.

The fix has two parts:
  1. The cache round-trips through the wire's type rules (Decimal in, float out) and says so
     when a write fails.
  2. The monthly counter is charged PER LANE: `live` for the on-ingest hook, `bulk` for any
     sweep. A sweep can no longer spend the live path's month.

The fake table below is the wire (reference_fixture_must_be_the_wire). It serializes every
write through boto3's own `TypeSerializer`, so a float is rejected here exactly as DynamoDB
rejects it. The pre-existing FakeTable in test_training_notes_llm.py accepts floats, which is
why `test_cache_hit_skips_model` stayed green while the live cache stayed empty.
"""

import ast
import os
import sys

import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from training import (
    training_notes as tn,  # noqa: E402
    training_notes_llm as tnl,  # noqa: E402
)
from training.training_notes import TAXONOMY  # noqa: E402

_SER, _DESER = TypeSerializer(), TypeDeserializer()

# An over-cap session as it looked live: the owner's own note, short, extracted AFTER the
# shared September counter had passed 300.
OWNER_NOTE = "Grip gave out before legs on the last set, felt strong otherwise"
MODEL_SIGNALS = [
    {"class": "limiter", "summary": "grip limits before legs", "confidence": 0.85},
    {"class": "sentiment_adherence", "summary": "felt strong", "confidence": 0.7},
]


class WireTable:
    """DynamoDB-faithful: every item passes through boto3's TypeSerializer on the way in and
    TypeDeserializer on the way out, so floats raise and numbers come back as Decimal."""

    def __init__(self):
        self.store = {}

    def get_item(self, Key):
        raw = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": {k: _DESER.deserialize(v) for k, v in raw.items()}} if raw else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = {k: _SER.serialize(v) for k, v in Item.items()}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        for v in ExpressionAttributeValues.values():
            _SER.serialize(v)
        cur = self.get_item(Key).get("Item") or {"pk": Key["pk"], "sk": Key["sk"]}
        cur["calls"] = int(cur.get("calls", 0)) + 1
        self.put_item(cur)


def _counting_model(monkeypatch):
    calls = {"n": 0}

    def fake(note, taxo):
        calls["n"] += 1
        return [dict(s) for s in MODEL_SIGNALS]

    monkeypatch.setattr(tnl, "_haiku_call", fake)
    return calls


# ── 1. the hash cache holds a non-empty extraction on the wire ──────────────────
def test_the_wire_table_rejects_a_float_like_dynamodb_does():
    """Guards the fixture itself: if this ever passes a float, every test below is blind."""
    with pytest.raises(TypeError, match="Float types are not supported"):
        WireTable().put_item({"pk": "p", "sk": "s", "signals": [{"confidence": 0.5}]})


def test_a_repeated_note_is_served_from_the_cache_and_not_billed_twice(monkeypatch):
    calls = _counting_model(monkeypatch)
    t = WireTable()
    fn = tnl.make_llm_fn(t, lane="bulk")
    first = fn(OWNER_NOTE, TAXONOMY)
    second = fn(OWNER_NOTE, TAXONOMY)
    assert calls["n"] == 1, "the second identical note re-billed — the cache did not hold the extraction"
    assert tnl.monthly_calls(t, lane="bulk") == 1
    assert second == first and len(second) == 2
    # A hit hands back floats, the same shape a fresh model call returns.
    assert all(isinstance(s["confidence"], float) for s in second)


def test_mutation_control_raw_float_cache_write_rebills(monkeypatch):
    """Put back the pre-#4151 write (signals handed over raw): the wire rejects it, and the
    same note is billed twice. This is the live state the 19 empty CACHE rows recorded."""
    calls = _counting_model(monkeypatch)
    monkeypatch.setattr(tnl, "floats_to_decimal", lambda x: x)
    t = WireTable()
    fn = tnl.make_llm_fn(t, lane="bulk")
    fn(OWNER_NOTE, TAXONOMY)
    fn(OWNER_NOTE, TAXONOMY)
    assert calls["n"] == 2
    assert tnl.cache_get(t, tn.note_hash(OWNER_NOTE)) is None


def test_a_failed_cache_write_is_logged_not_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(tnl, "floats_to_decimal", lambda x: x)
    with caplog.at_level("WARNING"):
        tnl.cache_put(WireTable(), "h", [{"class": "limiter", "confidence": 0.5}])
    assert any("hash-cache write failed" in r.getMessage() for r in caplog.records)


# ── 2. an over-cap session is read in full ───────────────────────────────────────
def _september_as_it_was(t):
    """The live counters of 2026-09-23: the legacy shared row at 301 (spent by the backfill),
    and a bulk lane that a sweep has also run to its cap."""
    t.put_item({"pk": tnl._USAGE_PK, "sk": f"MONTH#{tnl._month()}", "calls": 301})
    t.put_item({"pk": tnl._USAGE_PK, "sk": tnl.usage_sk(lane="bulk"), "calls": tnl.DEFAULT_MONTHLY_CAP})


def test_an_over_cap_session_is_read_in_full_on_the_live_lane(monkeypatch):
    calls = _counting_model(monkeypatch)
    t = WireTable()
    _september_as_it_was(t)
    rec = tn.extract_signals(OWNER_NOTE, llm_fn=tnl.make_llm_fn(t, lane="live"))
    assert rec["degraded"] is False, rec.get("degraded_reason")
    assert rec["extracted_by"] in ("haiku", "hybrid")
    assert {"limiter", "sentiment_adherence"} <= {s["class"] for s in rec["signals"]}
    assert rec["note_raw"] == OWNER_NOTE
    assert calls["n"] == 1 and tnl.monthly_calls(t, lane="live") == 1
    assert tnl.monthly_calls(t, lane="bulk") == tnl.DEFAULT_MONTHLY_CAP, "the live call charged the bulk lane"


def test_mutation_control_a_shared_counter_degrades_the_same_session(monkeypatch):
    """Collapse both lanes back onto the one pre-#4151 key: the same session degrades with
    `cap_exceeded`. This is the specimen the owner saw."""
    _counting_model(monkeypatch)
    monkeypatch.setattr(tnl, "usage_sk", lambda now=None, lane="live": f"MONTH#{tnl._month(now)}")
    t = WireTable()
    _september_as_it_was(t)
    rec = tn.extract_signals(OWNER_NOTE, llm_fn=tnl.make_llm_fn(t, lane="live"))
    assert rec["degraded"] is True
    assert str(rec["degraded_reason"]).startswith("cap_exceeded")


def test_the_bulk_lane_still_caps_a_sweep(monkeypatch):
    """NEGATIVE CONTROL: the split is not a lift. A sweep at its own cap still degrades."""
    calls = _counting_model(monkeypatch)
    t = WireTable()
    _september_as_it_was(t)
    rec = tn.extract_signals("a note no sweep has seen before", llm_fn=tnl.make_llm_fn(t, lane="bulk"))
    assert rec["degraded"] is True and str(rec["degraded_reason"]).startswith("cap_exceeded")
    assert "bulk lane" in rec["degraded_reason"]
    assert calls["n"] == 0


def test_an_unknown_lane_is_refused_at_build_time():
    with pytest.raises(ValueError):
        tnl.make_llm_fn(WireTable(), lane="nightly")


# ── 3. every caller charges the lane it is ───────────────────────────────────────
def _make_llm_fn_lanes(path):
    tree = ast.parse(open(os.path.join(ROOT, path)).read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "make_llm_fn":
            lane = next((k.value.value for k in node.keywords if k.arg == "lane" and isinstance(k.value, ast.Constant)), None)
            out.append(lane)
    return out


_CALL_SITE_LANES = {
    "lambdas/ingestion/hevy_backfill_lambda.py": ["bulk", "live"],
    "deploy/backfill_training_notes.py": ["bulk", "bulk"],
}


def test_every_make_llm_fn_call_site_names_its_lane():
    """A call site with no `lane=` falls back to `live`. A new sweep written that way would
    quietly bring back the shared-month starvation, so every call site has to name its lane."""
    offenders = {p: got for p, want in _CALL_SITE_LANES.items() if (got := sorted(_make_llm_fn_lanes(p), key=str)) != want}
    assert not offenders, f"make_llm_fn call sites with a missing or wrong lane: {offenders}"


def test_the_repair_sweep_is_the_bulk_lane_and_ingest_is_the_live_lane():
    src = open(os.path.join(ROOT, "lambdas/ingestion/hevy_backfill_lambda.py")).read()
    derive = src[src.index("def _derive_training_notes") : src.index("def _attach_adherence")]
    reextract = src[src.index("def reextract_training_notes") :]
    reextract = reextract[: reextract.index("\ndef ")]
    assert 'lane="live"' in derive and 'lane="bulk"' not in derive
    assert 'lane="bulk"' in reextract and 'lane="live"' not in reextract


# ── 4. the cap carries its derivation ────────────────────────────────────────────
def test_the_cap_is_derived_and_covers_its_measured_demand():
    d = tnl.MONTHLY_CAP_DERIVATION
    for k in ("metric", "window", "rule", "re_derive_when", "cost_per_call_usd"):
        assert d.get(k), k
    cap = tnl.DEFAULT_MONTHLY_CAP
    assert cap >= 2 * d["live_projected_peak_month"]
    assert cap >= 2 * d["bulk_corpus_distinct_notes"]
    assert d["live_projected_peak_month"] >= max(d["live_monthly_noted_sessions"].values())
    # The worst case the rule states is the arithmetic of the numbers it cites.
    assert f"{len(tnl.LANES) * cap} x ${d['cost_per_call_usd']['max']}" in d["rule"]
