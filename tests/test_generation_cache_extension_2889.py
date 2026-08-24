"""tests/test_generation_cache_extension_2889.py — #2889 box 2.

ADR-126's hash-and-reuse seam spreads from the coach brief to the other daily
narrative surfaces (coach-daily-reflection, coach-ensemble-digest). What is pinned
here is the ONE rule that makes that spread safe:

    A CACHE HIT SKIPS THE GENERATION, NEVER THE GATE.

The coach brief could get away with reusing the gate VERDICT along with the text,
because its gate is a pure function of the fingerprinted inputs. No other surface
is like that. `grounded_generation`'s fabricated-date (#1242) and cycle-freshness
(#1691/#1897) classes are functions of TODAY: a reflection that honestly said
"Day 4" when it was written is a stale-Day-N violation when it is republished on
Day 9, from byte-identical inputs. Reusing the verdict ships it; re-running the
gate catches it.

Every test below is written to FAIL if that re-gate is removed, weakened to
fail-open, or fed the wrong text — not merely to observe the happy path.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import generation_cache as gc  # noqa: E402

_PARTS = {"facts": {"summary": "sleep efficiency 88%", "n": 12}, "voice": "dry"}
_FP = gc.brief_fingerprint(_PARTS)


class _Table:
    """Minimal DDB double: one stored cache entry, plus call recording."""

    def __init__(self, entry=None):
        self.entry = entry
        self.updates = []
        self.puts = []

    def get_item(self, Key):
        return {"Item": self.entry} if self.entry else {}

    def update_item(self, **kw):
        self.updates.append(kw)

    def put_item(self, Item):
        self.puts.append(Item)


def _hit_table(output="stored reflection text", fingerprint=_FP):
    return _Table({"brief_hash": fingerprint, "output": output, "first_generated": "2026-08-14"})


class _Spy:
    """A revalidate double that records what it was asked about."""

    def __init__(self, verdict=True, boom=False):
        self.verdict, self.boom, self.seen = verdict, boom, []

    def __call__(self, text):
        self.seen.append(text)
        if self.boom:
            raise RuntimeError("gate blew up")
        return self.verdict


# ── the re-gate is MANDATORY, not advisory ────────────────────────────────────


def test_a_hit_whose_stored_output_fails_todays_gate_is_not_reused():
    """THE test. Inputs are byte-identical (the fingerprint matches), and the answer
    is still 'regenerate', because the stored text no longer passes TODAY.

    Delete the revalidate call from reuse_if_still_valid and this goes green while
    the platform quietly republishes stale Day-N prose."""
    spy = _Spy(verdict=False)
    fp, reused, since = gc.reuse_if_still_valid(_hit_table(), "sleep_coach", "daily_reflection", _PARTS, spy)
    assert reused is None, "a stored output that fails today's gate must never be reused"
    assert since is None
    assert fp == _FP, "the fingerprint is still returned so the caller can store the fresh generation under it"
    assert spy.seen == ["stored reflection text"], "the re-gate must judge the STORED text, not the parts"


def test_a_raising_revalidate_fails_CLOSED():
    """The asymmetry from generation_cache's header: a spurious regeneration costs
    money, a spurious reuse costs the truth. An exception must therefore land on the
    money side. A bare `except: pass` around the re-gate would invert this."""
    fp, reused, since = gc.reuse_if_still_valid(_hit_table(), "sleep_coach", "daily_reflection", _PARTS, _Spy(boom=True))
    assert (reused, since) == (None, None)
    assert fp == _FP


def test_a_hit_that_still_passes_is_reused_verbatim():
    spy = _Spy(verdict=True)
    fp, reused, since = gc.reuse_if_still_valid(_hit_table(), "sleep_coach", "daily_reflection", _PARTS, spy)
    assert reused == "stored reflection text"
    assert since == "2026-08-14"
    assert fp == _FP
    assert len(spy.seen) == 1, "the gate runs exactly once on a hit — it is the whole point of the seam"


def test_a_falsy_but_non_False_verdict_still_blocks_reuse():
    """`bool()` the verdict, don't `is False` it: a gate that returns [] findings or
    "" is saying no, and a truthiness bug here is a silent stale-serve."""
    for falsy in (None, 0, "", []):
        _fp, reused, _since = gc.reuse_if_still_valid(_hit_table(), "c", "t", _PARTS, lambda _t, v=falsy: v)
        assert reused is None, f"falsy verdict {falsy!r} must block reuse"


# ── a MISS must not pay for a gate it has nothing to gate ─────────────────────


def test_a_miss_never_calls_the_revalidator():
    spy = _Spy(verdict=True)
    fp, reused, since = gc.reuse_if_still_valid(_Table(), "sleep_coach", "daily_reflection", _PARTS, spy)
    assert (reused, since) == (None, None)
    assert fp == _FP
    assert spy.seen == [], "nothing is stored — there is no text to re-gate"


def test_a_fingerprint_mismatch_is_a_miss_even_with_a_passing_gate():
    """The gate is an ADDITIONAL barrier, never a substitute for the hash. A gate
    that says 'this text is fine' does not license serving it against changed inputs."""
    spy = _Spy(verdict=True)
    _fp, reused, _since = gc.reuse_if_still_valid(_hit_table(fingerprint="stale-hash"), "c", "t", _PARTS, spy)
    assert reused is None
    assert spy.seen == []


def test_an_entry_with_an_empty_output_is_a_miss():
    t = _Table({"brief_hash": _FP, "output": "", "first_generated": "2026-08-14"})
    _fp, reused, _since = gc.reuse_if_still_valid(t, "c", "t", _PARTS, _Spy(verdict=True))
    assert reused is None


# ── the named part sets: dropping a part NARROWS the fingerprint ──────────────
#
# `reflection_parts` / `ensemble_parts` exist so the names live in this module and a
# call site cannot quietly drop one. These assert the property that matters — every
# named part actually reaches the digest — rather than the literal key list, so they
# stay honest if a part is renamed but break if one stops counting.


def _reflection_kwargs():
    return {
        "persona": {"name": "Sol", "domain": "sleep"},
        "voice_rules": '{"tone": "dry"}',
        "example": "A sample in voice.",
        "facts": {"summary": "efficiency 88%", "themes": ["consistency"], "n": 12},
    }


def test_every_named_reflection_part_moves_the_fingerprint():
    base = gc.reflection_parts(**_reflection_kwargs())
    for name in base:
        mutated = dict(_reflection_kwargs())
        mutated[name] = {"MUTATED": True}
        assert gc.brief_fingerprint(gc.reflection_parts(**mutated)) != gc.brief_fingerprint(
            base
        ), f"part '{name}' does not reach the fingerprint — reuse could serve output generated from a different {name}"


def _ensemble_kwargs():
    return {
        "coach_data": {"sleep_coach": {"summary": "steady", "themes": ["consistency"]}},
        "expected_coach_ids": ["sleep_coach", "mind_coach"],
        "system_prompt": "You synthesize the coaches.",
    }


def test_every_named_ensemble_part_moves_the_fingerprint():
    base = gc.ensemble_parts(**_ensemble_kwargs())
    for name in base:
        mutated = dict(_ensemble_kwargs())
        mutated[name] = ["MUTATED"]
        assert gc.brief_fingerprint(gc.ensemble_parts(**mutated)) != gc.brief_fingerprint(
            base
        ), f"part '{name}' does not reach the fingerprint"


def test_ensemble_fingerprint_ignores_the_cycle_date_by_construction():
    """`cycle_date` is deliberately not a part — if no coach moved, the cross-coach
    reading has not moved either. This is only safe because the reuse path re-gates,
    which the tests above pin. Asserted so the omission reads as a decision."""
    a = gc.ensemble_parts(**_ensemble_kwargs())
    b = gc.ensemble_parts(**_ensemble_kwargs())
    assert gc.brief_fingerprint(a) == gc.brief_fingerprint(b)
    assert "cycle_date" not in a


def test_a_coach_dropping_out_of_the_expected_roster_busts_the_fingerprint():
    """The honesty invariant at the ensemble level: 'who was expected but absent' is
    content the digest narrates, so it may not be silently reused across a roster change."""
    a = gc.ensemble_parts(**_ensemble_kwargs())
    b = gc.ensemble_parts(**{**_ensemble_kwargs(), "expected_coach_ids": ["sleep_coach"]})
    assert gc.brief_fingerprint(a) != gc.brief_fingerprint(b)


# ── the metric: the skip-rate has to be attributable to a surface ─────────────


class _CW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def test_surface_dimension_is_emitted_when_given():
    cw = _CW()
    gc.emit_skip_metric(cw, "LifePlatform/AI", "sleep_coach", surface="daily_reflection")
    dims = {d["Name"]: d["Value"] for d in cw.calls[0]["MetricData"][0]["Dimensions"]}
    assert dims == {"Coach": "sleep_coach", "Surface": "daily_reflection"}
    assert cw.calls[0]["MetricData"][0]["MetricName"] == "GenerationSkippedUnchanged"


def test_metric_emit_stays_non_fatal():
    """Cost telemetry may never take down a generation path."""

    class _Boom:
        def put_metric_data(self, **kw):
            raise RuntimeError("AccessDenied")

    gc.emit_skip_metric(_Boom(), "LifePlatform/AI", "sleep_coach", surface="daily_reflection")


# ── bookkeeping still lands, so the skip-rate is auditable without CloudWatch ──


def test_record_reuse_bumps_the_counter_on_the_right_row():
    t = _hit_table()
    gc.record_reuse(t, "ensemble", "ensemble_digest", "2026-08-24")
    assert t.updates[0]["Key"] == {"pk": gc.CACHE_PK, "sk": gc.cache_sk("ensemble", "ensemble_digest")}
    assert ":one" in t.updates[0]["ExpressionAttributeValues"]
