#!/bin/bash
# ============================================================
# Life Platform — Master Drop Folder Processor
# /Users/matthewwalker/Documents/Claude/life-platform/ingest/process_all_drops.sh
#
# Triggered by launchd WatchPaths on any of the drop folders.
# Scans each folder in turn and routes files to the correct backfill script.
#
# Drop folders watched (inside life-platform/datadrops/):
#   datadrops/habits_drop/       → backfill/backfill_chronicling.py
#   datadrops/macrofactor_drop/  → backfill/backfill_macrofactor.py or backfill_macrofactor_workouts.py
#   datadrops/apple_health_drop/ → backfill/backfill_apple_health.py
#
# Processed files are moved to <drop_folder>/processed/ on success.
# Failed files are left in place for retry.
# ============================================================

LIFE_PLATFORM="/Users/matthewwalker/Documents/Claude/life-platform"
BASE="$LIFE_PLATFORM/datadrops"
LOG="$LIFE_PLATFORM/ingest/ingest.log"
MAX_LOG_LINES=5000

# Rotate log if it gets large
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
    mv "$LOG" "${LOG%.log}_$(date +%Y%m%d).log"
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

process_file() {
    local csv="$1"
    local script="$2"
    local drop_dir
    drop_dir=$(dirname "$csv")
    local processed_dir="$drop_dir/processed"
    local filename
    filename=$(basename "$csv")

    mkdir -p "$processed_dir"
    log "  Running: python3 $script $csv"
    python3 "$script" "$csv" >> "$LOG" 2>&1

    if [ $? -eq 0 ]; then
        local dest="$processed_dir/${filename%.csv}_$(date '+%Y%m%d%H%M%S').csv"
        mv "$csv" "$dest"
        log "  ✓ Success → processed/$(basename "$dest")"
    else
        log "  ✗ ERROR — file left in drop folder for retry"
    fi
}

# ── 1. HABITS (Chronicling) ──────────────────────────────────────────────────
HABITS_DROP="$BASE/habits_drop"
for csv in "$HABITS_DROP"/*.csv; do
    [ -f "$csv" ] || continue
    log ""
    log "HABITS: Found $(basename "$csv")"
    process_file "$csv" "$LIFE_PLATFORM/backfill/backfill_chronicling.py"
done

# ── 2. MACROFACTOR (Nutrition + Workouts, auto-detected) ────────────────────
MF_DROP="$BASE/macrofactor_drop"
for csv in "$MF_DROP"/*.csv; do
    [ -f "$csv" ] || continue
    log ""
    log "MACROFACTOR: Found $(basename "$csv")"

    first_line=$(head -1 "$csv")
    if echo "$first_line" | grep -q "Food Name"; then
        log "  Detected: nutrition export"
        process_file "$csv" "$LIFE_PLATFORM/backfill/backfill_macrofactor.py"
    elif echo "$first_line" | grep -q "Exercise"; then
        log "  Detected: workout export"
        process_file "$csv" "$LIFE_PLATFORM/backfill/backfill_macrofactor_workouts.py"
    else
        log "  UNKNOWN format — skipping (headers: $first_line)"
    fi
done

# ── 3. APPLE HEALTH ──────────────────────────────────────────────────────────
AH_DROP="$BASE/apple_health_drop"
# Apple Health exports as a zip containing export.xml
for f in "$AH_DROP"/*.zip "$AH_DROP"/*.xml; do
    [ -f "$f" ] || continue
    log ""
    log "APPLE HEALTH: Found $(basename "$f")"

    ext="${f##*.}"
    if [ "$ext" = "zip" ]; then
        # Unzip export.xml into the apple_health_export folder, then run backfill
        log "  Unzipping to $BASE/apple_health_export/"
        unzip -o "$f" -d "$BASE/apple_health_export/" >> "$LOG" 2>&1
        if [ $? -ne 0 ]; then
            log "  ✗ Unzip failed — leaving in place"
            continue
        fi
    fi

    # Run the backfill against the exported XML
    XML="$BASE/apple_health_export/export.xml"
    if [ ! -f "$XML" ]; then
        log "  ✗ export.xml not found after unzip — check zip contents"
        continue
    fi

    log "  Running: python3 $LIFE_PLATFORM/backfill/backfill_apple_health.py $XML"
    python3 "$LIFE_PLATFORM/backfill/backfill_apple_health.py" "$XML" >> "$LOG" 2>&1

    if [ $? -eq 0 ]; then
        processed_dir="$AH_DROP/processed"
        mkdir -p "$processed_dir"
        dest="$processed_dir/$(basename "$f" .${ext})_$(date '+%Y%m%d%H%M%S').${ext}"
        mv "$f" "$dest"
        log "  ✓ Success → processed/$(basename "$dest")"
    else
        log "  ✗ ERROR — file left in drop folder for retry"
    fi
done

log ""
log "── Scan complete ──"
