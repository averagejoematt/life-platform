#!/usr/bin/env bash
# Fan the simulation corpus out one process per coach.
#
# Sequential, the whole corpus is ~570 turns at ~7s each — over an hour of
# wall-clock during which nothing can be inspected. Per-coach processes are
# independent (each assembles its own prompt, writes its own JSONL, carries its
# own spend cap) so the fan-out is safe and finishes in roughly one coach's time.
#
# The per-process cap is deliberately per-coach rather than shared: a shared
# counter across processes would need coordination, and a runaway in one coach
# should not be able to consume another coach's budget silently.
set -u
OUT="${1:?usage: coach_sim_runall.sh <output-dir> [max-usd-per-coach]}"
CAP="${2:-1.30}"
mkdir -p "$OUT"
HERE="$(cd "$(dirname "$0")" && pwd)"

COACHES="sleep_coach nutrition_coach mind_coach physical_coach explorer_coach pattern_coach career_coach eli_marsh"

for c in $COACHES; do
  python3 "$HERE/coach_chat_sim.py" --out "$OUT/$c.jsonl" --coaches "$c" --max-usd "$CAP" >"$OUT/$c.log" 2>&1 &
done
wait

echo "=== simulation complete ==="
for c in $COACHES; do
  n=$(wc -l <"$OUT/$c.jsonl" 2>/dev/null || echo 0)
  spend=$(grep -o '"total_usd": [0-9.]*' "$OUT/$c.log" 2>/dev/null | tail -1)
  echo "$c: $n conversations  $spend"
done
