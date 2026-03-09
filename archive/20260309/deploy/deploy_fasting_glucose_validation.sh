#!/bin/bash
# deploy_fasting_glucose_validation.sh — Fasting Glucose Validation Tool
# Version: v2.32.0
#
# What this does:
#   1. Patches MCP server with get_fasting_glucose_validation tool (61st tool)
#   2. Deploys updated MCP Lambda
#   3. Updates docs (CHANGELOG, SCHEMA, PROJECT_PLAN, handover)
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Life Platform — Fasting Glucose Validation"
echo "  Version: v2.32.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Patch MCP Server ─────────────────────────────────────────────
echo ""
echo "── Step 1: Patching MCP server ──"
python3 patch_fasting_glucose_validation.py

# ── Step 2: Verify patches ───────────────────────────────────────────────
echo ""
echo "── Step 2: Verifying patches ──"

for check in "def tool_get_fasting_glucose_validation" "get_fasting_glucose_validation"; do
    if grep -q "$check" mcp_server.py; then
        echo "  ✅ Found: $check"
    else
        echo "  ❌ MISSING: $check — aborting"
        exit 1
    fi
done

python3 -c "import py_compile; py_compile.compile('mcp_server.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

# ── Step 3: Check handler ────────────────────────────────────────────────
echo ""
echo "── Step 3: Checking MCP Lambda handler ──"
HANDLER=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "Handler" \
    --output text \
    --region us-west-2)
echo "  Handler: $HANDLER"

# ── Step 4: Package and deploy ───────────────────────────────────────────
echo ""
echo "── Step 4: Packaging MCP Lambda ──"
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py

echo "── Step 5: Deploying MCP Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ MCP Lambda deployed"

# ── Step 6: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 6: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

# ── Step 7: Update CHANGELOG ────────────────────────────────────────────
echo ""
echo "── Step 7: Updating docs ──"

# CHANGELOG
python3 << 'PYEOF'
with open('CHANGELOG.md', 'r') as f:
    content = f.read()

entry = """## v2.32.0 — 2026-02-26 — Fasting Glucose Validation (Session 15)

### New MCP Tool: get_fasting_glucose_validation (#61)
- Computes proper overnight nadir (00:00-06:00) from raw S3 CGM readings
- Deep nadir window (02:00-05:00) avoids late digestion and dawn phenomenon
- Distribution stats: mean, median, p10-p90, std dev across ~139 CGM days
- Statistical validation: z-scores and percentiles of lab values vs CGM distribution
- Direct same-day validation ready for future overlapping CGM + lab draws
- Bias analysis with confidence level (high/moderate/low/very_low)
- Compares three proxies: overnight nadir, deep nadir, daily minimum (current)
- Board of Directors insights (Attia, Patrick, Huberman)
- Finding: No same-day CGM + lab overlap exists yet — statistical comparison only

### Platform Stats
- 61 MCP tools (was 60)
- CGM coverage: 2024-09-08 → 2025-01-25 (~139 days)
- Lab draws with fasting glucose: 6 (2019-2025)

---

"""

anchor = '## v2.31.0'
if 'v2.32.0' not in content:
    content = content.replace(anchor, entry + anchor)
    with open('CHANGELOG.md', 'w') as f:
        f.write(content)
    print('  ✅ CHANGELOG.md updated')
else:
    print('  ⏭️  CHANGELOG already has v2.32.0')
PYEOF

# SCHEMA
python3 << 'PYEOF'
with open('SCHEMA.md', 'r') as f:
    content = f.read()

content = content.replace('v2.31.0 — 60 MCP tools', 'v2.32.0 — 61 MCP tools')

with open('SCHEMA.md', 'w') as f:
    f.write(content)
print('  ✅ SCHEMA.md version bumped')
PYEOF

# PROJECT_PLAN
python3 << 'PYEOF'
with open('PROJECT_PLAN.md', 'r') as f:
    content = f.read()

# Version bump
content = content.replace(
    'v2.31.0 — 60 MCP tools, 16 data sources, 20 Lambdas, derived metrics complete',
    'v2.32.0 — 61 MCP tools, 16 data sources, 20 Lambdas'
)
content = content.replace('**Platform version:** v2.31.0', '**Platform version:** v2.32.0')
content = content.replace(
    '**MCP Server:** 60 tools serving health data through Claude Desktop',
    '**MCP Server:** 61 tools serving health data through Claude Desktop'
)

