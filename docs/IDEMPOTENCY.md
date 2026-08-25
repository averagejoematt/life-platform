# IDEMPOTENCY.md — the external-side-effect replay census

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-25

**What this is:** every code path in this platform that causes an effect the
platform cannot take back — mail on the wire, a row in a ledger, an object in a
vendor's account — with a per-path statement of what happens if it runs **twice
with the same input**.

**Why it exists (DIL-025).** The external diligence review of 2026-08-23 filed
finding 025 as a CONFIRMED architecture risk: the platform had email senders,
write-capable MCP tools, webhooks and site writes, and *no enterprise-wide
inventory of which of them are safe to replay*. Nothing was known to be broken;
nothing was known to be safe either. This file is the answer, and the honest `N`
rows are as much the point as the `Y` rows.

**Maintained, not archived.** `tests/test_idempotency_census_dil025.py` derives
the sender and webhook sets from source and fails if a member has no row here. A
new email Lambda cannot ship without declaring its replay semantics.

---

## 1. The three replay vectors

A "duplicate invocation" is not hypothetical and is not usually a human. In
descending order of how often it can happen:

1. **Lambda async retry.** A scheduled (async) invoke that raises is retried by
   Lambda itself, twice, roughly 1 and 2 minutes later. Mail already on the wire
   is not un-sent by the exception that followed it. The failure shape that
   matters is therefore *"sent, then crashed"* — not *"crashed"*.
2. **DLQ redrive.** Every ingestion, compute and email function routes async
   failures to `life-platform-ingestion-dlq`
   (`cdk/stacks/{ingestion,compute,email}_stack.py`, `dlq=local_dlq`).
   `operational/dlq_consumer_lambda.py` runs on `rate(6 hours)`; its
   `classify_message` **defaults an unrecognised failure to TRANSIENT**, and
   `retry_message` then calls `lam.invoke(FunctionName=..., InvocationType="Event",
   Payload=body_str)` — the original function, the original payload. A Lambda
   async-DLQ message body *is* the original invocation event, so what gets
   replayed is the EventBridge scheduled event, byte for byte.
3. **A manual re-invoke** — an operator diagnosing a failed run.

### What the existing gates do and do not cover

The platform already has two mechanisms here. Neither one answers the replay
question, and conflating them is how this stayed invisible:

| mechanism | question it answers | covers a redrive? |
|---|---|---|
| `common/send_guard.py` (#2222) | "did an **operator** ask for a build-but-don't-send run?" | **No.** A redrive carries the original scheduled payload with no suppressor on it, so the send gate correctly lets it through. |
| `emails/daily_brief_lock.py` (#2860) | "is another invocation **mid-flight right now**?" | **No.** A 1200s lease, deliberately short so a genuine crash still gets a real retry. The redrive arrives up to 6 hours later — 18× the lease. |
| `common/send_ledger.py` (DIL-025) | "did this exact letter **already go out**?" | **Yes.** A durable completion record keyed on *what* was sent. |

The three are complementary, not redundant: an operator-safety gate, an
in-flight lease, and a durable ledger.

---

## 2. Email senders — the SES set (28 handlers)

**The finding said 7. The derived set is 28.** `tests/test_ses_send_guard_set_2222.py::derive_ses_sending_handlers`
walks `lambdas/` for modules that define a `lambda_handler` *and* put mail on the
wire; the census below is built from that same derivation, so the two can never
disagree about who is in the set.

All 28 honour a send suppressor (#2222/#2291) — that is a solved problem and is
not restated per row. The column that matters here is **replay-safe**.

**#3113 closed the gap DIL-025 opened.** 6 senders were replay-safe when this
file was written; 19 are now, and the remaining **9** carry a written verdict
rather than silence. The honest `N` rows in §2b are as much the deliverable as
the `Y` rows — three of them are `N` because the Lambda's IAM role is read-only
by design and the duplicate it would prevent is an ops digest nobody records.

**Legend.** Replay-safe `Y` = a second invocation with the same payload will not
send a second letter. `N` = it will.

### 2a. Replay-safe today (19)

| Module | Trigger | Mechanism | Evidence |
|---|---|---|---|
| `emails/daily_brief_lambda.py` | `cron(0 17 * * ? *)` | **DIL-025.** `send_ledger.already_sent(table, "daily_brief", yesterday)` before the send; `record_email_send(..., yesterday)` one line after it. Keyed on the **brief date**, not the send date, so a redrive crossing UTC midnight is still caught. Fail-open on a read error. | `daily_brief_lambda.py` guard + `common/send_ledger.py`; `tests/test_send_replay_guard_dil025.py` |
| `emails/monthly_digest_lambda.py` | `cron(0 16 ? * 1#1 *)` | `_already_sent_this_month()` queries the `email_log` partition for the calendar month before sending (#1658). The in-repo precedent DIL-025 generalised. | `monthly_digest_lambda.py:814-829` |
| `emails/chronicle_email_sender_lambda.py` | schedule **+** approve-invoke | `delivered_at` marker on the installment: read before send (`:195`), stamped after with `ConditionExpression="attribute_not_exists(delivered_at)"` (#2112). Closes the dual-trigger race too. | `chronicle_email_sender_lambda.py:193-230` |
| `emails/wednesday_chronicle_lambda.py` | `cron` Wednesday | #2254 generation-time gate, **before** the Sonnet call and the approval mail: refuses a week already in a protected status, so a replay cannot mint a second `approval_token` over the one in Matthew's inbox. `{"force": true}` is the escape hatch. | `wednesday_chronicle_lambda.py:509+`; `chronicle_store.py:63-72` |
| `emails/coach_nudge_lambda.py` | schedule | `_reserve_day()` — a conditional put claiming the day's nudge slot (`attribute_not_exists(pk)`, no TTL). Fails **closed**: any error stands the nudge down. | `coach_nudge_lambda.py:325-345` |
| `emails/coach_panel_podcast_lambda.py` | manual / unscheduled | Week-artifact presence check — an existing week in `episodes.json` is skipped unless `{"force": true}`. Gates the whole run, including the mail. | `coach_panel_podcast_lambda.py:8`, `:947` |
| `emails/milestone_digest_lambda.py` | `cron(15 17 * * ? *)` | **#3113.** `period_key = milestone:{milestone_id}` — episodic, so the key is the announced milestone, not a calendar period, and it is the same id however many days later a redrive lands. Recorded after the **first** delivery, so a crash mid-fan-out cannot re-mail the whole list. | `milestone_digest_lambda.py::_period_key`; `tests/test_send_replay_guard_dil025.py` |
| `emails/partner_email_lambda.py` | `cron(30 17 ? * 1 *)` | **#3113.** `period_key = week:{ISO week}`, guarded before `gather_all` and the Sonnet call. ISO week rather than a date because `w_end` is derived from the wall clock and shifts under a redrive crossing UTC midnight; Saturday and the following Sunday close the same ISO week. | `partner_email_lambda.py::_period_key`; `tests/test_send_replay_guard_dil025.py` |
| `emails/weekly_digest_lambda.py` | `cron(0 16 ? * SUN *)` | **#3113.** `period_key = week:{ISO week}`; the completion row moved from the end of the handler (~40 lines of insight-writing later) to one line after the SES call. | `weekly_digest_lambda.py` guard + `record_email_send` |
| `emails/weekly_plate_lambda.py` | `cron(0 2 ? * SAT *)` | **#3113.** `period_key = week:{ISO week}` — the food window is a rolling 14 days, but the EDITION is weekly and that is what must not be mailed twice. | `weekly_plate_lambda.py::_period_key` |
| `emails/monday_compass_lambda.py` | `cron(0 15 ? * MON *)` | **#3113.** `period_key = week:{ISO week of TODAY}` — the compass is the letter for the week AHEAD, so unlike the look-back senders it keys on today, not yesterday. | `monday_compass_lambda.py::_period_key` |
| `emails/nutrition_review_lambda.py` | `cron(0 17 ? * SAT *)` | **#3113.** `period_key = week:{ISO week}`, and the ledger is read/written under `USER_ID` (not a hardcoded `matthew`) so the guard reads the partition #2221 fixed. | `nutrition_review_lambda.py::_period_key` |
| `emails/anomaly_detector_lambda.py` | `cron(5 15 * * ? *)` | **#3113.** `period_key = date:{analysed date}`, covering **both** letters this handler can mail (multi-source alert + sustained-streak alert) — two keys would collide on the shared sort key and the second would erase the first. Deliberately **not** an early return: a replay re-runs the analysis and rewrites the anomaly record, and only the mail is suppressed. A completed run that mailed nothing writes a `run:` key that can never match, so a quiet run cannot suppress a later genuine alert. | `anomaly_detector_lambda.py` `replayed` branches |
| `emails/ai_review_pack_lambda.py` | `cron(0 18 ? * SUN *)` | **#3113.** `period_key = week:{ISO week}`. Note the ledger name keeps the historical hyphen (`email_log#ai-review-pack`) so the guard reads the partition the status page writes. | `ai_review_pack_lambda.py::LEDGER_NAME` |
| `emails/between_chronicle_lambda.py` | `cron(0 17 ? * SUN *)` | **#3113.** `period_key = week:{ISO week}`, recorded after the **first** subscriber send. Deliberately not the content hash this module already computes: the digest is assembled from live records, so a redrive hours later can hash differently for the same letter and the existing marker check sails through. | `between_chronicle_lambda.py::_period_key` |
| `emails/evening_nudge_lambda.py` | `cron(0 3 * * ? *)` | **#3113.** `period_key = date:{pacific_today()}` — the same reason AUDIT BUG-02 made the rest of this handler read Pacific: at 03:00 UTC a UTC-dated key names tomorrow. Needed a new `dynamodb:PutItem` grant (`role_policies_email.email_evening_nudge`). | `evening_nudge_lambda.py` guard |
| `emails/insight_email_parser_lambda.py` | **SES receipt rule → S3** (event-driven, #2291) | **#3113.** No calendar period exists — the letter's identity is the inbound message it answers, so `period_key = msg:{S3 object key}`. Needed a new `dynamodb:Query` grant (`role_policies_operational.operational_insight_email_parser`). | `insight_email_parser_lambda.py` per-record guard |
| `compute/weekly_signal_lambda.py` | `cron(30 16 ? * SUN *)` | **#3113.** `period_key = week:{ISO week}`, recorded after the **first** subscriber send. The #2820 delivery datapoint is a CloudWatch METRIC, not a durable record, and cannot answer "did this week's letter already go to the list?". Needed new `dynamodb:PutItem` + `kms:GenerateDataKey` grants. | `weekly_signal_lambda.py` guard |
| `web/subscriber_onboarding_lambda.py` | `cron(5 17 * * ? *)` | The guard is **per-recipient**, which a per-lambda `period_key` cannot express: there is no one letter, there are N, each on its own clock relative to that subscriber's `confirmed_at`. The `onboarding_sent` flag IS a durable per-letter record, read before the send by the query's `FilterExpression` and written **one line** after it. Re-classified from "partial" on re-reading (#3113): the residual window (send OK, `update_item` raises) is the same fail-open window `send_ledger.record_sent` has. | `subscriber_onboarding_lambda.py:174`, `:225-232` |

### 2b. Residual — no ledger, by verdict (9)

Each of these was assessed under #3113 and **deliberately not** given the shared
primitive. The reasons are specific, not a shrug — and two of them are the same
reason twice: the role is read-only *by design*, so adopting the ledger would
mean granting `dynamodb:PutItem` to a Lambda whose whole posture is that it
cannot write, in order to close a "duplicate ops digest is noise" gap. That is
the disproportion ADR-103/144 exists to refuse.

| Module | Trigger | Replay-safe | Why no ledger |
|---|---|---|---|
| `operational/canary_lambda.py` | `rate(4 hours)` | **N — accepted** | A liveness alert is a *fresh observation*, and a repeated alert during a real outage is the point. Suppressing the second one is a way to hide an outage, which is a worse failure than a duplicate mail. |
| `operational/dlq_consumer_lambda.py` | `rate(6 hours)` | **N — accepted** | **It is itself the redrive engine.** Its digest is queue state at read time; a duplicate is a repeated reading of a moving number. |
| `operational/qa_smoke_lambda.py` | `cron(30 18 ? * * *)` | **N — accepted** | Nightly observation, not a reproducible artifact. (Also at 1,198 of the 1,200-line module ceiling — `tests/test_module_size_guard.py` — so a guard cannot land without an unrelated extraction.) |
| `operational/alert_digest_lambda.py` | `cron(0 15 * * ? *)` | **N — accepted** | Content is the alarm state at read time. Its role (`operational_alert_digest`) holds **no DynamoDB grant at all** — SQS drain + `DescribeAlarms` + SES. |
| `operational/pip_audit_lambda.py` | `cron(0 17 ? * MON *)` | **N — accepted** | Its role holds **no AWS resource access at all** ("just runs pip-audit and reports"). |
| `operational/traffic_digest_lambda.py` | `cron(0 16 ? * MON *)` | **N — accepted** | `dynamodb:Query` only — "Query only, never write — the digest is read-only by contract" (`role_policies_operational.py`). |
| `operational/permanence_lambda.py` | `cron(0 6 * * ? *)` | **N — accepted** | `dynamodb:Query` only, and #1400 says why out loud: "the contract's own state lives in the published continuity document rather than in a private partition." |
| `operational/data_reconciliation_lambda.py` | `cron(30 7 ? * MON *)` | **N — accepted** | Read-only DDB grant (`GetItem`/`Query`/`Scan`, no write). Report content is a fresh reconciliation reading. |
| `web/email_subscriber_lambda.py` | **reader HTTP** (FunctionURL) | **Partial — accepted** | The remaining exposure is a *reader resubmitting the form*, which is not a replay: re-sending the confirmation is the intended behaviour when someone lost the first mail. The `confirm` leg is already replay-safe — the token is `REMOVE`d on use, so a replayed confirm cannot re-send the welcome (see §4). |

> The eight ops rows are the honest `N` this census was built to make sayable.
> Their content is a *fresh observation at send time*, so a duplicate is a
> repeated reading, not a falsified record — and closing that gap would cost a
> write grant on five roles that are read-only on purpose.

---

## 3. Webhook ingestion

Only **one** webhook is live. `lambdas/ingestion/hevy_webhook_lambda.py` parses
an HTTP shape but is **not deployed** (Hevy publishes no webhooks; the CDK
function and its IAM policy were removed — source kept for revival).
`lambdas/web/telegram_webhook_lambda.py` has a FunctionURL but performs no
persistent write, only a worker invoke.

### `lambdas/ingestion/health_auto_export_lambda.py` — API Gateway HTTP API `POST /ingest`

**The good news, recorded so a refactor cannot quietly undo it:** a duplicate
delivery of the same HAE payload does **not** double-count water or caffeine.
Two independent reasons, and the load-bearing one is the second:

1. every DDB write is `SET field = <absolute>`, never `ADD` (`:1020-1022`) — so
   even with zero dedup logic a replay overwrites rather than accumulates;
2. the `_rd_{field}` reading map merges by the raw HAE timestamp and
   **recomputes the total from the merged map** (`:966-1005`), so `if ts not in
   merged` makes a replay a no-op. This is also what makes *incremental* syncs
   correct, since HAE sends only-new-readings bundles.

| Source | Dedup mechanism today | Replay-safe | Evidence |
|---|---|---|---|
| water, caffeine | Reading-level `_rd_` map keyed on the HAE timestamp string, total recomputed from the merge; a failed dedup-read withholds the `_rd_` write rather than overwriting the stored map (#3119) | **Y** | `:677`, `:966-1005` |
| steps, distance, active/basal calories, flights | GREATEST-on-write monotonic guard + cross-source `max_sum` | **Y** (also protected against undercount) | `:455-462`, `:946-964` |
| blood_glucose_readings_count, blood_pressure_readings_count, som_check_in_count | GREATEST-on-write monotonic guard (#3119 — joined the mechanism above via `_READING_COUNT_GUARD_FIELDS`, kept as its own set since these are single-source per-payload counts, not a cross-device max-of-sums) | **Y** (also protected against undercount) | `:473-480`, `:946-964` |
| cgm, blood_pressure, state_of_mind (DDB, non-count fields) | Stateless recompute from the payload → last-write-wins | **Y** for an identical replay | `:1511`, `:1540` |
| cgm, blood_pressure, state_of_mind, workouts (S3) | Read-merge-dedup on the reading's own `time` / `id`; `put_object` skipped when nothing is new. Bodies extracted to the sibling `health_auto_export_archive.py` (#3119, the module-size ratchet split); `health_auto_export_lambda.py` keeps thin same-signature wrappers | **Y** | `ingestion/health_auto_export_archive.py:48-183`, wrappers at `health_auto_export_lambda.py:1080-1097,1422-1429` |
| raw payload archive | Key leaf is `{DD}_{sha256(payload)[:16]}.json` (#3119, was pure wall-clock `DD_HHMMSS.json`) — a redelivery of identical bytes the same UTC day resolves to the SAME key, an idempotent overwrite. Also a DIL-028 generation flip: `filename`/`filename_legacy` facets added to `apple_health`'s `raw_layout` in `source_registry.py` | **Y** for a same-day replay of identical bytes | `ingestion/health_auto_export_archive.py:165-186` |

Fixed by #3119: the raw archive no longer mints a fresh object per delivery of
the same bytes; `*_readings_count` / `check_in_count` now share the
GREATEST-on-write guard so a *partial* re-export can no longer silently
**lower** them; and a failed dedup-map read no longer replaces the stored `_rd_`
map with a payload-only one (it used to — a genuine data-loss bug, the mirror
image of "replay is safe").

**Accepted in writing, not fixed (#3119 residual #3):** `merge_day_to_dynamo` is
still a plain read-modify-write with no `ConditionExpression`/version — two
DIFFERENT bundles racing on the SAME (date, dedup-field) pair inside the same
invocation window could last-writer-win and lose one bundle's readings. An
exact-duplicate redelivery is unaffected (identical merge either way). The
window is narrow by construction — HAE fires one automation trigger per data
type on its own schedule, so real concurrency needs two DIFFERENT automations
racing on a field they don't actually share, or the same automation
double-firing, which is the already-safe duplicate case — and self-healing: a
reading dropped by the race reappears on the field's next sync (incremental or
full) and merges in normally then. Full optimistic locking would need a
version attribute and a retry-on-conflict loop spanning every
CGM/BP/SoM/generic-metrics call site; judged not worth it for a race this
narrow. Revisit if HAE ever ships true multi-automation-per-second delivery.

No transport idempotency key (API Gateway request id / `aws_request_id`) is
consulted anywhere in this path.

---

## 4. Site-API interactive writes

The real package is `lambdas/web/` (CLAUDE.md's `web/*.py` is the *deployed zip
root* naming — `lambdas/` is staged at the zip root per ADR-146). Three deployed
functions carry FunctionURLs: `site_api_lambda`, `site_api_ai_lambda`
(`serve_stack.py`) and `email_subscriber_lambda` (`web_stack.py`).

**This surface is mostly well-guarded, and its pattern is the one to copy:** the
vote / follow / certify family writes a *conditional dedup row first*, so the
counter `ADD` is structurally unreachable a second time.

The two rows the census marked **N** were closed by #3118 with that same pattern,
one on each store: `put_object(IfNoneMatch="*")` is S3's `attribute_not_exists`,
and the follow-up's `turn_ids` set makes the turn's own identity part of the
ConditionExpression. Both fail **open** — a capture door losing a reader's
submission is worse than a duplicate pending row — and the per-IP rate token is
still spent by a replay, which fails *closed* and is why the limiter can never be
the dedup primitive (see the `rate_limiter` row).

| Route | Mechanism today | Replay-safe |
|---|---|---|
| `/api/challenge_vote`, `/api/experiment_vote`, `/api/predict_week`, `/api/replicate_certify` | Conditional put on `IP#{ip_hash}#…` (`attribute_not_exists(pk)`) gates the `ADD` counter; replay 429s or returns `counted: false` | **Y** |
| `/api/challenge_follow`, `/api/experiment_follow` | Conditional put on `EMAIL#{email_hash}#…` → `already_following` | **Y** (the hourly rate counter double-spends, but fails *closed*) |
| `/api/experiment_suggest` | Content hash **+** `ConditionExpression="attribute_not_exists(sk)"` → true no-op, `duplicate: true` | **Y** — the strongest door on the surface |
| `/api/challenge_checkin` | Read-modify-write dedup on `date` | **Y** for replay; races on truly simultaneous delivery |
| `/api/cohort_submit`, `/api/ritual_log` | Natural-key overwrite (`SUBMIT#{ip_hash}`, `DATE#{date}`) | **Y** |
| `/api/subscribe` | Natural key `EMAIL#{sha256}` — no duplicate row, but a resubmit mints a **new token** and re-sends the confirmation | **Partial** — accepted (#3113 §2b: a resubmit is a reader action, not a replay) |
| `/api/subscribe?action=confirm` / `unsubscribe` | Token is `REMOVE`d on confirm (self-invalidating); unsubscribe guarded by a status read | **Y** |
| `/api/submit_finding`, `/api/board_question` | Content hash **alone** for the key (no clock in it) **+** `put_object(IfNoneMatch="*")` → true no-op, `duplicate: true` (`web/site_api_capture_store.py`) | **Y** — #3118. The clock left the key, so there is no boundary to cross; the conditional put means a replay cannot overwrite a moderation decision |
| `site_api_ai` follow-up turn | Pre-spend `replayed_turn` match serves the stored answer, **and** the condition adds `NOT contains(turn_ids, :tid)` alongside the cap and IP (`web/site_api_ai_session.py`) | **Y** — #3118. A redelivery costs no model call and no turn; the DDB condition closes the simultaneous-delivery race the pre-check can't see |
| `site_api_ai` session mint | `pk = SESSION#{secrets.token_urlsafe(24)}` | **Accepted N** — a replay mints a second row, bounded by a ≤1h TTL and reachable only with the token the *first* response returned, so no reader-visible loss and no unbounded growth. Left random deliberately (#3118): the token must stay unguessable and un-derived from any request field |
| `common/rate_limiter.py` | Unguarded atomic `ADD` | **N by design** — fails *closed* (a replay only rate-limits you harder). Not a correctness bug, but it means **the limiter can never be the dedup primitive** for a replayed request. |

---

## 5. Write-capable MCP tools

`mcp/audit.py::is_write_tool` classifies by leading verb; that yields **26
write-capable tools** of the 75 in `mcp/registry.py`. Most write on a
deterministic key and are replay-safe by overwrite — `write_platform_memory`,
`manage_sick_days`, `log_evening_intake`, `end_experiment`,
`update_insight_outcome`, `update_decision_outcome`, `mark_journal_quote`
(content-hash key), `manage_diary_claims`, `log_coach_checkin`,
`curate_horizon`'s pick, `archive_horizon`, most of `manage_reading`,
`update_todoist_task`, `log_habit_reflection`, `log_field_note_response`.

Cross-cutting and **non-idempotent by design**: every write tool appends an
audit object at `s3://…/mcp-audit/…/{HHMMSS}-{tool}-{uuid4}.json`
(`mcp/handler.py:82` → `mcp/audit.py:154`). That is an append-only trail; a
duplicate entry is the correct record of a duplicate call.

**Not replay-safe — `filed #3114`:** `log_decision` (`DECISION#{ms-ts}`),
`save_insight` (`INSIGHT#{second-ts}`), `log_coach_correction` and
`audit_coach_dossier` retract/correct (uuid4 ledger sk), `manage_reading`
`log_session` / `add_note` / `debrief` (timestamp-derived ids — `debrief` also
starts a **second spaced-repetition clock**), `curate_horizon`'s follow-up arm
(`CHECKIN#{date}#{uuid4[:8]}`).

**Not replay-safe against a vendor — `filed #3115`:** `create_todoist_task`
(Todoist mints a task per call, no idempotency header), `close_todoist_task` on
a **recurring** task (close *advances* the recurrence — a replay skips a real
occurrence), `manage_hevy_routine` draft (`ROUTINE#{uuid4}` per draft) and
first-push commit (`POST /routines`). Hevy *template* and *folder* creates are
already genuine find-or-create — that is the shape the routine create lacks.

**Guarded, not naturally idempotent** (worth naming so a refactor does not
remove the guard by accident): `log_coach_calibration` does a read-modify-write
Beta-counter update that is only safe because a conditional put on a
deterministic `LEARNING#` sk short-circuits first
(`lambdas/coach/coach_calibration.py:395-449`). `create_experiment` pre-reads
and *raises* on a duplicate rather than upserting.

---

## 6. Adding a row

`tests/test_idempotency_census_dil025.py` derives the SES-sending set and the
live-webhook set from source and asserts every member appears in this file. If
you ship a new sender, add its row — the guard names the missing module.

Reach for `common/send_ledger.py` before hand-rolling: `already_sent(table,
name, period_key)` before the send, `record_sent(...)` **immediately after** it
(not at the end of the handler — that gap is the bug DIL-025 closed in the
brief). Both halves fail open; a broken guard must degrade to a possible
duplicate, never to a silently unsent letter.

**Related:** ADR-103/144 complexity posture → `docs/PROPORTIONALITY.md` ·
send suppression → `lambdas/common/send_guard.py` (#2222) · in-flight lease →
`lambdas/emails/daily_brief_lock.py` (#2860) · the DIL-025 register row →
`docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md`.
