# HANDOVER — #590 home constellation v2 (motion epic #575 now 5/5) — 2026-07-05

> Matthew authorized all edits/merges/deploys up front. One flagship story start→finish:
> scope the data question → de-risk with real numbers → build backend + frontend →
> taste-gate with Matthew → ship → live-verify. Ran TWO background agents in parallel
> (#589, #408) — both surfaced a **concurrent-session tangle** that cost a cleanup PR
> (see "The #408 mixup" below). Worked in the **shared primary working dir, not a
> worktree** — that was the mistake that caused the tangle.

## What shipped — #590 (PR #706), the last of motion epic #575

The home hero constellation no longer hand-draws its edges. It now draws **real measured
pillar co-movement**.

**Backend (additive, read-only, no layer bump, no CDK):**
- **`/api/pillar_coupling`** (`site_api_data.handle_pillar_coupling`, registered in `site_api_lambda.ROUTES`) — reads the trailing `_COUPLING_WINDOW=60` character-sheet `DATE#` records, builds each pillar's daily `raw_score` series **masking non-real days** (`_coupling_real_score`: drops `coverage_hold` / `data_coverage<=0` days so a floored/held score can't manufacture spurious correlation across the manual-log gap), then deterministic pairwise Pearson via `stats_core.pearson_r` (+ `pearson_p_value`). Each edge carries its own `n`; pairs below `_COUPLING_MIN_N=6` or with no variance are **omitted, never faked** (ADR-104/105). Cached 3600s. Returns `{edges:[{a,b,r,n,p,significant}], pillars, window_start/end, window_days, min_n, honest_null}`.
- **`/api/character` now surfaces `active_effects`** — the already-persisted (`character_engine.py:1261`) active cross-pillar effects, additive one-block. Empty today (the 6 gameplay effects rarely fire in the cut regime).

