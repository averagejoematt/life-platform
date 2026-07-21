# HANDOVER — Opus/no-Fable: honest ceiling re-confirmed; #1610 follow-up resolved (window is load-bearing) — 2026-07-20 (late evening)

> Instruction thread: "ultracode +2M — continue the drain (75 → as low as honesty allows), same
> contract. **Still opus only** (Fable credits NOT restored → Tier 1 fable work stays fenced)."
> First-action TCC probe still **EPERM** → whole session ran from a `/private/tmp` gh clone (the
> proven pattern). All merges/deploys/pushes authorized; IAM stays user-NAMED.

## Outcome — board UNCHANGED at 75. Zero honest closes available; NONE forced. This is the ceiling.
## The one Tier-2 Opus item (#1610 follow-up) was investigated to a definitive conclusion (below).
## No code merged/deployed — because nothing was honestly shippable, exactly as last session predicted.

**#1610 follow-up — RESOLVED as "diagnostic works; alarm window is correctly sized; today's fail not
retroactively nameable":**
- **Itemized logging works.** The 4:50 PM PT post-deploy run emitted 8 named `[QA] WARN …` lines
  (freshness/score/mcp). The next scheduled FAILURE will be named `[QA] FAIL {cat}/{name}: {msg}`.
- **Today's scheduled run DID fail** (18:30 UTC / "11:30 AM PT", RequestId cacf513f, FailCount 1,
  Pass 18 / Warn 8 / Paused 4) — but it **predates the 23:49 UTC #1610 deploy**, so the itemized
  line doesn't exist for it. **Not retroactively nameable.**
