# HANDOVER — Opus/no-Fable drain: honest ceiling reached; qa-smoke observability shipped — 2026-07-20 (evening)

> Instruction thread: "ultracode +2M — continue the drain (83 → as low as honesty allows), same
> contract. Tier 1 = carried-over **fable** work (#1481/#1483/#1577). **Addendum: out of Fable
> credits for 5 days, switched to Opus — DO NOT work on candidates much better done via Fable.**"
> First-action TCC probe still EPERM → whole session ran from a `/private/tmp` gh clone (the proven
> pattern). All merges/deploys/pushes authorized; IAM stays user-NAMED.

## Outcome — board 76→75 issues (one epic closed) + 1 Dependabot PR + 1 net-new ops fix
## filed→shipped→deployed→verified. The honest close ceiling for a solo/no-Fable session is LOW
## and was reached: a two-agent sweep confirmed **no other issue is honestly closeable** right now.

**Closed (this session):**
- **#1355** (epic — Dead controls) VERIFIED-DONE: all 8 children (#1319–#1326) verified CLOSED.
- **#1610** (NEW, filed + SHIPPED this session): qa-smoke logged only the EMF summary; the specific
  failing check went ONLY to the failure email → a latched `qa-smoke-failures` daily alarm was
  undiagnosable from CloudWatch (hit live — Gmail token also expired). Fix: print every fail/warn
  as `[QA] {FAIL,WARN} {category}/{name}: {msg}` before the `if not fails:` gate. PR #1611 merged
  (5af4771), full suite green (no -x), guard proven RED on 5af4771~1. **Deployed** qa-smoke
  (CodeSha256 `D3imGU5P6+…`, was `rAU+UkBD…`) and **verified live**: a warnings-only invoke now
  emits 8 named `[QA] WARN …` lines. This is the diagnostic that names the next scheduled FAILURE.
- **#1191** (Dependabot) MERGED: actions-group bump (checkout v7.0.0→v7.0.1, setup-python
  v6.3.0→v7.0.0) across 13 workflow YAMLs, all gates green, python pinned 3.12 so the major is safe.

**Owner-queue verification (the "verify, don't assume" mandate — paid off):**
- **Canary still BLIND.** Invoked `life-platform-ai-quality-canary` → `status=BLIND`, all 5 probes
  403, transport self-test firing exactly as designed. The Operational-stack IAM grant is **NOT yet
  applied** → **#1589 correctly stays OPEN** (did not double-do / did not falsely close).
- **Email stack IS deployed** (many `LifePlatformEmail-*` rules ENABLED, incl. Sunday crons).
- **TCC still revoked** (~/Documents EPERM) — re-grant is still owner-pending.
- **Main red = the by-design R8-ST6 Plan gate ONLY** (over the un-applied canary IAM); all
  test/lint/deploy-critical green on 5af4771. CI queuing healthy — no #1544 silent-death recurrence.

**Deferred with reasons (all have irreducible owner/design/Fable dependencies — NOT punts):**
- **#1435** perf-trend persistence (opus, sole open child of epic #1425): metrics are ALREADY
  captured per-page in `tests/visual_qa.py` (`perf_result` → report.json). The gap is persist +
  weekly trend + retention. BUT the digest lambda role (`LifePlatformOperational-TrafficDigestRole…`)
  has **no read access to DDB OR the data-bucket S3** (both implicitDeny, simulated live) — so the
  read side is **owner-gated IAM regardless of store**. DDB TTL is enabled (`ttl` attr) → clean
  retention. Deploy role CAN write S3 (`matthew-life-platform`) but CANNOT PutItem DDB. Design:
  persist per-page perf from the daily `visual-qa.yml` (it has OIDC creds) → S3, weekly trend as a
  new source in `traffic_digest_lambda.collect_green_report()`. **Needs one owner IAM grant.**
