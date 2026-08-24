"""tests/test_coach_daily_reflection_reuse_2889.py — #2889 box 2, the reflection surface.

CC-08 pays 8 Haiku calls + up to 16 deterministic gate runs every day. `_gather_facts`
reads each coach's LATEST `OUTPUT#` record, so on any day a coach did not publish — an
ADR-108 quality-gate HOLD, a budget pause, a stalled coach — the facts are byte-identical
to yesterday's and the model is paid to re-say the same 120 words.

Measured on 2026-08-23 (live DDB, `COACH#*` / `OUTPUT#`, 8 coaches x 30 days): 206 of 240
coach-days produced a new output, so 34 coach-days (14%) had an unchanged input. One coach
(training_coach) had not published since 2026-08-09 — 14 consecutive identical-input days.

What is pinned here is that the saving never buys a lie: the stored text is re-gated
against TODAY before it is served, because `_accepts` arms the #2430 date and freshness
classes, which are functions of today and not of the fingerprinted inputs.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

from ai import budget_guard  # noqa: E402
from common import generation_cache as gc  # noqa: E402
from compute import coach_daily_reflection_lambda as writer  # noqa: E402

TODAY = "2026-08-24"

# Real facts, built by the module's own derivation (#2889 split `facts_from` out of
# `_gather_facts` for exactly this) — the allow-lists below are the ones production
# computes, not a hand-rolled lookalike.
FACTS = writer.facts_from("Sleep efficiency held near 88% across the week.", ["consistency"], 12)

# A reflection that uses only allowed numbers and hedges — passes ER-03 + grounding.
GOOD = "Sleep efficiency appears to be holding near 88% so far this week, which is early but consistent. Correlation only, small sample."


class _Table:
    def __init__(self, entry=None):
        self.entry, self.updates, self.puts = entry, [], []

    def get_item(self, Key):
        return {"Item": self.entry} if self.entry else {}

    def update_item(self, **kw):
        self.updates.append(kw)

    def put_item(self, Item):
        self.puts.append(Item)


class _CW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


PERSONA = {"name": "Sol", "domain": "sleep", "coach_config_key": "sleep_coach"}
VOICE, EXAMPLE = '{"tone": "dry"}', "A sample in voice."


def _entry(output, fingerprint=None):
    fp = fingerprint or gc.brief_fingerprint(gc.reflection_parts(PERSONA, VOICE, EXAMPLE, FACTS))
    return {"brief_hash": fp, "output": output, "first_generated": "2026-08-18"}


def _reuse(entry, cw=None):
    return writer._reuse_or_none(_Table(entry), cw or _CW(), "sleep_coach", PERSONA, VOICE, EXAMPLE, FACTS, TODAY)


# ── the guard that makes the whole extension safe ─────────────────────────────


def test_the_stored_text_must_pass_TODAYS_gate_or_it_is_regenerated():
    """Sanity-check the fixture first, then break only the gate-relevant part.

    The stored text below reuses an input fingerprint that MATCHES — so the only
    thing standing between it and publication is the re-gate. It cites 71%, a number
    that is not in the facts, which is precisely the ADR-104 class the reflection
    surface is gated on."""
    assert writer._accepts(GOOD, FACTS, TODAY)[0], "fixture guard: the good text must pass, or the next assert proves nothing"
    fabricated = "Sleep efficiency appears to have moved to 71% so far, which is early but notable."
    assert not writer._accepts(fabricated, FACTS, TODAY)[0]

    _fp, reused, _since = _reuse(_entry(fabricated))
    assert reused is None, "a stored reflection that fails today's gate must be regenerated, not republished"


def test_a_hit_that_still_passes_is_reused_and_counted():
    cw = _CW()
    fp, reused, since = _reuse(_entry(GOOD), cw=cw)
    assert reused == GOOD
    assert since == "2026-08-18"
    assert fp
    dims = {d["Name"]: d["Value"] for d in cw.calls[0]["MetricData"][0]["Dimensions"]}
    assert dims == {"Coach": "sleep_coach", "Surface": "daily_reflection"}


def test_reuse_bookkeeping_lands_on_the_daily_reflection_slot_not_the_brief_slot():
    """The coach brief already owns COACH#<id>#daily_brief_* in this partition. A
    collision would have the two surfaces overwriting each other's cached output."""
    t = _Table(_entry(GOOD))
    writer._reuse_or_none(t, _CW(), "sleep_coach", PERSONA, VOICE, EXAMPLE, FACTS, TODAY)
    assert t.updates[0]["Key"]["sk"] == "COACH#sleep_coach#daily_reflection"
    assert writer.OUTPUT_TYPE != "daily_brief_sleep"


