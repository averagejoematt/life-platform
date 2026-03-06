#!/bin/bash
# deploy_v231_complete.sh — Derived Metrics Phase 1f (ASCVD) + Phase 2c (Day Type) + Docs
# Version: v2.31.0
#
# What this does:
#   1. Patches labs records with ASCVD 10-year risk scores (Phase 1f)
#   2. Patches MCP server with day_type utility + tool + ASCVD in health risk profile
#   3. Deploys updated MCP Lambda (60 tools)
#   4. Updates SCHEMA.md, PROJECT_PLAN.md
#   5. Creates handover file + updates HANDOVER_LATEST.md
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Life Platform — v2.31.0 Complete Deploy"
echo "  Derived Metrics Phase 1f + 2c + Docs"
echo "═══════════════════════════════════════════════════"

# ── Step 1: ASCVD Risk Scores on Labs Records ──────────────────────────────
echo ""
echo "── Step 1: Computing ASCVD 10yr risk on labs records ──"
python3 patch_ascvd_risk.py

# ── Step 2: Patch MCP Server ──────────────────────────────────────────────
echo ""
echo "── Step 2: Patching MCP server (day_type + ASCVD display) ──"
python3 patch_day_type_ascvd.py

# ── Step 3: Verify patches ──────────────────────────────────────────────────
echo ""
echo "── Step 3: Verifying patches ──"

PASS=true
for check in "def classify_day_type" "def tool_get_day_type_analysis" "ASCVD 10yr Risk" "get_day_type_analysis"; do
    if grep -q "$check" mcp_server.py; then
        echo "  ✅ Found: $check"
    else
        echo "  ❌ MISSING: $check"
        PASS=false
    fi
done

python3 -c "import py_compile; py_compile.compile('mcp_server.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

if [ "$PASS" = false ]; then
    echo "  ❌ Patch verification failed — aborting"
    exit 1
fi

# ── Step 4: Check MCP Lambda handler ─────────────────────────────────────
echo ""
echo "── Step 4: Checking MCP Lambda handler ──"
HANDLER=$(aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "Handler" \
    --output text \
    --region us-west-2 \
    --no-cli-pager)
echo "  Current handler: $HANDLER"
if [ "$HANDLER" != "mcp_server.lambda_handler" ]; then
    echo "  ⚠️  Handler mismatch! Expected mcp_server.lambda_handler"
    echo "  Continuing but verify after deploy..."
fi

# ── Step 5: Package and deploy MCP Lambda ──────────────────────────────────
echo ""
echo "── Step 5: Packaging MCP Lambda ──"
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py

echo "── Step 6: Deploying MCP Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ MCP Lambda deployed"

# ── Step 7: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 7: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

# ── Step 8: Update SCHEMA.md ─────────────────────────────────────────────
echo ""
echo "── Step 8: Updating SCHEMA.md ──"

# Update version header
sed -i '' 's/v2\.30\.0 — 59 MCP tools/v2.31.0 — 60 MCP tools/g' SCHEMA.md

# Add ASCVD fields to labs section — insert before "Access via labs-specific MCP tools"
ASCVD_SCHEMA='
**ASCVD Risk Score fields (on draw records):**

| Field | Type | Description |
|-------|------|-------------|
| `ascvd_risk_10yr_pct` | number/string | 10-year ASCVD risk percentage (Pooled Cohort Equations). String "insufficient_data..." if missing TC/HDL. |
| `ascvd_risk_category` | string | `low` (<5%), `borderline` (5-7.5%), `intermediate` (7.5-20%), `high` (>20%) |
| `ascvd_inputs` | object | All inputs used: age, sex, race, TC, HDL, SBP, bp_treated, is_diabetic, is_smoker, systolic_bp_source |
| `ascvd_equation` | string | "Pooled Cohort Equations (2013 ACC/AHA)" |
| `ascvd_caveats` | list | Any caveats (e.g. age extrapolation outside 40-79 range) |

Note: SBP currently uses estimate (125 mmHg) — `ascvd_inputs.systolic_bp_source` tracks provenance. Update when BP monitor data available.'

# Use python for safe multiline insert
python3 -c "
import re
with open('SCHEMA.md', 'r') as f:
    content = f.read()

insert_before = 'Access via labs-specific MCP tools'
schema_block = '''$ASCVD_SCHEMA'''

if 'ascvd_risk_10yr_pct' not in content:
    content = content.replace(insert_before, schema_block + '\n\n' + insert_before)
    with open('SCHEMA.md', 'w') as f:
        f.write(content)
    print('  ✅ ASCVD fields added to labs section')
else:
    print('  ⏭️  ASCVD fields already in schema')
" 2>/dev/null || {
    # Fallback: use heredoc approach
    python3 << 'PYEOF'
with open('SCHEMA.md', 'r') as f:
    content = f.read()

