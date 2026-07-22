"""tests/test_review_pack_ranker.py — the Hybrid ranker + tagger (#1688, epic #1687 S1).

Covers lambdas/review_pack_ranker.py:
  - numbered_entries: deterministic, stable numbering (the #1690 contract)
  - each deterministic heuristic (baseline-mismatch, ungrounded-behavioral, claim
    density, hedge absence, genesis mismatch, cross-coach inconsistency)
  - error-class tagging stays inside coach_corrections.ERROR_CLASSES
  - the HYBRID critic tier-gate: tier ≥ 2 does NOT call Bedrock; tier ≤ 1 does
  - stack-ranking order (most-likely-wrong → least) + graceful quiet-week degrade

Run:  python3 -m pytest tests/test_review_pack_ranker.py -v
"""

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "emails"))

import review_pack_ranker as rpr  # noqa: E402
from coach_corrections import ERROR_CLASSES  # noqa: E402

START = "2026-07-22"
BASELINE = 321.38


def _entry(surface, text, archived_at, variant=None, meta=None, key=None):
    return {
        "schema": 1,
        "surface": surface,
        "variant": variant,
        "date": archived_at[:10],
        "archived_at": archived_at,
        "text": text,
        "meta": meta or {},
        "_key": key or f"generated/qa_archive/text/{archived_at[:10]}/{surface}--{archived_at[11:19]}.json",
    }


# ── numbering (the #1690 contract) ──────────────────────────────────────────────


def test_numbered_entries_is_deterministic_regardless_of_input_order():
    a = _entry("chronicle", "c", "2026-07-20T09:00:00+00:00", key="k/a")
    b = _entry("coach_brief", "b", "2026-07-20T10:00:00+00:00", variant="mind", key="k/b")
    c = _entry("coach_brief", "b2", "2026-07-19T08:00:00+00:00", variant="nutrition", key="k/c")

    forward = rpr.numbered_entries({"chronicle": [a], "coach_brief": [b, c]})
    # Same entries, different in-memory ordering (reversed lists / dict order).
    reverse = rpr.numbered_entries({"coach_brief": [c, b], "chronicle": [a]})

    assert [(n, e["_key"]) for n, e in forward] == [(n, e["_key"]) for n, e in reverse]
    # chronicle (rank 0) numbers before coach_brief (rank 2); within coach_brief the
    # older date sorts first.
    assert forward[0][1]["_key"] == "k/a"
    assert [e["_key"] for _, e in forward] == ["k/a", "k/c", "k/b"]
    assert [n for n, _ in forward] == [1, 2, 3]


def test_numbering_unknown_surface_sorts_after_known():
    known = _entry("chronicle", "c", "2026-07-20T09:00:00+00:00", key="k/known")
    unknown = _entry("brand_new", "x", "2026-07-20T09:00:00+00:00", key="k/unknown")
    numbered = rpr.numbered_entries({"brand_new": [unknown], "chronicle": [known]})
    assert numbered[0][1]["_key"] == "k/known"
    assert numbered[-1][1]["_key"] == "k/unknown"


def test_surface_order_matches_the_pack():
    import ai_review_pack_lambda as arp

    assert tuple(arp.SURFACE_ORDER) == tuple(rpr.DEFAULT_SURFACE_ORDER)


# ── deterministic heuristics ────────────────────────────────────────────────────


def test_baseline_mismatch_flags_a_stale_starting_weight():
    e = _entry(
        "coach_brief",
        "Starting weight: 315 lb. You have momentum now.",
        "2026-07-25T09:00:00+00:00",
        variant="nutrition",
        meta={"generation_date": "2026-07-25"},
    )
    findings = rpr.baseline_mismatch_findings(e, baseline_lbs=BASELINE, start_date_iso=START)
    assert findings and any(f["type"] == "stale_baseline" for f in findings)


def test_baseline_mismatch_ignored_for_non_coach_brief():
    e = _entry("chronicle", "Starting weight: 315 lb.", "2026-07-25T09:00:00+00:00", meta={"generation_date": "2026-07-25"})
    assert rpr.baseline_mismatch_findings(e, baseline_lbs=BASELINE, start_date_iso=START) == []


def test_behavioral_findings_flags_ungrounded_action_claim():
    findings = rpr.behavioral_findings("You maintained your eating window today. Great job.")
    assert findings and findings[0]["type"] == "ungrounded_behavioral"


def test_behavioral_findings_ignores_advice_and_numbered_claims():
    # modal / conditional → advice, not a completed-action claim
    assert rpr.behavioral_findings("You could maintain your eating window tomorrow.") == []
    assert rpr.behavioral_findings("Try to hit your window each day.") == []
    # a number is log-shaped evidence — out of scope for THIS heuristic
    assert rpr.behavioral_findings("You hit 190 g of protein today.") == []


def test_claim_and_hedge_stats():
    stats = rpr.claim_stats("Your RHR was 52 bpm and HRV 68 ms across 3 nights.")
    assert stats["count"] >= 3
    assert rpr.hedge_stats("This is roughly on track, approximately.")["hedged"] is True
    assert rpr.hedge_stats("You weigh 315 lb.")["hedged"] is False


def test_genesis_mismatch_flags_a_pre_genesis_brief():
    e = _entry("coach_brief", "hi", "2026-07-20T09:00:00+00:00", variant="mind", meta={"generation_date": "2026-07-20"})
    f = rpr.genesis_mismatch_finding(e, start_date_iso=START)
    assert f and f["type"] == "genesis_mismatch"
    # a brief generated on/after genesis is fine
    ok = _entry("coach_brief", "hi", "2026-07-25T09:00:00+00:00", variant="mind", meta={"generation_date": "2026-07-25"})
    assert rpr.genesis_mismatch_finding(ok, start_date_iso=START) is None


