# Handover — Session AD: the three features, and a card that shipped public (2026-09-13 ~20:00Z → 2026-09-14 ~17:30Z)

**Driver:** Opus 5 (1M). Owner brief: the three features from his week-one review, by priority —
**P1** the Hevy/training tool fixes (#3762) plus planning-engine v1, **P2** the daily Instagram card
with a back-catalogue (#3741), **P3** progress photos (#3743). Standing authority to merge and
deploy each slice; CDK deploys announced. Overnight constraint: **render only, deliver nothing**.

---

## What shipped, merged AND deployed

| PR | What | Deployed |
|---|---|---|
| **#3776** | Hevy: every free resolution step before the paid one; the template index gets a producer (#3764) + a dead-man; the MCP soft timeout returns AT the deadline | `LifePlatformIngestion`, `hevy-backfill`, `life-platform-mcp` |
| **#3779** | `get_exercise_history` restored; `get_exercise_notes` reports `layer_status` (merged pre-session, deployed here) | `life-platform-mcp` |
| **#3777** | One server-side planning engine + the owner's redlines as a file he edits (`ACTIVE=False`) | `life-platform-mcp` |
| **#3782** | Progress-photo tier registered BEFORE any photo exists; #3719 measurements stamped `TIER_OWNER_PUBLISHED` | no deploy needed (registry only) |
| **#3780** | The daily recap card, as a campaign post | `LifePlatformOperational` |
| **#3783** | **The cards were world-readable — moved off the public prefix** | `LifePlatformOperational` |

## The headline: a feature that had never once worked

`#3768` was an IAM grant. The extractor's Bedrock call raised `AccessDenied`, `extract_signals`
caught it, wrote the deterministic fallback and reported success — for the whole life of the
feature. **Live proof after deploy:**

- `training_notes#USAGE / MONTH#2026-09` → **`calls: 15`**, on a counter that had **no item for any
  month** (it only increments after a successful call)
- `extracted_by` → **15 `hybrid`, 7 `haiku`, 22 not degraded**, where every record had been
  `deterministic` + `degraded: true`
- `get_exercise_notes` → **`layer_status: "ok"`, `extractor_dark: false`, `degraded: 0`,
  "Training-note extractor healthy."**
- `list_available_tools` → **`get_exercise_history` present, 83 registered** (it had been pruned
  while another tool's description still cited it)
- The index dead-man fired on its own 13:40Z rule before I invoked anything;
  `hevy-template-index-not-rebuilt-48h` sits **OK** on a real datapoint. Index: 820 templates.

## The card pipeline, verified by shipped behaviour

9 PNGs rendered from live DynamoDB (Days 1–7, Day 8, week-01). The beats genuinely vary —
`scorecard` on the untrained Day 1, `session` on training days with real set counts, `trajectory`
on the one day he weighed in. **Day 1 did NOT choose "new weigh-in"**, which is the cross-cycle bug
that bit twice. The Day-7 row: `privacy: {status: cleared, blocked_templates: [streaks]}`,
`delivered: {}` — **nothing was sent to him.**

## The defect I shipped, and closed the same hour

The cards went live **world-readable**. Full account in `docs/INCIDENT_LOG.md` (2026-09-14, P2) and
the durable lesson in memory (`reference_a_private_artifact_under_a_public_prefix`). In short: the
bucket grants anonymous `s3:GetObject` on `generated/*` **at the origin**; my privacy test asserted
*no CloudFront route*, which was true and was never the property that mattered. Verified live at
200/48,779 bytes/byte-identical. **This was #3559 one prefix over** — same defect, already fixed
once, whose guard named two doors by hand. Mitigated by overwriting in place (deletion is denied on
`generated/*`), fixed by moving to `recap/` and guarding the SET. Anonymous GET now **403**.

## Gotchas worth carrying

- **`Closes #A, #B, #C` closes only #A.** GitHub honours the keyword only before the first number.
  PR #3780 closed epic #3741 and left five shipped stories open — caught by the (e8) DoD sweep.
- **The premerge lane is a STRICT SUBSET of the full unit suite.** I twice reported a branch green
  off a passing premerge run; the full suite then found real things (the #3609 ISO-parse registry,
  the pillow layer manifest). Premerge-green is not green.
- **Two gates in apparent conflict were the answer.** The ISO-parse subset check demanded a file be
  registered; the shrink-only ratchet forbade growing the registry. Together they left only the real
  fix: `pacific_time` had been doing calendar-day parsing internally twice without exposing it, so
  every caller open-coded it — most of what that 65-file registry inventories. Now `parse_day_key` +
  `shift_day_key`, the second built on the first.
- **`git add -A` swept a test's mutation probe into a commit.** One stray file produced FOUR red
  gates, only one about it; the three loud ones sent me looking in the wrong place first.
- **A `git reset --hard` after a piped `git checkout` hit the wrong branch** — the pipe returned
  `tail`'s status so `&&` ran anyway. Destroyed the card branch; recovered from reflog.

---

**Build beat:** 2026-09-14-three-months-dark
**Docs:** SCHEMA.md (recap prefix + the reason it is private), DATA_GOVERNANCE.md (two Tier-2 rows + the `recap/` changelog row), INCIDENT_LOG.md (P2 row), PROPORTIONALITY.md (3 rows), MONITORING.md + ARCHITECTURE.md (regenerated counts), OPERATING_KNOWLEDGE_LEDGER.md (2 rows + snapshot), alarm_citations.json (2 entries), .claude/skills/deploy/SKILL.md (function→source table)
**Decisions:** none needed — the two judgment calls (the recap prefix, Telegram as a fourth capture channel) are recorded in the code and test docstrings that enforce them, not new architecture; ADR-140 rule 5 and ADR-155 already governed both
**Main:** red — `Deploy-critical tests` exited 2 on `d1950442` (a pytest collection/usage error, not test failures). The identical selection passes locally on that sha: `pytest -m "deploy_critical and not integration"` → **1880 passed, 36 skipped**. Cause not yet determined: GitHub withholds job logs until the whole run completes and `test / Unit Tests` was still running at wrap. NOT the IAM-gate class that redded the four preceding main runs — those were `Plan deployments` (R8-ST6, #1901), and both stacks have since been deployed so that leg should clear. **First thing next session: read that job's log.**
**Incidents:** 1 row added — the recap cards world-readable for ~47 min (P2, 2026-09-14), mitigated by overwrite and fixed by prefix move
**Stash/hooks:** clean
**Closures:** #3719, #3757, #3744, #3745, #3746, #3747, #3748 commented; #3741 REOPENED (two real children remain: #3749 the coach line, #3750 the Instagram account) · DoD: scanned 8, hits 0
**Backlog:** Now live; #3781 filed this session and brought to the ADR-099 contract (Problem/Set/Outcome/Acceptance/Score/Epic). Later sweep — no stale issues surfaced. **(e7) remains red on 61 PRE-EXISTING corpus violations** (51 `set_section`, from the newer #3594 rule); none is on an issue this session filed, touched or closed — the gate's own contract is met, the corpus debt is not mine to pay here and is not silently skipped
**Alarms:** 0 red >72h; 2 fired-and-cleared flaps cited — `hevy-template-index-not-rebuilt-48h` and `recap-card-no-invocations-24h`, both BIRTH flaps (a `treat_missing_data=BREACHING` dead-man enters ALARM the instant it is created and clears on its first datapoint; every future one will do the same)
**CI warnings:** unverified — the latest completed main run isn't green, so there is no green run to read annotations from
**Ledger:** 3 rows added — the daily recap card, the Hevy index rebuild + dead-man, and the public-write prefix registry

---

## Residual / next picks

- **Read the `Deploy-critical tests` log on `d1950442` and fix or explain it** — exit 2, passes locally. `not-work — a diagnosis step, not a backlog item; it becomes an issue only if it is a real defect`
- **#3781** — the surface-drift gate's CRON leg sees 16 of 86 schedules; the paved-road `schedule="cron(...)"` form is invisible to it
- **#3749** — the grounded coach line / caption for the card (out of v1 deliberately)
- **#3750** — the dedicated Instagram account + handle
- **#3758** — progress-photo capture (PR 2). #3782 merged first, which was the point
- **#3760** — the progress-photo viewer (PR 3). Secret `life-platform/progress-token-secret` exists
- **The owner's verdict on the 22 review cards** on his desktop, and whether to `--deliver` `not-work — his call, and the reason nothing has been sent`
- **#3753** redlines `ACTIVE` flag `not-work — his to edit`
- **#3770** Calf Press muscle group `not-work — his 20 seconds in the Hevy app`
- **61 pre-existing backlog-hygiene violations** (51 `set_section`) `not-work — corpus debt predating this session; a batch cleanup, not a session residual`
