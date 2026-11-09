"""tests/test_sensor_self_test_caller_5522.py — the #4034 post-deploy sensor self-test has a caller,
and its silence is alarmed (#5522).

Defect class: an instrument the ledgers call armed with no automatic caller. `deploy/sensor_self_test.py`
was invoked only by `deploy/post_cdk_smoke.sh`, which nothing calls, and LifePlatform/SelfTest held no
metric at all on 2026-10-31 while three stacks had deployed that day.

What this proves:
  1. `deploy/cdk_deploy.sh` runs `sensor_self_test.py --self-test` AFTER `npx cdk deploy`, as its last
     command, and its exit code is the script's: the REAL tail block is executed against a stub
     self-test that passes, degrades, or is skipped;
  2. every scratch write also feeds the dimensionless run-level SelfTestWrite stream;
  3. the daily pipeline-health-check reads that stream over 35 days and emits SensorSelfTestStale,
     fail-loud, beside its other gauges — and the alarm watches exactly that gauge;
  4. the reader's namespace/metric are the writer's (the two halves of one wire).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
for sub in ("deploy", "lambdas"):
    if str(_ROOT / sub) not in sys.path:
        sys.path.insert(0, str(_ROOT / sub))

import sensor_self_test as st  # noqa: E402
from operational import pipeline_health_check_lambda as phc  # noqa: E402

_CDK_DEPLOY = _ROOT / "deploy" / "cdk_deploy.sh"
_MONITORING = _ROOT / "cdk" / "stacks" / "monitoring_stack.py"
_ROLE_POLICIES = _ROOT / "cdk" / "stacks" / "role_policies_serve.py"
NOW = datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)


# ── 1. cdk_deploy.sh: the caller, its position, and its exit code ─────────────────────────────────
def _commands(src: str) -> list[str]:
    return [ln.strip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_cdk_deploy_runs_the_self_test_after_the_deploy_as_its_last_command():
    src = _CDK_DEPLOY.read_text(encoding="utf-8")
    cmds = _commands(src)
    deploy_at = next(i for i, c in enumerate(cmds) if "npx cdk deploy" in c)
    self_test_at = [i for i, c in enumerate(cmds) if "sensor_self_test.py" in c and "--self-test" in c]
    assert len(self_test_at) == 1, "exactly one sensor self-test call in cdk_deploy.sh"
    assert self_test_at[0] > deploy_at, "the self-test must run AFTER the stacks deploy"
    tail = cmds[self_test_at[0] :]
    assert all(c in ("fi", "exit 1") or c.startswith("echo ") for c in tail[1:]), f"nothing may run after the self-test: {tail}"


def _run_tail(tmp_path: Path, stub_exit: int, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Execute the REAL #5522 block of cdk_deploy.sh (from its marker to EOF) with ROOT pointing at a
    tmp tree whose deploy/sensor_self_test.py is a stub exiting `stub_exit` and recording its argv."""
    src = _CDK_DEPLOY.read_text(encoding="utf-8")
    block = src[src.index("# ── #5522") :]
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "sensor_self_test.py").write_text(
        f"import sys, pathlib\npathlib.Path({str(tmp_path / 'argv')!r}).write_text(' '.join(sys.argv[1:]))\nsys.exit({stub_exit})\n"
    )
    script = tmp_path / "tail.sh"
    script.write_text(f'set -euo pipefail\nROOT="{tmp_path}"\n{block}')
    env = {k: v for k, v in os.environ.items() if k != "SKIP_SENSOR_SELF_TEST"}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=60)


def test_a_degraded_self_test_fails_the_deploy_script(tmp_path):
    r = _run_tail(tmp_path, stub_exit=1)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DEGRADED" in r.stderr
    assert (tmp_path / "argv").read_text() == "--self-test"


def test_an_ok_self_test_passes(tmp_path):
    ok = _run_tail(tmp_path, stub_exit=0)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert (tmp_path / "argv").read_text() == "--self-test"


def test_a_skip_is_loud_and_runs_nothing(tmp_path):
    skipped = _run_tail(tmp_path, stub_exit=1, env_extra={"SKIP_SENSOR_SELF_TEST": "1"})
    assert skipped.returncode == 0 and "did NOT run" in skipped.stderr
    assert not (tmp_path / "argv").exists(), "a skipped self-test must not run"


# ── 2. the writer: every scratch write also feeds the run-level stream ───────────────────────────
def test_scratch_write_feeds_the_dimensionless_run_level_stream():
    class _CW:
        def __init__(self):
            self.calls = []

        def put_metric_data(self, **kw):
            self.calls.append(kw)

    cw = _CW()
    st.write_scratch(cw, "qa-smoke-heartbeat")
    (call,) = cw.calls
    assert call["Namespace"] == st.SCRATCH_NAMESPACE
    data = call["MetricData"]
    assert {d["MetricName"] for d in data} == {st.SCRATCH_METRIC}
    assert any(not d.get("Dimensions") for d in data), "the run-level stream (no dimension) is what the dead-man reads"
    assert any(d.get("Dimensions") == [{"Name": "Sensor", "Value": "qa-smoke-heartbeat"}] for d in data)


