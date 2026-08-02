"""tests/test_qa_smoke_coach_labs_truth_1993.py — #1993 qa-smoke coach-labs-truth guard.

The labs coach's served card narrated "zero results … a total sync failure" while
/api/labs simultaneously served 8 draws — and the daily regeneration re-fabricated
the claim fresh each night. check_coach_labs_truth() is the tripwire for the CLASS:
any served coach text claiming zero results/draws while /api/labs serves
total_draws > 0 is an ALARMED content-truth FAIL (novel defect, never chronic —
the #2025 taxonomy). Fetch blips fail soft (warn); an empty store makes a
zero-narration uncontradicted (the extraction-side honesty lives in labs_facts).
"""

import os
import sys
import urllib.error

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402
from operational import qa_check_coach_labs  # noqa: E402 — the SOURCE module (a re-export is not a patch point)

OKAFOR_FABRICATION = (
    "I asked for the latest panel and the system returned zero results for that date. "
    "No flagged markers, no values, no panel — a total sync failure."
)


# ── the pure assessor ────────────────────────────────────────────────────────


def test_zero_results_claim_against_real_draws_fails():
    # The exact live defect: Okafor's card vs total_draws=8.
    coaches = [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]
    ok, msg = qa.assess_coach_labs_truth({"total_draws": 8}, coaches)
    assert ok is False
    assert "labs" in msg and "total_draws=8" in msg and "#1993" in msg


def test_zero_draws_wording_also_trips():
    coaches = [{"coach_id": "labs", "position_summary": "There have been zero draws this quarter."}]
    ok, _ = qa.assess_coach_labs_truth({"total_draws": 8}, coaches)
    assert ok is False


def test_weekly_priority_text_is_scanned_too():
    ok, msg = qa.assess_coach_labs_truth({"total_draws": 3}, [], weekly_priority_text="labs came back with zero results")
    assert ok is False
    assert "weekly_priority" in msg


def test_clean_coach_texts_pass():
    coaches = [
        {"coach_id": "labs", "position_summary": "ApoB remains high at 112; vitamin D low — 2 of 3 markers flagged."},
        {"coach_id": "sleep", "position_summary": "Sleep debt is trending down."},
    ]
    ok, msg = qa.assess_coach_labs_truth({"total_draws": 8}, coaches)
    assert ok is True
    assert "total_draws=8" in msg


def test_empty_store_makes_zero_narration_uncontradicted():
    # /api/labs 404s (labs={}) — a zero-results narration has nothing to contradict.
    coaches = [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]
    ok, _ = qa.assess_coach_labs_truth({}, coaches)
    assert ok is True


def test_junk_total_draws_is_treated_as_absent():
    coaches = [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]
    ok, _ = qa.assess_coach_labs_truth({"total_draws": "n/a"}, coaches)
    assert ok is True


def test_decimal_style_total_draws_counts():
    coaches = [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]
    ok, _ = qa.assess_coach_labs_truth({"total_draws": 8.0}, coaches)
    assert ok is False


# ── the check wrapper (fetch wiring) ─────────────────────────────────────────


def _run_check(monkeypatch, responses):
    """responses: path → dict payload | Exception to raise."""

    def fake_fetch(path, timeout=15):
        r = responses[path]
        if isinstance(r, Exception):
            raise r
        return r

    # Patch the SOURCE module — qa_smoke_lambda's name is a re-export, and the
    # internal call resolves against qa_check_coach_labs, not the re-export.
    monkeypatch.setattr(qa_check_coach_labs, "_fetch_site_json", fake_fetch)
    checks = qa.check_coach_labs_truth()
    assert len(checks) == 1
    return checks[0]


def test_check_fails_on_live_contradiction(monkeypatch):
    c = _run_check(
        monkeypatch,
        {
            "/api/labs": {"labs": {"total_draws": 8, "latest_draw_date": "2026-04-03"}},
            "/api/coaching-dashboard": {"coaches": [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]},
        },
    )
    assert c.passed is False
    assert c.chronic is not True  # novel content-truth defect — must hold the alarm


def test_check_labs_404_is_shaped_empty_not_a_fault(monkeypatch):
    c = _run_check(
        monkeypatch,
        {
            "/api/labs": urllib.error.HTTPError("u", 404, "nf", {}, None),
            "/api/coaching-dashboard": {"coaches": [{"coach_id": "labs", "position_summary": OKAFOR_FABRICATION}]},
        },
    )
    assert c.passed is True


def test_check_fetch_blip_warns_fail_soft(monkeypatch):
    c = _run_check(
        monkeypatch,
        {
            "/api/labs": {"labs": {"total_draws": 8}},
            "/api/coaching-dashboard": TimeoutError("timed out"),
        },
    )
    assert c.passed is None  # warn — a fetch blip must never red the nightly
