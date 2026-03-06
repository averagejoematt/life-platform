#!/bin/bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# Life Platform v2.33.0 — Expanded Cache Warmer (Step 3)
# ══════════════════════════════════════════════════════════════════════════════
# Adds 6 heavy tools to nightly warmer + inline cache-get for instant reads:
#   7. readiness_score (4 DDB queries)
#   8. health_risk_profile (3 DDB queries)
#   9. body_composition_snapshot (3 DDB queries)
#  10. energy_balance (parallel query)
#  11. day_type_analysis (2 parallel queries)
#  12. movement_score (2 parallel queries)
#
# Cost impact: ~$0 (runs within existing warmer Lambda invocation)
# Expected warmer time: 60-90s → 90-140s (well within 300s timeout)
# ══════════════════════════════════════════════════════════════════════════════

FUNCTION_NAME="life-platform-mcp"
REGION="us-west-2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK_DIR="$SCRIPT_DIR/tmp_warmer_$$"

echo "══════════════════════════════════════════════════════════════════"
echo "  Downloading current deployed code"
echo "══════════════════════════════════════════════════════════════════"

mkdir -p "$WORK_DIR"
DOWNLOAD_URL=$(aws lambda get-function \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --query 'Code.Location' \
    --output text)
curl -sL "$DOWNLOAD_URL" -o "$WORK_DIR/current.zip"
cd "$WORK_DIR"
unzip -q current.zip -d package/
echo "✅ Downloaded"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  Patching: expand warmer + add cache reads"
echo "══════════════════════════════════════════════════════════════════"

python3 << 'PYEOF'
import re, sys

with open('package/mcp_server.py') as f:
    content = f.read()

errors = []

# ─────────────────────────────────────────────────────────────────────
# PART 1: Add 6 new warmer steps after step 6 (habit_dashboard)
# ─────────────────────────────────────────────────────────────────────

warmer_insert_marker = '''        results["habit_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] habit_dashboard failed: {e}")
        results["habit_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}'''

warmer_new_steps = '''        results["habit_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] habit_dashboard failed: {e}")
        results["habit_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 7. get_readiness_score
    _t = time.time()
    try:
        logger.info("[warmer] computing readiness_score")
        data = tool_get_readiness_score({"_skip_cache": True})
        ddb_cache_set(f"readiness_score_{today}", data)
        mem_cache_set(f"readiness_score_{today}", data)
        results["readiness_score"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] readiness_score failed: {e}")
        results["readiness_score"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 8. get_health_risk_profile
    _t = time.time()
    try:
        logger.info("[warmer] computing health_risk_profile")
        data = tool_get_health_risk_profile({"_skip_cache": True})
        ddb_cache_set("health_risk_profile_all", data)
        mem_cache_set("health_risk_profile_all", data)
        results["health_risk_profile"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_risk_profile failed: {e}")
        results["health_risk_profile"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 9. get_body_composition_snapshot
    _t = time.time()
    try:
        logger.info("[warmer] computing body_composition_snapshot")
        data = tool_get_body_composition_snapshot({"_skip_cache": True})
        ddb_cache_set("body_comp_snapshot_latest", data)
        mem_cache_set("body_comp_snapshot_latest", data)
        results["body_composition_snapshot"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] body_composition_snapshot failed: {e}")
        results["body_composition_snapshot"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 10. get_energy_balance
    _t = time.time()
    try:
        logger.info("[warmer] computing energy_balance")
        data = tool_get_energy_balance({"_skip_cache": True})
        ddb_cache_set(f"energy_balance_{today}", data)
        mem_cache_set(f"energy_balance_{today}", data)
        results["energy_balance"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] energy_balance failed: {e}")
        results["energy_balance"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 11. get_day_type_analysis (90-day default)
    _t = time.time()
    try:
        logger.info("[warmer] computing day_type_analysis")
        data = tool_get_day_type_analysis({"_skip_cache": True})
        ddb_cache_set(f"day_type_analysis_{today}", data)
        mem_cache_set(f"day_type_analysis_{today}", data)
        results["day_type_analysis"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] day_type_analysis failed: {e}")
        results["day_type_analysis"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 12. get_movement_score (30-day default)
    _t = time.time()
    try:
        logger.info("[warmer] computing movement_score")
        data = tool_get_movement_score({"_skip_cache": True})
        ddb_cache_set(f"movement_score_{today}", data)
        mem_cache_set(f"movement_score_{today}", data)
        results["movement_score"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] movement_score failed: {e}")
        results["movement_score"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}'''

