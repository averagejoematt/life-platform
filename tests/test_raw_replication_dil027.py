"""DIL-027 (#3042) — the raw/ zone's cross-region backup, guarded in both directions.

Two jobs:

  A. PARITY — `cdk/stacks/constants.py` is the single source of truth for the four
     identifiers (destination bucket, destination region, replication role, replicated
     prefix). Three consumers restate them in their own vocabulary: the CDK stack, the
     source-side `deploy/s3_replication.json`, and `cdk/app.py`'s region literal. A
     rename that lands in one and not the others produces a replication configuration
     that points at nothing — and S3 reports that as `InvalidRequest` at apply time, or
     worse, as a silently un-replicated zone. These tests are the lockstep.

  B. CAN-IT-FAIL (#2578) — every failure mode of `check_raw_replication` is driven on
     fakes shaped like the real boto3 call sites, and each one is asserted to produce
     drift/degraded rather than a silent clean. The check exists to be red on a real
     day; a check nobody has ever seen fail is a check nobody knows works.

The fakes answer the actual method names and response shapes the module calls
(`get_bucket_replication` → `{"ReplicationConfiguration": …}`, `head_object` →
`{"ReplicationStatus": …}`, `list_objects_v2` → `{"Contents": [{"Key", "LastModified"}]}`)
— fixture-must-be-the-wire, not a convenience stand-in.
"""

import ast
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONSTANTS_PY = os.path.join(_ROOT, "cdk", "stacks", "constants.py")
_BACKUP_STACK_PY = os.path.join(_ROOT, "cdk", "stacks", "backup_stack.py")
_APP_PY = os.path.join(_ROOT, "cdk", "app.py")
_REPLICATION_JSON = os.path.join(_ROOT, "deploy", "s3_replication.json")

