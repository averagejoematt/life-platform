# Life Platform Handover — v3.7.57
**Date:** 2026-03-16 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.57 |
| MCP tools | 89 |
| Data sources | 19 active |
| Lambdas | 45 |
| S3 objects | 35,273+ (fully restored) |
| S3 versioning | ✅ Enabled |
| S3 bucket policy | ✅ DeleteObject denied on data prefixes |
| Website | **LIVE** — averagejoematt.com |

---

## What Was Done This Session

### 1. P1 Incident: S3 Bucket Wipe (35,188 objects)
- Deploy script `deploy_v3756_restore_signal_homepage.sh` ran `aws s3 sync --delete` from 17-file website dir to bucket root
- Sonnet's initial assessment: ~1,002 deletions across 5 prefixes — **incorrect**
- Opus forensic analysis of 35,313-line terminal log: **35,188 deletions across 15 prefixes**
- Raw data archive destroyed: Apple Health (2012–2026), Strava (2009–2026), Whoop (2020–2026), Withings (2012–2026), Garmin, Eight Sleep, Todoist, CGM, MacroFactor, weather, plus config, deploys, dashboard, CloudTrail, exports, and more

### 2. Full Recovery via S3 Versioning
- S3 versioning confirmed enabled pre-incident (`"IsLatest": false` on 2009 Strava file proved versions survived)
- Python batch script removed all delete markers: 34,221 raw + 1,052 infrastructure = 35,273 objects restored
- Post-recovery inventory verified against forensic counts — all prefixes match except config (restored manually from git)

### 3. Post-Incident Hardening (ADR-032, ADR-033)
- **S3 bucket policy:** Deny `s3:DeleteObject` for `matthew-admin` on `raw/*`, `config/*`, `uploads/*`, `dashboard/*`, `exports/*`, `deploys/*`, `cloudtrail/*`, `imports/*`. Verified: upload succeeds, delete returns AccessDenied.
- **`deploy/lib/safe_sync.sh`:** Wrapper blocks syncs to bucket root, runs `--dryrun`, aborts if >100 deletions
- **Removed offending script:** `deploy/deploy_v3756_restore_signal_homepage.sh` deleted
- **Config files restored:** `board_of_directors.json`, `character_sheet.json`, `project_pillar_map.json` (root + matthew/ prefixes)
- **Requirements restored:** `lambdas/requirements/*.txt` synced to `config/requirements/`

### 4. Documentation Updated
- `INCIDENT_LOG.md`: P1 entry + new patterns (one-off scripts, S3 sync --delete watch-out)
- `DECISIONS.md`: ADR-032 (bucket policy) + ADR-033 (safe sync wrapper)
- `CHANGELOG.md`: v3.7.57 entry
- This handover file

---

## Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| S3 bucket policy Deny over IAM restriction | Resource-based Deny is absolute — overrides any Allow in identity policy |
| Protect data prefixes, leave `site/` open | `sync_site_to_s3.sh --delete` legitimately needs to clean old site files |
| safe_sync wrapper with 100-deletion threshold | Catches "17 files vs 35,000" scenario without blocking normal deploys |
| No one-off deploy scripts (principle) | Two separate incidents (Mar 11, Mar 16) traced to one-off scripts bypassing canonical tooling |

---

## Current S3 Protection Layers

1. **S3 versioning** — delete markers recoverable (safety net)
2. **Bucket policy** — `matthew-admin` cannot delete from data prefixes (hard blocker)
3. **safe_sync.sh** — blocks root syncs, dryrun gate on deletion count (process guard)
4. **Canonical deploy scripts** — `sync_site_to_s3.sh` uses `S3_PREFIX="site"` (correct targeting)

---

## Known Issues

- `raw/test_policy_check.txt` — test file from bucket policy verification, cannot be deleted by `matthew-admin` due to the policy. Remove by temporarily suspending bucket policy or using a different IAM principal.
- Config `requirements/*.txt` were not in the original `config/` directory in git — they live under `lambdas/requirements/` and were synced to S3 `config/requirements/`. This S3 path may differ from what Lambdas expect; verify next session.
- Root-level website files (from the broken sync) may still exist at bucket root alongside `site/` copies. Cleanup deferred to avoid more deletions during incident response.

---

## Pending Next Session

| Item | Priority | Notes |
|------|----------|-------|
| Clean up root-level site files | Low | `index.html`, `assets/`, `data/`, `character/`, `journal/`, `platform/` at bucket root |
| Verify all Lambda scheduled runs post-incident | Medium | Confirm morning pipeline ran correctly on Mar 17 |
| Consider separate S3 bucket for website | Long-term | ADR-032 notes this as architecturally cleaner |
| Upload requirements to config/ if needed | Low | Verify whether config/requirements/ path is consumed by any Lambda |
| BS-03: Email capture implementation | **P0** | Carried forward from v3.7.54 |
| BS-02: Website hero redesign | **P0** | Carried forward from v3.7.54 |
| R17 Architecture Review | Deferred | ~2026-04-08 |

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `deploy/lib/safe_sync.sh` | **New** — safe S3 sync wrapper (ADR-033) |
| `deploy/deploy_v3756_restore_signal_homepage.sh` | **Deleted** — offending script |
| `docs/INCIDENT_LOG.md` | P1 entry + new patterns |
| `docs/DECISIONS.md` | ADR-032, ADR-033 |
| `docs/CHANGELOG.md` | v3.7.57 entry |
| `docs/HANDOVER_LATEST.md` | Points to this file |
