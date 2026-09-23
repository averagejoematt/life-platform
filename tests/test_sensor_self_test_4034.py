"""tests/test_sensor_self_test_4034.py — liveness-sensor self-tests (#4034 box 2).

Every test here drives `deploy/sensor_self_test.py` against STUBBED clients built to the
CloudWatch / DynamoDB wire shapes. Nothing in this file touches AWS; the first live run is
the first `deploy/post_cdk_smoke.sh` after merge.
"""

import os
import re
import sys
from datetime import datetime, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("deploy", "tests", "lambdas"):
    p = os.path.join(_ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import sensor_self_test as st  # noqa: E402
import test_heartbeat_completeness as hb  # noqa: E402

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


# ── the set is derived, and every kind has a self-test ──────────────────────


def test_every_coverage_kind_with_a_sensor_has_a_self_test():
    """'An entry without a self-test reds': every row kind the ledger uses, except the
    exemption (which by definition has no sensor), must map to a registered self-test."""
    kinds = {entry[0] for entry in hb.COVERAGE.values()} | {entry[0] for entry in hb.NON_SCHEDULED_EMITTERS.values()}
    kinds.discard(hb.EXEMPT)
    kind_to_sensor_kind = {hb.ALARM: st.KIND_ALARM, hb.LIVENESS: st.KIND_LIVENESS, hb.CENSUS: st.KIND_CENSUS}
    missing = sorted(k for k in kinds if kind_to_sensor_kind.get(k) not in st.SELF_TESTS)
    assert not missing, f"COVERAGE row kind(s) with no registered self-test in deploy/sensor_self_test.SELF_TESTS: {missing}"


def test_sensor_set_is_derived_from_the_ledger():
    sensors = st.sensor_set()
    alarm_rows = {e[1] for e in hb.COVERAGE.values() if e[0] == hb.ALARM} | {e[1] for e in hb.NON_SCHEDULED_EMITTERS.values()}
    assert alarm_rows <= set(sensors), f"alarm sensors missing from the derived set: {sorted(alarm_rows - set(sensors))}"
    covered = sorted(fn for spec in sensors.values() for fn in spec["covers"] if fn in hb.COVERAGE)
    expected = sorted(fn for fn, e in hb.COVERAGE.items() if e[0] != hb.EXEMPT)
    assert covered == expected, "every non-exempt COVERAGE row must be covered by exactly one derived sensor"
    assert not [s for s in sensors if s.startswith("unknown-kind:")]
    assert sensors[st.ER01_SENSOR]["alarms"] == st.ER01_ALARMS
    assert len(sensors[st.CENSUS_SENSOR]["covers"]) >= 40


def test_a_row_of_an_unregistered_kind_is_degraded_not_skipped():
    out = st.run({"x": {"kind": "brand-new-kind", "alarms": (), "covers": ["f"]}}, clients={}, now=NOW)
    assert out[0]["verdict"] == st.DEGRADED and "no self-test registered" in out[0]["detail"]


# ── stubs on the wire shape ─────────────────────────────────────────────────


class _CW:
    def __init__(self, alarms, fail_put=False):
        self.alarms = alarms
        self.fail_put = fail_put
        self.puts, self.reads = [], []

    def describe_alarms(self, AlarmNames, AlarmTypes):
        assert set(AlarmTypes) == {"MetricAlarm", "CompositeAlarm"}, "composites are invisible without AlarmTypes (#3503)"
        found = [self.alarms[n] for n in AlarmNames if n in self.alarms]
        return {
            "MetricAlarms": [a for a in found if "AlarmRule" not in a],
            "CompositeAlarms": [a for a in found if "AlarmRule" in a],
        }

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, **kw):
        self.reads.append(MetricDataQueries)
        results = []
        for q in MetricDataQueries:
            label = q.get("Label", q["Id"])
            results.append({"Id": q["Id"], "Label": label, "Timestamps": [EndTime], "Values": [1.0]})
        return {"MetricDataResults": results}

    def put_metric_data(self, Namespace, MetricData):
        if self.fail_put:
            raise RuntimeError("AccessDenied: cloudwatch:PutMetricData")
        self.puts.append((Namespace, MetricData))


class _DDB:
    def __init__(self, items):
        self.items, self.queries = items, []

    def query(self, **kw):
        self.queries.append(kw)
        return {"Items": self.items}


def _metric_alarm(name, ns="LifePlatform/QaSmoke", metric="RunCompleted", **extra):
    a = {
        "AlarmName": name,
        "ActionsEnabled": True,
        "Namespace": ns,
        "MetricName": metric,
        "Statistic": "Sum",
        "Period": 86400,
        "Dimensions": [],
    }
    a.update(extra)
    return a


def test_alarm_self_test_reads_the_exact_metric_and_writes_only_scratch():
    cw = _CW({"qa-smoke-heartbeat": _metric_alarm("qa-smoke-heartbeat")})
    out = st.run({"qa-smoke-heartbeat": {"kind": st.KIND_ALARM, "alarms": ("qa-smoke-heartbeat",), "covers": []}}, {"cloudwatch": cw}, NOW)
    assert out[0]["verdict"] == st.OK, out
    q = cw.reads[0][0]["MetricStat"]
    assert q["Metric"]["Namespace"] == "LifePlatform/QaSmoke" and q["Metric"]["MetricName"] == "RunCompleted" and q["Period"] == 86400
    assert [ns for ns, _ in cw.puts] == [
        st.SCRATCH_NAMESPACE
    ], "a self-test wrote outside the scratch namespace — it could feed or mute the live alarm"
    assert cw.puts[0][1][0]["Dimensions"] == [{"Name": "Sensor", "Value": "qa-smoke-heartbeat"}]


