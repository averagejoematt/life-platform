# HANDOVER — Overnight max paydown, Day 4: 11 PRs merged (9 stand + 2 honestly reverted), 6 issues closed, the GitHub-Actions incident that ate the night — 2026-08-05 ~20:10 PT → 2026-08-06 ~19:00 PT

> Instruction thread: *"overnight maximum-paydown, full autonomy, owner asleep — Fable drives
> only, worktree-implementers on model:* labels, waves of ≤5, THE LEASE RULE (approve every
> gated run immediately, watchers poll check_deploy_wedge.py), Now queue first (#2149, #2148,
> #2152, #2150, #2151), then stored rank; dependabot with judgment; batch owner actions into
> ONE list."* Owner came live mid-morning ("how are we doing") and evening; no scope changes.

**Main:** green (`36438d39` — full pipeline incl. Deploy, smoke, integration, visual-QA;
`check_main_green.py` exit 0 at wrap). The #2164 merge run (`d3fbf495`, approved at its gate
within seconds) was still in_progress at the wrap commit with zero failed jobs; its SITE half
already deployed green and live (build `d3fbf49`, smoke + visual-QA green in site-deploy run
31138909850) — the ci-cd half's only cargo is the doc-literal bump.
**Docs:** `docs/alarm_citations.json` refreshed (qa-smoke-failures re-cited, PR #2158);
INCIDENT_LOG rows added at wrap; everything else was in-PR. Wiki checkers green at commit.
**Decisions:** none needed — every call reused an existing posture (R8-ST6 hold discipline for
IAM/CDK PRs, the #2099 honest-manifest bar, ADR-140 structural denial inside PR #2167's design,
ADR-099 closure shapes).
**Incidents:** 4 rows added — the GitHub Actions platform incident (P3, the session's story);
the #2157 mypy red on main (P4, fixed forward <1h); the honest-manifest red from the dependabot
layer bumps (P4, reverted); whoop's third credential loss (P3, OPEN — owner re-auth).
**Build beat:** 2026-08-06-the-sentence-google-would-not-say.
**Closures:** #2148 #2149 #2150 #2151 #2152 #1475 commented in the ADR-099 two-line shape
(all realized; #2148's records the two-stage fix + the verified regen) + #2165 (the #2149
alert path's auto-filed episode marker — the mechanism fired live on its FIRST episode, one
alert not six, self-re-armed on clear). #2112 (already closed) got its Aug-6 verification
comment; #1968 got an evidence comment.
**Backlog:** Now refilled to 4 actionable — promoted #1919 + #1968 by their stored 0.90 rank
(Next holds only the gated #1629, so the path was Later→Now via the sweep's sanctioned
promote call); Later sweep clean (later_staleness OK); in-flight issues (#1402 #1675 #1676
#1946 via open PRs) stay put; corpus otherwise clean (58 open, labels OK).
**Alarms:** all reds >72h cited — 3 NEW whoop entries added this wrap
(ingest-liveness-unhealthy, ingest-auth-unhealthy-whoop, ingest-consecutive-failures-whoop,
all → #1934, the third credential loss); gate exit 0 clean.
**CI warnings:** 4 — all the carried owner-gated cdk config-drift warnings
(Operational + Ingestion = the layer rebuild, PR #2100 runbook, owner item 3; Email + Compute
= #2134's AlarmDescription, owner items 2a/4). Deliberate no-action this session — they clear
with the owner's CDK window. The #2159 thresholds went live mid-session: duration/coverage
warnings are QUIET on the latest green run, as #2152's closure predicted.
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## What shipped (merged; deployed unless noted)

**The Now queue, complete:**
- **#2156 (#2149)** — wedge-watch active alerting: a CONFIRMED wedge fires
  `check_deploy_wedge.py --alert` → `repository_dispatch` `urgent_alarm` → the remediation
  agent's curated email; one alert per episode via a tracking-issue marker, re-armed on clear/24h.
- **#2154 + #2166 (#2148, the session's best measured lesson)** — the TTS fix was TWO-stage:
  #2154's 4500-char request chunking deployed and the regen STILL 400'd; measurement showed
  Google segments sentences itself and rejects ~489-char ones regardless of chunk size. #2166
  adds a 200-char per-sentence cap (clause-boundary splits, terminal punctuation stamped so
  Google sees complete short sentences). **Regen then verified live:**
  `{"rendered": 1, "errors": 0}`, `generated/podcast/ep-2026-08-02.mp3` (2.9 MB) exists —
  the Aug-2 prologue orphan is cured.
- **#2157 (#2150)** — genesis-blind remainder: `digest_utils.query_range/_list` gained
  `include_pilot` (default-preserving, 9 callers pinned), monthly_digest + vitals timeline read
  per-source via `source_reads_cross_phase`; the cross-cycle debt ledger is EMPTY.
- **#2155 (#2151)** — /protocols/discoveries renders 67/67 (slice(0,60) removed, count and list
  derive from one array), citation notes tap-reachable via the `.supp-tip` focus idiom. LIVE.
- **#2159 (#2152)** — suite budget 900→1200s (8 green-run derivation, max 985s), coverage floor
  47→53 vs 57.13% measured with CI pins.

**Stored-rank wave 2:** **#2164 (#1475)** — the wayfinding layer: loop ribbon in the canonical
footer on all 89 chrome-bearing pages (here/next/from station states), mega-menu re-poured on
the loop, pure-CSS `:has()` cue; one real light-theme contrast bug found & fixed pre-merge.
**LIVE at build d3fbf49.**

**Fix-forwards on main:** `bfb980c0` (mypy annotation for #2157's accumulator — PR checks
don't run the tier-2 gate, main's lint does) · `36438d39` (honest-manifest revert, below).

**Dependabot, judgment applied:** #2124 (constructs) + #2127 (actions) merged — cdk synth
drift until the next owner cdk deploy (owner list). #2102/#2103 (urllib3/idna in the garmin
layer manifest) merged then **REVERTED in `36438d39`**: the #2099 gate red-mained proving the
manifest is a CLAIM about the deployed layer — the bumps ride the owner's layer rebuild
instead, and dependabot re-proposes after. #2126 left open with the CQ-01 explanation (needs
workflow pins bumped together). #2125 awaiting dependabot recreate after a same-file conflict.

**Held for the owner window (open PRs, deliberately NOT merged — each strands CI or defeats a
gate if merged before its adjacent owner action):** #2153, #2161, #2162, #2163 — see OWNER
ACTIONS. **#2167** (#1402 structural half; replaced #2160 whose branch never minted checks
through four re-trigger attempts) — mergeable once GitHub mints its checks; content verified
locally (42 tests green).

## The incident (the session's story)

GitHub Actions had a platform incident spanning most of the session: (1) **~9h job-queue
stall** (05:50→14:40Z — my 05:49Z gate approval registered but Deploy sat queued; the
deploy-wedge-watch red overnight was an honest symptom, not a stranded gate); (2) **"Failed to
resolve action download info" 500/503 reds** across ~6 runs mid-day; (3) **swallowed events**
into the evening — pushes minting no CI/CD runs (the #781-era silent-death class), PR branches
minting no check suites (#2160 never got checks across empty commits, the rerequest API,
close/reopen, AND a fresh-branch PR). Recovery playbook that worked: `gh run rerun --failed`
for infra reds · `deploy_all=true` dispatch when a push run never minted (used twice; second
one deployed the whole fleet green) · fresh-branch PR swap for check-minting (partial). Two
REAL reds hid inside the infra noise (the mypy annotation, the manifest drift) — each needed
reading past "GitHub is sick" to find; both fixed forward within the hour.

## Gotchas hit (carry these)

- **PR-level checks don't run the mypy tier-2 gate** — an implementer's mypy pass over its own
  files isn't the union; a touched clean-set file (digest_utils) red-mained only at main's lint.
  Run `mypy --config-file mypy.ini` on changed clean-set files during reconcile.
- **The layer manifest is a deploy-truth claim, enforced** — `test_live_tree_has_no_manifest_drift`
  reds main on any `lambdas/requirements/*.txt` bump that isn't a promoted rebuild. Dependabot
  layer-manifest PRs must NOT merge ahead of the rebuild (stronger than "deploys nothing").
- **Google TTS enforces a per-SENTENCE limit far below the request cap** — measured: a 489-char
  em-dash sentence 400s even inside a compliant 4500-char chunk. Split to ~200 chars and stamp
  terminal punctuation.
- **A run-conclusion "failure" can be all-cancelled jobs** — during the incident, `fail` rows
  decoded to `conclusion: cancelled` (supersession), not real failures. Read the job list
  before diagnosing.
- **An approved gate + queued Deploy looks exactly like a wedge** — the wedge checker said
  "progressing" all night because nothing was *stranded*; the stall was runner starvation.
  The lease rule held (every gate approved within seconds); the delay was upstream of us.

## Residual / next picks

- Merge **#2167** when GitHub mints its checks (#1402 stays open for the gated remainder —
  the syndication-lambda half needs the ADR-140 amendment decision, owner list item 8).
- **#2125** — dependabot recreate pending. not-work — automation completes it.
- Aug-7+: first scheduled deploy-wedge-watch run exercises the #2149 alert path live;
  the nightly podcast parity check should go quiet (#2148's verification is already in hand).
  not-work — passive verification on closed issues.
- #1383 / #1114 stay Now for a Matthew-live session. not-work — need his interactive input.
- qa-smoke citation removal still needs its two green scheduled nights (whoop re-auth is the
  blocker for the freshness fail). not-work — dated bookkeeping per the citation's contract.

## OWNER ACTIONS (Matthew — carried + new, one list)

1. **Whoop re-auth (URGENT — third credential loss, latched since Aug-4 00:00Z, no data since
   Aug-3):** `python3 setup/setup_whoop_auth.py --backfill`, then delete the AUTH_FAILURE
   marker row (#2085 — re-auth does NOT clear the latch). Clears the qa-smoke freshness fail
   and two DLQ-alarm citations too.
2. **The CDK/IAM window** — one sitting, merge-adjacent-to-deploy for the four held PRs:
   a. Merge **#2153** → `cdk deploy LifePlatformEmail` (bundles carried #2134 AlarmDescription).
      Restores the #2112 delivered-marker guard before the Aug-12 send.
   b. Merge **#2163** → `cdk deploy LifePlatformIngestion` FIRST (SSM budget-tier grant; else
      budget_guard fails open), then `deploy_lambda.sh social-enrichment …` + `deploy_site_api.sh`.
   c. Merge **#2161** → same Ingestion deploy creates the Bluesky/Mastodon lambdas; then the two
      secrets (`life-platform/bluesky`, `life-platform/mastodon`) when accounts exist.
   d. Merge **#2162** → `aws iam put-role-policy …` (staged JSON in `infra/iam/`), then
      `teardown_hae_orphan_api.py` dry-run → `--apply`. Its daily gate is red-by-design until then.
   After the deploys: `deploy_all=true` dispatch + approve, which clears the R8-ST6 window.
3. **Layer rebuild (carried, PR #2100 runbook)** — now ALSO the vehicle for the reverted
   urllib3/idna bumps (#2102/#2103); dependabot re-proposes them after the rebuild.
4. **`cdk deploy LifePlatformMonitoring`** (carried) + the synth drift from merged #2124/#2127.
5. **Branch protection one-liner (carried):** `python3 scripts/apply_branch_protection.py --apply && … --check`.
6. **Backfills (carried, dry-run-first):** `deploy/backfill_coach_ensemble_phase_stamps.py`
   (qa-smoke still counts 42 unstamped COACH#/ENSEMBLE# rows); optional NARRATIVE#arc
   restoration; optional `deploy/restart_leadin_pages.py --apply`.
7. **Two data/content calls:** the #1984 stack decision (tongkat/NMN/berberine), and Home's
   static "sixteen prior climbs, sixteen collapses" count (reader-truth flags it; only you know
   the true lifetime number — `site/index.html:176`).
8. **The #1402 governance decision:** automated posting of the vitals-derived fingerprint card
   is structurally denied under ADR-140 rule 5 (PR #2167 implements the denial); either it stays
   human-post-only permanently or a board convening amends the rule.
9. **Carried:** #2126 pin-companion decision, CodeQL dismissals ×3 (#2046), PR #2012 revision
   purge, the #1905 clinicians call.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-04_day3-daytime-max-paydown.md`.
