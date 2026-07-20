#!/bin/bash
# apply_s3_lifecycle.sh — Apply the FULL S3 lifecycle configuration for matthew-life-platform.
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ THIS FILE IS THE SOURCE OF TRUTH for the bucket's lifecycle configuration.  │
# │ `put-bucket-lifecycle-configuration` REPLACES the entire config — a rule    │
# │ not declared below is DELETED on the next run. Add/change rules HERE,       │
# │ never out-of-band in the console or ad-hoc CLI calls.                       │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# The bucket is imported into CDK (`Bucket.from_bucket_name`, core_stack.py), so
# CDK cannot own lifecycle rules — this script is the sanctioned management path
# (see docs/MANAGED_WHERE_LEDGER.md). Retention values mirror the policy table
# in docs/DATA_GOVERNANCE.md — change them together.
#
# Rules (one per managed prefix):
#   deploys/       expire 30d (rollback artifacts; latest.zip age resets each deploy)
#   raw/           keep current forever; noncurrent versions 7d (keep 1); abort MPU 7d
#   uploads/       expire 30d; noncurrent 7d
#   generated/     keep current forever; noncurrent 7d (keep 1)
#   generated/qa_archive/  expire 90d AT THE BYTE LEVEL (#1441 — generation-time
#                  archive of every AI surface, text + screenshots; audit-log
#                  retention class). The bucket is VERSIONED, so a bare
#                  `Expiration {Days: 90}` only writes a delete marker — the
#                  bytes live on as a noncurrent version, and the overlapping
#                  generated/ rule would KEEP that version forever
#                  (NewerNoncurrentVersions: 1 retains the newest one, which for
#                  these write-once uuid-keyed objects is ALWAYS the one holding
#                  100% of the bytes). Hence TWO rules:
#                  (a) qa-archive-expire-90d — delete-marker the current version
#                      at 90d AND expire noncurrent versions 7d after they turn
#                      noncurrent, with NO keep-newest carve-out (on overlap S3
#                      applies the action that deletes soonest, so the
#                      generated/ carve-out does not shield these keys);
#                  (b) qa-archive-clean-delete-markers — sweep the then-expired
#                      delete markers (ExpiredObjectDeleteMarker cannot share a
#                      rule with Days, so it needs its own rule).
#                  Net per object: listed 90d, bytes purged ≈day 97, marker
#                  swept after. Verify post-apply on a >97d-old day prefix:
#                  `aws s3api list-object-versions --bucket matthew-life-platform \
#                     --prefix generated/qa_archive/text/<old-date>/` → empty.
#   claude-memory-backup/  keep current forever; noncurrent 90d (#1026 —
#                  daily-changing memory files on a versioned bucket would
#                  otherwise accrete versions unboundedly)
#   datadrops-archive/     keep current forever; noncurrent 30d (keep 1)
#                  (#1026 — laptop datadrops originals; NOT under uploads/,
#                  whose 30d EXPIRATION would silently delete the archive)
#   config/        keep current forever; noncurrent 30d (keep 3)
#   cloudtrail/    expire 90d (audit-log class); noncurrent 7d
#   remediation-log/dispatch-dedupe/  expire 1d (dedupe markers only; the
#                  automerge audit ledger under remediation-log/ is kept forever)
#   mcp-audit/     IA at 30d, expire 90d (#886 — MCP write-audit trail, #753).
#                  90d matches the cloudtrail/ audit-log retention class in
#                  docs/DATA_GOVERNANCE.md. NB: the bucket's
#                  TransitionDefaultMinimumObjectSize is all_storage_classes_128K,
#                  so the IA transition is a no-op for today's tiny (<128 KB)
#                  audit records — expiration is the operative control; the
#                  transition future-proofs larger records at zero cost.
#
# Lifecycle expiration is executed by the S3 service itself — no IAM principal
# is evaluated against the bucket policy — so these rules coexist with the
# `ProtectDataFromDeployScripts` DeleteObject Deny on matthew-admin
# (deploy/bucket_policy.json), which covers raw/*, config/*, mcp-audit/*, etc.
#
# Re-run is idempotent. Run after changing any rule below.
#
# Usage:
#   bash deploy/apply_s3_lifecycle.sh

