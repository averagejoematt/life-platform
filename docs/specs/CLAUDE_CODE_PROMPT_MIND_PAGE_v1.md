# CLAUDE CODE PROMPT — Mind & Accountability Page Redesign (v1)
**Target:** averagejoematt.com → `/evidence/mind/`
**Companion spec:** `docs/specs/SPEC_MIND_PAGE_REDESIGN_2026-06-21.md` (read first — the "awaiting its human" spine, the sensitivity rules, the friction-killer capture)
**Date:** 2026-06-21

Implement in phases. Inspect existing code before changing it. API: `lambdas/site_api_lambda.py` (Lambda `life-platform-site-api`, **us-west-2**); page consumes `/api/mind_overview`. Locate the front-end `/evidence/mind/` components; reuse the inline-SVG chart kit (no new deps). Where a component matches a Vices/abstinence-streak surface or the doors/Coaching Third Wall, REUSE it — do not duplicate.

---

## HARD RULES (non-negotiable — sensitivity is the brief)
1. **Privacy: specific vices/substances are NEVER named publicly.** Private, unnamed streaks only.
2. **No shame.** A relapse is a muted RESET, never red, never an alarm. The site-wide "red allowed" rule is EXPLICITLY EXCLUDED on this page — NO red on relapses or mood. Lead with cumulative restraint + resilience, not a fragile streak that punishes a reset.
3. **Autonomy.** Mood/journal logging is INVITATION, not obligation — NO nags, NO guilt, NO gamified coercion.
4. **Non-clinical / non-preachy / self-compassionate** tone throughout. No diagnosis; never reinforce negative self-talk.
5. **Agency.** The Third Wall restores Matthew's last word over the machine's read.
6. **Honest empty states, never hollow.** Empty mood/journal is an INVITING absence ("this is where how-it-felt goes; one tap to start"), never an empty axis or a "no data" error. Charts refuse <4 points.
7. **Anti-black-box.** The Mind pillar (~54 Foundation) decomposes to its inputs.
8. **No causal language, n=1, correlative only.** No Pearson/correlation chip until >=2 weeks.
9. **Design tokens only:** Fraunces, IBM Plex Mono, ONE ember accent `#DD7A37`, tick spine, two-voice. First-class dark AND light.

---

## PHASE 0 — Reframe + the restraint that's real (buildable now)
**P0.1 — Vice restraint (held + cumulative, reset-honest).** Current hold + milestone ladder + CUMULATIVE total days held across resets (a reset never erases the proof). Relapses = muted resets, NEVER red/alarm. Private/unnamed. Binds vice streaks.
**P0.2 — The inviting absence (mood/journal).** Replace the hollow "no data" line with a dignified inviting empty state + a one-tap entry point. Never an empty axis.
**P0.3 — Mind pillar decomposed.** Show the ~54 Foundation score with its inputs, not a black box.
**P0.4 — Third Wall centerpiece.** The AI's weekly read vs Matthew's response slot, invitingly EMPTY (waiting, not absent). Two-voice. Reuse the doors/Coaching Third Wall component.

## PHASE 1 — The friction-killer capture (the data gap is behavioral)
**P1.1 — 1-tap daily mood.** One inviting control (faces/dots + optional note), low-stakes, no nag, no guilt; capturable from the Cockpit / Vitals glyph row / email reply. Accrues into a mood sparkline. Add the capture field/ingestion BEFORE binding; honest empty state until it accrues.
**P1.2 — Weekly reflection prompt.** One gentle question → journal seed; beats the blank page.
**P1.3 — Temptation quick-log + ledger.** One judgment-free tap when a temptation hits (resisted/not); a quiet private resist-rate ledger. Binds `log_temptation` / `get_temptation_trend`.
**P1.4 — Meditation minutes.** Auto-source if possible (less friction than manual).

## PHASE 2 — The payoff (gated on input)
**P2.1 — Mood-vs-recovery overlay.** Once mood logs accrue (>=~2 weeks), "did I feel as good as my body said?" Observation-only; no Pearson/chip under the window. Placeholder until then.

---

## ACCEPTANCE CRITERIA / QA
Re-capture `evidence-mind.png` + `-mobile.png` (390px) AND a light capture. Verify:
- [ ] No vice/substance named anywhere public; streaks private/unnamed.
- [ ] Relapses render as muted resets — NO red, NO alarm, NO shame language; cumulative restraint leads, not a fragile streak.
- [ ] Empty mood/journal is an INVITING absence with a one-tap entry, not a hollow axis or error.
- [ ] Mind pillar decomposes to inputs (not a black box).
- [ ] Third Wall present with an invitingly-empty Matthew-response slot.
- [ ] Mood/journal capture is invitation, not obligation — no nags/guilt/gamified coercion anywhere.
- [ ] Tone non-clinical, non-preachy, self-compassionate.
- [ ] No correlation chip under 2 weeks; charts refuse <4 points.
- [ ] Single ember accent; dark AND light first-class.

## STOP-AND-ASK gates (no proceed without sign-off)
- ANY use of red on this page (excluded by default).
- The mood/journal/temptation capture mechanics (P1.x) — confirm the invitation-not-obligation UX with me before building.
- The Third-Wall reply mechanic.
- Any deploy.

## DEPLOY (per convention)
`deploy/deploy_lambda.sh` for `life-platform-site-api` (us-west-2), 10s between deploys. Update CHANGELOG + PROJECT_PLAN; data-model changes → ARCHITECTURE/SCHEMA/DATA_DICTIONARY; `python3 deploy/sync_doc_metadata.py --apply` if counts changed; commit + push.

## OUT OF SCOPE
Naming vices/substances publicly; red/alarm on relapses or mood; shame/nag/guilt framing; gamified mood coercion; clinical/diagnostic tone; hollow empty axes; a black-box Mind pillar; correlation chip under 2 weeks; merging Mind into Habits (share components instead); duplicating the Third Wall or abstinence-streak components.