insert_before = 'Access via labs-specific MCP tools'
schema_block = """
**ASCVD Risk Score fields (on draw records):**

| Field | Type | Description |
|-------|------|-------------|
| `ascvd_risk_10yr_pct` | number/string | 10-year ASCVD risk percentage (Pooled Cohort Equations). String "insufficient_data..." if missing TC/HDL. |
| `ascvd_risk_category` | string | `low` (<5%), `borderline` (5-7.5%), `intermediate` (7.5-20%), `high` (>20%) |
| `ascvd_inputs` | object | All inputs used: age, sex, race, TC, HDL, SBP, bp_treated, is_diabetic, is_smoker, systolic_bp_source |
| `ascvd_equation` | string | "Pooled Cohort Equations (2013 ACC/AHA)" |
| `ascvd_caveats` | list | Any caveats (e.g. age extrapolation outside 40-79 range) |

Note: SBP currently uses estimate (125 mmHg) - ascvd_inputs.systolic_bp_source tracks provenance. Update when BP monitor data available."""

if 'ascvd_risk_10yr_pct' not in content:
    content = content.replace(insert_before, schema_block + '\n\n' + insert_before)
    with open('SCHEMA.md', 'w') as f:
        f.write(content)
    print('  ✅ ASCVD fields added to labs section')
else:
    print('  ⏭️  ASCVD fields already in schema')
PYEOF
}

echo "  ✅ SCHEMA.md updated to v2.31.0"

# ── Step 9: Update PROJECT_PLAN.md ───────────────────────────────────────
echo ""
echo "── Step 9: Updating PROJECT_PLAN.md ──"

python3 << 'PYEOF'
with open('PROJECT_PLAN.md', 'r') as f:
    content = f.read()

# Update version header
content = content.replace(
    'v2.30.0 — 59 MCP tools, 16 data sources, 20 Lambdas, derived metrics Phase 1a-1e deployed',
    'v2.31.0 — 60 MCP tools, 16 data sources, 20 Lambdas, derived metrics complete'
)

# Update current state block
content = content.replace(
    '**Platform version:** v2.30.0',
    '**Platform version:** v2.31.0'
)
content = content.replace(
    '**MCP Server:** 59 tools serving health data through Claude Desktop',
    '**MCP Server:** 60 tools serving health data through Claude Desktop'
)

# Strike through derived metrics in Tier 2
content = content.replace(
    '| NEW | **Derived Metrics (6 sessions)** | Board of Directors schema review → 16 derived metrics across 3 patterns. See `DERIVED_METRICS_PLAN.md`. Phase 1a-1e complete (5/6 Pattern A metrics). | ~12 hr remaining |',
    '| ~~NEW~~ | ~~**Derived Metrics (6 sessions)**~~ | ~~All Pattern A (6/6) + Pattern B (4/4) deployed. 60 MCP tools. See CHANGELOG v2.29.0-v2.31.0.~~ | ~~Done~~ |'
)

# Add v2.31.0 to completed table
completed_anchor = '| v2.30.0 | Derived Metrics Phase 1c-1e: CGM optimal %, protein distribution, micronutrient sufficiency | 2026-02-26 |'
new_row = '| v2.31.0 | Derived Metrics Phase 1f (ASCVD risk) + Phase 2c (day_type classification + analysis tool) | 2026-02-26 |'
if 'v2.31.0' not in content:
    content = content.replace(completed_anchor, new_row + '\n' + completed_anchor)

# Update remaining gaps — glucose meal response is done
content = content.replace(
    '3. **Glucose meal response** — highest-ROI new analysis for weight loss → #6',
    '3. ~~**Glucose meal response**~~ — deployed v2.26.0 ✔️'
)

with open('PROJECT_PLAN.md', 'w') as f:
    f.write(content)

print('  ✅ PROJECT_PLAN.md updated to v2.31.0')
PYEOF

# ── Step 10: Create handover file ────────────────────────────────────────
echo ""
echo "── Step 10: Creating handover file ──"

cat > handovers/2026-02-26-session14-derived-phase1f-2c.md << 'HANDOVER'
# Handover — Session 14: Derived Metrics Phase 1f + Phase 2c

**Date:** 2026-02-26
**Version:** v2.31.0

---

## What happened this session

### Phase 1f: ASCVD 10-Year Risk Score — DEPLOYED ✅
- Implemented Pooled Cohort Equations (2013 ACC/AHA) for all 4 race/sex cohorts
- Patched labs records in DynamoDB with `ascvd_risk_10yr_pct`, `ascvd_risk_category`, `ascvd_inputs`
- Draw 1 (2025-04-08): skipped — no total cholesterol or HDL
- Draw 2 (2025-04-17): computed with TC 219, HDL 72, SBP 125 (estimated)
- Age-extrapolation caveat: PCE validated 40-79, Matthew was 36 at draw
- SBP uses estimate (125 mmHg) — flagged for update when BP data available
- ASCVD now surfaces in `get_health_risk_profile` cardiovascular domain

