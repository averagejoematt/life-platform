#!/usr/bin/env bash
# deploy/www_preview_sync.sh — sync a built v9 tree to its S3 prefix and invalidate it (#5530).
#
# Only ever writes under the prefix it is given (default the preview path site/next/v9) and
# never deletes: a page that disappears from the build stays served until a cut-over decides
# otherwise (the owner's keep-everything rulings). Hashed assets are immutable for a year;
# pages are 300 s, the same ladder deploy/sync_site_to_s3.sh uses for site/.
#
# Usage: bash deploy/www_preview_sync.sh [<dist-dir>] [<s3-prefix>] [<invalidation-path>]
#   defaults: www/dist  site/next/v9  /next/v9/*
# Needs: the AWS CLI with a role that may write s3://matthew-life-platform/<prefix>/* and
# call cloudfront:CreateInvalidation (the site deploy's role already can).
set -euo pipefail

DIST="${1:-www/dist}"
PREFIX="${2:-site/next/v9}"
INVALIDATE="${3:-/next/v9/*}"
BUCKET="${BUCKET:-matthew-life-platform}"
STACK="${WEB_STACK:-LifePlatformWeb}"

test -d "$DIST" || { echo "www_preview_sync: dist dir not found: $DIST" >&2; exit 3; }
test -f "$DIST/index.html" || { echo "www_preview_sync: $DIST has no index.html — refusing to sync an empty build" >&2; exit 3; }
case "$PREFIX" in
  site/*) ;;
  *) echo "www_preview_sync: prefix must live under site/ (got '$PREFIX')" >&2; exit 3 ;;
esac

PAGES=$(find "$DIST" -name index.html | wc -l | tr -d ' ')
echo "www_preview_sync: $PAGES pages from $DIST → s3://$BUCKET/$PREFIX (no delete)"

aws s3 sync "$DIST/_astro" "s3://$BUCKET/$PREFIX/_astro" --cache-control "public, max-age=31536000, immutable" --only-show-errors
aws s3 sync "$DIST/assets" "s3://$BUCKET/$PREFIX/assets" --cache-control "public, max-age=31536000, immutable" --only-show-errors
aws s3 sync "$DIST" "s3://$BUCKET/$PREFIX" --exclude "_astro/*" --exclude "assets/*" --cache-control "public, max-age=300" --only-show-errors

DIST_ID=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" --output text)
test -n "$DIST_ID" && test "$DIST_ID" != "None"
INV=$(aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "$INVALIDATE" --query "Invalidation.Id" --output text)
echo "www_preview_sync: invalidation $INV on $DIST_ID for $INVALIDATE"
