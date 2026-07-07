#!/usr/bin/env bash
# sync_site_to_s3.sh — Build content-hashed assets, sync to S3, invalidate CloudFront
#
# Content-hash strategy (ADR-039 fix):
#   - CSS/JS files get an 8-char MD5 hash in their filename (base.css → base.a1b2c3d4.css)
#   - Hashed files: max-age=31536000 (1 year, immutable) — browser never re-downloads
#   - Original filenames still uploaded with max-age=86400 (fallback for dynamic JS loads)
#   - HTML: max-age=300 (5 min) — references hashed filenames, updates quickly on deploy
#   - Data JSON: max-age=86400 (Lambda overwrites daily)
#
# Usage:
#   bash deploy/sync_site_to_s3.sh
#   bash deploy/sync_site_to_s3.sh --dry-run   (preview only)
#
# ⚠️  Cost: CloudFront invalidations free for first 1000 paths/month (we use 1 wildcard).
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Portable in-place sed. This script runs both locally (macOS / BSD sed, needs the
# empty '' suffix arg) AND in CI (GitHub Actions ubuntu / GNU sed, which rejects it).
# GNU sed answers --version; BSD sed errors. Use an array so the flag words expand
# correctly under set -u. (Added with the CI-gated site deploy — #393.)
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(-i)       # GNU
else
  SED_INPLACE=(-i '')    # BSD/macOS
fi

# ─────────────────────────────────────────────────────────────────────────────
# CLOBBER GUARD (Coherence Program Phase 3). sync_site_to_s3.sh pushes the WHOLE
# site/ tree, so syncing from a branch that's MISSING site/ commits which are
# already on origin/main silently OVERWRITES live site content. This is exactly
# what bit us 2026-06-28: parallel feature branches cut from clean main, each
# full-package sync clobbering the last. Block when origin/main has site/ commits
# this checkout lacks. Fail-soft (offline / not-a-git-repo → skip, never break a
# deploy). Override with ALLOW_STALE_SITE=1 for an intentional rollback.
if [ "${1:-}" != "--dry-run" ] && [ "${ALLOW_STALE_SITE:-0}" != "1" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  if git fetch origin main --quiet 2>/dev/null; then
    _missing="$(git rev-list --count HEAD..origin/main -- site/ 2>/dev/null || echo 0)"
    if [ "${_missing:-0}" -gt 0 ]; then
      echo "⛔ CLOBBER GUARD: origin/main has $_missing site/ commit(s) this checkout doesn't." >&2
      echo "   Syncing now would OVERWRITE live site changes you don't have locally." >&2
      echo "   Fix: git merge origin/main  (or rebase), then re-run." >&2
      echo "   Override (intentional rollback only): ALLOW_STALE_SITE=1 bash deploy/sync_site_to_s3.sh" >&2
      exit 1
    fi
    echo "→ clobber guard: site/ is up to date with origin/main ✓"
  else
    echo "  ⚠️  clobber guard skipped (couldn't fetch origin/main — offline?)"
  fi
fi

# Regenerate rss.xml from the live published chronicle (best-effort — never block a
# deploy if offline). Keeps the feed's pubDates/lastBuildDate correct on every sync.
if [ "${1:-}" != "--dry-run" ]; then
  python3 "$(dirname "$0")/../scripts/v4_build_rss.py" || echo "  ⚠️  rss build skipped (offline?) — keeping existing site/rss.xml"
  # #733: regenerate sitemap.xml (every published post URL) + inject the dated post
  # link-list into the chronicle hub's <noscript> — so crawlers/LLMs/no-JS visitors
  # see the posts. Best-effort; keeps the existing sitemap if the live posts feed is
  # unreachable. Was NOT wired in before, so the sitemap silently drifted post-less.
  python3 "$(dirname "$0")/../scripts/v4_build_sitemap.py" || echo "  ⚠️  sitemap build skipped (offline?) — keeping existing site/sitemap.xml"
  # #788: bake the cockpit's static proof (character level + pillars + as-of stamp)
  # into /now/'s <noscript> — the #729/#730 treatment for the flagship page. Best-
  # effort; keeps the last baked block if the live API is unreachable.
  python3 "$(dirname "$0")/../scripts/v4_build_cockpit_proof.py" || echo "  ⚠️  cockpit proof skipped (offline?) — keeping existing baked block"
  # #498: data_sources.json is GENERATED from lambdas/source_registry.py — never hand-edit.
  python3 "$(dirname "$0")/../scripts/v4_build_data_sources.py" || echo "  ⚠️  data_sources build skipped — keeping existing site/data/data_sources.json"
  # #544: /method/registry/ is GENERATED from lambdas/methods_registry.py — never hand-edit.
  python3 "$(dirname "$0")/../scripts/v4_build_methods.py" || echo "  ⚠️  methods registry build skipped — keeping existing site/method/registry/index.html"
  # #586/ADR-106: portrait_data.js is GENERATED from config/portraits/ (signed recipes
  # only) — never hand-edit. Validation failure BLOCKS the sync (a bad recipe must not ship).
  python3 "$(dirname "$0")/../scripts/v4_build_portraits.py"
  # #593/ADR-106: the signed portraits also travel off-site as email-ready PNGs under
  # site/assets/portraits/ (one source of truth with the site SVG). Re-render so a recipe
  # edit propagates here in the same sync; CI's parity guard fails if this is skipped.
  python3 "$(dirname "$0")/../scripts/render_portraits.py" || echo "  ⚠️  portrait PNG render skipped — keeping existing site/assets/portraits/"
fi

BUCKET="matthew-life-platform"
SITE_DIR="$(cd "$(dirname "$0")/.." && pwd)/site"
S3_PREFIX="site"
REGION="us-west-2"
DRY_RUN="${1:-}"

# ER-06 — PII / guardrail gate (FAIL-CLOSED, before any publish). Scans the
# static site for blocked-vice terms, structural PII, and (if a local/CI denylist
# is present) guarded personal literals. A hit aborts the sync. set -e propagates
# the non-zero exit; the explicit message makes the block unmissable.
echo "→ PII surface guard (ER-06)…"
if ! python3 "$(dirname "$0")/pii_surface_guard.py" "$SITE_DIR"; then
  echo "❌ PII surface guard FAILED — a guarded string or PII is on the public surface. Publish blocked." >&2
  exit 1
fi

# #377 — JS parse gate (FAIL-CLOSED). One ES module (evidence.js, ~3k lines) renders
# all 44 archive pages; it's edited nearly every site session and nothing else validates
# it, so a one-character typo would break every Data/Protocols/Method page at once.
# Parses each site JS module (ms each) and aborts the publish on the first failure,
# naming the file. MUST use `--input-type=module` via stdin: plain `node --check <file>`
# with auto-detection SILENTLY MISSES real errors in ES-module files (verified — a
# dangling operator passed file-mode but is caught here). Module mode is a safe superset
# for the non-module legacy scripts too (all 27 site JS files parse clean). GitHub-hosted
# runners ship Node, so this runs on the CI path (deploy_site.sh → here); if node is
# genuinely absent we warn loudly rather than wedge every deploy on a missing toolchain.
if command -v node >/dev/null 2>&1; then
  echo "→ JS parse gate (#377)…"
  _js_fail=0
  while IFS= read -r _jsf; do
    if ! node --check --input-type=module <"$_jsf" 2>/tmp/jsparse_err; then
      echo "❌ JS PARSE ERROR — publish blocked. Offending file:" >&2
      echo "   ${_jsf#"$SITE_DIR"/}" >&2
      sed 's/^/     /' /tmp/jsparse_err >&2
      _js_fail=1
      break
    fi
  done < <(find "$SITE_DIR" -name '*.js' -not -path '*/node_modules/*')
  [ "$_js_fail" -eq 0 ] || exit 1
  echo "   ✓ all site JS modules parse clean"
else
  echo "⚠️  node not found — JS parse gate SKIPPED (install Node to enable the #377 gate)." >&2
fi

# Find CloudFront distribution ID for averagejoematt.com
CF_DIST_ID=$(aws cloudformation describe-stacks \
  --stack-name LifePlatformWeb \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue" \
  --output text 2>/dev/null || echo "")

[[ -z "$CF_DIST_ID" ]] && echo "⚠️  CloudFront distribution ID not found — skipping invalidation."

if [[ "$DRY_RUN" == "--dry-run" ]]; then
  echo "DRY RUN — showing what would be synced:"
  aws s3 sync "$SITE_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
    --exclude "data/*" \
    --exclude ".git/*" \
    --exclude ".DS_Store" \
    --dryrun \
    --region "$REGION"
  echo "(dry run complete, no changes made)"
  exit 0
fi

# ── Phase 1: Build content-hashed assets in temp directory ─────────────────
echo "=== Building content-hashed assets ==="
BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT
cp -r "$SITE_DIR"/* "$BUILD_DIR/"

# Content-hash CSS/JS across the FULL module graph (leaves first) and rewrite every
# reference — HTML <link>/<script> AND intra-module `import ... from "/assets/js/*"`.
# Rewriting only HTML (the old behavior) left module imports on unhashed, mutable,
# 24h-cached URLs, so a fresh entry module could pair with a stale cached dependency
# and throw at load — rendering only the static shell (the "frozen page" bug,
# 2026-07-03). Full-graph hashing makes every asset URL immutable → no version skew.
# /legacy assets stay unhashed (served verbatim); the helper skips legacy/.
python3 "$(dirname "$0")/hash_site_assets.py" "$BUILD_DIR"

# ── Build stamp (apples-to-apples QA) ─────────────────────────────────────────
# Stamp every deploy with the git short-SHA + UTC time so we always know which build
# is live: (1) /version.json — the machine-readable source of truth; (2) <meta name=
# "build"> on every v4 page (View-Source / DevTools); (3) roll the service-worker cache
# name so a stale page can't survive a reload (the real cause of "v451 vs v452"). The
# muted visible stamp on the Cockpit + Evidence footers reads the meta tag (cockpit.js /
# evidence.js).
# OVERRIDE_BUILD_SHA lets an intentional rollback (deploy/rollback_site.sh, #418)
# stamp version.json + the <meta build> tag with the RESTORED build's short-SHA
# instead of the working-tree HEAD, so /version.json truthfully returns to the
# prior build. Normal deploys leave it unset and stamp HEAD as before.
BUILD_SHA="${OVERRIDE_BUILD_SHA:-$(git -C "$(dirname "$0")/.." rev-parse --short HEAD 2>/dev/null || echo unknown)}"
BUILD_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "→ Build stamp: $BUILD_SHA · $BUILD_AT"
printf '{"build":"%s","deployed":"%s"}\n' "$BUILD_SHA" "$BUILD_AT" > "$BUILD_DIR/version.json"
find "$BUILD_DIR" -name "*.html" -not -path "*/legacy/*" -exec sed "${SED_INPLACE[@]}" "s#</head>#<meta name=\"build\" content=\"$BUILD_SHA $BUILD_AT\"></head>#" {} +
sed "${SED_INPLACE[@]}" -E "s/const VERSION = \"[^\"]*\";/const VERSION = \"$BUILD_SHA\";/" "$BUILD_DIR/sw.js"

echo ""
echo "=== Syncing to s3://$BUCKET/$S3_PREFIX/ ==="
echo ""

# ── Phase 2: Sync to S3 ───────────────────────────────────────────────────

# HTML pages — short TTL, references hashed asset filenames
echo "→ HTML files (max-age=300)..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*" \
  --include "*.html" \
  --cache-control "max-age=300, public" \
  --content-type "text/html; charset=utf-8" \
  --region "$REGION"

# Hashed CSS/JS — immutable 1-year cache (filename changes when content changes)
echo "→ Hashed CSS/JS (max-age=31536000, immutable)..."
aws s3 sync "$BUILD_DIR/assets/" "s3://$BUCKET/$S3_PREFIX/assets/" \
  --exclude "*" \
  --include "*.????????.css" \
  --include "*.????????.js" \
  --cache-control "max-age=31536000, public, immutable" \
  --region "$REGION"

# Original CSS/JS — 1-day cache (fallback for dynamic loads like countdown.js)
echo "→ Original CSS/JS (max-age=86400, fallback)..."
aws s3 sync "$BUILD_DIR/assets/" "s3://$BUCKET/$S3_PREFIX/assets/" \
  --exclude "*.????????.css" \
  --exclude "*.????????.js" \
  --exclude "*.map" \
  --cache-control "max-age=86400, public" \
  --region "$REGION"

# Data JSON — Lambda overwrites daily, 24h TTL is fine
echo "→ Data JSON (max-age=86400)..."
aws s3 sync "$BUILD_DIR/data/" "s3://$BUCKET/$S3_PREFIX/data/" \
  --cache-control "max-age=86400, public" \
  --content-type "application/json" \
  --region "$REGION" 2>/dev/null || true

# Everything else (images, fonts, etc.)
echo "→ Other files..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*.html" \
  --exclude "assets/*" \
  --exclude "data/*" \
  --exclude ".git/*" \
  --exclude ".DS_Store" \
  --exclude "*.webmanifest" \
  --exclude "sw.js" \
  --exclude "version.json" \
  --cache-control "max-age=3600, public" \
  --region "$REGION"

# PWA control files MUST NOT be long-cached: a stale manifest = silent install
# failure, and a service worker must always re-check for updates.
echo "→ PWA manifest + service worker (max-age=300, must-revalidate)..."
aws s3 sync "$BUILD_DIR/" "s3://$BUCKET/$S3_PREFIX/" \
  --exclude "*" \
  --include "*.webmanifest" \
  --include "sw.js" \
  --cache-control "max-age=300, must-revalidate, public" \
  --region "$REGION"

# version.json — the deploy fingerprint; never cache it, so QA is always apples-to-apples.
echo "→ version.json (no-cache)..."
aws s3 cp "$BUILD_DIR/version.json" "s3://$BUCKET/$S3_PREFIX/version.json" \
  --cache-control "no-cache, must-revalidate" \
  --content-type "application/json" \
  --region "$REGION"

echo ""
echo "✅ S3 sync complete."

# ── Phase 3: CloudFront invalidation ──────────────────────────────────────
if [[ -n "$CF_DIST_ID" ]]; then
  echo "Invalidating CloudFront distribution $CF_DIST_ID..."
  INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$CF_DIST_ID" \
    --paths "/*" \
    --query "Invalidation.Id" \
    --output text)
  echo "✅ Invalidation created: $INVALIDATION_ID (takes ~30s to propagate)"
fi

echo ""
echo "Site live at: https://averagejoematt.com"
