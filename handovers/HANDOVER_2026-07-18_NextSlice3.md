# HANDOVER — Next-milestone slice 3: 14 fullreview issues shipped + deployed + verified live — 2026-07-18

> Instruction thread: "close as many OPEN GitHub issues as possible — PROPERLY" (a real fix
> + a non-vacuous regression guard proven to fail on the pre-fix code, merged AND deployed +
> verified live where it has a runtime surface). Matthew granted full authority mid-session:
> **"i approve you to do all deploys, merges etc."** (IAM grants still user-NAMED).

## Outcome — 14 issues CLOSED, main GREEN (`d2442db5`), everything deployed + verified
All from the /fullreview 2026-07-16 backlog (`review:2026-07-16`). Four `worktree-implementer`
fan-out batches, each issue disjoint-file, each with a non-vacuity-proven guard, every diff
verified against its issue before merge:

- **#1221** rate-limit keyed on the client-controllable LEFTMOST `X-Forwarded-For` → now the
  EDGE-appended LAST hop. Verified topology: BOTH site-api + email-subscriber are **Lambda
  Function URLs behind CloudFront** (not API Gateway) → CloudFront appends viewer IP last, no
  second append → last-hop = true viewer. Shared `lambdas/client_ip.py`, all 13 call sites.
- **#1207** consolidated ~17 divergent `_to_decimal` forks → `numeric.floats_to_decimal` with
  NaN/Inf→None (boto3 rejects `Decimal('NaN')`) + `precision=` (default None = byte-compat).
  Structural guard: no forked walker outside numeric.py (21 offenders → 0).
- **#1237** wired 10 OG cards to their topic pages (og-sleep→/data/sleep, etc.). Live.
- **#1216/#1217** supplement registry: 4 fake `?term=` PubMed SEARCH URLs → real PMIDs (each
  verified live via WebFetch: 30875872 apigenin, 40626304 lion's-mane, 22364157 Rosanoff) or
  honest "open question"; "80% deficient" → real ~48% NHANES. Config-sync deploy + CDN inval.
- **#1218** retired writer-less `/method/benchmarks` (honest copy + chronicle hook removed) +
  AST orphan-partition guard. **#1234** pk-family census preflight (fail-loud taxonomy totality
  at reset). **#1232** monthly_cost ~$60→~$80 + offline band guard.
- **#1210** SVG type-floor: shared `svgtype.js` floors registered labels to ≥11px effective +
  retired the `fs-ok: SVG viewBox units` sanction + a getScreenCTM audit in the gating visual-QA.
- **#1219** prologue Part I/II reconciled with an editor's note (annotate-not-rewrite, ADR-104);
  content lives in DDB via `restart_leadin_repair.py` → regen applied, live. **#1205**
  ARCHITECTURE.md 6 false claims fixed + cron-diff guard in check_doc_facts.py.
- **#1233** write-time phase+cycle stamp on COACH#/ENSEMBLE#/NARRATIVE# writers via cached
  fail-soft `phase_taxonomy.experiment_stamp` (phase="experiment" matches with_phase_filter, so
  rows stay visible; NARRATIVE#arc name-collision → cycle-only). **#1215** constellation edge
  evidence → shared `data-cpts` readout (touch+keyboard). **#1223** palette-wide WCAG-AA pytest.

## Deploys done (all verified)
`deploy_fleet.sh` 95/0 (#1207) · site-api ×2 (#1221/#1232, monthly_cost live "~$80") ·
email-subscriber (us-east-1) + wednesday-chronicle (#1221/#1218) · 4 coach fns (#1233) ·
config S3 sync + CDN invalidations (#1216/#1217, zero `?term=` live) · 3 site auto-deploys —
each passed the gating visual-QA incl. the NEW #1210 floor audit + #1215 cpts audit · #1219
DDB content regen (editor's note live, Part I body preserved). Site `version.json`==HEAD.

## TWO red-main incidents — both fixed WITH guards (don't repeat)
1. **PR #1297** (red main): #1237's `test_og_card_coverage.py` imported `PIL` (Pillow — a
   Lambda LAYER dep absent in CI's unit lane) → `ModuleNotFoundError` at COLLECTION → exit-2
   redded the WHOLE Unit-Tests + Deploy-critical lanes. Fix = AST-parse `PAGES` instead of
   importing. **New reflex + memory [[reference_test_layer_dep_import_collection_red]]: run
   `pytest --collect-only` before trusting an agent's "tests pass"; a layer-dep import
   (PIL/playwright/garth) reds the whole suite.** #1215's playwright test did it right
   (`pytest.importorskip`) — that's the safe pattern.
2. **PR #1298**: pre-existing (#943) `restart_leadin_repair.backup_record` crash —
   `local.relative_to(REPO_ROOT)` on its `/tmp` backup dir raises ValueError every run,
   aborting the repair mid-way. Blocked #1219's content regen. Fixed (display abs path) + guard.

## Merge mechanics that worked
Disjoint-file batches only. `test_count` literal drift after each merge is auto-fixed by the
reconcile bot (`chore(reconcile) [skip-reconcile]`, ~1 min) — `git reset --hard origin/main`
between batches. #1294 was the ONE conflict (it edits the test_count line directly) → resolved
in-worktree by taking origin's side + `sync_doc_metadata.py --apply`, keeping monthly_cost.
CI/CD serializes on a concurrency group; a run parked at the manual Deploy gate blocks the next
— cancel the parked run (its Lint/Test/Plan already recorded) to let HEAD validate.

## Left for Matthew (NOT done — needs you)
- **Next milestone now = 5 stories, ALL non-code:** #1228 (unmanaged us-west-2 email-subscriber
  twin — infra cleanup), #1227 (cfn_drift role needs `cloudformation:DetectStackResourceDrift`
  — a **user-NAMED IAM grant** in role_policies + CDK deploy), #1187 (podcast music bed),
  #1114 (coach portrait art v2), #916 (MCP passcode UX). The code-actionable Next backlog is CLEARED.
- Carried from prior session (unchanged): #1266 DDB cycle re-stamp, #1265 Elena held-draft regen.
- Budget tier 1. Later/Backlog milestones untouched.

**Build beat:** `2026-07-18-fourteen-in-one-sitting` — a single fan-out session cleared the
entire code-actionable Next backlog (14 fullreview issues, security→a11y→data-honesty), each
with a regression guard proven to fail on the old code, all deployed and verified live — and
caught + fixed two of its own red-main traps (a layer-dep test import, a pre-existing reset-tool
crash) along the way. Distill per `docs/content/BUILD_DISPATCH_CHECKLIST.md` at next content pass.

Prior session: `handovers/HANDOVER_2026-07-18_Cycle7Reset.md`.
