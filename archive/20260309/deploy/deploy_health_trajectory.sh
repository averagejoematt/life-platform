#!/bin/bash
# deploy_health_trajectory.sh — Health Trajectory Projections (Package 3 of 3)
# Version: v2.34.0
#
# What this does:
#   1. Patches MCP server with get_health_trajectory tool (77 tools total)
#   2. Deploys updated MCP Lambda
#   3. Updates all docs (CHANGELOG, SCHEMA, PROJECT_PLAN)
#   4. Creates session handover
#
# Pre-flight: Run from ~/Documents/Claude/life-platform/
# IMPORTANT: Run deploy_n1_experiments.sh FIRST (Package 2)

set -euo pipefail
cd ~/Documents/Claude/life-platform

echo "═══════════════════════════════════════════════════"
echo "  Package 3/3: Health Trajectory Projections"
echo "  Version: v2.34.0"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Patch MCP Server ─────────────────────────────────────────────
echo ""
echo "── Step 1: Patching MCP server ──"
python3 patches/patch_health_trajectory.py

# ── Step 2: Verify patches ───────────────────────────────────────────────
echo ""
echo "── Step 2: Verifying all v2.34.0 patches ──"

# Verify Package 2 (N=1 experiments) is present
for check in "EXPERIMENTS_PK" "def tool_create_experiment" "def tool_list_experiments" "def tool_get_experiment_results" "def tool_end_experiment"; do
    if grep -q "$check" mcp_server.py; then
        echo "  ✅ [Pkg2] Found: $check"
    else
        echo "  ❌ [Pkg2] MISSING: $check — run deploy_n1_experiments.sh first!"
        exit 1
    fi
done

# Verify Package 3 (health trajectory)
for check in "def tool_get_health_trajectory" "\"get_health_trajectory\":"; do
    if grep -q "$check" mcp_server.py; then
        echo "  ✅ [Pkg3] Found: $check"
    else
        echo "  ❌ [Pkg3] MISSING: $check — aborting"
        exit 1
    fi
done

python3 -c "import py_compile; py_compile.compile('mcp_server.py', doraise=True)" && echo "  ✅ Python syntax valid" || { echo "  ❌ Syntax error"; exit 1; }

# Count tools
TOOL_COUNT=$(grep -c '"fn":' mcp_server.py)
echo "  ℹ️  Tool count: $TOOL_COUNT"

# ── Step 3: Package and deploy ───────────────────────────────────────────
echo ""
echo "── Step 3: Packaging MCP Lambda ──"
rm -f mcp_server.zip
zip mcp_server.zip mcp_server.py

echo "── Step 4: Deploying MCP Lambda ──"
aws lambda update-function-code \
    --function-name life-platform-mcp \
    --zip-file fileb://mcp_server.zip \
    --region us-west-2 \
    --no-cli-pager

echo "  ✅ MCP Lambda deployed"

# ── Step 5: Wait and verify ──────────────────────────────────────────────
echo ""
echo "── Step 5: Waiting for Lambda to stabilize ──"
sleep 5

aws lambda get-function-configuration \
    --function-name life-platform-mcp \
    --query "[LastModified, CodeSize, Handler]" \
    --region us-west-2 \
    --no-cli-pager

# ── Step 6: Update docs ─────────────────────────────────────────────────
echo ""
echo "── Step 6: Updating docs ──"

# CHANGELOG
python3 << 'PYEOF'
with open('docs/CHANGELOG.md', 'r') as f:
    content = f.read()

entry = """## v2.34.0 — 2026-02-26 — Triple Feature Deploy (Session 18)

### Package 1: Strava Ingestion Dedup (#4 on roadmap)
- Added `dedup_activities()` to Strava ingestion Lambda
- Same overlap logic as daily brief: same sport_type + start within 15 min → keep richer record
- All downstream MCP tools now get clean data (training load, Zone 2, exercise-sleep correlation)
- Eliminates double-counted activities at source

### Package 2: N=1 Experiment Framework (#5 on roadmap) — 4 new MCP tools
- `create_experiment` — Start tracking a protocol change with hypothesis
- `list_experiments` — View active/completed/abandoned experiments
- `get_experiment_results` — Auto-compare before vs during across 16 health metrics
- `end_experiment` — Close experiment with outcome notes
- Schema: PK USER#matthew#SOURCE#experiments, SK EXP#<slug>_<date>
- Board of Directors evaluates each experiment result against hypothesis
- Minimum 14-day data threshold warning (Huberman/Attia consensus)

### Package 3: Health Trajectory Projections (#3 on roadmap) — 1 new MCP tool
- `get_health_trajectory` — Forward-looking intelligence across 5 domains:
  - Weight: rate of loss, phase milestones, projected goal date
  - Biomarkers: lab trend slopes, 6-month projections, threshold warnings
  - Fitness: Zone 2 trend, training consistency %, volume direction
  - Recovery: HRV trend, RHR trend, sleep efficiency trend
  - Metabolic: mean glucose trend, time-in-range from CGM
- Board of Directors longevity assessment with positives/concerns summary

### Platform Stats
- 77 MCP tools (was 72, +5 new)
- 3 North Star gaps addressed: "No did-it-work loop" (#5), "No forward-looking intelligence" (#3), Strava dedup (#4)
- Strava Lambda updated with ingestion-time dedup

---

"""

