"""tests/test_training_notes_llm.py — bounded Haiku tail (parse + hash-cache + cap).

No real Bedrock call: _haiku_call is monkeypatched. Proves the JSON parser is defensive,
the hash-cache reuses without a model call, and the monthly cap raises CapExceeded (which
the extractor catches → degraded, never drops a note).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import training_notes_llm as tnl  # noqa: E402
from training_notes import TAXONOMY, note_hash  # noqa: E402


class FakeTable:
    """In-memory DDB stand-in for get/put/update_item."""

    def __init__(self):
        self.store = {}

    def _k(self, key):
        return (key["pk"], key["sk"])

    def get_item(self, Key):
        it = self.store.get(self._k(Key))
        return {"Item": it} if it else {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        it = self.store.setdefault(self._k(Key), {"pk": Key["pk"], "sk": Key["sk"]})
        it["calls"] = int(it.get("calls", 0)) + 1


def test_parse_signals_defensive():
    # Off-taxonomy dropped; fenced/prose-wrapped JSON tolerated; confidence clamped.
    txt = 'here you go: [{"class":"limiter","summary":"grip first","confidence":1.4},{"class":"bogus","summary":"x","confidence":0.5}]'
    sigs = tnl._parse_signals(txt, TAXONOMY)
    assert len(sigs) == 1 and sigs[0]["class"] == "limiter"
    assert sigs[0]["confidence"] == 1.0  # clamped


def test_parse_signals_garbage_returns_empty():
    assert tnl._parse_signals("no json here", TAXONOMY) == []
    assert tnl._parse_signals("", TAXONOMY) == []


def test_cache_hit_skips_model(monkeypatch):
    calls = {"n": 0}

    def fake_call(note, taxo):
        calls["n"] += 1
        return [{"class": "sentiment_adherence", "summary": "enjoyed", "confidence": 0.9}]

    monkeypatch.setattr(tnl, "_haiku_call", fake_call)
    t = FakeTable()
    fn = tnl.make_llm_fn(t, monthly_cap=300)
    s1 = fn("first time, enjoyed it", TAXONOMY)
    s2 = fn("first time, enjoyed it", TAXONOMY)  # same note → cache hit
    assert s1 == s2
    assert calls["n"] == 1  # model called once; second served from cache
    assert tnl.monthly_calls(t) == 1


def test_cap_raises_capexceeded(monkeypatch):
    monkeypatch.setattr(tnl, "_haiku_call", lambda n, x: [])
    t = FakeTable()
    # Pre-seed the usage counter at the cap.
    t.put_item({"pk": tnl._USAGE_PK, "sk": f"MONTH#{tnl._month()}", "calls": 300})
    fn = tnl.make_llm_fn(t, monthly_cap=300)
    try:
        fn("a brand new note never seen", TAXONOMY)
        assert False, "expected CapExceeded"
    except tnl.CapExceeded:
        pass


def test_cap_breach_degrades_in_extractor(monkeypatch):
    # End-to-end: a capped llm_fn → extract_signals catches → degraded, deterministic kept.
    from training_notes import extract_signals

    t = FakeTable()
    t.put_item({"pk": tnl._USAGE_PK, "sk": f"MONTH#{tnl._month()}", "calls": 999})
    fn = tnl.make_llm_fn(t, monthly_cap=300)
    rec = extract_signals("Low effort level 10 for whole thing", llm_fn=fn)
    assert rec["degraded"] is True
    # deterministic progression survived the LLM cap
    assert any(s["class"] == "progression" for s in rec["signals"])
    assert note_hash(rec["note_raw"]) == rec["note_hash"]
