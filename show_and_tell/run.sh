#!/bin/bash
# show_and_tell/run.sh
# One-command Show & Tell PDF pipeline
#
# Usage:
#   ./run.sh              # full pipeline
#   ./run.sh --open       # full pipeline + open PDF in Preview
#   ./run.sh --skip-shots # skip screenshot capture (use existing screenshots)
#
# Prerequisites (first time only): bash setup.sh

set -e
cd "$(dirname "$0")"

# Activate the virtual environment (created by setup.sh)
if [ ! -d ".venv" ]; then
  echo "ERROR: Virtual environment not found. Run: bash setup.sh"
  exit 1
fi
source .venv/bin/activate

OPEN=""
SKIP_SHOTS=false
SKIP_REDACT=false

for arg in "$@"; do
  case $arg in
    --open)        OPEN="--open" ;;
    --skip-shots)  SKIP_SHOTS=true ;;
    --skip-redact) SKIP_REDACT=true ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Life Platform — Show & Tell PDF Pipeline   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Step 1: Update manifest from live docs
echo "Step 1/4 — Updating manifest from docs..."
python3 update_manifest.py
echo ""

# Step 2: Screenshots
if [ "$SKIP_SHOTS" = false ]; then
  echo "Step 2/4 — Capturing screenshots..."
  python3 capture_screenshots.py
  echo ""
  echo "⏸  Complete manual screenshots listed above, then press Enter to continue..."
  read -r
else
  echo "Step 2/4 — Skipping screenshot capture (--skip-shots)"
fi
echo ""

# Step 3: Redact
if [ "$SKIP_REDACT" = false ]; then
  echo "Step 3/4 — Applying redaction rules..."
  python3 redact_screenshots.py
else
  echo "Step 3/4 — Skipping redaction (--skip-redact, using existing processed/ files)"
fi
echo ""

# Step 4: Build PDF
echo "Step 4/4 — Building PDF..."
python3 build_pdf.py $OPEN
echo ""

echo "✅ Pipeline complete."
