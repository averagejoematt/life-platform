#!/usr/bin/env python3
"""The #4641 re-measure: per-function runs/day and per-secret write counts over a window (READ-ONLY).

    python3 scripts/ingestion_churn_remeasure.py --since 2026-10-19 --until 2026-11-02
    python3 scripts/ingestion_churn_remeasure.py --since 2026-10-19 --until 2026-11-02 --json

The issue's acceptance reads "after 14 days live, the per-source run counts and secret-write
counts are pasted beside the 2026-10-04 figures". This is that paste, from one command, with no
write of any kind:

  * Runs/day: CloudWatch `AWS/Lambda` `Invocations` (Sum, one datapoint per UTC day) for every
    scheduled ingestion function, set beside the schedule's own derived runs/day
    (`scripts/ingestion_runs_per_day.py`, which includes the site-stats refresh's invocations)
    and beside the 2026-10-04 figure the issue recorded.
  * Secret writes: CloudTrail `UpdateSecret` events (the framework's write-back is
    `secrets_client.update_secret`) grouped by `life-platform/<secret>`; the 2026-10-04 total was
    1,106 in 14 days across four sources. A secret should now be written only when its token
    really rotated, so a count far above the source's real refreshes is the regression.
  * Extra rules: the `function#RuleName` schedules (reconciles, Whoop's recovery refresh, Hevy's index
    rebuild), which `ingestion_runs_per_day.py` leaves out of a function's own cadence.
  * Boot probes: `pipeline-health-check` invokes every probed function with `{"healthcheck": true}`
    on its own schedule (5/day), which returns before any vendor call or secret read. CloudWatch
    cannot tell these from scheduled runs, so they are added to the expected figure — measured
    runs sit exactly that many above the schedule, and a gap beyond it is the finding.
  * Habitify's mean duration, because removing the per-habit notes calls (Q28) was expected to take
    the run from ~36 s to ~1 s.

`--since` is inclusive and `--until` exclusive, both whole UTC days. CloudTrail's lookup reads
management events for 90 days and allows two calls a second, so it paginates slowly.
Never run this against a window that is not complete days: a partial day reads as a low count.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingestion_runs_per_day as rpd  # noqa: E402

REGION = "us-west-2"

# Runs/day measured 2026-10-04 over 14 days (the #4641 body's table). The three social feeds are
# retired (Q39), so their expected figure is 0; the issue's per-source "total" for withings and
# habitify includes the site-stats refresh's four invocations.
BASELINE_RUNS_PER_DAY = {
    "notion-journal-ingestion": 18,
    "youtube-social-ingestion": 18,
    "bluesky-social-ingestion": 18,
    "mastodon-social-ingestion": 18,
    "dropbox-poll": 48,
    "hevy-backfill": 24,
    "withings-data-ingestion": 22,
    "eightsleep-data-ingestion": 18,
    "habitify-data-ingestion": 28,
}
BASELINE_SECRET_WRITES_14D = 1106  # across four sources: 308, 280, 266, 252 (Withings 308)
BASELINE_HABITIFY_MEAN_SECONDS = 36.5
SECRET_PREFIX = "life-platform/"  # noqa: S105 - a Secrets Manager name prefix, not a credential


def utc_days(since: date, until: date) -> list[date]:
    if until <= since:
        raise ValueError("--until must be after --since")
    return [since + timedelta(days=i) for i in range((until - since).days)]


def _start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def daily_invocations(cloudwatch, function: str, since: date, until: date) -> dict:
    """{ 'YYYY-MM-DD': invocations } for each whole UTC day in the window (a missing datapoint is 0)."""
    resp = cloudwatch.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName="Invocations",
        Dimensions=[{"Name": "FunctionName", "Value": function}],
        StartTime=_start(since),
        EndTime=_start(until),
        Period=86400,
        Statistics=["Sum"],
    )
    got = {p["Timestamp"].astimezone(timezone.utc).date().isoformat(): int(p["Sum"]) for p in resp.get("Datapoints", [])}
    return {d.isoformat(): got.get(d.isoformat(), 0) for d in utc_days(since, until)}


def mean_duration_seconds(cloudwatch, function: str, since: date, until: date) -> float | None:
    resp = cloudwatch.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName="Duration",
        Dimensions=[{"Name": "FunctionName", "Value": function}],
        StartTime=_start(since),
        EndTime=_start(until),
        Period=86400 * max(1, (until - since).days),
        Statistics=["Average"],
    )
    points = resp.get("Datapoints", [])
    return round(points[0]["Average"] / 1000.0, 2) if points else None


def secret_name(event_json: str) -> str | None:
    """The secret an `UpdateSecret` CloudTrail event wrote, without the `life-platform/` prefix."""
    try:
        sid = (json.loads(event_json).get("requestParameters") or {}).get("secretId")
    except (TypeError, ValueError):
        return None
    if not sid:
        return None
    sid = str(sid)
    if ":secret:" in sid:  # an ARN carries a random "-XXXXXX" suffix after the name
        sid = sid.split(":secret:")[-1].rsplit("-", 1)[0]
    return sid[len(SECRET_PREFIX) :] if sid.startswith(SECRET_PREFIX) else sid


def secret_writes(cloudtrail, since: date, until: date, sleep=time.sleep) -> Counter:
    """Counter of `UpdateSecret` events per secret over the window. Paginates; two calls a second at most."""
    counts: Counter = Counter()
    kwargs = {
        "LookupAttributes": [{"AttributeKey": "EventName", "AttributeValue": "UpdateSecret"}],
        "StartTime": _start(since),
        "EndTime": _start(until),
        "MaxResults": 50,
    }
    while True:
        resp = cloudtrail.lookup_events(**kwargs)
        for ev in resp.get("Events", []):
            name = secret_name(ev.get("CloudTrailEvent", ""))
            if name:
                counts[name] += 1
        token = resp.get("NextToken")
        if not token:
            return counts
        kwargs["NextToken"] = token
        sleep(0.6)


def boot_probes_per_day() -> dict:
    """{function: healthcheck invocations/day} from pipeline-health-check's own schedule and probe list."""
    rows = rpd._schedule_table().load()
    per_run = sum(rpd.runs_per_day_expr(r["expression"]) or 0 for k, r in rows.items() if k == "pipeline-health-check")
    sys.path.insert(0, os.path.join(rpd.ROOT, "lambdas"))
    from ingestion.source_registry import SOURCE_REGISTRY, health_probe_targets

    return {fn: per_run for fn, _display, src in health_probe_targets() if not SOURCE_REGISTRY.get(src, {}).get("paused")}


