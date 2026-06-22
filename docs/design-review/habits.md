# Design review — HABITS page (paste whole into your claude.ai Project; attach screenshots)

You are running an elite, page-specific design review for ONE page of my personal
health-transformation website, **averagejoematt.com**. Work in two stages.

## STAGE 1 — Assemble the room (do this first)
Design the IDEAL panel for THIS page's domain (**habit formation / behavior change / consistency
science / personal-analytics design**). Name 4–6 world-class specialists (think: a habit-formation
researcher, a behavioral economist on streaks/incentives, a quantified-self analytics person, a
keystone-habit/identity-change author), **plus a data-viz designer**. Justify each pick for THIS
page; one-line intros.

## PLATFORM CONTEXT (every idea must live inside this)
Honest, ongoing **documentary of an ordinary person rebuilt with AI — "anti-Blueprint."** Cut
started **2026-06-14** (~1 week of post-genesis data, though Habitify history runs longer).
Audience: **me daily → a few who know me → a stranger**; me-first but legible. Honesty is the brand
(missed days shown). **n=1, correlation-not-cause — explicitly no Pearson coefficient claims until
~2+ weeks** (the keystone-correlation panel currently runs on ~7 days, so it must be framed as
suggestive, not statistical).

## DESIGN SYSTEM (elevate within it — don't replace it)
**Fraunces** headings; **IBM Plex Mono** data; **ONE ember accent `#DD7A37`** (down = muted ink,
never red); restrained, data-forward, dark AND light. Chart kit: line (goal line; refuses <4 pts),
bar, stacked-composition bar, sparkline, **correlation chip** (already used here). Protect the
measuring-rule spine + the two-voice dialogue.

## THE PAGE + ITS REAL DATA (ground every idea here — flag anything needing data I don't capture)
**Page:** `/evidence/habits/` (`/api/habits` + `/api/habit_registry`) — "the consistency engine."
**Data right now:**
- **90-day adherence history** — daily tier-0 completion % (`history[].tier0_pct`), plus per-day group breakdown.
- **Per-group 90-day averages** (`group_90d_avgs`: Nutrition 71%, Discipline 44%, Recovery 14%, …).
- **Keystone correlations** — top habit-groups by Pearson r vs the day-grade (Nutrition r=0.88, n=7)
  — **correlative, tiny-n; must be framed as "suggestive, not proven."**
- **Day-of-week averages**, best/worst day, **current streak** (shown honestly even at 0).
- Full **Habitify registry** grouped by category (the habits being tracked).
**Currently rendered:** streak + days-tracked + habits-count + most-held-group figures, a
keystone-correlation panel, a 90-day adherence trend, a last-7-days color grid, per-group completion
bars, day-of-week bars, and the grouped habit list.
**Screenshots:** attached (full desktop scroll + mobile; light/dark if it differs).

## STAGE 2 — The review (after assembling + introducing the panel)
Panel reacts in their own voices, disagreeing where they would, and delivers:
1. **The one story** this page should tell that it currently doesn't (e.g. "which habit actually
   moves the needle" — done honestly at small n).
2. **Specialist visuals** — concrete; chart type + exact fields. (Push past, don't copy: a
   GitHub-style 90-day adherence heatmap; a streak calendar; the keystone-correlation panel
   redesigned with an explicit n / confidence treatment; per-group trend small-multiples;
   identity-based framing ("the kind of person who…").)
3. **Features / interactions** that level it up.
4. **What to cut** (or merge with Vices/Mind?).
5. **What's missing** I should capture.
Rank by impact. Honor the design system + honesty + me-first. **Especially:** how to present the
keystone correlations *honestly* at n=7 without either overclaiming or hiding the most interesting
signal on the page. Mark **buildable now** vs **needs more weeks**.
