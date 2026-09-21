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
  4. LEDGER PROVENANCE (--apply, #3511): a seal is a claim ABOUT the live rows, so
     before the bytes go up, deploy/prereg_provenance_gate.py checks that the live
     prediction ledger agrees with the frozen artifact — no unsealed row presenting
     as pre-genesis, and (from genesis onward) no sealed id missing from the season.
     Blocking findings abort the publish; a gate that cannot run aborts it too.
  5. TRUTH (#3599): steps 3 and 4 can both be green over an artifact that is
     internally consistent and simply not true — a retired coach, a superseded
     baseline, a minimum effect nobody priced. deploy/prereg_truth_gate.py checks the
     artifact against the platform's own facts (persona registry, EXPERIMENT_BASELINE_
     WEIGHT_LBS, the #3552 derivation block) and write_stamp() refuses to MINT a seal
     over blocking findings. It is deliberately placed after the idempotent
     already-stamped return: a seal that already exists is never re-vouched or
     rewritten (#3552's lesson — a published pre-registration is amended in public,
     never edited), so the gate binds new seals only.

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


def _truth_findings(frozen: dict) -> list:
    """The #3599 blocking findings for `frozen`. Fails CLOSED — "could not tell" is not
    "fine" for the platform's central credibility claim, the same posture the #3511
    gate and restart_verify.served_genesis take."""
    if str(REPO_ROOT / "deploy") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "deploy"))
    try:
        import prereg_truth_gate
    except Exception as e:
        raise SystemExit(f"#3599 truth gate could not be imported ({e}) — refusing to stamp a seal it cannot vouch for.")
    try:
        return prereg_truth_gate.require_clean_for_seal(artifact=frozen)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"#3599 truth gate could not run ({e}) — refusing to stamp a seal it cannot vouch for.")


def _refuse_untrue_seal(frozen: dict) -> None:
    untrue = _truth_findings(frozen)
    if untrue:
        raise SystemExit(
            f"REFUSED: the #3599 truth gate reports {len(untrue)} blocking finding(s) — this pre-registration "
            "disagrees with the platform's own facts, and a seal is permanent. Fix the artifact and re-freeze "
            "(delete the frozen file and re-run deploy/seed_genesis_preregistration.py); a sealed one is amended "
            "in public, never edited.\n  - " + "\n  - ".join(str(f) for f in untrue)
        )
    print("#3599 truth gate: clean — the artifact agrees with the persona registry, the baseline and the derivation contract.")


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

    # #3599 — everything below MINTS a seal, and a seal is one-way: the same genesis may
    # never be re-stamped with different bytes and stamped_at is never backdated, so an
    # artifact that names a retired coach, a superseded baseline or an underived minimum
    # effect can never be corrected afterwards, only amended in public. Pure (file +
    # repo constants, no credentials, no network), so unlike the #3511 ledger gate it
    # runs on every seal path — the seeder's freeze-time stamp as well as this module's
    # CLI. Placed AFTER the idempotent return on purpose: an already-published seal is
    # left exactly as it stands.
    _refuse_untrue_seal(frozen)

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

    # #3599 — write_stamp() only gates seals it MINTS, so an artifact sealed before this
    # gate existed slips past silently. Report it here so the operator sees the verdict
    # on every run rather than only on the run that would have been blocked. This does
    # NOT block: the seal is already published, and rewriting a published pre-registration
    # is the defect, not the repair.
    standing = _truth_findings(json.loads(FROZEN_PATH.read_text()))
    if standing:
        print(
            f"\nALREADY SEALED, NOT RE-VOUCHED — the #3599 truth gate reports {len(standing)} blocking finding(s) "
            f"against this artifact. It was stamped at {stamp['stamped_at']}; a FRESH seal carrying these would be "
            "REFUSED. The repair for a published seal is a public amendment record, never an edit:\n  - "
            + "\n  - ".join(str(f) for f in standing)
            + (
                "\n\nThat record now has a shape and a builder (#3599) — read-only, prints what it would publish:\n"
                f"  python3 deploy/prereg_amendment.py --genesis {stamp['genesis']}\n"
                "It appends to generated/experiments/prereg/genesis-<genesis>.amendments.json, which the site serves\n"
                "beside the seal (site_api_common.prereg_seal_meta). The sealed bytes are never touched."
            )
        )

    if not args.apply:
        print(
            "\nDRY RUN for the publish step — re-run with --apply to upload the artifact + stamp to S3.\n"
            "(the #3511 ledger-provenance gate runs on --apply, where it can read the live table)"
        )
        return 0

    # #3511 — "else the seal cannot publish". A published, hash-verified seal whose
    # claims the live ledger contradicts is worse than no seal: it is a verifiable
    # artifact vouching for rows that do not match it. So the LEDGER is checked before
    # the bytes go up, using the same pure predicate restart_verify check 20 and the CI
    # test call. Pre-genesis (the normal attended publish moment) the only applicable
    # clauses are the two write classes — the missing-seal clause is not applicable
    # until genesis — so this gate is satisfiable by construction at the moment it runs.
    # Read-only: it queries the COACH#* PREDICTION# partitions and writes nothing.
    if str(REPO_ROOT / "deploy") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "deploy"))
    try:
        import prereg_provenance_gate

        offenders = prereg_provenance_gate.require_clean_for_publish()
    except Exception as e:
        # Fail CLOSED. "Could not tell" is not "fine" for the platform's central
        # credibility claim — the same posture restart_verify.served_genesis takes.
        raise SystemExit(f"#3511 provenance gate could not run ({e}) — refusing to publish a seal it cannot vouch for.")
    if offenders:
        raise SystemExit(
            f"#3511 provenance gate: {len(offenders)} blocking finding(s) — the live prediction ledger "
            "disagrees with the frozen pre-registration, so this seal would vouch for rows that do not "
            "match it. Refusing to publish.\n  - " + "\n  - ".join(str(f) for f in offenders)
        )
    print(f"#3511 provenance gate: clean — the live ledger agrees with {FROZEN_PATH.name}.")

    publish_to_s3(stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
