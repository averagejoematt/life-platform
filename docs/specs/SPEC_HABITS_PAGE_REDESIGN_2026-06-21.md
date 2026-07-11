# SPEC — /evidence/habits/ Page Redesign
**Date:** 2026-06-21 (rev. with intelligence-layer additions)
**Page:** averagejoematt.com → /evidence/habits/ — "the consistency engine."
**Source:** elite page-specific design review (habit-formation / behavior-change / consistency-science bench, viz, product/UX), grounded in live screenshots (`qa-screenshots/evidence-habits.png`, `-mobile.png`; NO light capture exists — verify light parity at build) + real data, plus athlete-requested taxonomy/scoring/drivers layer.

---

## 0. The one story (the spine)
The page treats every habit as a flat checkbox in a pre-assigned category, and the one place it adds intelligence (the keystone panel) does it with false precision (`Nutrition r=0.88` at n=7). The redesign adds an HONEST INTELLIGENCE LAYER over the raw Habitify feed — read → group → tier → grade → state-code → tie to goals — with the keystone signal gated for honesty on top.

> **Spine: "Which habits are load-bearing, where the effort actually is, and which one is pulling the day up — said as an early signal, not a law."**

## 1. Current-state findings (must fix)
- **Keystone panel shows a bare Pearson (`r=0.88`, n=7) as if proven.** THE core honesty problem. Lead with direction + an explicit `n=7 - early signal, not proven` stamp; demote/withhold the coefficient until >=2 weeks.
- **Recovery group at 14%** (vs Nutrition 71%, Discipline 44%) → surface honestly as "the floor you haven't built yet," muted not red, never shaming.
- **Habitify categories are storage, not logic** → re-derive each habit's context/role (time-of-day, trigger, type: do/avoid/maintain) and regroup logically. Label inferred groupings as auto-derived, not fact.
- **Fragile single streak used as hero** → demote; north-star is consistency RATE + heatmap. Streak honest at 0.
- **No tiering / grading / state surfaced** → add the tier ladder, group grades, and a state taxonomy (incl. backlog).
- **90-day trend mixes pre-cut and cut-era** → mark cut-start (Jun 14); history predates the cut.
- **Signatures absent** → tick spine + two-voice.
- **Keep:** last-7-days grid (extend to 90-day heatmap); day-of-week bars; grouped registry; streak honest at 0.

## 2. Page architecture (top to bottom)
Legend: **[now]** · **[needs-data]** · **[defer]** · **[gated]**.

**§0 — Keystone signal (hero, honesty-rebuilt).** Strongest habit-group lever as direction + strength chip, stamped `n=N - early signal, not proven`; coefficient withheld until >=2 weeks; two-voice. Binds keystone correlations. **[now]**
**§1 — Consistency rate (north-star).** "Held X of last N days" + the 90-day heatmap as headline; single streak demoted (honest at 0). **[now]**
**§2 — 90-day adherence heatmap.** GitHub-style calendar of daily `history[].tier0_pct`, ember-saturation = completion, cut-start (Jun 14) marked; day → that day's group breakdown. **[now]**
**§3 — Tier ladder + group grades.** Habits laid out by tier (Tier-0 non-negotiables → Tier-3 nice-to-have), each GROUP carrying an adherence grade (0-100 / A-F) computed from RATE (real), never from a correlation. Shows what's load-bearing. Binds registry tiers + `group_90d_avgs`. **[now]**
**§4 — Habit state taxonomy (color-coded, the wow).** Every habit tagged by STATE, encoded on ONE ember+ink ramp + position (NOT a rainbow):
  - **Automatic** (high, stable) — full ember
  - **Holding** (consistent, lower) — ember tint
  - **Needs attention** (slipping) — muted ink + marker
  - **Backlog / never started** — outline only, honestly empty (most apps HIDE this; we show it)
  Binds per-habit adherence. **[now]**
**§5 — Effort map ("where the effort is").** Ranked dot-strip OR small treemap (group block size = habit-count/volume, ember-saturation = adherence). Radar/spider is OPTIONAL and flagged app-cliché + misleading-geometry — build only if the familiarity is explicitly wanted. **[now; radar gated/optional]**
**§6 — Per-group trend small-multiples.** Each group's 90-day adherence sparkline (Recovery 14% = the floor, muted). Binds `group_90d_avgs` + per-day breakdown. **[now]**
**§7 — Goal linkage.** Each group/score links UP to a broader goal/pillar (Recovery habits → recovery pillar → "hold the cut without breaking"). Cross-links to other Evidence pages. **[now, copy-driven]**
**§8 — Identity / compliance reflection (data-anchored two-voice).** Atomic-habits framing pinned to real data ("never missed twice on Hydrate in 44 days"; automaticity = how reliably it fires). NEVER a generic mantra/quote box. **[now]**
**§9 — Drivers behind the habits.** The trigger / friction / reward per habit. **[needs-data: per-habit driver capture]**
**§10 — Day-of-week + grouped registry.** Keep. **[now]**

## 3. Features / interactions
- Keystone card expands → n, the days behind it, "what would sharpen this read."
- Heatmap day → that day's group breakdown.
- State filter (show me: needs-attention / backlog / automatic).
- "Early signal" / honest empty states wherever thin.

## 4. Cut / merge
- **Do NOT merge with Vices/Mind — SHARE components** (streak+heatmap = Vices kit; keystone honesty = sleep correlation-board DNA; state-taxonomy reusable). Reuse, don't duplicate.
- Raw Pearson headline → n-stamped chip.
- Fragile single streak as hero → demoted.
- Redundant top figures → keep one or two.
- Radar (unless explicitly wanted) → ranked strip/treemap instead.

## 5. Data-capture backlog (ranked)
1. **Derived taxonomy inference** — NLP/classification pass over the registry → context (time/trigger/type) + logical grouping. Powers §3-§5; label auto-derived.
2. **Per-habit difficulty / friction tag** — separates hard vs automatic.
3. **Drivers: trigger / friction / reward per habit** — powers §9.
4. **"Why missed" tags** — misses become narrative.
5. **Cross-page wiring** — nutrition/sleep/training completion feed groups + goal linkage.

## 6. Must-honor constraints
- **Design system:** Fraunces, IBM Plex Mono, ONE accent ember `#DD7A37`; down = muted ink, **never red**. First-class dark AND light (verify light — no light screenshot yet). Reuse the inline-SVG kit (correlation chip ONLY for >=2-week pairs). Deploy tick spine + two-voice.
- **Color discipline:** the state taxonomy and effort map use ONE ember+ink ramp + position/shape, NOT multiple hues. "Color-coded states" = ember intensity + ink + markers, not a rainbow.
- **Ember semantics:** higher adherence = ember; Recovery 14% / backlog = muted, NOT red/alarm. Streak honest at 0.
- **Honesty / rigor:** n=1, correlative only, no causal language. Keystone correlations on ~7 days = SUGGESTIVE, n-forward; NO Pearson headline; no correlation chip until >=2 weeks; n is the loudest element. Group GRADES come from adherence RATE (real), not correlation. Inferred groupings labeled auto-derived, not fact. Backlog/never-started shown honestly. Identity framing data-anchored, never a mantra. Charts refuse <4 points.
- **Audience/privacy:** me-first; keep framing non-clinical.
