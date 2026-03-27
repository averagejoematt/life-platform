#!/bin/bash
# warmup_lambdas.sh — Ping all homepage API endpoints to prevent cold starts
# Run this 5 minutes before launch: bash deploy/warmup_lambdas.sh
# Schedule via: echo "bash ~/Documents/Claude/life-platform/deploy/warmup_lambdas.sh" | at 11:55pm March 31

BASE="https://averagejoematt.com"
ENDPOINTS=(
  "/public_stats.json"
  "/api/habit_streaks"
  "/api/character_stats"
  "/api/vitals"
  "/api/correlations?featured=true&limit=3"
  "/api/current_challenge"
  "/api/subscriber_count"
)

echo "🔥 Warming up $(echo ${#ENDPOINTS[@]}) endpoints..."
for ep in "${ENDPOINTS[@]}"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}${ep}")
  echo "  ${STATUS} ${ep}"
  sleep 1
done
echo "✅ Warm-up complete"
