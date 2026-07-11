# CLAUDE CODE PROMPT — The Doors / Cross-Site Experience (v1)
**Scope:** averagejoematt.com whole-experience — Home `/`, Cockpit `/now/`, Story `/story/`, Coaching `/coaching/`, Evidence `/evidence/`.
**Companion spec:** `docs/specs/SPEC_DOORS_EXPERIENCE_REDESIGN_2026-06-21.md` (read first — this is an IA/editorial review; the 5-door model and me-first are LOCKED).
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. This touches multiple front-end routes + shared layout/components; locate the door templates and the shared header/footer/genesis-stamp component by inspection. Reuse the design system + signatures (constellation, waveform, tick spine, two-voice); no new deps.

---

## HARD RULES (non-negotiable)
1. **5-door IA is LOCKED.** Do NOT add, cut, or merge doors. Improve within the five.
2. **Me-first is LOCKED.** Do NOT rebalance the hero/IA toward virality or stranger-conversion when it conflicts with the daily-me priority.
3. **One artifact, one home.** Each artifact (chronicle, board, Third Wall, dispatches reader) lives in exactly ONE door; others show a one-line teaser + "see full in X" link — never the full duplicate.
4. **Anti-black-box.** Composites (whole-life score, "Foundation" character level) must visibly decompose to their pillars/inputs.
5. **Honesty / week-one.** Down weeks shown; youth shown as the headline; projection suppressed; no superhuman/guru framing.
6. **Design tokens + signatures only:** Fraunces / IBM Plex Mono / Instrument Sans; ONE ember accent `#DD7A37`; dark AND light first-class; protect + extend the tick spine, two-voice, constellation, honest waveform.

---

## PHASE 0 — The throughline bug (P0, do first)
**P0.1 — One genesis source of truth.** Create/locate a single genesis util: days = (today - 2026-06-14), week = ceil(days/7). Every door's Day-N/Week stamp consumes it. Fix Home (currently "Week 1" on Day 8; correct is "Week 2"). Verify Home / Story / Coaching all agree.

## PHASE 1 — De-duplicate to one-home-plus-teaser
**P1.1 — Chronicle owns Story.** Remove the full chronicle reader from Home; Home shows a one-line teaser + link to Story.
**P1.2 — Board + Third Wall own Coaching.** Cockpit shows a one-line board read + link to Coaching (not the full board); Home teases the Third Wall + links to Coaching (not the full lab note).
**P1.3 — One canonical dispatches reader (Story).** Collapse the three readers (Home/Story/Coaching) so the full reader lives in Story; others teaser+link.

## PHASE 2 — Per-door uplevels
**P2.1 — Home: proof up to the promise.** Bring genesis stamp + live weight delta + the down-beat waveform together near the hero (claim + proof on one screen); waveform leads, prose follows.
**P2.2 — Cockpit: decompose the composite + de-densify.** Wire the big "Foundation" number to the constellation/pillars; collapse Month/Journey scopes by default.
**P2.3 — Story: elevate Matthew's voice.** Promote "In my own words"; make the timeline a first-class week-one artifact.
**P2.4 — Coaching: anticipation, not placeholder.** Frame "track record accruing" as "scores unlock as predictions resolve — week 1 of N"; expand the disagreement lines (Training->Physical etc.) into readable arguments.
**P2.5 — Door descriptors.** One-line descriptor per nav door (hover/under-label), extending the Cockpit "NEW HERE?" pattern.

## PHASE 3 — The moat (soul features; stop-and-ask on the mechanic)
**P3.1 — Third-Wall reply slot.** Design a first-class "Matthew's response" panel that is compelling WHILE EMPTY (clearly waiting, not absent), and an easy/habitual reply path. STOP-AND-ASK before building the reply mechanic.
**P3.2 — Track-record activation (needs weeks).** As predictions resolve, surface per-coach hit-rates; until then, the accruing-state anticipation copy.

---

## ACCEPTANCE CRITERIA / QA
Re-capture all four doors (desktop + mobile 390px + light). Verify:
- [ ] Day-N/Week stamp identical and correct across Home / Story / Coaching (Day 8 = Week 2).
- [ ] No artifact appears in full in more than one door; teasers link to the owning door.
- [ ] Home hero pairs the promise with proof (waveform + genesis + live delta).
- [ ] Cockpit big number visibly decomposes to pillars; Month/Journey collapsed by default.
- [ ] Story promotes "In my own words" + timeline.
- [ ] Coaching shows accruing-as-anticipation + readable disagreements.
- [ ] One-line descriptor per door.
- [ ] 5 doors intact; me-first intact (hero not reworked for conversion).
- [ ] Signatures intact (tick spine, two-voice, constellation, honest waveform); ember accent; dark AND light first-class.

## STOP-AND-ASK gates (no proceed without sign-off)
- Any change to door count/structure (should be none).
- Any change that rebalances away from me-first.
- The Third-Wall reply mechanic (P3.1).
- Any deploy.

## DEPLOY (per convention)
Front-end deploy per repo convention (CloudFront distribution `E3S424OXQZ8NBE`; site-api in us-west-2 if APIs touched). NEVER `--delete` on S3 sync; never execute deploy scripts via MCP. Update CHANGELOG + PROJECT_PLAN; commit + push.

## OUT OF SCOPE
Adding/cutting/merging doors; rebalancing toward virality; duplicating artifacts across doors; black-box composites without decomposition; animation gimmickry for the week-one frame; building the Third-Wall reply mechanic without sign-off.
