#!/usr/bin/env bash
# deploy/quarantine_public_copy.sh — take a public copy off the site WITHOUT destroying it (#6083, owner ruling 2026-11-16:
# "Do not automatically delete protected historical evidence; remove public access and preserve it privately").
#
# For each key: a server-side copy to s3://$BUCKET/backups/quarantine/public-copies/<UTC stamp>/<key> (backups/ is not
# anonymously readable and not delete-protected — deploy/bucket_policy.json; no lifecycle rule expires it), then the
# copy is VERIFIED (ETag and size equal the original's), and only then is the public object removed. A key whose copy
# does not verify is left public and named; the run exits 1. Last: the removed paths are invalidated at CloudFront and
# a manifest of what moved is written beside the copies.
#
# Why a copy and not the bucket's versioning: site/ non-current versions EXPIRE after 7 days (lifecycle rule
# site-expire-noncurrent-7d), so a bare delete keeps the evidence for a week, not for good.
#
# Only site/ keys: everything else a reader can fetch is either not a copy of the site or delete-protected
# (generated/* — the archive is replaced by re-running life-platform-permanence, never by removing it). Never a
# bucket-root operation, never `--delete`, never run by CI: scripts/check_public_copies.py prints this command and
# a human runs it, attended, with a principal that may delete site/* (the CI deploy role may not).
#
# Usage:
#   bash deploy/quarantine_public_copy.sh --keys FILE [--apply]          # one site/ key per line (check_public_copies.py --orphans-out)
#   bash deploy/quarantine_public_copy.sh --prefix site/next/v9/ [--apply]   # every object under a prefix (emptying the preview)
# Without --apply it is a dry run: it lists the keys and prints every command, and runs nothing that writes.
set -euo pipefail
# #6116: under a test runner, real AWS is unreachable from this script (deploy/lib/prod_write_guard.sh)
source "$(dirname "${BASH_SOURCE[0]}")/lib/prod_write_guard.sh"

BUCKET="${BUCKET:-matthew-life-platform}"
STACK="${WEB_STACK:-LifePlatformWeb}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="backups/quarantine/public-copies/$STAMP"
KEYS_FILE="" PREFIX="" APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --keys) KEYS_FILE="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    *) echo "quarantine_public_copy: unknown argument $1" >&2; exit 3 ;;
  esac
done
if [ -n "$KEYS_FILE" ] && [ -n "$PREFIX" ]; then echo "quarantine_public_copy: --keys or --prefix, not both" >&2; exit 3; fi
if [ -z "$KEYS_FILE" ] && [ -z "$PREFIX" ]; then echo "quarantine_public_copy: --keys FILE or --prefix site/<dir>/ is required" >&2; exit 3; fi
if [ -n "$PREFIX" ]; then
  # a prefix is one directory under site/, never site/ itself (the whole site) and never outside it
  case "$PREFIX" in
    site/?*/) ;;
    *) echo "quarantine_public_copy: --prefix must be a directory under site/ ending in / (got '$PREFIX')" >&2; exit 3 ;;
  esac
fi

KEYS="$(mktemp)"
trap 'rm -f "$KEYS"' EXIT
if [ -n "$PREFIX" ]; then
  aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$PREFIX" --query 'Contents[].Key' --output text | tr '\t' '\n' | grep -v '^None$' | sed '/^$/d' > "$KEYS" || true
else
  test -f "$KEYS_FILE" || { echo "quarantine_public_copy: no such keys file: $KEYS_FILE" >&2; exit 3; }
  sed '/^[[:space:]]*$/d' "$KEYS_FILE" > "$KEYS"
fi
while IFS= read -r key; do
  case "$key" in
    site/?*) ;;
    *) echo "quarantine_public_copy: REFUSED — '$key' is not a site/ object (generated/* is delete-protected; the archive is regenerated, not removed)" >&2; exit 3 ;;
  esac
done < "$KEYS"
N=$(wc -l < "$KEYS" | tr -d ' ')
[ "$N" -gt 0 ] || { echo "quarantine_public_copy: nothing to quarantine"; exit 0; }

