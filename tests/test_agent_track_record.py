"""
tests/test_agent_track_record.py — the #1399 track-record computation gates.

Three load-bearing things are proven here, all against fixture audit-log records
(never live S3):

  1. COMPUTED COUNTS (AC1) — triages / PRs / merges / holds are derived from the
     records, never hand-maintained.
  2. FIX-SURVIVAL-14d GRADING (AC2, ADR-104) — held / regressed / not-yet-
     gradeable, with a not-yet fix NEVER counted as a success and the held-rate
     taken over the gradeable n only.
  3. THE R22 PRIVACY CONTROL (AC3) — a security-shaped alarm class fed through
     every ingress (a merged fix, an auto_fixed item, an alarm-fire event) can
     NEVER appear in a published case file; the alarm-type allowlist is
     default-deny, so an unclassified alarm is withheld too.
"""

import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))

import track_record as tr  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────────
def _agent_run(d, alarms=None, ci=0, prs=None, auto_fixed=None, needs_human=None, mode="shadow"):
    return {
        "_date": d,
        "_key": f"remediation-log/{d.replace('-', '/')}/000000.json",
        "mode": mode,
        "signals": {
            "alarms": [{"name": a, "reason": "Threshold Crossed"} if isinstance(a, str) else a for a in (alarms or [])],
            "ci_failures": [{"id": i} for i in range(ci)],
            "dlq": {"depth": 0},
        },
        "report": {
            "auto_fixed": auto_fixed or [],
            "prs": prs or [],
            "needs_human": needs_human or [],
            "stale": [],
        },
    }


def _gate(pr, action, title, reason="", d="2026-06-01", infra=False):
    return {
        "_date": d,
        "_key": f"remediation-log/automerge/{d.replace('-', '/')}/pr{pr}-000000.{action}.json",
        "pr": pr,
        "url": f"https://github.com/averagejoematt/life-platform/pull/{pr}",
        "title": title,
        "reason": reason,
        "action": action,
        "infra": infra,
    }


# ── 1. computed counts ────────────────────────────────────────────────────────
def test_computed_counts_from_fixture_audit_log():
    agent_records = [
        _agent_run("2026-06-01", alarms=["slo-source-freshness", "life-platform-dlq-depth-warning"], ci=1),
        _agent_run(
            "2026-06-02",
            alarms=["ingest-liveness-unhealthy"],
            prs=[{"summary": "fix(freshness): filter DDB to DATE# SKs", "pr": "branch: remediation/freshness-sk"}],
            needs_human=[{"issue": "measurements stale", "action": "log a check-in"}],
        ),
    ]
    automerge_records = [
        _gate(101, "merged", "fix(freshness): raise SOURCE_STALE_HOURS for withings"),
        _gate(102, "held", "fix(monitoring): recalibrate alarm-threshold", reason="diff too large"),
        _gate(103, "held", "chore: tests", reason="not on allowlist"),
    ]
    counts = tr.compute_counts(agent_records, automerge_records)
    assert counts["agent_runs"] == 2
    # 2 alarms + 1 CI on run 1, 1 alarm on run 2 = 4 triaged signals
    assert counts["signals_triaged"] == 4
    assert counts["prs_opened"] == 1  # one report.prs item, zero auto_fixed
    assert counts["gate_merges"] == 1
    assert counts["gate_holds"] == 2
    assert counts["needs_human"] == 1


# ── 2. fix-survival grading (ADR-104) ─────────────────────────────────────────
def test_survival_regressed_when_alarm_refires_in_window():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)  # well past the window
    # freshness fix landed 2026-06-01; same class fires again 2026-06-05 → regressed
    refires = [date(2026, 6, 5)]
    assert tr.grade_survival("2026-06-01", refires, now) == tr.GRADE_REGRESSED


def test_survival_held_when_window_elapsed_clean():
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert tr.grade_survival("2026-06-01", [], now) == tr.GRADE_HELD


def test_survival_not_yet_gradeable_when_window_open():
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)  # only 9 days after a 2026-06-01 fix
    assert tr.grade_survival("2026-06-01", [], now) == tr.GRADE_NOT_YET


def test_refire_outside_window_does_not_count_as_regression():
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # a re-fire 20 days out is past the 14d horizon → the fix HELD its window
    assert tr.grade_survival("2026-06-01", [date(2026, 6, 21)], now) == tr.GRADE_HELD


def test_refire_before_window_closes_regresses_even_if_young():
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)  # only 4 days old
    assert tr.grade_survival("2026-06-01", [date(2026, 6, 3)], now) == tr.GRADE_REGRESSED


