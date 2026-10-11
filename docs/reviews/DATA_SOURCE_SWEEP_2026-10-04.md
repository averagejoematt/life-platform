# Data-source sweep — 2026-10-04

Read-only audit of every ingestion, end to end — read, update and write sides. Eight audit
lanes, then eight independent verifiers that re-proved each P1/P2 against the repo at
`ee18b3c9a` and live AWS state. The audit itself changed nothing.

This is the public-safe edition. The raw lane and verifier evidence is held privately
because it carries personal health values, habit names, journal dates and security detail;
finding ids below (C1, G-1, A-W1 …) are stable references into it. Every finding is tracked
on GitHub under the label `review:data-source-sweep-2026-10-04` — see §6 for the map. Each
issue carries its own repo evidence, so it can be reproduced from the public repo alone.

**Owner rule adopted from this sweep (2026-10-04):** ingestion writers capture everything
the vendor sends, per source, and never merge, max, dedup or pick a winner across sources
at write time; interpretation, combining and discounting happen later, in one read-side
resolver keyed on field + source. Epic #4624 carries it.

**Severity:** P1 = a wrong number a reader sees, or data loss, happening now · P2 = wrong or
lossy but contained, or latent with real exposure · P3 = hygiene or opportunity.

**Verification tally:** ~129 findings checked · 118 confirmed · 6 plausible · 4 refuted ·
1 split. About 30 confirmed findings had their severity lowered. Four lane-rated P1s went
in; two came out as P1.

---

## 1. Summary

### The two P1s

**P1-a · Zone 2 on the public training page is far too high (G-1).**
`/api/training_overview` serves a weekly average of 940 min (627% of target); `/api/zone2`
serves 517.8 for the current week. The vendors' own time-in-zone for the week of 09-28 is
38 min (Whoop) or 83–115 min (Strava). Rendered on the current site by
`site/assets/js/evidence_body.js:968`.

| Stage | 28-day avg / week |
|---|---|
| Strava time-in-zone, after dedup | 73 |
| Whole activity counted when its average HR falls in the page's band | 487 |
| + dedup keeps Hevy's 2.5–3.5 h lifting copy with Whoop's average HR grafted on | 634 |
| + Hevy cardio blocks (475 min of them inside sessions already counted) | 940 |

No ADR or issue defines Zone 2 this way, and the page's heart-rate band starts lower than
the vendors' Zone 2 floor appears to (inferred from zone splits). Time in the page's own band cannot be
derived from stored data but cannot exceed 364 min, so the overstatement is at least ~2.1×.
**Needs a ruling: what Zone 2 means on the site.**

**P1-b · Apple Health daily activity totals are undercounted (C1).**
The export app switched to incremental payloads around 2026-06-20/21. The Lambda keeps
`GREATEST(stored, new)` per payload, so it stores the largest single sync of the day.
Stored equals the largest payload on 55 of 55 field-days checked.

| UTC day | Steps stored ÷ delivered | Basal energy stored ÷ delivered |
|---|---|---|
| 10-01 | 0.75 | 0.32 |
| 10-02 | 0.50 | 0.37 |
| 10-03 | 0.60 | 0.46 |

Affects `steps`, `active_calories`, `basal_calories`, `distance_walk_run_miles`,
`flights_climbed`. Served verbatim by `/api/pulse_history`, `/api/training_overview`,
`/api/weekly_physical_summary`, `/api/fingerprint`; half the day-grade movement score is
these steps (G-9). Two caveats the verifier added: on non-walk days the phone itself
delivers roughly a third of the steps Whoop records, so fixing the
Lambda does not by itself give a true total; and a backfill recovers only what was
delivered. **Needs a ruling: per-reading store vs app setting, the backfill, and whether
steps should come from Whoop.**

### The next eight

3. **Whoop heart-rate zones are all stored as 0 (A-W1, P2).** Code reads `zone_duration`;
   the payload key is `zone_durations`. Rebuildable from raw. Must ship *with* the Zone 2
   fix and the duplicate fix below, or it adds a fourth stack to P1-a.