if warmer_insert_marker in content:
    content = content.replace(warmer_insert_marker, warmer_new_steps)
    print("✅ Added 6 warmer steps (7-12)")
else:
    errors.append("Could not find warmer insertion point")
    print("❌ Warmer insertion marker not found")

# ─────────────────────────────────────────────────────────────────────
# PART 2: Add cache-get checks at top of each tool function
# ─────────────────────────────────────────────────────────────────────

cache_patches = [
    {
        "func": "tool_get_readiness_score",
        "marker": '''def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Eight Sleep quality,
    HRV 7-day trend, TSB training form, and Garmin Body Battery into a single
    GREEN / YELLOW / RED signal with a 1-line actionable recommendation.''',
        "replacement": '''def tool_get_readiness_score(args):
    """
    Unified readiness score (0–100) synthesising Whoop recovery, Eight Sleep quality,
    HRV 7-day trend, TSB training form, and Garmin Body Battery into a single
    GREEN / YELLOW / RED signal with a 1-line actionable recommendation.''',
        "after_docstring_marker": 'end_date   = args.get("date"',
        "cache_code": '''    # ── Cache check ──
    if not args.get("_skip_cache"):
        _today = datetime.utcnow().strftime("%Y-%m-%d")
        _ck = f"readiness_score_{_today}"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            logger.info(f"[readiness_score] cache HIT")
            return _cached
''',
    },
    {
        "func": "tool_get_health_risk_profile",
        "after_docstring_marker": 'domain = args.get("domain")',
        "cache_code": '''    # ── Cache check ──
    if not args.get("_skip_cache"):
        _ck = "health_risk_profile_all"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            if domain:
                _cached = {k: v for k, v in _cached.items() if k in (domain, "summary", "metadata", "board_of_directors")}
            logger.info(f"[health_risk_profile] cache HIT")
            return _cached
''',
    },
    {
        "func": "tool_get_body_composition_snapshot",
        "after_docstring_marker": 'scan_date = args.get("date")',
        "cache_code": '''    # ── Cache check (latest only — specific date requests bypass) ──
    if not args.get("_skip_cache") and not args.get("date"):
        _ck = "body_comp_snapshot_latest"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            logger.info(f"[body_composition_snapshot] cache HIT")
            return _cached
''',
    },
    {
        "func": "tool_get_energy_balance",
        "after_docstring_marker": 'end_date   = args.get("end_date"',
        "cache_code": '''    # ── Cache check (default 30-day window only) ──
    if not args.get("_skip_cache") and not args.get("start_date") and not args.get("end_date"):
        _today = datetime.utcnow().strftime("%Y-%m-%d")
        _ck = f"energy_balance_{_today}"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            logger.info(f"[energy_balance] cache HIT")
            return _cached
''',
    },
    {
        "func": "tool_get_day_type_analysis",
        "after_docstring_marker": 'end_date   = args.get("end_date"',
        "cache_code": '''    # ── Cache check (default 90-day window only) ──
    if not args.get("_skip_cache") and not args.get("start_date") and not args.get("end_date"):
        _today = datetime.utcnow().strftime("%Y-%m-%d")
        _ck = f"day_type_analysis_{_today}"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            logger.info(f"[day_type_analysis] cache HIT")
            return _cached
''',
    },
    {
        "func": "tool_get_movement_score",
        "after_docstring_marker": 'end_date   = args.get("end_date"',
        "cache_code": '''    # ── Cache check (default 30-day window only) ──
    if not args.get("_skip_cache") and not args.get("start_date") and not args.get("end_date"):
        _today = datetime.utcnow().strftime("%Y-%m-%d")
        _ck = f"movement_score_{_today}"
        _cached = ddb_cache_get(_ck) or mem_cache_get(_ck)
        if _cached:
            logger.info(f"[movement_score] cache HIT")
            return _cached
''',
    },
]

