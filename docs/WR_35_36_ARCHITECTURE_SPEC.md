# Architecture Spec — WR-35 (Pause Mode) + WR-36 (Stale-Source Alerts)

**Date:** 2026-05-03
**Source:** AJM Re-Entry Plan, Phase 10 ("Build the Repeatable Pattern") + post-mortem of the Apr 2 → May 2 silence.
**Status:** Design spec, ready for Claude Code or focused build session.

---

## Why these two together

The 4-week silence post-move surfaced a system-level weakness: **the platform was not silence-resilient.** When Matthew stopped tracking, the system did not gracefully degrade. Instead:

1. OAuth tokens expired silently (Garmin, Strava).
2. Habits flatlined to 0% with no distinction between "actively skipped" and "not tracked."
3. Streaks broke and were not recoverable.
4. The freshness checker Lambda *should* have alerted — but either didn't fire, fired silently, or got lost in noise.
5. The character sheet, Pillars, and digests kept computing against stale data, producing low-grade misinformation.

These two workrolls together fix the pattern. **WR-35 (Pause Mode)** is the user-declared graceful degradation. **WR-36 (Stale-Source Alerts)** is the system-detected cousin — it catches the gap when Matthew didn't declare one. Either alone is half the solution.

---

## WR-35 — Pause Mode

### User story

> As Matthew, when I know I'm going to be away from the platform for >7 days (planned trip, family emergency, mental-health reset, anything), I want to declare a pause so the platform stops grading me, suppresses streak punishment, and shows the gap honestly on the public site instead of erasing or stretching data to fill it. When I come back, I want a structured re-entry that respects the gap and accelerates getting honest again.

### Behavior — when paused

When Pause Mode is active:

1. **Habit scoring suppressed.** No habit completion is computed for paused dates. Tier-0 habits that go uncompleted do not break the streak — they emit `paused` instead of `failed`. Streak counters freeze, not break.
2. **Character sheet uses last-known values.** The character sheet does not recompute pillars during pause. The displayed score is "as of [pause start date]" with explicit pause framing.
3. **Daily brief suppressed.** No daily brief Lambda runs during pause. No emails go out.
4. **Weekly digest annotated, not suppressed.** Elena Voss (or the digest narrator) runs in a "Pause Chronicle" mode — the digest exists but its job is to mark the gap, not to grade behavior.
5. **Public site shows the pause.** The site renders a gap banner: "Cycle 1: April 1 – April 1. Pause: April 2 – May 1 (move). Cycle 2: May 2 →" — with whatever cycle naming the user has set.
6. **Freshness checker suppressed.** During pause, stale-source alerts do not fire. WR-36 reads the pause state and skips alerting.
7. **Subscriber list (if any) gets one "On Coming Back" post on un-pause, not silence + abrupt restart.**

### Behavior — entering pause

User declares pause via MCP tool:

```
life-platform:start_pause \
  reason="Move to new house" \
  expected_return_date="2026-05-01" \
  cycle_label_before="Cycle 1: Launch" \
  cycle_label_after="Cycle 2: Re-Entry"
```

Side effects:
- Writes a `PAUSE#` record to the `life-platform` DDB table partition `USER#matthew#PAUSES`.
- Disables the daily brief EventBridge rule.
- Suppresses freshness checker SNS publishes (does not disable the Lambda — keeps logs flowing).
- Posts the gap banner to the public site via `site_writer` Lambda.

### Behavior — exiting pause

User declares un-pause:

```
life-platform:end_pause \
  return_date="2026-05-02"
```

Or auto-detection: if `expected_return_date` passes by ≥2 days *and* a habit completion fires for the user, end the pause automatically (with a notification — not silently).