4. **Whoop workout rows: duplicates and a polluted reader (A-W2/F1, P2–P3).** 181 of 2,520
   workout ids sit under two date keys. `/api/training_overview` serves
   `whoop_workout_count: 100` against 63 real workouts and `avg_strain` 10.0 against 11.9,
   because the reader's key range mixes day rows with workout rows.
5. **Whoop sport names are wrong (A-W3, P2).** 21 of 24 hand-written labels disagree with
   Whoop's published table; raw `sport_name` is correct. Served on the public training API.
6. **Eight Sleep partial nights stored as full (A-E2, P2).** 9 of 34 Sep–Oct nights carry
   `incomplete: true`; one is stored at a small fraction of its real length.
7. **A deleted KMS key (A-X7, P2).** 25 raw objects written 05-16 21:31Z → 05-17 21:44Z are
   unreadable: Apple Health 14 (cannot be re-fetched), Withings 5, Whoop 3, Todoist 2,
   Strava 1. No backup copy for the three sampled. Other prefixes and months not checked.
8. **Notion reconcile can delete sibling entries (N1, P2), and re-keying strips enrichment
   (N1-b, P2).** No guard; 14 dates / 42 rows exposed. Likely fired once.
9. **Habits are keyed by display name (H1/G-3, P2) and un-ticks never propagate (H2, P2).**
10. **The inbound-email capture path under-verifies the sender (P2).** Class-level only
    here; see #4633 (evidence held privately).

### Themes

- **Totals are assembled differently by every reader.** There is no single resolver: the
  source-of-truth map has two callers, and each consumer hardcodes a source and its own
  dedup. Both P1s are instances.
- **Identity is the display name** for habits, supplements, Todoist projects and Notion
  templates. Hevy is the exception (stable `template_id`) and is the model to copy.
- **Edits and deletes mostly do not flow back.** Only Hevy propagates at any age. There is
  no ledger for correcting a stored value; hand patches are overwritten on refresh.
- **The fleet is healthy and cheap.** No stale source, auth failure or reconciliation miss
  in 30 days. Ingestion costs ~$18–19/month of a $137.15 September bill; Lambda compute is
  inside the free tier. The waste is API churn and token rotation, not money.
