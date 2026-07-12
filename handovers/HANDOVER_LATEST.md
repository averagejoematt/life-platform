# HANDOVER — Second Fable paydown: 11 PRs merged+deployed, cockpit gains its two missing stations, Now/Next backlog nearly empty — 2026-07-11 (late)

> Instruction: "read memory and handover to form a plan to do as much pay down of open
> issues in git efficiently, i approve all merges and deploys" (approval upfront).

## What ran

Second Fable session of launch eve (hours after the char-math-v2 session, genesis at
midnight). Two tracks: **Track A** — 8 `worktree-implementer` agents (7 wave-1 on
disjoint surfaces, #975 held to wave 2 because it shares /now/ with #974); **Track B** —
the driver did #1025 (git-surgery, attended-class), the engine-doc re-verification +
`check_doc_index --strict` promotion, the serial reconcile-merge queue, all deploys, and
one fix-forward when the deploy pipeline broke.

## What shipped (11 PRs #1060–#1065, #1067–#1070, ALL merged + deployed + verified)

- **#1060** (no issue): re-verified COACH_STANCE/HYPOTHESIS/READINESS/SCORING against
  their 07-11 sources (one real claim drift fixed: COACH_STANCE now documents #966's
  terminal CoachHold), then **promoted the #1057 source-newer-than-verify gate advisory →
  `--strict`** in docs-ci + ci-cd (zero advisories outstanding at flip).
- **#1061** (#935): real `setup/setup_whoop_auth.py` — callback-server OAuth flow
  mirroring fix_withings_oauth.py; the premise had shifted (a paste-URL variant existed
  at deploy/ since 06-13 — moved, rewritten, docs reconciled). Interactive leg untested
  until the next real re-auth, stated plainly.
- **#1062** (#1020): **SW is a deliberate cockpit-PWA island** (home + /now/ + coaching);
  story-page registration was drift — removed via the generators. The issue's "hand-bumped
  VERSION" premise was stale: build-SHA stamping already existed in both deploy paths —
  shipped the myth removal + a hard-fail stamp guard. Decision recorded on the issue.
- **#1063** (#1014): deep-tree sub-nav — evidence-engine tiles are now real `<a>` anchors
  (new-tab/long-press work), mobile rails gain a live `k/n` position readout + an
  "all N topics" index toggle; one engine change covers /data/ + /method/ + /protocols/.
  2-tap reachability measured at 390×844.
- **#1064** (#1019): skeleton states for /story/agents/ + the /data/ readout (tokens-based
  shimmer, no spinners), sessionStorage stale-while-revalidate for the agents feed,
  plus a real fetch-race bug found and fixed in both routers (rapid taps could paint a
  stale response over the newest selection). SW-level SWR deferred to the #1020 island.
- **#1065** (#974): **the cockpit levers station** — /now/ now shows the Protocols
  station (supplement stack + running experiments "day N of D" with meter, linking
  /protocols/), pre-genesis honest ("staged for Day 1"). Training lever needs a routine
  endpoint → filed **#1066**.
- **#1067** (#1015): **section-TOC primitive** (DESIGN_SYSTEM_V5 §10.8) — top-sticky
  collapsible "on this page" bar with real slug ids (shareable deep links) on
  /data/labs/ (~19 screens), /data/character/, /gear/; /now/ deferred with reasoning.
- **#1068** (#968): ADR-108 quality gate on the public board ask/followup surface —
  evaluate-then-regenerate-once, **fail-open under a hard latency budget** (voice
  fidelity never becomes a reader-facing timeout), verdicts → CW metric + EVALRET
  retention (closes the "unmeasured" gap). ask/explain correctly scoped OUT
  (narrator-voiced, no voice spec). ADR-103 posture row + ADR-108 scope note added.
  Deployed: `cdk deploy LifePlatformServe` (new gate-invoke IAM) + deploy_site_api.sh.
- **#1069** (#975): **the inputs station** — per-channel freshness marks on /now/
  (`food · today`, `journal · 6d`), registry-owned channel set, framed as instrument
  health (muted ember past registry tolerance, never red/streaks/shame); /api/presence
  extended with a `channels` projection (raw channel_detail still never leaks).
  Deployed API-before-frontend.