for _p in (os.path.join(_ROOT, "deploy"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sentinel_replication as sr  # noqa: E402

# ── Offline readers (no aws_cdk import — the unit lane does not have it) ─────


def _constant_defaults(path):
    """`NAME = os.environ.get("NAME", "value")` / `NAME = "value"` → {NAME: value}."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[target.id] = value.value
        elif isinstance(value, ast.Call) and len(value.args) == 2 and isinstance(value.args[1], ast.Constant):
            out[target.id] = value.args[1].value
    return out


@pytest.fixture(scope="module")
def consts():
    c = _constant_defaults(_CONSTANTS_PY)
    for name in ("RAW_BACKUP_BUCKET", "RAW_BACKUP_REGION", "RAW_REPLICATION_ROLE_NAME", "RAW_REPLICATION_PREFIX", "S3_BUCKET", "ACCT"):
        assert name in c, f"cdk/stacks/constants.py no longer defines {name} — the parity tests below would pass vacuously"
    return c


@pytest.fixture(scope="module")
def replication_cfg():
    with open(_REPLICATION_JSON, encoding="utf-8") as f:
        return json.load(f)


# ── A. Parity ────────────────────────────────────────────────────────────────


def test_replication_json_destination_matches_constants(consts, replication_cfg):
    rule = replication_cfg["Rules"][0]
    assert rule["Destination"]["Bucket"] == f"arn:aws:s3:::{consts['RAW_BACKUP_BUCKET']}"


def test_replication_json_role_matches_constants(consts, replication_cfg):
    assert replication_cfg["Role"] == f"arn:aws:iam::{consts['ACCT']}:role/{consts['RAW_REPLICATION_ROLE_NAME']}"


def test_replication_json_prefix_matches_constants(consts, replication_cfg):
    assert replication_cfg["Rules"][0]["Filter"]["Prefix"] == consts["RAW_REPLICATION_PREFIX"]


def test_replication_rule_is_enabled(replication_cfg):
    assert replication_cfg["Rules"][0]["Status"] == "Enabled"


def test_delete_markers_are_not_replicated(replication_cfg):
    """The load-bearing half of "this is a backup, not a mirror". If a future edit
    flips this to Enabled, a delete on the source starts propagating and the backup
    stops protecting against the exact scenario DIL-027 names (bucket destruction)."""
    assert replication_cfg["Rules"][0]["DeleteMarkerReplication"]["Status"] == "Disabled"


def _granted_actions(path):
    """Every string inside an `actions=[...]` keyword in the stack. AST, not text —
    the module's own prose explains why `s3:ReplicateDelete` is absent, and a grep
    would happily match the explanation and call it a grant."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "actions" or not isinstance(kw.value, ast.List):
                continue
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.add(elt.value)
    return out


def test_replication_role_has_no_replicate_delete_grant():
    """The IAM half of the same guarantee, so neither can be loosened alone."""
    actions = _granted_actions(_BACKUP_STACK_PY)
    assert actions, "AST parse found no actions= grants in backup_stack.py — this assertion would pass vacuously"
    assert "s3:ReplicateObject" in actions, "the replication role cannot write the replica"
    assert (
        "s3:ReplicateDelete" not in actions
    ), "backup_stack.py grants s3:ReplicateDelete — that plus DeleteMarkerReplication would turn the backup into a mirror"


def test_replication_role_read_grant_is_scoped_to_the_raw_prefix(consts):
    """The object-read grant must be raw/*, never the whole bucket: the replication
    role is assumable by the S3 service and its blast radius is whatever it can read."""
    with open(_BACKUP_STACK_PY, encoding="utf-8") as f:
        src = f.read()
    assert "_SOURCE_PREFIX_ARN" in src and 'RAW_REPLICATION_PREFIX}*"' in src
    bucket_wide = f'"arn:aws:s3:::{consts["S3_BUCKET"]}/*"'
    assert bucket_wide not in src, "backup_stack.py grants object reads bucket-wide instead of raw/*"


def test_backup_bucket_retains_and_blocks_public_access():
    with open(_BACKUP_STACK_PY, encoding="utf-8") as f:
        src = f.read()
    assert "RemovalPolicy.RETAIN" in src, "a cdk destroy must never be able to take the backup with it"
    assert "BlockPublicAccess.BLOCK_ALL" in src
    assert "versioned=True" in src, "S3 refuses to replicate to an unversioned destination"


def test_backup_bucket_has_delete_protection_for_the_admin_principal():
    with open(_BACKUP_STACK_PY, encoding="utf-8") as f:
        src = f.read()
    assert "ProtectRawBackupFromDeployScripts" in src
    assert "iam.Effect.DENY" in src
    for action in ("s3:DeleteObject", "s3:DeleteObjectVersion", "s3:DeleteBucket"):
        assert action in src, f"the backup's Deny statement does not cover {action}"


def test_app_py_backup_region_literal_matches_constants(consts):
    """cdk/app.py must carry the region as a STRING LITERAL (the offline AST parser in
    tests/test_drift_checker_stack_regions.py resolves a Name to the DEFAULT region,
    which would silently point the deploy guard at us-west-2 — the #1816 class). This
    pins that literal to constants.RAW_BACKUP_REGION so the duplication cannot drift."""
    with open(_APP_PY, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "BackupStack":
            continue
        for kw in node.keywords:
            if kw.arg == "env" and isinstance(kw.value, ast.Call):
                for env_kw in kw.value.keywords:
                    if env_kw.arg == "region" and isinstance(env_kw.value, ast.Constant):
                        found = env_kw.value.value
    assert found is not None, "cdk/app.py no longer builds BackupStack with a literal region= — the region maps go silently wrong"
    assert found == consts["RAW_BACKUP_REGION"]


def test_backup_region_is_not_the_sites_control_plane_region(consts):
    """us-east-1 already carries LifePlatformWeb (ACM + CloudFront config). A backup
    there would share a region with a thing it is meant to survive."""
    assert consts["RAW_BACKUP_REGION"] not in ("us-west-2", "us-east-1")


def test_sentinel_is_registered_in_the_drift_sweep():
    """The check has to actually run. A module nobody calls is a comment."""
    with open(os.path.join(_ROOT, "deploy", "drift_sentinel.py"), encoding="utf-8") as f:
        src = f.read()
    assert "from sentinel_replication import check_raw_replication" in src
    assert '"raw_replication": check_raw_replication()' in src


# ── B. Can-it-fail ───────────────────────────────────────────────────────────

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
_DEST = "matthew-life-platform-raw-backup"
_LIVE_CFG = {
    "Role": "arn:aws:iam::205930651321:role/life-platform-raw-replication",
    "Rules": [
        {
            "ID": "raw-zone-crr-us-east-2",
            "Priority": 0,
            "Status": "Enabled",
            "Filter": {"Prefix": "raw/"},
            "DeleteMarkerReplication": {"Status": "Disabled"},
            "Destination": {"Bucket": f"arn:aws:s3:::{_DEST}", "StorageClass": "STANDARD"},
        }
    ],
}


class _NotFound(Exception):
    response = {"Error": {"Code": "ReplicationConfigurationNotFoundError"}}


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "404"}}


class _FakeSource:
    def __init__(self, cfg=_LIVE_CFG, replication_status="COMPLETED", newest_age_min=5.0):
        self.cfg = cfg
        self.replication_status = replication_status
        self.newest_age_min = newest_age_min

    def get_bucket_replication(self, Bucket):  # noqa: N803 — boto3's kwarg name
        if self.cfg is None:
            raise _NotFound("An error occurred (ReplicationConfigurationNotFoundError)")
        return {"ReplicationConfiguration": self.cfg}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=None):  # noqa: N803
        if MaxKeys == 1:
            return {"Contents": [{"Key": f"{Prefix}2026/01/01.json", "LastModified": _NOW - timedelta(days=200)}]}
        if "2026/08/" not in Prefix:
            return {}
        return {"Contents": [{"Key": f"{Prefix}24.json", "LastModified": _NOW - timedelta(minutes=self.newest_age_min)}]}

    def head_object(self, Bucket, Key):  # noqa: N803
        if self.replication_status is None:
            return {}
        return {"ReplicationStatus": self.replication_status}


