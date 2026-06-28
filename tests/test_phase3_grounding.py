"""Phase-3 accuracy remediation — day-selection + impossible-value guards.

Covers the structural "no contradictions" fixes:
  * ai_summaries.build_data_summary narrates the SAME whoop the vitals block shows
    (primary_whoop = today-if-finalized else yesterday) — kills the recovery 30-vs-86 split.
  * ingestion_validator flags impossible canonical vitals on the computed_metrics record.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import ai_summaries  # noqa: E402
import ingestion_validator as iv  # noqa: E402

# ── Day-selection: the narrative must read primary_whoop, not always-yesterday ──


def test_build_data_summary_prefers_primary_whoop():
    """When primary_whoop is set (today, finalized), the narrative recovery follows it."""
    data = {
        "date": "2026-06-26",
        "whoop": {"recovery_score": 86, "strain": 8.0},  # yesterday
        "primary_whoop": {"recovery_score": 30, "strain": 12.0},  # chosen day (today)
    }
    out = ai_summaries.build_data_summary(data, {})
    assert out["recovery_score"] == 30, "narrative must use the chosen primary_whoop, not yesterday"
    assert out["strain"] == 12.0


def test_build_data_summary_falls_back_to_whoop():
    """Callers that never set primary_whoop keep the legacy yesterday behaviour."""
    data = {"date": "2026-06-26", "whoop": {"recovery_score": 86, "strain": 8.0}}
    out = ai_summaries.build_data_summary(data, {})
    assert out["recovery_score"] == 86


def test_recovery_zero_is_honoured_not_skipped():
    """A real recovery of 0 must not be silently dropped (the `or` bug)."""
    data = {"date": "2026-06-26", "primary_whoop": {"recovery_score": 0, "strain": 5.0}}
    out = ai_summaries.build_data_summary(data, {})
    assert out["recovery_score"] == 0


# ── Impossible-value guard on the canonical record ──


def _base_item(**extra):
    item = {
        "pk": "USER#matthew#SOURCE#computed_metrics",
        "sk": "DATE#2026-06-26",
        "date": "2026-06-26",
        "computed_at": "2026-06-26T17:40:00+00:00",
        "day_grade_score": 70,
    }
    item.update(extra)
    return item


def test_sane_vitals_pass_clean():
    r = iv.validate_item("computed_metrics", _base_item(recovery_pct=86, hrv_ms=51.5, rhr_bpm=58, protein_g_avg=140.7), "2026-06-26")
    assert not r.should_skip_ddb
    assert not any("recovery_pct" in w for w in r.warnings)


def test_impossible_recovery_warns():
    r = iv.validate_item("computed_metrics", _base_item(recovery_pct=305), "2026-06-26")
    assert any("recovery_pct" in w for w in r.warnings), "recovery > 100 must warn"
    # WARN, not CRITICAL — the rest of the day's metrics still write.
    assert not r.should_skip_ddb


def test_impossible_rhr_warns():
    r = iv.validate_item("computed_metrics", _base_item(rhr_bpm=5), "2026-06-26")
    assert any("rhr_bpm" in w for w in r.warnings)


# ── 3a: coach shared snapshot — authoritative facts injected into the system prompt ──

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))


def _load_coach_module():
    import ai_expert_analyzer_lambda as ax  # noqa: E402

    # Bypass DDB — inject canonical facts directly into the cache.
    ax._CANON_FACTS_CACHE.clear()
    ax._CANON_FACTS_CACHE.update(
        {
            "_loaded": True,
            "facts": {
                "recovery_pct": 30.0,
                "hrv_ms": 25.2,
                "rhr_bpm": 58.0,
                "protein_g_avg": 140.7,
                "protein_g_target": 190.0,
                "protein_g_floor": 170.0,
                "latest_weight": 300.8,
                "weekly_rate_lbs": -7.33,
                "as_of": "2026-06-26",
            },
        }
    )
    return ax


def test_shared_prompt_carries_authoritative_facts():
    ax = _load_coach_module()
    prompt = ax._build_shared_system_prompt()
    assert "AUTHORITATIVE FACTS" in prompt
    # The real intake (140.7) is present and the prompt forbids substituting target/floor.
    assert "140.7" in prompt
    assert "never state intake as the target or floor" in prompt
    # HRV carries its unit guard.
    assert "MILLISECONDS" in prompt or "ms" in prompt


def test_canonical_protein_target_not_hardcoded_190_path():
    ax = _load_coach_module()
    facts = ax._load_canonical_facts()
    assert facts["protein_g_target"] == 190.0
    assert facts["protein_g_avg"] == 140.7  # the actual intake the coaches must cite
