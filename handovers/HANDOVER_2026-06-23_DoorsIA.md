# Handover — 2026-06-23 (Doors / cross-site IA redesign)

Cross-site IA/editorial pass over the five doors (Home `/`, Cockpit `/now/`, Story `/story/`, Coaching `/coaching/`, Evidence `/evidence/`). Spec: `docs/SPEC_DOORS_EXPERIENCE_REDESIGN_2026-06-21.md` + `docs/specs/CLAUDE_CODE_PROMPT_DOORS_v1.md`. 11 P-item commits. **Front-end only — no server change.** 5-door model + me-first LOCKED (untouched).

**Status: built + DEPLOYED + live-verified + MERGED.** PR **#206** (`doors-experience-redesign` → `main`, squash-merged `f2a5990c`). Live: all doors "Day 10 · Week 2" from one source, zero console errors.

## What shipped
- **P0.1** one genesis source of truth — `genesisCount()` in `coach_popover.js`; `story.js` duplicate math removed.
- **P1.1–P1.3** de-dup to one-home-plus-teaser — Home teases chronicle (→Story) + Third Wall (→Coaching); lab notes routed to Coaching. Home `story.js` is the only Home script; Story uses `dispatches.js`, Coaching `coaching.js` (separate — safe to edit Home alone).
- **P2.1** Home hero proof-paired (live delta + genesis), waveform leads the arc. **P2.2** Cockpit "sum of seven pillars" link + Month/Journey quieted (`scope-deep`). **P2.3** Story promotes "In my own words" + timeline cards. **P2.4** Coaching anticipation copy + readable disagreement cards (positions + integrator's call, reusing the WQA-06 `_team_tensions` fields position_a/position_b/resolution). **P2.5** door descriptors (hover title) across 55 nav files.
- **P3.1** Third-Wall reply slot = first-class held space (`voice-pending`, dashed-ember). **Reply mechanic NOT wired** (STOP-AND-ASK + no-fabricated-reply). **P3.2** track records auto-activate as predictions resolve.

## Files
`coach_popover.js` (genesisCount), `story.js` (Home teasers + hero proof), `coaching.js` (anticipation + readable tensions + reply slot), `index.html` (hero proof + beat reorder + wall/dispatches teasers), `now/index.html` (decomp link + quiet scopes), `story/index.html` (voice/timeline cards), `story.css` + `cockpit.css`, + 55 nav files (descriptors). No DDB/API change.

## Gates honored
5 doors intact (no add/cut/merge); me-first intact (hero copy unchanged, no conversion rework); signatures intact (tick spine, two-voice, constellation, honest waveform); ember; dark+light. STOP-AND-ASK respected: no door-count change, no me-first rebalance, reply mechanic NOT built. Never `--delete` on S3 (used `sync_site_to_s3.sh` safe sync).

## Earlier this session
Physical (#201), RQA-04 (#202), RQA-05 (#203), WQA-06 (#204), Vitals (#205) — all live. See their handovers + CHANGELOG.

## Next: Mind page redesign (queued)
Specs: `docs/specs/CLAUDE_CODE_PROMPT_MIND_PAGE_v1.md` + `docs/SPEC_MIND_PAGE_REDESIGN_2026-06-21.md`. THE most sensitive page. HARD RULES: vices/substances NEVER named publicly (private unnamed streaks); relapse = muted RESET, NO red (site-wide red rule EXCLUDED here), no shame; lead with cumulative restraint/resilience not a fragile streak; mood/journal logging is an INVITATION not obligation; non-clinical tone; inviting empty states; Mind pillar decomposes; Third Wall restores Matthew's last word. STOP-AND-ASK: ANY red; the mood/journal/temptation capture mechanics (confirm invitation-not-obligation UX first); the Third-Wall reply mechanic; any deploy. No light screenshot yet — create one.

See [[project_build_fingerprint]], [[reference_local_render_qa]], [[feedback_sensitive_content]], [[feedback_prod_deploy_authorization]].
