#!/usr/bin/env bash
# smoke_test_site.sh — Post-deploy verification for averagejoematt.com (v4 "The Measured Life")
#
# Verifies the three-door v4 site (ADR-071): Cockpit (/now/), Story (/story/),
# Evidence (/data/), over the unchanged read-only engine. Checks live pages (200),
# legacy v3 URLs (301 → v4), assets, API endpoints + freshness, content markers,
# cache headers, and stale-copy. Run after `bash deploy/sync_site_to_s3.sh`.
#
# Usage:
#   bash deploy/smoke_test_site.sh           # full check
#   bash deploy/smoke_test_site.sh --quick   # HTTP-only, skip content checks
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BASE="https://averagejoematt.com"
QUICK="${1:-}"
PASS=0
FAIL=0

check_status() {
  local label="$1"
  local url="$2"
  local expected="${3:-200}"
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url")
  if [[ "$status" == "$expected" ]]; then
    echo "  ✅ $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $label — expected $expected, got $status ($url)"
    FAIL=$((FAIL + 1))
  fi
}

check_header() {
  local label="$1"
  local url="$2"
  local header_pattern="$3"
  local headers
  headers=$(curl -s -I --max-time 10 "$url")
  if echo "$headers" | grep -qi "$header_pattern"; then
    echo "  ✅ $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $label — header not found: $header_pattern"
    FAIL=$((FAIL + 1))
  fi
}

echo "============================================================"
echo "averagejoematt.com — v4 post-deploy smoke tests"
echo "$(date)"
echo "============================================================"
echo ""

# ── v4 pages (HTTP 200) ───────────────────────────────────────────────────────
echo "── v4 pages (HTTP 200) ───────────────────────────────────"
check_status "Home"                 "$BASE/"
check_status "Cockpit (/now/)"      "$BASE/now/"
check_status "Story hub"            "$BASE/story/"
check_status "Evidence hub"         "$BASE/data/"
check_status "Subscribe"            "$BASE/subscribe/"
# Story sub-pages
check_status "Story · chronicle"    "$BASE/story/chronicle/"
check_status "Story · journal"      "$BASE/story/journal/"
check_status "Coaching · lab-notes" "$BASE/coaching/lab-notes/"
check_status "Story · timeline"     "$BASE/story/timeline/"
check_status "Story · about"        "$BASE/story/about/"
# Evidence topics (sample across groups)
check_status "Evidence · vitals"    "$BASE/data/vitals/"
check_status "Evidence · glucose"   "$BASE/data/glucose/"
check_status "Evidence · sleep"     "$BASE/data/sleep/"
check_status "Evidence · labs"      "$BASE/data/labs/"
check_status "Evidence · board"     "$BASE/method/board/"
check_status "Evidence · platform"  "$BASE/method/platform/"
check_status "Evidence · data"      "$BASE/method/data/"
check_status "Evidence · pipeline"  "$BASE/method/pipeline/"
check_status "404 page"             "$BASE/nonexistent-page-xyz" "404"
check_status "www redirect"         "https://www.averagejoematt.com/" "200"
echo ""

# ── Legacy v3 URLs → 301 (the v4-redirects CloudFront fn) ──────────────────────
echo "── Legacy v3 URLs (expect 301 → v4) ─────────────────────"
check_status "/live/ → 301"         "$BASE/live/"        "301"
check_status "/chronicle/ → 301"    "$BASE/chronicle/"   "301"
check_status "/journal/ → 301"      "$BASE/journal/"     "301"
check_status "/character/ → 301"    "$BASE/character/"   "301"
check_status "/glucose/ → 301"      "$BASE/glucose/"     "301"
check_status "/sleep/ → 301"        "$BASE/sleep/"       "301"
check_status "/habits/ → 301"       "$BASE/habits/"      "301"
check_status "/evidence/ → 301"     "$BASE/evidence/"    "301"
check_status "/board/ → 301"        "$BASE/board/"       "301"
check_status "/platform/ → 301"     "$BASE/platform/"    "301"
echo ""

# ── Static assets (non-hashed fallbacks + feeds) ───────────────────────────────
echo "── Static assets ─────────────────────────────────────────"
check_status "tokens.css"           "$BASE/assets/css/tokens.css"
check_status "cockpit.js"           "$BASE/assets/js/cockpit.js"
check_status "story.js"             "$BASE/assets/js/story.js"
check_status "evidence.js"          "$BASE/assets/js/evidence.js"
check_status "RSS feed"             "$BASE/rss.xml"
check_status "feed.xml alias"       "$BASE/feed.xml"
check_status "Sitemap"              "$BASE/sitemap.xml"
echo ""

# ── API endpoints (HTTP 200) ───────────────────────────────────────────────────
echo "── API endpoints ─────────────────────────────────────────"
check_status "/api/vitals"          "$BASE/api/vitals"
check_status "/api/journey"         "$BASE/api/journey"
check_status "/api/character"       "$BASE/api/character"
check_status "/api/pulse"           "$BASE/api/pulse"
check_status "/api/snapshot"        "$BASE/api/snapshot"
check_status "/api/source_freshness" "$BASE/api/source_freshness"
check_status "/api/platform_stats"  "$BASE/api/platform_stats"
echo ""