# Strike through fasting glucose validation
content = content.replace(
    '| 8 | **Fasting glucose validation** | Compare daily CGM minimum (overnight nadir) against lab fasting glucose across 7 blood draws. | 2 hr |',
    '| ~~8~~ | ~~**Fasting glucose validation**~~ | ~~Deployed v2.32.0 — overnight nadir + deep nadir + bias analysis + statistical validation~~ | ~~Done~~ |'
)

# Add to completed table
completed_anchor = '| v2.31.0 | Derived Metrics Phase 1f (ASCVD risk) + Phase 2c (day_type classification + analysis tool) | 2026-02-26 |'
new_row = '| v2.32.0 | Fasting glucose validation — overnight nadir distribution vs lab draws, bias analysis, 61st MCP tool | 2026-02-26 |'
if 'v2.32.0' not in content:
    content = content.replace(completed_anchor, new_row + '\n' + completed_anchor)

with open('PROJECT_PLAN.md', 'w') as f:
    f.write(content)
print('  ✅ PROJECT_PLAN.md updated')
PYEOF

# ── Step 8: Create handover ─────────────────────────────────────────────
echo ""
echo "── Step 8: Creating handover ──"

cat > handovers/2026-02-26-session15-fasting-glucose-validation.md << 'HANDOVER'
# Handover — Session 15: Fasting Glucose Validation

**Date:** 2026-02-26
**Version:** v2.32.0

---

## What happened this session

### Fasting Glucose Validation Tool — DEPLOYED ✅
- New MCP tool: `get_fasting_glucose_validation` (#61)
- Reads raw S3 CGM data (~139 days), computes proper overnight nadir
- Two windows: broad (00:00-06:00) and deep (02:00-05:00) to avoid dawn phenomenon
- Distribution stats: mean, median, percentiles, std dev
- Statistical validation: lab fasting glucose z-scores vs CGM nadir distribution
- Direct same-day validation: ready but no CGM + lab overlap yet
- Bias analysis with interpretation and confidence level
- Board of Directors insights (Attia, Patrick, Huberman)

### Key Finding
- No same-day overlap between CGM data (Sep 2024 - Jan 2025) and lab draws
- Statistical comparison is the only available mode currently
- Recommendation: schedule next blood draw while wearing Stelo for gold-standard validation

---

## Files created
- `patch_fasting_glucose_validation.py` — MCP server patch
- `deploy_fasting_glucose_validation.sh` — Deploy script (this file)

## Files modified
- `mcp_server.py` — Added tool_get_fasting_glucose_validation + registry entry
- `CHANGELOG.md` — v2.32.0 entry
- `SCHEMA.md` — Version bumped to v2.32.0
- `PROJECT_PLAN.md` — Updated, fasting glucose validation marked done

---

## DST Reminder — ACTION March 7 evening or March 8 before 6 AM PDT

```bash
cd ~/Documents/Claude/life-platform
chmod +x deploy_dst_spring_2026.sh
./deploy_dst_spring_2026.sh
```

## Next session suggestions

### Tier 1:
1. **DST cron update** — March 8 (script ready)
2. **MCP latency investigation** — 1.2s → 2.8s trend
3. **Monarch Money** (#9) — Financial pillar

### Tier 2:
4. **Daily Brief v2.4** — Integrate derived metrics + fasting validation into brief
5. **Health trajectory** (#15) — Weight goal date, metabolic age projections
6. **Google Calendar** (#14) — Cognitive load pillar

### Infrastructure:
7. **WAF rate limiting** (#10)
8. **MCP API key rotation** (#11)
9. **S3 bucket 2.3GB growth** — Investigate
HANDOVER

# Update pointer
cat > HANDOVER_LATEST.md << 'EOF'
# Latest Handover Pointer
→ `handovers/2026-02-26-session15-fasting-glucose-validation.md`
EOF

echo "  ✅ Handover created"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ v2.32.0 DEPLOYED — Fasting Glucose Validation"
echo ""
echo "  New: get_fasting_glucose_validation (61st MCP tool)"
echo ""
echo "  Test with:"
echo "    'How accurate is my CGM fasting glucose?'"
echo "    'Validate my CGM against lab draws'"
echo "    'Compare my overnight nadir to blood work'"
echo "═══════════════════════════════════════════════════"