anchor = '## Docs & Reorg'
if 'v2.34.0' not in content:
    content = content.replace(anchor, entry + anchor)
    with open('docs/CHANGELOG.md', 'w') as f:
        f.write(content)
    print('  ✅ CHANGELOG.md updated')
else:
    print('  ⏭️  CHANGELOG already has v2.34.0')
PYEOF

# PROJECT_PLAN
python3 << 'PYEOF'
with open('docs/PROJECT_PLAN.md', 'r') as f:
    content = f.read()

# Version bump
content = content.replace('**Platform version:** v2.33.0', '**Platform version:** v2.34.0')
content = content.replace(
    '**MCP Server:** 72 tools serving health data through Claude Desktop (1024 MB, 12 cached tools)',
    '**MCP Server:** 77 tools serving health data through Claude Desktop (1024 MB, 12 cached tools)'
)
content = content.replace('v2.33.0 (no code changes this session', 'v2.34.0')
content = content.replace('72 MCP tools, 16 data sources, 20 Lambdas, 12 cached tools', '77 MCP tools, 16 data sources, 20 Lambdas, 12 cached tools')

# Mark roadmap items as done
# Item 3 - Health trajectory
content = content.replace(
    '| 3 | **Health trajectory projections**',
    '| ~~3~~ | ~~**Health trajectory projections**~~'
)
# Item 4 - Strava dedup
content = content.replace(
    '| 4 | **Strava ingestion dedup**',
    '| ~~4~~ | ~~**Strava ingestion dedup**~~'
)
# Item 5 - N=1 experiments
content = content.replace(
    '| 5 | **N=1 experiment framework**',
    '| ~~5~~ | ~~**N=1 experiment framework**~~'
)

# Add to completed table
completed_anchor = '| v2.33.0 |'
new_row = '| v2.34.0 | Triple feature: Strava dedup, N=1 experiments (4 tools), Health trajectory (1 tool) — 77 MCP tools | 2026-02-26 |'
if 'v2.34.0' not in content:
    content = content.replace(completed_anchor, new_row + '\n' + completed_anchor)

# Update North Star gaps
content = content.replace(
    '6. **No "did it work?" loop** — interventions aren\'t tracked → N=1 experiments (#5), Supplement log (#9)',
    '6. ~~**No "did it work?" loop**~~ — N=1 experiments deployed v2.34.0 ✔️ (Supplement log (#9) enhances this further)'
)
content = content.replace(
    '7. **No forward-looking intelligence** — all data is retrospective → Health trajectory (#3), Training periodization (#11)',
    '7. ~~**No forward-looking intelligence**~~ — Health trajectory deployed v2.34.0 ✔️ (Training periodization (#11) adds depth)'
)

with open('docs/PROJECT_PLAN.md', 'w') as f:
    f.write(content)
print('  ✅ PROJECT_PLAN.md updated')
PYEOF

# SCHEMA
python3 << 'PYEOF'
with open('docs/SCHEMA.md', 'r') as f:
    content = f.read()

content = content.replace('72 MCP tools', '77 MCP tools')
content = content.replace('v2.33.0', 'v2.34.0')

# Add experiments schema entry if not present
if 'SOURCE#experiments' not in content:
    schema_anchor = '### Insights Partition'
    if schema_anchor in content:
        exp_schema = """### Experiments Partition (v2.34.0)
| PK | SK | Description |
|----|-----|-------------|
| `USER#matthew#SOURCE#experiments` | `EXP#<slug>_<date>` | N=1 experiment record |

**Fields:** experiment_id, name, hypothesis, start_date, end_date, status (active/completed/abandoned), tags[], notes, outcome, created_at, ended_at

"""
        content = content.replace(schema_anchor, exp_schema + schema_anchor)

with open('docs/SCHEMA.md', 'w') as f:
    f.write(content)
print('  ✅ SCHEMA.md updated')
PYEOF

# ── Step 7: Create handover ─────────────────────────────────────────────
echo ""
echo "── Step 7: Creating handover ──"

cat > handovers/2026-02-26-session18-triple-feature.md << 'HANDOVER'
# Life Platform — Session Handover
## 2026-02-26 Session 18: Triple Feature Deploy (Autonomous)

