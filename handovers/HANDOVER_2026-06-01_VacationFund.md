# HANDOVER — 2026-06-01 (Vacation fund tracker + site-api deploy lesson)

**Previous handover:** `handovers/HANDOVER_LATEST.md` (ADR-069 custom routine authoring + Hevy template index + auto-create + rate-limit fix).
**This session covers:** a vacation-fund tracker ($1 per workout mile since experiment start), shipped across MCP + website + daily brief, plus a production incident + recovery on the site-api deploy.
**State:** merged to `main` (PR #6, merge `48577af`); deployed + verified live. Layer **v70 → v71**, fleet uniform on v71.

---

## What shipped

Every mile of workout distance since `EXPERIMENT_START_DATE` (2026-06-01) = $1 toward a vacation fund.

| Piece | Where |
|---|---|
| Shared compute | `lambdas/vacation_fund.py` (NEW, **layer** module) — `compute_vacation_fund(start?, end?)`. Strava daily `total_distance_miles` (base) + **opt-in additive** Hevy (`exercises[].sets[].distance_m`/1609.34) + MacroFactor (`distance_miles` or `distance_yards`/1760). Per-sport + per-source breakdown, pace, warnings. Read-only (boto3 queries + S3 config). |
| Config | `config/vacation_fund.json` (S3 `config/`): `rate_per_mile` (1.0), `start_date` (null→genesis), `included_sport_types` ("all"), `extra_sources` (["hevy","macrofactor_export"]), `manual_adjustment_usd` (0). |
| Chat | `mcp/tools_vacation.py` → `get_vacation_fund` MCP tool (registered in `mcp/registry.py`; count 139→140, bound bumped to 141). |
| Website | `lambdas/web/site_api_lambda.py` → `/api/vacation_fund` (read-only, 15m cache). |
| Daily brief | `lambdas/emails/daily_brief_lambda.py` computes the fund (try/except, non-fatal) + passes `vacation_fund=` to `html_builder.build_html`, which renders a 🏝️ banner. |

**Design choices (user-confirmed):** additive across Strava+Hevy+MacroFactor (he logs some cardio only in Hevy/MF; overlap accepted, shown per-source, correctable via `manual_adjustment_usd`); **Garmin NOT counted** (auto-syncs into Strava → double-count); all activity types; from genesis. Layer change: `vacation_fund.py` added to `deploy/build_layer.sh` + `ci/lambda_map.json` (LV4 enforces these match); `html_builder.py` also edited (both layer).

**Verified live:** MCP `get_vacation_fund` → $7 (7 Hevy miles, day 1); `/api/vacation_fund` 200 via CloudFront; daily-brief healthcheck 200. Full suite 1443 passed (7 new tests).

---

## ⚠️ Production incident + lesson: site-api is a MULTI-MODULE package

Deploying `life-platform-site-api` with `deploy/deploy_lambda.sh life-platform-site-api lambdas/web/site_api_lambda.py` (single-file) **broke prod** → `Runtime.ImportModuleError: No module named 'web.site_api_common'`. The handler `web.site_api_lambda.lambda_handler` imports many siblings (`web/site_api_common.py`, `site_api_vitals.py`, `site_api_data.py`, `site_api_intelligence.py`, `site_api_social.py`, `site_api_observatory.py`, `site_api_coach.py`). Single-file deploy dropped them.

- **`rollback_lambda.sh` did NOT help** — the saved `previous.zip` was also incomplete (site-api is normally **CDK**-deployed; deploy_lambda.sh's rollback artifact was stale/single-file).
- **Fix that worked:** rebuild the full package and `update-function-code`:
  ```bash
  rm -rf /tmp/siteapi && mkdir -p /tmp/siteapi/web && cp lambdas/web/*.py /tmp/siteapi/web/
  (cd /tmp/siteapi && zip -r /tmp/siteapi.zip web/ -x '*__pycache__*' '*.pyc')
  aws lambda update-function-code --function-name life-platform-site-api --zip-file fileb:///tmp/siteapi.zip --region us-west-2
  ```
- **Rule:** deploy site-api (and other multi-module web/* handlers) with the **full `web/` package** or via CDK — never `deploy_lambda.sh` single-file. The `deploy` skill's `life-platform-site-api → site_api_lambda.py` mapping is misleading for this; needs `--extra-files` of all web/ siblings or a full-package build. **TODO: fix the deploy skill / add a guard.**

`daily-brief` single-file deploy was fine — it imports only **layer** modules (html_builder, ai_calls, output_writers, constants, phase_filter), no siblings.

---

## Notes / follow-ups
- Fleet repointed to **v71** (63 functions, config-only) → `test_i2` green. (Required user approval — the broad fleet repoint trips the safety classifier coming out of plan mode.)
- Strava had 0 miles on genesis day; the $7 came from a Hevy-logged cycle. As Strava data accrues, cross-check `per_source.strava` vs `get_weekly_summary` to gauge Hevy/MF overlap; use `manual_adjustment_usd` to correct or to fold in the girlfriend's contribution.
- Optional future: same-day Strava↔Hevy distance-match dedup (not built; additive by design).
- Plan file: `/Users/matthewwalker/.claude/plans/generic-swimming-dragon.md`.
