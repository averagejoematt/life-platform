# HANDOVER — QA & Testing Strategy: full-surface gap analysis → epic #1425 + 30 stories — 2026-07-18 (evening, plan-only)

> Instruction thread: "put a plan together about all the qa and testing approach to the
> whole averagejoematt.com website and the broader infrastructure" — where testing is and
> isn't, per-page QA tiers, browser vs mobile, AI-content screenshots vs deterministic
> bugs, cost/run-rate flags, notifications for scheduled tests outside deploys, less
> reliance on Matthew as the bug-finder. Follow-ups mid-session: (1) we pay for GitHub
> Pro — never burn past the included Actions minutes, and build levers to dial run rate
> down; (2) drift-proofing — tests must move in lockstep as new pages/features/pipelines
> stand up; (3) "go ahead and update all of the issues in git."
>
> **Session constraint (Matthew, mid-turn): a separate session was running a full deploy
> in parallel — this session was deliberately PLAN-ONLY. Zero working-tree writes until
> this wrap commit (handovers/ + CLAUDE.md only). All work product = GitHub issues, the
> plan artifact, and memory.**

## Outcome — plan published, backlog filed: epic #1425 + stories #1426–#1455

**Plan artifact (living doc):** https://claude.ai/code/artifact/887b6131-d64c-48be-b086-ed0c33bac2a5
— scorecard (current→target grades), full inventory, gap analysis, 4-plane strategy,
page-tier matrix, notification hygiene, cost flags, run-rate levers, drift-proofing,
and the filed backlog with issue numbers.

**Filed (issue-filer agent, all 31 verified live via `gh issue view`):** epic **#1425**
(type:epic, Now) + 30 stories, label `review:qa-strategy-2026-07-18`, 11 Now / 13 Next /
6 Later:
- **A coverage** #1426–#1430 — #1426 = the **QA tier manifest** (one page registry all
  sweeps derive from + gating completeness test; kills the four-registry trap; DO FIRST —
  unlocks A2/A3/G3/F1/F2), #1427 deterministic Playwright → all 80 pages, #1428 tiered AI
  vision (tier-1 at deploy, full weekly).
- **B front-end** #1431–#1435 — #1431 first-ever JS unit harness (charts.js/evidence.js =
  ~40-page blast radius; 38 modules/~12.3k lines currently untested), #1432 real `import()`
  graph check, #1433 axe-core, #1434 weekly WebKit mobile, #1435 perf trends.
- **C API truth** #1436–#1439 — #1436 schema snapshots + completeness gate for all ~118
  endpoints (docs said "60+"; #1437 fixes the count via sync_doc_metadata), #1438 write-path
  E2E (votes/follows/checkins/subscribe — currently zero coverage).
- **D AI-content** #1440–#1443 — #1440 budget-pause visibility (reader-truth silently
  pauses at tier ≥1 today), #1441 generation-time archive (AI surfaces are point-in-time —
  nothing records what a reader saw), #1442 weekly AI review-pack email, #1443 AI-quality
  canary 1×→2–3×/week.
- **E notifications** #1444–#1448 — #1444 **urgent SNS topic has NO email subscription in
  IaC** + dispatcher URGENT_PATTERNS mostly match digest-routed alarms it never receives
  (ai-daily-spend-high, DLQ, auth-dead, ddb-throttled have no fast path today); #1445
  qa-smoke heartbeat (silent on green AND warnings-only); #1446 weekly green report; #1447
  advisory-workflow failures file issues; #1448 wire restart_verify_rendered leak sweep
  into daily visual-qa.
- **F process** #1449–#1451 — /qa manifest-driven modes, /qa audit (this review as a
  10-min ritual), quarterly re-grade.
- **G levers/drift** #1452–#1455 — #1452 SSM `/life-platform/qa-level` dial
  (full|standard|lean|off, deploy gates exempt from off); #1453 CI-minutes metering vs
  **GitHub Pro 3,000 included min/mo** with 70% warn + concurrency-cancel/path-filters
  (extends #1334 — linking comment left); #1454 **PR-time surface drift gate** (new
  page/route/cron/JS module without matching QA registration reds CI); #1455 heartbeat
  completeness assertion (CDK-level).
- Filer also left a boundary comment on #1333 (paging ADR, adjacent to #1444).

## Verified (how the findings were established)

Three parallel Explore agents over `tests/` (~370 files/~3,000 tests mapped to
gating/advisory/schedule/notification), the site surface (80 live pages + 84 legacy;
visual_qa covers ~35 → **44 uncovered incl. live-data/AI/write pages**; ~118 endpoints
enumerated from the router; 38 JS modules/~12.3k lines), and the monitoring stacks
(~52 alarms → topic routing → the urgent-email + dispatcher-mismatch holes; every
scheduled check's failure path traced). Cost math: current AI-vision run ≈ $0.20–0.40;
naïve 80-page daily ≈ $30–70/mo → REJECTED for tiered ~$5–8/mo. No code was changed,
so no test/deploy verification applies.

## Gotchas hit

- None operational (plan-only). Key pre-existing traps the plan encodes: the four-registry
  new-page trap (`reference_new_site_page_registries`), node --check lazy-parse (#1156),
  qa-smoke/urgent-topic silence classes above.

## Residual / next picks

- **Now lane seeding:** #1426 (manifest) FIRST → one small-fixes session #1444/#1445/#1440/#1453
  → big lifts #1431 (JS units) and #1436 (schema snapshots) as dedicated sessions.
- #1444 first step is a live check: does a console-only email subscription exist on
  `life-platform-alerts`? Codify either way.
- Everything else from the prior (BacklogPaydown) handover's attended queue still stands:
  cycle-8 prereg publish, Sunday `restart_verify.py`, #1319 approval-gate posture,
  #1114 portrait pick.

**Build beat:** none — planning-only session; output was GitHub issues #1425–#1455 + the plan artifact, nothing merged/deployed.
**Docs:** none needed — no shipped code; checkers run read-only and green (`sync_doc_metadata --check` PASS, links/tombstones/ADR-index OK). The endpoint-count drift ("60+" vs ~118) is deliberately filed as #1437 rather than hot-fixed mid-parallel-deploy. Advisory from check_doc_index for the NEXT session: `docs/engines/HYPOTHESIS.md` (verified 2026-07-13) predates today's `hypothesis_engine_lambda.py` commit — re-verify + bump its header.
**Main:** green (902ba9b8) — `check_main_green.py` exit 0 at wrap.
