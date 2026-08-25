"""tests/test_stale_asof_recurrence_3111.py — R8, the CGM as_of-lag recurrence check (#3111).

reader_truth's LLM pass caught /api/glucose's `as_of_date` sitting 2 days behind
today on 2026-08-24 (finding `e5eafd`): a genuine CGM/HAE-webhook catch-up gap that
had already healed by the time it was investigated (both 2026-08-23 and 2026-08-24
landed later that same day — confirmed live against DynamoDB while filing #3111).
A live query of the apple_health partition across 2026-08-18 through 2026-08-24
turned up no second instance, so this reads as an isolated delivery gap, not a
systemic lag — but #3111 asks for a HOME for a recurrence, not a data backfill,
because today this class is visible only when the nightly LLM sample happens to
land on the lagging day (the #1920/#1927 "dark window" shape).

phase_plausibility.py R8 is that home: the exact "no more than 1 day behind" bar
the LLM already used against this payload, computed identically every qa_smoke run,
zero tokens, never budget-paused (ADR-105/#1922 precedent). These tests:

  - REPLAY the 08-24 shape (as_of_date 2 days behind today) and assert R8 fires,
    with the correct category/severity/day-count so a genuine recurrence is
    unmistakable in the log line;
  - confirm the healthy shapes (same-day, and the 1-day allowance the LLM's own
    quoted rule already grants) stay quiet — R8 must not tighten the bar past
    what reader_truth itself judged correct;
  - confirm R8 is scoped to registered near-real-time surfaces only (a source with
    a legitimately longer lag, e.g. labs, must never be swept by this rule);
  - confirm R8 runs pre-start and independent of `strict` (a date-lag question,
    not a day-count or narration question — same posture as R6/R7, #2613);
  - pin the qa_smoke wiring: sweep_payloads threads `today` through so the rule
    is live end-to-end, not just reachable via a direct check_payload call.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_LAMBDAS = os.path.join(_REPO, "lambdas")
for p in (_LAMBDAS, os.path.join(_LAMBDAS, "operational")):
    if p not in sys.path:
        sys.path.insert(0, p)

from operational import phase_plausibility as pp  # noqa: E402

# ── the replay acceptance: the live 08-24 shape, no LLM ──────────────────────


def _glucose_payload(as_of_date):
    """The reader_truth canonical shape site_api_biomarkers.glucose() actually
    publishes — as_of_date nested under the "glucose" object, per #3111's finding."""
    return {"glucose": {"avg_mg_dl": 104.3, "as_of_date": as_of_date}, "glucose_trend": []}


def test_replays_the_08_24_two_day_lag():
    findings = pp.check_payload("/api/glucose", _glucose_payload("2026-08-22"), day_n=8, today="2026-08-24")
    assert len(findings) == 1
    f = findings[0]
    assert f["page"] == "/api/glucose"
    assert f["category"] == "temporal_contradiction"
    assert f["severity"] == "high"
    assert "2 day(s) behind today 2026-08-24" in f["note"]
    assert "#3111" in f["note"]


def test_a_worse_lag_still_flags_once():
    # Deeper gaps are the same defect class, not a new one — one finding either way.
    findings = pp.check_payload("/api/glucose", _glucose_payload("2026-08-15"), day_n=8, today="2026-08-24")
    assert len(findings) == 1
    assert "9 day(s) behind" in findings[0]["note"]


# ── the healthy shapes stay quiet — R8 must not tighten past the LLM's own bar ──


def test_same_day_as_of_is_quiet():
    assert pp.check_payload("/api/glucose", _glucose_payload("2026-08-24"), day_n=8, today="2026-08-24") == []


def test_one_day_behind_is_the_allowed_margin_and_stays_quiet():
    # The quoted live WARN text: "should be no more than 1 day behind today" — 1
    # day IS within bounds, not the violation.
    assert pp.check_payload("/api/glucose", _glucose_payload("2026-08-23"), day_n=8, today="2026-08-24") == []


def test_no_as_of_date_field_is_quiet_not_a_crash():
    # cgm_days empty => site_api_biomarkers returns {"glucose": None, ...} — no
    # field to compare, so R8 has nothing to say (fail-soft, not a false claim).
    assert pp.check_payload("/api/glucose", {"glucose": None, "glucose_trend": []}, day_n=8, today="2026-08-24") == []


def test_duplicate_as_of_date_in_payload_is_reported_once():
    payload = {"glucose": {"as_of_date": "2026-08-22"}, "summary": {"as_of_date": "2026-08-22"}}
    findings = pp.check_payload("/api/glucose", payload, day_n=8, today="2026-08-24")
    assert len(findings) == 1


# ── scope: registered near-real-time surfaces only ───────────────────────────


def test_unregistered_surface_never_flags():
    # A stale as_of_date on a page NOT in NEAR_REAL_TIME_ASOF_MAX_LAG_DAYS (e.g.
    # labs, which legitimately lags weeks) must never be swept by this rule.
    assert "/api/labs" not in pp.NEAR_REAL_TIME_ASOF_MAX_LAG_DAYS
    findings = pp.check_payload("/api/labs", _glucose_payload("2026-07-01"), day_n=8, today="2026-08-24")
    assert findings == []


def test_glucose_is_registered_at_a_one_day_bar():
    assert pp.NEAR_REAL_TIME_ASOF_MAX_LAG_DAYS["/api/glucose"] == 1


# ── phase-independence: runs pre-start and regardless of `strict` ───────────


def test_r8_runs_pre_start():
    # R1-R4 need a real day_n to compare against; R8 is a pure date comparison
    # (like R6/R7, #2613) so it must fire even at day_n=0 (pre-genesis countdown).
    findings = pp.check_payload("/api/glucose", _glucose_payload("2026-08-15"), day_n=0, today="2026-08-24")
    assert len(findings) == 1 and findings[0]["category"] == "temporal_contradiction"


def test_r8_does_not_require_strict():
    findings = pp.check_payload("/api/glucose", _glucose_payload("2026-08-22"), day_n=8, today="2026-08-24", strict=False)
    assert len(findings) == 1


def test_r8_is_skipped_when_today_is_omitted():
    # Same fail-soft posture as R6/R7 with no start_date: a rule with nothing to
    # compare against must not guess "today".
    assert pp.check_payload("/api/glucose", _glucose_payload("2026-08-15"), day_n=8) == []


# ── qa_smoke wiring: sweep_payloads threads `today` through end-to-end ──────


def test_sweep_payloads_replays_the_finding_via_today_iso():
    payloads = [{"path": "/api/glucose", "body": '{"glucose": {"as_of_date": "2026-08-22"}}', "strict": True}]
    findings, warnings = pp.sweep_payloads(payloads, today_iso="2026-08-24")
    assert warnings == []
    matches = [f for f in findings if f["page"] == "/api/glucose" and "#3111" in f["note"]]
    assert len(matches) == 1, "sweep_payloads must thread `today` into check_payload so R8 is live, not just reachable directly"


def test_sweep_payloads_healthy_glucose_is_quiet():
    payloads = [{"path": "/api/glucose", "body": '{"glucose": {"as_of_date": "2026-08-24"}}', "strict": True}]
    findings, warnings = pp.sweep_payloads(payloads, today_iso="2026-08-24")
    assert warnings == []
    assert not any(f["page"] == "/api/glucose" for f in findings)
