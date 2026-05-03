# TD-19 — Cross-source date partition audit (Phase 1)

**Date:** 2026-05-03
**Source spec:** `docs/specs/TD-19_DATE_PARTITION_FIX.md`
**Phase:** 1 of 4 (audit only — Phase 2 fix-forward gated on Matthew approval)
**Verdict legend:**
- ✅ **UTC** — Lambda derives partition key from a UTC timestamp; cross-source consistent.
- ❌ **PT-local / source-tz needs fix** — partition key reflects the timestamp's original timezone, not UTC. Two sources observing the same wall-clock event can land on different partitions.
- ⚪ **N/A — event-anchored** — Lambda does not derive the partition key from "now"; it uses a date that's intrinsic to the event (lab draw date, file import date in source CSV). No cross-source ambiguity.

---

## Audit method

For every Lambda that writes a `DATE#` partition key:
```bash
grep -nE 'DATE#|date_str|datetime\.now|date\.today|astimezone|timezone\.utc|pytz|zoneinfo' lambdas/<lambda>.py
```

Then read the date-keying code path and classify how the partition key is derived. Where the partition key comes from external data (a webhook payload, a third-party API response), the audit also notes which timezone the SOURCE provides.

---

## Per-Lambda findings

| Lambda | Verdict | Where partition key comes from | Notes |
|---|---|---|---|
| `whoop-data-ingestion` | ✅ UTC | `datetime.now(timezone.utc).date()` (lambdas/whoop_lambda.py:161) | Cleanly UTC. Iterates 7 days back from UTC today. |
| `garmin-data-ingestion` | ✅ UTC (effectively) | API-driven `date_str` | Calls Garmin API per-day with `date_str`. Lambda's outer loop derives `date_str` from UTC `datetime.now`. |
| `withings-data-ingestion` | ✅ UTC | `datetime(target_date.year, ..., tzinfo=timezone.utc)` (line 186) | Window construction uses explicit `timezone.utc`. Stores `measurement_time_utc` as ISO format. |
| `strava-data-ingestion` | ✅ UTC | `datetime.now(timezone.utc)` (line 97), activities sk = `DATE#{date_str}` from activity start | Activity dates pulled directly from Strava API which uses UTC. Lambda token-refresh uses UTC throughout. |
| `eightsleep-data-ingestion` | ⚪ Event-anchored (special) | `wake_date` derived from sleep session intent | Sleep sessions starting evening of D and ending morning of D+1 → stored under `DATE#(D+1)` (the wake date). This is intentional semantic, not a TZ bug. Comment line 8 explains. **No fix needed**. |
| `habitify-data-ingestion` | ⚪ Event-anchored | `target_date` passed in, partition `sk = DATE#{target_date}` | Habitify API's `target_date` is per-habit-completion. Partition matches habit's logical day. Not "now"-anchored. |
| `todoist-data-ingestion` | ✅ UTC | `datetime.now(timezone.utc).replace(hour=0,...)` (line 165) | Yesterday's window in UTC. Clean. |
| `notion-journal-ingestion` | ⚠️ **Mixed — explicit PT** | `from zoneinfo import ZoneInfo` (line 33), `astimezone(pt)` (line 414) | Imports a `pt` ZoneInfo. Journal entries' `Date` property comes from Notion (user-set). Partition matches Notion's `Date` value — which is whatever the user typed. **Probably correct semantically** (journal entries belong to the day the user marked them, not to UTC midnight of when Notion's API was hit), but worth flagging — different from the other Lambdas' UTC discipline. |
| `health-auto-export-webhook` | ❌ **PT-local — source-tz needs fix** | `parse_date_str(date_str)` returns `date_str[:10]` (line 164) | Strips the date part of a timestamp like `"2026-05-02 21:00:00 -0700"` → `"2026-05-02"`. The date reflects the timestamp's original timezone (typically PT for an iOS device in California). **The TD-19-flagged case.** A 9pm PT workout lands at `DATE#2026-05-02`; the same instant in UTC (04:00 May 3) would land at `DATE#2026-05-03`. |
| `apple-health-ingestion` | ❌ Same shape as HAE | `parse_date(date_str)` returns `date_str[:10]` (line 140) | Same trust-the-timestamp pattern. Same fix shape. (S3-triggered; reads exported XML, not webhook.) |
| `macrofactor-data-ingestion` | ⚪ Event-anchored | CSV row's `Date` field, `datetime.strptime(date_str, fmt)` (line 134-136) | Date comes from MacroFactor's CSV, which uses the user's local date. Each row already has a date; Lambda just normalizes the format. Not derived from `datetime.now`. |
| `weather-data-ingestion` | ✅ UTC (effectively) | `date_str` passed into `fetch_day(creds, date_str)`, used in API request | Visual Crossing API call uses the date as-is. Outer loop derives date in UTC. |
| `dropbox-poll` | ⚪ N/A | Polling-only Lambda; doesn't write `DATE#` partitions itself | Triggers downstream MacroFactor processing. Date logic happens there. |
| `measurements-ingestion` | ✅ UTC | `datetime.now(timezone.utc).strftime("%Y-%m-%d")` (line 135) | Clean UTC. Partition `sk = DATE#{session_date}` where `session_date` is set explicitly. |
| `food-delivery-ingestion` | ✅ UTC | `datetime.now(timezone.utc).strftime('%Y-%m-%d')` (line 51) | Clean UTC for the import date. Per-transaction dates come from the source CSV (event-anchored). |
| `function-health` ingest | ⚪ Event-anchored | Uses explicit lab `draw_date` from PDF source | Lab draws have an intrinsic date (the day blood was drawn). No "now"-anchoring. |

---

## Companion: backfill scripts

| Backfill | Verdict | Notes |
|---|---|---|
| `backfill/backfill_apple_health_export_v16.py` | ❌ Same as HAE | `parse_dt(date_str)` returns `date_str[:10]` (line 252-255). Same trust-the-timestamp pattern. Backfill consistency depends on this matching the live Lambda. **A fix to HAE Lambda WITHOUT a corresponding fix to this backfill would re-introduce drift on the next backfill run** — TD-14 parity-debt scenario. |

---

## Cross-source verification matrix

For 2026-05-02, here's where each source's "today" data should land:

| Wall-clock event | HAE today | Withings today | Whoop today | Garmin today | Strava today |
|---|---|---|---|---|---|
| 9pm PT (04:00 UTC May 3) | `DATE#2026-05-02` ❌ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ |
| 4am PT (11:00 UTC) | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ | `DATE#2026-05-03` ✅ |

The **9pm PT case** is the visible discrepancy. Workouts logged in the evening land at HAE's PT-local day but at every other source's UTC day → cross-source aggregation by day silently undercounts whichever source is on the "wrong" partition for the question being asked.

---

## Sources verdict summary

| Verdict | Count | Lambdas |
|---|---|---|
| ✅ UTC | 8 | whoop, garmin, withings, strava, todoist, weather, measurements, food-delivery |
| ❌ PT-local needs fix | 2 | **health-auto-export-webhook**, **apple-health-ingestion** |
| ⚪ Event-anchored (no fix needed) | 5 | eightsleep (wake-date semantic), habitify, macrofactor, dropbox-poll, function-health |
| ⚠️ Notion (explicit PT, intentional?) | 1 | notion-journal-ingestion — flag for Matthew's call |
| Backfill drift | 1 | `backfill_apple_health_export_v16.py` (mirrors HAE — must be fixed in same PR per TD-14) |

---

## Open questions for Matthew (gate Phase 2 on these)

1. **Confirm UTC over PT-local**, per spec recommendation. (No new info from this audit; the original spec's reasoning still holds.)
2. **Notion journal — keep PT-local or migrate to UTC?** This is the only Lambda I'd want explicit confirmation on. The user types a journal `Date` in Notion's UI; the Lambda trusts that value. Migrating to UTC would mean the Notion-typed date might not match the partition (Matthew journals at 11pm PT on May 2 → Notion `Date=2026-05-02` → if we partition at `DATE#2026-05-03 (UTC)`, the journal "lives" on a day that doesn't match what Matthew typed). Recommendation: **keep the Notion path as-is** (event-anchored to the user-typed date), but document that Notion is intentionally an exception.
3. **Migration urgency.** Phase 2 (HAE + apple_health Lambda fix) stops new corruption. Phase 3 (historical migration) is expensive — only worth doing if cross-source correlations from past months are load-bearing for ongoing intelligence work. Per spec: "interim policy" is a valid stopping point.
4. **Per-source rollout vs all-at-once for Phase 2.** Recommendation: HAE + apple_health together (they share the same root cause and same `parse_date_str` pattern). Plus the v16 backfill in the same PR per TD-14 parity discipline.

---

## Next step

This audit unblocks Phase 2 (fix-forward in HAE + apple_health Lambdas + v16 backfill). I am stopping here per the brief. Matthew approves Phase 2 separately.

Phase 2 scope (preview):
- `lambdas/health_auto_export_lambda.py`: `parse_date_str` and `parse_timestamp` need to convert the timestamp to UTC before stripping. Specifically, parse the source TZ offset from the input string, convert to UTC, then format as `YYYY-MM-DD`.
- `lambdas/apple_health_lambda.py`: same fix on `parse_date(date_str)`.
- `backfill/backfill_apple_health_export_v16.py`: same fix on `parse_dt(date_str)`. Per TD-14, ship in the same PR.
- Phase 3 historical migration: separate PR. Higher risk (DDB cost, idempotency).
