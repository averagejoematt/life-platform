# HANDOVER — The decision sprint: Matthew answered ~15 questions live, 12 PRs shipped on the answers, OIDC tightened attended, the essay published, the site now deploys itself — 2026-07-08/09 (overnight)

> Instruction (evolving through the session): "is there any work we can be doing from the
> open issues, or do they all require something from me? I approve you to do all merge and
> deploys" → "merge or update the 2 open pull requests" → "organize [the Matthew-gated
> issues] easiest to unblock and how I can answer" → two answer batches + live refinements
> (Habitify-first capture, Strava correction, $85 ceiling) → "keep going on everything not
> requiring me, then wrap; I'll unblock the optional questions next session."

## The shape of the session

The previous wrap said "remaining 18 issues are ALL gated — no unblocked work exists."
This session's discovery: **most gates were one-sentence questions.** Ranking them
easiest-to-answer and asking in plain language turned "all blocked" into 15 answers,
which became 12 merged+deployed PRs (#887–#889, #892, #894–#901), one attended security
execution (#687), and one published essay — in a single overnight sitting. The
org-chart-of-one essay shipped *during* the session that demonstrated its thesis.

## What shipped (all MERGED + DEPLOYED + VERIFIED)

- **Dependabot pair** — #847 (dev tooling; CI's own ruff→0.14.14 / playwright→1.61.0 pins
  bumped across 4 workflows — the CQ-01 guard caught the drift) + #846 (action SHAs;
  fixed two stale `# v3.0.1` comments on v6.2.2 pins).
- **#885 (PR #887)** — email-subscriber Function URL origin guard: the last unguarded
  CloudFront origin. Direct URL → 403, via CF → 200, live-verified.
- **#886 (PR #888)** — `mcp-audit/` lifecycle (IA@30d, expire 90d). Agent also fixed a
  real footgun: `apply_s3_lifecycle.sh` declared 1 rule while the bucket had 8 — a re-run
  would have wiped 7. Now the declarative full config (9 rules), applied live.
- **Driver fix** — prod MCP canary red since the #395 prune (asserted ≥80 tools, registry
  60): floor → 55, deployed, verified ("60 tools listed, all_pass true"; 62 after #898).
- **#739 (PR #889)** — surge ceiling: floats to **$100** (Matthew) at >900 trailing-7d
  uniques (~4× real median — ADR-133, derived from live traffic-digest logs), edge-
  triggered alert via SSM `/life-platform/surge-active`; **base ceiling $75 → $85**
  (Matthew, mid-session — tier-1 was from internal creep at $79.27 projected). Tier bands
  now scale as fractions of the effective ceiling; AWS Budgets bumped via CDK (name kept —
  replacement key). NB: **$85 does NOT clear tier 1 immediately** — bands trip at ~73% by
  design; it self-clears as dev burn decays.
- **#746 (PR #892)** — manual-source reliability (channels = HAE/Notion/MCP, Matthew's
  call): thresholds as `source_registry` facets (HAE per-datatype thresholds migrated in;
  Notion 14d from real cadence), kind evening-nudge section, public "dark Nd" honesty
  display.
- **#422 (PR #898)** — habit causality, redesigned twice on Matthew's live input:
  **Habitify `/notes` ingestion is the primary capture** (note at check-off/skip =
  trigger/reward/why-missed, verbatim), MCP is a **reflection loop**
  (`get_habit_reflection_queue` + `log_habit_reflection`, provenance-tagged, never nags).
  Registry 60 → 62 (audit ratchet row added). Watch the first post-deploy Habitify ingest
  (live `/notes` field names unverified — fail-open).
- **#421 (PR #900)** — vitals depth: VO₂max trend (287 real Garmin records), walking HR
  (775 Strava Walk activities — **Strava IS a live source**; the driver wrongly told the
  agent otherwise and Matthew caught it), fitness age 59 (56–62, PhenoAge privacy
  pattern, leak-grep test). Hourly habits + vascular age **deferred with receipts**
  (Habitify timestamps are poll-observation times; no in-repo vascular formula).
  Fleet-wide motion.js dash-truncation fix (also heals the live weight hero).
- **#750 (PR #897)** — site deploys through CI on merge (separate `site-deploy.yml`, no
  approval gate by design, rollback wired). **Earned its keep within the hour** — see
  gotchas.
- **#741 part (PR #899)** — the essay is **LIVE**:
  `/journal/essays/org-chart-of-one/` — first "In my own words" post, RSS item #1,
  `/method/build/` cross-link, HN block ready in the PR. #741 stays open for Matthew's
  submission (referrer measurement already exists in the traffic digest).
- **PR #901** — reader participation ON: votes/follows/check-ins/suggest-an-experiment/
  submit-a-finding live against the long-hardened endpoints; the "deferred" footnote
  retired. Discovery: **predict-the-week was already active** (weekly config upload
  ritual) — the "dormant" note in memory was stale.
- **#890 (PR #895)** — character-sheet journal fetch fixed (flat `DATE#` key could never
  match templated `DATE#…#journal#…`): `themes` path revived via `merge_journal_view`;
  the Relationships pillar may show its **first real signal** on the next compute.