if [[ "$QUICK" != "--quick" ]]; then
  echo "── Content markers (v4 structure) ───────────────────────"
  check_body_contains() {
    local label="$1" file="$2" needle="$3"
    if grep -q "$needle" "$file"; then echo "  ✅ $label"; PASS=$((PASS+1)); else echo "  ❌ $label — expected to find: $needle"; FAIL=$((FAIL+1)); fi
  }
  check_body_not_contains() {
    local label="$1" file="$2" needle="$3"
    if grep -qi "$needle" "$file"; then echo "  ❌ $label — unexpectedly found: $needle"; FAIL=$((FAIL+1)); else echo "  ✅ $label"; PASS=$((PASS+1)); fi
  }

  HOME_FILE=$(mktemp);   curl -s --max-time 15 "$BASE/" > "$HOME_FILE"
  NOW_FILE=$(mktemp);    curl -s --max-time 15 "$BASE/now/" > "$NOW_FILE"
  STORY_FILE=$(mktemp);  curl -s --max-time 15 "$BASE/story/" > "$STORY_FILE"
  EVID_FILE=$(mktemp);   curl -s --max-time 15 "$BASE/data/" > "$EVID_FILE"
  PIPE_FILE=$(mktemp);   curl -s --max-time 15 "$BASE/method/pipeline/" > "$PIPE_FILE"
  SUB_FILE=$(mktemp);    curl -s --max-time 15 "$BASE/subscribe/" > "$SUB_FILE"
  trap 'rm -f "$HOME_FILE" "$NOW_FILE" "$STORY_FILE" "$EVID_FILE" "$PIPE_FILE" "$SUB_FILE"' EXIT

  # Home: cinematic landing + the three doors + interactive constellation
  check_body_contains "Home: constellation hero"      "$HOME_FILE"  'class="constellation"'
  check_body_contains "Home: door · the cockpit"      "$HOME_FILE"  'the cockpit'
  check_body_contains "Home: door · the story"        "$HOME_FILE"  'the story'
  check_body_contains "Home: door · the data"         "$HOME_FILE"  'the data'
  check_body_contains "Home: door · the protocols"    "$HOME_FILE"  'the protocols'
  # Cockpit: live data wiring
  check_body_contains "Cockpit: data-bind targets"    "$NOW_FILE"   'data-bind'
  check_body_contains "Cockpit: loads cockpit.js module" "$NOW_FILE" 'assets/js/cockpit'
  # Story hub: the writing surfaces
  check_body_contains "Story: chronicle linked"       "$STORY_FILE" 'chronicle'
  check_body_contains "Story: journal linked"         "$STORY_FILE" 'journal'
  # Evidence: registry + readout shell + the new live Pipeline-status topic
  check_body_contains "Evidence: registry embedded"   "$EVID_FILE"  '__EVIDENCE_REGISTRY__'
  check_body_contains "Evidence: readout mount"       "$EVID_FILE"  'data-readout'
  check_body_contains "Method: Pipeline-status topic" "$PIPE_FILE" 'Pipeline status'
  check_body_contains "Pipeline page: fetches /api/source_freshness" "$PIPE_FILE" 'source_freshness'
  # Subscribe form present
  check_body_contains "Subscribe: form present"       "$SUB_FILE"   'subscribe'
  # Stale-copy guard (would have caught the v3 'Week 1 ships after April 1' regression)
  check_body_not_contains "Home: no stale copy"       "$HOME_FILE"  'coming soon\|launching april\|lorem ipsum\|TODO'
  check_body_not_contains "Cockpit: no stale copy"    "$NOW_FILE"   'coming soon\|launching april\|lorem ipsum\|TODO'
  echo ""

  # ── Cache headers ────────────────────────────────────────────────────────────
  echo "── Cache headers ─────────────────────────────────────────"
  check_header "HTML page: short TTL (max-age=300)"  "$BASE/story/"               "cache-control:.*max-age=300"
  check_header "CSS: long TTL"                        "$BASE/assets/css/tokens.css" "cache-control:.*max-age="
  check_header "CloudFront serving"                  "$BASE/"                      "x-cache"
  echo ""

  # ── API data quality ─────────────────────────────────────────────────────────
  echo "── API data quality ──────────────────────────────────────"
  if curl -s --max-time 10 "$BASE/api/vitals" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('vitals',{}).get('weight_lbs') is not None" 2>/dev/null; then
    echo "  ✅ /api/vitals: weight_lbs present"; PASS=$((PASS + 1))
  else
    echo "  ❌ /api/vitals: missing weight_lbs"; FAIL=$((FAIL + 1))
  fi
  if curl -s --max-time 10 "$BASE/api/source_freshness" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d.get('sources'),list) and len(d['sources'])>0" 2>/dev/null; then
    echo "  ✅ /api/source_freshness: sources present"; PASS=$((PASS + 1))
  else
    echo "  ❌ /api/source_freshness: no sources array"; FAIL=$((FAIL + 1))
  fi
  if curl -s --max-time 10 "$BASE/api/character" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d.get('pillars'),list) and len(d['pillars'])==7" 2>/dev/null; then
    echo "  ✅ /api/character: 7 pillars present"; PASS=$((PASS + 1))
  else
    echo "  ❌ /api/character: pillars missing/incomplete"; FAIL=$((FAIL + 1))
  fi
  echo ""
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "============================================================"
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -eq 0 ]]; then
  echo "✅ All checks passed."
else
  echo "❌ $FAIL check(s) FAILED — do not consider this deploy complete."
fi
echo "============================================================"

[[ $FAIL -eq 0 ]] || exit 1