- **#1070** (fix-forward): the #1067+#1069 site deploys FAILED at "Building
  content-hashed assets" — the ADR-098 full-graph hasher treats ANY `/assets/…` path
  string as a dependency edge **including comments**; section_toc.css's header
  ("Companion to /assets/js/section_toc.js") + the JS's real self-injection formed a
  false js→css→js cycle. Live site safely stayed on the last good build (fail happened
  before QA/rollback). Comment reworded, hasher annotated with the trap, recovery
  deploy GREEN.

**Driver-attended:** **#1025 closed** — dangling tip cf3c5586 verified byte-identical
already-landed via PR #334 (not pushed); all 3 stashes dropped with recorded rationales
+ recovery SHAs (`45bae08d`/`a6ed1028`/`c307fe04`, recoverable until gc). Stash list now
empty.

## Verification

Serial reconcile queue with `git fetch` per leg (last session's lesson); doc-sync
`--apply` per test-adding PR; truth gate green at every step and `--check` PASSED on
final main. The #1063/#1064/#1067 triple-overlap in `evidence.js` produced one real
semantic conflict — hand-merged to keep skeleton + race-guard + TOC mount (TOC mounts
after the race guard, never on a superseded paint), render gate run on the combined
tree before merging. Deploys: `cdk deploy LifePlatformServe` (clean diff read first),
site-api ×2, site auto-deploys (final run GREEN through smoke + visual-AI QA; live
`/version.json` == main). Post-deploy: canary all_pass, MCP 401-boot, /api/presence
serving channels, both /now/ stations + section_toc.js live. All 9 issues CLOSED, 0
open PRs, worktrees/branches removed.

## Gotchas / new reflexes

- **The asset hasher reads comments:** any `/assets/js|css/<file>` string in ANY asset
  is a dependency edge (deliberately conservative, ADR-098) — a prose back-reference in
  a CSS header hard-failed the deploy as a false cycle. Name files in comments WITHOUT
  the /assets/ prefix. The hasher now carries a warning comment at ASSET_REF_RE.
- **A failed "Deploy public site" job is fail-safe:** it dies before S3 sync, so live
  stays on the previous build and QA/rollback never run — but the tell is site-deploy
  runs showing `failure` with QA `skipped`, NOT a rollback notification.
- **The render gate + local suites can't catch deploy-path-only failures** (the hasher
  runs only in sync_site_to_s3.sh) — for changes adding new asset files, run
  `python3 deploy/hash_site_assets.py <staged-copy>` locally before merging.
- Two agents each did a banned stash round-trip (both self-reported, both recovered,
  stack verified empty at wrap) — the ban needs to be louder in the implementer brief.

## Next picks / residual

- **Matthew (unchanged from last handover):** Sunday pipeline queue + prereg scripts;
  panelcast wk0 spot-listen; `/bin/bash` Full Disk Access grant; locate the genome
  original; decisions **#1023** (see below) / #1029 / #1017.
- **#1023 framed for decision:** /privacy/ says "no affiliate arrangements"; /gear/
  carries a full affiliate disclosure — but **zero affiliate-tagged links actually exist
  anywhere on the site** (the gear page has no external product links at all). So
  /privacy/ states today's truth and /gear/'s disclosure is aspirational. Pick: (a) cut
  the /gear/ disclosure until affiliate links actually ship, or (b) soften /privacy/ to
  "no affiliate arrangements beyond disclosed product links on /gear/" if links are
  coming. One-file change either way.
- **Open backlog is now: #1029 (owner-gated), #936 (attended DR drill), #741 (outward
  publish), #916 (wait-condition), #1066 (new: training lever + routine endpoint), #748 +
  #1017 (post-genesis conditions), + the Later mobile epics #1000/#1001 remnants.**
- Post-genesis watch (first compute ~17:35 UTC today, it's past midnight UTC):
  character-sheet v1.6.0 first real run (`headline_excluded_pillars`, new components
  scoring), /api/board_ask p95 after the #1068 gate, the levers/inputs stations on real
  Day-1 data.

**Build beat:** cockpit-two-stations (see `site/story/build/beats.json`) — all 11 PRs merged + live.

**Docs:** COACH_STANCE/HYPOTHESIS/READINESS/SCORING re-verified + strict gate flipped
(#1060); DESIGN_SYSTEM_V5 §10.8 (TOC primitive) + PWA-island paragraph; SITE_AUTHORING
SW section; SECRETS_ROTATION/SECRETS_MAP whoop-script names; ADR-103 posture row +
ADR-108 scope note (#1068) — all shipped IN the work PRs; docs-ci strict + all gates
green at wrap.
