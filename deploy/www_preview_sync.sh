#!/usr/bin/env bash
# deploy/www_preview_sync.sh — sync a built v9 tree to ONE of its two S3 targets and invalidate it
# (#5530 preview · #5534 root), or roll the root target back to the previous v9 build.
#
# Targets (one owner per path, #5534):
#   preview  www/dist → s3://matthew-life-platform/site/next/v9/   invalidates /next/v9/*
#            (WEB_BASE=/next/v9/, WEB_NOINDEX=1 — the existing noindex preview convention)
#   root     www/dist → s3://matthew-life-platform/site/           invalidates /*
#            ONLY when www/owned_paths.json says `live_at_root: true` (the committed cut-over switch),
#            and only after deploy/www_owned_paths.py --check-dist proves the LIVE build lands on no
#            kept site/ page outside the declared replaced set. The site/ deploy excludes exactly the
#            paths this writes, so neither path can overwrite the other.
#
# Never deletes: a page that disappears from the build stays served until a cut-over decides otherwise
# (the owner's keep-everything rulings). Hashed assets are immutable for a year; pages are 300 s — the
# same ladder deploy/sync_site_to_s3.sh uses for site/.
#
# Rollback (root only): `--restore-previous` copies s3://…/site/_v9_previous/ (the last root build
# whose sweeps were green, written by `--record-previous` at the end of a green run) back over the
# root, S3 → S3, no delete. The source holds only v9 output, so the restore can only ever touch
# v9-owned keys — it cannot re-publish the v8 front page, and it cannot touch a kept site/ page.
# On the FIRST root deploy there is no previous build: the restore says so and exits 0 having
# written nothing; the un-launch is then the owner's deliberate command (www/README.md).
#
# Usage:
#   bash deploy/www_preview_sync.sh --target preview|root [--dist www/dist] [--print]
#   bash deploy/www_preview_sync.sh --target root --record-previous [--dist www/dist] [--print]
#   bash deploy/www_preview_sync.sh --target root --restore-previous [--print]
#   bash deploy/www_preview_sync.sh [<dist-dir>] [<s3-prefix>] [<invalidation-path>]   # the #5530 form
# `--print` prints every aws command line instead of running it (the lane rehearsal: no credentials,
# no writes). Needs otherwise: the AWS CLI with a role that may write s3://matthew-life-platform/site/*
# and call cloudfront:CreateInvalidation (the site deploy's role already can).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUCKET="${BUCKET:-matthew-life-platform}"
STACK="${WEB_STACK:-LifePlatformWeb}"
PREVIOUS_PREFIX="site/_v9_previous"

TARGET=""
DIST="www/dist"
PRINT=0
MODE="sync"
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --dist) DIST="$2"; shift 2 ;;
    --print) PRINT=1; shift ;;
    --record-previous) MODE="record"; shift ;;
    --restore-previous) MODE="restore"; shift ;;
    --*) echo "www_preview_sync: unknown flag $1" >&2; exit 3 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

# The #5530 positional form (dist prefix invalidation) still works and means "preview".
if [ -z "$TARGET" ]; then
  TARGET="preview"
  DIST="${POSITIONAL[0]:-$DIST}"
  PREFIX="${POSITIONAL[1]:-site/next/v9}"
  INVALIDATE="${POSITIONAL[2]:-/next/v9/*}"
else
  case "$TARGET" in
    preview) PREFIX="site/next/v9"; INVALIDATE="/next/v9/*" ;;
    root)    PREFIX="site";         INVALIDATE="/*" ;;
    *) echo "www_preview_sync: --target must be preview or root (got '$TARGET')" >&2; exit 3 ;;
  esac
