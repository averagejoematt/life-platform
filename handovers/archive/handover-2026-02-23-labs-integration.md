# Handover — 2026-02-23 — Function Health Labs Integration

## What to do

I'm implementing **item 11 from PROJECT_PLAN.md: "Blood work / labs manual entry"** — integrating Function Health lab results into Life Platform.

I have **6 Function Health PDF lab reports** to upload (from ~March/April 2025). Please:

1. **Parse all 6 PDFs** — extract every biomarker with: name, value, unit, reference range, flag (high/low/normal)
2. **Design the `labs` DynamoDB schema** — follows existing `PK: USER#matthew#SOURCE#labs`, `SK: DATE#YYYY-MM-DD` pattern. All biomarkers nested within the day item. Schema must support: Function Health, GP panels, Inside Tracker, or any lab source; multiple draws over time for trending
3. **Build a seed script** (`seed_labs.py`) to load the parsed data into DynamoDB
4. **Build MCP tools** for conversational lab queries: trends over time, out-of-range flags, correlations with biometric data
5. **Write deployment script** to `~/Documents/Claude/life-platform/` (I execute manually in terminal — never deploy via MCP)

## Context files to read first

Read these files from `~/Documents/Claude/life-platform/`:
- `handovers/handover-2026-02-23-labs-integration.md` (this file)
- `SCHEMA.md` (current DynamoDB schema patterns)
- `ARCHITECTURE.md` (system architecture)
- `PROJECT_PLAN.md` (item 11 specifically + overall system context)

## Key conventions
- All deployment scripts go to `~/Documents/Claude/life-platform/` — I run them manually
- DynamoDB table: `life-platform`, region: `us-west-2`, account: `205930651321`
- S3 bucket: `matthew-life-platform`
- MCP server is at Lambda `life-platform-mcp` — currently v2.8.0 with 44 tools
- Every session ends with a handover file + CHANGELOG.md update
- Allowed filesystem path: `/Users/matthewwalker/Documents/Claude`

## What's NOT in scope this session
- Caffeine-sleep tool deployment (deploy script exists, not yet run)
- Habitify first full day verification
- DynamoDB TTL smoke test
- Data completeness alerting (item 16)
