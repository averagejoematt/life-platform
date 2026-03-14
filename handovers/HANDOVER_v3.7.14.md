# Life Platform Handover — v3.7.14
**Date:** 2026-03-14
**Session type:** Doc audit + sync automation

---

## What Was Done

### Full doc audit
Audited all 7 core docs. Found 19 stale facts across 6 files — all fixed:
- ARCHITECTURE.md (8 fixes), INFRASTRUCTURE.md (2), RUNBOOK.md (4), COST_TRACKER.md (3), DECISIONS.md (2), DATA_DICTIONARY.md (1), SLOs.md (1)

Root causes: tool count, secret count, alarm count, schedule times (PST vs PDT), and deleted-secret references all living in multiple places with no single source of truth.

### deploy/sync_doc_metadata.py (new)
Single source of truth for platform counters. `PLATFORM_FACTS` dict → regex replacements across all 7 docs.

```bash
python3 deploy/sync_doc_metadata.py          # dry run
python3 deploy/sync_doc_metadata.py --apply  # write changes
```

Covers: version, date, Lambda count, tool count, module count, secret count, alarm count, and api-keys status everywhere.

### RUNBOOK.md session close checklist — rewritten
Old: vague 5-step list. New: 2-command process + explicit trigger matrix per change type.

---

## New Session Close Process (use from now on)

```bash
# 1. If platform facts changed (counts, version), update PLATFORM_FACTS first:
#    edit deploy/sync_doc_metadata.py → PLATFORM_FACTS dict

# 2. Run the sync
python3 deploy/sync_doc_metadata.py --apply

# 3. Commit
git add -A && git commit -m "vX.X.X: <summary>" && git push
```

For structural changes (new Lambda, new secret, schedule change), also use the RUNBOOK trigger matrix to identify which prose tables need human edits.

---

## Platform Status
- Version: v3.7.14
- All alarms: OK | DLQ: 0 | api-keys: deleted
- Review #8: A- ✅
- SIMP-1 data window: accumulating (started 2026-03-13)

## Next Session
1. **bash deploy/archive_onetime_scripts.sh** (R8-6 — still pending run)
2. **Google Calendar integration** — TB7-18, ~6–8h, next major feature