Side effects on un-pause:
- Re-enables daily brief EventBridge rule.
- Triggers a one-time "re-entry challenge" creation: `create_challenge name="7-Day Re-Entry: Essential Seven Only" status=active duration_days=7 source=hypothesis_graduate source_detail="Auto-generated from end_pause"`.
- Triggers a one-time "On Coming Back" content slot in the next weekly digest.
- Triggers a `capture_baseline label='reentry_<DATE>'` automatically.
- Resumes freshness checker alerts (but with a 48-hour grace period — don't immediately alert that data is stale on day 1 of re-entry).

### DDB schema

```
pk = USER#matthew#PAUSES
sk = PAUSE#<start_date>
attrs:
  start_date: "2026-04-02"
  end_date: "2026-05-02"  # null while active
  reason: "Move to new house"
  expected_return_date: "2026-05-01"
  cycle_label_before: "Cycle 1: Launch"
  cycle_label_after: "Cycle 2: Re-Entry"
  baseline_captured: false  # set true when end_pause fires
  reentry_challenge_id: null  # populated on end_pause
  status: "active" | "completed" | "abandoned"
  created_at: ISO8601
  updated_at: ISO8601
```

**Read pattern:** "Is the platform currently paused?" — query partition with `status = active`, single item expected.

### MCP tools to add

```
life-platform:start_pause      → tools_lifestyle.py
life-platform:end_pause        → tools_lifestyle.py
life-platform:get_pause_state  → tools_lifestyle.py (read tool)
life-platform:list_pauses      → tools_lifestyle.py (history)
```

(These will trip TD-21 timezone import bug. Land TD-21 first or include the timezone import in the patch.)

### Lambda integrations

Lambdas that need a pause-aware short-circuit at the top of their handler:

- `daily_brief_lambda.py` — exit early if paused.
- `field_notes_lambda.py` — exit early if paused.
- `weekly_digest_lambda.py` — switch to "Pause Chronicle" mode if paused.
- `freshness_checker_lambda.py` — suppress SNS publish if paused (already has sick-day suppression pattern; mirror it).
- `character_sheet_lambda.py` — exit early if paused; do not recompute.
- `dashboard_refresh_lambda.py` — exit early if paused.
- `evening_nudge_lambda.py` — exit early if paused.
- `monday_compass_lambda.py` — exit early if paused.

Pattern for each:

```python
from pause_checker import check_paused
def lambda_handler(event, context):
    if check_paused(table, USER_ID):
        logger.info("Platform paused — skipping")
        return {"status": "paused", "skipped": True}
    # ...rest of handler
```

Add `lambdas/pause_checker.py` — single-purpose helper, mirrors `sick_day_checker.py`. ~25 lines.

### Public site rendering

The site needs a gap-aware timeline visualization. Two surfaces:

1. **Homepage hero.** When pause is active, replace the "current status" block with a "Currently paused: <reason>, expected back <date>" block.
2. **Cycle/Chapter timeline.** Add a visual timeline marker on key pages (labs, character, chronicle index) showing Cycle 1 / Pause / Cycle 2 boundaries.

Implementation: extend `site_writer.py` to read pause state and render conditionally. New CSS class `.pause-banner`. Defer fancy visualizations — start with text + a horizontal timeline bar.

### Order of build

1. DDB schema + pause_checker.py helper.
2. `start_pause` / `end_pause` / `get_pause_state` MCP tools.
3. Lambda short-circuits, one Lambda at a time, deployed individually so any breakage is isolated.
4. Site rendering.
5. Auto re-entry challenge + capture_baseline integration on end_pause.

Do not build all at once. Each step is independently shippable.

### Acceptance criteria

- Calling `start_pause` results in: pause record in DDB, daily brief Lambda no longer fires, freshness alerts suppressed, site banner visible.
- Calling `end_pause` results in: pause record marked completed, re-entry challenge created, baseline captured, daily brief resumes.
- A simulated un-paused → paused → un-paused cycle does not break the character sheet streak — the streak resumes from where it was, with the pause days marked as `paused` not `failed`.

---

## WR-36 — Stale-Source Alerts (enhancement, not greenfield)

### Discovery: the Lambda already exists

`lambdas/freshness_checker_lambda.py` already does:
- Per-source staleness checks against `STALE_HOURS` threshold (default 48h).
- Per-source override threshold (food_delivery 90d, measurements 60d).
- Field-level completeness checks (a "fresh" record can still be partial).
- OAuth token age check — alerts if any OAuth secret hasn't been updated in `OAUTH_STALE_DAYS` (default 60).
- SNS publish to `arn:aws:sns:us-west-2:205930651321:life-platform-alerts`.
- CloudWatch metrics: `StaleSourceCount`, `FreshSourceCount`, `PartialCompletenessCount`, `OAuthTokenStaleCount`.
- Sick-day suppression.

This is a thoughtful Lambda. The question is **why didn't it alert during the silence?**

### Investigation plan (run before building enhancements)

Four hypotheses, in decreasing order of likelihood:

1. **EventBridge rule disabled / never created.** Check via:
   ```bash
   aws events list-rule-names-by-target --target-arn <freshness-checker-arn> --region us-west-2
   ```
2. **SNS topic has no email subscription.** Check via:
   ```bash
   aws sns list-subscriptions-by-topic --topic-arn arn:aws:sns:us-west-2:205930651321:life-platform-alerts
   ```
3. **Subscription exists but emails went to spam / inbox bankruptcy.** Check the email account being subscribed to.
4. **CloudWatch logs show silent Lambda failure.** Check:
   ```bash
   aws logs tail /aws/lambda/life-platform-freshness-checker --since 30d --region us-west-2
   ```

Until you know which hypothesis is correct, building enhancements would compound the problem.

### Enhancements to add (after investigation)

Once the existing Lambda is verified-firing-correctly, the plan's WR-36 ask is to **add a user-facing surface** beyond SNS-to-email. SNS-to-email is dev-facing (gets buried in inbox); the plan said "daily-brief alert" which is user-facing.

#### Enhancement 1 — daily brief integration

Modify `daily_brief_lambda.py` to read `LifePlatform/Freshness/StaleSourceCount` CloudWatch metric on every run. If non-zero, prepend a "⚠️ Data Status" block at the top of the brief:

```
⚠️ DATA STATUS — 2 sources stale
  - Garmin (last update: 2026-04-05, 27 days ago)
  - Strava (last update: 2026-04-18, 14 days ago)
The intelligence below is based on the data we have.
```

Place this above all other content. Don't suppress the brief — surface the caveat. (If WR-35 Pause Mode is active, daily brief is suppressed entirely; this only fires during normal operation.)

#### Enhancement 2 — escalation tiers

Today, the alert fires whenever any source crosses the threshold. Add escalation:

- **Level 1 (yellow):** 1 source stale, < 7 days — single line in daily brief, no email.
- **Level 2 (orange):** 2+ sources stale, OR any source >7 days stale — daily brief block + daily SNS email.
- **Level 3 (red):** 3+ sources stale, OR any source >14 days stale, OR any OAuth token >50 days unrefreshed — push notification (if mobile is wired up) + persistent banner on public site + daily SNS.

Logic lives in `freshness_checker_lambda.py`. Add a new env var `ESCALATION_TIER_OUTPUT` to make it testable.

#### Enhancement 3 — Pause Mode awareness

When WR-35 lands, the freshness checker should read pause state and short-circuit. Implementation pattern is identical to the existing sick-day suppression — copy that pattern.

#### Enhancement 4 — stale-source dashboard

A read-only MCP tool `life-platform:get_freshness_status` that returns the latest per-source freshness summary. Useful for: "are we OK?" queries from chat. Reads from the same CloudWatch metrics that the Lambda emits — no new computation, just exposure.

```
life-platform:get_freshness_status
→ {
    "status": "yellow",  # green | yellow | orange | red
    "stale_sources": [
      {"source": "garmin", "last_date": "2026-04-05", "age_days": 27},
      {"source": "strava", "last_date": "2026-04-18", "age_days": 14}
    ],
    "partial_sources": [],
    "oauth_stale": [],
    "checked_at": "2026-05-02T22:35:00Z"
  }
```

#### Enhancement 5 — backstop alarm

The freshness checker checks data freshness. **What checks the freshness checker?** If the Lambda silently stops running (which is likely what happened during the silence), nothing detects it.

Add a CloudWatch alarm: if no `StaleSourceCount` metric is emitted in the last 26 hours (Lambda runs daily), alarm fires to a *separate* SNS topic, ideally to a *separate* email address (e.g. a partner's email — Partner), specifically because if Matthew's primary inbox is what's failing, the same failure mode catches the meta-alarm.

This is the cheapest, highest-leverage piece of WR-36. Build it first regardless of the rest.

### Order of build

1. **Investigation.** Find out why the existing Lambda didn't alert. Document findings.
2. **Backstop alarm (Enhancement 5).** Cheapest insurance against the same failure recurring.
3. **Daily brief integration (Enhancement 1).** Highest user-facing leverage.
4. **Escalation tiers (Enhancement 2).** Reduces false-positive fatigue.
5. **Pause Mode awareness (Enhancement 3).** Required for WR-35 coexistence.
6. **Read tool (Enhancement 4).** Convenience.

### Acceptance criteria

- A simulated 48-hour stale gap on a single source produces a Level-1 yellow flag in the daily brief and no email.
- A simulated 14-day stale gap on two sources produces a Level-3 red flag with daily brief banner, SNS email, and (if enabled) a public site banner.
- The backstop alarm fires within 26 hours if the Lambda stops emitting metrics.
- During Pause Mode, no alerts fire regardless of staleness.

---

## Out of scope for this spec

- Mobile push notifications (no mobile app; SNS-to-email + site banner is sufficient).
- Auto-recovery actions (Lambda re-auth on its own). Re-auth requires browser MFA for Garmin; can't be automated cleanly.
- The "On Coming Back" post template — this is content, not infrastructure. Belongs in a separate doc.

---

## Sequencing recommendation

| When | Who | What |
|---|---|---|
| Now | Claude Code | Land TD-21/22/23 patch first |
| Sunday morning | Matthew | Investigation hypothesis check (4 commands above) |
| Sunday afternoon | Claude Code | WR-36 backstop alarm (Enhancement 5) — 30 min |
| Next session | Matthew + Claude Code | WR-36 daily brief integration (Enhancement 1) |
| Following session | Claude Code | WR-35 DDB + MCP tools + pause_checker.py |
| Following session | Claude Code | WR-35 Lambda short-circuits (one at a time) |
| Following session | Claude Code | WR-35 site rendering + WR-36 escalation tiers |
| Final session | Matthew + Claude Code | Auto re-entry challenge + Pause Mode read tool |

Total estimated effort: 6-8 focused sessions across both workrolls. The backstop alarm is the only "must do this week" item; everything else can pace.
