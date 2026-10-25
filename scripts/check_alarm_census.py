#!/usr/bin/env python3
"""scripts/check_alarm_census.py — the live-vs-model alarm census (#5143).

The model (`model/platform_model.json` `alarms` plane) enumerates every CDK-declared
alarm by NAME; nothing compared that set with what CloudWatch actually holds. A 2026-10-25
read-only audit counted 144 live (134 metric + 4 composite in us-west-2, 6 in us-east-1)
against 141 modelled, by hand, and found no guard that would have said so. This is that
guard: it lists every live alarm (`describe_alarms`, read-only, MetricAlarm +
CompositeAlarm, in every region a stack deploys to — the region map is
`drift_sentinel.STACKS` / `check_lambda_config_drift.STACK_FILE_REGION`) and compares the
NAME SET, not the count, with the modelled set.

Verdicts (exit 1 on any):
  only-live    a live alarm the model does not hold and `ACCEPTED_ORPHANS` does not name
               — an un-modelled CDK alarm (fix the enumeration), a console-made alarm
               (owner retires it), or an alarm from a stack applied but not modelled.
  only-model   a modelled alarm that is not live — its stack is unapplied (name it), or
               the alarm was deleted by hand.
  stale-accept an `ACCEPTED_ORPHANS` entry that is no longer live — prune it.
Exit 0 + "UNVERIFIED" when AWS is unreachable (fail-open, like check_alarm_citations);
a half-read estate (one region errored) is UNVERIFIED too, never a pass.

NEVER writes: only `cloudwatch:DescribeAlarms`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))

MODEL_PATH = ROOT / "model" / "platform_model.json"
HOME_REGION = "us-west-2"

# Live alarms that are deliberately NOT in CDK, each with the ruling that says so.
# Source: cdk/stacks/web_alarms.py (#2829/#2961 "DO NOT ADOPT" — adopting an alarm under an
# existing physical name fails CloudFormation early validation and blocks LifePlatformWeb).
# An entry is a RULING, not a convenience: prune it the day the alarm is retired
# (a no-longer-live entry reds as `stale-accept`).
ACCEPTED_ORPHANS: dict[str, str] = {
    "life-platform-dash-5xx-rate": "us-east-1 console alarm, routed to life-platform-alerts-us-east-1; #2961 decided NOT to adopt",
    "life-platform-dash-total-errors": "us-east-1 console alarm on the MAIN distribution E3S424OXQZ8NBE (name is a lie); #2961 not adopted, rename = history loss",
    "life-platform-cf-auth-errors": "us-east-1 console alarm, AlarmActions=[], watches an unassociated Lambda@Edge fn; candidate for OWNER retirement (#2961/#2962)",
}


def regions() -> list[str]:
    """Every region a stack deploys to — drift_sentinel.STACKS is the source of truth."""
    import drift_sentinel

    return sorted(set(drift_sentinel.STACKS.values()) | {HOME_REGION})


def stack_region(stack: str) -> str:
    import check_lambda_config_drift as cd

    return cd.STACK_FILE_REGION.get(f"{stack}.py", HOME_REGION)


def modelled(model: dict | None = None) -> dict[str, str]:
    """{alarm name: region} from the model's alarms plane."""
    model = model if model is not None else json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    return {name: stack_region(row.get("stack", "")) for name, row in model["alarms"].items()}


def live_alarms(regs: list[str], client_factory=None) -> tuple[dict[str, str], list[str]]:
    """({alarm name: region}, [regions that could not be read]). Read-only."""
    if client_factory is None:
        import boto3

        def client_factory(r):
            return boto3.client("cloudwatch", region_name=r)

    out: dict[str, str] = {}
    failed: list[str] = []
    for r in regs:
        try:
            cw = client_factory(r)
            for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["CompositeAlarm", "MetricAlarm"]):
                for a in page.get("CompositeAlarms", []) + page.get("MetricAlarms", []):
                    out[a["AlarmName"]] = r
        except Exception as e:  # noqa: BLE001 — any read failure => unverified, not a pass
            print(f"(region {r}) could not read alarms: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(r)
    return out, failed


def compare(live: dict[str, str], model: dict[str, str], accepted: dict[str, str] | None = None) -> dict[str, list[str]]:
    """The set comparison. Names only-live (minus accepted), only-model, stale accepts,
    and region mismatches (same name, different region)."""
    accepted = ACCEPTED_ORPHANS if accepted is None else accepted
    only_live = sorted(set(live) - set(model) - set(accepted))
    only_model = sorted(set(model) - set(live))
    stale = sorted(n for n in accepted if n not in live)
    both_modelled_and_accepted = sorted(n for n in accepted if n in model)
    moved = sorted(f"{n} (live {live[n]}, model {model[n]})" for n in set(live) & set(model) if live[n] != model[n])
    return {
        "only-live": only_live,
        "only-model": only_model,
        "stale-accept": stale,
        "accepted-now-modelled": both_modelled_and_accepted,
        "region-mismatch": moved,
    }


def main(argv: list[str] | None = None) -> int:
    regs = regions()
    model = modelled()
    live, failed = live_alarms(regs)
    if failed:
        print(f"UNVERIFIED — could not read {', '.join(failed)}; alarm census not judged (fail-open)")
        return 0
    res = compare(live, model)
    print(f"alarm census: live={len(live)} model={len(model)} accepted-orphans={len(ACCEPTED_ORPHANS)} regions={','.join(regs)}")
    for n, why in sorted(ACCEPTED_ORPHANS.items()):
        if n in live:
            print(f"  accepted orphan: {n} — {why}")
    bad = False
    for kind, names in res.items():
        for n in names:
            bad = True
            print(f"  {kind}: {n}")
    if bad:
        print("alarm census: DIFFERENT — reconcile (model enumeration / owner retire / apply the unapplied stack)")
        return 1
    print("alarm census: CLEAN — live set == modelled set + accepted orphans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