def test_cross_coach_inconsistency_flags_conflicting_protein_targets():
    nut = _entry("coach_brief", "Aim for 170 g of protein daily.", "2026-07-25T09:00:00+00:00", variant="nutrition", key="k/nut")
    stg = _entry("coach_brief", "Target 190g protein to build muscle.", "2026-07-25T10:00:00+00:00", variant="strength", key="k/stg")
    out = rpr.cross_coach_findings({"coach_brief": [nut, stg]})
    assert "k/nut" in out and "k/stg" in out
    assert out["k/nut"][0]["type"] == "cross_coach_inconsistency"


def test_no_cross_coach_flag_when_coaches_agree():
    a = _entry("coach_brief", "Aim for 180 g of protein.", "2026-07-25T09:00:00+00:00", variant="nutrition", key="k/a")
    b = _entry("coach_brief", "Keep protein at 180g.", "2026-07-25T10:00:00+00:00", variant="strength", key="k/b")
    assert rpr.cross_coach_findings({"coach_brief": [a, b]}) == {}


# ── analysis / tagging ──────────────────────────────────────────────────────────


def test_analyze_entry_tags_from_error_classes_vocabulary():
    e = _entry(
        "coach_brief",
        "Starting weight: 315 lb. You maintained your window today.",
        "2026-07-25T09:00:00+00:00",
        variant="nutrition",
        meta={"generation_date": "2026-07-25"},
    )
    a = rpr.analyze_entry(e, baseline_lbs=BASELINE, start_date_iso=START)
    assert a["error_class"] in ERROR_CLASSES
    # baseline is the most-severe class present
    assert a["error_class"] == "stale-baseline"
    assert a["checkable_claim"]
    assert a["deterministic_score"] > 0


def test_analyze_entry_hedged_safe_tag():
    e = _entry("board_ask", "This is roughly 5 lb, approximately, and may vary.", "2026-07-25T09:00:00+00:00")
    a = rpr.analyze_entry(e, baseline_lbs=BASELINE, start_date_iso=START)
    assert a["error_class"] == "hedged-safe"


# ── HYBRID critic tier-gate ─────────────────────────────────────────────────────


def _one_pack():
    return {"coach_brief": [_entry("coach_brief", "Starting weight: 315 lb.", "2026-07-25T09:00:00+00:00", variant="nutrition")]}


def test_critic_skipped_at_tier_two_no_bedrock_call():
    invoke = MagicMock()
    res = rpr.rank_pack(_one_pack(), baseline_lbs=BASELINE, start_date_iso=START, tier_reader=lambda: 2, invoke_fn=invoke)
    invoke.assert_not_called()
    assert res["critic_ran"] is False
    assert res["tier"] == 2


def test_critic_runs_at_tier_one_and_adjusts_score():
    def fake_invoke(body, model_name=None):
        assert model_name == "claude-haiku-4-5-20251001"
        assert isinstance(body["system"], list) and body["system"][0].get("cache_control")  # prompt-cached
        return {"content": [{"type": "text", "text": '[{"n": 1, "wrongness": 1.0, "why": "wrong baseline"}]'}]}

    pack = _one_pack()
    res = rpr.rank_pack(pack, baseline_lbs=BASELINE, start_date_iso=START, tier_reader=lambda: 1, invoke_fn=fake_invoke)
    assert res["critic_ran"] is True
    a = res["analyses"][1]
    assert a["critic"] == 1.0
    assert a["score"] == round(a["deterministic_score"] + rpr._W_CRITIC_MAX, 4)


def test_critic_failsoft_keeps_deterministic_ranking():
    def boom(body, model_name=None):
        raise RuntimeError("bedrock down")

    res = rpr.rank_pack(_one_pack(), baseline_lbs=BASELINE, start_date_iso=START, tier_reader=lambda: 0, invoke_fn=boom)
    assert res["critic_ran"] is False
    assert res["analyses"][1]["score"] == res["analyses"][1]["deterministic_score"]


def test_run_critic_parses_defensively():
    resp = {"content": [{"type": "text", "text": 'noise [{"n":1,"wrongness":0.5},{"n":2,"wrongness":"bad"}] tail'}]}
    parsed = rpr.run_critic([(1, {"checkable_claim": "a"}), (2, {"checkable_claim": "b"})], lambda b, model_name=None: resp)
    assert parsed == {1: 0.5}  # malformed row dropped


# ── stack-ranking + quiet week ──────────────────────────────────────────────────


def test_rank_pack_orders_most_wrong_first():
    wrong = _entry(
        "coach_brief",
        "Starting weight: 300 lb. You maintained your window today.",
        "2026-07-25T09:00:00+00:00",
        variant="nutrition",
        key="k/wrong",
    )
    clean = _entry("chronicle", "A calm reflective week.", "2026-07-25T09:00:00+00:00", key="k/clean")
    res = rpr.rank_pack({"chronicle": [clean], "coach_brief": [wrong]}, baseline_lbs=BASELINE, start_date_iso=START, tier_reader=lambda: 9)
    ranked = res["ranked"]
    assert ranked[0][1]["_key"] == "k/wrong"  # highest wrongness first
    assert ranked[-1][1]["_key"] == "k/clean"


def test_quiet_week_degrades_and_never_calls_critic():
    invoke = MagicMock()
    res = rpr.rank_pack({}, baseline_lbs=BASELINE, start_date_iso=START, tier_reader=lambda: 0, invoke_fn=invoke)
    invoke.assert_not_called()  # no items → no critic even at tier 0
    assert res["numbered"] == []
    assert res["ranked"] == []
    assert res["critic_ran"] is False
