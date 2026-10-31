"""tests/test_cloudtrail_delivery_deadman_5512.py — the CloudTrail delivery dead-man (#5512).

Defect class owned (CONVENTIONS §9): the account's audit trail going dark with no
platform signal. Measured 2026-10-31: `life-platform-trail` had delivered nothing since
2026-07-08 — 115 days — because a `put-bucket-policy` from `deploy/bucket_policy.json`
REPLACED the bucket policy and dropped the two `cloudtrail.amazonaws.com` statements that
`setup/setup_cloudtrail.sh` had written from its own inline twin. CloudTrail retried every
few minutes with AccessDenied; the trail lives outside CDK, so no drift check saw it.

Four contracts, one per half of the fix:

  * **One policy document.** `deploy/bucket_policy.json` carries BOTH the public-read /
    delete-protection statements AND the two CloudTrail statements, with the exact
    SourceArn and the exact log prefix — so applying the file from either path
    (the reconcile smoke's "Fix:" line, or the setup script) can never drop a half again.
  * **No twin.** `setup/setup_cloudtrail.sh` applies the repo file and carries no inline
    policy literal (the INCIDENT_LOG 2026-08-30 twin-document class).
  * **The probe is fail-loud.** `_check_cloudtrail_delivery` reports stale on an old
    delivery, a delivery error, logging off, AND on an unreadable status — a dead-man
    whose sensor failure reads as "healthy" is the class this exists to end.
  * **Producer and consumer agree.** The metric the Lambda emits is the metric the
    `cloudtrail-delivery-stale` alarm watches, in the namespace whose heartbeat covers
    the run; and the Lambda's role can actually read the trail it probes.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import pytest
from operational import pipeline_health_check_lambda as phc

_REPO = os.path.join(os.path.dirname(__file__), "..")
_POLICY = os.path.join(_REPO, "deploy", "bucket_policy.json")
_SETUP = os.path.join(_REPO, "setup", "setup_cloudtrail.sh")
_MONITORING = os.path.join(_REPO, "cdk", "stacks", "monitoring_stack.py")
_ROLE_POLICIES = os.path.join(_REPO, "cdk", "stacks", "role_policies_serve.py")

TRAIL_ARN = "arn:aws:cloudtrail:us-west-2:205930651321:trail/life-platform-trail"
NOW = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── 1. one policy document ───────────────────────────────────────────────────


def test_bucket_policy_carries_both_cloudtrail_statements_exactly():
    doc = json.loads(_read(_POLICY))
    by_sid = {s["Sid"]: s for s in doc["Statement"]}

    # The half that was there all along — the fix is additive, never a swap.
    for sid in ("PublicReadSite", "PublicReadBlog", "PublicReadGenerated", "ProtectDataFromDeployScripts"):
        assert sid in by_sid, f"{sid} missing — the CloudTrail fix must not drop the public-read / delete-protection half"

    acl = by_sid.get("AWSCloudTrailAclCheck")
    assert acl, "AWSCloudTrailAclCheck missing — CloudTrail cannot verify the bucket before writing"
    assert acl["Effect"] == "Allow"
    assert acl["Principal"] == {"Service": "cloudtrail.amazonaws.com"}
    assert acl["Action"] == "s3:GetBucketAcl"
    assert acl["Resource"] == "arn:aws:s3:::matthew-life-platform"
    assert acl["Condition"] == {"StringEquals": {"aws:SourceArn": TRAIL_ARN}}

    write = by_sid.get("AWSCloudTrailWrite")
    assert write, "AWSCloudTrailWrite missing — this is the exact statement whose absence kept the trail dark for 115 days"
    assert write["Effect"] == "Allow"
    assert write["Principal"] == {"Service": "cloudtrail.amazonaws.com"}
    assert write["Action"] == "s3:PutObject"
    # The prefix must match the trail's S3KeyPrefix (`cloudtrail`) + CloudTrail's fixed layout.
    assert write["Resource"] == "arn:aws:s3:::matthew-life-platform/cloudtrail/AWSLogs/205930651321/*"
    assert write["Condition"] == {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control", "aws:SourceArn": TRAIL_ARN}}


def test_the_cloudtrail_prefix_is_still_delete_protected():
    """The delete-protection Deny names `cloudtrail/*`; the write grant must land INSIDE it."""
    doc = json.loads(_read(_POLICY))
    deny = next(s for s in doc["Statement"] if s["Sid"] == "ProtectDataFromDeployScripts")
    assert "arn:aws:s3:::matthew-life-platform/cloudtrail/*" in deny["Resource"]


# ── 2. no twin ───────────────────────────────────────────────────────────────


def test_setup_script_applies_the_repo_policy_file_and_carries_no_inline_policy():
    src = _read(_SETUP)
    assert "deploy/bucket_policy.json" in src, "the setup script must apply the repo's one policy document"
    assert re.search(
        r'--policy\s+"file://\$POLICY_FILE"', src
    ), "put-bucket-policy must read the file, not a shell variable holding a literal"
    assert (
        '"Sid"' not in src and '"Statement"' not in src
    ), "an inline policy literal here is the twin that dropped the public-read half once and the CloudTrail half once"
    assert "grep -q '\"AWSCloudTrailWrite\"'" in src, "the script must refuse to apply a document that would keep the trail dark"


def test_setup_script_trail_flags_match_the_live_trail():
    """The live trail is multi-region with global service events; a re-run must not narrow it."""
    src = _read(_SETUP)
    assert "--is-multi-region-trail" in src and "--no-is-multi-region-trail" not in src
    assert "--include-global-service-events" in src and "--no-include-global-service-events" not in src


# ── 3. the probe is fail-loud ────────────────────────────────────────────────


class _FakeCloudTrail:
    def __init__(self, status=None, boom=None):
        self.status = status or {}
        self.boom = boom
        self.asked: list[str] = []

    def get_trail_status(self, Name):
        self.asked.append(Name)
        if self.boom:
            raise self.boom
        return dict(self.status)


@pytest.fixture()
def cloudtrail(monkeypatch):
    holder = {}

    def _install(status=None, boom=None):
        fake = _FakeCloudTrail(status=status, boom=boom)
        holder["fake"] = fake
        monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: fake if name == "cloudtrail" else _Unused(name))
        return fake

    return _install


class _Unused:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, item):
        raise AssertionError(f"the probe must touch only the cloudtrail client, not {self.name}.{item}")


def _status(age_hours=1.0, error="", logging=True, with_time=True):
    s = {"IsLogging": logging, "LatestDeliveryError": error}
    if with_time:
        s["LatestDeliveryTime"] = NOW - timedelta(hours=age_hours)
    return s


def test_probe_reads_exactly_the_one_trail(cloudtrail):
    fake = cloudtrail(_status())
    phc._check_cloudtrail_delivery(NOW)
    assert fake.asked == [phc.CLOUDTRAIL_TRAIL_ARN]
    assert phc.CLOUDTRAIL_TRAIL_ARN == TRAIL_ARN


def test_probe_fresh_delivery_is_not_stale(cloudtrail):
    cloudtrail(_status(age_hours=3.5))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is False
    assert v["age_hours"] == 3.5
    assert v["reason"] == "delivering"


def test_probe_old_delivery_is_stale(cloudtrail):
    cloudtrail(_status(age_hours=30))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True
    assert "> 24h" in v["reason"]


def test_probe_the_measured_incident_shape_is_stale(cloudtrail):
    """2026-10-31: IsLogging true, LatestDeliveryError AccessDenied, LatestDeliveryTime 2026-07-08."""
    cloudtrail(
        {
            "IsLogging": True,
            "LatestDeliveryError": "AccessDenied",
            "LatestDeliveryTime": datetime(2026, 7, 8, 22, 39, 56, tzinfo=timezone.utc),
        }
    )
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True
    assert "LatestDeliveryError=AccessDenied" in v["reason"]
    assert v["age_hours"] > 24 * 100, "115 days dark must read as more than 100 days"


def test_probe_a_delivery_error_on_a_fresh_time_is_still_stale(cloudtrail):
    """CloudTrail reports the error on the latest ATTEMPT while LatestDeliveryTime is the last SUCCESS —
    a fresh success with a current error is a trail that just started failing; say so today, not tomorrow."""
    cloudtrail(_status(age_hours=1, error="AccessDenied"))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True


def test_probe_logging_off_is_stale(cloudtrail):
    cloudtrail(_status(age_hours=1, logging=False))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True
    assert "IsLogging is false" in v["reason"]


def test_probe_no_delivery_time_at_all_is_stale(cloudtrail):
    cloudtrail(_status(with_time=False))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True
    assert v["age_hours"] is None


def test_probe_an_unreadable_status_is_stale_not_skipped(cloudtrail):
    """Fail-loud: AccessDenied on get_trail_status (the IAM grant missing, the trail deleted) must
    light the alarm — a sensor that reads 'healthy' when it cannot see is the 115-day class."""
    cloudtrail(boom=RuntimeError("AccessDeniedException: not authorized"))
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is True
    assert "get_trail_status failed" in v["reason"]


def test_probe_handles_a_naive_delivery_time(cloudtrail):
    cloudtrail({"IsLogging": True, "LatestDeliveryError": "", "LatestDeliveryTime": (NOW - timedelta(hours=2)).replace(tzinfo=None)})
    v = phc._check_cloudtrail_delivery(NOW)
    assert v["stale"] is False and v["age_hours"] == 2.0


# ── 4. producer and consumer agree ───────────────────────────────────────────


def test_liveness_run_emits_the_stale_gauge_beside_the_source_count(monkeypatch):
    """The daily run puts UnhealthySourceCount AND CloudTrailDeliveryStale in ONE emit, same namespace."""

    class _Rec:
        def __init__(self):
            self.metrics = []
            self.puts = []

        def put_metric_data(self, **kw):
            self.metrics.append(kw)

        def publish(self, **kw):
            pass

        def put_item(self, Item):
            self.puts.append(Item)

        def query(self, **kw):
            return {"Items": []}

    rec = _Rec()
    stale_status = {"IsLogging": True, "LatestDeliveryError": "AccessDenied", "LatestDeliveryTime": NOW - timedelta(days=115)}
    fake_ct = _FakeCloudTrail(status=stale_status)
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: fake_ct if name == "cloudtrail" else rec)
    monkeypatch.setattr(phc, "table", rec)
    monkeypatch.setattr(phc, "ACTIVE_API_SOURCES", [])
    monkeypatch.setattr(phc, "BEST_EFFORT_SOURCES", [])
    monkeypatch.setattr(phc, "_INGEST_HEALTH_AVAILABLE", True)

    out = phc._check_ingest_liveness(NOW, day="2026-10-31")

    assert out["cloudtrail"]["stale"] is True
    (emit,) = rec.metrics
    assert emit["Namespace"] == "LifePlatform/IngestLiveness"
    names = {m["MetricName"]: m["Value"] for m in emit["MetricData"]}
    assert names["UnhealthySourceCount"] == 0
    assert names[phc.CLOUDTRAIL_STALE_METRIC] == 1
    assert names[phc.CLOUDTRAIL_AGE_METRIC] > 24 * 100
    (row,) = rec.puts
    assert json.loads(row["cloudtrail"])["stale"] is True, "the status page row must carry the trail verdict"


def test_liveness_run_emits_zero_when_the_trail_is_delivering(monkeypatch):
    class _Rec:
        metrics: list = []

        def put_metric_data(self, **kw):
            _Rec.metrics.append(kw)

        def publish(self, **kw):
            pass

        def put_item(self, Item):
            pass

        def query(self, **kw):
            return {"Items": []}

    _Rec.metrics = []
    rec = _Rec()
    fake_ct = _FakeCloudTrail(status=_status(age_hours=2))
    monkeypatch.setattr(phc.boto3, "client", lambda name, region_name=None: fake_ct if name == "cloudtrail" else rec)
    monkeypatch.setattr(phc, "table", rec)
    monkeypatch.setattr(phc, "ACTIVE_API_SOURCES", [])
    monkeypatch.setattr(phc, "BEST_EFFORT_SOURCES", [])
    monkeypatch.setattr(phc, "_INGEST_HEALTH_AVAILABLE", True)
    out = phc._check_ingest_liveness(NOW, day="2026-10-31")
    assert out["cloudtrail"]["stale"] is False
    names = {m["MetricName"]: m["Value"] for m in _Rec.metrics[0]["MetricData"]}
    assert names[phc.CLOUDTRAIL_STALE_METRIC] == 0


def test_alarm_watches_the_metric_the_lambda_emits():
    src = _read(_MONITORING)
    m = re.search(
        r'_alarm\(\s*"CloudTrailDeliveryStale",\s*"cloudtrail-delivery-stale",\s*"([^"]+)",\s*"([^"]+)",\s*(\d+),\s*"Maximum",\s*1,\s*GTE,\s*to_digest=True,?\s*\)',
        src,
    )
    assert m, "cloudtrail-delivery-stale must be declared through _alarm with Maximum/1/GTE on the digest route"
    namespace, metric, period = m.group(1), m.group(2), int(m.group(3))
    assert (
        namespace == "LifePlatform/IngestLiveness"
    ), "same namespace as the run's other gauge, so ingest-liveness-heartbeat covers this detector's death"
    assert metric == phc.CLOUDTRAIL_STALE_METRIC, "the alarm must watch the exact metric name the Lambda emits"
    assert period == 86400, "one daily emit per period — the ingest-liveness-unhealthy shape"


def test_health_check_role_can_read_the_trail_it_probes():
    src = _read(_ROLE_POLICIES)
    fn = src[src.index("def pipeline_health_check()") : src.index("def subscriber_onboarding()")]
    assert '"cloudtrail:GetTrailStatus"' in fn, "the probe's role must hold cloudtrail:GetTrailStatus, or the dead-man reads stale forever"
    assert "CLOUDTRAIL_TRAIL_ARN" in fn, "the grant must be scoped to the one trail, not cloudtrail:*"
    assert 'CLOUDTRAIL_TRAIL_NAME = "life-platform-trail"' in src
    assert phc.CLOUDTRAIL_TRAIL_ARN.endswith(":trail/life-platform-trail")
