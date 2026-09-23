#!/usr/bin/env python3
"""
deploy/sensor_self_test.py — every liveness sensor proves it can still do its job (#4034 box 2).

A heartbeat alarm is a claim about the future: "if the thing I watch goes quiet, I go red."
Nothing checked that the sensor itself could still read what it watches or write what it
emits — a deploy that renames a metric, drops an IAM grant, or deletes the alarm leaves the
ledger in `tests/test_heartbeat_completeness.py` green (it only checks that NAMES exist in
source) while the sensor is blind. This is the capability check, run after every deploy by
`deploy/post_cdk_smoke.sh`.

THE SET IS DERIVED, NEVER LISTED
────────────────────────────────
The sensors are read out of `tests/test_heartbeat_completeness.py` — its COVERAGE registry
plus NON_SCHEDULED_EMITTERS — and grouped by the ROW KIND:

  ALARM            one sensor per distinct absence alarm the ledger cites
  ingest-liveness  the ER-01 sweep: its two alarms + the INGEST_HEALTH sentinel read
  producer-census  the #4034 census: the AWS/Lambda Invocations read it grades on

`SELF_TESTS` maps each row kind to its self-test. A COVERAGE kind with no self-test reds in
`tests/test_sensor_self_test_4034.py` — the "an entry without a self-test" rule. EXEMPT rows
have no sensor by definition (that is what an exemption is) and are skipped.

WHAT A SELF-TEST DOES (its REAL read and its write, against a SCRATCH key)
─────────────────────────────────────────────────────────────────────────
  read   the sensor's own read path, live: `describe_alarms` for the alarm (it must exist,
         with actions not disabled), then `get_metric_data` on the EXACT metric or metric-math
         the alarm evaluates; for ingest-liveness also the DynamoDB `USER#system` /
         `INGEST_HEALTH#` query the ER-01 sweep runs; for the census its Invocations read.
  write  one `put_metric_data` datapoint to the scratch namespace `LifePlatform/SelfTest`,
         dimension `Sensor=<sensor id>` — never the live series, so a self-test can neither
         feed nor mute the alarm it is testing. No DynamoDB or S3 writes, ever.

A verdict is `ok` or `degraded` with the step that failed. `--self-test` exits 1 on any
degraded verdict — the post-deploy gate.

WHAT IT CANNOT PROVE (stated, not implied)
──────────────────────────────────────────
It runs under the DEPLOYER's credentials, so the write proves the CloudWatch write path and
endpoint, not the producer Lambda's own role grant. The producer's own liveness is the
alarm's job (and the census's); this proves the alarm half and the read half can still work.

Usage
    python3 deploy/sensor_self_test.py --self-test              # the whole derived set
    python3 deploy/sensor_self_test.py --self-test --sensor qa-smoke-heartbeat
    python3 deploy/sensor_self_test.py --list                   # the derived set, no AWS
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "tests"), os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SCRATCH_NAMESPACE = "LifePlatform/SelfTest"
SCRATCH_METRIC = "SelfTestWrite"
READ_LOOKBACK_HOURS = 48

OK = "ok"
DEGRADED = "degraded"

KIND_ALARM = "alarm"
KIND_LIVENESS = "ingest-liveness"
KIND_CENSUS = "producer-census"
ER01_ALARMS = ("ingest-liveness-unhealthy", "ingest-liveness-heartbeat")
ER01_SENSOR = "ingest-liveness"
CENSUS_SENSOR = "producer-census"


# ── the derived sensor set ──────────────────────────────────────────────────


def _ledger():
    import test_heartbeat_completeness as hb

    return hb


def sensor_set() -> dict[str, dict]:
    """{sensor_id: {"kind": ..., "alarms": (...), "covers": [function, ...]}} — derived
    from the heartbeat ledger's COVERAGE + NON_SCHEDULED_EMITTERS, grouped by row kind."""
    hb = _ledger()
    out: dict[str, dict] = {}
    for fn, entry in sorted(hb.COVERAGE.items()):
        kind = entry[0]
        if kind == hb.ALARM:
            row = out.setdefault(entry[1], {"kind": KIND_ALARM, "alarms": (entry[1],), "covers": []})
        elif kind == hb.LIVENESS:
            row = out.setdefault(ER01_SENSOR, {"kind": KIND_LIVENESS, "alarms": ER01_ALARMS, "covers": []})
        elif kind == getattr(hb, "CENSUS", None):
            row = out.setdefault(CENSUS_SENSOR, {"kind": KIND_CENSUS, "alarms": (), "covers": []})
        elif kind == hb.EXEMPT:
            continue  # an exemption has no sensor — that is what it is
        else:
            row = out.setdefault(f"unknown-kind:{kind}", {"kind": kind, "alarms": (), "covers": []})
        row["covers"].append(fn)
    for channel, entry in sorted(hb.NON_SCHEDULED_EMITTERS.items()):
        row = out.setdefault(entry[1], {"kind": KIND_ALARM, "alarms": (entry[1],), "covers": []})
        row["covers"].append(channel)
    return out


# ── the two halves ──────────────────────────────────────────────────────────


