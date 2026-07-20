# HANDOVER — Day-2 drain: the Ghost lands, QA depth built out, the radar rescued — 2026-07-19 (evening)

> Instruction thread: "ultracode +2M — keep draining toward zero, quality over count,
> same three-kinds-of-close contract; triage table first; #1410 Ghost fable-solo;
> Monday standing ops folded in; all merges/deploys/pushes authorized ('i authorize all
> deploys merges and pushes etc.'). Decision slots again arrived as UNFILLED brackets —
> all treated as pending." Mid-session Matthew asked after the lost homepage radar
> (the constellation) — found, promoted, live.

## Outcome — 12 issues closed honestly (104 → 92 open), all SHIPPED + live-verified

**Triage first:** full-board table posted (104 open: 6 Now / 47 Next / 33 Later / 18
unmilestoned incl. 16 epics + the permanent #423). Owner-gated cluster named and left
alone; Later tier deliberately held (needs its epics' sequencing).

**#1410 THE GHOST (fable solo, the last big rigor rock):** new pure
`lambdas/bsts_lite.py` — local-level Kalman + OLS on frozen control series, variances
by innovations ML over a fixed q-grid, fully deterministic, zero deps. Spec (controls /
pre_days / MAPE gate) frozen in the design at create (validate_design; no post-hoc spec
shopping); `end_experiment` closes with effect = observed − counterfactual + a 95% CI
from the FULL forecast-error covariance, or a stated refusal (MAPE over gate / thin
pre-period / unevaluable). Card renders served-series-only: ghost dashed, observed
solid, the honestly-WIDENING band. methods_registry entry (fp `bcde99d1a787`),
/method/registry/ regenerated (20 stats, 390px verified — the #1546 lesson applied
pre-push). Guard suite RED pre-fix (8 failed); AC1–AC5 pinned incl. known-effect
recovery + null-coverage. Live: `bsts_lite_counterfactual` serving in /api/methods.
(PR #1551)

**Wave 1 (6 agents, all verified → merged → deployed):** #1429 static-page structural
smoke (manifest-derived `structural` facet; live smoke now 166 checks) PR #1550 ·
#1434 weekly advisory WebKit mobile sweep (visual_qa gains --browser/--mobile/
--max-tier; first fire Tue 21:37 UTC) PR #1549 · #1446 weekly green report in the
Monday ops email (traffic-digest; honest "not collected" for GitHub-scoped numbers;
DEPLOYED tonight — tomorrow 16:00 UTC email carries it) PR #1552 · #1447 advisory
workflows file/auto-close deduped `auto-filed` issues on failure PR #1548 · #1354
COST_TRACKER rewritten from live Cost Explorer (real floor ~$36–43/mo; tier bands as
%-of-ceiling; days-at-tier≥1 from the BudgetTier metric; ADR-133 amendment: tier-1
residence accepted; 45d freshness gate — reds CI ~2026-09-02 unless the close ritual
re-verifies) PR #1553 · #1348 Day-1 docs refreshed against live CDK crons (Garmin
PAUSED was still taught as a cron; >60d Verified-stamp advisory added, currently
naming 8 stale V2-cohort docs) PR #1555.

**Wave 2 (4 agents; 3 merged, 1 in flight at wrap):** #1449+#1450+#1452 — /qa
manifest-driven modes (quick/tier1/full/mobile/ai-review/audit/api), scripts/
qa_audit.py coverage-drift audit (found: 2 pages without visual defs, 39
manifest-declared API deps never smoke-checked — reported-not-failing, follow-up
candidate), and the QA-depth dial (SSM /life-platform/qa-level, fail-open standard;
param created, Operational IAM deployed, diagnosis-role grant applied — exact policy
in the decision menu) PR #1557 · #1320 + #1544-detector — GitHub-side sentinel leg:
GET-only posture asserts (environment protection / ruleset 19162901 / vulnerability
alerts vs deploy/github_posture.json) + the main-push run-liveness detector; guard-red
recovered the EXACT six #1544 incident shas; live drift found: vulnerability alerts
DISABLED + the #1319 gate (both by-known-cause — weekly report will carry 2 standing
lines until owner acts) PR #1558 · #1473 utility-page de-templating (404/subscribe/
confirm/privacy on the v5 system, Litmus 10/10, structural markers kept byte-exact)
PR #1556 · **#1433 axe-core a11y — agent still capturing its day-one baseline at
wrap; PR lands after; next session merges** (vendored axe 4.12.1, gate proven red on
an alt-less fixture; 15/16 unit tests green pending baseline commit).