class _FakeDest:
    def __init__(self, versioning="Enabled", present=("new", "old")):
        self.versioning = versioning
        self.present = present

    def get_bucket_versioning(self, Bucket):  # noqa: N803
        return {"Status": self.versioning} if self.versioning else {}

    def head_object(self, Bucket, Key):  # noqa: N803
        is_old = "/2026/01/01.json" in Key
        want = "old" if is_old else "new"
        if want not in self.present:
            raise _NoSuchKey("An error occurred (404) when calling the HeadObject operation: Not Found")
        return {}


def _run(source=None, dest=None, monkeypatch=None, samples=(("whoop", "raw/matthew/whoop"),)):
    source = source or _FakeSource()
    dest = dest or _FakeDest()
    monkeypatch.setattr(sr, "_sample_prefixes", lambda: list(samples))
    return sr.check_raw_replication(
        client_factory=lambda service, region: dest if region == "us-east-2" else source,
        source_bucket="matthew-life-platform",
        now=_NOW,
    )


def test_happy_path_is_clean(monkeypatch):
    out = _run(monkeypatch=monkeypatch)
    assert out["status"] == "clean", out
    assert out["objects_confirmed"] >= 2


def test_no_replication_configuration_is_loud_drift(monkeypatch):
    out = _run(source=_FakeSource(cfg=None), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert "NO cross-region backup" in out["detail"]


def test_disabled_rule_is_drift(monkeypatch):
    cfg = json.loads(json.dumps(_LIVE_CFG))
    cfg["Rules"][0]["Status"] = "Disabled"
    out = _run(source=_FakeSource(cfg=cfg), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert any("status" in m for m in out["mismatches"])


def test_delete_marker_replication_turned_on_live_is_drift(monkeypatch):
    """The single most dangerous silent loosening: the backup becomes a mirror."""
    cfg = json.loads(json.dumps(_LIVE_CFG))
    cfg["Rules"][0]["DeleteMarkerReplication"]["Status"] = "Enabled"
    out = _run(source=_FakeSource(cfg=cfg), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert any("delete_marker" in m for m in out["mismatches"])


def test_redirected_destination_is_drift(monkeypatch):
    cfg = json.loads(json.dumps(_LIVE_CFG))
    cfg["Rules"][0]["Destination"]["Bucket"] = "arn:aws:s3:::somebody-elses-bucket"
    out = _run(source=_FakeSource(cfg=cfg), monkeypatch=monkeypatch)
    assert out["status"] == "drift"


def test_widened_prefix_is_drift(monkeypatch):
    cfg = json.loads(json.dumps(_LIVE_CFG))
    cfg["Rules"][0]["Filter"]["Prefix"] = ""
    out = _run(source=_FakeSource(cfg=cfg), monkeypatch=monkeypatch)
    assert out["status"] == "drift"


def test_unversioned_destination_is_drift(monkeypatch):
    out = _run(dest=_FakeDest(versioning="Suspended"), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert "will not replicate" in out["detail"]


def test_completed_but_replica_absent_is_drift(monkeypatch):
    """The check that a status field alone cannot make: S3 says COMPLETED, the object
    is not there."""
    out = _run(dest=_FakeDest(present=("old",)), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert "does not exist" in out["detail"]


def test_failed_replication_is_drift(monkeypatch):
    out = _run(source=_FakeSource(replication_status="FAILED"), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert "FAILED" in out["detail"]


def test_pending_inside_the_grace_window_is_not_drift(monkeypatch):
    out = _run(source=_FakeSource(replication_status="PENDING", newest_age_min=5.0), monkeypatch=monkeypatch)
    assert out["status"] == "clean", out


def test_pending_past_the_grace_window_is_drift(monkeypatch):
    out = _run(
        source=_FakeSource(replication_status="PENDING", newest_age_min=sr.PENDING_GRACE_MINUTES + 30),
        monkeypatch=monkeypatch,
    )
    assert out["status"] == "drift"
    assert "PENDING" in out["detail"]


def test_missing_historical_backfill_is_drift(monkeypatch):
    """Replication is not retroactive. Until the S3 Batch Replication job runs, the
    pre-existing raw/ history has no replica — and that must be RED, not assumed."""
    out = _run(dest=_FakeDest(present=("new",)), monkeypatch=monkeypatch)
    assert out["status"] == "drift"
    assert "not retroactive" in out["detail"]


def test_nothing_observable_is_degraded_not_clean(monkeypatch):
    """The vacuous-pass guard: configuration correct, destination correct, but every
    sampled object predates the configuration and none has a replica to confirm."""
    out = _run(
        source=_FakeSource(replication_status=None),
        dest=_FakeDest(present=()),
        monkeypatch=monkeypatch,
    )
    assert out["status"] in ("drift", "degraded")
    assert out["status"] != "clean"


def test_registry_import_failure_is_degraded_not_clean(monkeypatch):
    def _boom():
        raise ImportError("source_registry unavailable")

    monkeypatch.setattr(sr, "_sample_prefixes", _boom)
    out = sr.check_raw_replication(
        client_factory=lambda service, region: _FakeDest() if region == "us-east-2" else _FakeSource(),
        source_bucket="matthew-life-platform",
        now=_NOW,
    )
    assert out["status"] == "degraded"
    assert "NOT verified end to end" in out["detail"]


def test_sample_prefixes_are_registry_driven_and_under_raw():
    """No hand-typed key list: the probe's prefixes come from source_registry's
    raw_layout facets (the #1256 class — a plausible key that resolves to nothing)."""
    samples = sr._sample_prefixes()
    assert samples, "no date-tree raw/ sources resolved from the registry — the probe would be vacuous"
    assert len(samples) <= sr.SAMPLE_SOURCES
    for _source, prefix in samples:
        assert prefix.startswith("raw/")
