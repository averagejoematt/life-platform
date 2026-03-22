#!/usr/bin/env bash
# smoke_test_site.sh — Comprehensive post-deploy verification for averagejoematt.com
#
# Checks every page, API endpoint, CSS/JS assets, and content signals.
# Run after deploy_site_all.sh.
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

check_contains() {
  local label="$1"
  local url="$2"
  local needle="$3"
  local body
  body=$(curl -s --max-time 10 "$url")
  if echo "$body" | grep -q "$needle"; then
    echo "  ✅ $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $label — expected to find: $needle"
    echo "       URL: $url"
    FAIL=$((FAIL + 1))
  fi
}

check_not_contains() {
  local label="$1"
  local url="$2"
  local needle="$3"
  local body
  body=$(curl -s --max-time 10 "$url")
  if echo "$body" | grep -q "$needle"; then
    echo "  ❌ $label — unexpectedly found: $needle"
    echo "       URL: $url"
    FAIL=$((FAIL + 1))
  else
    echo "  ✅ $label"
    PASS=$((PASS + 1))
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
echo "averagejoematt.com — Post-deploy smoke tests"
echo "$(date)"
echo "============================================================"
echo ""

# ── HTTP 200 on every page ────────────────────────────────────────────────────
echo "── Static pages (HTTP 200) ──────────────────────────────"
check_status "Homepage"             "$BASE/"
check_status "Story"                "$BASE/story/"
check_status "Live"                 "$BASE/live/"
check_status "Journal"             "$BASE/journal/"
check_status "Journal archive"     "$BASE/journal/archive/"
check_status "Week"                 "$BASE/week/"
check_status "About"                "$BASE/about/"
check_status "Platform"             "$BASE/platform/"
check_status "Character"            "$BASE/character/"
check_status "Habits"               "$BASE/habits/"
check_status "Achievements"         "$BASE/achievements/"
check_status "Discoveries"          "$BASE/discoveries/"
check_status "Results"              "$BASE/results/"
check_status "Explorer"             "$BASE/explorer/"
check_status "Experiments"          "$BASE/experiments/"
check_status "Protocols"            "$BASE/protocols/"
check_status "Intelligence"         "$BASE/intelligence/"
check_status "Accountability"       "$BASE/accountability/"
check_status "Methodology"          "$BASE/methodology/"
check_status "Progress"             "$BASE/progress/"
check_status "Benchmarks"           "$BASE/benchmarks/"
check_status "Supplements"          "$BASE/supplements/"
check_status "Cost"                 "$BASE/cost/"
check_status "Tools"                "$BASE/tools/"
check_status "Ask"                  "$BASE/ask/"
check_status "Board"                "$BASE/board/"
check_status "Data"                 "$BASE/data/"
check_status "Start"                "$BASE/start/"
check_status "Subscribe"            "$BASE/subscribe/"
check_status "Privacy"              "$BASE/privacy/"
check_status "Glucose"              "$BASE/glucose/"
check_status "Sleep"                "$BASE/sleep/"
check_status "Biology (noindex)"    "$BASE/biology/"
check_status "404 page"             "$BASE/nonexistent-page-xyz" "404"
check_status "www redirect"         "https://www.averagejoematt.com/" "200"
echo ""

# ── Static assets ─────────────────────────────────────────────────────────────
echo "── Static assets ─────────────────────────────────────────"
check_status "tokens.css"           "$BASE/assets/css/tokens.css"
check_status "base.css"             "$BASE/assets/css/base.css"
check_status "nav.js"               "$BASE/assets/js/nav.js"
check_status "reveal.js"            "$BASE/assets/js/reveal.js"
check_status "og-image.png"         "$BASE/assets/images/og-image.png"
check_status "favicon.svg"          "$BASE/assets/icons/favicon.svg"
check_status "RSS feed"             "$BASE/rss.xml"
check_status "Sitemap"              "$BASE/sitemap.xml"
echo ""

# ── API endpoints ─────────────────────────────────────────────────────────────
echo "── API endpoints ─────────────────────────────────────────"
check_status "/api/vitals"          "$BASE/api/vitals"
check_status "/api/journey"         "$BASE/api/journey"
check_status "/api/character"       "$BASE/api/character"
check_status "/api/habits"          "$BASE/api/habits"
check_status "/api/supplements"     "$BASE/api/supplements"
echo ""

if [[ "$QUICK" != "--quick" ]]; then
  # ── Content checks ──────────────────────────────────────────────────────────
  echo "── Content checks (HTML structure) ──────────────────────"


  _tmpfile=$(mktemp)
  trap 'rm -f "$_tmpfile"' EXIT
  check_body_contains()  {
    local label="$1" url_key="$2" needle="$3"
    if grep -q "$needle" "$url_key"; then echo "  ✅ $label"; PASS=$((PASS+1)); else echo "  ❌ $label — expected to find: $needle"; FAIL=$((FAIL+1)); fi
  }
  check_body_not_contains() {
    local label="$1" url_key="$2" needle="$3"
    if grep -q "$needle" "$url_key"; then echo "  ❌ $label — unexpectedly found: $needle"; FAIL=$((FAIL+1)); else echo "  ✅ $label"; PASS=$((PASS+1)); fi
  }
  # Write each page body to a temp file for grep (avoids large-variable piping issues)
  HOMEPAGE_FILE=$(mktemp); curl -s --max-time 15 "$BASE/" > "$HOMEPAGE_FILE"
  STORY_FILE=$(mktemp);    curl -s --max-time 15 "$BASE/story/" > "$STORY_FILE"
  PLATFORM_FILE=$(mktemp); curl -s --max-time 15 "$BASE/platform/" > "$PLATFORM_FILE"
  SUBSCRIBE_FILE=$(mktemp); curl -s --max-time 15 "$BASE/subscribe/" > "$SUBSCRIBE_FILE"
  SITEMAP_FILE=$(mktemp);  curl -s --max-time 15 "$BASE/sitemap.xml" > "$SITEMAP_FILE"
  CSS_FILE=$(mktemp);      curl -s --max-time 15 "$BASE/assets/css/base.css" > "$CSS_FILE"
  trap 'rm -f "$HOMEPAGE_FILE" "$STORY_FILE" "$PLATFORM_FILE" "$SUBSCRIBE_FILE" "$SITEMAP_FILE" "$CSS_FILE"' EXIT

  # ── FOUC guard: overlay must be hidden before external CSS loads ─────────────
  check_body_contains     "Story: FOUC guard in <head>"      "$STORY_FILE"    'nav-overlay{display:none}'
  check_body_contains     "Homepage: FOUC guard in <head>"   "$HOMEPAGE_FILE" 'nav-overlay{display:none}'
  check_body_contains     "Platform: FOUC guard in <head>"   "$PLATFORM_FILE" 'nav-overlay{display:none}'

  # ── Nav overlay: present but not open on load ─────────────────────────────
  check_body_contains     "Story: nav-overlay present"       "$STORY_FILE"    'class="nav-overlay"'
  check_body_not_contains "Story: overlay NOT open on load"  "$STORY_FILE"    'class="nav-overlay is-open"'
  check_body_contains     "Story: base.css linked"           "$STORY_FILE"    '/assets/css/base.css'
  check_body_contains     "Story: nav.js linked"             "$STORY_FILE"    '/assets/js/nav.js'

  # ── Nav version: Sprint 11 (Explore replaces About) ──────────────────────
  check_body_contains     "Story: nav has Explore link"      "$STORY_FILE"    'href="/start/"'
  check_body_not_contains "Story: About removed from top nav" "$STORY_FILE"   'class="nav__link">About'

  # ── Homepage links ────────────────────────────────────────────────────────
  check_body_contains     "Homepage: /start/ linked"         "$HOMEPAGE_FILE" 'href="/start/"'
  check_body_contains     "Homepage: /glucose/ linked"       "$HOMEPAGE_FILE" 'href="/glucose/"'
  check_body_contains     "Homepage: /sleep/ linked"         "$HOMEPAGE_FILE" 'href="/sleep/"'
  check_body_contains     "Homepage: accountability quote"   "$HOMEPAGE_FILE" 'accountability without witnesses'
  check_body_contains     "Subscribe page: form or link"     "$SUBSCRIBE_FILE" 'subscribe'

  # ── Footer completeness (Sprint 9+10+11 pages) ────────────────────────────
  check_body_contains     "Story footer: /habits/ link"      "$STORY_FILE"    'href="/habits/"'
  check_body_contains     "Story footer: /achievements/"     "$STORY_FILE"    'href="/achievements/"'
  check_body_contains     "Story footer: /glucose/"          "$STORY_FILE"    'href="/glucose/"'
  check_body_contains     "Story footer: /sleep/"            "$STORY_FILE"    'href="/sleep/"'
  check_body_not_contains "Story footer: no /biology/"       "$STORY_FILE"    'footer.*biology'

  # ── Sitemap ───────────────────────────────────────────────────────────────
  check_body_contains "Sitemap: /habits/"       "$SITEMAP_FILE" '/habits/'
  check_body_contains "Sitemap: /achievements/" "$SITEMAP_FILE" '/achievements/'
  check_body_contains "Sitemap: /start/"        "$SITEMAP_FILE" '/start/'
  check_body_contains "Sitemap: /glucose/"      "$SITEMAP_FILE" '/glucose/'
  check_body_contains "Sitemap: /sleep/"        "$SITEMAP_FILE" '/sleep/'

  # ── CSS critical rules ────────────────────────────────────────────────────
  check_body_contains "base.css: nav-overlay fixed"    "$CSS_FILE" 'position: fixed'
  check_body_contains "base.css: overlay display none" "$CSS_FILE" 'display: none'
  check_body_contains "base.css: overlay opacity 0"    "$CSS_FILE" 'opacity: 0'
  check_body_contains "base.css: is-open display flex" "$CSS_FILE" 'display: flex'
  check_body_contains "base.css: pulse uses green-500" "$CSS_FILE" 'c-green-500'
  check_body_contains "base.css: reading-path defined" "$CSS_FILE" '.reading-path'
  check_body_contains "base.css: has-badge defined"    "$CSS_FILE" 'has-badge'
  check_body_contains "base.css: footer-v2__grid"      "$CSS_FILE" '\.footer-v2__grid'
  check_body_contains "base.css: footer-v2__col"       "$CSS_FILE" '\.footer-v2__col'
  check_body_contains "base.css: challenge-bar"        "$CSS_FILE" '\.challenge-bar'
  check_body_contains "base.css: back-to-top"          "$CSS_FILE" '\.back-to-top'

  echo ""

  # ── Cache headers ────────────────────────────────────────────────────────────
  echo "── Cache headers ─────────────────────────────────────────"
  check_header "HTML page: short TTL (max-age=300)"     "$BASE/story/"                "cache-control:.*max-age=300"
  check_header "CSS: long TTL (max-age=86400)"          "$BASE/assets/css/base.css"   "cache-control:.*max-age=86400"
  check_header "CloudFront serving"                     "$BASE/"                       "x-cache"
  echo ""

  # ── API data quality ─────────────────────────────────────────────────────────
  echo "── API data quality ──────────────────────────────────────"
  VITALS=$(curl -s --max-time 10 "$BASE/api/vitals")
  if echo "$VITALS" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('vitals',{}).get('weight_lbs') is not None" 2>/dev/null; then
    echo "  ✅ /api/vitals: weight_lbs present"
    PASS=$((PASS + 1))
  else
    echo "  ❌ /api/vitals: missing weight_lbs"
    FAIL=$((FAIL + 1))
  fi

  JOURNEY=$(curl -s --max-time 10 "$BASE/api/journey")
  if echo "$JOURNEY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'start_weight' in str(d)" 2>/dev/null; then
    echo "  ✅ /api/journey: data present"
    PASS=$((PASS + 1))
  else
    echo "  ❌ /api/journey: unexpected response"
    FAIL=$((FAIL + 1))
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
