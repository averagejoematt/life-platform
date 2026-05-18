#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Patch MCP server for Habitify support (4 changes)
#
# 1. Add "habitify" to SOURCES list
# 2. Update default SOT: habits → habitify
# 3. Make query_chronicling() SOT-aware
# 4. Add "Supplements" to P40_GROUPS
#
# Run BEFORE deploy_mcp.sh
# ══════════════════════════════════════════════════════════════════════════════

cd ~/Documents/Claude/life-platform

echo "Patching mcp_server.py for Habitify support..."

# 1. Add "habitify" to SOURCES list
if grep -q '"habitify"' mcp_server.py; then
    echo "  ✓ SOURCES already includes 'habitify'"
else
    sed -i '' 's/"garmin"\]/"garmin", "habitify"]/' mcp_server.py
    echo "  ✓ Added 'habitify' to SOURCES"
fi

# 2. Update default SOT
if grep -q '"habits":      "habitify"' mcp_server.py; then
    echo "  ✓ Default SOT already set to habitify"
else
    sed -i '' 's/"habits":      "chronicling",   # P40 habit tracking — Chronicling/"habits":      "habitify",      # P40 habit tracking — Habitify (was: Chronicling)/' mcp_server.py
    echo "  ✓ Updated default SOT: habits → habitify"
fi

# 3. Make query_chronicling() SOT-aware
cat > /tmp/patch_chronicling.py << 'PYTHON'
with open("mcp_server.py", "r") as f:
    content = f.read()

old_func = '''def query_chronicling(start_date, end_date):
    """Query all chronicling items in date range. Returns list of day dicts."""
    return query_source("chronicling", start_date, end_date)'''

new_func = '''def query_chronicling(start_date, end_date):
    """Query habit items (habitify or chronicling) based on source-of-truth.
    Name kept for backward compatibility with all habit tool call sites."""
    source = get_sot("habits")
    return query_source(source, start_date, end_date)'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open("mcp_server.py", "w") as f:
        f.write(content)
    print("  ✓ query_chronicling() now uses get_sot('habits')")
elif 'get_sot("habits")' in content:
    print("  ✓ query_chronicling() already patched")
else:
    print("  ⚠ Could not find exact match — manual patch needed")
PYTHON
python3 /tmp/patch_chronicling.py

# 4. Add "Supplements" to P40_GROUPS
if grep -q '"Supplements"' mcp_server.py; then
    echo "  ✓ P40_GROUPS already includes 'Supplements'"
else
    sed -i '' 's/P40_GROUPS = \["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Wellbeing"\]/P40_GROUPS = ["Data", "Discipline", "Growth", "Hygiene", "Nutrition", "Performance", "Recovery", "Supplements", "Wellbeing"]/' mcp_server.py
    echo "  ✓ Added 'Supplements' to P40_GROUPS"
fi

echo ""
echo "Done! MCP server patched for Habitify."
