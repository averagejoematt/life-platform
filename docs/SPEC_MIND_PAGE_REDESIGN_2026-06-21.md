# SPEC — /evidence/mind/ Page Redesign (Mind & Accountability)
**Date:** 2026-06-21
**Page:** averagejoematt.com → /evidence/mind/ — "the inner life: mood, restraint, reflection."
**Source:** elite page-specific design review (behavior-change + addiction-recovery + self-determination + mental-health-aware-design bench, viz, me-first product), grounded on the design-review brief (filesystem hung before screenshots could be pulled — current render per brief: mind-pillar figure, an honest "no journal/mood logged this cycle yet" line, the private vice-streak table). Verify layout-level notes against screenshots when available.

**SENSITIVITY:** this page touches vices and mood. Thoughtful, never preachy or clinical. HARD privacy rule: specific vices/substances are NEVER named publicly (private streaks only). Honesty: relapses shown, not hidden — but as resets, never shame.

---

## 0. The one story (the spine)
Every other page is the MACHINE watching (wearables, scale, labs — automatic). This is the only page that does NOT exist unless Matthew shows up. At week one the subjective layer is empty (journal 0, mood 0, meditation 0). The honest move is to make that emptiness an INVITING, dignified absence — not a hollow error — and to lead with the real restraint that IS there.

> **Spine: "The layer the machine can't see — awaiting its human."**

The AI has every number about the body this week and zero about what it felt like. That gap, shown with dignity, IS the Third Wall: the machine sees the body, it can't see the meaning. Reframe the emptiness; lead with restraint (held streaks, compassionately framed); make the Third Wall the centerpiece that hands Matthew the final word.

## 1. Current-state findings (must fix)
- **Empty mood/journal renders as a hollow "no data" line** → reframe as an inviting absence ("this is where how-it-felt goes; one tap to start"). The empty state IS content; don't show an axis of nothing.
- **Vice streaks risk reading as a fragile scoreboard** → lead with held-days + CUMULATIVE restraint (total days held across resets) + a milestone ladder; relapses render as muted RESETS, never red, never shame.
- **Mind pillar (~54 Foundation) shown as a black-box composite** → decompose to its inputs (the standard).
- **No Third Wall on this page** → make the AI-read vs Matthew-response dialogue the centerpiece.
- **No frictionless capture** → the data gap is BEHAVIORAL not technical; the highest-impact work is a 1-tap mood + a gentle reflection prompt.
- **Keep:** the honest acknowledgement that nothing's logged (but reframe it as inviting); the private/unnamed vice streaks.

## 2. Page architecture (top to bottom)
Legend: **[now]** · **[needs-input]** · **[needs-weeks]**.

**§0 — Vice restraint (held + cumulative, reset-honest).** Current hold (e.g. 5 days) + a milestone ladder + CUMULATIVE total days held across all resets (a reset never erases the proof of restraint). Relapses = muted resets, NEVER red, NEVER an alarm. Private/unnamed per the hard rule. Binds vice streaks. **[now]**
**§1 — The Third Wall (centerpiece).** The AI's read of the week (it has recovery/sleep/strain/nutrition) vs Matthew's response slot, invitingly EMPTY (clearly waiting, not absent). Two-voice. Same anticipated-empty-slot pattern as the doors review; shares the component. Binds AI weekly read + (empty) response. **[now]**
**§2 — The inviting absence (mood/journal).** Not a hollow chart — a dignified "this is where how-it-felt goes; nothing logged this cycle — one tap to start." Binds mood/journal (empty). **[now]**
**§3 — 1-tap daily mood (the friction-killer).** One inviting control (a few faces/dots + optional note), low-stakes, no nag, no guilt. The single highest-leverage element; the gap is behavioral. Accrues into a mood sparkline. **[now, needs the capture wired]**
**§4 — Restraint / temptation ledger.** A quiet, private ledger of temptations faced and resisted (resist-rate), no shame. Binds the temptation log (`log_temptation` / `get_temptation_trend`). **[now if temptation data exists]**
**§5 — Mind pillar, decomposed.** The ~54 Foundation score with its inputs, not a black box. **[now]**
**§6 — Mood-vs-recovery overlay.** Once mood logs: "did I feel as good as my body said?" Observation-only, no Pearson <2 weeks. The payoff of closing the gap. **[needs-weeks of mood input]**

## 3. Features / interactions (the behavioral core — this IS the page)
- **1-tap mood, capturable from anywhere** — the Cockpit, the Vitals glyph row, even an email reply. Invitation, never obligation: NO streak-shaming on mood, NO nags, NO gamified coercion.
- **Weekly reflection prompt** — one gentle question to seed the journal and beat the blank page.
- **Relapse logging is one tap and judgment-free** — if logging a reset feels unsafe, it won't happen, and the page lies by omission.
- The Third Wall reply: the compelling-while-empty slot from the doors review.

## 4. Cut / merge
- **Do NOT merge Mind into Habits** — the emptiness is the point; reframe, don't hide. SHARE components: the abstinence-streak kit with any Vices surface; the Third Wall with Coaching/the doors. (Habits = did I do the things; Mind = the inner life + the felt battle. Vice restraint lives here.)
- Cut any hollow mood/journal chart that renders an empty axis → the inviting empty state.
- Cut anything clinical, diagnostic, or preachy.

## 5. Data-capture backlog (ranked)
1. **1-tap daily mood** — the friction-killer; closes the gap.
2. **Weekly reflection prompt** — lowers the blank-page barrier; seeds the journal.
3. **Temptation quick-log** — one judgment-free tap when it hits.
4. **Meditation minutes** — auto-source if possible; less friction than manual entry.

## 6. Must-honor constraints (sensitivity is the differentiator)
- **Privacy:** specific vices/substances NEVER named publicly — private, unnamed streaks only. HARD.
- **No shame:** a relapse is a muted RESET, never red, never an alarm. The site-wide "red allowed" decision is EXPLICITLY EXCLUDED on this page — no red on relapses or mood. Lead with cumulative restraint + resilience, not a fragile streak that punishes a reset.
- **Autonomy:** mood logging is INVITATION, not obligation — no nags, no guilt, no gamified coercion (kills intrinsic logging).
- **Non-clinical / non-preachy / self-compassionate** tone throughout. No diagnosis, no judgment. Never reinforce negative self-talk.
- **Agency:** the Third Wall exists to restore Matthew's agency — the human gets the last word over the machine's read.
- **Design system:** Fraunces, IBM Plex Mono, ONE ember accent `#DD7A37`; down = muted ink. First-class dark AND light. Reuse the inline-SVG kit; charts refuse <4 points. Deploy tick spine + two-voice.
- **Honesty / rigor:** n=1, correlative only, no causal language, no Pearson/correlation chip until >=2 weeks. Much of this page is honestly "awaiting input" at week one — say so with dignity.
- **Audience:** me-first; the page earns its place by showing the machine's blind spot, not by faking content.
