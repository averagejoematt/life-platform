"""tests/test_coach_ensemble_reuse_2889.py — #2889 box 2, the ensemble surface.

`coach-ensemble-digest` is the platform's single most expensive daily Haiku call
(`max_tokens=6000`, and a surviving grounding finding buys a second one). It
synthesizes the eight coaches' stored `OUTPUT#` / `COMPRESSED#latest` records, so on
a cycle where not one coach moved, it pays full price to re-derive the identical
cross-coach reading.

`cycle_date` is deliberately NOT part of the fingerprint — otherwise the gate could
never fire, which is exactly how ADR-126's original wiring died (the rendered prompt
carried `generation_date`, so the hash busted every day and `GenerationSkippedUnchanged`
was never once emitted in ~2 months). Leaving the date out is only safe because the
reuse path re-runs the ADR-104 grounding gate against TODAY's inputs — that gate owns
the fabricated-date (#1242) and cycle-freshness (#1691/#1897) classes. These tests pin
that, and pin that only a gate-passed MODEL digest is ever cached.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from coach import coach_ensemble_digest as ced  # noqa: E402
from common import generation_cache as gc  # noqa: E402

CYCLE = "2026-08-24"
# Shaped exactly as `_gather_coach_data` returns it — {coach_id: {"output", "compressed"}} —
# so the grounding allow-list under test is derived from the real prompt material.
COACH_DATA = {
    "sleep_coach": {
        "output": {"content": "Sleep efficiency held near 88% across the week.", "themes": ["consistency"], "created_at": "2026-08-18"},
        "compressed": None,
    },
    "mind_coach": {
        "output": {"content": "Mood steady; the journal has been quiet.", "themes": ["quiet"], "created_at": "2026-08-18"},
        "compressed": None,
    },
}
CLEAN_DIGEST = {
    "coach_summaries": [
        {
            "coach_id": "sleep_coach",
            "key_concerns": ["Sleep efficiency near 88% is steady but the sample is small."],
            "key_recommendations": ["Keep the schedule steady."],
            "predictions_active": [],
            "wants_team_input_on": [],
        }
    ],
    "active_disagreements": [],
    "unanimous_flags": [],
    "created_at": "2026-08-18T19:00:00+00:00",
}


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


def _user_message(cycle=CYCLE):
    return ced._build_user_message(COACH_DATA, cycle, expected_coach_ids=sorted(COACH_DATA))


def _fingerprint():
    return gc.brief_fingerprint(gc.ensemble_parts(COACH_DATA, sorted(COACH_DATA), ced._ensemble_system_prompt()))


def _entry(digest, fingerprint=None):
    return {
        "brief_hash": fingerprint or _fingerprint(),
        "output": json.dumps(digest),
        "first_generated": "2026-08-18",
    }


def _install(monkeypatch, entry):
    table, cw = _Table(entry), _CW()
    monkeypatch.setattr(ced, "table", table)
    monkeypatch.setattr(ced, "_cw", cw)
    return table, cw


# ── the re-gate is what licenses leaving cycle_date out of the hash ───────────


def test_the_grounding_check_actually_discriminates():
    """Fixture guard. If `_still_grounded` said True for everything, every test below
    would pass while proving nothing."""
    um = _user_message()
    assert ced._still_grounded(CLEAN_DIGEST, um)
    fabricated = {
        **CLEAN_DIGEST,
        "coach_summaries": [{**CLEAN_DIGEST["coach_summaries"][0], "key_concerns": ["Efficiency collapsed to 41.7% overnight."]}],
    }
    assert not ced._still_grounded(fabricated, um)


def test_a_stored_digest_that_fails_todays_gate_is_not_reused(monkeypatch):
    """Identical inputs, matching fingerprint — and still 'regenerate', because the
    stored prose does not survive today's grounding check. Remove the re-gate from
    `reuse_if_still_valid` and this goes green while stale prose is republished."""
    fabricated = {
        **CLEAN_DIGEST,
        "coach_summaries": [{**CLEAN_DIGEST["coach_summaries"][0], "key_concerns": ["Efficiency collapsed to 41.7% overnight."]}],
    }
    _install(monkeypatch, _entry(fabricated))
    fp, reused, since = ced._reuse_digest(COACH_DATA, sorted(COACH_DATA), _user_message())
    assert reused is None and since is None
    assert fp == _fingerprint(), "the fingerprint still comes back so the fresh generation can be stored under it"


def test_a_clean_stored_digest_is_reused_and_counted(monkeypatch):
    table, cw = _install(monkeypatch, _entry(CLEAN_DIGEST))
    fp, reused, since = ced._reuse_digest(COACH_DATA, sorted(COACH_DATA), _user_message())
    assert reused is not None
    assert reused["coach_summaries"] == CLEAN_DIGEST["coach_summaries"]
    assert since == "2026-08-18"
    assert reused["_reused_since"] == "2026-08-18", "the stored digest must say it was reused, not claim to be fresh"
    assert reused["created_at"] != CLEAN_DIGEST["created_at"], "created_at records when the row was WRITTEN"
    assert table.updates and table.updates[0]["Key"]["sk"] == "COACH#ensemble#ensemble_digest"
    dims = {d["Name"]: d["Value"] for d in cw.calls[0]["MetricData"][0]["Dimensions"]}
    assert dims == {"Coach": "ensemble", "Surface": "ensemble_digest"}
    assert fp


def test_one_coach_moving_busts_the_hash(monkeypatch):
    """The honesty invariant at the cross-coach level."""
    _install(monkeypatch, _entry(CLEAN_DIGEST))
    moved = {
        **COACH_DATA,
        "sleep_coach": {
            "output": {"content": "Sleep efficiency slipped to 81%.", "themes": [], "created_at": "2026-08-24"},
            "compressed": None,
        },
    }
    _fp, reused, _since = ced._reuse_digest(moved, sorted(moved), _user_message())
    assert reused is None


def test_a_new_cycle_date_alone_does_not_bust_the_hash(monkeypatch):
    """The design decision, asserted rather than assumed — and safe only because of
    `test_a_stored_digest_that_fails_todays_gate_is_not_reused` above."""
    _install(monkeypatch, _entry(CLEAN_DIGEST))
    _fp, reused, _since = ced._reuse_digest(COACH_DATA, sorted(COACH_DATA), _user_message("2026-09-02"))
    assert reused is not None


def test_a_broken_cache_degrades_to_generate(monkeypatch):
    class _Broken:
        def get_item(self, **kw):
            raise RuntimeError("table gone")

    monkeypatch.setattr(ced, "table", _Broken())
    monkeypatch.setattr(ced, "_cw", _CW())
    fp, reused, since = ced._reuse_digest(COACH_DATA, sorted(COACH_DATA), _user_message())
    assert (reused, since) == (None, None)
    assert fp is None or isinstance(fp, str)


# ── the handler takes the branch, and stores only what deserves storing ───────


def _drive(monkeypatch, entry, haiku_result, expect_haiku=None):
    table, _cw = _install(monkeypatch, entry)
    calls = {"haiku": 0}

    def _haiku(**kw):
        # Counted, never raised: the handler wraps generation in `except Exception`,
        # so an assertion thrown here would be swallowed into the fallback path and
        # the test would report the wrong failure. The count is checked by the caller.
        calls["haiku"] += 1
        return haiku_result

    monkeypatch.setattr(ced, "_gather_coach_data", lambda ids: COACH_DATA)
    monkeypatch.setattr(ced, "_call_haiku", _haiku)
    monkeypatch.setattr(ced, "_write_digest", lambda d, c: None)
    monkeypatch.setattr(ced, "_update_coach_compressed_states", lambda d, cd, c: None)
    out = ced.lambda_handler({"cycle_date": CYCLE, "coach_ids": sorted(COACH_DATA)}, None)
    return out, calls, table


def test_handler_returns_the_cached_digest_without_calling_bedrock(monkeypatch):
    out, calls, table = _drive(monkeypatch, _entry(CLEAN_DIGEST), None, expect_haiku=False)
    assert calls["haiku"] == 0, "a cache hit must skip the 6000-token call — that is the entire saving"
    assert out["coach_summaries"] == CLEAN_DIGEST["coach_summaries"]
    assert out["_reused_since"] == "2026-08-18"
    assert table.updates, "a hit must bump reuse bookkeeping"


def test_handler_caches_a_gate_passed_model_digest(monkeypatch):
    out, calls, table = _drive(monkeypatch, None, CLEAN_DIGEST, expect_haiku=True)
    assert calls["haiku"] == 1
    stored = [p for p in table.puts if p.get("sk") == "COACH#ensemble#ensemble_digest"]
    assert stored, "a gate-passed digest must be cached, or tomorrow can never hit"
    assert json.loads(stored[0]["output"])["coach_summaries"] == CLEAN_DIGEST["coach_summaries"]
    assert out["coach_summaries"]


def test_a_non_dict_llm_response_falls_back_and_is_NOT_cached(monkeypatch):
    """Caching a fallback would let a degraded cycle be replayed later as if it were
    the real cross-coach reading."""
    _out, calls, table = _drive(monkeypatch, None, "not a dict", expect_haiku=True)
    assert calls["haiku"] == 1
    assert not [p for p in table.puts if p.get("sk") == "COACH#ensemble#ensemble_digest"]


def test_a_grounding_HOLD_is_NOT_cached(monkeypatch):
    fabricated = {
        "coach_summaries": [{"coach_id": "sleep_coach", "key_concerns": ["Efficiency collapsed to 41.7% overnight."]}],
        "active_disagreements": [],
        "unanimous_flags": [],
    }
    out, _calls, table = _drive(monkeypatch, None, fabricated, expect_haiku=True)
    assert out.get("_grounding_hold") is True
    assert not [p for p in table.puts if p.get("sk") == "COACH#ensemble#ensemble_digest"]
