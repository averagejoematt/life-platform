# Handover — 2026-08-22 ~18:00 → ~20:45 PT: fable week, session 1 — Lane A cleared the publish path, and the corpus finally means something

**Session:** Fable 5 (set mid-session), interactive, merge + deploy authority granted as one
numbered ask. The driving instruction: *"fable is back — read the Open-Issue Ledger artifact,
synthesize an effective fable week, really close open issues, and stop the bleeding in
process/bugs/tech-debt — improve the SDLC so paying down backlogs gets easier."* Previous wrap
archived as `HANDOVER_2026-08-22_max-opus-paydown.md` on `session-archive`.

## The synthesis (approved via AskUserQuestion, both recommendations taken)

The 25 `model:fable` issues split **4 machinery / 21 product** — "use fable well" and "stop the
bleeding" point at the same 4 (#2842, #2800, #2846, #2849), not the product majority. Week plan:
**Lane A** (publish path + lying gauges, fan-out) → **Lane B** (one primitive per session:
#2832 operating calendar first — review cadence is what sets the filing rate) → **Lane C**
(corpus semantics). This session executed A + C.

## Shipped — 11 PRs merged, all deployed and verified

- **#3010** (→#3003): both publish-path highs adjudicated against the *rendered page* — one
  rubric fix in code, one baselined under #2959; report.json evidence caps removed.
- **#3008** (→#2992): `days_with_data` counted SKs, not dates — whoop `DATE#…#WORKOUT#` sub-rows
  inflated the column (cycle 1: 16 "days" in a 6-day matched window). One line + mutation-proved
  test. **Verified live:** every cycle ≤ window after deploy.
- **#3011**: the **Roadmap milestone** (ADR-099 amendment) — 26 July product-vision issues parked
  outside the debt corpus; score-line grammar + `MILESTONE_ORDER` + hygiene extended; one
  promotion per cycle. Corpus now: **Now 6 · Next 35 · Later 10 · Roadmap 26** (+2 unmilestoned
  fable epics). The tracked number finally measures defects, not review cadence.
- **#3012** (→#3002): namespace casing twin retired behind one imported constant + set-guard
  (mutation-proved 4 ways); **first-ever alarm on ContentFilterFallback** (threshold derived
  from a 15-month retention query: 62 fires/9 days in March, zero watchers). cdk Serve deployed.
- **#3013** (→#2973): AI-QA silent skips root-caused (screenshots >8000px → Bedrock
  ValidationException swallowed as a pass); downscale pre-call, cannot-evaluate now a gating
  FAIL, evaluated-count printed. **First post-merge CI sweep: 93/93 pages, 0 unevaluated.**
- **#3014** (→#2976): ingest alarms latched because healthy was only ever emitted as 0 —
  dropbox's healthy stream had *never carried a 1 in its life*. Emit on every authenticated
  success + windows 86400→3600s. **Live recovery proof: both alarms (lit since 08-21) flipped
  OK six minutes after the emitter deploy.**
- **#3015** (→#2972): the audience frame is now a property of the surface — `public_summary`
  producer field, deterministic `audience_guard` (full text before truncation), all four public
  consumer seams guarded. Closure verdict **partial**: honest-empty until the coaches' next
  daily run writes the first rows.
- **#3009** (→#2974): scoped `PutMetricData` for the CI diagnosis role, applied attended,
  `verify_oidc_iam.py --strict` CLEAN; telemetry failure now ERROR-visible. **Proof:** the first
  post-apply CI QA job logged zero emit-failures while LifePlatform/AI datapoints landed in its window.
- **#3016 / #3017 / #3020**: same-session repairs of what the queue itself surfaced (below).
- **#3019**: `/method/cycles/` third-objection baseline under #2959 (wrong data-must-exist
  inference vs. the honest absence dash).

**Deploy surface:** site-api + site-api-ai + coach-state-updater + qa-smoke + dropbox-poll +
notion (all sha-postflight-verified), the full fleet via the approved CI run (shared-module
trigger), cdk Serve + Monitoring, and the IAM policy. Superseded deploy-gate leases rejected
(2), the final run approved.