def test_survival_summary_excludes_not_yet_from_denominator():
    # Three landed freshness fixes: one held, one regressed, one still not-yet.
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    agent_records = [
        # a re-fire on 2026-06-01 — inside the 2026-05-20 fix's window (closes 2026-06-03)
        _agent_run("2026-06-01", alarms=["slo-source-freshness"]),
    ]
    automerge = [
        _gate(1, "merged", "fix(freshness): held one", d="2026-05-20"),  # >14d, refire → regressed
        _gate(2, "merged", "fix(dlq): drained queue depth", d="2026-05-01"),  # >14d, no refire → held
        _gate(3, "merged", "fix(freshness): fresh one", d="2026-06-10"),  # 2d old → not-yet
    ]
    rec = tr.build_track_record(agent_records, automerge, now=now)
    surv = rec["survival"]
    assert surv["regressed"] == 1
    assert surv["held"] == 1
    assert surv["not_yet_gradeable"] == 1
    # honest n — not-yet is NOT in the denominator
    assert surv["n_gradeable"] == 2
    assert surv["held_rate"] == 0.5


# ── 3. the R22 privacy control ────────────────────────────────────────────────
_SECURITY_ALARMS = [
    "mcp-token-exposure-spike",
    "waf-sqli-block-surge",
    "auth-bypass-detected",
    "secret-access-denied-anomaly",
    "credential-leak-canary",
    "rate-limit-bypass-observed",
    "unauthorized-admin-access",
]


def test_security_alarm_never_classifies_public():
    for name in _SECURITY_ALARMS:
        assert tr.is_security_shaped(name), f"{name} must trip the security gate"
        assert tr.public_alarm_class(name) is None, f"{name} must never get a public class"


def test_security_alarm_never_reaches_a_published_case_file():
    """The load-bearing R22 assertion: feed a security-shaped alarm through EVERY
    ingress — a merged gate fix, an agent auto_fixed item, AND an alarm-fire event
    — and prove it appears in ZERO published cases while still being counted as
    withheld."""
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    agent_records = [
        _agent_run(
            "2026-06-02",
            alarms=["mcp-token-exposure-spike"],  # security alarm fire
            auto_fixed=[{"summary": "fix(auth): patch auth-bypass in /token handler", "pr": "PR #999"}],
        ),
        _agent_run("2026-06-03", alarms=["slo-source-freshness"]),  # one legit alarm too
    ]
    automerge = [
        _gate(900, "merged", "fix(security): waf-sqli-block rule", reason="exploit mitigation"),
        _gate(901, "merged", "fix(freshness): raise stale threshold"),  # legit, should appear
    ]
    rec = tr.build_track_record(agent_records, automerge, now=now)

    published_blob = repr(rec["cases"]).lower()
    for marker in ("token-exposure", "auth-bypass", "waf-sqli", "/token", "exploit"):
        assert marker not in published_blob, f"security detail {marker!r} leaked into a published case file"

    # the legit freshness fix DID make it through
    assert any(c["alarm_class"] == "source-freshness" for c in rec["cases"])
    # and the security case-ingress items (gate fix + auto_fixed item) were counted
    # as withheld, not silently dropped. (The security ALARM fire is not a case — it
    # is asserted out of the survival timeline below.)
    assert rec["excluded_case_count"] >= 2

    # the security alarm never entered the survival timeline either
    events = tr.alarm_fire_events(agent_records)
    assert all("token" not in name.lower() and "sqli" not in name.lower() for _d, _c, name in events)


def test_unknown_alarm_class_is_default_denied():
    # a novel, non-security alarm we've simply never classified is still withheld
    assert tr.classify_alarm_type("brand-new-widget-metric-alarm") is None
    assert tr.public_alarm_class("brand-new-widget-metric-alarm") is None


def test_oauth_token_health_alarm_stays_public():
    """Guard against an over-broad security match: OAuth token-HEALTH alarms are
    operational (they already render on /story/agents/) and must stay public."""
    for name in ("ingest-auth-unhealthy-24h", "garmin-auth-unhealthy-24h"):
        assert not tr.is_security_shaped(name)
        assert tr.public_alarm_class(name) == "oauth-health"


def test_real_alarm_names_classify_to_public_classes():
    # the alarm names actually observed on the live log all resolve to a class
    real = [
        "slo-source-freshness",
        "life-platform-dlq-depth-warning",
        "ingest-liveness-unhealthy",
        "ingestion-error-ai-expert-analyzer",
        "ai-canary-overall",
        "coherence-overall",
        "grading-stalled",
        "panelcast-no-episode-7d",
        "qa-paused-by-budget",
        "qa-smoke-warnings",
        "ai-tokens-platform-daily-total",
        "ingest-reconciliation-strava",
    ]
    for name in real:
        assert tr.public_alarm_class(name) is not None, f"{name} should classify public"
