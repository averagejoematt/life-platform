#!/bin/bash
# apply_s3_replication.sh — Apply the FULL S3 replication configuration for
# matthew-life-platform (DIL-027, #3042: the isolated backup of the raw/ zone).
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ deploy/s3_replication.json IS THE SOURCE OF TRUTH.                          │
# │ `put-bucket-replication` REPLACES the entire configuration — a rule not     │
# │ declared there is DELETED on the next run. Add/change rules THERE, never    │
# │ out-of-band in the console or an ad-hoc CLI call.                           │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# WHY A SCRIPT AND NOT CDK
#   The primary bucket is imported (`Bucket.from_bucket_name`, core_stack.py), so
#   CDK cannot own a replication configuration on it — the identical constraint
#   that already puts the bucket policy and the lifecycle configuration in the
#   out-of-IaC ring (docs/MANAGED_WHERE_LEDGER.md). The DESTINATION bucket, its
#   delete-protection policy, its lifecycle and the replication ROLE are all
#   CDK-owned in cdk/stacks/backup_stack.py. This is the one leg that cannot be.
#
# DEPLOY ORDER — this script is step 2 of 3 and is NOT optional in any other order:
#
#   0. (once, if us-east-2 has never hosted a CDK stack in this account)
#        cd cdk && npx cdk bootstrap aws://205930651321/us-east-2
#   1. bash deploy/cdk_deploy.sh LifePlatformBackup
#        Creates the destination bucket + the replication role. The put below
#        FAILS with InvalidRequest if either does not exist yet.
#   2. bash deploy/apply_s3_replication.sh --apply       ← you are here
#   3. S3 Batch Replication for the pre-existing objects (see BACKFILL below)
#
# SOURCE VERSIONING
#   Replication requires versioning on the SOURCE bucket. Verified live
#   2026-08-24: matthew-life-platform versioning Status=Enabled already — no
#   change needed, and this script asserts it rather than assuming it.
#
# BACKFILL — READ THIS, IT IS THE EASY THING TO GET WRONG
#   S3 replication is NOT retroactive. Turning it on protects objects written
#   FROM NOW ON. The 37,665 objects / 541,451,065 bytes already in raw/ (measured
#   2026-08-24) stay unprotected until an S3 Batch Replication job copies them.
#   `deploy/sentinel_replication.py` probes an OLD key precisely so this cannot be
#   quietly skipped — it reports drift until the backfill lands. Kick it off in the
#   S3 console (Management → Replication rules → "Replicate existing objects") or:
#     aws s3control create-job --account-id 205930651321 --region us-west-2 \
#       --operation '{"S3ReplicateObject":{}}' --priority 10 \
#       --manifest-generator file://<generated> --role-arn <batch-ops-role>
#   One-time cost measured against the live inventory: ≈ $0.49 (37,665 PUTs
#   ≈ $0.19 + 0.50 GB transfer ≈ $0.01 + Batch Operations job ≈ $0.29).
#
# Usage:
#   bash deploy/apply_s3_replication.sh            # DRY RUN — prints the diff, changes nothing
#   bash deploy/apply_s3_replication.sh --apply    # writes the configuration

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUCKET="${S3_BUCKET:-matthew-life-platform}"
REGION="${AWS_REGION:-us-west-2}"
CONFIG="$ROOT/deploy/s3_replication.json"

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

echo "── S3 replication configuration — $BUCKET ($REGION)"
echo "   source of truth: deploy/s3_replication.json"

# The JSON carries a leading `_comment` block (the rationale has to live WITH the
# rules, not in a doc that drifts from them). The API rejects unknown keys, so it is
# stripped here at apply time rather than being omitted from the file.
PAYLOAD="$(python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
cfg.pop("_comment", None)
print(json.dumps(cfg))
' "$CONFIG")"

# ── Preflight 1: source versioning (a hard requirement for replication) ──
SRC_VERSIONING="$(aws s3api get-bucket-versioning --bucket "$BUCKET" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "None")"
if [[ "$SRC_VERSIONING" != "Enabled" ]]; then
    echo "   ✗ source bucket versioning is '$SRC_VERSIONING' — replication requires 'Enabled'." >&2
    echo "     Enable it first (additive, safe): aws s3api put-bucket-versioning --bucket $BUCKET --versioning-configuration Status=Enabled" >&2
    exit 1
fi
echo "   ✓ source versioning: Enabled"

# ── Preflight 2: the destination bucket and the role must already exist ──
DEST_ARN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["Rules"][0]["Destination"]["Bucket"])' "$PAYLOAD")"
DEST_BUCKET="${DEST_ARN##*:::}"
ROLE_ARN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["Role"])' "$PAYLOAD")"
ROLE_NAME="${ROLE_ARN##*/}"

DEST_VERSIONING="$(aws s3api get-bucket-versioning --bucket "$DEST_BUCKET" --query 'Status' --output text 2>/dev/null || echo "MISSING")"
if [[ "$DEST_VERSIONING" != "Enabled" ]]; then
    echo "   ✗ destination bucket $DEST_BUCKET: versioning is '$DEST_VERSIONING' (expected Enabled)." >&2
    echo "     Deploy the backup stack FIRST: bash deploy/cdk_deploy.sh LifePlatformBackup" >&2
    exit 1
fi
echo "   ✓ destination $DEST_BUCKET: versioning Enabled"

if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "   ✗ replication role $ROLE_NAME does not exist." >&2
    echo "     Deploy the backup stack FIRST: bash deploy/cdk_deploy.sh LifePlatformBackup" >&2
    exit 1
fi
echo "   ✓ replication role $ROLE_NAME: exists"

# ── The diff ──
echo "   live configuration:"
aws s3api get-bucket-replication --bucket "$BUCKET" --region "$REGION" 2>/dev/null \
    | python3 -m json.tool \
    | sed 's/^/     /' \
    || echo "     (none — replication has never been configured on this bucket)"

echo "   desired configuration:"
echo "$PAYLOAD" | python3 -m json.tool | sed 's/^/     /'

if [[ "$APPLY" -eq 0 ]]; then
    echo
    echo "   DRY RUN — nothing written. Re-run with --apply to put the configuration."
    exit 0
fi

aws s3api put-bucket-replication \
    --bucket "$BUCKET" \
    --region "$REGION" \
    --replication-configuration "$PAYLOAD"

echo "   ✓ applied. Verifying…"
aws s3api get-bucket-replication --bucket "$BUCKET" --region "$REGION" | python3 -m json.tool | sed 's/^/     /'

echo
echo "   NEXT: replication is NOT retroactive — run the S3 Batch Replication backfill"
echo "   for the pre-existing raw/ objects (see the BACKFILL section in this script's"
echo "   header). Until it completes, deploy/sentinel_replication.py reports drift, by design."
