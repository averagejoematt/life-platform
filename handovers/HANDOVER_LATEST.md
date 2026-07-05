# HANDOVER — motion epic #575: 4 of 5 shipped (coherence floor → motion v2 → cockpit presence) — 2026-07-05

> Solo session (no other Claude running). Opened by cleaning the repo, then shipped the
> motion-epic dependency chain in order, one PR each, taste-gating with Matthew at every
> gate. **#590 (home cinematic) deferred to a fresh session** by Matthew's call — it's the
> L-effort, highest-stakes page and opens a data question. Matthew authorized all
> edits/merges/deploys up front.

## Repo cleanup (session open)
- Working tree was already clean (opus batch #2 wrapped cleanly). `main` was 1 behind origin → fast-forwarded (`#699`, a concurrent-session deploy.md fix).
- **Local branches 281 → 2.** Pruned 126 `[gone]`-upstream branches, then the rest after confirming **0 open PRs** and that every branch traced to shipped work. Verified `recovered/378-hae-auth-header-only` was fully redundant (main already has the PRIV-02 header-only fix) before deleting. Left: `main` + the pre-existing `docs/uplevel-handover` worktree branch.

## What shipped (4 issues, dependency-ordered, one PR each)

**#577 — one theme.js (PR #700, front-end)**
Six near-identical `wireTheme()` blocks → `site/assets/js/theme.js` (`initTheme()`). Reads/writes `localStorage["ajm-theme"]`, applies `dataset.theme`, wires any `.theme-toggle`, and now keeps `<meta name="theme-color">` honest to an *explicit* theme (shells ship media-split metas that only track OS scheme). View Transition on toggle when supported + reduced-motion off. `mind.js` is orphaned (reading page is served by `evidence.js`) but consolidated too. Pre-paint boot scripts stay.

**#578 — the v5 kit on every door (PR #700, front-end)**
Every door opens with `.page-hero` (ember kicker · serif title · one-line promise) + `.loop-ribbon`: **`Now · Data → Coaching → Protocols → Story ↺`**, current door ember `.lr-here`; Home/Method mark nothing.
- **`scripts/v4_kit.py`** = the ONE ribbon source (`loop_ribbon(current_door)`), imported by the evidence/coaching/dispatches/methods builders so the spine can't drift (the same duplication #577 killed for the theme).
- Heads converted `.ev-head`/`.dx-head` → `.page-hero` (pure, not dual-classed — evidence/story CSS would otherwise override the kit). JS anchors that read the old heads followed the rename (`evidence.js` wireFirstRun, `dispatches.js` storySince). Genesis stamp + portrait disclaimer preserved.
- **Cockpit**: slim `.page-hero` (kicker + ribbon, no promise — the big score is the headline). **Home**: kept its cinematic `.hero-loop`, aligned to include a leading "the now" node (full rework is #590). **Method registry**: gained the ribbon.
- Taste-gate: `/data/` rendered + approved before the sweep. Ribbon-node model (`Now ·` leading, set apart) was Matthew's pick.
- **Builders are `.format()`, not f-strings** → the ribbon is inlined once at module load via `SHELL = SHELL.replace("{ribbon}", loop_ribbon(...))` before the per-page format calls (evidence uses a real f-string, so it interpolates `{loop_ribbon(...)}` directly).

**#588 — motion v2: cross-document View Transitions (PR #701, front-end/CSS)**
`@view-transition { navigation: auto }` in `tokens.css`. `.loop-ribbon` + `.brand` carry a per-document `view-transition-name` → the ribbon **morphs in place** (ember marker slides door→door), brand pinned, content cross-fades. Pure progressive enhancement (unsupported → plain nav, zero fallback cost). Reduced-motion drops the cross-fade/morph to an instant swap. `.lr-here` settles on arrival; cockpit `.spine::after` draws with scroll (`animation-timeline: scroll(root block)`, starts at a visible base). **`.page-hero` pulled OUT of the `html.mo` opacity-reveal** so the morph target isn't captured mid-fade (same "no dead air" reasoning as `.rd-card`). SW: no navigation preload + a clean `fetch()` on `req.mode==='navigate'` → composes unchanged, no SW edit. Taste-gate: `/data/→/coaching/` filmstrip (Chromium 145) + reduced-motion instant-swap both verified.

**#591 — cockpit presence pass (PR #702, site-api + front-end)**
The board read is now *present*, three honest signals, all self-hiding:
1. **Signed + timestamped verdict** — author sigil/portrait mark + "written 6:02 AM this morning" (from `weekly_priority.generated_at`, UTC→PT, "this morning" gated on today PT). No fake liveness.
2. **"The argument underneath"** — the #540 inter-coach dispute (`/api/coach_team.dispute.turns[]`) rendered as a THREAD (position→reply→rejoinder, sigil-marked, stepped in). Data-driven over `turns[]` → **handles 1..n turns** (verified with 3-turn and 1-turn fixtures).
3. **"Where the team stands"** — per-coach stance chips with an **honest** held-duration: **"held since {date} · ~N weeks"**, NEVER a day count (STANCE# is weekly — ADR-104/105). Matthew chose this over the issue's literal "held 6 days". No history → stage alone.
- One new `/api/coach_team` fetch (fire-and-forget, present-tense; added to `DAILY_SEL` so it hides in week/month/journey).
- **Server side (the only backend change this session):** `site_api_coach.handle_coach_team` gained a per-coach `held_since` = earliest consecutive same-stage `STANCE#` `as_of` (`_stance_held_since`). Additive; existing consumers unaffected.
- Live-verified with real data: real 3-turn dispute (Webb↔Reyes on caloric adequacy), 8 stance chips ("held since Jun 29"), "written 7:55 AM this morning".

## Deploy record
- 3 static-site deploys (`sync_site_to_s3.sh`, content-hashed + self-invalidating): after #578, after #588, after #591. Each: `version.json` build == HEAD, **smoke 67/67**.
- 1 site-api deploy (`deploy_site_api.sh`) for #591's `held_since` — full `web/` package; layer already v114 so **no re-attach**; `/api/coach_team` confirmed returning `held_since` live.
- **No layer bump, no CDK, no MCP.** OG/tests untouched.

## Gotchas (minor, for next time)
- **`sync_site_to_s3.sh` regenerates `site/feed.xml` + `site/rss.xml`** (date-only) → they show dirty after every deploy. `git checkout site/feed.xml site/rss.xml` before the next commit, or they leak into the PR.
- The pre-commit doc-sync hook ran clean all session ("already in sync") — no counter-file churn this time (single-PR-at-a-time, not a stacked merge).
- Local render QA harness: serve `site/` over `http.server` (absolute `/assets` paths need a real origin), block service workers, route-mock `**/api/**`. To slow a View Transition for a filmstrip, route-inject `::view-transition-*{animation-duration:1.8s}` onto the `tokens.css` response (non-destructive). Bump the port if a crashed run leaves it bound.

## State at close
- `main` clean == `origin/main` (`12df246b`), 2 branches (main + `docs/uplevel-handover`), all 4 issues + PRs closed, smoke 67/67 on the live site.
- **GitHub Pages still enabled + public** (carried from prior sessions, unactioned).

## Next session — #590 (home cinematic), do it fresh
The last motion-epic issue and the highest-stakes page ("every screenshot comes from here"). Scope:
- **Constellation v2**: slow *deterministic* drift seeded like `sigils.js` (same seed → same motion — currently only a simple `mo-breathe` translateY); pillar-node hover → door affordance (icon + label + "enter" cue); **edges weighted by real pillar-correlation data** with thin-data edges honestly faint. Current impl: `site/assets/js/story.js` `drawConstellation()` (lines ~36–106) — hardcoded 7-node `NODES`/`EDGES`, nodes sized by score, `.live` if either endpoint is up.
- **Waveform** scrub migrated onto the shared `data-cpts` contract (kills the bespoke tooltip in `story.js` ~line 237).
- Hero counter keeps its ember glow; no new glow. Sequence-check vs #386 (transformation-hook lede).
- **⭐ Taste-gate: 2–3 constellation options rendered as screenshots for Matthew; winner ships.**
- **OPEN DATA QUESTION (scope first):** the pillar-pair correlation edge-weight data is **not** in `/api/character` today (`#535` was uncertainty/CIs, not pillar correlations). Grep found `pillar_correlation` refs in `lambdas/character_engine.py` + `site_api_vitals.py` — check whether a real inter-pillar correlation matrix is computed and can be exposed (site-api field) or derived client-side, BEFORE committing to weighted edges. If no honest correlation data exists, weight edges by something real (co-movement of xp_delta?) or keep them uniform + honest.

Then batch-#3 leftovers (from opus batch #2's handover): **#408** shift render/accuracy QA left onto site PRs (CI) · **#409** batch-price the content AI (**touches `bedrock_client`/`ai_calls` = LAYER modules → layer bump + full consumer redeploy**). Attended/destructive: **#395** MCP prune. Watched CI: **#687** OIDC trust-tighten.