fi
case "$PREFIX" in
  site|site/*) ;;
  *) echo "www_preview_sync: prefix must live under site/ (got '$PREFIX')" >&2; exit 3 ;;
esac

run() {
  if [ "$PRINT" = "1" ]; then
    printf '  $'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

invalidate() {
  local paths="$1" wait="$2"
  if [ "$PRINT" = "1" ]; then
    echo "  \$ DIST_ID=\$(aws cloudformation describe-stacks --stack-name $STACK --query \"Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue\" --output text)"
    echo "  \$ INV=\$(aws cloudfront create-invalidation --distribution-id \$DIST_ID --paths '$paths' --query Invalidation.Id --output text)"
    [ "$wait" = "1" ] && echo "  \$ aws cloudfront wait invalidation-completed --distribution-id \$DIST_ID --id \$INV   # #1526: the sweeps read fresh edges"
    return 0
  fi
  local dist_id inv
  dist_id=$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" --output text)
  test -n "$dist_id" && test "$dist_id" != "None"
  inv=$(aws cloudfront create-invalidation --distribution-id "$dist_id" --paths "$paths" --query "Invalidation.Id" --output text)
  echo "www_preview_sync: invalidation $inv on $dist_id for $paths"
  if [ "$wait" = "1" ]; then
    # #1526: the root target is judged by the smoke + visual sweeps right after this; block until the
    # edges serve the new build so a stale edge cannot red a healthy deploy. A waiter timeout warns.
    aws cloudfront wait invalidation-completed --distribution-id "$dist_id" --id "$inv" \
      && echo "www_preview_sync: invalidation $inv completed — edges serve this build" \
      || echo "www_preview_sync: ⚠️  invalidation $inv still in flight after the waiter's cap; proceeding"
  fi
}

# ── restore: the previous v9 build back over the root, S3 → S3 ─────────────────────────────────
if [ "$MODE" = "restore" ]; then
  [ "$TARGET" = "root" ] || { echo "www_preview_sync: --restore-previous is a root-target operation" >&2; exit 3; }
  echo "www_preview_sync: ROLLBACK — restoring the previous v9 build from s3://$BUCKET/$PREVIOUS_PREFIX/ over s3://$BUCKET/site/ (no delete; v9-owned keys only, #5534)"
  if [ "$PRINT" = "1" ]; then
    echo "  \$ aws s3 ls s3://$BUCKET/$PREVIOUS_PREFIX/index.html   # absent → first root deploy, nothing to restore, exit 0"
  elif ! aws s3 ls "s3://$BUCKET/$PREVIOUS_PREFIX/index.html" >/dev/null 2>&1; then
    echo "www_preview_sync: no previous v9 build at s3://$BUCKET/$PREVIOUS_PREFIX/ (the first root deploy) — NOTHING RESTORED."
    echo "  The v9 build stays live at /. Un-launching is the owner's deliberate command (www/README.md § Rollback), never this script."
    exit 0
  fi
  run aws s3 sync "s3://$BUCKET/$PREVIOUS_PREFIX/_astro" "s3://$BUCKET/site/_astro" --cache-control "public, max-age=31536000, immutable" --only-show-errors
  run aws s3 sync "s3://$BUCKET/$PREVIOUS_PREFIX/assets" "s3://$BUCKET/site/assets" --cache-control "public, max-age=31536000, immutable" --only-show-errors
  run aws s3 sync "s3://$BUCKET/$PREVIOUS_PREFIX" "s3://$BUCKET/site" --exclude "_astro/*" --exclude "assets/*" --cache-control "public, max-age=300" --only-show-errors
  invalidate "/*" 1
  echo "www_preview_sync: previous v9 build restored over / — verify https://averagejoematt.com/"
  exit 0
fi

# ── sync and record both need a built tree ────────────────────────────────────────────────────
test -d "$DIST" || { echo "www_preview_sync: dist dir not found: $DIST" >&2; exit 3; }
test -f "$DIST/index.html" || { echo "www_preview_sync: $DIST has no index.html — refusing to sync an empty build" >&2; exit 3; }
PAGES=$(find "$DIST" -name index.html | wc -l | tr -d ' ')

if [ "$MODE" = "record" ]; then
  [ "$TARGET" = "root" ] || { echo "www_preview_sync: --record-previous is a root-target operation" >&2; exit 3; }
  echo "www_preview_sync: recording this green root build ($PAGES pages) as the previous build at s3://$BUCKET/$PREVIOUS_PREFIX/ (no delete)"
  run aws s3 sync "$DIST" "s3://$BUCKET/$PREVIOUS_PREFIX" --cache-control "public, max-age=300" --only-show-errors
  exit 0
fi

if [ "$TARGET" = "root" ]; then
  # The two gates a root sync must pass, both fail-closed and both AWS-free (#5534):
  #   1. the committed cut-over switch — a dispatch cannot launch before the repo says `/` is v9's;
  #   2. the LIVE build's routes land on no kept site/ page outside the replaced set.
  if [ "$PRINT" = "1" ]; then
    echo "  \$ python3 deploy/www_owned_paths.py --live-at-root    # exit 1 → refuse the root sync"
    echo "  \$ python3 deploy/www_owned_paths.py --check-dist $DIST   # exit 1 → refuse the root sync"
  else
    python3 "$HERE/www_owned_paths.py" --live-at-root || { echo "www_preview_sync: REFUSED — www/owned_paths.json has live_at_root=false; the switch is a one-line merge, not a dispatch (#5534)" >&2; exit 4; }
    python3 "$HERE/www_owned_paths.py" --check-dist "$DIST" || exit 4
  fi
fi

echo "www_preview_sync: target=$TARGET · $PAGES pages from $DIST → s3://$BUCKET/$PREFIX (no delete) · invalidate $INVALIDATE"
run aws s3 sync "$DIST/_astro" "s3://$BUCKET/$PREFIX/_astro" --cache-control "public, max-age=31536000, immutable" --only-show-errors
run aws s3 sync "$DIST/assets" "s3://$BUCKET/$PREFIX/assets" --cache-control "public, max-age=31536000, immutable" --only-show-errors
run aws s3 sync "$DIST" "s3://$BUCKET/$PREFIX" --exclude "_astro/*" --exclude "assets/*" --cache-control "public, max-age=300" --only-show-errors
if [ "$TARGET" = "root" ]; then invalidate "$INVALIDATE" 1; else invalidate "$INVALIDATE" 0; fi
