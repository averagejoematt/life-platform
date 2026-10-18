"""#4626 — the HAE webhook role can READ the four day files it merges.

Found 2026-10-17 by the #4628 lane: `/aws/lambda/health-auto-export-webhook` logs
`s3_read_workouts raw/matthew/workouts/2026/10/11.json: An error occurred (AccessDenied)
when calling the GetObject operation: ... is not authorized to perform: s3:GetObject`
(2026-10-11T21:57Z, the exists case) and seven more over the week naming `s3:ListBucket`
(S3's 403-for-a-missing-key shape, the first delivery of a day). The role's only S3
statement was `S3Write` (PutObject). `health_auto_export_archive.py` merges each CGM /
blood-pressure / state-of-mind / workout day file read-dedup-put, and on a read error
other than NoSuchKey it logs at WARNING and continues with `existing=[]` — so the put
OVERWRITES the day file with only the latest delivery. A silent loss on every
multi-delivery day. Fix: one `s3:GetObject` grant on exactly the four `sub_layouts`
prefixes the registry names (never a hand-built key).

Mutation control (run 2026-10-18 against the pre-grant policy): the first test fails with
four `("GetObject", …/raw/matthew/<sub>/*)` entries; the rest pass unchanged.
"""

from __future__ import annotations

import json
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cdk"))
sys.path.insert(0, str(ROOT / "lambdas"))

import pytest  # noqa: E402
from ingestion import (
    health_auto_export_archive as archive,  # noqa: E402
    source_registry as sr,  # noqa: E402
)

# Every HAE fan-out stream the registry names — the SET the grant must cover (the four
# day-file merges below plus #4962's additive_readings/* trees, which the webhook also
# reads back before it writes). Guard the set, not the instance.
HAE_SUBS = tuple(sr.raw_layout_for("apple_health")["sub_layouts"])
MERGED_SUBS = ("cgm_readings", "blood_pressure", "state_of_mind", "workouts")
assert set(MERGED_SUBS) <= set(HAE_SUBS)


def _policy():
    """The HAE statements + the bucket ARN. Imported HERE, not at module scope: `stacks.*` reaches
    `aws_cdk`, which the minimal deploy-critical lane does not install (#2758/#3784) — the two
    policy tests skip there, the three archive-merge tests below still run."""
    pytest.importorskip("aws_cdk")
    from stacks import role_policies_ingestion as rpi
    from stacks.role_policies_base import BUCKET_ARN

    return rpi.ingestion_hae(), BUCKET_ARN


def _sub_arn(bucket_arn: str, sub: str) -> str:
    return f"{bucket_arn}/{sr.raw_layout_for('apple_health', sub)['prefix']}/*"


def _covered(arn: str, stmts) -> bool:
    # A statement resource is an ARN glob: `.../additive_readings/*` covers `.../additive_readings/steps/*`.
    return any(fnmatchcase(arn, r) for s in stmts for r in s.resources)


def test_every_merged_day_file_prefix_is_readable_and_writable_by_the_hae_role():
    stmts, bucket_arn = _policy()
    reads = [s for s in stmts if "s3:GetObject" in s.actions]
    writes = [s for s in stmts if "s3:PutObject" in s.actions]
    missing = []
    for sub in HAE_SUBS:
        arn = _sub_arn(bucket_arn, sub)
        if not _covered(arn, reads):
            missing.append(("GetObject", arn))
        if not _covered(arn, writes):
            missing.append(("PutObject", arn))
    assert not missing, f"the HAE role cannot read-merge-put every day file it writes: {missing}"


def test_the_read_grant_stays_inside_the_hae_raw_trees_and_adds_no_delete_or_wildcard():
    stmts, bucket_arn = _policy()
    for s in stmts:
        assert "s3:*" not in s.actions and not any(a.startswith("s3:Delete") for a in s.actions), s.sid
    for s in (s for s in stmts if "s3:GetObject" in s.actions):
        for r in s.resources:
            assert r.startswith(f"{bucket_arn}/raw/matthew/") and r.endswith("/*"), (s.sid, r)
            assert r != f"{bucket_arn}/raw/matthew/*", (s.sid, r)