**The radar rescue (Matthew, mid-session):** the constellation wasn't lost — variant A
moved it 4 beats deep (~4,700px). Promoted to FIRST beat under the loop stage
(~3,570px), anchored `/#pillars`, hover + 84 nodes intact, beat-order pin updated with
rationale (PR #1554). Live-verified after healing a **superseded-skip deploy race**:
the Ghost merge's site-deploy queued 4 runs; cab9b70a's run reported success with a
SKIPPED deploy while live served dee9bf4 — the stale-version.json tell → manual
`sync_site_to_s3.sh`, per the standing reflex (INCIDENT_LOG row added).

**Ops reality checks:** the prompt said Monday but the clock said Sunday 14:10 PT —
Monday ops (W30 predict-week rebuild, ops-email glance) deliberately NOT run (would
produce wrong-week output); felt-probe verify lands tonight after Matthew's taps.
Ghost-deploy chain: fleet via CI (HEAD run e13b1e26 fully green) + fast-path MCP/
site-api/traffic-digest + 2× `cdk deploy LifePlatformOperational`. Two intermediate
CI reds decoded = the R8-ST6 Plan/IAM gate by design, cleared by the attended CDK
deploys. Auto-reconcile bot (#1173) observed working (bot-commits literal fixes to
main post-merge — bot pushes get no push-runs by GitHub design; the #1558 detector
exempts them).

## Gotchas hit (durable → memory)
- An agent worktree at repo-root `.worktrees/` polluted the hevy isolation scan (1
  test red on main until removed) — agent worktrees belong OUTSIDE the repo or under
  `.claude/worktrees/`; `git worktree remove` + re-run the scan.
- The superseded-skip class fired again exactly as documented — the reflex
  (stale version.json ⇒ manual sync) healed it in minutes; 4 queued site-deploys from
  a fast merge queue make it MORE likely, not less.
- Keep-both facet merges in tests/qa_manifest.py (structural #1429 vs coverage #1446)
  and tests/test_wiki_checkers.py (45d gate #1354 vs 60d advisory #1348) — resolve
  file-by-file, parse-check, run the file's own suite before committing.
- `git checkout -B` refuses over hook-staged literal churn — clear main's working
  tree (checkout -- files) before switching; never stash in concurrent sessions.

## Residual / next picks
- **#1433 a11y PR** — lands shortly after this wrap; verify diff + merge + reconcile
  (first next-session pick; the agent's baseline summary rides the PR body).
- **Decision menu (Matthew)** — see the session-close message: #1544 owner legs
  (billing check + INCIDENT_LOG row + the two standing drift lines), GH_POSTURE_TOKEN
  fine-grained PAT (Administration:read + Actions:read + Contents:read) for the
  sentinel's full coverage (#1320 note), Dependabot vulnerability alerts DISABLED
  live (one toggle), #1319 fork, SNS click, #1114 pick (PR #1512), #1350 sign+run,
  #1329 rotate, Withings weigh-in still missing (not-work — device check).
- Tonight attended (not-work — standing ops): felt-probe taps → SOURCE#felt_probe +
  /api/character_calibration n=1; first connection tap re-adopts the fulfillment
  channel (coverage 0.15→0.65).
- Monday (not-work — standing ops): `deploy/build_genesis_predict_week.py --apply`
  for W30; glance the 16:00 UTC ops email (first green report + dial line).
- Pre-existing open PRs, not today's: #1543 deep-context (unreviewed), #1512
  DO-NOT-MERGE portrait sheet (#1114), #1491 gh-quota observability (needs a
  mechanical reconcile vs #1558's drift_sentinel changes — noted in #1558's body),
  #1191 dependabot bump. All cite issues or carry their own gates.
- Next-tier remainder: #1438 write-path E2E, #1441/#1442/#1443 AI-QA lane, #1455
  heartbeats, #1467 reference capture, #1466 Slop-Litmus formalization (fable),
  #1470–#1472/#1474 design, #1406 edges, chat epic #1476 children (#1481–#1484).
- Standing alarms (#1329 checklist): ai-keys staleness continues until Matthew
  rotates; the two by-design GitHub drift lines (gate + alerts) will appear in
  Monday's weekly report — expected, not a new incident.

**Main:** green (e13b1e26) — check_main_green exit 0; HEAD CI run succeeded end-to-end
(fleet deploy included); the two intermediate reds decode to the R8-ST6 Plan/IAM gate
(by design, cleared attended). Full local suite at wrap-prep: 6046+1 passed after the
worktree-pollution cleanup; smoke 166/166 at HEAD; site version.json == main.
**Build beat:** `2026-07-19-day2-ghost-and-qa-depth` (this session).
**Docs:** COST_TRACKER (rewritten, in-PR), ONBOARDING/OPERATOR_GUIDE/QUICKSTART
(in-PR), RUNBOOK (advisory-filer + QA dial sections, in-PR), CONVENTIONS §4b addendum
(in-PR), MANAGED_WHERE_LEDGER (in-PR), DECISIONS (ADR-133 amendment, in-PR); wrap adds
the handover + status block only.
**Decisions:** ADR-133 amendment (tier-1 residence, in #1553) — no NEW ADR needed;
the release-topology ADR (#1338) still awaits the #1319 fork (not-work — owner).
**Incidents:** 1 row added (the superseded-skip stale-deploy window on the
constellation promote — healed by the standing reflex, ~35 min stale-home window,
no rollback fired); the `.worktrees` CI-only pollution logged here, below
incident-class (no rollback, red <1h, self-cleaned).
**Stash/hooks:** clean (stash list empty; hook fresh via postflight 🟢; the one
postflight 🔴 remains `email-subscriber: NOT DEPLOYED` — the #1350 owner-gated purge
lambda, pre-existing, on the menu).

Prior session (same day): `handovers/HANDOVER_2026-07-19_Day1-NextTier-Drain.md`.
