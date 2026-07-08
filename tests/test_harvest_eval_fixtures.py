"""test_harvest_eval_fixtures.py — the #812 harvest loop's deterministic contract.

Pins: a retained flagged draft becomes a canary candidate whose expected checks
are derived from the recorded findings AND re-verified by replay; a corrected
final becomes a golden candidate only if it replays clean; candidates the gate
can no longer catch (or goldens that now flag) are REJECTED, never packed.
Fully offline — fake retention records, no AWS.
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harvest_eval_fixtures as hv  # noqa: E402


def _rec(**kw):
    base = {
        "draft": "",
        "final": "",
        "verdict": "flagged_kept_best",
        "findings": [],
        "allowed": [],
        "facts": None,
        "extra": {},
        "_sk": "TS#2026-07-01T00:00:00+00:00#abcd1234",
        "_created_at": "2026-07-01T00:00:00+00:00",
    }
    base.update(kw)
    return base


def _by_surface(**surfaces):
    out = {s: [] for s in hv.harness.SURFACES}
    out.update(surfaces)
    return out


def test_flagged_pair_yields_validated_canary_and_golden():
    records = _by_surface(
        chronicle=[
            _rec(
                draft="The scale fell from 306.2 to 300.8 this week.",
                final="The scale read 300.8 this week.",
                verdict="flagged_corrected",
                findings=[{"type": "fabricated_number", "claimed": 306.2, "detail": "306.2 nowhere in the packet"}],
                allowed=[300.8],
            )
        ]
    )
    out = hv.build_candidates(records)
    assert len(out["canaries"]) == 1 and len(out["golden"]) == 1, out
    cn = out["canaries"][0]
    assert cn["mode"] == "generic"
    assert cn["expect_checks"] == ["evidence_ceiling"]
    assert cn["mutation"].startswith("HARVESTED REAL FAULT")
    assert "EVALRET#chronicle" in cn["provenance"]
    assert out["golden"][0]["reference_output"] == "The scale read 300.8 this week."
    assert not out["rejected"]


def test_uncatchable_canary_is_rejected():
    """If the recorded 'fault' number is actually IN the allow-list, the replay
    can't catch it — packing it would poison the suite with a permanent red."""
    records = _by_surface(
        chronicle=[
            _rec(
                draft="The scale read 300.8 this week.",
                findings=[{"type": "fabricated_number", "claimed": 300.8, "detail": "stale finding"}],
                allowed=[300.8],
            )
        ]
    )
    out = hv.build_candidates(records)
    assert not out["canaries"] and len(out["rejected"]) == 1, out


def test_golden_that_still_flags_is_rejected():
    records = _by_surface(
        board_ask=[
            _rec(
                draft="HRV climbed to 58 ms.",
                final="HRV climbed to 61 ms.",  # "corrected" but still ungrounded
                verdict="flagged_corrected",
                findings=[{"type": "fabricated_number", "claimed": 58.0, "detail": "58 nowhere in inputs"}],
                allowed=[42.0],
            )
        ]
    )
    out = hv.build_candidates(records)
    assert len(out["canaries"]) == 1  # the draft is still a good canary
    assert not out["golden"] and any("findings" in r["reason"] for r in out["rejected"]), out


def test_som_causal_flag_round_trips():
    records = _by_surface(
        state_of_matthew=[
            _rec(
                draft="Recovery hit 73.6 because the deficit eased.",
                final="",
                verdict="flagged_fallback",
                findings=[{"type": "causal_language", "detail": "banned causal connective 'because'"}],
                allowed=[73.6],
            )
        ]
    )
    out = hv.build_candidates(records)
    assert len(out["canaries"]) == 1
    assert out["canaries"][0]["expect_checks"] == ["causal_language"]


def test_memoir_reason_mapping():
    assert hv._expect_checks("memoir", [{"type": "memoir_gate", "detail": "fabricated numbers: [19.0]"}]) == ["evidence_ceiling"]
    assert hv._expect_checks("memoir", [{"type": "memoir_gate", "detail": "no_miss_cited_despite_refuted_learnings"}]) == ["miss_dodged"]
    assert hv._expect_checks("memoir", [{"type": "memoir_gate", "detail": "empty"}]) == ["empty_output"]


# ── #744: coach_brief is retained but has no golden_surface_eval adapter yet ──
def test_split_harness_ready_separates_unadaptered_surfaces():
    """`eval_retention.SURFACES` includes `coach_brief` (#744) but the harness
    (`golden_surface_eval.SURFACES`) does not — it has no replay adapter for it.
    The split must route coach_brief records to `retention_only`, never into
    `build_candidates` (which would silently mis-evaluate them through the
    wrong check dimension), while still reporting their count so nothing
    retained goes unnoticed."""
    records = {
        "chronicle": [_rec(draft="x")],
        "coach_brief": [_rec(draft="y"), _rec(draft="z")],
        "board_ask": [],
    }
    ready, retention_only = hv._split_harness_ready(records, hv.harness.SURFACES)
    assert set(ready) == {"chronicle", "board_ask"}
    assert retention_only == {"coach_brief": 2}  # board_ask excluded: zero records


def test_split_harness_ready_empty_when_all_covered():
    records = _by_surface(chronicle=[_rec(draft="x")])
    ready, retention_only = hv._split_harness_ready(records, hv.harness.SURFACES)
    assert set(ready) == set(hv.harness.SURFACES)
    assert retention_only == {}