## The three defects the session created and repaired in-session (each now a rule)

1. **I merged #3012 on the agent's stated red-reason without reading the lane** — the real red
   was its unregistered tree-sweeping guard (#2372 class), which red main's pre-merge lane.
   Fixed in ~20 min (#3016); memory rule: the not-green set must equal the expected set exactly.
2. **The reconcile job had the writer but not the write** — #2986 added
   `generate_platform_model.py` to `run_generators()` but never whitelisted
   `model/platform_model.json`, so #3012's alarm killed main CI pre-deploy. Manual reconcile
   per the job's own fallback, then #3017: whitelist + a mutation-proved registry test so the
   class reds pre-merge forever.
3. **#3013's honesty upgrades red the full suite only** (PR lane deselects ~11k tests): a
   string-probe test pinning the old exit line verbatim, a whole-dict assert, pillow parity,
   and a fixture PNG that passed the size filter but died at the new IHDR sniff. Fixed in #3020
   — the fixture must survive *every* filter on the wire path.

## Gate lines (#736 et al.)

**Build beat:** 2026-08-22-the-oracle-stopped-guessing
**Docs:** ARCHITECTURE.md cost-table alarm count (97→109, drift gate); DECISIONS.md ADR-099
amendment (in #3011); SCHEMA.md + MONITORING.md + RUNBOOK.md updated inside the agent PRs;
sync + link/tombstone/index checkers green at commit.
**Decisions:** ADR-099 amendment 2026-08-22 filed (Roadmap milestone, in #3011) — no separate ADR needed.
**Main:** green (d94b11b7a) — #3020's run completed/success with every lane green, full
unit suite included (Deploy correctly skipped on a test-only change; verified by
`check_main_green.py` exit 0). The intervening reds were the in-session repair chain
above, TTR ~2.5h.
**Incidents:** 1 row added — main-red chain 00:45–03:30Z from the two queue-surfaced gaps
(reconcile whitelist + premerge classification), no data loss, no reader impact.
**Closures:** #2992, #2972, #2973, #2974, #2976, #3002, #3003 commented (6 realized, 1 partial — #2972).
**Backlog:** Now 6 actionable of 6 non-blocked after the Roadmap move (3 former Now items
parked as product: #1571, #1629, #1738 — deliberate, they were the product cohort); hygiene OK
over the whole corpus; no stale Later issues printed. Roadmap promotions are explicit
one-per-cycle acts per the amendment.
**Alarms:** 0 red; 3 flaps flagged by the gate = the #2976 recovery episodes themselves
(dropbox + 24h fired-and-cleared around the emitter deploy; liveness cleared organically at
10:11 PT) — named here, gate closed with `--decoded`.
**CI warnings:** 1 — Unit Tests 1427s vs the 1200s budget (fifth breach): owned by the
already-open #2692, deliberately folded into next session's pre-merge-completeness
decision (approved plan, Step 3) rather than re-raising the budget blind.
**Stash/hooks:** clean (empty stash, hook 🟢).
**Ledger:** none — no new standing subsystem; the ContentFilterFallback alarm and the
whitelist registry test fold into the existing alarm-board and #2986-registry rows.

## Residuals / next picks

- **Lane B, session 2 flagship: #2832** (operating calendar + dead-man) — the filing-rate
  lever; then #2986 application, #2846, #2847 (one contract pair), #2999/#3000 (#2578 children).
- **#3018** — integrator public register (filed this session, epic #2799, Next).
- **#2972 tail** (tracked in #3018's body + the #2959 baseline): after the coaches' next daily
  run writes `public_summary`, verify 2 clean oracle runs then delete the `/method/board/`
  baseline entry — not-work — a dated observation step, owned by the next session's boot.
- **#2889** first live `GenerationSkippedUnchanged` observation at the 08-23 17:00 UTC brief —
  not-work — scheduled observation, issue already open.
- **Product allowance if Lane B lands: #1629** (Bluesky shadow, Roadmap → Now would be the
  cycle's one promotion).
- **#2959** — the reader-truth oracle rubric: three objections on one page in one day, two
  over-reads; the baselines are accumulating where rubric fixes belong.
