"""tests/test_phase_plausibility_1922.py — the deterministic half of Reader Truth.

#1922 (ADR-105 "deterministic computation before any LLM verdict", ADR-147):
numeric phase-bound claims are arithmetic, and the LLM got `5 <= 6` wrong six
times in a row while missing exactly the class a comparison catches. This file
pins:

  - the REPLAY acceptance: both true 2026-08-01 findings (`weight_delta_30d`
    and `hrv_30d_avg` published non-null on Day 5, #1917) are caught with no LLM;
  - zero findings against a correct payload of the current shape (it must not
    inherit the false positives it replaces — 5-day window on Day 6 is CORRECT);
  - the registry contract: EVERY gated intensive `_Nd` field in the shared
    registry is covered (parametrized over the registry, not hand-listed);
  - gap-declared debt (#1919) and extensive counts are deliberately exempt;
  - span/day/prose rules, pre-start behavior, and fail-soft parse warnings;
  - the qa_smoke wiring: the deterministic pass runs UNCONDITIONALLY — a budget
    pause silences only the LLM half (the #1920 26-day dark window cannot
    recur for arithmetic) — and the LLM rubric no longer claims
    `impossible_number` (the overlap is owned by this module).
"""

import os
import sys

import pytest

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_LAMBDAS = os.path.join(_REPO, "lambdas")
for p in (_LAMBDAS, os.path.join(_LAMBDAS, "operational")):
    if p not in sys.path:
        sys.path.insert(0, p)

from operational import phase_plausibility as pp  # noqa: E402
from web.window_registry import INTENSIVE, REGISTRY, window_days  # noqa: E402

# ── the replay acceptance: both true 2026-08-01 findings, no LLM ────────────


def test_replays_both_true_2026_08_01_findings():
    payload = {"vitals": {"weight_delta_30d": -4.1, "hrv_30d_avg": 55.2, "hrv_avg_ms": 55.2}}
    findings = pp.check_payload("/api/vitals", payload, day_n=5)
    noted = {f["note"].split(" = ")[0] for f in findings}
    assert "vitals.weight_delta_30d" in noted
    assert "vitals.hrv_30d_avg" in noted
    assert all(f["category"] == "impossible_number" and f["severity"] == "high" for f in findings)
    assert len(findings) == 2


# ── zero findings on a correct current-shape payload ────────────────────────


def _correct_day6_vitals():
    """The post-#1917 correct shape on Day 6: gated fields null, short honest
    windows, disclosure naming the true day. The exact state the LLM
    false-positived on six times."""
    return {
        "vitals": {
            "weight_delta_lbs": -4.1,
            "weight_delta_window_days": 5,
            "weight_delta_30d": None,
            "hrv_avg_ms": 55.2,
            "hrv_avg_window_days": 6,
            "hrv_30d_avg": None,
            "hrv_30d_n": None,
            "window_disclosure": "Today is Day 6 of the cycle that began 2026-07-27, so at most 6 day(s) of data can exist.",
            "workouts_30d": 3,
        }
    }


def test_zero_findings_on_correct_day6_payload():
    assert pp.check_payload("/api/vitals", _correct_day6_vitals(), day_n=6, strict=True) == []


def test_short_window_smaller_than_day_n_never_flags():
    # THE false-positive class being retired: 5 <= 6 is fine, every time.
    payload = {"weight_delta_window_days": 5}
    for _ in range(6):  # the model went 0-for-6 on this; the comparison goes 6-for-6
        assert pp.check_payload("/api/vitals", payload, day_n=6) == []


# ── registry contract: the SET is covered, not two remembered fields ────────

_GATED_INTENSIVE = sorted(k for k, (kind, gap) in REGISTRY.items() if kind == INTENSIVE and gap is None and (window_days(k) or 0) > 1)


@pytest.mark.parametrize("key", _GATED_INTENSIVE)
def test_every_gated_intensive_registry_field_is_covered(key):
    n = window_days(key)
    findings = pp.check_payload("/x", {key: 1.0}, day_n=n - 1)
    assert findings and findings[0]["category"] == "impossible_number", key
    assert pp.check_payload("/x", {key: 1.0}, day_n=n) == [], f"{key} must not flag once the window can be full"


def test_gap_declared_debt_is_exempt_and_stated():
    # #1919: group_90d_avgs is deliberately left ungated (the #1919 PR explains
    # why in window_registry.py — full-nulling would blank the /habits/ effort
    # map for up to 90 days post-reset) — the registry carries the debt as a
    # `gap` string, so the checker must not double-report it (the overlap is
    # stated, not duplicated). mean_7d/mean_30d used to be this file's example
    # of gap-declared debt; #1919 fully gated them (gap=None now), so they moved
    # into `_GATED_INTENSIVE` above instead of illustrating this case.
    assert pp.check_payload("/x", {"group_90d_avgs": 55}, day_n=3) == []


def test_gap_exempt_not_debt_is_also_not_flagged():
    # #1919: avg_30d_g / sleep_hours_30d_avg are INTENSIVE with a non-None gap
    # for a DIFFERENT reason than group_90d_avgs above — they are provably never
    # genesis-clamped (deliberately cross-phase reads, #2109), so a real,
    # correct, permanently-full value must not trip the day_n gate either.
    assert pp.check_payload("/x", {"avg_30d_g": 178.0}, day_n=3) == []
    assert pp.check_payload("/x", {"sleep_hours_30d_avg": 7.4}, day_n=3) == []