def extra_rules_per_day() -> dict:
    """{function: runs/day} of the `function#RuleName` schedules (reconciles, whoop's recovery refresh, hevy's index rebuild).

    `ingestion_runs_per_day.own_schedules` leaves these out (they are not the function's cadence), but
    each one is a real invocation, so a measured count that ignored them would read as a surplus.
    """
    out: dict = {}
    for key, row in rpd._schedule_table().load().items():
        if "#" in key and row["stack"] == "LifePlatformIngestion":
            out[row["function"]] = out.get(row["function"], 0) + (rpd.runs_per_day_expr(row["expression"]) or 0)
    return out


def build_report(cloudwatch, cloudtrail, since: date, until: date, sleep=time.sleep) -> dict:
    days = utc_days(since, until)
    probes = boot_probes_per_day()
    extras = extra_rules_per_day()
    rows = []
    for r in rpd.table():
        fn = r["function"]
        per_day = daily_invocations(cloudwatch, fn, since, until)
        total = sum(per_day.values())
        mean = round(total / len(days), 2)
        expected = r["total"] + extras.get(fn, 0) + probes.get(fn, 0)
        rows.append(
            {
                "function": fn,
                "source": r["source"],
                "scheduled_per_day": r["total"],
                "extra_rules_per_day": extras.get(fn, 0),
                "boot_probes_per_day": probes.get(fn, 0),
                "expected_per_day": expected,
                "measured_per_day": mean,
                "baseline_2026_10_04": BASELINE_RUNS_PER_DAY.get(fn),
                "off_schedule": abs(mean - expected) > 0.5,
                "invocations": total,
            }
        )
    for fn, base in BASELINE_RUNS_PER_DAY.items():
        if fn not in {r["function"] for r in rows}:  # a retired schedule: it should now read 0
            total = sum(daily_invocations(cloudwatch, fn, since, until).values())
            rows.append(
                {
                    "function": fn,
                    "source": None,
                    "scheduled_per_day": 0,
                    "extra_rules_per_day": 0,
                    "boot_probes_per_day": 0,
                    "expected_per_day": 0,
                    "measured_per_day": round(total / len(days), 2),
                    "baseline_2026_10_04": base,
                    "off_schedule": total > 0,
                    "invocations": total,
                }
            )
    writes = secret_writes(cloudtrail, since, until, sleep)
    return {
        "window": {"since": since.isoformat(), "until_exclusive": until.isoformat(), "days": len(days)},
        "runs": sorted(rows, key=lambda x: x["function"]),
        "secret_writes": dict(sorted(writes.items())),
        "secret_writes_total": sum(writes.values()),
        "secret_writes_baseline_14d": BASELINE_SECRET_WRITES_14D,
        "habitify_mean_seconds": mean_duration_seconds(cloudwatch, "habitify-data-ingestion", since, until),
        "habitify_baseline_mean_seconds": BASELINE_HABITIFY_MEAN_SECONDS,
    }


def render(report: dict) -> str:
    w = report["window"]
    out = [f"window: {w['since']} .. {w['until_exclusive']} (exclusive), {w['days']} UTC days"]
    out.append(f"{'function':32} {'sched':>5} {'rules':>5} {'probes':>6} {'expected':>8} {'measured':>8} {'2026-10-04':>10}  flag")
    for r in report["runs"]:
        base = "-" if r["baseline_2026_10_04"] is None else r["baseline_2026_10_04"]
        out.append(
            f"{r['function']:32} {r['scheduled_per_day']:>5} {r['extra_rules_per_day']:>5} {r['boot_probes_per_day']:>6} {r['expected_per_day']:>8} "
            f"{r['measured_per_day']:>8} {base:>10}  {'OFF-SCHEDULE' if r['off_schedule'] else ''}"
        )
    out.append("")
    out.append(f"secret writes (CloudTrail UpdateSecret): {report['secret_writes_total']} in {w['days']} days")
    for name, n in report["secret_writes"].items():
        out.append(f"  {name:24} {n:>5}  ({n / w['days']:.1f}/day)")
    out.append(f"  2026-10-04 baseline: {report['secret_writes_baseline_14d']} in 14 days across four sources")
    out.append(f"habitify mean run: {report['habitify_mean_seconds']} s (2026-10-04: {report['habitify_baseline_mean_seconds']} s)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", required=True, type=date.fromisoformat, help="first whole UTC day, inclusive")
    ap.add_argument("--until", required=True, type=date.fromisoformat, help="last whole UTC day, exclusive")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    import boto3  # imported late so the pure helpers test without it configured

    report = build_report(
        boto3.client("cloudwatch", region_name=REGION), boto3.client("cloudtrail", region_name=REGION), args.since, args.until
    )
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
