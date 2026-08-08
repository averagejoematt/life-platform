"""tests/test_content_cadence_1972.py — #1972 (epic #1890): no surface said WHEN
the next chronicle/podcast installment lands, even though the cadence is
entirely cron-derivable.

Covers all three acceptance criteria:
  AC1  common.content_cadence.build_payload — the deterministic cadence line
       (drafted-date positive case; honest-pending when paused), plus the
       anti-growth-1 guard: a paused payload NEVER also carries a positive
       date claim.
  AC2  the qa_smoke regression guard (operational.qa_check_content_cadence) —
       proves it actually FAILS on a malformed payload, not just passes on a
       good one.
  AC3  (verified live, not here — see the PR body) the driver verifies the
       served page post-merge; this suite is the fixture-side guarantee that
       makes that verification meaningful.

Also pins the cron literal itself: the module's weekday/hour constants must
match the literal EventBridge schedule in cdk/stacks/email_stack.py (derive
from source, prove it fires — never let the two silently drift apart).
"""

import os
import re
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import content_cadence  # noqa: E402
from operational import qa_check_content_cadence as qcc  # noqa: E402 — the SOURCE module (a re-export is not a patch point)

# ── AC1: the pure cadence math ────────────────────────────────────────────────


def test_same_wednesday_before_cron_hour_counts_today():
    # 2026-08-05 is a Wednesday. 10:00 UTC is before the 15:00 UTC cron.
    now = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
    assert content_cadence.next_chronicle_draft_date(now).isoformat() == "2026-08-05"


def test_same_wednesday_at_cron_hour_rolls_to_next_week():
    # Exactly 15:00 UTC — the cron has already fired for today; roll forward 7 days.
    now = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
    assert content_cadence.next_chronicle_draft_date(now).isoformat() == "2026-08-12"


def test_same_wednesday_after_cron_hour_rolls_to_next_week():
    now = datetime(2026, 8, 5, 23, 59, tzinfo=timezone.utc)
    assert content_cadence.next_chronicle_draft_date(now).isoformat() == "2026-08-12"


def test_non_wednesday_rolls_forward_to_the_right_wednesday():
    # 2026-08-02 is a Sunday -> next Wednesday is 2026-08-05.
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    assert content_cadence.next_chronicle_draft_date(now).isoformat() == "2026-08-05"


def test_monday_rolls_forward_two_days():
    # 2026-08-03 is a Monday -> next Wednesday is 2026-08-05.
    now = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)
    assert content_cadence.next_chronicle_draft_date(now).isoformat() == "2026-08-05"


def test_naive_datetime_rejected():
    with __import__("pytest").raises(ValueError):
        content_cadence.next_chronicle_draft_date(datetime(2026, 8, 5, 10, 0))


# ── AC1: build_payload — positive + honest-pending shapes ─────────────────────


def test_positive_payload_carries_next_date_for_both_surfaces():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    payload = content_cadence.build_payload(now, allowed=True)
    for key in ("chronicle", "podcast"):
        assert payload[key]["paused"] is False
        assert payload[key]["next_date"] == "2026-08-05"
        assert payload[key]["display"]  # non-empty


