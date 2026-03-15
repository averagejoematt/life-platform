#!/bin/bash
# setup/run_calendar_sync.sh — Shell wrapper for launchd
#
# launchd doesn't inherit your shell environment, so this wrapper:
#   1. Finds the right Python3 (prefers Homebrew, falls back to system)
#   2. Sets required environment variables
#   3. Runs calendar_sync.py
#   4. Logs output with a timestamp header
#
# Called by: com.matthewwalker.calendar-sync.plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/calendar_sync.log"
PYTHON=""

# Find Python3 with boto3 available
for candidate in \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"; do
    if [ -x "$candidate" ] && "$candidate" -c "import boto3" 2>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S') ERROR: No Python3 with boto3 found" >> "$LOG_FILE"
    exit 1
fi

# Environment — matches what the Lambda uses
export AWS_REGION="us-west-2"
export TABLE_NAME="life-platform"
export USER_ID="matthew"
export LOOKBACK_DAYS="7"
export LOOKAHEAD_DAYS="14"

echo "" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%dT%H:%M:%S') ─── calendar_sync run ───" >> "$LOG_FILE"

"$PYTHON" "$SCRIPT_DIR/calendar_sync.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S') WARN: calendar_sync.py exited $EXIT_CODE" >> "$LOG_FILE"
fi

exit $EXIT_CODE
