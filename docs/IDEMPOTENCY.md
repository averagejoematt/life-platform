# IDEMPOTENCY.md — the external-side-effect replay census

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-24

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

**Legend.** Replay-safe `Y` = a second invocation with the same payload will not
send a second letter. `N` = it will.

### 2a. Replay-safe today (6)

| Module | Trigger | Mechanism | Evidence |
|---|---|---|---|
| `emails/daily_brief_lambda.py` | `cron(0 17 * * ? *)` | **DIL-025.** `send_ledger.already_sent(table, "daily_brief", yesterday)` before the send; `record_email_send(..., yesterday)` one line after it. Keyed on the **brief date**, not the send date, so a redrive crossing UTC midnight is still caught. Fail-open on a read error. | `daily_brief_lambda.py` guard + `common/send_ledger.py`; `tests/test_send_replay_guard_dil025.py` |
| `emails/monthly_digest_lambda.py` | `cron(0 16 ? * 1#1 *)` | `_already_sent_this_month()` queries the `email_log` partition for the calendar month before sending (#1658). The in-repo precedent DIL-025 generalised. | `monthly_digest_lambda.py:814-829` |
| `emails/chronicle_email_sender_lambda.py` | schedule **+** approve-invoke | `delivered_at` marker on the installment: read before send (`:195`), stamped after with `ConditionExpression="attribute_not_exists(delivered_at)"` (#2112). Closes the dual-trigger race too. | `chronicle_email_sender_lambda.py:193-230` |
| `emails/wednesday_chronicle_lambda.py` | `cron` Wednesday | #2254 generation-time gate, **before** the Sonnet call and the approval mail: refuses a week already in a protected status, so a replay cannot mint a second `approval_token` over the one in Matthew's inbox. `{"force": true}` is the escape hatch. | `wednesday_chronicle_lambda.py:509+`; `chronicle_store.py:63-72` |
| `emails/coach_nudge_lambda.py` | schedule | `_reserve_day()` — a conditional put claiming the day's nudge slot (`attribute_not_exists(pk)`, no TTL). Fails **closed**: any error stands the nudge down. | `coach_nudge_lambda.py:325-345` |
| `emails/coach_panel_podcast_lambda.py` | manual / unscheduled | Week-artifact presence check — an existing week in `episodes.json` is skipped unless `{"force": true}`. Gates the whole run, including the mail. | `coach_panel_podcast_lambda.py:8`, `:947` |

### 2b. No replay guard (22) — `filed #3113`

None of these has a durable record of *what* it last sent, so a "sent, then
crashed" invocation followed by an async retry or a 6-hourly redrive mails the
same letter again. Ordered by consequence.

| Module | Trigger | Side effect | Why it is not merely cosmetic |
|---|---|---|---|
| `emails/milestone_digest_lambda.py` | schedule | Mails the **friends-and-family list** | A duplicate reaches third parties. Has a ledger *cooldown* spacing announcements, which is not a replay guard. |
| `emails/partner_email_lambda.py` | schedule | Mails a **partner address** resolved from SSM | Same: third-party recipient. |
| `emails/weekly_digest_lambda.py` | schedule | Reader-facing weekly letter | Writes an `email_log` row it never reads. |
| `emails/weekly_plate_lambda.py` | schedule | Reader-facing | Writes `email_log`, never reads it. |
| `emails/monday_compass_lambda.py` | schedule | Reader-facing | Writes `email_log`, never reads it. |
| `emails/nutrition_review_lambda.py` | schedule | Owner-facing review | Writes `email_log`, never reads it. |
| `emails/anomaly_detector_lambda.py` | schedule | Owner alerts | Writes `email_log`, never reads it. Its internal "dedup" is sleep-metric selection, not send dedup. |
| `emails/ai_review_pack_lambda.py` | schedule | Owner-facing | Writes `email_log`, never reads it. |
| `emails/between_chronicle_lambda.py` | schedule | Reader-facing | No `email_log` row at all. |
| `emails/evening_nudge_lambda.py` | schedule | Owner nudge | No completion record. |
| `emails/insight_email_parser_lambda.py` | **SES receipt rule → S3** (event-driven, #2291) | Reply mail | Event-driven, so the async-retry vector still applies. |
| `web/email_subscriber_lambda.py` | **reader HTTP** (FunctionURL) | Confirmation / welcome mail | See §4 — the row is natural-keyed, but a resubmit mints a new token and re-sends. |
| `web/subscriber_onboarding_lambda.py` | `cron(5 17 * * ? *)` | Onboarding mail | Flag-gated (`onboarding_sent`) — a *partial* guard, but the flag write is unconditional and follows the send. |
| `compute/weekly_signal_lambda.py` | schedule | Owner-facing | Hand-rolled dry-run gate only. |
| `operational/alert_digest_lambda.py` | schedule | Ops digest | Content is a fresh alarm observation; a duplicate is noise, not a false record. |
| `operational/canary_lambda.py` | schedule | Ops alert | As above. |
| `operational/data_reconciliation_lambda.py` | schedule | Ops report | As above. |
| `operational/dlq_consumer_lambda.py` | `rate(6 hours)` | Ops digest | **It is itself the redrive engine** — a duplicate digest is harmless, but note the recursion. |
| `operational/permanence_lambda.py` | schedule | Ops report | As above. |
| `operational/pip_audit_lambda.py` | schedule | Ops report | As above. |
| `operational/qa_smoke_lambda.py` | schedule | Ops report | As above. |
| `operational/traffic_digest_lambda.py` | schedule | Ops digest | As above. |

> The last eight are the weakest case for a guard and the strongest case for an
> explicit written verdict: their content is a *fresh observation at send time*,
> so a duplicate is a repeated reading, not a falsified record. #3113 requires
> each to either adopt the ledger or record that reasoning as a row here.

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

1. every DDB write is `SET field = <absolute>`, never `ADD` (`:1025-1026`) — so
   even with zero dedup logic a replay overwrites rather than accumulates;
2. the `_rd_{field}` reading map merges by the raw HAE timestamp and
   **recomputes the total from the merged map** (`:949-965`), so `if ts not in
   merged` makes a replay a no-op. This is also what makes *incremental* syncs
   correct, since HAE sends only-new-readings bundles.

| Source | Dedup mechanism today | Replay-safe | Evidence |
|---|---|---|---|
| water, caffeine | Reading-level `_rd_` map keyed on the HAE timestamp string, total recomputed from the merge; a failed dedup-read withholds the `_rd_` write rather than overwriting the stored map (#3119) | **Y** | `:681`, `:982-1030` |
| steps, distance, active/basal calories, flights | GREATEST-on-write monotonic guard + cross-source `max_sum` | **Y** (also protected against undercount) | `:451-462`, `:962-980` |
| blood_glucose_readings_count, blood_pressure_readings_count, som_check_in_count | GREATEST-on-write monotonic guard (#3119 — joined the mechanism above via `_READING_COUNT_GUARD_FIELDS`, kept as its own set since these are single-source per-payload counts, not a cross-device max-of-sums) | **Y** (also protected against undercount) | `:465-482`, `:962-980` |
| cgm, blood_pressure, state_of_mind (DDB, non-count fields) | Stateless recompute from the payload → last-write-wins | **Y** for an identical replay | `:1647`, `:1733` |
| cgm, blood_pressure, state_of_mind, workouts (S3) | Read-merge-dedup on the reading's own `time` / `id`; `put_object` skipped when nothing is new | **Y** | `:1096-1123`, `:1126-1151`, `:1154`, `:1510` |
| raw payload archive | Key leaf is `{DD}_{sha256(payload)[:16]}.json` (#3119, was pure wall-clock `DD_HHMMSS.json`) — a redelivery of identical bytes the same UTC day resolves to the SAME key, an idempotent overwrite | **Y** for a same-day replay of identical bytes | `:1540-1566` |

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

| Route | Mechanism today | Replay-safe |
|---|---|---|
| `/api/challenge_vote`, `/api/experiment_vote`, `/api/predict_week`, `/api/replicate_certify` | Conditional put on `IP#{ip_hash}#…` (`attribute_not_exists(pk)`) gates the `ADD` counter; replay 429s or returns `counted: false` | **Y** |
| `/api/challenge_follow`, `/api/experiment_follow` | Conditional put on `EMAIL#{email_hash}#…` → `already_following` | **Y** (the hourly rate counter double-spends, but fails *closed*) |
| `/api/experiment_suggest` | Content hash **+** `ConditionExpression="attribute_not_exists(sk)"` → true no-op, `duplicate: true` | **Y** — the strongest door on the surface |
| `/api/challenge_checkin` | Read-modify-write dedup on `date` | **Y** for replay; races on truly simultaneous delivery |
| `/api/cohort_submit`, `/api/ritual_log` | Natural-key overwrite (`SUBMIT#{ip_hash}`, `DATE#{date}`) | **Y** |
| `/api/subscribe` | Natural key `EMAIL#{sha256}` — no duplicate row, but a resubmit mints a **new token** and re-sends the confirmation | **Partial** — `filed #3113` |
| `/api/subscribe?action=confirm` / `unsubscribe` | Token is `REMOVE`d on confirm (self-invalidating); unsubscribe guarded by a status read | **Y** |
| `/api/submit_finding`, `/api/board_question` | Content-addressed — but under a `{date}` / `{YYYY-MM}` prefix, and an unconditional `put_object` | **N** — a boundary-crossing retry duplicates AND resets `status` over a moderation decision. `filed #3118` |
| `site_api_ai` follow-up turn | `ADD followup_count` + `list_append`; the condition enforces the **cap and IP**, never turn identity | **N** — a duplicate appends the same turn twice and burns two of three reader follow-ups. `filed #3118` |
| `site_api_ai` session mint | `pk = SESSION#{secrets.token_urlsafe(24)}` | **N** — mints a second row; bounded by a ≤1h TTL. `filed #3118` |
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
