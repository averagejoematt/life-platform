"""deploy/emf_series_census.py — the live half: series growth visible BEFORE the bill (#2837).

``deploy/emf_namespace_ledger.py`` says what each namespace is FOR. This says
how big it actually got. It reads the live us-west-2 estate and grades it
against the ledger's per-namespace `series_budget`, which is the whole outcome
the issue asks for: *series growth is visible before the bill.*

Three failures it is built to catch, all of which were live when it was written:

  1. a registered namespace over its budget — the fan-out driver grew (more
     routes, more tools, more sources) and nobody noticed;
  2. a live namespace the repo emits with no ledger row — belt and braces with
     the offline guard, which catches the same thing at PR time from the repo
     alone;
  3. a LIVE ORPHAN — series in CloudWatch that nothing in the tree writes.
     Reported by name, graded **informational**, because there is no action to
     take: nothing writes them, so they leave the 14-day window on their own.
     Two existed at the audit (``LifePlatform/SiteApi``, #3002's retired casing
     twin, and ``LifePlatform/SiteAPIShapeProof``, with no reference anywhere in
     the tree). Failing on them would have meant a red the operator could only
     wait out — and registering them would have meant writing the retired twin's
     spelling back into the repo, which is precisely what #3002 forbids.

WHY IT REPORTS TWO SERIES NUMBERS. ``list-metrics`` returns everything that got
a datapoint in the last **14 days**; ``--recently-active PT3H`` returns what got
one in the last **3 hours**. CloudWatch bills a custom metric prorated by the
hours it receives data, so the 3h figure is far closer to the invoice than the
14d figure. On 2026-08-23 the estate was 703 series by the first measure and
102 by the second, against ~67 billed metric-months in Cost Explorer. A census
that printed only the 14d number would have the operator chasing
``LifePlatform/SiteAPI`` (288 series, 2 of them active) while
``LifePlatform/IngestLiveness`` (27 series, 22 active) is the one that bills.
Both are printed, and the ledger's budget grades the 14d number because that is
the one that reflects a *design* change rather than the hour of the day.

The PT3H figure is one sample, not a distribution (ADR-105): it is reported as
what it is and is never used as a pass/fail gate.

OFFLINE. No credentials, no boto3, or an AWS error => a loud SKIP banner and
exit 0. CI pull-request lanes have no AWS creds by design; a census that
silently "passed" there would be a check that cannot fail. ``--strict`` turns
the skip into exit 2 for the scheduled/attended runs where creds are expected.

USAGE
    python3 deploy/emf_series_census.py                  # human table + verdicts
    python3 deploy/emf_series_census.py --line           # the one-line cost-close entry
    python3 deploy/emf_series_census.py --alarms         # alarm dedupe candidates (#2891)
    python3 deploy/emf_series_census.py --json           # machine output
    python3 deploy/emf_series_census.py --strict         # missing creds is a failure

EXIT CODES  0 clean (or skipped) · 1 a graded failure · 2 skipped under --strict.
"""

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The platform's day frame is PACIFIC, not UTC (#2675/#3030: a UTC clock stamps
# tomorrow's date on every PT-evening run, and a cost-close line dated a day
# ahead is a line the calendar probe reads wrong).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))

from common.pacific_time import pacific_today  # noqa: E402 — path bootstrap above
from emf_namespace_ledger import LEDGER, MEASURED_ON  # noqa: E402 — path bootstrap above

REGION = os.environ.get("AWS_REGION", "us-west-2")
OWN_PREFIX = "LifePlatform"
ACTIVE_WINDOW = "PT3H"  # the only window list-metrics' --recently-active accepts

SKIP_BANNER = "[SKIP] emf-series-census — no live CloudWatch read (no AWS credentials/boto3). NOTHING WAS CHECKED."


def _is_own(namespace: str) -> bool:
    return namespace == OWN_PREFIX or namespace.startswith(OWN_PREFIX + "/")


def _count(client, **kwargs) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    token = None
    while True:
        page = client.list_metrics(**({"NextToken": token} if token else {}), **kwargs)
        for m in page.get("Metrics", []):
            if _is_own(m["Namespace"]):
                counts[m["Namespace"]] += 1
        token = page.get("NextToken")
        if not token:
            return counts


