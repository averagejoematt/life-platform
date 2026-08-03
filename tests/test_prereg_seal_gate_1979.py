"""tests/test_prereg_seal_gate_1979.py — regression guard for the pre-registration
completion gate (#1979).

Three of the last six closed cycles (07-13, 07-18, 07-22) had no published,
hash-stamped pre-registration artifact and nothing ever failed — "pre-registered"
was usually true, not structurally true. These tests pin the gate that closes it
(`deploy/prereg_seal_gate.py`, wired into `deploy/restart_verify.py` check 15):

  - a cycle with a live, hash-matching S3 seal passes;
  - a cycle with NO published artifact fails (prove-red);
  - a cycle with a published artifact whose bytes no longer match its stamp's
    sha256 fails (prove-red — the tamper/drift case, not just "missing");
  - a cycle grandfathered by BOTH cycle number and genesis date passes without
    ever calling sealed_check for real (S3-free — the whole point of the
    exemption);
  - a grandfather entry does NOT transfer to a different genesis reusing the
    same cycle number (keyed to both, not just the cycle number);
  - a cycle whose genesis predates the hash-stamp tooling's own ship date is
    out of scope entirely — sealing was not literally possible yet;
  - a FRESH cycle (today's genesis, not grandfathered, not sealed) fails —
    exactly the credibility gap #1979 exists to close, and exactly what a
    freshly re-anchored reset looks like before the attended
    seed -> publish -> stamp sequence runs.

All offline: sealed_check is a plain dict-backed stub, never real S3/boto3.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import prereg_seal_gate as gate  # noqa: E402

TOOLING_INTRODUCED = gate.PREREG_SEAL_TOOLING_INTRODUCED  # "2026-07-19"


def _stub_check(sealed_geneses):
    """A sealed_check callable backed by a plain set — no I/O, no boto3."""

    def _check(genesis: str) -> bool:
        return genesis in sealed_geneses

    return _check


# ── audit_seal_coverage: pure logic ──────────────────────────────────────────


def test_all_sealed_passes():
    cycles = {8: "2026-07-19", 9: "2026-07-20", 11: "2026-07-27"}
    assert gate.audit_seal_coverage(cycles, _stub_check({"2026-07-19", "2026-07-20", "2026-07-27"})) == []


def test_unsealed_uncovered_cycle_fails():
    # The #1979 shape, minus a grandfather record: a post-tooling genesis with no
    # seal and no exemption must fail. (Uses a synthetic cycle number, since the
    # real cycle 10/2026-07-22 IS grandfathered — see the next test.)
    cycles = {97: "2026-07-22"}
    problems = gate.audit_seal_coverage(cycles, _stub_check(set()))
    assert len(problems) == 1
    assert "cycle 97" in problems[0] and "2026-07-22" in problems[0]


def test_grandfathered_cycle_passes_without_a_real_seal():
    # cycle 10 IS grandfathered in the shipped registry; sealed_check returning
    # False for everything proves the pass comes from the grandfather record,
    # not from a lucky True.
    assert gate.is_grandfathered(10, "2026-07-22")
    assert gate.audit_seal_coverage({10: "2026-07-22"}, lambda g: False) == []


def test_grandfather_keyed_to_genesis_not_just_cycle_number():
    # A hypothetical future reuse of cycle 10 with a DIFFERENT genesis must NOT
    # inherit the old exemption.
    assert gate.is_grandfathered(10, "2026-07-22") is True
    assert gate.is_grandfathered(10, "2099-01-01") is False
    problems = gate.audit_seal_coverage({10: "2099-01-01"}, lambda g: False)
    assert len(problems) == 1 and "cycle 10" in problems[0]


def test_pre_tooling_genesis_is_out_of_scope():
    # Cycles 6/7 (07-13, 07-18) predate genesis_prereg_stamp.py's own ship date —
    # sealing them was not literally possible. Neither is in the grandfather list,
    # and both must still pass (out of scope, not "covered by exemption").
    assert not gate.is_grandfathered(6, "2026-07-13")
    assert not gate.is_grandfathered(7, "2026-07-18")
    cycles = {6: "2026-07-13", 7: "2026-07-18"}
    assert gate.audit_seal_coverage(cycles, lambda g: False) == []


def test_genesis_exactly_at_tooling_introduction_is_in_scope():
    # Boundary case: the tooling's own ship date IS in scope (cycle 8, 07-19, was
    # in fact sealed the same day) — the cutoff is exclusive of "before", not "on".
    assert TOOLING_INTRODUCED == "2026-07-19"
    problems = gate.audit_seal_coverage({8: TOOLING_INTRODUCED}, lambda g: False)
    assert len(problems) == 1


def test_fresh_unsealed_cycle_fails_like_any_other():
    # The exact state right after restart_pipeline.py re-anchors, before the
    # attended seed -> publish -> stamp sequence runs: not grandfathered (dated
    # entries never cover a cycle that doesn't exist yet), not sealed.
    cycles = {12: "2026-08-03"}
    problems = gate.audit_seal_coverage(cycles, lambda g: False)
    assert len(problems) == 1 and "cycle 12" in problems[0] and "2026-08-03" in problems[0]


def test_fresh_cycle_passes_once_sealed():
    cycles = {12: "2026-08-03"}
    assert gate.audit_seal_coverage(cycles, _stub_check({"2026-08-03"})) == []


def test_mixed_cycles_report_only_the_real_gap():
    cycles = {
        6: "2026-07-13",  # pre-tooling, out of scope
        8: "2026-07-19",  # sealed
        10: "2026-07-22",  # grandfathered
        12: "2026-08-03",  # fresh, unsealed — THE gap
    }
    problems = gate.audit_seal_coverage(cycles, _stub_check({"2026-07-19"}))
    assert len(problems) == 1 and "cycle 12" in problems[0]


# ── s3_seal_check: I/O boundary, exercised with a fake S3 client ────────────


class _FakeBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    """Minimal boto3 S3 client stand-in: a dict of key -> bytes, raising the same
    ClientError shape boto3 raises for a missing key."""

    def __init__(self, objects: dict[str, bytes]):
        self._objects = objects

    def get_object(self, Bucket, Key):  # noqa: N803 — mirrors boto3's own signature
        if Key not in self._objects:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        return {"Body": _FakeBody(self._objects[Key])}


def _sealed_fixture(genesis: str):
    import hashlib
    import json

    artifact = json.dumps({"genesis": genesis, "hello": "world"}).encode()
    sha = hashlib.sha256(artifact).hexdigest()
    stamp = json.dumps({"genesis": genesis, "sha256": sha}).encode()
    return artifact, stamp, sha


def test_s3_seal_check_passes_when_hash_matches():
    genesis = "2026-07-27"
    artifact, stamp, sha = _sealed_fixture(genesis)
    import genesis_prereg_stamp as gps

    s3 = _FakeS3({gps.artifact_key(genesis): artifact, gps.stamp_key(genesis): stamp})
    ok, detail = gate.s3_seal_check(genesis, s3)
    assert ok is True and sha in detail


def test_s3_seal_check_fails_missing_artifact():
    ok, detail = gate.s3_seal_check("2026-07-22", _FakeS3({}))
    assert ok is False and "no published artifact" in detail


def test_s3_seal_check_fails_missing_stamp():
    import genesis_prereg_stamp as gps

    genesis = "2026-07-22"
    artifact, _stamp, _sha = _sealed_fixture(genesis)
    s3 = _FakeS3({gps.artifact_key(genesis): artifact})
    ok, detail = gate.s3_seal_check(genesis, s3)
    assert ok is False and "no stamp" in detail


def test_s3_seal_check_fails_on_sha_mismatch():
    # The tamper/drift case: the published artifact's live bytes no longer match
    # what its own published stamp claims — must fail, never trust the stamp blindly.
    import genesis_prereg_stamp as gps

    genesis = "2026-07-22"
    artifact, stamp, _sha = _sealed_fixture(genesis)
    tampered = artifact.replace(b"world", b"WORLD!!")
    s3 = _FakeS3({gps.artifact_key(genesis): tampered, gps.stamp_key(genesis): stamp})
    ok, detail = gate.s3_seal_check(genesis, s3)
    assert ok is False and "SHA mismatch" in detail


def test_s3_seal_check_fails_on_genesis_mismatch():
    import genesis_prereg_stamp as gps

    genesis = "2026-07-22"
    artifact, _stamp, sha = _sealed_fixture(genesis)
    import json

    wrong_genesis_stamp = json.dumps({"genesis": "2026-07-20", "sha256": sha}).encode()
    s3 = _FakeS3({gps.artifact_key(genesis): artifact, gps.stamp_key(genesis): wrong_genesis_stamp})
    ok, detail = gate.s3_seal_check(genesis, s3)
    assert ok is False and "genesis" in detail


def test_make_s3_sealed_check_adapts_and_caches():
    genesis = "2026-07-27"
    artifact, stamp, _sha = _sealed_fixture(genesis)
    import genesis_prereg_stamp as gps

    calls = {"n": 0}
    real_get_object = _FakeS3.get_object

    class _CountingFakeS3(_FakeS3):
        def get_object(self, Bucket, Key):  # noqa: N803
            calls["n"] += 1
            return real_get_object(self, Bucket=Bucket, Key=Key)

    s3 = _CountingFakeS3({gps.artifact_key(genesis): artifact, gps.stamp_key(genesis): stamp})
    check = gate.make_s3_sealed_check(s3)
    assert check(genesis) is True
    first_call_count = calls["n"]
    assert check(genesis) is True  # cached — no new S3 round-trips
    assert calls["n"] == first_call_count


def test_end_to_end_audit_with_fake_s3():
    """The realistic shape: audit_seal_coverage driven by make_s3_sealed_check
    against a fake S3 holding exactly the live bucket's current state (per the
    #1979 verifier's own S3 listing) — reproduces the reported gap directly."""
    import genesis_prereg_stamp as gps

    live_cycle_geneses = {
        6: "2026-07-13",
        7: "2026-07-18",
        8: "2026-07-19",
        9: "2026-07-20",
        10: "2026-07-22",
        11: "2026-07-27",
    }
    objects = {}
    for genesis in ("2026-07-19", "2026-07-20", "2026-07-27"):
        artifact, stamp, _sha = _sealed_fixture(genesis)
        objects[gps.artifact_key(genesis)] = artifact
        objects[gps.stamp_key(genesis)] = stamp
    s3 = _FakeS3(objects)
    problems = gate.audit_seal_coverage(live_cycle_geneses, gate.make_s3_sealed_check(s3))
    # 6/7 out of scope (pre-tooling), 8/9/11 sealed, 10 grandfathered — clean.
    assert problems == []
