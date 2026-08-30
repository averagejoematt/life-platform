# qa-smoke Alarm Set Review — 2026-08-30

**Issue:** #3317 (the open carrier for #2670's post-closure scope) · **Method:** ADR-105 (deterministic evidence before any verdict) · **Region:** us-west-2 · **Author:** alarms lane, 2026-08-30

> #2670 closed `realized` on 2026-08-20. A 2026-08-22 comment asserted "drain/re-justify the
> current standing set" onto the closed issue; the Session K closure audit filed #3317 as the
> open carrier. This is the evidence behind the verdicts recorded at the definitions in
> `cdk/stacks/monitoring_stack.py` (which sits at its module-size cap, so the numbers live here)
> and in `docs/alarm_citations.json`.

## 1. The set, enumerated from CDK

`cdk synth LifePlatformMonitoring` → three `AWS::CloudWatch::Alarm` resources with `AlarmName`
prefix `qa-smoke`, all routed to `life-platform-alerts-digest` (SNS → SQS → the daily digest; no
pager). No siblings anywhere else in `cdk/stacks/*.py`.

| alarm | metric (`LifePlatform/QaSmoke`) | shape |
|---|---|---|
| `qa-smoke-heartbeat` | `RunCompleted` SampleCount | `< 1`, 86400s × 2 evals, missing = BREACHING |
| `qa-smoke-failures` | `FailCount` Maximum | `>= 1`, 86400s × 1, missing = notBreaching |
| `qa-smoke-warnings` | `WarnCount` Maximum | `>= 1`, 86400s × 1, missing = notBreaching |

## 2. Evidence (all read-only)

- `describe-alarms --alarm-name-prefix qa-smoke`
- `describe-alarm-history --history-item-type StateUpdate`, 2026-07-31..2026-08-30 (one 100-record page each, no `NextToken`)
- `filter-log-events` on `/aws/lambda/life-platform-qa-smoke` since 2026-08-18: `"[QA] FAIL"` (46 lines), `"[QA] WARN"` (560 lines, 23 non-`[chronic]` after the 08-19 drain), per-run `"[QA]" "warning(s)"` summaries (37 runs)
- closed-issue search for every finding fingerprint / check key

### 2a. `qa-smoke-heartbeat`

0 state transitions since creation (2026-07-18). `RunCompleted` landed on every one of the 37 runs
logged 2026-08-18..08-30. A dead-man that has never fired is the expected record.

### 2b. `qa-smoke-failures`

| OK→ALARM | ALARM→OK | dwell | causes (all since closed) |
|---|---|---|---|
| 07-31 17:19 PT (window edge) | 08-17 08:46 PT | 16.6 d | the #2670 "rotating cast": #2634, #2705, #2738, #2741; one false-positive datapoint 08-16 (off-schedule `dashboard:date`, fixed #2785) |
| 08-17 11:32 PT | 08-19 19:53 PT | 2.35 d | the 08-17 trio: #1934-class Whoop breaker latch (`reader_truth:plausibility` d1c6a0), `redirect_spotcheck` 404s, #2705 recurrence; then 539c6d Day-2 home copy → #2880/#2741 |
| 08-20 11:31 PT | 08-28 07:05 PT | 7.8 d | fcd7d5 `/api/sleep_detail` → #2921 (closed 08-23); `recall:corpus_freshness` 2026-08-18 → #2977 (closed 08-24); `cross_surface:weight` 321.0 vs 326.0 lb → #3083 / PR 3215 (closed 08-30); e5eafd `/api/glucose` → #3204 / PR 3239 (closed 08-27) |

3 transitions, **3/3 true positives**, 0 unexplained; time-in-ALARM 26.8 d / 30 d (7.8 d of the
11 d since the drain, all of it cited). Last FAIL line 2026-08-27T14:05Z; the ~25 runs since,
including the 08-28/08-29/08-30 18:31Z scheduled sweeps, log 0 failures. OK since 2026-08-28T14:05:55Z.

### 2c. `qa-smoke-warnings`

Organic episodes since the #2670 drain (08-19 14:08 PT), each one fire and one clear ~24 h later:

| OK→ALARM (Z) | alarmed WarnCount | finding → owner |
|---|---|---|
| 08-20 18:03 | 2 | fcd7d5 confirm-demotion + verdict → #2921 |
| 08-23 06:49 | 2 | 539c6d confirm-demotion + verdict → #3258 (the judge counting its own retraction) |
| 08-24 17:10 | 1 | e5eafd `/api/glucose` as_of_date → #3204 |
| 08-27 18:31 | 1 | 539c6d → #3258 (fixed and deployed the same day) |

Other non-chronic lines in the read: 08-21T09:05Z (fcd7d5), 08-22T01:27Z (539c6d + cd6030
`duplicated_narrative` on `/`, cd6030's only occurrence in the read), 08-24T18:31Z (e5eafd).

Plus **33 synthetic OK→ALARM flaps** 2026-08-20 15:34..18:03Z from the ONE planted
`put-metric-data` datapoint (#2912's measurement). No organic datapoint has ever flapped.

**4/4 organic episodes mapped**; 0 alarmed warns in the 22 runs / 3 scheduled nightlies from
2026-08-27T18:50Z (the #3258 deploy boundary) through 2026-08-30T21:00Z. OK since 2026-08-28T18:31:50Z.
Time-in-ALARM 25.0 d / 30 d (5.3 d of the 11 d since the drain).

## 3. Verdicts — coverage 3/3

| alarm | verdict | why |
|---|---|---|
| `qa-smoke-heartbeat` | **KEEP** | the only detector of "the QA layer stopped running" (#1445); `tests/test_heartbeat_completeness.py` requires it; 0 false positives |
| `qa-smoke-failures` | **KEEP**, shape unchanged | 3/3 true positives, each producing a merged fix; the FAIL boundary is deterministic since #2741/#2880 |
| `qa-smoke-warnings` | **KEEP**, shape unchanged | 4/4 organic episodes mapped and fixed; #2670's residual ("should `>= 1`-in-24h become sustained N-of-M?") is closed by data — post-#3258 ambient non-chronic traffic is 0/22 runs, so N-of-M has no noise to remove and would only have delayed #3204's single-night 08-24 signal by a day. The flap concern is a plant artifact, not a property of the shape |

Nothing retired, nothing reshaped, no threshold widened. The standing-red set on 2026-08-30 is
**empty**; `python3 scripts/check_alarm_citations.py` exits 0 live.

## 4. Registry lifecycle

Both `docs/alarm_citations.json` entries were rewritten as dated verdicts with derivation and an
explicit PRUNE-after stamp honouring the 72 h flap window: `qa-smoke-failures` after
2026-08-31T14:06Z, `qa-smoke-warnings` after 2026-08-31T18:32Z. A re-light after those stamps is a
NEW cause and needs a new citation — the closed `#N`s here must not be revived.
