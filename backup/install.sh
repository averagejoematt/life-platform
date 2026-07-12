#!/bin/bash
# ============================================================
# Laptop-asset backup — Install / Uninstall LaunchAgent (#1026)
#
# Usage:
#   ./install.sh           Install and start the daily backup
#   ./install.sh uninstall Remove the agent
#   ./install.sh status    Show current status
#   ./install.sh run       Kick a backup run now (via launchctl)
# ============================================================

PLIST_NAME="com.matthewwalker.claude-memory-backup"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SRC_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
SCRIPT_DEST="$HOME/.local/bin/claude-memory-backup.sh"

case "${1:-install}" in
  install)
    echo "Installing laptop-asset backup agent..."
    # Stage the script OUTSIDE ~/Documents — launchd can't read the repo copy
    # (macOS TCC). Re-run install after editing backup/backup.sh in the repo.
    mkdir -p "$HOME/.local/bin"
    cp "$SRC_DIR/backup.sh" "$SCRIPT_DEST"
    chmod +x "$SCRIPT_DEST"
    cp "$PLIST_SRC" "$PLIST_DEST"
    launchctl unload "$PLIST_DEST" 2>/dev/null
    launchctl load "$PLIST_DEST"
    echo "  → loaded: $(launchctl list | grep "$PLIST_NAME" || echo NOT FOUND)"
    ;;
  uninstall)
    launchctl unload "$PLIST_DEST" 2>/dev/null
    rm -f "$PLIST_DEST"
    echo "Removed $PLIST_NAME"
    ;;
  status)
    launchctl list | grep "$PLIST_NAME" || echo "$PLIST_NAME not loaded"
    ;;
  run)
    launchctl kickstart -k "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || launchctl start "$PLIST_NAME"
    echo "Kicked $PLIST_NAME — tail datadrops/logs/backup-$(date +%Y%m%d).log"
    ;;
  *)
    echo "Usage: $0 [install|uninstall|status|run]"
    exit 1
    ;;
esac
