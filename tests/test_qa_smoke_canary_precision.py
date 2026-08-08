"""tests/test_qa_smoke_canary_precision.py — #1956: the nightly canary
false-positive-rate line (the sensor that watches sensors).

The AI quality canary's grounded-digits check fired ALARMs on provably TRUE
numbers for a month (its fact universe was narrower than the ask pipeline's
serving context) and NOTHING measured that precision decay — the alarm just
became the boy who cried wolf. check_canary_precision() makes the grounded
ALARM rate a nightly, queryable qa-smoke line:

  - reports the trailing-window grounded-ALARM rate on every run (OK line),
  - WARNs on chronic firing (> 20% across >= 5 sighted runs — the cried-wolf
    signature), never FAILs (single-firing ground truth is not
    deterministically knowable here, and a content-truth WARN must never feed
    a rollback),
  - excludes budget-paused / transport-BLIND runs from the denominator (they
    carry no grounded verdict),
  - fails soft when the log prefix is unreadable (the IAM grant rides the same
    stranded CDK deploy).

All offline — fake S3, no AWS.
"""

import io
import json
import os
import sys
import types
from datetime import timedelta

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from operational import qa_smoke_lambda as qa  # noqa: E402

ROLE_POLICIES = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "role_policies.py")


class _NoSuchKey(Exception):
    pass


class _FakeS3:
    """get_object over an in-memory {key: record} map; missing key raises the
    same exceptions.NoSuchKey shape botocore exposes."""

    def __init__(self, records):
        self.records = records
        self.exceptions = types.SimpleNamespace(NoSuchKey=_NoSuchKey)

    def get_object(self, Bucket, Key):
        if Key not in self.records:
            raise _NoSuchKey(Key)
        return {"Body": io.BytesIO(json.dumps(self.records[Key]).encode())}


class _DeniedS3:
    exceptions = types.SimpleNamespace(NoSuchKey=_NoSuchKey)

    def get_object(self, Bucket, Key):
        raise PermissionError("AccessDenied on " + Key)


def _dates_back(n):
    today = qa.pt_now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, n + 1)]


def _records(dates, alarmed=(), skipped=(), blind=()):
    out = {}
    for d in dates:
        rec = {"date": d, "status": "OK", "alarms": []}
        if d in alarmed:
            rec["status"] = "ALARM"
            rec["alarms"] = ["ask_factual:grounded"]
        if d in skipped:
            rec["skipped"] = "budget-paused"
        if d in blind:
            rec["blind"] = True
        out[f"{qa.CANARY_LOG_PREFIX}/{d}.json"] = rec
    return out


def _run(monkeypatch, records):
    monkeypatch.setattr(qa, "s3", _FakeS3(records))
    checks = qa.check_canary_precision()
    assert len(checks) == 1
    return checks[0]


# ── the line itself ───────────────────────────────────────────────────────────


def test_quiet_canary_reports_zero_rate_ok(monkeypatch):
    dates = _dates_back(qa.CANARY_PRECISION_WINDOW_DAYS)
    c = _run(monkeypatch, _records(dates))
    assert c.passed is True and not c.paused
    assert "0/14" in c.message and "0%" in c.message


def test_rare_true_alarm_stays_ok_but_is_counted(monkeypatch):
    dates = _dates_back(qa.CANARY_PRECISION_WINDOW_DAYS)
    c = _run(monkeypatch, _records(dates, alarmed={dates[0]}))
    assert c.passed is True  # one real fabrication catch is the canary WORKING
    assert "1/14" in c.message


def test_chronic_grounded_alarms_warn_with_cried_wolf_signature(monkeypatch):
    # The pre-#1956 live pattern: grounded ALARMs on 07-03/06/22/24/27/31 —
    # chronically red, which is precisely the precision defect this line watches.
    dates = _dates_back(qa.CANARY_PRECISION_WINDOW_DAYS)
    c = _run(monkeypatch, _records(dates, alarmed=set(dates[:6])))
    assert c.passed is None  # WARN, never FAIL
    assert "#1956" in c.message and "precision suspect" in c.message


def test_paused_and_blind_runs_leave_the_denominator(monkeypatch):
    # 14 dated records: 6 budget-paused, 4 blind, 4 sighted (1 alarmed).
    dates = _dates_back(qa.CANARY_PRECISION_WINDOW_DAYS)
    recs = _records(dates, alarmed={dates[0]}, skipped=set(dates[1:7]), blind=set(dates[7:11]))
    c = _run(monkeypatch, recs)
    assert "1/4" in c.message  # 4 sighted runs, not 14


def test_below_min_runs_never_judges(monkeypatch):
    # 3 sighted runs, all alarmed = 100% — but n < CANARY_PRECISION_MIN_RUNS,
    # so the line reports without judging (a 3-run rate is noise).
    dates = _dates_back(3)
    c = _run(monkeypatch, _records(dates, alarmed=set(dates)))
    assert c.passed is True
    assert "3/3" in c.message


def test_no_records_warns_unmeasurable(monkeypatch):
    c = _run(monkeypatch, {})
    assert c.passed is None
    assert "unmeasurable" in c.message


def test_unreadable_log_prefix_fails_soft_naming_the_grant(monkeypatch):
    # Pre-CDK-deploy reality: qa-smoke's role lacks s3:GetObject on
    # ai-canary-log/* until the owner's deploy lands — the check must degrade
    # to a WARN that names the grant, never crash the nightly.
    monkeypatch.setattr(qa, "s3", _DeniedS3())
    checks = qa.check_canary_precision()
    assert len(checks) == 1 and checks[0].passed is None
    assert "s3:GetObject" in checks[0].message and qa.CANARY_LOG_PREFIX in checks[0].message


def test_check_is_content_truth_partitioned(monkeypatch):
    # A canary-precision finding is about the state of the world, not the
    # deploy in flight — it must never be able to gate ci-cd's rollback.
    c = _run(monkeypatch, {})
    assert c.partition == qa.CONTENT_TRUTH


# ── wiring + IAM lockstep ─────────────────────────────────────────────────────


def test_lambda_handler_runs_the_precision_check():
    # #2307: the nightly run list is qa.check_steps() — the one wiring point.
    assert ("canary_precision", qa.check_canary_precision) in qa.check_steps()


def test_qa_smoke_role_grants_the_canary_log_read():
    # The code path is fail-soft without it, but the LINE only exists once this
    # grant deploys — keep repo IAM and the reader in lockstep.
    with open(ROLE_POLICIES) as f:
        src = f.read()
    qa_policy = src.split("def operational_qa_smoke", 1)[1].split("\ndef ", 1)[0]
    assert '"ai-canary-log/*"' in qa_policy
