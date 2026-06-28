# Coaching Section Review — `/coaching/` (expert panel + build plan)

**Date:** 2026-06-28 · **Method:** 6-lens expert panel (product/IA · UX · MD/health · AI/trust · sample-reader · consultant), adversarially synthesized, then findings verified against the live render. Capture: `scratchpad/coaching-review/`.

> ⚠️ Internal self-assessment, not external validation.

## Verdict

**Ship the commentary-first flip — but the diagnosis sharpens the owner's complaint.** The section isn't *bio*-first (bio is already demoted: the coach detail page defaults to **Current read**, with Bio the 3rd tab). It is **roster-first**: you land on a rail of 9 near-identical coach cards and a subtitle, and the genuinely excellent content — each coach's live read, the disagreements, the integrator's call — sits *below the fold*. The platform's real differentiator (named AI coaches taking falsifiable stances and **arguing over real data**) already exists; it's **buried, not missing.** ~80% of the win is **re-layout + composing endpoints the section already fetches but doesn't render.**

**The redesign is ~40% shipped.** Only two asks are genuine backend: the experiment-to-date temporal frame and the most-recent-session card.

## Correction to the panel (verify-the-reviewer)

The panel's #1 "critical" was *"the read pane paints as an empty void on load."* **Verified false:** a direct DOM check shows `[data-dx-read]` renders **4451 chars / 2476px tall from ~300ms**. What looked empty in the static screenshot is the v5 **motion-layer reveal** (`html.mo` fades content in on scroll) — not a bug. There is **no render bug to fix**; the real problem is the IA one below (the *above-the-fold* payload), which the redesign solves. (~50% of raw review findings are false positives — `feedback_verify_agent_findings`.)

## What the section gets right (keep)

- The collective-read content is excellent and **falsifiable** — "WHERE THE TEAM DISAGREES — THE ARGUMENT, NOT JUST THE HEADLINE" with named opposing positions + "THE INTEGRATOR'S CALL." This is the moat.
- Bio is already demoted; the **Huddle** ("each coach's current read" + "watching: <metric>") is the right commentary-first atom.
- The **Third Wall** lab-notes framing ("an empty slot is honest, not a gap") is distinctive and on-brand.
- Consistent epistemic guardrail on every card ("a lens on real numbers, not a real person; correlative, never causal").

## Top problems (deduped, consensus-weighted)

| # | Problem | Sev | Fix |
|---|---------|-----|-----|
| 1 | **Roster-first, read-below-fold** — no all-coach view of "what the board is saying about my day/week" without clicking 8 rail items | CRITICAL | Make **The Read** the default painted payload: integrator tensions band + a stacked all-coach digest of live `position_summary` lines |
| 2 | **By Coach omits the domain data the owner asked for** (cardio, lifts this week, recent session, volume, comparisons) — and the endpoints are fetched-but-unrendered | CRITICAL | Render the coach's read **on top of** `observatory_week` + `coach_analysis` + `training_overview` (the read-on-its-data pattern) |
| 3 | **No temporal frame** — only "today's reflection"; "week/experiment" unanswerable though the week read exists unused | HIGH | Today/This-week/Experiment toggle: today=`coaching_dashboard`, week=`weekly_priority.cross_domain_notes`+`field_notes` (both FE), experiment=new compute (Ph B) |
| 4 | **8× identical "TRACK RECORD ACCRUING" badges** — the roster's only per-coach metadata; dead + repetitive | HIGH | Replace with each coach's live one-line stance (`position_summary`) + domain label |
| 5 | **Huddle shows static slogans** (`stance.headline`) instead of the live read that exists | HIGH | Swap to `coaching_dashboard.position_summary`; deep-link each row into that coach's Current read |
| 6 | **"Ask the board" form eats the entire first screen** on every load | MED | Move into a **Reader Q&A** tab; keep a one-line "Ask the board ↗" header link |
| 7 | **Proposed top-level "Scorecard" would be 8 rows of zeros** (`predictions` all 0 today) | MED | Don't give it top-level real estate; fold a thin track-record strip into By Coach, N>0-gated; promote in Phase C |
| 8 | **Mobile: 9-item vertical rail buries the read** | MED | Collapse to a horizontal domain-chip selector over a single-column read |
| 9 | **Integrator identity inconsistent** — hub says "Dr. Eli Marsh," `coaching_dashboard` says "Dr. Kai Nakamura" for the same synthesis voice | LOW | Pin one fictional persona in config so all endpoints agree |

## Final IA to build (refined from the proposed cut)

The panel refined the original 5-section cut: **merge "The Board" into "The Read"** (the My Team panel *is* the board synthesis) and **demote "Scorecard"** (no data). The one job: *"Hear what your AI board is saying about your data right now — and zoom into any domain."*

1. **THE READ** *(default)* — Today · This week · Experiment toggle. Lead with the integrator tensions band + a stacked all-coach digest of live `position_summary`. (Absorbs the standalone Board.) `coaching_dashboard` + `weekly_priority` + `field_notes`.
2. **BY COACH** — the coach's read rendered **on top of** their domain data (`observatory_week` + `coach_analysis` + `training_overview` + most-recent-session) with a thin track-record strip; bio is the 3rd tab. The owner's literal ask.
3. **THE TEAM** — roster / personalities / config, demoted to reference. `/api/coaches` + `/api/coach/{id}` character.
4. **AI LAB NOTES** — keep as-is (the Third Wall).
5. **READER Q&A** — absorbs the "Ask the board" form off the first screen.

## Ranked feature backlog

**Phase A — front-end only (the ~80% win; composes existing endpoints):**
1. Default the hub to **The Read** (all-coach digest + tensions band; roster → a tab). *transformational*
2. **By Coach: read-on-top-of-data** — `coach_analysis` + `observatory_week` + `training_overview` beside the read. *transformational*
3. Replace the 8× dead badge with each coach's **live stance + domain label**. *high*
4. **Huddle → live `position_summary`**, deep-linking to Current read. *high*
5. Move **Ask the board → Reader Q&A**; open on the read. *high*
6. **Mobile**: horizontal domain chips over single-column read. *high*
7. Thin track-record strip in By Coach (N>0-gated); **reconcile the integrator persona** in config. *medium*

**Phase B — modest backend:**
8. **Temporal toggle** on The Read — Today + This-week ship in Phase A (FE); **Experiment-to-date** = new cross-week synthesis. *high*
9. **"Most recent session" card** (date, exercises, sets, volume, vs last comparable session) on training/physical. *high*

**Phase C — future (deferred; needs the engine to produce data):**
10. Dedicated **Scorecard** (predictions/hit-rate) promoted to top-level *once predictions reach N>0*. *nice-to-have*

## Build sequencing

Phase A (front-end) lands the whole daily-value ask at low risk (re-cut `coaching.js` + `scripts/v4_build_coaching.py`; deploy = site sync). Phase B adds the most-recent-session card + temporal params (`site_api_coach.py`; deploy = `web/` site-api). Phase C deferred. Verify per the plan (render-QA, `/accuracy-review --live`, add routes to `visual_qa.PAGES`).
