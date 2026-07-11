# CLAUDE CODE PROMPT — Habits Page Redesign (v1, rev. with intelligence-layer additions)
**Target:** averagejoematt.com → `/evidence/habits/`
**Companion spec:** `docs/specs/SPEC_HABITS_PAGE_REDESIGN_2026-06-21.md` (read first — rationale, panel disagreements, field bindings, the keystone-honesty treatment, and the taxonomy/tier/state/effort layer)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/habits`, `/api/habit_registry`. Locate the front-end `/evidence/habits/` components; reuse the inline-SVG chart kit (no new deps). Where a component matches a Vices/abstinence-streak page or the sleep correlation board, REUSE it — do not duplicate.

---

## HARD RULES (non-negotiable)
1. **No fabricated data.** <4 points → honest refusal. Missed days + backlog/never-started shown, never hidden.
2. **No causal language, n=1, correlative only.** Keystone correlations run on ~7 days: SUGGESTIVE, n-forward. **NO Pearson headline; no correlation chip until >=2 weeks.** n is the loudest element; lead with direction, not magnitude.
3. **Grades come from adherence RATE (real), not correlation.** Group grades/scores are computed from completion rate only.
4. **Inferred groupings are labeled auto-derived, not fact.** The derived taxonomy (P1.1) must carry a confidence/"auto-grouped" label; never present inference as ground truth.
5. **Streaks are fragile.** Consistency RATE + heatmap is the north-star; single streak demoted (honest at 0).
6. **Color discipline.** State taxonomy + effort map use ONE ember+ink ramp + position/shape/markers, NOT multiple hues. Recovery 14% / backlog = muted, NEVER red/alarm.
7. **Identity/atomic-habits framing is DATA-ANCHORED, never a mantra.** Always pinned to a real figure.
8. **Mark the genesis line.** 90-day history predates the cut — mark cut-start (2026-06-14).
9. **Design tokens only:** Fraunces, IBM Plex Mono, tick spine, two-voice. First-class dark AND light (NO light screenshot exists — verify yourself).

---

## PHASE 0 — Keystone honesty + the intelligence layer (buildable now)
**P0.1 — Keystone panel, honesty-rebuilt (THE fix).** Bare `r=0.88` → habit-group + direction/strength chip stamped `n=N - early signal, not proven`; coefficient withheld until >=2 weeks; two-voice; expands to show n + days + "what would sharpen this." Binds keystone correlations.
**P0.2 — Consistency rate north-star + heatmap headline.** "Held X of last N days"; demote single streak (honest at 0).
**P0.3 — 90-day adherence heatmap.** GitHub-style calendar of `history[].tier0_pct`, ember-saturation = completion, cut-start (Jun 14) marked; day → group breakdown.
**P0.4 — Tier ladder + group grades.** Lay habits out by registry tier (Tier-0 → Tier-3); each GROUP carries an adherence grade from RATE. Shows what's load-bearing. Binds registry tiers + `group_90d_avgs`.
**P0.5 — Habit state taxonomy (color-coded).** Tag every habit: Automatic (full ember) / Holding (ember tint) / Needs-attention (muted + marker) / Backlog-never-started (outline, honestly empty). ONE ember+ink ramp + position, no rainbow. Add a state filter. Binds per-habit adherence.
**P0.6 — Effort map.** Ranked dot-strip OR small treemap (block size = habit-count/volume, ember-saturation = adherence). Do NOT build a radar/spider unless I explicitly ask (cliche + misleading geometry) — STOP-AND-ASK if you think it's warranted.
**P0.7 — Per-group trend small-multiples.** Recovery 14% = the floor, muted. Binds `group_90d_avgs` + per-day breakdown.
**P0.8 — Goal linkage.** Each group/score links up to a broader goal/pillar; cross-link to other Evidence pages (copy-driven).
**P0.9 — Identity/compliance reflection (data-anchored two-voice).** Atomic-habits framing pinned to real data ("never missed twice on Hydrate in 44 days"). No mantras.
**P0.10 — Declutter + signatures.** Keep one or two top figures; day-of-week bars; grouped registry; add tick spine + >=1 serif annotation.

## PHASE 1 — Inference + new capture (add the capability/field first; never stub)
- **P1.1 Derived taxonomy** — NLP/classification pass over the registry → per-habit context (time-of-day, trigger, type: do/avoid/maintain) + logical grouping. Powers P0.4-P0.6. Label auto-derived; never present as fact.
- **P1.2 Per-habit difficulty / friction tag** — hard vs automatic.
- **P1.3 Drivers (trigger / friction / reward) per habit** → the drivers view.
- **P1.4 "Why missed" tags** → misses become narrative.
- **P1.5 Cross-page wiring** → nutrition/sleep/training completion feed groups + goal linkage.

## PHASE 2 — Keystone calibration (honesty-gated)
- **P2.1 Surface the keystone coefficient + correlation chip** ONLY once a group has >=2 weeks overlap; else "early signal, direction-only." Reuse the sleep correlation-board pattern.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-habits.png` + `-mobile.png` (390px) AND a NEW light capture. Verify:
- [ ] Keystone: NO bare Pearson headline; n loudest; "early signal, not proven"; coefficient withheld under 2 weeks.
- [ ] Consistency rate + heatmap lead; streak demoted (honest at 0); cut-start (Jun 14) marked.
- [ ] Tier ladder + group grades present; grades derived from RATE only.
- [ ] State taxonomy present incl. Backlog/never-started shown honestly; ONE ember+ink ramp, no rainbow, no red.
- [ ] Effort map is a strip/treemap (radar NOT built unless I approved).
- [ ] Per-group small-multiples; Recovery 14% muted, not alarm.
- [ ] Goal-linkage + data-anchored identity copy (no mantra).
- [ ] Inferred groupings (if P1.1 shipped) labeled auto-derived.
- [ ] Tick spine + >=1 serif annotation; <4-point charts refuse; no causal language.
- [ ] Dark AND light first-class (verify the new light capture).

## STOP-AND-ASK gates (no proceed without sign-off)
- Building a radar/spider chart (P0.6).
- Surfacing any keystone coefficient before the >=2-week window.
- Shipping inferred taxonomy groupings to the public surface (confirm the auto-derived labeling is acceptable).
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
Bare Pearson as a headline; correlation chip under 2 weeks; grades from correlation; streak as hero; red/alarm or rainbow states; guru/mantra copy; radar without sign-off; inferred groupings presented as fact; merging Habits with Vices/Mind (share components instead).