**Frontend (`site/assets/js/story.js` + `story.css` + `tokens.css` + `index.html`):**
- Constellation edges = the coupling data. **ember solid = rise & fall together · dashed ink = trade off** (single-accent identity held — negative is NOT a new hue/red, it's dashed tension). Width ∝ |r|, opacity ∝ significance → weak/non-significant pairs honestly faint. A pillar with **no** measured coupling (relationships, flat at 50) has **no edges** and renders `.node.quiet` (recessed, dashed) — the absence stated.
- **Deterministic seeded drift** replaces the uniform `mo-breathe`: `driftVars(name)` seeds `--dx/--dy/--dur/--ddelay` from `fnv1a(name)→mulberry32` (imported from `sigils.js`), CSS keyframe `cn-drift` in `tokens.css` inside the reduced-motion-safe motion block. Same seed → same motion.
- **Hover/focus door affordance**: pillar icon (`domainIcon` from `icons.js`, in an SVG `foreignObject`) + "open →" cue, revealed on interaction.
- **Designed-coupling overlay**: when an `active_effect` fires, `effectSources()` parses the condition string for source pillars, pairs them with `targets`, and lights those directional edges bright ember (`.edge.effect`) over the measured web.
- **Waveform migrated onto the shared `data-cpts` contract (#582)**: the bespoke cursor-tooltip is GONE. Bars now live in a fresh inner **`.wave-cpts[data-cpts]`** node (a newly-added node so `motion.js`'s MutationObserver wires it — setting `data-cpts` on the pre-existing `.wave` wrap would NOT trigger wiring, since only added nodes get scanned). One focus-dot + tooltip + keyboard path, same as every chart. `story.css` moved the flex from `.wave` to `.wave-cpts`.

**Taste-gate:** rendered 3 variants (A relational-web / B living-orbit / C instrument-plate) as real screenshots against the live coupling matrix, in an Artifact. Matthew picked **A**; B/C machinery stripped (the `?c=a|b|c` toggle + `.cn-b`/`.cn-c` CSS removed).

## The data question — RESOLVED (Option 2)
The issue asked for edges "weighted by real pillar-correlation data (#535 outputs)" — **that data did not exist** (no inter-pillar correlation matrix anywhere; `cross_pillar_effects` are *designed* gameplay rules, `what_changed.newly_unlocked` is *metric*-pair not *pillar*-pair). Matthew chose to **build it honestly** (Option 2): compute real trailing-window pillar-pair co-movement, deterministic, n-reported, faint when thin. **De-risk paid off:** the coupling is genuinely rich — the strongest couplings are NEGATIVE trade-offs (sleep↔nutrition −0.84, movement↔nutrition −0.75, sleep↔consistency −0.69 live), and they held even with the quiet week fully excluded → real signal, not a log-gap artifact. Guardrail honored: **no forecasting** coupling from stale data (that would invent numbers).

## Deploy record
- 1 site-api (`deploy/deploy_site_api.sh`, layer already v114 → no re-attach). Live-verified `/api/pillar_coupling` returns 15 edges over 60d; `/api/character` carries `active_effects`.
- 1 static-site (`deploy/sync_site_to_s3.sh`, self-invalidating). `version.json` == HEAD (`2a7545a2`), **smoke 67/67**.
- **Live browser check:** constellation renders 15 edges with real scores (77,11,2,59,17,50,28), People quiet with no edges, "over the last 60 days", no h-overflow desktop+mobile, no console errors, reduced-motion static.
- **No layer bump, no CDK, no MCP.**

## The #408 mixup (my mistake — worktree lesson, reinforced)
I built #590 in the **shared primary working directory** while a **concurrent session** was also using it (that session shipped #589/PR #705 and had a *different* agent mid-#408 in the same dir). When I branched `feat/590` and squash-merged **PR #706**, it **silently dragged that concurrent agent's #408 work (= PR #703's version) onto main** under my #590 commit — test/CI-only files (`v4-gate.yml`, `pr_render_gate.py`, `accuracy_audit.py`, `visual_qa.py`), so **no production impact** (never in the site-api/static deploy artifacts), but unreviewed + mislabeled, alongside a competing #408 PR (#704, my OWN background agent's different impl).
- **Fix:** PR **#707** reverted those 4 files to their exact pre-#590 state (0 diff vs `72cd185b`). #590 now stands clean; **#408 is back to its two PRs for Matthew to choose.**
- **Lesson (already in memory, now with teeth):** a concurrent session sharing the primary working dir means `git checkout -b` can inherit their committed work → it rides onto main on your squash. **Use a worktree for your own work too when another session is live**, not just for the subagents.

## Live PRs at close (Matthew's to resolve)
- **#703** `feat/408-pr-render-accuracy-gate` — a concurrent agent's #408 (the version that briefly rode onto main; complete, compiles).
- **#704** `feat/408-pr-render-gate` — my background agent's #408 (different approach, self-tested pass-on-clean/fail-on-seeded).
- **These two are competing #408 implementations — pick one, close the other.** Both "Fixes #408".
- #705 (#589) — merged+deployed by the concurrent session. #706 (#590), #707 (revert) — mine, merged.

## State at close
- `main` clean == `origin/main` (`99ee566a`). Worktrees pruned to 2 (main + pre-existing `docs/uplevel-handover`).
- **Motion epic #575 COMPLETE (5/5):** #577 #578 #588 #591 (prior session) + #590 (this).
- Site smoke 67/67, `/api/pillar_coupling` live.
- **GitHub Pages still enabled + public** (carried across many sessions, unactioned).

## Next session
1. **Resolve the two #408 PRs (#703 vs #704)** — pick one, close the other, merge the winner. (Matthew's call, in flight.)
2. **#409** batch-price the content AI — **touches `bedrock_client`/`ai_calls` = LAYER modules → layer bump + full consumer redeploy.** Attended.
3. **#395** MCP prune (attended/destructive) · **#687** OIDC trust-tighten (watched live CI).
4. Backlog: `gh issue list --label type:story --milestone Now --state open` (Now is at zero; Next has #583 chart-contract-v2-batch-2, which extends the same `data-cpts`/motion.js path #590 touched — do it aware of that).
5. Housekeeping: GitHub Pages enable/disable decision.