def test_reader_and_writer_name_the_same_series():
    assert phc.SELF_TEST_NAMESPACE == st.SCRATCH_NAMESPACE
    assert phc.SELF_TEST_METRIC == st.SCRATCH_METRIC


# ── 3. the reader: 35 days, fail-loud ─────────────────────────────────────────────────────────────
class _FakeCW:
    def __init__(self, datapoints=None, boom=None):
        self.datapoints = datapoints or []
        self.boom = boom
        self.asked: list[dict] = []

    def get_metric_statistics(self, **kw):
        self.asked.append(kw)
        if self.boom:
            raise self.boom
        return {"Datapoints": list(self.datapoints)}


@pytest.fixture()
def cw(monkeypatch):
    def _install(**kw):
        fake = _FakeCW(**kw)
        monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: fake)
        return fake

    return _install


def test_the_probe_reads_35_days_of_the_dimensionless_stream(cw):
    fake = cw(datapoints=[{"Timestamp": NOW - timedelta(days=3), "Sum": 12.0}])
    v = phc._check_sensor_self_test(NOW)
    (q,) = fake.asked
    assert q["Namespace"] == st.SCRATCH_NAMESPACE and q["MetricName"] == st.SCRATCH_METRIC
    assert "Dimensions" not in q or not q["Dimensions"], "the run-level stream has no dimension"
    assert q["EndTime"] - q["StartTime"] == timedelta(days=35)
    assert v["stale"] is False and v["last_write_day"] == (NOW - timedelta(days=3)).date().isoformat()


def test_the_probe_is_stale_on_silence_on_zeros_and_on_a_failed_read(cw):
    cases = {
        "no datapoints": dict(datapoints=[]),
        "only zero buckets": dict(datapoints=[{"Timestamp": NOW - timedelta(days=1), "Sum": 0.0}]),
        "read failed": dict(boom=RuntimeError("AccessDenied: cloudwatch:GetMetricStatistics")),
    }
    wrong = []
    for name, kw in cases.items():
        cw(**kw)
        v = phc._check_sensor_self_test(NOW)
        if v["stale"] is not True or not v["reason"]:
            wrong.append(f"{name}: {v}")
    assert not wrong, "the dead-man must be loud on every blind shape:\n  " + "\n  ".join(wrong)


def test_the_daily_run_emits_the_gauge_beside_its_other_gauges(monkeypatch):
    class _Rec:
        def __init__(self):
            self.metrics = []

        def put_metric_data(self, **kw):
            self.metrics.append(kw)

        def get_metric_statistics(self, **kw):
            return {"Datapoints": []}  # no self-test in 35 days

        def get_trail_status(self, **kw):
            return {"IsLogging": True, "LatestDeliveryTime": NOW - timedelta(hours=1)}

        def publish(self, **kw):
            pass

        def put_item(self, Item):
            pass

        def query(self, **kw):
            return {"Items": []}

    rec = _Rec()

    class _FrozenDatetime(phc.datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(phc, "datetime", _FrozenDatetime)
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: rec)
    monkeypatch.setattr(phc, "table", rec)
    monkeypatch.setattr(phc, "ACTIVE_API_SOURCES", [])
    monkeypatch.setattr(phc, "BEST_EFFORT_SOURCES", [])
    monkeypatch.setattr(phc, "_INGEST_HEALTH_AVAILABLE", True)
    phc._check_ingest_liveness(NOW, day="2026-11-08")
    (emit,) = rec.metrics
    assert emit["Namespace"] == "LifePlatform/IngestLiveness"
    names = {m["MetricName"]: m["Value"] for m in emit["MetricData"]}
    assert names[phc.SELF_TEST_STALE_METRIC] == 1
    assert names[phc.CLOUDTRAIL_STALE_METRIC] == 0


# ── 4. the alarm watches that gauge, and the role may read the stream ─────────────────────────────
def test_alarm_watches_the_gauge_the_lambda_emits():
    m = re.search(
        r'_alarm\(\s*"SensorSelfTestStale",\s*"sensor-self-test-stale",\s*"([^"]+)",\s*"([^"]+)",\s*(\d+),\s*"Maximum",\s*1,\s*GTE,\s*to_digest=True,?\s*\)',
        _MONITORING.read_text(encoding="utf-8"),
    )
    assert m, "sensor-self-test-stale must be declared through _alarm with Maximum/1/GTE on the digest route"
    assert m.group(1) == "LifePlatform/IngestLiveness", "same namespace as the run's other gauges (ingest-liveness-heartbeat covers it)"
    assert m.group(2) == phc.SELF_TEST_STALE_METRIC
    assert int(m.group(3)) == 86400


def test_the_health_check_role_may_read_the_stream():
    src = _ROLE_POLICIES.read_text(encoding="utf-8")
    body = src[src.index("def pipeline_health_check(") :]
    body = body[: body.index("\ndef ", 1)]
    assert '"cloudwatch:GetMetricStatistics"' in body, "the daily probe cannot read SelfTestWrite without the grant"