- **#1475** wayfinding (opus, last of the design trio): the `loop_ribbon()` in `scripts/v4_kit.py`
  ALREADY draws the full loop with the current station marked (so "current+adjacent" is inherently
  met); it's on ~4 generator families, not all pages. Universalizing it via `v4_apply_chrome.py`
  (like #1468's loop-forward) is buildable BUT has real design decisions: placement consistency,
  **fine-key preservation** (method/game pages show ribbon key "method" though door=/data/), and the
  AC's "footer mega-menu **redesigned through the design round-trip**" — the epic explicitly routes
  this through the Claude Design pipeline. With Fable exhausted + no live design partner, rushing an
  all-80-pages change solo was the wrong risk. **Deferred to a design-round-trip/Fable session.**
- **#1243** orphaned Prologue Part II audio: STILL reproduces — episode "The Plan, On the Record"
  dated 2026-07-11 vs the article now at **2026-07-19** (moved with the cycle-9 reset); title
  matches, dates don't → `read_aloud.js` honest-empty. The fix regenerates **reader-facing narrated
  public audio** (retired chronicle-podcast cron, manual-invoke only) → owner-review content, not an
  autonomous republish. The regression guard would correctly RED until the audio is regenerated
  (can't ship green). **Owner regenerates the audio; then land the parity guard.**
- **#1544** CI-queuing incident: CI queues again (verified), but ACs need owner billing-page
  confirmation + a new detector in the #1453 lane. Stays open.

## Standing-ops glances (this session)
- **restart_integration_check --expect-cycle 9:** 20 pass / 4 fail / 7 skip. The 4 fails all
  KNOWN: hevy (6/25), notion (5/25), strava (7/14) dark; + the cloudwatch-alarms line bundling
  ai-canary-blind/overall (→ IAM deploy), ai-tokens-* (heavy Bedrock load), qa-paused-by-budget
  (tier posture). **qa-smoke-failures WAS outside the allowlist → investigated → #1610** (latched
  daily-Maximum on intermittent scheduled fails; clean invoke = 0 fails; now diagnosable).
- **felt_probe = n=0** (DDB `USER#matthew#SOURCE#felt_probe` COUNT 0) — wrap-noted, not chased.
- **Tue restart_verify** (expect 12/12) is a *tomorrow* op — the 16:30 UTC compute hasn't run
  (session is Mon ~16:50 PT). Not applicable this session.
- **ai-canary-heartbeat** self-heals after Wed 16:20 UTC (unchanged).

## Gotchas / notes
- Cosmetic drift: the reconcile bumped `PLATFORM_STATS.test_count` 4794→4795 in
  `lambdas/web/site_api_common.py`; the LIVE site-api serves 4794 until the next site-api/fleet
  deploy. Self-heals; not worth a standalone site-api deploy for +1.
- Gmail MCP token expired — qa-smoke failure emails unreadable this session (part of why #1610
  matters). Owner re-auth if inbox diagnosis is ever needed.
- deploy_lambda.sh confirmed ships the FULL tree (single-file-strip class dead, #781) — used for
  the targeted qa-smoke deploy.

## Live state at wrap
- **Board: 75 open** (was 76 issues at session start; #1355 closed; #1191 was a PR).
- **Main:** 5af4771; test/lint/deploy-critical green; Plan gate reds by-design (canary IAM);
  Deploy stages WAIT on the owner production-approval gate. CI queuing healthy.
- Cycle 9; site healthy on latest content. Dark sources unchanged. TCC still revoked.

## Owner queue (the decision menu — nothing blocks; all optional)
1. **TCC re-grant** (~/Documents) — restores normal local work; else next session forks to clone.
2. **`cdk deploy LifePlatformOperational`** (canary IAM) → then invoke canary once → expect
   OK/Blind=0 → **close #1589**; also clears the by-design main Plan-gate red. (user-NAMED IAM)
3. **#1435 IAM grant** — give the traffic-digest role read on the perf store (DDB or S3) so the
   perf-trend half can ship. (user-NAMED IAM; the code side is scoped + ready to build once granted.)
4. **#1243 audio** — regenerate the Prologue Part II read-aloud (dated 2026-07-19 to match the
   article) so it's no longer orphaned; then the parity guard can land green.
5. **#1475** — schedule the design-round-trip (or a Fable session) for the wayfinding layer.
6. **#1544 billing** — confirm root cause from the billing page; decide the budget posture.
7. Standing (unchanged): approve the waiting CI Deploy run (fleet-sync); pr-checks required-ness
   toggle (advisory today); Tue restart_verify after the 16:30 UTC compute.

**Build beat:** unchanged public build; server-side ops fix (`2026-07-20-qa-smoke-itemized-logging`).
**Docs:** #1611 carried TESTING.md (test-count) + the #1610 code comment; this wrap adds no ADR/
INCIDENT rows (TCC already logged; no new incident). **Main:** red — sole failing job is the
by-design R8-ST6 Plan gate; all test/lint/deploy-critical green on 5af4771. **Stash/hooks:** clone
stash empty; main-checkout stash/hook state UNVERIFIABLE (TCC) — re-check after the re-grant.

Prior session: `HANDOVER_2026-07-20_MaxDrain.md`.
