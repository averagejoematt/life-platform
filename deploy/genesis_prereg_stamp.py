#!/usr/bin/env python3
"""genesis_prereg_stamp.py — the content-hash seal on the frozen genesis pre-registration (#1378).

Pre-registration is only checkable if readers can verify the claims were not edited
after Day 1 data started flattering (or embarrassing) them. This module makes the
freeze content-addressed — the receipts pattern (ADR-105):

  1. STAMP: compute SHA-256 over the EXACT BYTES of the frozen file
     (deploy/generated/genesis_preregistration.json) and record it in a sidecar
     (deploy/generated/genesis_preregistration.sha256.json). The frozen file itself
     is never touched — the freeze rule (#976) stays intact.
  2. PUBLISH (--apply): upload the frozen file VERBATIM plus the stamp to the
     existing public pre-registration route (#728):
       generated/experiments/prereg/genesis-{genesis}.json
       generated/experiments/prereg/genesis-{genesis}.sha256.json
     → https://averagejoematt.com/experiments/prereg/genesis-{genesis}.json
     Anyone can then verify:  curl -s <url> | shasum -a 256
  3. GUARD: verify_stamp() is called by the seeder and the publisher before ANY
     write — a hash mismatch (the frozen file edited after stamping) hard-aborts,
     and tests/test_prereg_hash_stamp.py reds CI on the same mismatch. The S3
     upload additionally refuses to overwrite a published artifact with different
     bytes, so the public copy is immutable post-publish.

HONESTY RULES (ADR-104, docs-current-truth-only):
  - stamped_at is ALWAYS the real stamping moment — never backdated to the freeze.
    When the stamp postdates the freeze (the cycle whose prereg shipped before this
    tooling existed), BOTH dates are recorded and the public seal states both.
  - Re-running the stamp over an unchanged file is idempotent and keeps the
    ORIGINAL stamped_at (re-dating a stamp would be a quiet lie).
  - Re-stamping the SAME genesis with a DIFFERENT hash is refused outright — that
    is exactly the edit-laundering this tool exists to prevent. A new genesis
    (deliberate regeneration after a reset) stamps fresh.

Usage:
    python3 deploy/genesis_prereg_stamp.py            # stamp (idempotent) + verify, local only
    python3 deploy/genesis_prereg_stamp.py --apply    # + publish artifact + stamp to S3
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.json"
STAMP_PATH = REPO_ROOT / "deploy" / "generated" / "genesis_preregistration.sha256.json"

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
SITE_URL = "https://averagejoematt.com"


def artifact_key(genesis: str) -> str:
    return f"generated/experiments/prereg/genesis-{genesis}.json"


def stamp_key(genesis: str) -> str:
    return f"generated/experiments/prereg/genesis-{genesis}.sha256.json"


def artifact_url(genesis: str) -> str:
    # The #728 CloudFront behavior serves generated/experiments/prereg/* at /experiments/prereg/*.
    return f"{SITE_URL}/experiments/prereg/genesis-{genesis}.json"


def stamp_url(genesis: str) -> str:
    return f"{SITE_URL}/experiments/prereg/genesis-{genesis}.sha256.json"


def compute_sha256(path: Path = None) -> str:
    """SHA-256 over the EXACT file bytes — what `shasum -a 256` reports."""
    return hashlib.sha256((path or FROZEN_PATH).read_bytes()).hexdigest()


def load_stamp() -> dict | None:
    if not STAMP_PATH.exists():
        return None
    return json.loads(STAMP_PATH.read_text())


def write_stamp(now: datetime = None) -> dict:
    """Stamp the current frozen file. Idempotent over an unchanged file (keeps the
    original stamped_at). Refuses a same-genesis re-stamp with a different hash —
    that is an edit being laundered, not a stamp."""
    if not FROZEN_PATH.exists():
        raise SystemExit(f"No frozen pre-registration at {FROZEN_PATH} — run deploy/seed_genesis_preregistration.py first.")
    frozen = json.loads(FROZEN_PATH.read_text())
    genesis = frozen["genesis"]
    frozen_generated_at = frozen["generated_at"]
    sha = compute_sha256()

    existing = load_stamp()
    if existing is not None and existing.get("genesis") == genesis:
        if existing.get("sha256") == sha:
            print(f"Already stamped (unchanged): sha256 {sha} · stamped_at {existing['stamped_at']} kept.")
            return existing
        raise SystemExit(
            f"REFUSED: {FROZEN_PATH.name} for genesis {genesis} no longer matches its stamp "
            f"({existing.get('sha256')} → {sha}). The frozen pre-registration was EDITED after "
            "stamping — that edit cannot be laundered into a fresh stamp. Restore the frozen "
            "file (git checkout), or regenerate the whole pre-registration deliberately for a "
            "new genesis (delete BOTH the frozen file and this stamp)."
        )

    stamped_at = (now or datetime.now(timezone.utc)).isoformat()
    if stamped_at < frozen_generated_at:
        raise SystemExit(f"REFUSED: stamped_at {stamped_at} predates the freeze {frozen_generated_at} — a stamp is never backdated.")
    same_day = stamped_at[:10] == frozen_generated_at[:10]
    stamp = {
        "artifact": FROZEN_PATH.name,
        "genesis": genesis,
        "algorithm": "sha256",
        "sha256": sha,
        "frozen_generated_at": frozen_generated_at,
        "stamped_at": stamped_at,
        "stamp_note": (
            "Hash stamped at freeze time."
            if same_day
            else (
                f"Claims frozen {frozen_generated_at}; hash stamped later, {stamped_at}. Both moments are "
                "recorded — a stamp is never backdated. The hash covers the frozen file exactly as it "
                "stood when stamped."
            )
        ),
        "public_artifact_url": artifact_url(genesis),
        "public_stamp_url": stamp_url(genesis),
        "verify": f"curl -s {artifact_url(genesis)} | shasum -a 256",
    }
    STAMP_PATH.write_text(json.dumps(stamp, indent=2) + "\n")
    print(f"STAMPED {FROZEN_PATH.name} → {STAMP_PATH.name}\n  sha256 {sha}\n  stamped_at {stamped_at}")
    return stamp


def verify_stamp(frozen: dict = None) -> list:
    """Deterministic integrity check — returns a list of issues ([] = clean).
    Callers (seeder, publisher, tests) treat ANY issue as a hard stop."""
    issues = []
    if not FROZEN_PATH.exists():
        return [f"frozen pre-registration missing: {FROZEN_PATH}"]
    if frozen is None:
        frozen = json.loads(FROZEN_PATH.read_text())
    stamp = load_stamp()
    if stamp is None:
        return [f"no hash stamp at {STAMP_PATH} — run: python3 deploy/genesis_prereg_stamp.py"]
    sha = compute_sha256()
    if stamp.get("sha256") != sha:
        issues.append(
            f"HASH MISMATCH: frozen file is {sha} but the stamp says {stamp.get('sha256')} — "
            "the pre-registration was edited after stamping (pre-registration never silently changes)"
        )
    if stamp.get("genesis") != frozen.get("genesis"):
        issues.append(f"stamp is for genesis {stamp.get('genesis')} but the frozen file says {frozen.get('genesis')}")
    if stamp.get("frozen_generated_at") != frozen.get("generated_at"):
        issues.append(f"stamp records freeze time {stamp.get('frozen_generated_at')} but the frozen file says {frozen.get('generated_at')}")
    if stamp.get("stamped_at", "") < stamp.get("frozen_generated_at", ""):
        issues.append("stamp is BACKDATED (stamped_at predates the freeze) — stamps state their real moment")
    return issues


def require_valid_stamp(frozen: dict = None) -> dict:
    """verify_stamp or die — the shared write-path guard (seeder + publisher)."""
    issues = verify_stamp(frozen)
    if issues:
        raise SystemExit("Pre-registration hash-stamp check FAILED:\n  - " + "\n  - ".join(issues))
    return load_stamp()


def publish_to_s3(stamp: dict) -> None:
    """Upload the frozen file VERBATIM + the stamp to the public prereg route.
    Immutable post-publish: refuses to overwrite a published artifact whose bytes
    differ from the local (stamped) frozen file."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client("s3", region_name=REGION)
    genesis = stamp["genesis"]
    body = FROZEN_PATH.read_bytes()
    local_sha = hashlib.sha256(body).hexdigest()
    assert local_sha == stamp["sha256"], "stamp/file drift caught at publish time"

    for key, payload in ((artifact_key(genesis), body), (stamp_key(genesis), (json.dumps(stamp, indent=2) + "\n").encode())):
        try:
            existing = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
            if existing == payload:
                print(f"  s3://{S3_BUCKET}/{key} — already published, byte-identical, left untouched.")
                continue
            if key == artifact_key(genesis):
                raise SystemExit(
                    f"REFUSED: s3://{S3_BUCKET}/{key} already exists with DIFFERENT bytes "
                    f"(published sha256 {hashlib.sha256(existing).hexdigest()}, local {local_sha}). "
                    "A published pre-registration is immutable — it is never overwritten."
                )
            # The stamp sidecar may gain fields (e.g. a re-generated verify string) but its
            # hash must agree with the published artifact — checked above via the artifact.
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
                raise
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=payload, ContentType="application/json", CacheControl="public, max-age=300")
        print(f"  WROTE s3://{S3_BUCKET}/{key} ({len(payload)} bytes)")
    print(f"\nPublic artifact: {artifact_url(genesis)}\nPublic stamp:    {stamp_url(genesis)}\nVerify:          {stamp['verify']}")
    print("(New objects on /experiments/prereg/* can be 404-cached by CloudFront for ~300s — re-curl after 5 min before alarming.)")


def main():
    ap = argparse.ArgumentParser(description="Hash-stamp + publish the frozen genesis pre-registration (#1378)")
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
