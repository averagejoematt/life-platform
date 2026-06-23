# Handover — 2026-06-23 (Habits evidence page redesign — P0→P2)

Fourth and final page through the design-review → Claude-Code pipeline (Nutrition → Training → Sleep → **Habits**). Spec: `docs/SPEC_HABITS_PAGE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_HABITS_PAGE_v1.md`. Rebuilt `/evidence/habits/` into an honest intelligence layer over Habitify: **which habits are load-bearing, where the effort is, and which one pulls the day up — as an early signal, not a law.** 17 commits, one per P-item.

**Status: built + locally verified + DEPLOYED + live-verified + MERGED.** PR **#197** (`habits-page-redesign` → `main`, squash-merged, branch deleted). Build fingerprint `cfbfaeaa` == HEAD live. **Completes the four-page Evidence series** (Nutrition #193/#194 · Training #195 · Sleep #196 · Habits #197).

## What shipped
- **Phase 0 (P0.1–P0.10):** honesty-rebuilt keystone hero (n-forward, NO bare Pearson, coefficient withheld <2wk) · consistency RATE north-star, single streak demoted (honest at 0) · 90-day ember heatmap, cut-start (Jun 14) ringed — replaces green/amber/red grid · group grades from real adherence RATE not correlation · state taxonomy (every habit on ONE ember+ink ramp incl. **backlog/never-started**, no red) · effort strip (NOT radar) · per-group small-multiples (floor muted) · goal linkage · data-anchored identity · tick spine + serif/mono two-voice; dark + light first-class.
- **Phase 1 (P1.1–P1.5):** **P1.1** auto-derived per-habit taxonomy (time-of-day / do·avoid·maintain / logical group), deterministic name-only heuristic, labeled "auto-derived, not fact" — *inferred groupings NOT shipped to the visible surface* (only context tags). **P1.2** friction tag from real adherence (automatic / takes effort / high friction; ember→muted→dashed; no red). **P1.3** drivers (trigger·friction·reward) — friction real, trigger/reward honest-empty. **P1.4** why-missed — real miss counts, reason honest-empty, no shame. **P1.5** cross-page wiring — groups link out to their evidence page; reverse completion-feed honest-pending.
- **Phase 2 (P2.1):** keystone coefficient + chip gated to ≥2wk overlap, in the **sleep-board confidence-card DNA** (n + overlap-weeks + confidence tier + "likely noise" guard that suppresses the coefficient when |r| is thin even at sufficient n). Verified all three states: withheld (n=7) · ready-strong (n=21/r=.88 → card+chip) · ready-noise (n=21/r=.18 → noise guard, no number).

## Architecture
- **API:** `lambdas/web/site_api_data.py`. `handle_habit_registry` now attaches a `taxonomy` per habit (`_derive_habit_taxonomy` — keyword maps `_TAX_TIME`/`_TAX_AVOID`/`_TAX_MAINTAIN`/`_TAX_GROUP_HINTS`) + a top-level `taxonomy_derived: true`. `handle_habits` gained `per_habit[]` — 90-day adherence aggregation over Habitify `habit_statuses` (scheduled/completed/adherence_pct/state ∈ automatic|holding|needs_attention|backlog). **No DDB schema change.** Blocked vice/habit names still stripped via `_is_blocked_vice`.
- **Front-end:** `site/assets/js/evidence.js::renderHabits` (concatenated parts). New module helpers: `habitsKeystone` (P0.1 + P2.1 calibration), `habitTaxonomyChips` (P1.1), `habitFrictionChip` (P1.2), `habitsDrivers` (P1.3), `habitsWhyMissed` (P1.4), `habitStateTaxonomy`/`habitsEffortMap`/`habitsGroupTrends`/`habitsGoalLinkage`/`habitsIdentity` (P0.x). Reused sleep's `correlationChip` + `cb-card` markup. `charts.js` `heatStrip` gained `max`/`compact`/`cutDate`/`caption`. Styles (`.hb-tax*`, `.hb-fr*`, `.st-*`, `.em-*`, `.gt-*`, `.drv-empty`, `.wm-*`) in `tokens.css`.
- **Deploy (DONE):** `bash deploy/deploy_site_api.sh /api/habit_registry` (verified 200 + live taxonomy on 59 real habits) → `bash deploy/sync_site_to_s3.sh` (build `cfbfaeaa`, CloudFront invalidated I9YI39UWU2261O437V3YYDDSXZ).

## Privacy / honesty rails honored
- **Inferred taxonomy groupings NOT public** — `taxonomy.group` is computed server-side but the visible registry still groups by Habitify's *stored* group; only the time-of-day/type context tags ship, each under an "auto-derived, not fact" label. The STOP-AND-ASK gate (ship inferred groupings public) was **not crossed**.
- **Keystone coefficient self-gates** — withheld <14 days overlap; genesis+8d at ship → renders **withheld** live now. Matthew authorized **auto-surface** at the 2-week window (~2026-06-28); noise-guarded, stays N=1/correlative. (EVR-06 — eyeball it then.)
- No red anywhere; backlog/never-started shown honestly; friction/grades from real RATE never correlation; drivers/misses honest-empty rather than fabricated.

## Follow-ups (EVR-series in `docs/BACKLOG.md`) — all genuine needs-data capture
- **EVR-01** per-habit driver capture (trigger + reward) → fills the drivers table.
- **EVR-02** "why missed" reason capture (one-tap why-on-missed-day) → misses become narrative.
- **EVR-03** cross-page completion-feed (evidence pages expose a daily-completion signal → fold into group score without double-counting).
- **EVR-04** DECISION — promote inferred taxonomy groupings to the public surface (held).
- **EVR-05** upgrade `_derive_habit_taxonomy` beyond name-only heuristic (low priority).
- **EVR-06** watch — keystone coefficient auto-surfaces ~2026-06-28; eyeball it.

## Verification
- Local render harness `/tmp/habits_render.py` (route-mocks `/api/habits` + `/api/habit_registry` with 90-day data) — captured desktop / mobile-390px / **new light capture** (none existed before; light parity confirmed on every section). Keystone three-state harness `/tmp/keystone.py`.
- `black --check` clean; 93 habit/site-api/web tests pass. Build fingerprint == HEAD live (per [[project_build_fingerprint]]).

See [[reference_local_render_qa]], [[project_nutrition_privacy_flags]], [[feedback_prod_deploy_authorization]] (Matthew authorized this session's deploy + merge explicitly).