set -euo pipefail

BUCKET="matthew-life-platform"

echo "Applying full S3 lifecycle configuration to s3://${BUCKET} ..."

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "expire-lambda-deploy-artifacts",
        "Status": "Enabled",
        "Filter": {"Prefix": "deploys/"},
        "Expiration": {"Days": 30}
      },
      {
        "ID": "raw-expire-noncurrent-versions-7d",
        "Status": "Enabled",
        "Filter": {"Prefix": "raw/"},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7, "NewerNoncurrentVersions": 1}
      },
      {
        "ID": "raw-abort-incomplete-multipart-7d",
        "Status": "Enabled",
        "Filter": {"Prefix": "raw/"},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
      },
      {
        "ID": "uploads-expire-30d",
        "Status": "Enabled",
        "Filter": {"Prefix": "uploads/"},
        "Expiration": {"Days": 30},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7}
      },
      {
        "ID": "generated-expire-noncurrent-7d",
        "Status": "Enabled",
        "Filter": {"Prefix": "generated/"},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7, "NewerNoncurrentVersions": 1}
      },
      {
        "ID": "qa-archive-expire-90d",
        "Status": "Enabled",
        "Filter": {"Prefix": "generated/qa_archive/"},
        "Expiration": {"Days": 90},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7}
      },
      {
        "ID": "qa-archive-clean-delete-markers",
        "Status": "Enabled",
        "Filter": {"Prefix": "generated/qa_archive/"},
        "Expiration": {"ExpiredObjectDeleteMarker": true}
      },
      {
        "ID": "claude-memory-backup-expire-noncurrent-90d",
        "Status": "Enabled",
        "Filter": {"Prefix": "claude-memory-backup/"},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 90}
      },
      {
        "ID": "datadrops-archive-expire-noncurrent-30d",
        "Status": "Enabled",
        "Filter": {"Prefix": "datadrops-archive/"},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 30, "NewerNoncurrentVersions": 1}
      },
      {
        "ID": "config-expire-noncurrent-30d",
        "Status": "Enabled",
        "Filter": {"Prefix": "config/"},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 30, "NewerNoncurrentVersions": 3}
      },
      {
        "ID": "cloudtrail-expire-90d",
        "Status": "Enabled",
        "Filter": {"Prefix": "cloudtrail/"},
        "Expiration": {"Days": 90},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7}
      },
      {
        "ID": "remediation-dispatch-dedupe-expire-1d",
        "Status": "Enabled",
        "Filter": {"Prefix": "remediation-log/dispatch-dedupe/"},
        "Expiration": {"Days": 1}
      },
      {
        "ID": "mcp-audit-ia-30d-expire-90d",
        "Status": "Enabled",
        "Filter": {"Prefix": "mcp-audit/"},
        "Transitions": [{"Days": 30, "StorageClass": "STANDARD_IA"}],
        "Expiration": {"Days": 90},
        "NoncurrentVersionExpiration": {"NoncurrentDays": 7}
      }
    ]
  }'

echo ""
echo "Done. Verifying..."
aws s3api get-bucket-lifecycle-configuration --bucket "${BUCKET}" \
  | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
for r in cfg.get('Rules', []):
    exp = r.get('Expiration', {}).get('Days', '-')
    trans = ','.join(f\"{t['StorageClass']}@{t['Days']}d\" for t in r.get('Transitions', []))
    print(f\"  {r['ID']:45s} {r['Status']:8s} prefix={r.get('Filter',{}).get('Prefix','?'):40s} expire={exp} {('transition=' + trans) if trans else ''}\")
print(f\"  ({len(cfg.get('Rules', []))} rules)\")
"
echo ""
echo "Lifecycle configuration applied."