class _NoSuchKey(Exception):
    pass


class _FakeS3:
    """Records the call order; `existing` is what a GetObject returns, or an exception to raise."""

    exceptions = SimpleNamespace(NoSuchKey=_NoSuchKey)

    def __init__(self, existing):
        self._existing = existing
        self.calls: list[tuple[str, str]] = []
        self.put_body = None

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Key))
        if isinstance(self._existing, Exception):
            raise self._existing
        return {"Body": SimpleNamespace(read=lambda: json.dumps(self._existing))}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Key))
        self.put_body = json.loads(Body)


# (saver, sub, the day file already in S3, the second delivery of the same day)
_SAVERS = [
    (archive.save_cgm_readings_to_s3, "cgm_readings", [{"time": "T1", "v": 1}], [{"time": "T1", "v": 1}, {"time": "T2", "v": 2}]),
    (archive.save_bp_readings_to_s3, "blood_pressure", [{"time": "T1"}], [{"time": "T1"}, {"time": "T2"}]),
    (archive.save_state_of_mind_to_s3, "state_of_mind", [{"time": "T1"}], [{"time": "T1"}, {"time": "T2"}]),
    (archive.save_workouts_to_s3, "workouts", [{"id": "a", "start": "1"}], [{"id": "a", "start": "1"}, {"id": "b", "start": "2"}]),
]
DAY = "2026-10-11"


def test_each_merge_reads_the_registry_key_before_it_writes_and_keeps_the_earlier_delivery():
    offenders = []
    for saver, sub, existing, delivery in _SAVERS:
        s3 = _FakeS3(existing)
        n = saver(s3, "bucket", "matthew", DAY, delivery)
        key = sr.raw_date_key("apple_health", DAY, sub=sub)
        if s3.calls != [("get", key), ("put", key)] or n != 1 or len(s3.put_body) != 2:
            offenders.append((sub, s3.calls, n, s3.put_body))
    assert not offenders, offenders


def test_a_missing_day_file_is_the_empty_case_and_the_first_delivery_is_written_whole():
    for saver, sub, _existing, delivery in _SAVERS:
        s3 = _FakeS3(_NoSuchKey())
        assert saver(s3, "bucket", "matthew", DAY, delivery) == 2, sub
        assert len(s3.put_body) == 2, sub


def test_an_unreadable_day_file_is_overwritten_with_only_the_delivery_which_is_why_the_grant_exists(monkeypatch):
    """The live defect's shape: AccessDenied is not NoSuchKey, so the merge logs `s3_read_<sub> <key>: …`
    at WARNING and the put carries the delivery alone — the earlier delivery of the day is gone.
    Pinned so the log line stays greppable as the live evidence (the module's logger is swapped for a
    recorder: its structured handler is bound to a stream neither capsys nor capfd sees)."""
    warnings: list[str] = []
    monkeypatch.setattr(archive, "logger", SimpleNamespace(warning=lambda fmt, *a: warnings.append(fmt % a)))
    for saver, sub, _existing, delivery in _SAVERS:
        s3 = _FakeS3(Exception("An error occurred (AccessDenied) when calling the GetObject operation"))
        saver(s3, "bucket", "matthew", DAY, delivery)
        assert len(s3.put_body) == 2 and s3.calls[0][0] == "get", sub
        key = sr.raw_date_key("apple_health", DAY, sub=sub)
        # The tag is the module's own (`s3_read_bp_readings`, not the registry sub name) — pin the shape, not the spelling.
        assert warnings and warnings[-1].startswith("s3_read_") and f" {key}: " in warnings[-1], (sub, warnings)
        assert "AccessDenied" in warnings[-1], (sub, warnings)