- **Several day-key candidates were already ruled** (Whoop and Apple Health stay UTC,
  #3913/#3677). Withings and Todoist are the unruled exceptions, and are rare.

---

## 2. Source by source

### Whoop
*Today:* framework poll 5×/day + 17:30Z refresh + daily reconcile; v2 API; UTC day key by
ruling; rotating single-use refresh token. Clean for 14 days.
*Working:* rotation-loss handling, reconciler, absence markers, `records[0]` (right on
29/29 days), first-page reads (max 12 workouts/day vs limit 25).

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Zones stored 0 — field-name typo (A-W1) | P2 | Read `zone_durations`; rebuild history from raw; ship with the Zone 2 definition | with P1-a |
| Workouts under two date keys (A-W2/F1) | P2–P3 | File each workout once; delete 181 duplicates | which day a workout belongs to |
| Reader mixes day and workout rows: count 100 vs 63, `avg_strain` 10.0 vs 11.9 | P2 | Split the key range in `site_api_training.py`; #3442 fixed this class elsewhere | no |
| Sport names wrong on 21 of 24 ids (A-W3) | P2 | Use the payload's `sport_name`; downstream code special-cases the wrong labels | yes — relabel history |
| Secret written back on every run (280 in 14 d) | P3 | Write only on real rotation | no |
| Fields dropped: steps (present since 09-21), sleep need, band-off, `timezone_offset` (A-W5/6) | P3 | Pick which to keep; `timezone_offset` is a free travel signal | yes |
| Deletes/edits not propagated; v2 webhooks unused (A-W7) | P3, plausible | Reconciler store→API direction | no |
| Unused scopes; stale "every hour" docstring; unread UTC `sleep_onset_minutes` | P3 | Tidy | no |

Refuted: workout rows keyed by UTC day is a recorded ruling (#3913), not a defect.

### Eight Sleep
*Today:* framework poll 18×/day against the unofficial API; password grant; vendor wake-day key.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| `incomplete: true` nights stored as full — 9 of 34 (A-E2) | P2 | Store the flag; exclude or mark in readers; re-fetch until complete | no |
| Most of the trends payload discarded: snoring, presence, social jetlag, chronotype (A-E1) | P3 | Pick fields | yes |
| 18 polls/day for one nightly record; ~95% re-put the same row; 266 secret writes in 14 d | P3 | 3–4 runs in the morning window; write secret only on change | no |
| Offset uses today's DST for past nights (F6) | — | No wrong row in 1,032; documented as deliberate. Do not file. | — |

### Withings
*Today:* framework poll 18×/day (+4 via site-stats); one `getmeas` call; latest value per field wins.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Rotating token refreshed every run — 308 in 14 d (A-X2/H4) | P3 | Refresh near expiry, as Whoop does; cut to ~4 runs/day | no |
| UTC day key under a Pacific registry default — 17 of 1,235 rows, none this cycle (A-X1/F2) | P3 | Key by Pacific at the writer; re-key 17 rows | no |
| BodyScan / ECG / vascular fields have no consumer | P3 | Decide use (#4503 wants segmental lean) | yes |
| `attrib` ignored — a guest weigh-in would be stored as the owner's | P3 | Filter on `attrib` | no |

### Strava
*Today:* framework poll 18×/day + daily reconcile; activity-local date key; three devices
now push (Whoop 34, Hevy 27, Garmin epix 7 in 45 d).
*Working:* the read-time seam — public training numbers use the deduped set.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Kilojoules are 0 on all 1,242 rows (G-7) | P2 | Find why; the deficit tool's training channel can never fire. Add to #3754 | no |
| Deletes and edits older than 3 days never propagate (S2) | P2, plausible | Reconciler: add store→API direction | no |
| Stored day totals inflated on 16 of 31 days; seam docstring says Garmin is absent (S3) | P3 | Dedup at write as well, or stop storing totals | yes |
| `hr_recovery` is not a recovery measure; no reader (S1) | P3 | Drop the field | no |
| Zones + streams re-fetched 18×/day for 4 days though they never change (S4); 252 secret writes vs 42 refreshes | P3 | Fetch once per activity; write secret on change | no |
| Not captured: calories, Relative Effort, laps (S5) | P3 | One detail call per new activity; laps could split a Garmin record for #4424 | yes |
| Location fields never populated; enrichment label built on them (S6/E3) | P3 | Fold enrichment into ingest or retire it | yes |

### Hevy
*Today:* hourly events-feed poll (324 of 336 runs empty); per-workout rows keyed by
`template_id`; tombstones for deletes. Edits and deletes propagate at any age.
*Working:* identity, cursor discipline, routine write-back with readback verification.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Monthly digest reads a retired record shape: 0 sessions vs 24 in September (G-8) | P2 | Fix the extractor; sent email not inspected | no |
| MCP `get_workouts` returns Hevy and legacy MacroFactor rows on 421 days; periodization strength block and muscle recency read only the dead partition (G-6) | P2 | Point both at Hevy; retire the legacy bridge | no |
| No drop detector (H7) | P3 | Daily `GET /v1/workouts/count` vs stored rows | no |
| No auth breaker; truncated walk recorded as success; one bad event blocks the cursor (H1–H3) | P3, latent | Breaker + quarantine | no |
| Three names map to two templates; two templates renamed (H9) | P3 | Name-keyed consumers key on `template_id` | no |
| New write-back: `PUT /v1/workouts/{id}` is documented (H11) | P3 | Correct a mis-keyed set at Hevy instead of patching DynamoDB | yes |

Refuted: "Hevy offers webhooks" — the official spec has none. The retired webhook URL is gone.

### Garmin — reactivation decision
- **Do not reactivate the direct API** (lane recommendation; facts verified).
  Unofficial client: throttling and Cloudflare blocks still open on GitHub, though it is
  actively maintained (0.3.17 on 09-29). Official Health API: business-only per Garmin's
  FAQ ("applications paused" is secondary-source only). Aggregator: $399/month billed
  annually.
- **Garmin → Strava sync is already live** since 2026-09-06 (7 epix walks), and Garmin
  Connect is also writing steps into Apple Health. That covers #4503 / #4424.
- **If you agree:** retire the dormant `garmin-data-ingestion` function, its alarm, secret
  and reserved-concurrency slot; move the stress and body-battery source-of-truth entries
  off Garmin; fix ADR-074's stale "Strava paused" and "free tier" lines.
- What the direct API alone would add: stress, body battery, training readiness.

### Apple Health (Health Auto Export)
*Today:* webhook, 291 of 291 responses 200 in 14 days; UTC day key by ruling (#3677).
*Working:* water/caffeine per-reading dedup; CGM and State of Mind exact (15 of 15 days).

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Activity totals store the largest sync (C1) | **P1** | See P1-b | yes |
| Gait averages are the last batch's average (C2) | P3 | Same per-reading fix | no |
| `_apple` HR/HRV/SpO2 fields dead — 0 kept, 9,456 dropped (9,407 Eight Sleep) (C4) | P3 | Remove, or admit there is no Apple Watch | yes |
| `total_calories_burned` never written since 05-02 (C5) | P3 | Derive at read or drop | no |
| MacroFactor macros arrive here and are skipped by design (C6/D1) | P3 | Opportunity — see MacroFactor | yes |
| Combined source tag `Matt 17|Connect` treated as a rival device — 0.2% of steps (C3) | P3 | Normalise source names | no |
| Medications, symptoms, ECG, cycle not handled (C7, not re-verified) | P3 | Pick | yes |
| Edits/deletes in Health never propagate; failed S3 read could overwrite a day file (C8/C9) | P3, code-only | Guard the read | no |

### MacroFactor + Dropbox
*Today:* manual export → Dropbox → poller every 30 min (6 files in 672 polls) → S3 → parser.
0 days lost since genesis 09-06. Official path lags by days: rows for 09-27 → 10-03 all
arrived 10-04T04:33Z.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Same-day nutrition is already arriving via Apple Health (median lag 0.82 h) and discarded | P3 | Store as provisional; diary export stays the truth. Calories arriving is unproven | yes |
| Rolling 7-day export: a longer gap loses days (D2) | P3 | Nudge at day 5 | no |
| Poller: 48 runs/day, "recently empty" skip never fires (D8) | P3 | Hourly in waking hours | no |
| `macrofactor_meals` stopped 06-18, hand-run writer, no reader (D5) | P3 | Retire or schedule | yes |
| Diary export carries no trend weight, expenditure or targets | P3 | Accept, or add the summary export | yes |
| XLSX converter shifts sparse columns (D7, not re-verified; no XLSX in 14 d) | P3 | Honour cell refs | no |

### Habitify
*Today:* v1 read, hourly (+4 via site-stats), 36.5 s per run; v2 write through the skill.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| No habit id stored; three renames split history; 6 registry orphans (H1/G-3) | P2 | Store the vendor id; registry keyed on id with names as aliases | do the August renames keep their streaks |
| Un-ticks never reach the store; re-running a date does not help (H2) | P2 | Trust the vendor inside a window, or a corrections path | yes |
| Supplement bridge keyed on name and cannot retract (D18/D19) | P2, latent | Key on id; write retractions | no |
| 2,928 notes calls/day for 0 notes ever (H4) | P3 | Stop the notes and mood calls | yes |
| Open-day completion excludes pending (0.40 vs strict 0.23); one public nutrition endpoint includes the open day (H5) | P3 | Show completed days only | no |
| Two group taxonomies; stale `P40_GROUPS` (G-4) | P3 | One taxonomy from live areas | no |

Note: six habits were renamed and the registry updated after 20:11Z today, so counts moved
during the sweep.

### Todoist
*Today:* one poll a day at 14:00Z; MCP create/update/close.

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Priority inverted: vendor 4 = urgent; ingestion labels 1 urgent; MCP create defaults to 4 (T1) | P2 | Flip both | no |
| Very few completions in the last month; most open tasks overdue (T4) | ruling | Keep, simplify or retire as a signal | yes |
| UTC completion window — 387 of 959 all-time, 0 in 60 d (F2) | P3 | Pacific window | no |
| Row for day D written D+1; counts are a snapshot (T2) | P3 | Label as snapshot | no |
| MCP writes have no timeout or retry (T5/T6) | P3 | Add | no |

### Notion + journal enrichment
*Today:* 18 polls/day, 0 pages in 252 runs; no new entry for over three weeks.
The freshness checker did alert (151 times in 30 days).

| Finding | Sev | Proposed change | Ruling? |
|---|---|---|---|
| Reconcile deletes same-day siblings when one old page is edited or added (N1) | P2 | Reconcile only when the fetch covered the whole date | no |
| Re-keyed entries lose enrichment permanently (N1-b) | P2 | Carry `enriched_*` across the re-key; do **not** run a full re-sync first | no |
| Did the one suspected firing lose a sibling entry? Undetermined | — | Count the vendor-side pages for that date | owner, or one credentialed read |
| Top-level blocks only; partial body can overwrite a full one (N2/N3) | P3 | Recurse; refuse shorter overwrite | no |
| journal-analyzer 10:00Z reads fields enrichment writes at 14:30Z | P3 | Reorder | no |
| Hourly polling for a near-dormant journal | P3 | 2–3 runs/day | is the journal still a channel |

### Smaller sources
- **Food delivery** — dormant since 2026-03-28; readers show it as overdue, not current.
  6 of 1,598 rows are refunds stored as orders. *Ruling: revive or retire.*
- **Labs / DEXA / genome** (P2, latent) — no writer anywhere; raw for one draw only; the
  status page says labs are due now. *Ruling: build a repeatable path before the next draw.*
- **Measurements** — works; its S3 trigger, like all four bucket notifications, lives
  outside CDK with nothing checking for drift (P3).
- **Weather** — 38 of 45 stored days differ from the final archive (up to 2.3 °F, 4.1 mm);
  `uv_index_max` absent on all rows; status page says "OpenWeather", code calls Open-Meteo.
  Nothing on the site reads weather. *Ruling: re-fetch after 5 days, or retire.*
- **Social feeds** — three Lambdas on placeholder ids: 756 runs, 0 rows, 45 YouTube 404s.
  *Disable the schedules until accounts exist.*
- **Progress photos** — nothing beyond open #3743 / #3761 / #3759.
- **Inbound email** (P2) — see summary item 10 and #4633.

---

## 3. Cross-cutting

### Day boundaries
- Ruled and left alone: Whoop daily rows and Apple Health stay UTC.
- **Late recompute uses the wrong windows (F3, P2 low).** `daily_metrics_compute` anchors
  trailing windows on the real today. One provable row: 2026-09-27, recomputed today by an
  operator date-override — its window-derived fields disagree with both neighbours. Consumers of old rows:
  weekly correlation, baselines, hypothesis engine, recap regeneration, digests.
- **Clocks change 2026-11-01 (F5).** Fixed-UTC crons move the brief from 10:00 to 09:00 PT.
  On the last 61 wake times, the owner wakes after the last pre-brief Whoop pull on 18 days,
  against 5 now. Already filed and closed not-planned as #4284. *Ruling: reopen or leave.*
- **Travel (F4, P3).** 0 rows, no writer (removed deliberately in #884), five readers
  expecting two key shapes. *Ruling: restore a writer — Whoop's `timezone_offset` could
  feed it — or retire the readers.*

### Source of truth, double counting, renames
- The source-of-truth map is decorative (G-5, P3 today): two callers; the profile names
  MacroFactor for strength and Garmin for stress.
- Guards that hold: walking volume, training load, Apple Health max-field, the Strava seam
  for same-sport copies.
- Guards that fail: Zone 2 (P1-a), Whoop day-vs-workout rows, MCP strength history.
- Four different max-HR values in use (G-10, P3).
- **Proposed target (lane G §5):** a per-metric truth facet in the source registry with one
  resolver and a CI guard; id-keyed entities with name aliases; canonical units; one
  corrections ledger. *This is the main architectural ruling.*

### Schedule
| Source | Runs / day now | Useful | Suggested |
|---|---|---|---|
| Notion | 18 | 0 of 252 | 2–3 |
| Social ×3 | 18 each | 0 of 756 | off |
| Dropbox | 48 | 6 of 672 | ~12 |
| Hevy | 24 | 12 of 336 | keep, or every 2 h |
| Withings | 18 + 4 | ~5% change a row | 4 |
| Eight Sleep | 18 | ~5% | 3–4, mornings |
| Habitify | 24 + 4 | — | keep; drop notes calls |

`site-stats-refresh` also invokes Whoop, Withings and Habitify four times a day (documented
in code, but not in the registry's `method`). Whoop's 17:30Z refresh lands after the 17:00Z
brief — intent is inferred, not proven.

### Observability and self-healing
- Healthy: no ingestion incident needed self-healing in 30 days beyond one Habitify
  timeout the next run absorbed.
- Gaps confirmed (all P3): Hevy has no auth breaker; enrichment Lambdas write no health
  record; four ingest-path AI callers have no budget-ledger row; the health-check
  `PIPELINES` list is hand-written; bucket notifications are outside CDK; no reconciler for
  Withings, Eight Sleep, Habitify, Notion or Hevy.
- Six secrets are 133–210 days old; routing them to the needs-human list was deliberate
  (#1329) but nobody acts on it.
- Remediation agent: 42 runs, ~$8.41 (its own estimate), no ingestion fixes.

### Cost
- September total **$137.15**. Ingestion **~$18.4–19.3/month** (estimate from measured
  usage at list price): health metrics ~$8.34, 14 secrets ~$5.60, alarms. Lambda $0.00
  billed.
- Platform-wide CloudWatch as billed: metrics $13.07, alarms $11.84, composites $1.82.
- Nothing in ingestion is expensive enough to stop on cost alone. Retiring Garmin, the
  social schedules and unread secrets saves ~$2/month; the case is tidiness and token
  safety.

---

## 4. Rulings needed, in suggested order

The complete, numbered list (43 questions, grouped by source) is the owner-rulings docket,
**#4644**. The themes:

1. What Zone 2 means on the site (band, per-activity vs time-in-zone, whether Hevy cardio
   blocks count). Unblocks P1-a and the Whoop zone fix.
2. Apple Health totals: per-reading store vs app setting; backfill; should steps come from
   Whoop given the phone under-delivers on non-walk days. Then what "movement" rewards.
3. Garmin: retire the direct API and treat it as a Strava-delivered source?
4. The truth-registry / id-keyed / corrections-ledger target — adopt as an epic or patch
   site by site?
5. Which day a Whoop workout belongs to; relabel Whoop sport history?
6. Habitify: do the August renames keep their streaks; how should un-ticks behave; stop
   notes and mood calls?
7. Todoist, food delivery, weather, meal layer, social feeds: keep, simplify or retire each.
8. Journal: is Notion still a channel? Check whether the suspected firing lost an entry.
9. MacroFactor provisional same-day macros from Apple Health?
10. Labs/DEXA ingest path before the next draw.
11. Travel: restore a writer or retire the readers. Winter brief hour (#4284).
12. Extra fields worth keeping: Whoop steps / sleep need / timezone, Eight Sleep snoring
    and presence, Strava calories and laps, Apple Health medications and symptoms.

---

## 5. Refuted, corrected and unverified

**Refuted:** Hevy webhooks exist · Whoop UTC workout key is a defect (ruled, #3913) ·
interior-gap alarm stuck (real Eight Sleep gaps, #3504) · liveness check misplaced
(deliberate) · Eight Sleep DST offset produced wrong rows · weather zeros fabricated ·
Hevy cursor stall, whole-partition query cost, missing start time, enrichment race (all
latent with no live exposure) · `completion_pct` 0–1 vs 0–100 mismatch.

**Lane numbers the verifiers corrected:** "7×" Zone 2 is not a reproducible ratio ·
ingestion cost $15–17 → ~$18–19 · remediation runs 49 → 42 · Whoop steps "28 of 29 days" →
14 of 29 · Garmin first Strava sync 09-26 → 09-06 · Apple Health onset dated by archive
volume to 06-20/21, not by monthly medians · `_apple` drops are mostly Eight Sleep, not
Whoop · late-recompute evidence is one row, not seven.

**Not verified (filed as rows marked "re-prove before starting"):** Dropbox XLSX column shift (D7) and MCP weather second writer (D23) ·
Apple Health capability list (C7) and token-bundle posture (C11) · A-X3, A-X6, A-X8, T3,
N4, N7, G-11 · vendor-side deletion behaviour for any source (needs credentialed calls) ·
whether `avg_strain` renders on a current page (legacy page confirmed only) · the phone's
export settings · the exact per-namespace metric bill · KMS-dead objects outside `raw/` and
outside May.

**Environment note:** another session deployed the Lambda fleet at 20:32–20:45Z and
renamed six habits during the sweep; verifiers worked at `ee18b3c9a`.

---

## 6. Finding → issue map

Label: `review:data-source-sweep-2026-10-04` (21 issues). Findings not listed below are
checklist rows under `## Backlog rows` in the owning epic, grouped by source.

| Issue | What | Prio · milestone | Model | Findings |
|---|---|---|---|---|
| #4624 | **Epic A** — capture everything per source; interpret in one place | Now | fable | lanes F, G; dropped fields |
| #4625 | **Epic B** — each source stores what the vendor sent, and follows it when it changes | Now | fable | lanes A–E |
| #4626 | **Epic C** — ingestion operations: cadence, credentials, coverage | Next | fable | lane H; Garmin |
| #4627 | Zone 2 overstated on public training surfaces | P1 · Now | fable | G-1 |
| #4628 | Apple Health day totals store the largest sync | P1 · Now | opus | C1, C2 |
| #4629 | Whoop workout rows: zones, sport names, duplicates, reader | P2 · Next | opus | A-W1, A-W2, A-W3, F1, G-2 |
| #4630 | One truth resolver, steps as the first metric | P2 · Next | fable | G-5, G-9, A-W5 |
| #4631 | Notion reconcile and enrichment loss | P2 · Now | opus | N1, N1-b |
| #4632 | Habit identity by vendor id; un-ticks; supplements bridge | P2 · Next | opus | H1, H2, G-3, D18, D19 |
| #4633 | Inbound-email sender verification | P2 · Next | fable | lane H |
| #4634 | Raw objects unreadable under a deleted encryption key | P2 · Next | opus | A-X7 |
| #4635 | Vendor flags and enums stored with the wrong meaning | P2 · Now | sonnet | A-E2, T1 |
| #4636 | Readers on retired training record shapes | P2 · Next | opus | G-6, G-8 |
| #4637 | Late recompute builds windows from the wrong day | P2 · Now | opus | F3 |
| #4638 | Upstream edits and deletes that never reach the store | P2 · Next | opus | S2, A-W7, C8, D-series |
| #4639 | Labs and DEXA have no repeatable ingest path | P2 · Next | opus | D17 |
| #4640 | Garmin decision: retire the direct-API path | P3 · Next | sonnet | lane B §4 |
| #4641 | Ingestion cadence and credential churn | P3 · Next | sonnet | H1, H2, H4, H5, D8 |
| #4642 | Capture fields already fetched and dropped | P3 · Next | opus | A-W6, A-E1, S5, H8, C6, D1 |
| #4643 | Ingestion coverage gaps | P3 · Next | opus | H1–H3 (Hevy), H7, lane H §4 |
| #4644 | **Owner-rulings docket** — every decision waiting on the owner | P2 · Now | fable | all `gate:owner` items |

Existing issues extended by comment rather than duplicated: #3754 (Strava kilojoules are
zero on every stored row), #4424 and #4503 (the Garmin → Strava sync is already live),
#4622 (shares the Habitify merge code with #4632). The clocks-change effect on the daily
brief is a row under #4626 citing the prior ruling #4284; it was not refiled.

## 7. What an assessor should check

Each epic's `## Done when` is written as a measurable bar. In short: every key in
`lambdas/ingestion/source_registry.py` has a declared truth and day frame checked against
its writer by a test; every public number named in a story reproduces from stored rows by a
documented command; every source has a stated behaviour for upstream edit, delete and
rename, with a test or a live proof; and no scheduled ingestion runs above the cadence
table in §3 without a recorded reason.
