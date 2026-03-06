#!/bin/bash
# ============================================================
# Life Platform Ingest — Install / Uninstall LaunchAgent
#
# Run once to register the watcher with macOS launchd.
# After install, drop any supported file into a watched folder
# and processing starts automatically (no manual trigger needed).
#
# Usage:
#   ./install.sh          Install and start the watcher
#   ./install.sh stop     Stop the watcher (keeps plist installed)
#   ./install.sh uninstall Remove the watcher entirely
#   ./install.sh status   Show current status
# ============================================================

PLIST_NAME="com.matthewwalker.life-platform-ingest"
PLIST_SRC="$(dirname "$0")/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
OLD_PLIST="$HOME/Library/LaunchAgents/com.matthewwalker.macrofactor-drop.plist"

case "${1:-install}" in

  install)
    echo "Installing Life Platform ingest watcher..."

    # Disable the old per-source macrofactor watcher if present
    if launchctl list | grep -q "com.matthewwalker.macrofactor-drop" 2>/dev/null; then
        echo "  → Unloading old macrofactor-drop watcher..."
        launchctl unload "$OLD_PLIST" 2>/dev/null
    fi

    cp "$PLIST_SRC" "$PLIST_DEST"
    launchctl load "$PLIST_DEST"

    if launchctl list | grep -q "$PLIST_NAME"; then
        echo "  ✓ Installed and running: $PLIST_NAME"
        echo ""
        echo "Drop folders being watched:"
        echo "  ~/Documents/Claude/habits_drop/       → Chronicling habits CSV"
        echo "  ~/Documents/Claude/macrofactor_drop/  → MacroFactor nutrition or workout CSV"
        echo "  ~/Documents/Claude/apple_health_drop/ → Apple Health export.xml or .zip"
        echo ""
        echo "Log: $(dirname "$0")/ingest.log"
    else
        echo "  ✗ Install may have failed. Check: launchctl list | grep matthewwalker"
        exit 1
    fi
    ;;

  stop)
    echo "Stopping watcher..."
    launchctl unload "$PLIST_DEST" 2>/dev/null
    echo "  ✓ Stopped (plist still installed, run './install.sh install' to restart)"
    ;;

  uninstall)
    echo "Uninstalling watcher..."
    launchctl unload "$PLIST_DEST" 2>/dev/null
    rm -f "$PLIST_DEST"
    echo "  ✓ Uninstalled"
    ;;

  status)
    if launchctl list | grep -q "$PLIST_NAME"; then
        echo "  ✓ RUNNING: $PLIST_NAME"
    else
        echo "  ✗ NOT RUNNING: $PLIST_NAME"
    fi
    if launchctl list | grep -q "com.matthewwalker.macrofactor-drop"; then
        echo "  ⚠ OLD WATCHER STILL ACTIVE: com.matthewwalker.macrofactor-drop"
        echo "    Run './install.sh install' to migrate and disable it."
    fi
    ;;

  *)
    echo "Unknown command: $1"
    echo "Usage: $0 [install|stop|uninstall|status]"
    exit 1
    ;;
esac