def test_metric_math_alarm_is_read_through_its_own_queries():
    math = _metric_alarm("board-verdict-silence-7d")
    for k in ("Namespace", "MetricName", "Statistic", "Period", "Dimensions"):
        math.pop(k)
    math["Metrics"] = [
        {
            "Id": "v",
            "ReturnData": False,
            "MetricStat": {"Metric": {"Namespace": "LifePlatform/AI", "MetricName": "X"}, "Period": 3600, "Stat": "Sum"},
        },
        {"Id": "e", "ReturnData": True, "Expression": "v * 1", "Label": "silence"},
    ]
    cw = _CW({"board-verdict-silence-7d": math})
    out = st.run({"b": {"kind": st.KIND_ALARM, "alarms": ("board-verdict-silence-7d",), "covers": []}}, {"cloudwatch": cw}, NOW)
    assert out[0]["verdict"] == st.OK, out
    assert [q["Id"] for q in cw.reads[0]] == ["v", "e"] and cw.reads[0][1]["Expression"] == "v * 1"


@pytest.mark.parametrize(
    "alarms, fail_put, needle",
    [
        ({}, False, "does not exist live"),
        ({"a": _metric_alarm("a", ActionsEnabled=False)}, False, "DISABLED"),
        ({"a": _metric_alarm("a")}, True, "PutMetricData"),
    ],
)
def test_alarm_self_test_degrades_on_each_blind_state(alarms, fail_put, needle):
    cw = _CW(alarms, fail_put=fail_put)
    out = st.run({"a": {"kind": st.KIND_ALARM, "alarms": ("a",), "covers": []}}, {"cloudwatch": cw}, NOW)
    assert out[0]["verdict"] == st.DEGRADED and needle in out[0]["detail"], out


def test_ingest_liveness_self_test_reads_the_er01_partition():
    alarms = {n: _metric_alarm(n, ns="LifePlatform/IngestLiveness", metric="UnhealthySourceCount") for n in st.ER01_ALARMS}
    spec = {"kind": st.KIND_LIVENESS, "alarms": st.ER01_ALARMS, "covers": []}
    ddb = _DDB([{"pk": {"S": "USER#system"}, "sk": {"S": "INGEST_HEALTH#whoop"}}])
    out = st.run({st.ER01_SENSOR: spec}, {"cloudwatch": _CW(alarms), "dynamodb": ddb}, NOW)
    assert out[0]["verdict"] == st.OK, out
    q = ddb.queries[0]["ExpressionAttributeValues"]
    assert q[":pk"] == {"S": "USER#system"} and q[":pfx"] == {"S": "INGEST_HEALTH#"}
    empty = st.run({st.ER01_SENSOR: spec}, {"cloudwatch": _CW(alarms), "dynamodb": _DDB([])}, NOW)
    assert empty[0]["verdict"] == st.DEGRADED and "ZERO rows" in empty[0]["detail"]


def test_census_self_test_degrades_when_invocations_read_nothing():
    class _Blind(_CW):
        def get_metric_data(self, MetricDataQueries, **kw):
            return {"MetricDataResults": [{"Id": q["Id"], "Label": q["Label"], "Timestamps": [], "Values": []} for q in MetricDataQueries]}

    spec = {"kind": st.KIND_CENSUS, "alarms": (), "covers": []}
    ok = st.run({st.CENSUS_SENSOR: spec}, {"cloudwatch": _CW({})}, NOW)
    assert ok[0]["verdict"] == st.OK, ok
    blind = st.run({st.CENSUS_SENSOR: spec}, {"cloudwatch": _Blind({})}, NOW)
    assert blind[0]["verdict"] == st.DEGRADED and "silent" in blind[0]["detail"]


def test_self_test_cli_exits_nonzero_on_any_degraded(monkeypatch, capsys):
    monkeypatch.setattr(st, "_clients", lambda: {"cloudwatch": _CW({}), "dynamodb": _DDB([])})
    assert st.main(["--self-test", "--sensor", "qa-smoke-heartbeat"]) == 1
    assert "[DEGRADED]" in capsys.readouterr().out
    monkeypatch.setattr(st, "_clients", lambda: {"cloudwatch": _CW({"qa-smoke-heartbeat": _metric_alarm("qa-smoke-heartbeat")})})
    assert st.main(["--self-test", "--sensor", "qa-smoke-heartbeat"]) == 0


def test_list_mode_touches_no_aws(monkeypatch):
    monkeypatch.setattr(st, "_clients", lambda: pytest.fail("--list must not build AWS clients"))
    assert st.main(["--list"]) == 0


def test_post_cdk_smoke_runs_the_self_tests_and_fails_on_degraded():
    with open(os.path.join(_ROOT, "deploy", "post_cdk_smoke.sh"), encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r'if SELF_TEST_OUT=\$\(python3 "\$SCRIPT_DIR/sensor_self_test\.py" --self-test 2>&1\); then(.*?)\nfi', src, re.S)
    assert m, "post_cdk_smoke.sh no longer runs `sensor_self_test.py --self-test` (#4034)"
    assert 'check "Liveness sensors" "fail:' in m.group(1), "a degraded self-test must FAIL the smoke, not warn"
    assert "--sensor" not in m.group(0), "the smoke must run the WHOLE derived set, never a hand-picked subset"