def _metric_queries(alarm: dict) -> list[dict]:
    """The GetMetricData queries for EXACTLY what the alarm evaluates."""
    if alarm.get("Metrics"):
        queries = []
        for m in alarm["Metrics"]:
            q = {"Id": m["Id"], "ReturnData": bool(m.get("ReturnData", False))}
            if "MetricStat" in m:
                q["MetricStat"] = m["MetricStat"]
            if "Expression" in m:
                q["Expression"] = m["Expression"]
                if "Period" in m:
                    q["Period"] = m["Period"]
            queries.append(q)
        return queries
    stat = alarm.get("Statistic") or alarm.get("ExtendedStatistic") or "Sum"
    return [
        {
            "Id": "m0",
            "ReturnData": True,
            "MetricStat": {
                "Metric": {"Namespace": alarm["Namespace"], "MetricName": alarm["MetricName"], "Dimensions": alarm.get("Dimensions", [])},
                "Period": int(alarm.get("Period") or 300),
                "Stat": stat,
            },
        }
    ]


def read_alarm(cw, name: str, now) -> str | None:
    """The sensor's read path. Returns a failure string, or None when it can read."""
    resp = cw.describe_alarms(AlarmNames=[name], AlarmTypes=["MetricAlarm", "CompositeAlarm"])
    found = list(resp.get("MetricAlarms", [])) + list(resp.get("CompositeAlarms", []))
    if not found:
        return f"alarm {name!r} does not exist live"
    alarm = found[0]
    if alarm.get("ActionsEnabled") is False:
        return f"alarm {name!r} has its actions DISABLED — it would go red and tell nobody"
    if "AlarmRule" in alarm:
        return None  # a composite reads other alarms, not a metric
    cw.get_metric_data(MetricDataQueries=_metric_queries(alarm), StartTime=now - timedelta(hours=READ_LOOKBACK_HOURS), EndTime=now)
    return None


def write_scratch(cw, sensor_id: str) -> None:
    cw.put_metric_data(
        Namespace=SCRATCH_NAMESPACE,
        MetricData=[{"MetricName": SCRATCH_METRIC, "Dimensions": [{"Name": "Sensor", "Value": sensor_id}], "Value": 1.0, "Unit": "Count"}],
    )


# ── one self-test per row kind ──────────────────────────────────────────────


def self_test_alarm(sensor_id, spec, clients, now):
    cw = clients["cloudwatch"]
    for name in spec["alarms"]:
        problem = read_alarm(cw, name, now)
        if problem:
            return problem
    write_scratch(cw, sensor_id)
    return None


def self_test_ingest_liveness(sensor_id, spec, clients, now):
    problem = self_test_alarm(sensor_id, spec, clients, now)
    if problem:
        return problem
    from ingestion.ingest_health import SYSTEM_PK  # the ER-01 sweep's own key, never retyped

    resp = clients["dynamodb"].query(
        TableName=TABLE_NAME,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": {"S": SYSTEM_PK}, ":pfx": {"S": "INGEST_HEALTH#"}},
        Limit=50,
    )
    if not resp.get("Items"):
        return "the INGEST_HEALTH sentinel query returned ZERO rows — the ER-01 sweep would grade every source on nothing"
    return None


def self_test_producer_census(sensor_id, spec, clients, now):
    import sentinel_producer_census as pc

    population = pc.census_population()
    if not population:
        return "census population derived EMPTY"
    probe = sorted(population)[:5]
    last = pc.fetch_last_invocations(probe, clients["cloudwatch"], now, lookback_days=7)
    if not any(last.values()):
        return f"Invocations read returned nothing for any of {probe} in 7 days — the census would read every producer as silent"
    write_scratch(clients["cloudwatch"], sensor_id)
    return None


SELF_TESTS = {
    KIND_ALARM: self_test_alarm,
    KIND_LIVENESS: self_test_ingest_liveness,
    KIND_CENSUS: self_test_producer_census,
}


def run(sensors: dict, clients: dict, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    results = []
    for sensor_id, spec in sorted(sensors.items()):
        fn = SELF_TESTS.get(spec["kind"])
        if fn is None:
            results.append({"sensor": sensor_id, "verdict": DEGRADED, "detail": f"no self-test registered for row kind {spec['kind']!r}"})
            continue
        try:
            problem = fn(sensor_id, spec, clients, now)
        except Exception as e:  # noqa: BLE001 — a crashed self-test is a degraded sensor
            problem = f"{type(e).__name__}: {e}"
        results.append({"sensor": sensor_id, "verdict": DEGRADED if problem else OK, "detail": problem or "read + scratch write ok"})
    return results


def _clients():
    import boto3

    return {"cloudwatch": boto3.client("cloudwatch", region_name=REGION), "dynamodb": boto3.client("dynamodb", region_name=REGION)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--self-test", action="store_true", help="run every derived sensor's self-test (reads live, writes scratch)")
    ap.add_argument("--sensor", action="append", help="limit to this sensor id (repeatable)")
    ap.add_argument("--list", action="store_true", help="print the derived sensor set and exit (no AWS)")
    args = ap.parse_args(argv)
    sensors = sensor_set()
    if args.sensor:
        unknown = sorted(set(args.sensor) - set(sensors))
        if unknown:
            print(f"unknown sensor id(s): {unknown}; known: {sorted(sensors)}")
            return 2
        sensors = {k: v for k, v in sensors.items() if k in args.sensor}
    if args.list or not args.self_test:
        for sid, spec in sorted(sensors.items()):
            print(f"{sid:40s} {spec['kind']:16s} covers {len(spec['covers'])}")
        return 0
    results = run(sensors, _clients())
    degraded = [r for r in results if r["verdict"] != OK]
    for r in results:
        print(f"  [{r['verdict'].upper():8s}] {r['sensor']:40s} {r['detail']}")
    print(f"sensor self-test: {len(results) - len(degraded)}/{len(results)} ok")
    return 1 if degraded else 0


if __name__ == "__main__":
    sys.exit(main())
