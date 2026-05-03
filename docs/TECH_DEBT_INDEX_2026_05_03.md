# Tech Debt Index — Post-Restoration (2026-05-03)

**Source:** v6.8.1 carry-forwards (TD-11 through TD-20) + 2026-05-02 evening session discoveries (TD-21, TD-22, TD-23) + AJM Re-Entry Plan Phase 8 items.
**Ordering principle:** severity first, then effort.

---

## HIGH severity — production correctness or major architectural risk

### TD-15 — HAE Lambda missing source-priority fix
**File:** `lambdas/health_auto_export_lambda.py`
**Carry-forward from:** v6.8.1
**Symptom:** iPhone+Garmin step double-counting in production today; mL→fl_oz water unit drift; `weight_body_mass` field-name mismatch (TD-18 same root cause).
**Fix:** Port `SOURCE_PRIORITY` dict from `backfill/backfill_apple_health_export_v16.py` into the live Lambda.
**Effort:** 30-45 min.
**See:** `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.

### TD-19 — Cross-source date partition mismatch (UTC vs local-PT)
**Files:** Multiple Lambdas — needs audit.
**Carry-forward from:** v6.8.1.
**Symptom:** HAE writes today's data at `DATE#<PT-local>`, Withings at `DATE#<UTC>`. Same wall-clock event lands in different DDB partitions. Daily aggregation silently undercounts; cross-source correlations will produce systematically wrong outputs as more sources come online.
**Fix:** Pick UTC as the canonical convention. Audit every ingestion Lambda. One-time backfill rewrite for Lambdas on the wrong convention.
**Effort:** 2-3 hours + 30 min backfill.
**See:** `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`. **Do this in a dedicated session, not folded in with other patches.**

### TD-21 — `mcp/tools_lifestyle.py` missing `timezone` import
**File:** `mcp/tools_lifestyle.py:9`
**Discovered:** 2026-05-02.
**Symptom:** ~40 functions in the file fail with `NameError: name 'timezone' is not defined` at runtime. Three functions (lines 3090, 3136, 3222) work via local imports. Bug masked for weeks because platform was silent.
**Tools confirmed broken:** `create_experiment`, `log_supplement` (likely). Untested but probably broken: `log_temptation`, `log_travel`, `log_interaction`, jet-lag tools, supplement reads, BP logs.
**Fix:** One-line patch (add `, timezone` to existing import). Redeploy MCP Lambda.
**Effort:** 2 min + 5 min for the deploy.
**See:** `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.

### TD-23 — MCP Lambda IAM role missing `secretsmanager:GetSecretValue` on `life-platform/todoist`
**Resource:** `LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW`
**Discovered:** 2026-05-02.
**Symptom:** All MCP Todoist write tools fail with `AccessDeniedException`. Reads work because Todoist `_list_all_tasks` apparently uses cached token (verify).
**Fix:** Add `life-platform/todoist*` to the role's `secretsmanager:GetSecretValue` policy. Prefer CDK fix; inline policy as hotfix.
**Effort:** 5 min CDK or 1 min inline.
**Audit:** While in the role, diff what secrets MCP code reads from vs what the role permits. There may be more.
**See:** `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.

---

## MEDIUM severity — correctness or strategy issues

### TD-11 — Habitify writes 65 phantom-failed habits per day
**Carry-forward from:** v6.8.1.
**Symptom:** Full habit registry written daily as `0.0` even when user hasn't completed any. No distinction between "not done yet" and "actively skipped." Affects streak calculation.
**Fix:** Strategic, not quick. Touches Habitify Lambda + scoring engine + Habitify completion-API contract.
**Effort:** Half-day minimum. Defer until Pause Mode (WR-35) is built — Pause Mode pattern of distinguishing `paused` from `failed` is precedent for the same `not_yet` vs `skipped` distinction.

### TD-14 — Backfill scripts drift from live Lambdas
**Carry-forward from:** v6.8.1.
**Symptom:** v16.1 backfill has source-priority fix; live HAE Lambda doesn't.
**Fix:** Address as part of TD-15. Going forward, add a CI invariant that compares backfill vs live Lambda field-mapping logic.
**Effort:** Folded into TD-15.

### TD-16 — Apple Health "Connect" inflates Garmin activity ~2x
**Carry-forward from:** v6.8.1.
**Symptom:** Garmin syncs to Apple Health, which writes back under non-iPhone source name, double-counting steps in apple_health + garmin partitions.
**Fix:** Folded into TD-15 (same SOURCE_PRIORITY fix).
**Effort:** Folded into TD-15.