- **Dashboard-freshness hypothesis DISPROVEN** (verify-don't-assume paid off again): S3 versioning
  is ON — `list-object-versions dashboard/matthew/data.json` shows a **17:07 UTC** write, so at the
  18:30 run the dashboard was **1h23m old → fresh**. `check_s3_freshness` did NOT fail. The 1 fail
  was a transient MCP/live-fetch/score check that self-cleared (a clean invoke now = 0 fails).
- **"Shorten the daily-Maximum window" is the WRONG move — the 24h latch is LOAD-BEARING.**
  `AlertDigest` runs **15:00 UTC** (`cron(0 15 …)`); `qa-smoke` runs **18:30 UTC** (`cron(30 18 …)`).
  The digest reads `describe_alarms(ALARM)` ~20.5h AFTER the prior qa run, so the alarm MUST stay
  latched ~24h for the failure to reach the digest. A shorter period would self-clear → the daily
  digest would **silently miss** qa failures (breaking the #1445 visibility). The real (bigger) fix
  is re-sequencing qa-smoke BEFORE the 15:00 digest — a system-wide scheduling change (every
  `to_digest` alarm), route through owner/design, NOT a solo rush. **New memory captured.**
- **Manual invokes pollute the window**: a dev-session `aws lambda invoke life-platform-qa-smoke`
  when data.json is >4h old trips `check_s3_freshness` (the only critical freshness FAIL) → spurious
  FailCount. A latched `qa-smoke-failures` is NOT necessarily a real scheduled-run failure — check
  the metric timestamp against the 18:30 UTC slot first.

**Owner-queue verification (verify-don't-assume — unchanged from last session):**
- **Canary STILL BLIND.** Invoked `life-platform-ai-quality-canary` → `status=BLIND`, all 5 probes
  403, transport self-test firing as designed. Operational-stack IAM grant **NOT yet applied** →
  **#1589 correctly stays OPEN** (no false close).
- **TCC still revoked** (~/Documents EPERM) — re-grant still owner-pending.
- **Main red = the by-design R8-ST6 Plan gate ONLY** — confirmed the sole failing CI/CD job on
  5af4771 is "Plan deployments" (over the un-applied canary IAM); every other job green/skipped.
- No new Dependabot PRs (garminconnect / black 26.x still don't exist → Tier 3 skip).

## Standing-ops glances (this session)
- **restart_integration_check --expect-cycle 9:** 20 pass / 4 fail / 7 skip — IDENTICAL to last
  session. All 4 fails KNOWN/allowlisted: hevy (6/25), notion (5/25), strava (7/14) dark; +
  cloudwatch-alarms bundling ai-canary-blind/overall (→ IAM deploy), ai-tokens-* (heavy Bedrock),
  qa-paused-by-budget (tier), qa-smoke-failures (today's real transient fail, now #1610-diagnosable).
  **No new finding.** SSM cycle live=9 expected=9. DLQ 0.
- **felt_probe = n=0** (DDB COUNT 0, unchanged) — wrap-noted, not chased.
- **Tue restart_verify** (expect 12/12) is a *tomorrow* op — session is Mon ~17:15 PT (16:30 UTC
  compute hasn't run). Not applicable this session.
- **ai-canary-heartbeat** self-heals after Wed 16:20 UTC (unchanged).

## Gotchas / notes
- **Owner PR #1491** (feat(ops): GitHub quota/billing observability, #1334/#1453) is the OWNER's own
  PR, stale since 2026-07-19, mergeState UNKNOWN, **failing "Wiki drift gates"** — NOT touched
  (owner's WIP, failing gate, needs rebase). In the decision menu as resume/rebase-or-close.
- Cosmetic drift (unchanged): `PLATFORM_STATS.test_count` 4794→4795 in site_api_common.py; live
  site-api serves 4794 until the next site-api/fleet deploy. Self-heals.
- Gmail MCP token expired last session — qa-smoke failure emails still unreadable (owner re-auth if
  ever needed for inbox diagnosis).

## Live state at wrap
- **Board: 75 open** (unchanged).
- **Main:** 5af4771; test/lint/deploy-critical green; Plan gate reds by-design (canary IAM);
  Deploy stages WAIT on the owner production-approval gate. CI queuing healthy. (This wrap adds one
  docs-only commit — the handover + archive — no deploy.)
- Cycle 9; site healthy on latest content. Dark sources unchanged. TCC still revoked.

## Owner queue (the decision menu — nothing blocks; all optional)
1. **TCC re-grant** (~/Documents) — restores normal local work; else next session forks to clone.
2. **`cdk deploy LifePlatformOperational`** (canary IAM) → invoke canary → expect OK/Blind=0 →
   **close #1589**; also clears the by-design main Plan-gate red. (user-NAMED IAM)
3. **#1435 IAM grant** — traffic-digest role read on the perf store (DDB or S3) so the perf-trend
   half can ship (closes epic #1425). (user-NAMED IAM; code side scoped + ready.)
4. **#1243 audio** — regenerate the Prologue Part II read-aloud (dated 2026-07-19) so it's no longer
   orphaned; then the parity guard lands green.
5. **#1475** — schedule the design-round-trip (or a Fable session) for the wayfinding layer.
6. **#1491** — YOUR stale PR (billing observability): resume/rebase (fix Wiki-drift gate) or close?
7. **#1544 billing** — confirm root cause from the billing page; decide the budget posture.
8. **Fable credits** — if restored, next session's Tier 1 (#1481/#1483/#1577 conversational) is the
   real meat; still-Opus means the honest ceiling stays low.
9. Standing (unchanged): approve the waiting CI Deploy run (fleet-sync); Tue restart_verify after
   the 16:30 UTC compute; if you want the qa-smoke alarm to reflect same-day failures, the real fix
   is re-sequencing qa-smoke before the 15:00 UTC AlertDigest (system-wide — route through design).

**Build beat:** unchanged (no code change this session; server-side qa-smoke build stays
`2026-07-20-qa-smoke-itemized-logging`). **Docs:** this wrap + one new memory
(`reference_qa_smoke_alarm_window_load_bearing`). **Main:** red — sole failing job is the by-design
R8-ST6 Plan gate; all test/lint/deploy-critical green on 5af4771. **Stash/hooks:** clone stash empty;
main-checkout stash/hook state UNVERIFIABLE (TCC) — re-check after the re-grant.

Prior session: `HANDOVER_2026-07-20_QaSmokeItemized.md`.
