# Handover — 2026-08-23 (night, Fable 5, autonomous + one owner call): Phase D1 of the A-Grade Program — control boundaries closed: CSP hardened, budget guard fails closed, edge enforcement observed nightly, WAF decided

**Session:** Fable 5. Drove: *"Boot Phase D1 of the A-Grade Program"* — the plan's
"Control boundaries" phase (`~/.claude/plans/lively-juggling-candle.md`), AUTONOMOUS
with merge+deploy authority, ONE owner decision surfaced first (WAF). Owner call
received mid-session: **defer the WAF — dated priced acceptance, revisit ~2026-10-15.**
Previous handover archived as `HANDOVER_2026-08-23_agrade-d0-p0-truth.md` on
`session-archive`.

## What shipped (all merged AND deployed AND live-verified; 7 PRs #3056–#3063)

- **Budget-guard fail-closed (DIL-036 → FIXED)** — PR #3059 (worktree agent). The bare
  `except → tier 0` SSM read split into named classes logging
  `BUDGET_TIER_UNREADABLE reason=<class>`; exported `FAIL_CLOSED_FEATURES=("website_ai",)`
  consulted by `allow()` — public /api/ask + /api/board_ask DENY tier-3-equivalent on
  unreadable budget state (AST-pinned to the real `_ai_paused_response` wire path);
  `current_tier()` stays fail-open fleet-wide (protect-longest deliberate; a phantom
  tier 3 would take the brief down with the public surface). 23 tests mutation-proved
  both directions. **Deployed:** cdk Monitoring (`budget-tier-unreadable` alarm live,
  metric filter scoped to site-api-ai's log group) + site-api-ai deploy_and_verify PASS.
  **The control proved itself same-day:** the split logging surfaced the CI diagnosis
  role's missing `ssm:GetParameter` on the budget-tier param (silently swallowed
  pre-#3059) — grant added to `infra/iam/github-actions-diagnosis-role.permissions.json`,
  applied live, `verify_oidc_iam.py` CLEAN (second member of the #2959 cycle-param class).
- **Edge-429 observation + the WAF decision (DIL-014; #2828 CLOSED)** — PR #3058 (inline).
  Nightly qa-smoke check `ratelimit:edge_429` (`qa_check_edge_429.py`, sibling module —
  qa_smoke sits at 1198/1200): ≤6 too-short POSTs at board_ask ($0 model cost — rate
  charged BEFORE validation, ordering AST-pinned), requiring one real 429 with
  Retry-After + JSON shape. Outcome vocabulary has no vacuous green: RED on no-429 (the
  08-14 signature) · YELLOW could-not-observe · ⏸ on tier-3 pause. **First live run
  observed a real 429.** #1439's manual-only posture re-decided on the record (script
  header + RUNBOOK). **Owner decision executed:** no WAF — dated priced acceptance
  (PROPORTIONALITY row names the compensating stack), **revisit 2026-10-15** or on
  observed abuse / non-self-inflicted spike fire / commercialization. Docs PR #3062.
- **CSP hardening (DIL-015 → FIXED; #3048 CLOSED)** — PR #3060 (worktree agent). Real
  surface was **266 inline blocks / ~920KB / 91 pages** (the issue's V2 numbers were
  stale) → **0**; production `script-src` exactly `'self'` (extraction + non-executable
  `application/json` data islands — no hash entries needed); **jsdelivr DROPPED**
  (axe-core already vendored; `a11y_audit.py:86` moved to CDP evaluate); `/legacy/`
  isolated on a compat policy. **Deployed both halves** (site auto-deploy green
  end-to-end incl. real-browser visual-QA; hand `cdk deploy LifePlatformWeb` for the
  header). **Live: smoke 246/0** with the new source-derived CSP assertion (hardened on
  `/`, compat on `/legacy/`).
- **Secrets re-scope (DIL-016 → partial)** — PR #3056 (inline). SECRETS_MAP gains the
  rotation-ownership register (owner + expiry/next-action per family, ⚠️ loud-gap
  convention for GitHub-UI PAT expiries); us-east-1 "replicas" justified in writing
  (cf-auth/buddy-auth are edge-native and were MISSING from the map — now rows;
  site-api-origin-secret is the one true CFN-region-local twin); #2890 re-scoped to
  per-family PRICED split/merge/keep decisions (never a default consolidation target).
  `notion` deletion batched to owner with a REQUIRED pre-check: live LastAccessedDate
  is **2026-07-25**, not the recorded 03-09 — something still reads it.
- **Two main-red repairs (PRs #3061, #3063)** — both #3059/#3060 merge-union
  registration reds: (1) the #2372 premerge classifier needed both agents' new
  tree-sweeping test files registered; (2) the alarm COUNTER was blind to cross-file
  extraction seams (a single-alarm module helper counts at call sites, which live in a
  different file → counted 0; fixed structurally: a helper with zero in-file callers
  counts at its definition), which forced the cap-bound cohesive split of
  `deploy/alarm_discovery.py` out of sync_doc_metadata (ratchet TIGHTENED 1780→1253);
  (3) the permanence tests followed the extracted `privacy_permanence.js` (all 8
  asserted literals verified present exactly once — test-shape, not a regression).
- **Also:** D0's build dispatch published (the wrap-beats rollback diagnosed as a
  transient data-state AA violation — class filed #3057, INCIDENT row added); recall
  corpus gap backfilled (2026-08-18 installment, $0); #3064 (auto-filed standalone
  visual-QA red) fully diagnosed — FP build-dispatches verdict (verified both schemes
  locally), the `/method/cycles/` matched-window misread baselined citing #2957 (third
  member), and the real IAM gap fixed (above); re-run dispatched, auto-closes on green.

## Deploys (hand, from exact merged/reconciled shas, postflight-verified)

cdk LifePlatformMonitoring 19:5xZ (stale-checkout guard caught the reconcile-bot race —
pulled + redeployed) · site-api-ai deploy_and_verify PASS · qa-smoke 19:00Z (sha
7c2ffecc; dry-run invoke verified the new check live) · site-api ×2 (first raced my own
concurrent pull — the postflight mismatch caught it; clean redeploy verified
`/api/platform_stats` alarms:111) · cdk LifePlatformWeb 19:5xZ (hardened CSP) · site ×2
green gated deploys (D0-beats rerun + CSP) · IAM put-role-policy diagnosis-role
(budget-tier grant, parity CLEAN). Leases: 3 rejected with decodes (superseded,
artifacts hand-deployed), 1 APPROVED (fac0826e0 fleet deploy — Deploy/smoke/visual-QA
green; its unit-test red was #3063's repair), final run bf11b366 **completed/success**.

## Gate lines

**Build beat:** 2026-08-23-d1-control-boundaries
**Docs:** SECRETS_MAP (rotation register + us-east-1 + counts) · PROPORTIONALITY (+3
rows: WAF acceptance, edge-429 observation, budget fail-closed channel) · RUNBOOK
(probe posture) · INCIDENT_LOG (+1 row + header) · DILIGENCE register (DIL-014/015/016/036
flipped with live evidence) · alarm_citations (+1 by #3059) · ARCHITECTURE/INFRASTRUCTURE
(alarm-count literals via --apply)
**Decisions:** none needed — the WAF deferral is recorded as a dated PROPORTIONALITY
acceptance + the #2828 closure (revisit 2026-10-15); below ADR threshold per the
priced-acceptance vocabulary the register defines
**Main:** green (bf11b366)
**Incidents:** 1 row added — the wrap-beats site auto-rollback (transient data-state AA
contrast on /method/board/; class filed #3057; full rerun green)
**Stash/hooks:** clean
**Closures:** #2828, #3048 commented (ADR-099 two-line verdicts, both realized with
live evidence); #3064 auto-closes on the dispatched green run (diagnosis comment on it)
**Backlog:** Now live at 5 actionable (+2 epics); no stale Later issues; hygiene: the 5
violations found at the gate all fixed this session (#3057 labels + epic coverage,
#3064 labels + outcome form) — the auto-filed-vs-hygiene structural tension filed as
#3065
**Alarms:** 0 red >72h; 5 flaps in the window, decoded — `ai-daily-spend-high` ×1 (two
heavy dev sessions same day: D0's oracle sweeps + D1's agents; cleared on its own),
`ingest-auth-unhealthy-24h`/`-dropbox` + `ingest-liveness-unhealthy` ×1 each (the known
#2976 recovery-episode cluster, same decode as the D0 wrap), `site-api-invocation-spike`
×4 (self-inflicted: this session's full-surface QA sweeps during deploy verification —
three visual-QA passes + smoke 246 + probes; no reader symptom). Closed with `--decoded`.
**CI warnings:** none
**Ledger:** 3 rows added — WAF priced acceptance (#2828), nightly edge-429 observation
(#3058), budget-integrity fail-closed channel (#3059)

## Owner batch (ONE ask — everything needing Matthew)

1. **RECONCILE_PUSH_TOKEN PAT** (unblocks D0.6 — main's first required checks): mint a
   fine-grained PAT (Contents read-write, this repo only) as a repo secret, then next
   session runs `apply_branch_protection.py --apply` + adds the #3025 context.
2. **DEPLOY_GATE_JANITOR_TOKEN** secret (#3021 — arms the lease janitor).
3. **respiratory_rate + disturbance_count consent** (#3045 residual — stamp
   TIER_OWNER_PUBLISHED or strip; currently default-public deliberately pending your call).
4. **notion secret deletion** (#2890): pre-check required — live LastAccessedDate
   2026-07-25 says something still calls GetSecretValue on it; identify that reader
   (start: freshness-checker / pipeline-health-check), then delete or adopt.
5. Carried: **#2961** billing-alarm dupes · **#2834** IAM posture decision.
   (WAF is DECIDED — nothing left on it until the 2026-10-15 revisit.)

## Residuals / next picks

- **D0.6 branch protection** — blocked on owner item 1 above (#3042 program). not-work —
  owner-only PAT mint.
- **#2957 got a third class member** (/method/cycles/ matched-window misread, baselined) —
  the producer fix (judge-legible cycle/window framing) drains all three.
- **#3057** (AA clamp on data-supplied coach colors) — filed this session, S-effort,
  prevents the next transient-roster rollback; on epic #2842.
- **#3065** (auto-filed trackers vs the hygiene gate) — Later; gate-design decision.
- **#2890 residual** — the per-family disposition table + CE delta (issue re-scoped with
  boxes).
- **Scheduled observations (not-work — dated):** WAF revisit **2026-10-15** (#2828
  closure + PROPORTIONALITY row carry it) · first edge-429 nightly runs tonight 18:30 UTC
  (a RED would be real) · `prediction-gradable-share-low` may fire ~3d on the legacy
  corpus, clears from 08-24 · first real prediction grades ~2026-08-31 · #2978 30-day
  re-measure ~09-22 · legacy unsubscribe-link sunset 2026-09-22 · Monday retention sweep
  anonymizes the legacy subscriber backlog · #3064 auto-closes on the dispatched
  standalone run going green (in flight at wrap).
- **Next phase:** D2 (the truth manifest — platform_facts artifact + public-claims
  registry, closes #2898, advances #2986/#2842) per
  `~/.claude/plans/lively-juggling-candle.md`; D0+D1 register rows are the re-grade
  evidence pack. **Honest lesson worth carrying:** two merge-past-red incidents in one
  session from sampling PR checks with a fail/pending filter before the slow full-suite
  lane attached — assert the expected check set BY NAME (memory:
  absent-check-invisible-to-fail-filter).