- **#891 (PR #894)** — `MCP_TOOL_CATALOG.md` regenerated from the registry via a new
  idempotent zero-arg generator (`scripts/generate_mcp_tool_catalog.py`).
- **#687 EXECUTED (attended, direct commits dcd4d17f)** — OIDC trust-tighten: both roles
  main-only (deploy also `environment:production` per ADR-120); **negative test proven**
  (branch dispatch → `Not authorized to perform sts:AssumeRoleWithWebIdentity`); new
  **`github-actions-diagnosis-role`** (main-only trust, Bedrock-vision-QA-only) assumed by
  all 3 vision-QA jobs; `proposed/` promoted to canonical; `verify_oidc_iam` CLEAN (9
  targets); weekly drift sentinel gained `check_oidc_iam`. Full pipeline green
  post-tighten (Deploy job = the environment subject).
- **Also closed without code:** #740 (essay approved as-is + venue shortlist: blog → HN
  same week; LeadDev/Pragmatic Engineer/AI-Eng-Summit as the submission options).
- **Filed:** #893 (MCP auth beyond URL possession — R22 residual, Matthew-approved),
  #902 (journal mood-scale mismatch — social_mood_correlation still dead), #903 (shed
  diagnosis reads from the deploy role), #904 (gear page w/ affiliate links — Matthew's
  idea).
- **Tail fixes:** MANAGED_WHERE_LEDGER stale `seeds/` pointer → `deploy/bucket_policy.json`;
  `get_date_range` description no longer references a pruned tool; QUICKSTART/RUNBOOK now
  present CI as the primary site-deploy path.

## Deploys + verification

Ordered: LifePlatformWeb (subscriber guard) → lifecycle applied → canary → serial merge
train with doc-sync reconciles → **site-api BEFORE site** (learned the hard way, see
gotchas) → `cdk deploy --all` 9/9 → SSM `hevy/restamp_enabled=true` → site via its own CI.
**Verified:** full ci-cd green on tip (post-tighten, every job) · site-deploy green
(smoke + visual-QA 34/34) · direct-URL 403 / via-CF 200 · canary 62 tools · AWS budget
$85 · essay 200 + RSS + build stamp == main tip · participation flows render-QA'd ·
`verify_oidc_iam` CLEAN.

## Gotchas (new this session)

- **Deploy the API before the front-end that calls it.** The new site-deploy CI shipped
  the site while `/api/vitals_depth` wasn't deployed → visual-QA 404 → **auto-rollback
  fired correctly on day one**. site-api first, then site.
- **Superseded queued site-deploy runs** hit the clobber guard as red runs + SNS alerts;
  fixed with an up-front ancestry check that skips cleanly (the newer commit's run
  deploys a superset).
- **A transient API outage killed all 7 in-flight agents simultaneously.** Worktrees and
  branches survived; `SendMessage` resume-from-transcript recovered every one with zero
  lost work. Also: two agents stalled because their render-QA subagents couldn't route
  verdicts back — the driver must relay.
- **IAM normalizes single-element `StringLike` lists to bare strings** — store the
  normalized form in `infra/iam/*.json` or the verifier false-drifts.
- **`gh issue create` has no `--json` flag** — it fails silently inside a piped one-liner;
  three "filed" issues weren't. Check the URL output.
- **The "all gated" framing goes stale fast** — asking the human ranked, simplified
  questions with recommended answers unblocked 15 items in minutes. Cheapest tool in the
  box.
- The old HAE API (`a76xwxt2wa`) still takes ~4–5 successful POSTs/day — a straggler
  device/automation. **Deletion approved but HELD** until it's repointed.

**Build beat:** 2026-07-09-decision-sprint

## Residual — waiting on Matthew (he'll unblock next session)

1. **PRE-13 decisions** (audit delivered in-session): genome is public per-SNP incl.
   APOE genotype; labs public at exact values incl. testosterone/PSA/cancer screening —
   both contradict DATA_GOVERNANCE's "aggregates only". Recommended: genericize genome
   to category counts, split labs (experiment-core exact, clinical-personal banded),
   remove the latent adherence_pct code path, genericize quest names. One PR once
   answered.
2. **HN submission** (title + URL in PR #899) + the one-line call: update the essay's
   snapshot-pinned "8 stacks, ~140 tools" to current (9/60) or leave.
3. **/verify/ profile URLs** — Strava/Hevy/Garmin public profile links or "keep private".
4. **HAE straggler** — repoint the device still on the old URL, then the API gets deleted.
5. GitHub GC ticket — paused by Matthew's explicit choice.

## Watch

First 18:00 UTC Hevy re-stamp run (metrics `LifePlatform/HevyRoutine`, alarm
`hevy-restamp-errors`; Hevy app should show the recommended branch) · first Habitify
`/notes` ingest (field names unverified against live API) · Relationships pillar's first
real `interaction_quality` signal on the next character-sheet compute · Sunday fresh-eyes
run · surge metrics appearing after the next weekly traffic digest · first organic CI
site deploy on a normal site/ merge · `mcp-audit/` records (still zero — fine unless MCP
writes happened) · budget tier self-clearing below ~$62 projected.

Prior session archived at `handovers/HANDOVER_2026-07-08_backlog-paydown-64-to-18.md`.
