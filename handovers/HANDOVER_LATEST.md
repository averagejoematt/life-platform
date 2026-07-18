# HANDOVER — High-value backlog paydown: Truth Spine, Attempts Ledger, throttles, un-red main + 3 fan-out smalls — 2026-07-18 (late night)

> Instruction thread: "pay down the HIGH-VALUE backlog" from the two fresh review
> queues (/sdlc-review #1319–#1358, /frontier-plan #1363–#1415) — rank by Score,
> exclude gate:owner, big architectural items SOLO, disjoint smalls via
> worktree-implementer fan-out; "properly" = real fix + non-vacuous guard proven RED
> pre-fix, merged AND deployed + verified live. Matthew pre-authorized all merges and
> deploys ("i authorize all merges and deploys this session"); IAM stays user-NAMED.

## Outcome — 7 issues closed properly (5 solo + 3 fan-out, one absorbed), all live

**Fan-out (worktree-implementer, each verified against its issue before merge):**
- **#1335** (PR #1418): `ai_spend_attribution.py` GetMetricData Period ceil'd to 60s
  multiples via one pure `_metric_period()`; 18 unit cases; pre-fix red `15 failed`.
  Live smoke: `--days 7` completes ($6.68 self-reported vs $7.25 authoritative).
- **#1321** (PR #1419): `generate_adr_index.py` parses `## `+`### ADR-` records
  (amendments fold into parents); index 121 → **133 records** (ADR-046..057 restored);
  permissive-scan oracle makes silent omission a hard error.
- **#1370** (PR #1420): `calibration_core.score_pairs` — skill ≤ 0 can never render
  "well-calibrated"/authoritative; new dignified `not_yet_skillful` (score 45), `skilled`
  True/False/None in payload; **live-verified**: the −0.0047 platform block now serves
  `not_yet_skillful/45/skilled=False`.

**Solo:**
- **#1369 Truth Spine** (PR #1421): NEW `lambdas/web/vitals_resolver.py` — the ONE
  latest-reading resolution (finalized recovery, separately-finalizing sleep,
  garmin-then-apple steps, honest-null, provenance via as_of). Consumed by
  `/api/pulse`, `/api/vitals`(→snapshot), `site_stats_refresh`, daily-brief
  public_stats/pulse writers. Counts (mcp_tools/data_sources/lambdas + "19 data
  sources" hero copy) derive from PLATFORM_STATS; AST guard bans writer literals.
  `/api/wrong` ships `caught_detailed/undetailed`, page header derives from parts
  (render-QA'd 3 scenarios). **Live-verified**: vitals==pulse (96/green/8.4h, as-of
  07-16; was 0.0/red/null vs 96), wrong `4 = 2 + 2`. public_stats **platform counts
  self-heal at tomorrow's daily-brief run** (writer fixed; refresh preserves that block).
- **#1328** (PR #1422): site-api reserved concurrency 5 → 20 (cap BOUND daily; 627
  reader 429s/30d), Throttles alarm per serve-stack lambda (zero existed anywhere; both
  live in CloudWatch), `account_concurrency_limit` maintained fact + check_doc_facts
  token, RESERVED_CONCURRENCY.md rewritten (old page claimed "limit 10, awaiting
  approval" vs live 100/88 — gate reds on it). CDK deployed (LifePlatformServe, 38s),
  cap + alarms verified live. **Bonus**: fixed the #1419-introduced `_count_adrs`
  h2-only vs index-generator h2+h3 ping-pong (adrs fact 121 → 133) before it could red
  a wrap.
- **#1327 un-red main** (PR #1423): I9 → `test_i9_dlq_no_deploy_caused_messages`
  (SentTimestamp-dated: >1h-old messages WARN, deploy-window messages FAIL — the one
  Withings transient had redded 38 consecutive runs); shared-fact test discovery-first
  (the `assert 69 == 67` hand-literal class is gone, ±5 fallback hygiene);
  `scripts/check_main_green.py` + wrap.md gate (e2). 8/8 tests red on pre-fix tree.
  **b1a596fb's own CI/CD run: SUCCESS.**
- **#1375 Serial Restarter's Ledger** (PR #1424): `/story/attempts/` — expedition log +
  same-day-axis survival overlay derived live from `/api/survival`+`/api/cycle_compare`;
  cockpit masthead "Attempt #8 — previous best: 13 days" (self-hiding, links to the
  ledger); footer chrome sweep (77 pages); registered in visual-qa (gating) + smoke +
  the 41-URL restart gate + PAGE_BINDINGS. Three render-QA rounds fixed real findings:
  svgtype floor actually wired (was a false fs-ok comment — 5.1px → 11.0px effective at
  390px), min-width scroll container, PADL 140 label clipping. **Live**: page 200,
  version.json == a518ad3, gating visual-QA passed. Absorbs deferred #1244 framing.

**Merge discipline:** /reconcile-branch ritual per PR (merge main → `sync_doc_metadata
--apply` over the merged tree → linearize → squash) — test_count literal moved
3644→3948 across the queue with zero conflicts left behind.

## Gotchas hit (durable ones in memory)
- **CI deploy race**: my manual `deploy_site_api.sh` was overwritten ~2min later by the
  in-flight ci-cd run of an OLDER merge commit (cancelled runs ≠ no deploys; the oldest
  in_progress run deploys ITS tree). Redeployed after the pipeline settled; verify via
  the function's CodeSha256/zip listing, not the deploy script's ✅.
- **CloudFront caches /api/* per TTL** — post-deploy verification needs a viewer-path
  invalidation first (`/api/vitals|pulse|wrong|calibration|snapshot`), else you re-read
  the pre-fix lambda for up to an hour.
- **New site page checklist is FOUR registries**: visual_qa PAGES + smoke_test_site +
  restart_verify_rendered (auto-bumps the 41-URL fact) + `tests/site_review_bindings.py`
  PAGE_BINDINGS — the last one redded a518ad3b's Unit Tests; fixed 902ba9b8.
- **fs-ok comments are checked for truth**: claiming "floored by svgtype.js" without a
  `SVG_TYPE_FLOORS` entry + `var(--fs-*)` consumption is a false sanction — render-QA
  measured 5.1px effective and the guard's retired-sanction rule catches the phrasing.

## Residual / next picks
- **Sunday+ (post-genesis)**: `python3 deploy/restart_verify.py`; re-run
  `seed_genesis_preregistration.py --apply` + `publish_genesis_preregistration.py
  --apply` AFTER any pipeline re-run (claims stay frozen).
- **Prereg publish awaiting Matthew's OK** — cycle-8 seeded (10 coach claims + 2
  hypotheses, frozen `deploy/generated/genesis_preregistration.json`, cycle-6 artifact
  archived beside it); full dry-run in `handovers/prereg_dryrun_cycle8.txt`.
- **Decision menu items** (Matthew): #1319 approval-gate posture (restore
  required_reviewers vs ratify gate-less — deploys verifiably run unattended today),
  #1114 portrait pick, #1243/#748/#1187/#1029, gate:owner queue (#1350, #1329).
- Now-milestone remainder: #1403/#1405/#1409 (fable/opus data stories), #1395 growth
  surface, #1376 career-vs-season, #1371 cold-start gates, #1338 release-topology ADR,
  #1322 deploy README; epics #1194/#1195.
- public_stats platform counts self-heal at the next daily-brief run (verify Sunday).

**Main:** green (902ba9b8) — its full CI/CD run concluded SUCCESS at wrap;
b1a596fb (the #1327 merge) also ran green end-to-end. a518ad3b's Unit Tests red was
the missing PAGE_BINDINGS entry, fixed by 902ba9b8 (decode per the new e2 gate).
**Build beat:** `2026-07-18-truth-spine-attempts` (distilled per checklist — merged +
deployed + verified only).
**Docs:** RESERVED_CONCURRENCY.md rewritten (#1328), TESTING.md I9 row (#1327),
wrap.md e2 gate, ADR index regenerated 133 records (#1321), sync'd literals via
doc-sync per merge; no other pages invalidated (guards + resolver are self-documenting
in-tree).

Prior session (same day): `handovers/HANDOVER_2026-07-18_LaterDrainCycle8Reset.md`.