def read_live_estate():
    """`(all_14d, active_3h)` Counters, or `None` when the estate cannot be read."""
    try:
        import boto3

        client = boto3.client("cloudwatch", region_name=REGION)
        return _count(client), _count(client, RecentlyActive=ACTIVE_WINDOW)
    except Exception as exc:  # noqa: BLE001 — every failure mode is "cannot read", and it skips
        print(f"{SKIP_BANNER}\n        reason: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def grade(all_14d: collections.Counter, active_3h: collections.Counter) -> dict:
    """Ledger vs. live. Returns the full census plus the graded failures."""
    produced = producing_namespaces()
    over_budget, unregistered, live_orphans = [], [], []
    for ns, count in sorted(all_14d.items()):
        row = LEDGER.get(ns)
        if row is None:
            # Unregistered AND written by this repo is a real failure. Unregistered
            # and written by nothing is a live orphan: named, never graded, because
            # the only available action is to wait for the window to pass.
            (unregistered if ns in produced else live_orphans).append((ns, count))
        elif count > row["series_budget"]:
            over_budget.append((ns, count, row["series_budget"]))
    return {
        "measured_at": pacific_today(),
        "ledger_measured_on": MEASURED_ON,
        "region": REGION,
        "namespaces_live": len(all_14d),
        "series_14d": sum(all_14d.values()),
        "series_active_3h": sum(active_3h.values()),
        "namespaces_registered": len(LEDGER),
        "per_namespace": {ns: {"series_14d": c, "series_active_3h": active_3h.get(ns, 0)} for ns, c in sorted(all_14d.items())},
        "over_budget": over_budget,
        "unregistered": unregistered,
        "live_orphans": live_orphans,
    }


def producing_namespaces() -> set:
    """Namespaces this repo actually writes — the ledger's keys by construction."""
    from emf_namespace_discovery import discover_producers

    return set(discover_producers())


# ── alarm dedupe candidates (#2891, folded into #2837) ───────────────────────
#
# The premise #2891 was filed on — "103 metric alarms, ~$9-10/mo, 35 per-Lambda
# AWS/Lambda alarms" — re-measured on 2026-08-23 as 110 metric alarms, 36 of them
# AWS/Lambda, and $8.25 of AlarmMonitorUsage in July (84.2 alarm-months, the last
# full month; $6.68 Aug MTD). At ~$0.10/alarm-month the entire theoretical prize is
# about a dollar a month, so the bar for touching coverage is very high — which is
# ADR-116's rule, arrived at from the numbers rather than asserted.
#
# So the deriver proposes a candidate ONLY where coverage is equivalent by
# construction: the same (namespace, metric) already carries a **dimensionless**
# alarm — a genuine SET guard, since CloudWatch treats a dimensionless series as
# its own stream and the emitter must be writing a roll-up on purpose — AND the
# per-instance alarm matches it on statistic, comparison and threshold. Anything
# that differs on any of those is reported as NOT a candidate, with the reason.
# Cross-metric coverage claims (does `UnhealthySourceCount` cover
# `ConsecutiveFailures`?) are deliberately never inferred: that is a judgement
# about semantics, and a script guessing it is how coverage gets traded away.
#
# What a candidate still costs is ATTRIBUTION. `auth_breaker.auth_health_metric_data`
# emits both forms in one call and says why in its docstring (#1960): the
# dimensionless stream is what alarms, the Source dimension is "so the page names
# the culprit". Deduping keeps the detection and loses the name.

_EQUIVALENCE_FIELDS = ("Statistic", "ComparisonOperator", "Threshold")


def alarm_dedupe_candidates(alarms: list) -> dict:
    """`{"candidates": [...], "not_equivalent": [...]}` from a describe-alarms page."""
    groups: dict = {}
    for a in alarms:
        ns = a.get("Namespace")
        if not ns or not _is_own(ns):
            continue
        key = (ns, a.get("MetricName"))
        groups.setdefault(key, {"set": [], "instances": []})["instances" if a.get("Dimensions") else "set"].append(a)

    candidates, not_equivalent = [], []
    for (ns, metric), g in sorted(groups.items()):
        if not (g["set"] and g["instances"]):
            continue
        guard = g["set"][0]
        for inst in sorted(g["instances"], key=lambda a: a["AlarmName"]):
            differs = [f for f in _EQUIVALENCE_FIELDS if inst.get(f) != guard.get(f)]
            row = {
                "namespace": ns,
                "metric": metric,
                "alarm": inst["AlarmName"],
                "set_guard": guard["AlarmName"],
                "dimensions": {d["Name"]: d["Value"] for d in inst.get("Dimensions", [])},
            }
            if differs:
                row["differs_on"] = differs
                not_equivalent.append(row)
            else:
                candidates.append(row)
    return {"candidates": candidates, "not_equivalent": not_equivalent}


def read_alarms() -> list | None:
    try:
        import boto3

        client = boto3.client("cloudwatch", region_name=REGION)
        out, token = [], None
        while True:
            page = client.describe_alarms(**({"NextToken": token} if token else {}))
            out.extend(page.get("MetricAlarms", []))
            token = page.get("NextToken")
            if not token:
                return out
    except Exception as exc:  # noqa: BLE001
        print(f"{SKIP_BANNER}\n        reason: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def render_alarm_dedupe(result: dict) -> str:
    lines = ["Alarm dedupe candidates (#2891 folded into #2837) — us-west-2 metric alarms", ""]
    if result["candidates"]:
        lines.append("CANDIDATES — a dimensionless SET guard already watches the same metric on the")
        lines.append("same statistic/comparison/threshold. Retiring one keeps DETECTION and loses")
        lines.append("ATTRIBUTION (which instance). Owner call, not an automatic cut (ADR-116):")
        for r in result["candidates"]:
            lines.append(f"  {r['alarm']:40s} -> kept by {r['set_guard']}  [{r['namespace']}::{r['metric']} {r['dimensions']}]")
    else:
        lines.append("CANDIDATES — none.")
    lines += ["", "NOT candidates — a SET guard exists but does not cover the same condition:"]
    for r in result["not_equivalent"] or []:
        lines.append(f"  {r['alarm']:40s} differs from {r['set_guard']} on {', '.join(r['differs_on'])}")
    if not result["not_equivalent"]:
        lines.append("  (none)")
    lines += [
        "",
        "Every other alarm has NO set-level equivalent — including all AWS/Lambda Errors",
        "alarms, which #2891 named as the target. There are zero composite and zero",
        "metric-math alarms in this account, so nothing aggregates them today; retiring",
        "one removes coverage outright rather than consolidating it.",
    ]
    return "\n".join(lines)


def census_line(census: dict) -> str:
    """The dated one-liner the cost-close ritual appends to docs/PROPORTIONALITY.md."""
    return (
        f"- EMF census: {census['measured_at']} — {census['series_14d']} series / "
        f"{census['namespaces_live']} namespaces live (14d), {census['series_active_3h']} active (PT3H sample, n=1); "
        f"{len(census['over_budget'])} over budget, {len(census['unregistered'])} unregistered, "
        f"{len(census['live_orphans'])} live-orphan"
    )


def render(census: dict) -> str:
    lines = [
        f"EMF series census — {census['region']} — {census['measured_at']}",
        f"  live: {census['series_14d']} series across {census['namespaces_live']} namespaces (14d window)",
        f"  active: {census['series_active_3h']} series (single {ACTIVE_WINDOW} sample, n=1 — closest proxy to the bill)",
        f"  ledger: {census['namespaces_registered']} registered namespaces (measured {census['ledger_measured_on']})",
        "",
        f"  {'namespace':36s} {'14d':>5s} {'3h':>5s} {'budget':>7s}",
    ]
    for ns, d in sorted(census["per_namespace"].items(), key=lambda kv: -kv[1]["series_14d"]):
        budget = LEDGER[ns]["series_budget"] if ns in LEDGER else "—"
        flag = "  OVER BUDGET" if any(o[0] == ns for o in census["over_budget"]) else ""
        flag = flag or ("  UNREGISTERED" if any(u[0] == ns for u in census["unregistered"]) else "")
        flag = flag or ("  live orphan (nothing writes it — ages out)" if any(a[0] == ns for a in census["live_orphans"]) else "")
        lines.append(f"  {ns:36s} {d['series_14d']:5d} {d['series_active_3h']:5d} {str(budget):>7s}{flag}")
    if census["over_budget"]:
        lines += ["", "OVER BUDGET — the fan-out driver grew; re-price the row or cut the cardinality:"]
        lines += [f"  {ns}: {count} series > budget {budget}" for ns, count, budget in census["over_budget"]]
    if census["unregistered"]:
        lines += ["", "UNREGISTERED — this repo writes it and no row in deploy/emf_namespace_ledger.py covers it:"]
        lines += [f"  {ns}: {count} series" for ns, count in census["unregistered"]]
    if census["live_orphans"]:
        lines += ["", "LIVE ORPHANS (informational) — nothing in the tree writes these; they age out of the 14d window:"]
        lines += [f"  {ns}: {count} series" for ns, count in census["live_orphans"]]
    lines += ["", census_line(census)]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable census")
    ap.add_argument("--line", action="store_true", help="print only the dated cost-close line")
    ap.add_argument("--alarms", action="store_true", help="alarm dedupe candidates (#2891) instead of the series census")
    ap.add_argument("--strict", action="store_true", help="missing credentials is a failure (exit 2), not a skip")
    args = ap.parse_args(argv)

    if args.alarms:
        alarms = read_alarms()
        if alarms is None:
            return 2 if args.strict else 0
        result = alarm_dedupe_candidates(alarms)
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else render_alarm_dedupe(result))
        return 0

    estate = read_live_estate()
    if estate is None:
        return 2 if args.strict else 0

    census = grade(*estate)
    if args.json:
        print(json.dumps(census, indent=2, sort_keys=True))
    elif args.line:
        print(census_line(census))
    else:
        print(render(census))
    return 1 if (census["over_budget"] or census["unregistered"]) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
