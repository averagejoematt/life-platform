#!/usr/bin/env python3
"""
deploy/sentinel_cadence.py — the dead-man for the weekly drift sentinel's OWN cadence
(#3130). Own module (same split shape as `sentinel_github.py` / `sentinel_quota.py` /
`sentinel_replication.py` — module-size ceiling #1665, `tests/test_module_size_guard.py`),
imported into `deploy/drift_sentinel.py` with a one-line registration.

WHY THIS CHECK, AND WHY ABSENCE IS THE FAILURE MODE (#3130)
─────────────────────────────────────────────────────────────
Every other check in this module asserts something about LIVE infrastructure. This one
asserts something about the sentinel itself: did it actually run? The #3112 autopsy
found the 2026-08-17 Monday remediation run (id 32041058520) failed outright — the
workflow crashed before `drift_sentinel.persist()` ever executed — so NO
`drift-log/{date}.json` record was written for that week. The S3 record set silently
jumped 08-10 → 08-24. A CI-failure email fired and nobody actioned it; nothing else
noticed the gap. This is the #2799 "absent check" class in its purest form: the
detector itself went dark, and the only trace was an unread email.

MECHANISM: SELF-REPORT, NOT A NEW ALARM (option b over option a)
──────────────────────────────────────────────────────────────────
Two shapes were on the table: (a) a CloudWatch metric + missing-data alarm, which needs
a Monitoring-stack CDK deploy and new infrastructure to operate; or (b) a self-report at
the START of each sentinel run that asserts the previous expected run(s) left a record.
This module implements (b): it is the cheapest honest mechanism — $0, no deploy, and it
reuses the EXACT reporting surface (`checks` dict → `drift_report.as_signal` →
needs-human triage email) every other check in this module already uses. `main()` calls
`run_sweep()` BEFORE `persist()`, so at the moment this check runs, `drift-log/latest.json`
still holds the PREVIOUS run's record — the self-report has natural access to the
predecessor without snapshotting anything ahead of time. If a run crashes before
`persist()`, the gap is invisible to that run by construction (it never gets that far) —
but the NEXT successful run's cadence check will observe the missing date and report it,
because it lists the actual `drift-log/{date}.json` keys present in S3 rather than
trusting any single record's self-history.

THE #2578 / #3112 FAIL-CLOSED LESSON, APPLIED HERE
──────────────────────────────────────────────────
`check_codeql_alerts` (#1902) shipped with an unreadable-list case that returned a soft
`status: "error"` — and `error` never reaches `remediation/drift_report.as_signal`
(which only escalates on `status == "drift"`), so an unreadable check was invisible for
weeks while real findings sat untriaged (the #2578 fix, #3112 autopsy). The identical
trap applies here: if `list_objects_v2` on `drift-log/` raises, or returns something
this check cannot parse, that is NOT "no gap found" and NOT a soft `error` — it is
`status: "drift"` with a `detail` that says plainly the log is unreadable, so a human
isn't sent chasing a fabricated missing-date list when the real problem is access/
permissions. "Couldn't verify" and "verified nothing wrong" must never look the same.

CADENCE SOURCE OF TRUTH
────────────────────────
Mon/Wed/Fri, mirroring `.github/workflows/remediation-agent.yml`'s
`cron: "45 14 * * 1,3,5"` (cron weekday 1,3,5 = Mon/Wed/Fri; Python's
`datetime.weekday()` 0=Mon..6=Sun, so the equivalent set is {0, 2, 4}). This module does
not parse the workflow YAML — the two encodings are different weekday numbering systems
maintained by hand in two places, same as `PUSH_TRIGGER_GLOBS` in `sentinel_github.py`
mirrors its own workflow trigger list without parsing it. A change to the cron needs a
matching change here; `tests/test_drift_sentinel.py` pins the {0, 2, 4} set so a drift
in one without the other fails a test, not just a code review.

Cost: a handful of LIST calls per week (`drift-log/` has one object per run day plus
`latest.json` — never more than a few hundred keys even at years of history). No new
infrastructure.
"""

import os
from datetime import datetime, timedelta, timezone

# Mirrors .github/workflows/remediation-agent.yml's `cron: "45 14 * * 1,3,5"`.
# Cron weekday 1,3,5 (Mon,Wed,Fri) == Python datetime.weekday() {0, 2, 4}.
EXPECTED_WEEKDAYS = frozenset({0, 2, 4})  # Mon, Wed, Fri

# The acceptance criteria's explicit staleness threshold (#3130): latest.json older
# than this many days is drift, independent of whether every individual expected date
# was reported missing (a run that only ever half-writes would show no "missing" dates
# yet also never advance latest.json — staleness catches that shape too).
STALE_AFTER_DAYS = 4

