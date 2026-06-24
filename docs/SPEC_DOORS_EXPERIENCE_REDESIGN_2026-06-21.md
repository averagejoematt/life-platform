# SPEC — The Doors / Cross-Site Experience Redesign
**Date:** 2026-06-21
**Scope:** averagejoematt.com whole-experience — Home `/`, Cockpit `/now/`, Story `/story/`, Coaching `/coaching/`, Evidence `/evidence/` — how the five doors blend into one documentary.
**Source:** elite whole-site review (editorial + IA + brand + narrative + first-10s + viz/motion bench), grounded in live screenshots of all four doors (`home.png`, `now.png`, `story.png`, `coaching.png`, `coaching-lab-notes.png`).
**Note:** this is an IA/editorial review, not a data-page review — most moves are structure/ownership/throughline, not new data-bound components. The 5-door model is LOCKED; me-first is LOCKED (do not rebalance toward virality).

---

## 0. The spine
The doors share a system (Fraunces/Plex, ember, the Day-N stamp, the footer, the two-voice) but the SAME ARTIFACTS surface in multiple doors, which is what makes it feel like five tabs instead of one documentary. The fix is OWNERSHIP, not fewer doors.

> **Spine: "One documentary, five doors — each artifact has one home and teases elsewhere; one throughline counts the days, honestly."**

## 1. P0 BUG — the throughline disagrees across doors
- **Home reads "Day 8 · Week 1"; Story and Coaching read "Day 8 · Week 2."** Day 8 since 2026-06-14 is Week 2 → Home is wrong.
- The Day-N/Week stamp is the device meant to UNIFY the doors; it contradicting itself is the worst inconsistency on an honesty-brand site.
- **Fix:** ONE source of truth for genesis math (days since 2026-06-14, week = ceil(day/7)), computed once, consumed by every door. (Strongest argument for the cross-page DESIGN_STANDARD.)

## 2. Whole-site coherence — content ownership + de-dup
The disjointed feeling is duplication, not door count:
- **Chronicle** appears on Home AND Story.
- **Third Wall / lab notes** appears on Home AND Coaching.
- **"The board"** appears in Cockpit (weekly AI read) AND Coaching (huddle/disagreements).
- **Three dispatches readers** (Home, Story, Coaching) read overlapping content.

**Rule: one home + teaser.** Each artifact lives in ONE door; others show a one-line teaser + "see full in X" link, never the full artifact.
- **Story owns:** chronicle, Matthew's writing, timeline, about, podcast.
- **Coaching owns:** the board, the huddle, the disagreements, the Third Wall / lab notes.
- **Evidence owns:** the data pages.
- **Cockpit:** the daily instrument (me-first, noindex).
- **Home:** the trailer — teases all of the above, duplicates none.

## 3. Per-door highest-impact move
- **Home — pull proof up to the promise.** Move genesis stamp + the live weight delta (10.5 lb / 8 days) + the down-beat waveform together near the hero so claim + proof share a screen. The honest waveform is the most shareable, least-braggy asset — lead with it; prose follows.
- **Cockpit — connect the composite to its parts.** "4 Foundation" / whole-life score is a black-box composite; visibly wire the big number to the constellation/pillars (decomposition), and collapse Month/Journey by default so the dense instrument isn't overwhelming on open.
- **Story — elevate Matthew's own voice.** Promote "In my own words" (the one voice no AI can fake; most valuable on a me-first site); make the timeline the artifact that makes week-one felt (grows over time).
- **Coaching — make "track record accruing" the soul.** Frame the accruing state as anticipation ("scores unlock as predictions resolve — week 1 of N"); expand the cryptic disagreement lines (Training→Physical, Nutrition→Mind, Sleep→Explorer) into readable arguments — the coaches disagreeing is the most documentary thing on the site.

## 4. The "week one" frame (youth = momentum, not thinness)
- Make youth read as a clock ticking: Day-N-of-the-climb, "predictions resolving in ~X weeks," "next DEXA in Y days," track records "accruing."
- Anticipation devices + honest artifacts (the down-beat waveform, the growing timeline, accruing scores) — NOT animation gimmicks.
- Fix the week-number bug (§1) first or the frame undercuts itself.

## 5. The moat (named coaches + Third Wall)
- **Third Wall is one-sided (monologue).** Fine + honest at week one ("pending Matthew's response · honest both ways"). But the premise is DIALOGUE — a permanently one-sided wall becomes a broken promise by ~week 4-6. **Design the reply slot to be compelling WHILE EMPTY** (a first-class "Matthew's response" panel clearly WAITING, not absent) and make replying habitual, so a reply is a payoff the site has held space for. Revisit by week ~4.
- **Track records = the anti-guru engine.** Coaches scored over time, sometimes wrong, is the moat. Lean into accruing-as-anticipation; activate hit-rates as predictions resolve.

## 6. First-10-seconds (stranger; me-first preserved)
- NOT conversion optimization (me-first is locked) — honesty made instantly legible.
- In 10s a stranger should get: WHAT (a real person's AI-assisted transformation), IS-IT-REAL (down-beat waveform + Day-8 genesis + down-weeks-shown), WHY-CARE ("tools you already own").
- Lead the hero with waveform + genesis + one true number; prose second. The honest waveform is the tasteful hook.

## 7. Door legibility (without cutting doors)
- Five abstract nav labels ("The Cockpit" vs "The Evidence") don't tell a stranger instrument-vs-data.
- Add a one-line descriptor per door (hover/under-label), extending the Cockpit "NEW HERE?" pattern. Don't cut; label.

## 8. Consolidated build order (ranked)
1. Fix the Day-N/Week throughline — one source of truth. **[now, P0]**
2. De-duplicate artifacts to one-home-plus-teaser (chronicle→Story, board+Third Wall→Coaching). **[now]**
3. Home: pull proof up to the promise (waveform/genesis/delta hero). **[now]**
4. Design the empty Third-Wall reply slot (compelling-while-waiting). **[now]**
5. Frame "track record accruing" + expand disagreements as anticipation. **[now; hit-rates need weeks]**
6. One-line door descriptors for stranger-legibility. **[now]**
7. Wire Cockpit's big number to its pillars; collapse Month/Journey by default. **[now]**

## 9. Must-honor constraints
- **Design system:** Fraunces (human) + IBM Plex Mono (machine) + Instrument Sans (UI); ONE ember accent `#DD7A37`; first-class dark AND light; custom motion + View Transitions. Protect + extend the signatures: measuring-rule tick spine, two-voice dialogue, pillar constellation, honest waveform (down beats shown).
- **LOCKED:** the 5-door IA (do not cut/merge doors); me-first priority (do not rebalance toward virality/stranger-legibility when they conflict).
- **Honesty:** down weeks shown, never superhuman/guru; week-one youth shown honestly as the headline; projection suppressed at week one ("watch it happen"); any composite (whole-life score, character level) decomposes to its inputs (anti-black-box, per the page standard).
- **STOP-AND-ASK (touches locked IA + soul features):** any change to door count/structure; any change that rebalances away from me-first; the Third-Wall reply mechanic before sign-off.