### Phase 2c: Day Type Classification + Analysis Tool — DEPLOYED ✅
- New utility: `classify_day_type()` — rest/light/moderate/hard/race
- Classification priority: Whoop strain > computed load > Strava distance/time
- Thresholds: rest (<4), light (4-8), moderate (8-14), hard (14+)
- New MCP tool: `get_day_type_analysis` — segments sleep, recovery, nutrition by day type
- Auto-generates insights: HRV impact, caloric adjustment, sleep debt patterns

### Phase 2 Completion Notes
- 2a (ACWR): Already in `get_training_load` ✅
- 2b (fiber_per_1000kcal): Already in `get_nutrition_summary` ✅
- 2d (strength_to_bw_ratio): Already in `get_strength_standards` ✅
- **All Pattern A (6/6) + Pattern B (4/4) derived metrics now deployed**

### Platform Stats
- 60 MCP tools (was 59)
- Derived metrics program COMPLETE

---

## Derived Metrics Final Status

| Phase | Metric | Status |
|-------|--------|--------|
| 1a | `sleep_onset_consistency_7d` | ✅ Session 12 |
| 1b | `lean_mass_delta_14d` + `fat_mass_delta_14d` | ✅ Session 12 |
| 1c | `blood_glucose_time_in_optimal_pct` | ✅ Session 13 |
| 1d | `protein_distribution_score` | ✅ Session 13 |
| 1e | `micronutrient_sufficiency` | ✅ Session 13 |
| 1f | `ascvd_risk_10yr_pct` | ✅ Session 14 |
| 2a | ACWR in `get_training_load` | ✅ Pre-existing |
| 2b | fiber_per_1000kcal in `get_nutrition_summary` | ✅ Pre-existing |
| 2c | `get_day_type_analysis` tool | ✅ Session 14 |
| 2d | strength_to_bw_ratio in `get_strength_standards` | ✅ Pre-existing |

---

## Files created
- `patch_ascvd_risk.py` — ASCVD Pooled Cohort Equations, patches labs records
- `patch_day_type_ascvd.py` — MCP patches: day_type utility + tool + ASCVD display
- `deploy_derived_phase1f_2c.sh` — Original deploy script (from cut-off session)
- `deploy_v231_complete.sh` — Complete deploy with docs (this session)

## Files modified
- `mcp_server.py` — classify_day_type(), tool_get_day_type_analysis, ASCVD in risk profile
- `SCHEMA.md` — Added ASCVD fields to labs section, bumped to v2.31.0
- `PROJECT_PLAN.md` — Updated to v2.31.0, 60 tools, derived metrics complete
- `CHANGELOG.md` — v2.31.0 entry (written in cut-off session)

---

## DST Reminder
March 8 (10 days). All EventBridge crons shift +1 hour. Plan a quick session to update.

## Next session suggestions

### Tier 1 priorities:
1. **DST cron update** — Quick 30-min session before March 8
2. **Fasting glucose validation** (#8) — Compare CGM nadir vs lab draws
3. **MCP latency investigation** — 1.2s → 2.8s trend, uninvestigated

### Tier 2:
4. **Monarch Money** (#9) — Financial pillar, setup_monarch_auth.py exists
5. **Daily Brief v2.4** — Integrate derived metrics into brief sections
6. **Health trajectory** (#15) — Weight goal date, metabolic age projections

### Infrastructure:
7. **WAF rate limiting** (#10) — $5/mo
8. **MCP API key rotation** (#11) — 90-day schedule
9. **S3 bucket 2.3GB** — Investigate growth

---

## Remaining from prior sessions (low priority)
- S3 bucket 2.3GB growth — uninvestigated
- MCP server latency trending 1.2s → 2.8s — uninvestigated
- WAF rate limiting (#10)
- MCP API key rotation (#11)
HANDOVER

echo "  ✅ Handover file created"

# ── Step 11: Update HANDOVER_LATEST.md ───────────────────────────────────
echo ""
echo "── Step 11: Updating HANDOVER_LATEST.md ──"

cat > HANDOVER_LATEST.md << 'EOF'
# Latest Handover Pointer
→ `handovers/2026-02-26-session14-derived-phase1f-2c.md`
EOF

echo "  ✅ HANDOVER_LATEST.md updated"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ v2.31.0 FULLY DEPLOYED"
echo ""
echo "  What shipped:"
echo "    - ASCVD 10yr risk on labs records (Phase 1f)"
echo "    - classify_day_type() utility (Phase 2c)"
echo "    - get_day_type_analysis MCP tool (#60)"
echo "    - ASCVD in get_health_risk_profile"
echo "    - All docs updated (SCHEMA, PROJECT_PLAN, handover)"
echo ""
echo "  Derived Metrics program: COMPLETE ✨"
echo "    Pattern A: 6/6 | Pattern B: 4/4"
echo ""
echo "  Test with:"
echo "    'Segment my sleep by training day type'"
echo "    'Show my cardiovascular risk profile'"
echo "═══════════════════════════════════════════════════"