# How far back to look for expected-but-missing run dates. Two weeks covers a single
# missed run with room to spare without turning this into a full-history audit; the
# freshness check (STALE_AFTER_DAYS) is what actually gates on the mostly-recent case.
LOOKBACK_DAYS = 14

DRIFT_LOG_PREFIX = "drift-log/"


def _expected_dates(now):
    """Mon/Wed/Fri dates in the lookback window, ending YESTERDAY.

    Ends at yesterday (not today) deliberately: today's own record does not exist yet
    during this very run (persist() happens after run_sweep()), so including today
    would make every single run report itself as a false gap."""
    out = []
    for i in range(1, LOOKBACK_DAYS + 1):
        d = (now - timedelta(days=i)).date()
        if d.weekday() in EXPECTED_WEEKDAYS:
            out.append(d)
    return sorted(out)


def _list_dated_keys(s3, bucket):
    """The set of `{date}.json` dates actually present under drift-log/, excluding
    `latest.json`. Paginated — list_objects_v2 caps at 1000 keys per page."""
    dates = set()
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": DRIFT_LOG_PREFIX}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        for obj in page.get("Contents") or []:
            key = obj.get("Key", "")
            name = key[len(DRIFT_LOG_PREFIX) :]
            if name.endswith(".json") and name != "latest.json":
                dates.add(name[: -len(".json")])
        if page.get("IsTruncated"):
            token = page.get("NextContinuationToken")
            if not token:
                break
        else:
            break
    return dates


def check_sentinel_cadence(client_factory=None, now=None):
    """Assert the sentinel's OWN weekly cadence has no gap and is fresh.

    `client_factory(service, region)` is injected so offline tests drive this against
    fakes on the real call shape (fixture-must-be-the-wire) — same contract as
    `check_raw_replication` in `sentinel_replication.py`.
    """
    if client_factory is None:  # pragma: no cover — exercised live, faked in tests
        from drift_sentinel import _client as client_factory  # noqa: PLC0415

    bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
    region = os.environ.get("AWS_REGION", "us-west-2")
    now = now or datetime.now(timezone.utc)

    try:
        s3 = client_factory("s3", region)
        present_dates = _list_dated_keys(s3, bucket)
    except Exception as e:  # noqa: BLE001
        # FAIL CLOSED (#2578/#3112 lesson): a drift-log we cannot list is
        # indistinguishable from one with a real gap in it, and proving the cadence
        # held is the entire job of this check. "Couldn't read it" is therefore
        # drift, not a soft `error` that `drift_report.as_signal` would never see.
        return {
            "status": "drift",
            "reason": "unreadable",
            "missing_dates": [],
            "latest_date": None,
            "days_stale": None,
            "detail": (
                f"drift-log/ on {bucket} is UNREADABLE — cannot prove the weekly sentinel cadence held ({e}). "
                "Fix S3 read access before trusting any other check in this run."
            ),
        }

    # A prefix that has been queried successfully but truly holds zero dated keys is
    # its own finding: the sentinel has been running since #394, so an empty
    # drift-log/ in production is not "first ever run" — it means something upstream
    # (bucket recreation, an accidental prefix wipe) is badly wrong, not benign.
    if not present_dates:
        return {
            "status": "drift",
            "reason": "empty",
            "missing_dates": [d.isoformat() for d in _expected_dates(now)],
            "latest_date": None,
            "days_stale": None,
            "detail": f"drift-log/ on {bucket} has ZERO dated records — the sentinel has run since #394; an empty prefix is not a fresh start",
        }

    expected = _expected_dates(now)
    missing = [d for d in expected if d.isoformat() not in present_dates]

    latest_date_str = max(present_dates)
    latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days_stale = (now - latest_date).days

    if not missing and days_stale <= STALE_AFTER_DAYS:
        return {
            "status": "clean",
            "missing_dates": [],
            "latest_date": latest_date_str,
            "days_stale": days_stale,
        }

    reasons = []
    if missing:
        reasons.append(f"missing expected run date(s): {', '.join(d.isoformat() for d in missing)}")
    if days_stale > STALE_AFTER_DAYS:
        reasons.append(f"latest record ({latest_date_str}) is {days_stale}d stale (cadence allows {STALE_AFTER_DAYS}d)")

    return {
        "status": "drift",
        "reason": "gap",
        "missing_dates": [d.isoformat() for d in missing],
        "latest_date": latest_date_str,
        "days_stale": days_stale,
        "detail": "sentinel cadence gap — " + "; ".join(reasons),
    }
