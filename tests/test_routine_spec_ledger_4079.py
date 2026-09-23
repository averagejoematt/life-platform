"""tests/test_routine_spec_ledger_4079.py — mcp/routine_spec_ledger.py (#4079).

The commit path (mcp/tools_hevy_routine.py::_action_commit) writes the committed
routine's spec to its own durable, non-git home so a chat coaching session never
again has to be told "save this to docs/coaching/routines/ and remind Matthew to
git commit" for the routine to survive. These tests exercise the ledger module
directly, offline (no real S3 call): fixture shape (routine_id, content hash,
date, session role), key derivation, fail-soft behaviour, and hash stability
across a Decimal round-trip.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import routine_spec_ledger as ledger  # noqa: E402


def _ir(**overrides):
    kw = dict(
        routine_id="r-4079",
        target_date="2026-09-23",
        archetype="push",
        variant="ideal",
        title="Foundation - Push - 1 - 1",
        version=2,
        status="active",
        hevy_routine_id="hevy-abc123",
        created_by="chat",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10, weight_kg=40.0)])],
    )
    kw.update(overrides)
    return RoutineSpec(**kw)


def test_spec_key_is_type_scoped_and_stable():
    assert ledger.spec_key("push", "r-4079") == "config/coaching/routine_specs/push/r-4079.json"
    # same routine, same key on a second call — overwritten in place, never a new file per commit.
    assert ledger.spec_key("push", "r-4079") == ledger.spec_key("push", "r-4079")


def test_spec_key_falls_back_when_archetype_is_missing():
    assert ledger.spec_key(None, "r-4079") == "config/coaching/routine_specs/unclassified/r-4079.json"
    assert ledger.spec_key("", "r-4079") == "config/coaching/routine_specs/unclassified/r-4079.json"


def test_build_spec_carries_the_4079_fixture():
    """routine_id, content hash, date, session role — the fixture named in the issue."""
    spec = ledger.build_spec(_ir())
    assert spec["routine_id"] == "r-4079"
    assert spec["target_date"] == "2026-09-23"  # "date"
    assert spec["session_role"] == "chat"  # RoutineSpec.created_by, reused as-is
    assert isinstance(spec["content_hash"], str) and len(spec["content_hash"]) == 64  # sha256 hex
    assert "committed_at" in spec and spec["committed_at"]
    # identity, so a reader never needs a second lookup
    assert spec["hevy_routine_id"] == "hevy-abc123"
    assert spec["archetype"] == "push"
    assert spec["version"] == 2
    assert spec["status"] == "active"


def test_content_hash_is_stable_across_a_decimal_round_trip():
    """DDB round-trips float -> Decimal -> float (routine_ir.serialize/deserialize).
    The hash must not move just because a weight passed through that trip."""
    from decimal import Decimal

    ir = _ir()
    direct = ledger.content_hash(ir)

    from training.routine_ir import deserialize, serialize

    roundtripped = deserialize(serialize(ir))
    assert isinstance(serialize(ir)["exercises"][0]["sets"][0]["weight_kg"], Decimal)
    assert ledger.content_hash(roundtripped) == direct


def test_content_hash_changes_when_the_routine_changes():
    a = ledger.content_hash(_ir())
    b = ledger.content_hash(_ir(title="A different title"))
    assert a != b


def test_save_routine_spec_writes_to_the_expected_key_with_the_stubbed_client():
    put = MagicMock()
    fake_client = MagicMock(put_object=put)
    with patch.object(ledger, "_spec_s3", return_value=fake_client):
        out = ledger.save_routine_spec(_ir())

    assert out["saved"] is True
    assert out["key"] == "config/coaching/routine_specs/push/r-4079.json"
    put.assert_called_once()
    _, kwargs = put.call_args
    # The CONFIGURED bucket, read at call time — `mcp.config` may have been imported by an
    # earlier test under a different S3_BUCKET env, so a literal here is order-dependent.
    from mcp.config import S3_BUCKET

    assert kwargs["Bucket"] == S3_BUCKET
    assert kwargs["Key"] == "config/coaching/routine_specs/push/r-4079.json"
    assert kwargs["ContentType"] == "application/json"
    body = json.loads(kwargs["Body"])
    assert body["routine_id"] == "r-4079"
    assert body["session_role"] == "chat"
    assert body["content_hash"] == out["content_hash"]


def test_save_routine_spec_is_fail_soft_and_never_raises():
    """A ledger-write failure must never break an already-successful Hevy commit."""
    fake_client = MagicMock()
    fake_client.put_object.side_effect = RuntimeError("S3 is down")
    with patch.object(ledger, "_spec_s3", return_value=fake_client):
        out = ledger.save_routine_spec(_ir())  # must not raise
    assert out["saved"] is False
    assert "error" in out
    assert out["key"] == "config/coaching/routine_specs/push/r-4079.json"


def test_save_routine_spec_uses_created_by_cron_for_generator_authored_routines():
    """draft/cron-authored routines carry created_by="cron" — the same field, no
    second provenance concept invented for "session role"."""
    put = MagicMock()
    fake_client = MagicMock(put_object=put)
    with patch.object(ledger, "_spec_s3", return_value=fake_client):
        out = ledger.save_routine_spec(_ir(created_by="cron"))
    body = json.loads(put.call_args.kwargs["Body"])
    assert body["session_role"] == "cron"
    assert out["saved"] is True


@pytest.mark.parametrize("archetype", ["push", "legs", None])
def test_the_written_key_is_spec_key_and_the_registry_classifies_it(archetype):
    """The put_object key is spelled as a literal f-string so deploy/config_twin_registry.py can
    resolve it to a runtime-written family; it must stay byte-equal to `spec_key` and SPEC_PREFIX."""
    ir = _ir()
    ir.archetype = archetype
    put = MagicMock()
    with patch.object(ledger, "_spec_s3", return_value=MagicMock(put_object=put)):
        ledger.save_routine_spec(ir)
    assert put.call_args.kwargs["Key"] == ledger.spec_key(archetype, ir.routine_id)
    assert put.call_args.kwargs["Key"].startswith(ledger.SPEC_PREFIX + "/")
