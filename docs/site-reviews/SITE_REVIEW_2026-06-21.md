# Site Review — 2026-06-21 · Full-site pass (all four doors)

> ⚠️ Internal self-assessment vs the V4 constitution + Product Board lenses, not external
> validation. See `docs/SITE_REVIEW_METHODOLOGY.md`.

**Scope:** full site — Home · Cockpit · Story (chronicle/journal/about) · **Coaching (new 4th door)** · Evidence (vitals/training + 11 more). Packet `qa-screenshots/2026-06-21/` (23 pages, 50 shots, 41 endpoints).
**Deterministic:** all 23 pages PASS; all 41 endpoints 200; cross-page consistency **0 disagreements** (weight/lost/progress/level agree across journey↔snapshot↔character).
**Context:** first pass *after* the F-01…F-10 fix sprint (PRs A–D, all live).

## Throughline verdict: **COHERES** (up from BREAKS on 6/20)

The Coaching breakout, the feed untangle, and the Story cleanup all landed and read well. The residual issues are **stale lede/teaser copy that hasn't caught up with the 4-door restructure**, and a few **data-story** questions (movement scoring, rounding).

## What's working (verified live)
- **Coaching door (F-04)** — clean: My Team lead (Eli Marsh) → roster → huddle → tabs (The Team / AI lab notes). 4-door nav + footer Coaching column wired on every door.
- **Coach page (F-05/F-06)** — now leads with stance + report card and *discloses* character/hypotheses/voice/journey; unified type. No longer one giant scroll.
- **Journal (F-01)** — "Nothing published here yet." ✅ honest-empty.
- **Chronicle (F-02)** — honest-empty (reads the real feed; pre-genesis cruft gone). ✅
- **About (F-08)** — personable, on-brand. **Podcast** rename + tab cleanup (F-07/F-10) live.
- **Data corroborates** — Evidence/vitals narrative ("Day 7, 305.1 lbs, down 9.4, sleep 8.2, recovery 60%") matches the Cockpit readiness band.

## Findings

| ID | Page | Cat | Sev | Finding | Suggested fix |
|----|------|-----|-----|---------|---------------|
| R-01 | Home + Story lede | narrative | **med** | Both still say *"The chronicle, the AI's weekly **lab notes**, the journal…"* — but lab notes (+ coaches) moved to the new **Coaching** door. The lede describes the old 3-door world. | Update the Home + Story lede copy; weave in the Coaching door. |
| R-02 | Home teaser | data | **med** | Home features **"The Architecture of Absence"** (a pre-genesis chronicle post) in the "in their own words" card, but the chronicle feed is now empty. `public_stats.json`'s `chronicle_recent` is stale → features a post that no longer exists. | Regenerate/clear `chronicle_recent` in `public_stats.json` (daily-brief) so Home doesn't feature a vanished post. |
| R-03 | Cockpit + Evidence/training | data | **med** | **Movement pillar = 21 / "slipping"** despite Evidence/Training showing **8 workouts** (5 Hevy session types) + daily walks (5.7 mi on 6/20). The movement score doesn't seem to credit the logged training/steps. | Verify the movement-pillar scoring credits Hevy workouts + steps (ties to the DI-1 movement-integrity work). |
| R-04 | Home / Cockpit vs Evidence | data | low | Weight shows **305** on Home/Cockpit (`/api/journey`) but **305.1** on Evidence/vitals (`/api/pulse`) — rounding mismatch (within the 0.1 tolerance, so the auto-check passed, but a reader notices). | Round consistently across `journey`/`pulse`. |
| R-05 | Evidence/training | data | low | **Strength 1RMs all read 0 lb** (Deadlift/Squat/Bench/OHP) — reads as "no strength data." Either no lifts logged this cycle or a data gap. | Confirm strength data flow; if genuinely none yet, label it an honest "no lifts logged yet" state. |
| R-06 | Evidence/training | data | low | "This week · daily movement" shows 290/184/186/148/200/357 labeled **"active min"** — 290 active-min ≈ 5 h; if these are steps they're far too low. Unit/label looks off. | Verify the metric + label (active minutes vs steps). |
| R-07 | Evidence/vitals | data | low | Reads **"Day 7"** (genesis 2026-06-14 → 2026-06-21 is 7 elapsed / Day 8 if Day 1 = genesis). | Confirm the day-count convention is consistent across pages. |
| R-08 | Home (landing) | ia/narrative | low | The cinematic home's body still narrates the 3-door world; the 4th (Coaching) door exists only in the top nav, not woven into the scroll. | Consider a Coaching beat in the home scroll (optional — nav may be enough). |

## Story spine (as walked)
Home (hook + proof numbers + honest waveform) → Cockpit (am-I-winning glance, the Chair's read) → Story (the honest arc; journal honestly blank) → **Coaching** (the AI team argues; each coach in depth) → Evidence (does the data hold up — it corroborates). The arc holds; the seams are the **lede copy** (R-01) and the **stale Home teaser** (R-02).

## Resonance note
Curious which of R-01…R-08 match Matt's own eyeball — R-01/R-02 (lede + teaser not catching up with the Coaching move) and R-03 (movement scoring) are the ones I'd expect a careful look to land on too.