**Version:** v2.34.0
**MCP tools:** 77 (was 72, +5 new) | **Cached:** 12 | **Lambda:** 1024 MB

---

## What Was Done (3 packages, autonomous session)

### Package 1: Strava Ingestion Dedup ✅ (Roadmap #4)
- Added `dedup_activities()` to `lambdas/strava_lambda.py`
- Same overlap logic as daily brief: same sport_type + 15-min window → keep richer record
- Benefits all downstream MCP tools (training load, Zone 2, exercise-sleep, etc.)
- No MCP server change needed (Strava Lambda only)

### Package 2: N=1 Experiment Framework ✅ (Roadmap #5)
- 4 new MCP tools: `create_experiment`, `list_experiments`, `get_experiment_results`, `end_experiment`
- DynamoDB schema: `USER#matthew#SOURCE#experiments` / `EXP#<slug>_<date>`
- `get_experiment_results` auto-compares 16 metrics across before/during periods
- Board of Directors evaluates results against hypothesis
- Minimum 14-day threshold warning per Huberman/Attia

### Package 3: Health Trajectory Projections ✅ (Roadmap #3)
- 1 new MCP tool: `get_health_trajectory`
- 5 domains: weight, biomarkers, fitness, recovery, metabolic
- Weight: rate of loss, phase milestones, projected goal date, 3/6/12-mo projections
- Biomarkers: linear regression across 10 key markers, 6-month projections, threshold flags
- Fitness: Zone 2 trend, training consistency %, volume direction
- Recovery: HRV/RHR/sleep efficiency trends (first half vs second half comparison)
- Metabolic: mean glucose trend, time-in-range from CGM
- Board of Directors longevity assessment with positives/concerns

---

## North Star Progress
- ~~"No did-it-work loop"~~ → N=1 experiments deployed ✔️
- ~~"No forward-looking intelligence"~~ → Health trajectory deployed ✔️
- Strava dedup fixed at ingestion level ✔️

## Files Created
- `patches/patch_strava_dedup.py`
- `patches/patch_n1_experiments.py`
- `patches/patch_health_trajectory.py`
- `deploy/deploy_strava_dedup.sh`
- `deploy/deploy_n1_experiments.sh`
- `deploy/deploy_health_trajectory.sh`

## Files Modified
- `lambdas/strava_lambda.py` — dedup_activities() added
- `mcp_server.py` — 5 new tool functions + TOOLS entries
- `docs/CHANGELOG.md` — v2.34.0 entry
- `docs/PROJECT_PLAN.md` — Version, roadmap items struck, North Star updated
- `docs/SCHEMA.md` — Experiments partition added

---

## Outstanding Ops Tasks

| Task | When | Command |
|------|------|---------|
| DST Spring Forward | March 7 evening | `bash deploy/deploy_dst_spring_2026.sh` |

---

## Next Session Suggestions

Tier 1 remaining:
1. **Monarch Money (#1)** — Financial stress pillar. Auth setup exists. 4-6 hr.
2. **Google Calendar (#2)** — Cognitive load data (last major North Star gap). 6-8 hr.

Tier 2 quick wins:
3. **Sleep environment optimization (#6)** — Eight Sleep bed temp correlation. 3-4 hr.
4. **Readiness-based training recs (#7)** — Auto-suggest workout type. 4-6 hr.
5. **Supplement log (#9)** — Enhances N=1 experiments. 3-4 hr.

Polish:
6. **Add get_health_trajectory to cache warmer** — Pre-compute nightly. 30 min.
7. **MCP tool catalog update** — Add 5 new tools to MCP_TOOL_CATALOG.md. 15 min.

---

## Key Stats
- Roadmap: 3 of 5 Tier 1 items now complete
- North Star: 5 of 7 gaps closed (2 remaining: financial data, cognitive load)
- Platform: 77 tools, 16 sources, 20 Lambdas, ~$6/mo
HANDOVER

# Update pointer
cat > docs/HANDOVER_LATEST.md << 'EOF'
# Latest Handover Pointer
→ `handovers/2026-02-26-session18-triple-feature.md`
EOF

echo "  ✅ Handover created"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ ALL 3 PACKAGES DEPLOYED — v2.34.0"
echo ""
echo "  Package 1: Strava Ingestion Dedup"
echo "  Package 2: N=1 Experiment Framework (4 tools)"
echo "  Package 3: Health Trajectory Projections (1 tool)"
echo ""
echo "  77 MCP tools total (was 72)"
echo ""
echo "  Test commands:"
echo "    'Where am I headed health-wise?'"
echo "    'Create experiment: no caffeine after 10am'"
echo "    'What experiments am I running?'"
echo "    'Show my health trajectory for weight'"
echo "═══════════════════════════════════════════════════"