def test_paused_payload_never_also_carries_a_positive_date_claim():
    """The anti-growth-1 guard (#1972's core lesson): a payload cannot say
    both "paused" and "next Wednesday" — that IS the dishonest-promise class
    /subscribe/ shipped (a weekly email promise that was actually
    kill-switched for months, docs/reviews/FULLREVIEW_2026-08-02_DELTA.md)."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    payload = content_cadence.build_payload(now, allowed=False)
    for key in ("chronicle", "podcast"):
        assert payload[key]["paused"] is True
        assert payload[key]["next_date"] is None
        assert payload[key]["display"]  # non-empty — never a silent pause


def test_podcast_display_never_claims_an_independent_schedule():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    payload = content_cadence.build_payload(now, allowed=True)
    # The podcast lost its standing cron (#734) — its line must read as
    # conditional on the chronicle, never as its own promise.
    assert "chronicle" in payload["podcast"]["display"].lower()


# ── the cron literal itself: derive from source, prove it fires ───────────────


def test_module_constants_match_the_live_cdk_cron_literal():
    email_stack = os.path.join(_REPO, "cdk", "stacks", "email_stack.py")
    src = open(email_stack, encoding="utf-8").read()
    assert content_cadence.CHRONICLE_CRON_LITERAL in src, (
        "common/content_cadence.py's CHRONICLE_CRON_LITERAL no longer matches any literal "
        "in cdk/stacks/email_stack.py — the WednesdayChronicle schedule moved; update both."
    )
    # Sanity-decode the literal itself so the constants can never silently drift
    # from the string they claim to mirror.
    m = re.match(r"cron\((\d+) (\d+) \? \* (\w+) \*\)", content_cadence.CHRONICLE_CRON_LITERAL)
    assert m, "CHRONICLE_CRON_LITERAL isn't a recognizable AWS cron expression"
    minute, hour, weekday_name = m.group(1), m.group(2), m.group(3)
    assert minute == "0"
    assert int(hour) == content_cadence.CHRONICLE_CRON_HOUR_UTC
    assert weekday_name == "WED"
    assert content_cadence.CHRONICLE_CRON_WEEKDAY == 2  # Monday=0 .. Wednesday=2


# ── AC2: the qa_smoke regression guard — pure assessor ─────────────────────────


def _good_positive():
    return {
        "chronicle": {
            "paused": False,
            "next_date": "2026-08-05",
            "display": "Next Chronicle installment drafted Wednesday, August 5.",
        },
        "podcast": {
            "paused": False,
            "next_date": "2026-08-05",
            "display": "The Panel podcast ships the same week as the next Chronicle installment.",
        },
    }


def _good_paused():
    return {
        "chronicle": {"paused": True, "next_date": None, "display": "The next Chronicle installment is paused."},
        "podcast": {"paused": True, "next_date": None, "display": "The next Panel podcast episode is paused."},
    }


def test_assessor_passes_the_positive_shape():
    ok, msg = qcc.assess_content_cadence(_good_positive())
    assert ok is True
    assert "chronicle" in msg or "both" in msg


def test_assessor_passes_the_paused_shape():
    ok, _ = qcc.assess_content_cadence(_good_paused())
    assert ok is True


def test_assessor_fails_when_neither_next_date_nor_paused_present():
    """The actual regression this guard exists to catch: a payload with a
    display string but no honest signal of what's next."""
    bad = _good_positive()
    bad["podcast"] = {"paused": False, "next_date": None, "display": "Coming eventually."}
    ok, msg = qcc.assess_content_cadence(bad)
    assert ok is False
    assert "podcast" in msg


def test_assessor_fails_on_missing_display():
    bad = _good_positive()
    bad["chronicle"] = {"paused": False, "next_date": "2026-08-05", "display": ""}
    ok, msg = qcc.assess_content_cadence(bad)
    assert ok is False
    assert "chronicle" in msg


def test_assessor_fails_when_both_paused_and_next_date_present():
    """The anti-growth-1 shape: paused=true alongside a positive date claim."""
    bad = _good_positive()
    bad["chronicle"]["paused"] = True
    ok, msg = qcc.assess_content_cadence(bad)
    assert ok is False
    assert "anti-growth-1" in msg


def test_assessor_fails_on_missing_podcast_key():
    bad = {"chronicle": _good_positive()["chronicle"]}
    ok, msg = qcc.assess_content_cadence(bad)
    assert ok is False
    assert "podcast" in msg


def test_assessor_fails_on_non_dict_response():
    ok, msg = qcc.assess_content_cadence(None)
    assert ok is False
    assert msg


# ── AC2: the check wrapper — fetch wiring + fail-soft ──────────────────────────


def _run_check(monkeypatch, response):
    def fake_fetch(path, timeout=15):
        if isinstance(response, Exception):
            raise response
        return response

    # Patch the SOURCE module (operational.qa_check_content_cadence), never a
    # re-export — a re-export is not a patch point.
    monkeypatch.setattr(qcc, "_fetch_site_json", fake_fetch)
    checks = qcc.check_content_cadence()
    assert len(checks) == 1
    return checks[0]


def test_check_passes_on_a_healthy_live_payload(monkeypatch):
    c = _run_check(monkeypatch, _good_positive())
    assert c.passed is True


def test_check_fails_on_the_actual_regression(monkeypatch):
    """Proves the check REPORTS a failure, not just that the assessor does —
    a bad payload with both keys present but neither carrying next_date nor
    paused:true."""
    bad = {
        "chronicle": {"paused": False, "next_date": None, "display": "Something's coming."},
        "podcast": {"paused": False, "next_date": None, "display": "Something's coming."},
    }
    c = _run_check(monkeypatch, bad)
    assert c.passed is False
    assert c.chronic is not True  # novel content-truth defect — must hold the alarm


def test_check_warns_fail_soft_on_fetch_error(monkeypatch):
    c = _run_check(monkeypatch, TimeoutError("timed out"))
    assert c.passed is None  # warn — a fetch blip must never red the nightly


def test_check_wired_into_qa_smoke_lambda():
    """qa_smoke_lambda re-exports check_content_cadence and calls it in
    check_steps() — the same contract check_coach_labs_truth's wiring test
    pins (#1993)."""
    qa_smoke_path = os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")
    src = open(qa_smoke_path, encoding="utf-8").read()
    assert "from operational.qa_check_content_cadence import" in src
    assert "check_content_cadence" in src
    # #2307: the nightly run list moved out of lambda_handler into check_steps(),
    # the ONE place a check is wired in — and each step now runs fault-isolated.
    assert '("content_cadence", check_content_cadence)' in src, "check_content_cadence is not in the check_steps() run list"