echo "quarantine_public_copy: $N object(s) → s3://$BUCKET/$DEST/ (copy, verify, then remove the public object)$([ "$APPLY" = 1 ] || echo ' — DRY RUN, nothing written')"
moved=0 failed=0
MANIFEST="$(mktemp)"
printf '{"stamp": "%s", "reason": "public copy quarantined (#6083)", "objects": [' "$STAMP" > "$MANIFEST"
while IFS= read -r key; do
  if [ "$APPLY" != 1 ]; then
    echo "  \$ aws s3api copy-object --bucket $BUCKET --copy-source $BUCKET/$key --key $DEST/$key"
    echo "  \$ (verify: head-object ETag + ContentLength of both are equal)  &&  aws s3api delete-object --bucket $BUCKET --key $key"
    continue
  fi
  src="$(aws s3api head-object --bucket "$BUCKET" --key "$key" --query '[ETag,ContentLength]' --output text 2>/dev/null || true)"
  if [ -z "$src" ]; then echo "  – $key: not present (already removed?) — skipped"; continue; fi
  aws s3api copy-object --bucket "$BUCKET" --copy-source "$BUCKET/$key" --key "$DEST/$key" > /dev/null
  dst="$(aws s3api head-object --bucket "$BUCKET" --key "$DEST/$key" --query '[ETag,ContentLength]' --output text 2>/dev/null || true)"
  if [ "$src" != "$dst" ]; then
    echo "  ✗ $key: the copy does not verify (source '$src', copy '$dst') — LEFT PUBLIC"
    failed=$((failed + 1))
    continue
  fi
  aws s3api delete-object --bucket "$BUCKET" --key "$key" > /dev/null
  [ "$moved" -gt 0 ] && printf ',' >> "$MANIFEST"
  printf '{"key": "%s", "etag_size": "%s"}' "$key" "$(printf '%s' "$src" | tr '\t"' ' ')" >> "$MANIFEST"
  moved=$((moved + 1))
  echo "  ✓ $key"
done < "$KEYS"
printf '], "moved": %s, "failed": %s}\n' "$moved" "$failed" >> "$MANIFEST"

# the public paths to invalidate: a prefix by its wildcard, a key list by each path (an index.html also by its directory)
PATHS="$(mktemp)"
if [ -n "$PREFIX" ]; then
  echo "/${PREFIX#site/}*" > "$PATHS"
else
  sed -e 's#^site/#/#' "$KEYS" | while IFS= read -r p; do echo "$p"; case "$p" in */index.html) echo "${p%index.html}" ;; esac; done > "$PATHS"
fi
if [ "$APPLY" != 1 ]; then
  echo "  \$ aws s3 cp <manifest> s3://$BUCKET/$DEST/manifest.json"
  echo "  \$ DIST_ID=\$(aws cloudformation describe-stacks --region us-east-1 --stack-name $STACK --query \"Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue\" --output text)"
  echo "  \$ aws cloudfront create-invalidation --distribution-id \$DIST_ID --paths $(tr '\n' ' ' < "$PATHS")"
  echo "quarantine_public_copy: dry run — re-run with --apply to do it"
  rm -f "$MANIFEST" "$PATHS"
  exit 0
fi
aws s3 cp "$MANIFEST" "s3://$BUCKET/$DEST/manifest.json" --only-show-errors
if [ "$moved" -gt 0 ]; then
  DIST_ID=$(aws cloudformation describe-stacks --region us-east-1 --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" --output text)
  # shellcheck disable=SC2046 — one argument per path, by design
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths $(tr '\n' ' ' < "$PATHS") --query Invalidation.Id --output text
fi
rm -f "$MANIFEST" "$PATHS"
echo "quarantine_public_copy: $moved moved to s3://$BUCKET/$DEST/, $failed left public. Next: python3 scripts/check_public_copies.py --remediation"
[ "$failed" = 0 ]
