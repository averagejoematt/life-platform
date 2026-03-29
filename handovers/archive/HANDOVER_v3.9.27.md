# Handover — v3.9.27

## Session: Nutrition Bug Fix + Global Countdown.js

### What shipped this session (v3.9.26 → v3.9.27)

**v3.9.27**: Resolved all 3 pending items from v3.9.26 handover.

#### 1. `get_nutrition` positional args bug — FIXED
- Root cause: 3 call sites in `tools_nutrition.py` were calling `query_source_range(table, pk, start_date, end_date)` but the function signature is `query_source_range(source, start_date, end_date)` — it's an alias for `query_source()` which builds the pk internally. So `table` was being passed as `source`, `pk` as `start_date`, etc. → TypeError.
- Fix: Replaced all 3 with `query_source("macrofactor", start_date, end_date)` (and `"withings"` for the weight lookup in `tool_get_macro_targets`)
- Cleaned up unused `query_source_range` import from `tools_nutrition.py`

#### 2. `observatory.css` consolidation — ALREADY DONE
- File exists at `site/assets/css/observatory.css` (v1.0.0). Well-structured with `.obs-*` prefixed classes and `--obs-accent` theming. No action needed.

#### 3. countdown.js on all pages — DONE
- Added dynamic script loader at end of `components.js` IIFE
- Guard: checks `window.AMJ_EXPERIMENT` — if already set (homepage/chronicle archive load countdown.js explicitly), skips dynamic load to prevent double-execution
- All ~50+ pages using the shared component system now automatically get Day N badge and experiment counter
- Zero HTML files changed — entirely driven by components.js

### Files Modified
- `mcp/tools_nutrition.py` — Fixed 3 broken `query_source_range` calls, removed unused import
- `site/assets/js/components.js` — Added countdown.js dynamic loader with guard
- `deploy/sync_doc_metadata.py` — Version bump v3.9.26 → v3.9.27
- `docs/CHANGELOG.md` — v3.9.27 entry

### Deploy Required
```bash
# 1. Sync doc metadata
python3 deploy/sync_doc_metadata.py --apply

# 2. Deploy MCP Lambda (nutrition fix)
bash deploy/deploy_lambda.sh life-platform-mcp-server mcp_server.py

# 3. Deploy site files to S3
aws s3 sync site/ s3://matthew-life-platform/site/ --delete --exclude ".DS_Store"

# 4. CloudFront invalidation
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
```

### Pending Items
- SIMP-1 Phase 2 + ADR-025 cleanup targeted ~April 13
- Day 1 checklist (April 1): run `capture_baseline`, verify homepage shows "DAY 1", verify prequel banner auto-hides
- Old `.glc-*` / `.slp-*` CSS prefix migration opportunity (observatory.css consolidation identified some pages may still use old prefixes)
