# Life Platform Handover — v3.7.29
**Date:** 2026-03-15
**Session type:** Board review → SEC-3 MEDIUM + CLEANUP-4 + ADR-027 prep

## Platform Status
- **Version:** v3.7.29
- **MCP tools:** 88
- **Lambdas:** 42 (CDK) + 1 Lambda@Edge

## What Was Done This Session

### SEC-3 MEDIUM — mcp/utils.py (new)
- `validate_date_range` + `validate_single_date` — YYYY-MM-DD enforcement, calendar validity, span cap (365d default / 730d hard max)
- Wired into `handler._validate_tool_args` step 4 — auto-applies to all date-range tools with zero per-tool changes

### CLEANUP-4 — ingestion_validator.py
- `from decimal import Decimal as _Decimal` was completely absent — live NameError risk on any validated write
- Fixed: import moved to module level

### ADR-027 prep
- mcp/utils.py is now the first stable-tier module. Layer rebuild deferred Apr 13.

### Deployed
- `life-platform-mcp` ✅

## Carry to April 13
- CLEANUP-3: `python3 setup/setup_google_calendar_auth.py` (20 min, keeps surviving every review)
- ADR-027 full execution: `bash deploy/build_mcp_stable_layer.sh` + CDK update
- Architecture Review #13: `python3 deploy/generate_review_bundle.py` first
- SIMP-1 Phase 2 (<=80 tools, EMF data gated)