def test_extensive_counts_are_exempt_by_kind():
    assert pp.check_payload("/x", {"workouts_30d": 3}, day_n=6) == []


# ── span / day / prose rules ────────────────────────────────────────────────


def test_span_declaration_longer_than_elapsed_flags():
    findings = pp.check_payload("/api/vitals", {"weight_delta_window_days": 30}, day_n=6)
    assert len(findings) == 1 and findings[0]["severity"] == "high"
    findings = pp.check_payload("/api/vitals", {"hrv_window": {"actual_days": 7}}, day_n=6)
    assert len(findings) == 1 and "actual_days" in findings[0]["note"]


def test_requested_days_is_not_a_span_claim():
    # requested_days states intent (30 was asked for); actual_days states fact.
    assert pp.check_payload("/api/vitals", {"requested_days": 30, "actual_days": 6}, day_n=6) == []


def test_numeric_day_claim_beyond_today_flags():
    findings = pp.check_payload("/api/vitals", {"day_n": 9}, day_n=6)
    assert len(findings) == 1 and findings[0]["category"] == "temporal_contradiction"
    assert pp.check_payload("/api/vitals", {"day_n": 6}, day_n=6) == []


def test_day_prose_rule_is_strict_only():
    payload = {"window_disclosure": "Today is Day 7 of the cycle."}
    strict = pp.check_payload("/api/vitals", payload, day_n=6, strict=True)
    assert len(strict) == 1 and "frame/staleness" in strict[0]["note"]
    assert pp.check_payload("/api/coaches", payload, day_n=6, strict=False) == []


def test_prior_day_prose_never_flags():
    # "Day 3" on Day 6 is history, not a leak — only FUTURE days are impossible.
    assert pp.check_payload("/api/vitals", {"s": "since Day 3 we have kept pace"}, day_n=6, strict=True) == []


def test_pre_start_returns_no_findings():
    assert pp.check_payload("/api/vitals", {"weight_delta_30d": -4.0, "day_n": 4}, day_n=0) == []


# ── sweep_payloads: fail-soft but never silent ──────────────────────────────


def test_sweep_reports_unparseable_payload_as_warning():
    findings, warnings = pp.sweep_payloads(
        [
            {"path": "/api/broken", "body": "<html>not json</html>"},
            {"path": "/api/vitals", "body": '{"weight_delta_30d": -4.1}', "strict": True},
        ],
        today_iso=None,
    )
    assert any("/api/broken" in w for w in warnings), "an unreadable payload is a page NOT checked — it must be reported"
    # the parsable payload is still checked (day_n is live wall-clock here; the
    # gated field flags whenever the cycle is younger than 30 days, and the
    # sweep must not crash either way)
    assert isinstance(findings, list)


# ── qa_smoke wiring (#1922 acceptance: deterministic pass is never paused) ──

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import qa_smoke_lambda  # noqa: F401,E402  (imported for its module-level env/AWS setup)
from ai import budget_guard  # noqa: E402
from operational import qa_check_reader_truth  # noqa: E402  (#1665: check_reader_truth's real home)

_API_SURFACES = [
    {"name": "API · vitals", "path": "/api/vitals", "prose": '{"weight_delta_30d": -4.1}'},
]


def test_qa_smoke_deterministic_runs_even_when_budget_paused(monkeypatch):
    def must_not_call(body, model_name=None):
        raise AssertionError("Bedrock must not be called while budget-paused")

    from ai import bedrock_client

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(qa_check_reader_truth, "_fetch_reader_truth_surfaces", lambda: (_API_SURFACES, []))
    monkeypatch.setattr(bedrock_client, "invoke", must_not_call)
    checks = qa_check_reader_truth.check_reader_truth()
    names = [c.name for c in checks]
    assert "reader_truth:plausibility" in names, "the deterministic pass must run under a budget pause (#1922)"
    assert any(c.paused for c in checks), "the LLM half still pauses explicitly"


def test_qa_smoke_deterministic_finding_fails_reader_truth(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    monkeypatch.setattr(budget_guard, "allow", lambda feature: False)
    monkeypatch.setattr(qa_check_reader_truth, "_fetch_reader_truth_surfaces", lambda: (_API_SURFACES, []))
    import re

    from operational import reader_truth_qa

    day_n = reader_truth_qa.phase_context()["day_n"]
    checks = qa_check_reader_truth.check_reader_truth()
    det = [c for c in checks if c.name == "reader_truth:plausibility"]
    assert det, "deterministic check missing"
    if 1 <= day_n < 30:
        assert det[0].passed is False and re.search(r"impossible_number", det[0].message)


def test_llm_rubric_no_longer_claims_impossible_number():
    from operational import reader_truth_qa as rtq

    assert "impossible_number" not in rtq.CATEGORIES
    prompt = rtq.build_prompt(
        [{"name": "x", "path": "/x", "prose": "hello"}],
        rtq.phase_context("2026-07-28"),
    )
    assert '"impossible_number"' not in prompt, "the LLM must not be asked for the category code now owns"
    assert "deterministically" in prompt, "the prompt must state the overlap, not leave the category to be inferred"