---

## LOW severity — annoyance or cosmetic

### TD-12 — Todoist Lambda phantom no-op invocations every 4hr
**Carry-forward from:** v6.8.1.
**Symptom:** Cron fires every 4 hours; Lambda no-ops if no changes. 6 wasted invocations/day.
**Fix:** Reduce schedule to daily, OR add EventBridge throttle, OR move to Todoist webhooks.
**Effort:** 15 min for schedule change. Webhook migration is a half-day.

### TD-13 — No central secret-name reference
**Carry-forward from:** v6.8.1.
**Symptom:** Discovered Todoist's API key actually lives at `life-platform/ingestion-keys`, not `life-platform/todoist`. Required code archaeology.
**Fix:** Add a `docs/SECRETS.md` or similar — single canonical map of source → secret name.
**Effort:** 30 min audit + write-up.
**Compounds with:** TD-23 audit findings.

### TD-17 — HAE Tier 2 feeds dropped 100%
**Carry-forward from:** v6.8.1.
**Symptom:** HR/RHR/SpO2 from Health Auto Export iOS app sent but filtered out (Whoop is source of truth). Wasted Lambda invocations.
**Fix:** Disable Tier 2 feeds in iOS app config OR add fast-reject path in Lambda.
**Effort:** 5 min iOS app config.

### TD-18 — HAE weight feed name mismatch
**Carry-forward from:** v6.8.1.
**Symptom:** Live Lambda METRIC_MAP expects `body_mass`; iOS export sends `weight_body_mass`. Currently captured fine via `weight_lbs_apple` redundant field.
**Fix:** Folded into TD-15.

### TD-20 — `platform_logger.py` TypeError on exception formatting
**Carry-forward from:** v6.8.1.
**File:** `lambdas/platform_logger.py:103`
**Symptom:** Every error log line spawns secondary traceback `TypeError: 'bool' object is not subscriptable` in `formatException()`. Cosmetic but pollutes logs.
**Fix:** `logger.error("...", exc_info=True)` is passing `True` where `sys.exc_info()` tuple is expected. Either change call sites to pass tuple, or fix `formatException` to handle bool.
**Effort:** 15 min.

### TD-22 — `get_todoist_projects` registry mismatch
**Discovered:** 2026-05-02.
**File:** `mcp/tools_todoist.py:399`
**Symptom:** Function takes 0 args; dispatcher passes 1. `TypeError`.
**Fix:** Change signature to `def get_todoist_projects(args=None):`.
**Effort:** 2 min.
**See:** `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.

---

## Resolved during 2026-05-02 session — no action needed

### Phase 8 plan flag — `list_protocols` Lambda timeout
**Status:** Resolved. Cold-start issue. Worked fine in 2026-05-02 evening session.

### Phase 8 plan flag — `get_field_notes` Lambda timeout
**Status:** Resolved. Same cold-start pattern. Worked fine.

### Phase 8 plan flag — `chronicling internal` table 6mo stale
**Status:** Unverified. Re-check in next session. Likely deprecated artifact per the plan's read.

### Phase 8 plan flag — `dropbox_poll` Lambda null
**Status:** Unverified. Probably resolved as part of HAE backfill (which uses Dropbox). Re-check.

---

## Patterns observed across the debt

1. **The platform was never end-to-end exercised during the silence.** Every TD-21/22/23 bug is something that would have been caught the first day a user invoked the affected tool. Suggests: add a daily "smoke test" Lambda that exercises every MCP tool with a benign payload and alerts on failures. Cheap, high signal.

2. **Date-handling is the most common single source of bugs.** TD-19 (partition convention), TD-21 (timezone import), TD-20 (related). Timezone-aware datetime handling needs a single utility module that all Lambdas import from. Probably already exists in some form; the architectural fix is making it canonical and removing one-off date-handling.

3. **IAM drifts as Lambdas evolve.** TD-23 surfaced because someone added Todoist write access to MCP after the role was last updated. Pattern: every new MCP tool that calls a Secrets Manager secret needs an IAM update, and this is currently manual. Suggests: a `make audit-iam` script that diffs MCP secret reads against role policy.

4. **Backfill-to-Lambda drift is the highest-cost class of bug.** TD-14/15/16/18 are all this same pattern. The backfill script gets the latest fixes; the live Lambda lags. Suggests: shared library between backfill and live Lambda for any non-trivial transformation.

These four patterns are themselves design improvements worth a separate architecture session.
