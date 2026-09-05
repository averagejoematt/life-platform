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

CADENCE SOURCE OF TRUTH — ONE FACT, TWO READERS (#3508)
───────────────────────────────────────────────────────
This used to be a hand-maintained mirror: `EXPECTED_WEEKDAYS = {0, 2, 4}` with a docstring
saying "this module does not parse the workflow YAML". Meanwhile the workflow ran the
sentinel behind a THIRD encoding of the same fact —

    if [ "$(date -u +%u)" = "1" ] || [ workflow_dispatch ]; then python3 deploy/drift_sentinel.py

— "keep the sentinel weekly by running only on Mondays". So the declared cadence was
Mon/Wed/Fri and the real one was Mondays, and the disagreement was not a latent risk but
a live, permanent false finding: every Wed and Fri run reported "sentinel cadence gap" and
the needs-human line "Investigate 4 missed weekly sentinel runs (08-19, 21, 26, 28)",
identical in the 09-01, 09-02 and 09-04 reports. Worse than the noise: a REAL sentinel
death on a Monday was indistinguishable from the designed Wed/Fri silence, and the agent
handed off a 2-day-old drift record as current — the 09-04 17:49Z report cited six drifted
stacks that had all been redeployed at 16:32–16:36Z that morning.

The fix is the standing rule: derive, do not mirror. The schedule cron in
`.github/workflows/remediation-agent.yml` is now the ONE fact. This module PARSES it
(`workflow_cron_weekdays`) and the workflow's own guard asks this module whether today is
a run day (`python3 deploy/sentinel_cadence.py --should-run-today`), so the expectation and
the behaviour cannot disagree — there is only one literal left to change.

If the workflow file cannot be read or parsed, `EXPECTED_WEEKDAYS` falls back to
`FALLBACK_WEEKDAYS` and `CADENCE_SOURCE_ERROR` is set; the check then reports `drift` with
that reason rather than quietly grading itself against a guess ("couldn't verify" and
"verified nothing wrong" must never look the same — the same rule as the unreadable
drift-log branch below).

Cost: a handful of LIST calls per week (`drift-log/` has one object per run day plus
`latest.json` — never more than a few hundred keys even at years of history). No new
infrastructure.
"""

import os
import re
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(_ROOT, ".github", "workflows", "remediation-agent.yml")

# The workflow's `- cron: "m h dom mon dow"` schedule lines. A regex rather than a YAML
# parse so this module stays dependency-free in every runner it is imported from; the
# shape is one well-known line and `tests/test_drift_sentinel.py` asserts the parse
# against the real file, so a reformat that breaks it reds a test rather than going quiet.
_CRON_RE = re.compile(r"^\s*-\s*cron:\s*['\"]([^'\"]+)['\"]", re.M)

# Used ONLY when the workflow cannot be read/parsed — never as a silent default. See
# CADENCE_SOURCE_ERROR.
FALLBACK_WEEKDAYS = frozenset({0, 2, 4})  # Mon, Wed, Fri


def _cron_dow_to_python(field):
    """cron day-of-week (0 or 7 = Sunday, 1 = Monday) -> datetime.weekday() (0 = Monday).

    Supports the forms GitHub Actions actually accepts in this field: `*`, a comma list,
    a `a-b` range, and a bare number. Raises ValueError on anything else rather than
    guessing — a schedule this module cannot read must be loud, not approximated.
    """
    field = field.strip()
    if field == "*":
        return frozenset(range(7))
    out = set()
    for part in field.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            values = range(int(lo), int(hi) + 1)
        elif "/" in part:
            raise ValueError(f"step syntax {part!r} in the day-of-week field is not supported by this parser")
        else:
            values = [int(part)]
        for v in values:
            if not 0 <= v <= 7:
                raise ValueError(f"cron day-of-week {v} out of range")
            out.add((v % 7 - 1) % 7)  # cron 0/7=Sun -> py 6; cron 1=Mon -> py 0
    if not out:
        raise ValueError(f"empty day-of-week field {field!r}")
    return frozenset(out)


def workflow_cron_weekdays(path=WORKFLOW_PATH):
    """The union of `datetime.weekday()` values the workflow's schedule cron(s) fire on.

    This is THE cadence fact (#3508). Raises on an unreadable/unparseable workflow."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    crons = _CRON_RE.findall(text)
    if not crons:
        raise ValueError(f"no `- cron:` schedule found in {path}")
    days = set()
    for expr in crons:
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(f"cron {expr!r} does not have 5 fields")
        days |= _cron_dow_to_python(fields[4])
    return frozenset(days)


CADENCE_SOURCE_ERROR = None
try:
    EXPECTED_WEEKDAYS = workflow_cron_weekdays()
except Exception as _e:  # noqa: BLE001 — a broken read must degrade LOUDLY, not crash the sweep
    EXPECTED_WEEKDAYS = FALLBACK_WEEKDAYS
    CADENCE_SOURCE_ERROR = f"{type(_e).__name__}: {_e}"


def should_run_today(now=None):
    """Is today a scheduled sentinel day? The workflow's run guard asks THIS, so the
    expectation and the behaviour read the same literal (#3508)."""
    now = now or datetime.now(timezone.utc)
    return now.weekday() in EXPECTED_WEEKDAYS


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

    if CADENCE_SOURCE_ERROR:
        # #3508: the cadence fact is the workflow's own cron. If it could not be read,
        # every "missing date" below would be graded against a GUESS. Say so instead —
        # the same fail-closed rule as the unreadable drift-log branch.
        return {
            "status": "drift",
            "reason": "unknown_cadence",
            "missing_dates": [],
            "latest_date": None,
            "days_stale": None,
            "detail": (
                f"cannot read the sentinel's own schedule from {WORKFLOW_PATH} ({CADENCE_SOURCE_ERROR}) — "
                "grading a cadence against a hardcoded guess is how the Mon-only/Mon-Wed-Fri split went "
                "unnoticed for weeks (#3508). Fix the workflow read before trusting this leg."
            ),
        }

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


def _main(argv=None):
    """`--should-run-today` is the workflow's run guard (#3508): exit 0 = run the sentinel,
    exit 1 = not a scheduled day. The workflow no longer carries its own weekday literal,
    so the schedule cron in that same file is the only place the cadence is written.

    An unreadable/unparseable schedule exits 0 (RUN) and says why on stderr: an extra
    read-only sentinel run costs a handful of free API calls, while a silent skip is the
    exact failure this issue is about.
    """
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if "--should-run-today" not in argv:
        print(f"usage: {os.path.basename(__file__)} --should-run-today", file=sys.stderr)
        return 2
    if CADENCE_SOURCE_ERROR:
        print(f"[warn] cannot parse the schedule cron ({CADENCE_SOURCE_ERROR}) — running the sentinel anyway", file=sys.stderr)
        return 0
    today = datetime.now(timezone.utc)
    if should_run_today(today):
        print(f"{today.date()} (weekday {today.weekday()}) is a scheduled sentinel day: {sorted(EXPECTED_WEEKDAYS)}")
        return 0
    print(f"{today.date()} (weekday {today.weekday()}) is not in the schedule cron's day set {sorted(EXPECTED_WEEKDAYS)}")
    return 1


if __name__ == "__main__":  # pragma: no cover — exercised as a subprocess by the workflow
    raise SystemExit(_main())
