#!/bin/bash
# ────────────────────────────────────────────────────────────────
# NAV SPACER SWEEP — Remove all per-page nav-height clearance
# 
# Context: components.js now injects a .nav-spacer div after the
# nav that provides var(--nav-height) of clearance. Pages no longer
# need calc(var(--nav-height) + ...) in their headers.
#
# Three patterns found across 37 files:
#   A) calc(var(--nav-height) + var(--space-XX)) → var(--space-XX)
#   B) margin-top:var(--nav-height) on ticker divs → remove
#   C) position:fixed; top:var(--nav-height) → KEEP (fixed elements below nav)
# ────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")/.."

echo "=== NAV SPACER SWEEP ==="
echo ""

# ── STEP 1: Fix earlier incorrect edits ──────────────────────
# Earlier session replaced calc(nav-height + space-X) with space-8
# instead of preserving the original space-X. Restore correct values.

echo "Step 1: Correcting earlier wrong edits..."

# Files where space-16 was wrongly changed to space-8
for f in \
  site/experiments/index.html \
  site/stack/index.html \
  site/protocols/index.html \
  site/glucose/index.html \
  site/sleep/index.html \
  site/platform/index.html \
  site/explorer/index.html; do
  sed -i '' 's/padding: var(--space-8) var(--page-padding) var(--space-12)/padding: var(--space-16) var(--page-padding) var(--space-12)/g' "$f"
  echo "  ✓ $f (space-8 → space-16)"
done

# challenges had space-12 wrongly changed to space-8
sed -i '' 's/padding: var(--space-8) var(--page-padding) var(--space-8)/padding: var(--space-12) var(--page-padding) var(--space-8)/g' site/challenges/index.html
echo "  ✓ site/challenges/index.html (space-8 → space-12)"

# benchmarks had space-20 wrongly changed to space-10
sed -i '' 's/padding: var(--space-10) var(--page-padding) var(--space-16)/padding: var(--space-20) var(--page-padding) var(--space-16)/g' site/benchmarks/index.html
echo "  ✓ site/benchmarks/index.html (space-10 → space-20)"

# Files where responsive space-10 was wrongly changed to space-6
for f in \
  site/supplements/index.html \
  site/habits/index.html \
  site/intelligence/index.html; do
  # Desktop: space-8 → space-16
  sed -i '' 's/padding: var(--space-8) var(--page-padding) var(--space-12)/padding: var(--space-16) var(--page-padding) var(--space-12)/g' "$f"
  # Mobile: space-6 → space-10
  sed -i '' 's/padding: var(--space-6) var(--page-padding-sm) var(--space-8)/padding: var(--space-10) var(--page-padding-sm) var(--space-8)/g' "$f"
  echo "  ✓ $f (space-8→16, space-6→10)"
done

echo ""

# ── STEP 2: Pattern A — strip calc() wrapper globally ────────
# calc(var(--nav-height) + var(--space-XX)) → var(--space-XX)

echo "Step 2: Global sweep — Pattern A (calc wrapper removal)..."

patternA_count=0
for f in $(find site -name "index.html"); do
  if grep -q "calc(var(--nav-height)" "$f" 2>/dev/null; then
    sed -i '' 's/calc(var(--nav-height) + var(--space-\([0-9]*\)))/var(--space-\1)/g' "$f"
    echo "  ✓ $f"
    patternA_count=$((patternA_count + 1))
  fi
done
echo "  Pattern A: $patternA_count files cleaned."
echo ""

# ── STEP 3: Pattern B — remove ticker margin-top ─────────────
# margin-top:var(--nav-height) on ticker divs → spacer handles it

echo "Step 3: Pattern B (ticker margin-top removal)..."

patternB_count=0
for f in $(find site -name "index.html"); do
  if grep -q "margin-top:var(--nav-height)" "$f" 2>/dev/null; then
    sed -i '' 's/margin-top:var(--nav-height)/margin-top:0/g' "$f"
    echo "  ✓ $f"
    patternB_count=$((patternB_count + 1))
  fi
done
echo "  Pattern B: $patternB_count files cleaned."
echo ""

# ── STEP 4: Pattern C — leave fixed-position top references ──
# top:var(--nav-height) on fixed elements (reading progress bar)
# These are intentional — element is positioned below the nav.

echo "Step 4: Pattern C audit (fixed-position top — should KEEP)..."

patternC_count=0
for f in $(find site -name "index.html"); do
  if grep -q "top:var(--nav-height)" "$f" 2>/dev/null; then
    echo "  ℹ KEPT: $f (fixed element positioned below nav)"
    patternC_count=$((patternC_count + 1))
  fi
done
echo "  Pattern C: $patternC_count files left intentionally."
echo ""

# ── STEP 5: Verification scan ────────────────────────────────

echo "Step 5: Verification scan..."

leftover=0
for f in $(find site -name "index.html"); do
  nh=$(grep -c "nav-height" "$f" 2>/dev/null || echo "0")
  if [ "$nh" -gt 0 ]; then
    # Check if remaining refs are all Pattern C (acceptable)
    calcRefs=$(grep -c "calc(var(--nav-height)" "$f" 2>/dev/null || echo "0")
    marginRefs=$(grep -c "margin-top:var(--nav-height)" "$f" 2>/dev/null || echo "0")
    badRefs=$((calcRefs + marginRefs))
    if [ "$badRefs" -gt 0 ]; then
      echo "  ⚠ REMAINING: $f ($badRefs bad refs of $nh total)"
      grep -n "nav-height" "$f" 2>/dev/null | head -5
      leftover=$((leftover + 1))
    fi
  fi
done

if [ "$leftover" -eq 0 ]; then
  echo "  ✅ All clear — no problematic nav-height references remain."
else
  echo ""
  echo "  ⚠ $leftover files still have problematic nav-height references."
fi

echo ""
echo "=== SWEEP COMPLETE ==="
echo ""
echo "Deploy:"
echo "  aws s3 sync site/ s3://matthew-life-platform/site/ --exclude '*.DS_Store' --exclude '.git/*'"
echo "  aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*'"