for patch in cache_patches:
    marker = patch["after_docstring_marker"]
    cache_code = patch["cache_code"]
    func_name = patch["func"]

    # Find the marker line and insert cache check right before it
    # We need to handle indentation — the marker is inside the function body
    idx = content.find(marker)
    if idx == -1:
        errors.append(f"Could not find marker for {func_name}: {marker[:50]}")
        print(f"❌ {func_name}: marker not found")
        continue

    # Find the start of the line containing the marker
    line_start = content.rfind('\n', 0, idx) + 1
    # Get the indentation
    indent = content[line_start:idx]

    # Insert cache check before this line
    content = content[:line_start] + cache_code + content[line_start:]
    print(f"✅ {func_name}: cache check added")

# ─────────────────────────────────────────────────────────────────────
# PART 3: Update server version
# ─────────────────────────────────────────────────────────────────────
content = content.replace('"version": "2.26.0"', '"version": "2.33.0"')

# ─────────────────────────────────────────────────────────────────────
# Write and validate
# ─────────────────────────────────────────────────────────────────────
with open('package/mcp_server.py', 'w') as f:
    f.write(content)

if errors:
    print(f"\n❌ {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

print(f"\n✅ All patches applied successfully")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ Patch failed — aborting"
    rm -rf "$WORK_DIR"
    exit 1
fi

# Syntax check
python3 -c "import py_compile; py_compile.compile('package/mcp_server.py', doraise=True)" && \
    echo "✅ Python syntax check passed" || \
    { echo "❌ Syntax error"; rm -rf "$WORK_DIR"; exit 1; }

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  Package and deploy"
echo "══════════════════════════════════════════════════════════════════"

cd package
zip -q -r ../warmer_deploy.zip .
cd ..
echo "Package size: $(du -h warmer_deploy.zip | cut -f1)"

aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --zip-file "fileb://warmer_deploy.zip" \
    --query '[FunctionName, CodeSize, LastModified]' \
    --output table

echo "Waiting for update..."
aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  Verify"
echo "══════════════════════════════════════════════════════════════════"

echo "Test 1: Lambda health..."
RESULT=$(aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"tool": "list_tools", "parameters": {}}' \
    /tmp/warmer_test.json 2>&1)

if echo "$RESULT" | grep -q "FunctionError"; then
    echo "❌ BROKEN — check logs"
    rm -rf "$WORK_DIR"
    exit 1
else
    echo "✅ Lambda healthy"
fi

echo ""
echo "Test 2: MCP protocol..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --payload '{"body": "{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/call\", \"params\": {\"name\": \"get_sources\", \"arguments\": {}}}"}' \
    /tmp/warmer_test2.json 2>/dev/null

if grep -q '"statusCode": 200' /tmp/warmer_test2.json 2>/dev/null; then
    echo "✅ MCP protocol working"
else
    echo "⚠️  Check response"
fi

# Save locally
cp "$WORK_DIR/package/mcp_server.py" "$SCRIPT_DIR/mcp_server.py"
echo "✅ Local mcp_server.py updated"

# Cleanup
rm -rf "$WORK_DIR"
rm -f /tmp/warmer_test.json /tmp/warmer_test2.json

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ✅ v2.33.0 DEPLOYED — Expanded Cache Warmer"
echo ""
echo "  Warmer: 6 → 12 tools pre-computed nightly"
echo "  New cached tools:"
echo "    7.  readiness_score"
echo "    8.  health_risk_profile"
echo "    9.  body_composition_snapshot"
echo "    10. energy_balance"
echo "    11. day_type_analysis"
echo "    12. movement_score"
echo ""
echo "  Cache reads: 6 tools now check DDB cache before computing"
echo "  Expected: 3-6s queries → <100ms on cache hit"
echo "══════════════════════════════════════════════════════════════════"
