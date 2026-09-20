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

---

# 2026-09-19 — the ruling on `apple_health`, and the whoop row measurement (#3677)

*Added by #3677, the issue #3666 split out when it fixed habitify and derived the rest of
the class. Two members were left open. This section rules on both. Nothing in the sections
above is edited — Phase 2's reasoning is the history this ruling is made against.*

## 1. `apple_health` — **KEEP UTC.** No flip, no backfill, consequence recorded.

The defect is real and confirmed live 2026-09-06: a `dietary_water` reading that states
its own offset — `2026-09-06 19:15:00 -0700` — was stored on `DATE#2026-09-07`. Unit
conversion, source filter and reading-level dedup were all correct; only the day moved.

It is **not** being flipped:

- **2,508 stored rows** carry the UTC frame, counted not estimated, and there is no
  backfill. Re-deriving months of CGM, steps, BP, State-of-Mind and workout aggregates
  from raw is its own job with its own idempotency proof.
- A flip without that backfill produces a **silent mid-history discontinuity** in the
  platform's densest partition — a quieter defect than the one it fixes, and one no
  consumer can detect, because both sides of the boundary look like valid days.
- Three consumers resolve the frame from the registry facet by design (#3257/#3287). A
  flip is a coordinated change across all of them plus two ratchet files that assert
  `"utc"` by name, not a one-line edit.

**The price of keeping it, written where a consumer can read it.** `day_key_frame: "utc"`
now carries a sibling facet, `day_key_frame_consequence`, on the `apple_health` entry in
`lambdas/ingestion/source_registry.py`, read through `day_key_frame_consequence_for()`:
every reading taken from **17:00 PT (PDT; 16:00 PST) until Pacific midnight lands on the
FOLLOWING Pacific day's key**, so for the last ~7 hours of every Pacific day the row keyed
with today's date is a partial *next*-day record and the owner's evening is invisible to
anything that asks for today. `tests/test_ingestion_day_key_derivation_3666.py` fails any
UTC-framed source that carries no such note — derived over `utc_day_key_source_ids()`, so
the next source to take a non-default frame inherits the requirement instead of having to
be remembered into it.

### Every consumer that presents `apple_health` rows as "today"

Derived, not recalled. The query — reproducible, and it is a member of its own result set:

```bash
grep -rnE "(apple_health|health_auto_export)[^\n]*\btoday\b|\btoday\b[^\n]*(apple_health|health_auto_export)" \
  lambdas mcp --include="*.py"
```

plus the three frame-aware readers named in the `day_key_frame` facet, plus two
single-day readers the `today`-on-the-same-line query cannot see because they bind the
day to a variable first (`evening_nudge`'s `today = pacific_today()`, `dashboard_refresh`
and `daily_brief`'s `yesterday`). **Nothing below was changed by #3677** — the ruling's
whole point is that changing them piecemeal is how a frame becomes un-auditable.

**A. Frame-aware — these already absorb the boundary (they read the facet):**

| Consumer | What it does with the frame |
|---|---|
| `lambdas/common/pacific_time.py::anchor_day_key` | THE anchor. Turns a `DATE#` day into an instant *in the frame that named it* — UTC midnight for apple_health, Pacific midnight for everything else. |
| `lambdas/emails/freshness_checker_lambda.py:654` | Ops staleness alert; ages every source's key through `anchor_day_key`, so apple_health is not reported 7h stale at the moment it is written. |
| `lambdas/web/site_api_freshness.py:173` | The public freshness board, same anchor — the surface that once served a record stamped with today's Pacific date as 21.7 hours old (#3257). |
| `lambdas/web/vitals_resolver.py:190-207` | Steps resolution; publishes `steps_as_of_frame` from `day_key_frame_for(source)` so a reader is told which calendar the number's day belongs to (#3287). |
| `lambdas/web/site_api_pulse.py:260-274` | Widens the query to today(UTC) so a boundary row is never missed, then keeps only days Pacific has actually reached — the explicit fix (#3287) for the ~7h window where `Limit=1` returned a partial next-day row. |

**B. Single-day reads — the sharp edge. These ask for one named day and get the
17:00-PT-shifted window:**

| Consumer | The consequence, stated |
|---|---|
| `lambdas/emails/evening_nudge_lambda.py:138` | **The sharpest one.** The 8 PM PT nudge asks `apple_health[DATE#pacific_today()]` for `som_check_in_count`. A How We Feel check-in logged between 17:00 and 20:00 PT is on *tomorrow's* key, so the nudge can report "No How We Feel check-in today" hours after one was recorded. |
| `lambdas/compute/dashboard_refresh_lambda.py:365` | `apple_today = fetch_date("apple_health", today)` for glucose — from 17:00 PT this row is the next UTC day's partial, which is also why #3204 had to pick the *reading* rather than the row. |
| `lambdas/web/site_stats_refresh_lambda.py:86` | `resolve_glucose(apple_health, existing_vitals, today)` — publishes the day's glucose and its `sk` date to the public stats artifact. |
| `lambdas/emails/daily_brief_lambda.py:664` | `fetch_date("apple_health", yesterday)` at 10 AM PT: "yesterday" for apple_health spans 17:00 PT of the day before to 17:00 PT yesterday. |

**C. Window reads bounded at `today` — the boundary is real but diluted across the
window; only the newest day in each is a partial next-day row:**

`lambdas/web/site_api_body.py:178` · `lambdas/web/site_api_biomarkers.py:145` ·
`lambdas/web/site_api_mind.py:146,252` · `lambdas/web/site_api_sleep.py:391` ·
`lambdas/web/site_api_physical.py:82` · `lambdas/web/site_api_training.py:361,426` ·
`lambdas/web/site_api_journey.py:124` · `lambdas/web/site_api_pulse.py:819` ·
`lambdas/intelligence/ai_expert_analyzer_lambda.py:272,357,502` ·
`lambdas/coach/spiral_breaker.py:570` · `lambdas/content/output_writers.py:767,800` ·
`mcp/ritual_triggers.py:120`

**Not enumerated on purpose:** the ~50 further modules that touch the `apple_health`
partition without a today-bound (range extracts, correlation windows, field-tier and
manifest declarations). They inherit the frame, but they do not *present* a row as today,
which is the question this box asked.

## 2. `whoop`'s reconciler — **measured first, and the measurement reversed the finding**

#3666 registered `whoop_lambda.py` as the second open member on this reasoning: the
reconciler computes its expected keys with `_utc_day(sleep["start"])` while "the real
writes go through `ingestion_framework` in the Pacific frame", so the frames must disagree
for the evening PT hours.

**The premise is false.** The framework enumerates Pacific date *labels*
(`pacific_today()` backwards), but whoop's `fetch_day` turns each label into a UTC
*window* (`{d}T00:00:00.000Z` .. `{d+1}T00:00:00.000Z`) and `transform` files whatever the
window returns under that same label. A whoop `DATE#{d}` therefore names the **UTC day
`d`** — which is exactly what this audit's own cross-source matrix recorded in 2026-05
(*"Whoop today, 9pm PT → `DATE#2026-05-03`"*), four months before #3666 re-derived a
different belief from the framework's stamp.

**Blast radius, measured read-only before touching anything** (`aws dynamodb query` on
`USER#matthew#SOURCE#whoop`, projecting `sk`, `sleep_start`, `start_time`; 4,858 rows):

| Rows whose start straddles the boundary (UTC day ≠ Pacific day, i.e. 17:00 PT–midnight) | n | keyed by **UTC** day | keyed by **Pacific** day |
|---|---|---|---|
| daily aggregates (`sleep_start`) | 1,649 | **1,649** | **0** |
| workout sub-records (`start_time`) | 600 | **600** | **0** |
| **total** | **2,249** | **2,249** | **0** |

Range `2026-09-19` back to `2020-03-23`. The live instrument agrees:
`LifePlatform/IngestReconciliation::MissingActivityCount{Source=whoop}` = **0 on 30 of 30
consecutive daily runs, 2026-08-19 … 09-17** — which a frame disagreement could not
produce, since a main sleep starts after 17:00 PT nearly every night.

(37 daily rows match *neither* frame — sleeps that began 22:00–24:00 UTC filed on the next
UTC day. All are 2021-2025 bulk-import rows; **zero since 2026-01-01**, i.e. none from the
live writer. Noise from the historical import, not a third generation.)

**Ruling: the reconciler stays UTC — it is correct, by measurement rather than by
exemption**, and re-framing it to Pacific would mint a phantom gap most nights and hold
the reconciliation alarm red. The registry row in
`tests/test_ingestion_day_key_derivation_3666.py` moves from *undeclared residual* to
*measured and correct*, with the numbers in the reason; the belief is pinned behind
`tests/test_whoop_reconciler_frame_3677.py`, which fails if the frame is ever flipped.
The existing `tests/test_whoop_reconcile.py` was run against that flip and passed all 6 —
it could not see a whole-frame re-derivation, which is why the new file exists.

### The residual this leaves open (named, not folded in)

`source_registry` carries **no** `day_key_frame` for whoop, so the facet reads as the
`pacific` default while the keys are measurably UTC. Flipping the facet is not a
bookkeeping edit: `day_key_frame` feeds `utc_day_key_source_ids()`, which
`freshness_checker_lambda` and `site_api_freshness` use to anchor an **age**, so it moves
a reader-facing freshness number for whoop by 7 hours — the #3257 shape, needing its own
consumer sweep and its own `day_key_frame_consequence`. It is declared in-place at the
skip in `test_the_declared_frames_agree_with_the_live_source_registry` rather than changed
here, so the disagreement is visible to the next reader instead of resolved by silence.

**CLOSED 2026-09-19 by #3913** — the facet now says `utc`. The flip, its consumer sweep
and the live before/after are the last section of this file; this paragraph is left as
written so the residual and its closure can be read in order.

---

# 2026-09-19 — Box B consumer fixed: `evening_nudge_lambda.py:138` (#3914)

The line named above as "the sharpest one" — the 8 PM PT nudge's `som_check_in_count`
read — now folds in the next UTC day's row (the `reached_in_pacific` shape from #3287,
gated on the registry's `day_key_frame` facet so it only bites a UTC-framed source). A
check-in logged 17:00–20:00 PT counts on the same evening's nudge instead of being
reported missing until tomorrow. `apple_health`'s stored key frame is unchanged (#3677's
KEEP-UTC ruling stands) — this is the reader, not a re-key. Test:
`tests/test_som_checkin_frame_3914.py`. The remaining Box B rows
(`dashboard_refresh_lambda.py:365`, `site_stats_refresh_lambda.py:86`,
`daily_brief_lambda.py:664`) and all of Box C are untouched.

---

# 2026-09-19 (late) — closing the residual: `whoop` takes the `utc` facet (#3913)

*Added by #3913. Scope: **one facet and the arithmetic it feeds.** No ingestion code, no
stored key and no backfill — the store was already measured correct by #3677 above, and
`tests/test_whoop_reconciler_frame_3677.py` still fails anyone who re-frames the writer.*

## The ruling

`lambdas/ingestion/source_registry.py`'s `whoop` entry carries
`"day_key_frame": "utc"` plus the required `day_key_frame_consequence`. `whoop` is
therefore the **second** member of `utc_day_key_source_ids()`, and the set is now a set
rather than "the HAE exception" — which matters, because the two members got there by
different routes: apple_health converts to UTC *in the handler* (TD-19 Phase 2), whoop
never converts anything — `fetch_day` turns a Pacific date **label** into a UTC **window**
and files what comes back under that label. The frame follows the fetch, not the stamp,
and the only way to know which is to measure the partition.

## The measurement, re-run for this flip

Read-only `aws dynamodb query` on `USER#matthew#SOURCE#whoop`, projecting
`sk, sleep_start, start_time`, 2026-07-01 … 2026-09-19 (134 rows):

| Rows whose start straddles the boundary (17:00 PT–midnight) | n | keyed by **UTC** day | keyed by **Pacific** day |
|---|---|---|---|
| daily aggregates (`sleep_start`) | 57 | **57** | **0** |
| workout sub-records (`start_time`) | 9 | **9** | **0** |
| **total** | **66** | **66** | **0** |

Consistent with #3677's whole-history count (2,249 of 2,249, 2020-03-23 …). Two live rows
show the shape directly: `DATE#2026-09-18` holds a sleep begun **21:46 PT on 09-17**, and
`DATE#2026-09-19` one begun **21:44 PT on 09-18** — the key names the UTC day, never the
Pacific day the sleep started in.

*(4 workout rows in that window match neither frame: they start 23:0x–23:5x **UTC** and are
filed on the next UTC day — the provider window catches a workout that *ends* inside it.
Start-vs-end, not Pacific-vs-UTC; none of them is a Pacific keying, so the ruling is
unaffected. Named here rather than rounded away.)*

## The consumer sweep (#3257's shape)

Derived, not recalled:

```bash
grep -rn "utc_day_key_source_ids\|day_key_frame_for" lambdas mcp scripts deploy --include="*.py"
```

**Every reader of the facet, and what the flip does to it:**

| Reader | Verdict |
|---|---|
| `lambdas/common/pacific_time.py::anchor_day_key` | THE anchor, and the only code path that behaves differently: a whoop `DATE#{d}` is now anchored at `{d}T00:00Z` instead of `{d}T00:00-07:00`. |
| `lambdas/emails/freshness_checker_lambda.py:654` | Ops staleness alert. Age +7h (PDT) / +8h (PST). **Tier unchanged at the instant it runs** — `cron(45 16 * * ? *)` = 09:45 PT, where a 0/1/2-day-old key scores 16.75h / 40.75h / 64.75h against thresholds 24 (warn) and 48 (stale), the same three tiers the Pacific anchor produced (9.75h / 33.75h / 57.75h). No new alarm noise; pinned by `test_the_ops_alert_tier_is_unchanged_at_the_checkers_own_schedule`. |
| `lambdas/web/site_api_freshness.py:173` | Public freshness board, same helper, so the two consumers still agree to 0.05h. Live 24/7, so this one *can* mark whoop `stale` up to 7h earlier after a ≥2-day gap — the intended effect: the data was that old the whole time. |
| `lambdas/web/vitals_resolver.py:207` | Reads the facet only to LABEL steps (`steps_as_of_frame`), and whoop is not a steps source. Its whoop scan is guarded by `reached_in_pacific`, which compares a stored day against the Pacific calendar and never asks the frame — so it was already correct for a UTC-keyed whoop. **No change.** |
| `lambdas/emails/evening_nudge_lambda.py:162` | Added by #3914 between this flip's sweep and its merge (re-derived after the merge, not assumed): it reads the facet for **`apple_health` by name** to decide whether to fold in the next UTC day's row. The nudge never reads the whoop partition, so the flip does not reach it. |
| `utc_day_key_source_ids()` | Production callers: none. Read by `tests/test_freshness_age_frame_3257.py` and `tests/test_ingestion_day_key_derivation_3666.py` (the latter derives the "a UTC frame must state its price" requirement over it, which is how whoop acquired its consequence note). Both updated. |

**Adjacent, frame-blind by construction (checked, unchanged):**
`lambdas/web/site_api_sleep.py` presents a whoop `DATE#` row as the **wake date** — which
for an overnight sleep *is* the UTC day of the start (a 22:00 PT bedtime is 05:00Z the
next morning), so the convention it publishes is already the UTC frame under another name.
It ages nothing. `lambdas/ingestion/whoop_lambda.py`'s reconciler derives the key itself
and never reads the facet.

## The live before/after

Measured 2026-09-19 23:07 PT — deliberately **inside** the straddling window, since the
defect is invisible for the other 17 hours of the day.

| | value |
|---|---|
| newest stored key | `DATE#2026-09-19#WORKOUT#d9c333af…` (the `[:10]` slice both consumers take → `2026-09-19`) |
| live board, pre-flip (`/api/source_freshness`) | `last_update 2026-09-19`, `age_hours 23.1`, `last_update_ts 2026-09-19T00:00:00-07:00` |
| this branch, same key, same instant | `age 30.12h`, anchor `2026-09-19T00:00:00+00:00` |
| understatement removed | **7.00h**, exactly the PDT offset |

The anchor is now the start of the window the record actually came from: the row's own
instant falls inside `[anchor, anchor+24h)`. **Post-merge, the same curl should report
`last_update_ts … +00:00` for whoop and an age ~7h higher than the Pacific-anchored one**
— that is the deploy proof, and it needs `site-api` deployed before it can be true.

## What this does NOT do

- It does not re-key anything. `#3232`'s ruling (the stored key is correct, clamping is the
  wrong fix) stands, and an ahead-of-PT whoop day still ages honestly from its own UTC
  midnight and keeps its own date, with the board's derived `frame: "utc"` label.
- It does not touch the reconciler or the writer. Re-framing either would mint a phantom
  nightly gap — the thing #3677 measured and pinned.
