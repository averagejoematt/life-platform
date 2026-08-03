"""prereg_seal_gate.py — the #1979 pre-registration completion gate.

Pre-registration is the platform's central credibility claim ("predictions were
made before the data existed, and you can verify it"), but nothing ever asserted
that a cycle's seal was actually PUBLISHED. The #1979 verifier found S3
`generated/experiments/prereg/` held genesis artifacts for only 3 of the last 6
closed cycles (07-19, 07-20, 07-27) while `CYCLE_GENESES`
(`lambdas/web/site_api_data.py`) lists 6 (07-13, 07-18, 07-19, 07-20, 07-22,
07-27) — three cycles (07-13, 07-18, 07-22) were silently unsealed, and nothing
would have failed if a 7th, 8th, ... joined that list forever.

This module is the single shared core for two surfaces (the #1947
countdown_gap_sweep.py pattern):
  - deploy/restart_verify.py — the POST-genesis Monday health check: fails
    unless EVERY cycle in CYCLE_GENESES is either sealed (live S3 artifact whose
    SHA-256 matches its published stamp) or explicitly, dated-ly grandfathered
    below. A fresh cycle's genesis is NOT grandfathered — the gate stays red
    until the attended `seed_genesis_preregistration.py` -> the operator's own
    review of `publish_genesis_preregistration.py`'s dry-run -> `--apply` ->
    `genesis_prereg_stamp.py --apply` sequence actually runs and lands a real
    artifact (#1092 posture: those steps are NEVER auto-folded into the
    pipeline — see restart_pipeline.py's "DELIBERATELY NOT FOLDED" block).
  - tests/test_prereg_seal_gate_1979.py — the regression guard (prove-red): a
    missing or SHA-mismatched seal fails audit_seal_coverage(); a sealed or
    grandfathered cycle passes.

TWO-TIER EXEMPTION (never a silent pass):
  1. Cycles whose genesis predates PREREG_SEAL_TOOLING_INTRODUCED (the date
     genesis_prereg_stamp.py, #1378, first shipped) are excluded from the audit
     entirely — sealing was not literally possible yet, so an absent seal there
     is a tooling gap, not a credibility miss. This is DERIVED from the actual
     ship date (git-blameable), not a hand-picked per-cycle list.
  2. GRANDFATHERED_UNSEALED_CYCLES below is the explicit, dated exception list
     for cycles that COULD have been sealed (tooling existed) but weren't, and
     can never be sealed honestly now — `genesis_prereg_stamp.py`'s stamped_at
     is never backdated, so there is no honest way to retroactively produce a
     seal for a cycle that has already closed. Every entry names the cycle, its
     genesis, when it was recorded, and why — reviewed once via #1979's PR,
     never silently. A NEW unsealed cycle is NOT in this list by default.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "deploy") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "deploy"))

import genesis_prereg_stamp as gps  # noqa: E402

# The date deploy/genesis_prereg_stamp.py (#1378) first shipped — see
# `git log --follow --diff-filter=A -- deploy/genesis_prereg_stamp.py`. Any
# genesis strictly before this date could not have been sealed by construction.
PREREG_SEAL_TOOLING_INTRODUCED = "2026-07-19"

# ── explicit, dated grandfather record (tier 2 — see module docstring) ──────
GRANDFATHERED_UNSEALED_CYCLES: dict[int, dict[str, str]] = {
    10: {
        "genesis": "2026-07-22",
        "recorded_at": "2026-08-03",
        "reason": (
            "Post-dates the hash-stamp tooling (shipped 2026-07-19, #1378) but no artifact "
            "was ever published before the cycle closed; there is no honest way to seal it "
            "retroactively now (stamped_at is never backdated). Recorded by #1979 rather than "
            "silently passing forever."
        ),
    },
}


def is_grandfathered(cycle: int, genesis: str) -> bool:
    """A grandfather entry is keyed to BOTH cycle number and genesis date — a future
    cycle that happens to reuse a low cycle number (should never happen, but the
    check is cheap) cannot silently inherit an old exemption."""
    entry = GRANDFATHERED_UNSEALED_CYCLES.get(cycle)
    return bool(entry) and entry.get("genesis") == genesis


def audit_seal_coverage(
    cycle_geneses: dict[int, str],
    sealed_check: Callable[[str], bool],
    tooling_introduced: str = PREREG_SEAL_TOOLING_INTRODUCED,
) -> list[str]:
    """Pure audit — no I/O. For every cycle in `cycle_geneses` whose genesis is on
    or after `tooling_introduced`, call `sealed_check(genesis)`. A cycle is a
    PROBLEM iff it is unsealed AND not grandfathered. Returns [] when every
    in-scope cycle is covered (sealed or grandfathered) — the "prove-red" tests
    exercise both a missing seal (non-empty) and a covered one (empty)."""
    problems = []
    for cycle in sorted(cycle_geneses):
        genesis = cycle_geneses[cycle]
        if genesis < tooling_introduced:
            continue
        if sealed_check(genesis):
            continue
        if is_grandfathered(cycle, genesis):
            continue
        problems.append(
            f"cycle {cycle} (genesis {genesis}) has no published, hash-verified pre-registration "
            "seal and no grandfather record in deploy/prereg_seal_gate.py::GRANDFATHERED_UNSEALED_CYCLES "
            f"— run: python3 deploy/seed_genesis_preregistration.py --apply && "
            f"python3 deploy/publish_genesis_preregistration.py [--apply, after reviewing the dry-run] "
            f"&& python3 deploy/genesis_prereg_stamp.py --apply"
        )
    return problems


def s3_seal_check(genesis: str, s3_client, bucket: str = gps.S3_BUCKET) -> tuple[bool, str]:
    """I/O check: does S3 hold a published artifact for `genesis` whose live bytes
    hash to exactly the sha256 its published stamp records? Returns (ok, detail).
    Never trusts the stamp's own sha256 field for the artifact bytes — recomputes
    from what is actually live, the same honesty rule genesis_prereg_stamp.py
    itself applies at publish time."""
    from botocore.exceptions import ClientError

    artifact_key = gps.artifact_key(genesis)
    stamp_key = gps.stamp_key(genesis)
    try:
        artifact = s3_client.get_object(Bucket=bucket, Key=artifact_key)["Body"].read()
    except ClientError:
        return False, f"no published artifact at s3://{bucket}/{artifact_key}"
    try:
        stamp_body = s3_client.get_object(Bucket=bucket, Key=stamp_key)["Body"].read()
    except ClientError:
        return False, f"artifact published but no stamp at s3://{bucket}/{stamp_key}"
    try:
        stamp = json.loads(stamp_body)
    except ValueError:
        return False, f"stamp at s3://{bucket}/{stamp_key} is not valid JSON"
    actual_sha = hashlib.sha256(artifact).hexdigest()
    stamped_sha = stamp.get("sha256")
    if stamped_sha != actual_sha:
        return False, f"SHA mismatch: live artifact hashes to {actual_sha}, published stamp says {stamped_sha}"
    if stamp.get("genesis") != genesis:
        return False, f"published stamp genesis {stamp.get('genesis')!r} != {genesis!r}"
    return True, f"sealed: sha256 {actual_sha}"


def make_s3_sealed_check(s3_client, bucket: str = gps.S3_BUCKET) -> Callable[[str], bool]:
    """Adapts s3_seal_check to the bool-returning callable audit_seal_coverage
    wants, caching each genesis's result for the life of the callable (CYCLE_GENESES
    has a handful of distinct entries — one S3 round-trip pair per genesis, not
    per cycle number, even though several cycles could in principle share one)."""
    cache: dict[str, bool] = {}

    def _check(genesis: str) -> bool:
        if genesis not in cache:
            ok, _detail = s3_seal_check(genesis, s3_client, bucket)
            cache[genesis] = ok
        return cache[genesis]

    return _check
