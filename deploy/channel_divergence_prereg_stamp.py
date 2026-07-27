#!/usr/bin/env python3
"""channel_divergence_prereg_stamp.py — content-hash seal on the frozen spoken-vs-typed
channel-divergence pre-registration (#1844).

Same pattern as deploy/genesis_prereg_stamp.py (#1378), applied to a second frozen
artifact rather than generalizing the module — this codebase's convention is one small,
purpose-built script per frozen artifact (mirrors restart_leadin_pages.py,
restart_ledger_reset.py, etc.), not a shared generic engine. Reuses the SAME public
route #728 established (generated/experiments/prereg/{id}.json) and the SAME seal idea:

  1. STAMP: SHA-256 over the EXACT BYTES of the frozen file
     (deploy/generated/channel_divergence_prereg.json), recorded in a sidecar
     (deploy/generated/channel_divergence_prereg.sha256.json). The frozen file is
     never touched after stamping — that's the freeze itself.
  2. PUBLISH (--apply): upload the frozen file VERBATIM + the stamp to
       generated/experiments/prereg/spoken-vs-typed-divergence_2026-07-27.json
       generated/experiments/prereg/spoken-vs-typed-divergence_2026-07-27.sha256.json
     → https://averagejoematt.com/experiments/prereg/spoken-vs-typed-divergence_2026-07-27.json
     Verify from any terminal: curl -s <url> | shasum -a 256
  3. GUARD: verify_stamp() is a hard stop on any post-stamp edit to the frozen file —
     tests/test_channel_divergence_prereg_1844.py reds CI on the same mismatch.

This is a REGISTRATION tool, not an analysis tool — it writes nothing about the
comparison result (there isn't one yet). --apply performs the ONLY AWS write this
module makes (an S3 put); it is deliberately never invoked from a worktree branch —
sealing/publishing is a post-merge, from-main ops step (see the PR body).

Usage:
    python3 deploy/channel_divergence_prereg_stamp.py            # stamp (idempotent) + verify, local only
    python3 deploy/channel_divergence_prereg_stamp.py --apply    # + publish artifact + stamp to S3
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "channel_divergence_prereg.json"
STAMP_PATH = REPO_ROOT / "deploy" / "generated" / "channel_divergence_prereg.sha256.json"

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
SITE_URL = "https://averagejoematt.com"


def artifact_key(experiment_id: str) -> str:
    return f"generated/experiments/prereg/{experiment_id}.json"


def stamp_key(experiment_id: str) -> str:
    return f"generated/experiments/prereg/{experiment_id}.sha256.json"


def artifact_url(experiment_id: str) -> str:
    # The #728 CloudFront behavior serves generated/experiments/prereg/* at /experiments/prereg/*.
    return f"{SITE_URL}/experiments/prereg/{experiment_id}.json"


def stamp_url(experiment_id: str) -> str:
    return f"{SITE_URL}/experiments/prereg/{experiment_id}.sha256.json"


def compute_sha256(path: Path = None) -> str:
    """SHA-256 over the EXACT file bytes — what `shasum -a 256` reports."""
    return hashlib.sha256((path or FROZEN_PATH).read_bytes()).hexdigest()


def load_stamp() -> dict | None:
    if not STAMP_PATH.exists():
        return None
    return json.loads(STAMP_PATH.read_text())


def write_stamp(now: datetime = None) -> dict:
    """Stamp the current frozen file. Idempotent over an unchanged file (keeps the
    original stamped_at). Refuses a same-artifact re-stamp with a different hash —
    that is an edit being laundered, not a stamp."""
    if not FROZEN_PATH.exists():
        raise SystemExit(f"No frozen pre-registration at {FROZEN_PATH}.")
    frozen = json.loads(FROZEN_PATH.read_text())
    experiment_id = frozen["experiment_id"]
    frozen_registered_at = frozen["registered_at"]
    sha = compute_sha256()

    existing = load_stamp()
    if existing is not None and existing.get("experiment_id") == experiment_id:
        if existing.get("sha256") == sha:
            print(f"Already stamped (unchanged): sha256 {sha} · stamped_at {existing['stamped_at']} kept.")
            return existing
        raise SystemExit(
            f"REFUSED: {FROZEN_PATH.name} for {experiment_id} no longer matches its stamp "
            f"({existing.get('sha256')} → {sha}). The frozen pre-registration was EDITED after "
            "stamping — that edit cannot be laundered into a fresh stamp. Restore the frozen "
            "file (git checkout), or register a NEW experiment deliberately for a real design "
            "change (delete BOTH the frozen file and this stamp, pick a new experiment_id)."
        )

    stamped_at = (now or datetime.now(timezone.utc)).isoformat()
    if stamped_at < frozen_registered_at:
        raise SystemExit(f"REFUSED: stamped_at {stamped_at} predates registration {frozen_registered_at} — a stamp is never backdated.")
    same_day = stamped_at[:10] == frozen_registered_at[:10]
    stamp = {
        "artifact": FROZEN_PATH.name,
        "experiment_id": experiment_id,
        "algorithm": "sha256",
        "sha256": sha,
        "frozen_registered_at": frozen_registered_at,
        "stamped_at": stamped_at,
        "stamp_note": (
            "Hash stamped at registration time."
            if same_day
            else (
                f"Registered {frozen_registered_at}; hash stamped later, {stamped_at}. Both moments are "
                "recorded — a stamp is never backdated. The hash covers the frozen file exactly as it "
                "stood when stamped."
            )
        ),
        "public_artifact_url": artifact_url(experiment_id),
        "public_stamp_url": stamp_url(experiment_id),
        "verify": f"curl -s {artifact_url(experiment_id)} | shasum -a 256",
    }
    STAMP_PATH.write_text(json.dumps(stamp, indent=2) + "\n")
    print(f"STAMPED {FROZEN_PATH.name} → {STAMP_PATH.name}\n  sha256 {sha}\n  stamped_at {stamped_at}")
    return stamp


def verify_stamp(frozen: dict = None) -> list:
    """Deterministic integrity check — returns a list of issues ([] = clean).
    Callers (tests, the publisher) treat ANY issue as a hard stop."""
    issues = []
    if not FROZEN_PATH.exists():
        return [f"frozen pre-registration missing: {FROZEN_PATH}"]
    if frozen is None:
        frozen = json.loads(FROZEN_PATH.read_text())
    stamp = load_stamp()
    if stamp is None:
        return [f"no hash stamp at {STAMP_PATH} — run: python3 deploy/channel_divergence_prereg_stamp.py"]
    sha = compute_sha256()
    if stamp.get("sha256") != sha:
        issues.append(
            f"HASH MISMATCH: frozen file is {sha} but the stamp says {stamp.get('sha256')} — "
            "the pre-registration was edited after stamping (pre-registration never silently changes)"
        )
    if stamp.get("experiment_id") != frozen.get("experiment_id"):
        issues.append(f"stamp is for {stamp.get('experiment_id')} but the frozen file says {frozen.get('experiment_id')}")
    if stamp.get("frozen_registered_at") != frozen.get("registered_at"):
        issues.append(
            f"stamp records registration time {stamp.get('frozen_registered_at')} but the frozen file says {frozen.get('registered_at')}"
        )
    if stamp.get("stamped_at", "") < stamp.get("frozen_registered_at", ""):
        issues.append("stamp is BACKDATED (stamped_at predates registration) — stamps state their real moment")
    return issues


def require_valid_stamp(frozen: dict = None) -> dict:
    """verify_stamp or die — the shared write-path guard (the publisher)."""
    issues = verify_stamp(frozen)
    if issues:
        raise SystemExit("Pre-registration hash-stamp check FAILED:\n  - " + "\n  - ".join(issues))
    return load_stamp()


def publish_to_s3(stamp: dict) -> None:
    """Upload the frozen file VERBATIM + the stamp to the public prereg route.
    Immutable post-publish: refuses to overwrite a published artifact whose bytes
    differ from the local (stamped) frozen file. NEVER call this from a worktree
    branch — it is a live AWS write, an ops step run from main after merge."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=REGION)
    experiment_id = stamp["experiment_id"]
    body = FROZEN_PATH.read_bytes()
    local_sha = hashlib.sha256(body).hexdigest()
    assert local_sha == stamp["sha256"], "stamp/file drift caught at publish time"

    for key, payload in ((artifact_key(experiment_id), body), (stamp_key(experiment_id), (json.dumps(stamp, indent=2) + "\n").encode())):
        try:
            existing = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            if existing == payload:
                print(f"  s3://{S3_BUCKET}/{key} — already published, byte-identical, left untouched.")
                continue
            if key == artifact_key(experiment_id):
                raise SystemExit(
                    f"REFUSED: s3://{S3_BUCKET}/{key} already exists with DIFFERENT bytes "
                    f"(published sha256 {hashlib.sha256(existing).hexdigest()}, local {local_sha}). "
                    "A published pre-registration is immutable — it is never overwritten."
                )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
                raise
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=payload, ContentType="application/json", CacheControl="public, max-age=300")
        print(f"  WROTE s3://{S3_BUCKET}/{key} ({len(payload)} bytes)")
    print(
        f"\nPublic artifact: {artifact_url(experiment_id)}\nPublic stamp:    {stamp_url(experiment_id)}\nVerify:          {stamp['verify']}"
    )
    print("(New objects on /experiments/prereg/* can be 404-cached by CloudFront for ~300s — re-curl after 5 min before alarming.)")


def main():
    ap = argparse.ArgumentParser(description="Hash-stamp + publish the frozen channel-divergence pre-registration (#1844)")
    ap.add_argument("--apply", action="store_true", help="also upload the artifact + stamp to S3 (default: local stamp + verify only)")
    args = ap.parse_args()

    stamp = write_stamp()
    issues = verify_stamp()
    if issues:
        raise SystemExit("Post-stamp verification FAILED (should be impossible):\n  - " + "\n  - ".join(issues))
    print(f"VERIFIED: {FROZEN_PATH.name} matches its stamp ({stamp['sha256']}).")
    print(f"Note: {stamp['stamp_note']}")

    if not args.apply:
        print("\nDRY RUN for the publish step — re-run with --apply to upload the artifact + stamp to S3.")
        return 0
    publish_to_s3(stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