def test_a_changed_fact_busts_the_hash_even_though_the_text_would_still_gate_clean():
    """The honesty invariant, at this surface: new evidence must reach the reader."""
    moved = writer.facts_from("Sleep efficiency slipped to 81% across the week.", ["consistency"], 12)
    _fp, reused, _since = writer._reuse_or_none(_Table(_entry(GOOD)), _CW(), "sleep_coach", PERSONA, VOICE, EXAMPLE, moved, TODAY)
    assert reused is None


def test_the_cache_being_unavailable_degrades_to_generate_never_raises():
    class _Broken:
        def get_item(self, **kw):
            raise RuntimeError("table gone")

    fp, reused, since = writer._reuse_or_none(_Broken(), _CW(), "sleep_coach", PERSONA, VOICE, EXAMPLE, FACTS, TODAY)
    assert reused is None and since is None
    assert fp is not None or fp is None  # the point is that nothing raised


# ── the handler actually takes the branch (no Bedrock call on a hit) ──────────


def _drive(monkeypatch, entry, generate_should_run):
    calls = {"generate": 0, "put_object": []}

    class _S3:
        def put_object(self, **kw):
            calls["put_object"].append(kw)

    table = _Table(entry)

    class _Boto:
        @staticmethod
        def client(name, region_name=None):
            return _S3() if name == "s3" else _CW()

        @staticmethod
        def resource(name, region_name=None):
            class _R:
                Table = staticmethod(lambda _n: table)

            return _R()

    def _generate(*a, **kw):
        calls["generate"] += 1
        if not generate_should_run:
            raise AssertionError("the reuse path must not reach Bedrock")
        return GOOD

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(writer, "boto3", _Boto)
    monkeypatch.setattr(writer.persona_registry, "OPERATIONAL_COACH_IDS", ["sleep_coach"])
    monkeypatch.setattr(writer.persona_registry, "load_registry", lambda *a, **kw: {"personas": {"sleep_coach": PERSONA}})
    monkeypatch.setattr(writer, "_gather_facts", lambda *a, **kw: FACTS)
    monkeypatch.setattr(writer, "_voice", lambda *a, **kw: (VOICE, EXAMPLE))
    monkeypatch.setattr(writer, "_generate", _generate)
    out = writer.lambda_handler({}, None)
    return out, calls, table


def test_handler_serves_the_cached_reflection_without_generating(monkeypatch):
    out, calls, table = _drive(monkeypatch, _entry(GOOD), generate_should_run=False)
    assert out["written"] == 1
    assert calls["generate"] == 0, "a cache hit must skip the model call — that is the entire saving"
    import json

    payload = json.loads(calls["put_object"][0]["Body"].decode())
    served = payload["reflections"]["sleep_coach"]
    assert served["text"] == GOOD
    assert served["unchanged_since"] == "2026-08-18", "the published artifact discloses that the text was not regenerated"
    assert table.updates, "a hit must bump reuse bookkeeping so the skip-rate is auditable off-CloudWatch too"


def test_handler_generates_and_stores_on_a_miss(monkeypatch):
    out, calls, table = _drive(monkeypatch, None, generate_should_run=True)
    assert out["written"] == 1
    assert calls["generate"] == 1
    stored = [p for p in table.puts if p.get("sk") == "COACH#sleep_coach#daily_reflection"]
    assert stored, "a gate-passed generation must be cached, or tomorrow can never hit"
    assert stored[0]["output"] == GOOD
    assert stored[0]["part_hashes"], "per-part digests are what make the NEXT miss explain itself"


def test_a_generation_that_fails_the_gate_is_never_cached(monkeypatch):
    """Caching a held reflection would resurrect it every day it stayed unchanged."""
    fabricated = "Sleep efficiency moved to 71% this week, which caused the better mood."
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    table = _Table(None)

    class _Boto:
        @staticmethod
        def client(name, region_name=None):
            class _S3:
                def put_object(self, **kw):
                    pass

            return _S3() if name == "s3" else _CW()

        @staticmethod
        def resource(name, region_name=None):
            class _R:
                Table = staticmethod(lambda _n: table)

            return _R()

    monkeypatch.setattr(writer, "boto3", _Boto)
    monkeypatch.setattr(writer.persona_registry, "OPERATIONAL_COACH_IDS", ["sleep_coach"])
    monkeypatch.setattr(writer.persona_registry, "load_registry", lambda *a, **kw: {"personas": {"sleep_coach": PERSONA}})
    monkeypatch.setattr(writer, "_gather_facts", lambda *a, **kw: FACTS)
    monkeypatch.setattr(writer, "_voice", lambda *a, **kw: (VOICE, EXAMPLE))
    monkeypatch.setattr(writer, "_generate", lambda *a, **kw: fabricated)
    out = writer.lambda_handler({}, None)
    assert out["skipped"] == ["sleep_coach"]
    assert not [p for p in table.puts if p.get("sk") == "COACH#sleep_coach#daily_reflection"]
