#!/bin/bash
# backfill.command — Run a backfill script to reload data into DynamoDB
# Double-click in Finder to run, or: bash scripts/backfill.command

set -euo pipefail
cd "$(dirname "$0")/.."

echo "════════════════════════════════════════════"
echo "  Life Platform — Backfill Data"
echo "════════════════════════════════════════════"
echo ""
echo "Which source do you want to backfill?"
echo ""
echo "  1) Hevy        (strength workouts)"
echo "  2) Strava      (runs, rides, hikes)"
echo "  3) Whoop       (recovery, HRV, sleep)"
echo "  4) Withings    (weight, body composition)"
echo "  5) Todoist     (tasks completed)"
echo "  6) Apple Health (steps, heart rate)"
echo ""
read -p "Enter number (1-6): " CHOICE
echo ""

case "$CHOICE" in
  1) SCRIPT="backfill_hevy.py";        SOURCE="Hevy" ;;
  2) SCRIPT="backfill_strava.py";      SOURCE="Strava" ;;
  3) SCRIPT="backfill_whoop.py";       SOURCE="Whoop" ;;
  4) SCRIPT="backfill_withings.py";    SOURCE="Withings" ;;
  5) SCRIPT="backfill_todoist.py";     SOURCE="Todoist" ;;
  6) SCRIPT="backfill_apple_health.py"; SOURCE="Apple Health" ;;
  *) echo "Invalid choice. Exiting."; exit 1 ;;
esac

if [ ! -f "$SCRIPT" ]; then
  echo "❌ $SCRIPT not found in project root."
  read -p "Press Enter to close..."
  exit 1
fi

echo "▶ Starting $SOURCE backfill..."
echo "────────────────────────────────────────────"
python3 "$SCRIPT"
echo "────────────────────────────────────────────"
echo ""
echo "✅ $SOURCE backfill complete."
echo ""
read -p "Press Enter to close..."
