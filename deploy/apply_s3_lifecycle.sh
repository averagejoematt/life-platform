#!/bin/bash
# apply_s3_lifecycle.sh — Apply the FULL S3 lifecycle configuration for matthew-life-platform.
#
# ┌─────────────────────────────────────────────────────────────────────────────┐
# │ deploy/s3_lifecycle.json IS THE SOURCE OF TRUTH for the bucket's lifecycle  │
# │ configuration (externalized #DIL-026/#2799 so `deploy/drift_sentinel.py`'s  │
# │ check_s3_lifecycle() can compare live vs. declared without parsing shell).  │
# │ `put-bucket-lifecycle-configuration` REPLACES the entire config — a rule    │
# │ not declared in that JSON is DELETED on the next run. Add/change rules      │
# │ THERE, never out-of-band in the console or ad-hoc CLI calls, and never by   │
# │ hand-editing the live config — this script is the only writer.             │
# └─────────────────────────────────────────────────────────────────────────────┘
#
# The bucket is imported into CDK (`Bucket.from_bucket_name`, core_stack.py), so
# CDK cannot own lifecycle rules — this script is the sanctioned management path
# (see docs/MANAGED_WHERE_LEDGER.md). Retention values mirror the policy table
# in docs/DATA_GOVERNANCE.md — change them together. The weekly drift sentinel
# (deploy/drift_sentinel.py::check_s3_lifecycle, run from the remediation
# workflow) asserts live `get-bucket-lifecycle-configuration` still matches this
# same deploy/s3_lifecycle.json rule-for-rule — a rule edited here but never
# applied, or a live rule that drifted out of band, both surface as drift within
# a week instead of silently diverging (the DIL-026 finding: `imports/` sat
# completely uncovered — 2.23GB of noncurrent versions — with no detector at all).
#
# Rules (one per managed prefix; declared in deploy/s3_lifecycle.json):
#   deploys/       expire (current) 30d (rollback artifacts; latest.zip age resets
#                  each deploy); noncurrent versions 7d (keep 1) — added #2642. The
#                  bucket is versioned, so `deploy_lambda.sh` copying latest.zip to
#                  previous.zip creates a NEW current version each deploy and pushes
#                  the prior previous.zip to noncurrent; deploys/ had NO
#                  NoncurrentVersionExpiration and 15+ deploys/session made those
#                  noncurrent versions accumulate forever (85.9 GB measured, #2642
#                  census). NewerNoncurrentVersions: 1 keeps the newest noncurrent
#                  generation so `deploys/<fn>/previous.zip` — the CURRENT object,
#                  unaffected by this rule either way — always resolves; rollback
#                  reads the current object, never a noncurrent version.
#   site/          keep current forever; noncurrent versions 7d (keep 1) — added
#                  #2642 (was completely uncovered: 4.42 GB / 276k noncurrent
#                  objects from every content-hashed redeploy versioning the whole
#                  tree). `rollback_site.sh` rebuilds from a git ref (checkout →
#                  re-hash → sync + version.json restamp, #418/ADR-117) and never
#                  reads S3 noncurrent versions, so this expiry cannot affect it.
#   raw/           keep current forever; noncurrent versions 7d (keep 1); abort MPU 7d
#   imports/       keep current forever; noncurrent versions 7d (keep 1) — added
#                  DIL-026/#2799 (2026-08-24). Same shape as raw/: `imports/` (Apple
#                  Health XML / MacroFactor CSV / measurements backfills) carries the
#                  SAME `ProtectDataFromDeployScripts` DeleteObject Deny as raw/, but
#                  had NO NoncurrentVersionExpiration at all — every re-upload or
#                  ingestion-lambda overwrite left the prior version live forever.
#                  Measured 2026-08-24: 2.07 GB noncurrent across 452 versions under
#                  ~0 current bytes (i.e. almost the entire prefix was dead noncurrent
#                  weight, unbounded in age). Lifecycle expiration is enforced by the
#                  S3 service itself, not IAM, so this rule coexists with the Deny
#                  exactly like the raw/ rule already does (see the note below).
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
#                  swept after. NB (#1435): generated/qa_archive/perf/ — the
#                  visual-QA web-vitals snapshots + weekly trend.json — rides this
#                  SAME rule (the filter is the generated/qa_archive/ prefix), so
#                  the perf trend's retention is bounded here with no extra rule.
#                  Verify post-apply on a >97d-old day prefix:
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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIFECYCLE_JSON="${SCRIPT_DIR}/s3_lifecycle.json"

echo "Applying full S3 lifecycle configuration to s3://${BUCKET} from ${LIFECYCLE_JSON} ..."

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET}" \
  --lifecycle-configuration "file://${LIFECYCLE_JSON}"

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
