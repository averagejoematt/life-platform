# HANDOVER — the fable batch: all 6 model:fable R21 stories in one session — 2026-07-06

> Directed session: Matthew asked for "all issues in backlog marked model:fable, completed
> efficiently without sacrificing quality." **No deploy/merge authorization was given this
> session — NOTHING is merged or deployed.** Five PRs are open and CI-green; three
> decisions are batched for Matthew (below). Single-threaded on `main`; branches per story.

## What was built (5 open PRs, 0 merged)

| Story | PR | State | What it is |
|---|---|---|---|
| #745 channel decision | **#762** | ready (Refs) | **ADR-124 (Proposed)** in DECISIONS.md — 3 capture channels graded friction/honesty/privacy; recommends A (StateOfMind→HAE, build≈0) + C floor (two-scalar evening ritual); B rejected as primary. **Bad-week publication posture proposed BEFORE data flows** (aggregate always publishes; labels never; dark = honest absence; no retro-deletion). |
| #731 /method/ trust doc | **#763** | ready (**Fixes #731**) | The static trust contract — ten sections of `.prose` HTML rendered before the evidence.js explorer (new `.trust-doc` in tokens.css): number-gate (+ the published 11/112 baseline), blocking quality gate, code-stamped predictions, pre-registration w/ stopping rules, falsification conditions, no-cherry-picking, **the #725 incident disclosed in full**, N=1 limits, never-published list, the $75 ceiling. Playwright-verified JS-off (6.2k chars static), JS-on explorer intact, 390px overflow 0. **Merge with/after #765** — its pre-registration section describes #728's mechanism. |
| #732 protagonist fold | **#764** | **HOLD** (Refs) | `.hero-who` + `.hero-finish` static in the hero: Matthew named, the sixteen-attempts arc, 315→185 stakes, and the provisional finish line ("185 lbs held 90 consecutive days — or this experiment failed", linking /method/survival/). **Two Matthew confirmations before merge:** finish-line option (A maintenance / B date / C two-stage) and the "sixteen" count (R21-sourced, NOT verifiable in repo — fallback phrasing ready). |
| #728 pre-registration | **#765** | ready (Refs) | The mechanism: `stopping_rule` REQUIRED in `experiment_design.validate_design` (**layer module → v117 bump on deploy**); `create_experiment` freezes a public timestamped artifact to `generated/experiments/prereg/{id}.json` (fail-soft + honest warning); CF behavior `/experiments/prereg/*`→S3GeneratedOrigin (no clash with the exact-path `/experiments/` redirect); `mcp_server()` PutObject on that prefix only; `/api/experiments` passes `pre_registration_url`; card renders "frozen artifact ↗" + stopping rule. Tests: 4 new + stopping-rule cases; sweep 106 green; synth clean, **both changes verified in synthesized templates**. 3 candidate designs commented on the issue (A = fixed sleep window 23:00–07:00, `sleep_duration_hours` higher ≥0.5h, 14d baseline/2d washout/21d, full-run stopping rule — recommended; passive, survives quiet logging weeks). |
| #740 org-chart essay | **#766** | ready (Refs) | `docs/content/ESSAY_ORG_CHART_OF_ONE.md` — full draft + talk outline + ranked venue shortlist (own site → HN → AI Engineer CFP → podcasts → LeadDev). Failures ARE the spine (#408 squash-stomp, #725 constitution violation, 47.8% green-tests-lied, lead-list rule). Receipt index appended; 2 `[CONFIRM]` flags (the "~50 stories/3d" self-report). NB: the "case-insensitive macOS" worktree framing was NOT verifiable in-repo; the essay uses the documented squash-inheritance mechanism. |
| #748 fulfillment story | — | **blocked** | Commented gate status: needs the #745 decision, then ≥4 flowing weeks incl. ≥1 rough patch. Earliest start ≈ pick + 4–5 weeks. |

## The batched ask (Matthew — one numbered list)
1. **#732 finish line:** A (185 held 90d — drafted/recommended) / B (target+date) / C (two-stage)? And confirm **"sixteen"** or take the count-free phrasing.
2. **#728 first experiment:** A sleep-window (recommended) / B zone-2→recovery / C protein (not recommended first)? One `create_experiment` call registers it live post-deploy.
3. **#745 channel:** A / A+C (recommended) / other — and confirm the bad-week posture in ADR-124 (it flips Proposed→Accepted).
4. **Merges + deploys** (all held): merge order #765 → #763 (+#764 after decision 1; #762/#766 anytime). Deploy: layer v117 rebuild→publish→attach (CONVENTIONS §1; `rm -rf cdk.out` first), `cdk deploy LifePlatformWeb LifePlatformMcp`, MCP zip (stage `lambdas/reading/`!), `deploy_site_api.sh`, `sync_site_to_s3.sh`.

## State at close
- `main` == origin (untouched); branches `feat/745…/731…/732…/728…/740…` pushed; PRs #762–#766 open, checks green (render+accuracy gate passed on the site PRs; full pipeline runs post-merge).
- Pre-existing `stash@{0} "On main: session-local"` (settings churn + feed/rss regen) — not this session's, left alone. Untracked `docs/reviews/R21_BACKLOG.md` still present, left alone.
- No build dispatch distilled (#380 rule: merged work only — nothing merged).
- Next session: execute whatever subset of the ask Matthew approves; then #726 (void legacy prediction partition — mutates prod data, confirm first) and Session B epic #716 (#730 static proof render / #733 permalinks) remain the R21 spine.
