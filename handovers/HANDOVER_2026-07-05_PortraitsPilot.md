# HANDOVER — coach portraits: gate → approval → LIVE; fable queue emptied — 2026-07-05 (session 12)

Session opened on session-11's follow-ups, then Matthew said "work through all open issues
tagged to fable as the model" and granted merge + deploy for the session. **All three open
`model:fable` issues (#585 → #586 → #587, epic #576 Workstream G) are MERGED + DEPLOYED +
LIVE-VERIFIED and closed. The fable queue is empty.**

---

## What shipped (in ship order)

### Session-11 follow-ups (before the fable ask)
- **3 stale worktrees removed** (ds-health-review / honesty-pair / v5-coherence-redesign) after
  verifying all content already on main — `test_hevy_compiler_isolation` green again (117/117).
- **CI I22 rerun**: the watcher DID fire; run 28723416288 fully green; live `/version.json` == main.
- **Build dispatch (#380) distilled + LIVE** (PR #606): one beat for the session-11 fable batch —
  "The platform starts betting on tomorrow" (forecast engine + scenario explorer + first dispute).

### #585 — ADR-106 + runbook (PR #607)
ADR-106 "coach portraits — commissioned engraved identity" (AI may sketch, only code ships, only
Matthew approves; SS-11 + PG-14 photoreal NO-GO intact; kill = 2 failed revision rounds);
DESIGN_SYSTEM_V5 §8 header + §8.7; `docs/design/PORTRAIT_RUNBOOK.md` (style bible, contact-sheet
gate, disclosure spec).

### #586 — portraits.js, shipped dark (PR #608)
Recipe schema (`config/portraits/`, fixed 13 layers, `validate_recipe` authority in
`scripts/v4_build_portraits.py`); **sign-off gate is structural** — only recipes with
`_meta.sign_off` bundle into the generated `portrait_data.js` (wired into sync, blocking);
`portrait(c) || sigil(c)` at coaching.js coach-heads + coach_popover.js; tokens.css §13
(.portrait/-md/-lg, sigilDraw reuse, seeded 4–8s blink, 4.5s breath, reduced-motion = static via
inline opacity); 2 test-only fixtures; 8 unit tests. Live-verified byte-identical (0 portraits,
6 sigils, no JS errors).

### #587 — the taste gate, 4 rounds → approval → LIVE (PRs #609–#615)
The gate ran as a live design-review loop on ONE artifact URL (contact sheet, label history
v1→v4): **R1** "they look the same" → distinct facial constructions. **R2** "less sketch, more
animated realistic" → duotone filled masses (accent layer = coach colour; no engine change).
**R3** "identifiable like Pixar/animated-TV characters — reader knows who is who without the
name" → **the shape-language standard**: distinct geometric base per coach (Elena oblong / Park
circle / Chen wedge), owned full-colour palettes, one hyper-distinctive feature each, and the
**silhouette litmus row** (solid shapes, no faces) opening the sheet. Needed the **tone-palette
engine extension** (PR #612: per-recipe `palette` skin/hair/cloth/blush/line + per-element
`tone` → CSS custom props; accent falls back to `var(--coach)`; validator enforces resolution).
**R4 approved** ("approved" → variant A per coach; B variants = glasses/headband, staged in
`docs/design/portrait_candidates/2026-07-05/`).
**Ship (PR #614, closes #587):** signed recipes promoted; bundle = 3; Elena's chronicle-byline
portrait (dispatches.js, portrait-or-nothing); lab-notes coach-heads join the chain; disclosure
sentence on /coaching/ (builder-generated); runbook §1 rewritten to "commissioned character
identity" + ADR-106 amendment note + §8.7 update. Full suite 3010 green.

## Gotchas learned (the expensive ones)
1. **Runtime coach ids ≠ board persona ids.** The V2 engine serves `persona_id: "sleep_coach"` /
   `"training_coach"`; recipes are keyed `lisa_park`/`sarah_chen` — first deploy showed ZERO
   portraits (fallback chain silently rendered sigils, exactly as designed — which is also why
   nothing broke). Fix (PR #615): recipe `aliases` list → bundler emits collision-checked
   `ALIASES` map → `portrait()` resolves either key. **Any future recipe for a V2-engine coach
   needs its engine id in `aliases`. Elena has no engine id (journalist) — byline passes
   `elena_voss` explicitly.**
2. **Style gates steer, they don't converge on their own** — 4 rounds from "engraved stroke-only"
   (what the ADR I wrote that morning said) to full character illustration. Write style ADRs
   AFTER the first contact sheet, or expect to amend (the amendment path worked fine: load-bearing
   rules unchanged, style clause superseded with provenance).
3. **The silhouette litmus is the cheap recognisability test** — solid single-colour render, no
   faces: if the cast isn't tellable apart, no amount of facial detail will fix it.
4. `.claude/settings.local.json` is TRACKED in this repo — session permission grants ride along
   in commits (consistent with existing practice, but don't be surprised by the diff).

## Watch
- The last CI run on main (alias fix, duplicate event) was still in_progress at wrap —
  the same commit already has a fully green run; production manually live-verified.
  If it lands red on visual-qa, the coaching page is the place to look.
- **Sun 07-06** (unchanged from session 11): hypothesis engine journal-seeded; panelcast v2;
  inter-coach dialogue correctly SKIPS (W27 aired). **Mon 07-07**: data-recon on derived rows.
- Forecast resolutions started accruing 07-05 (cockpit coverage line switches on at n≥1).

## Next
- **⭐ FULL-CAST PORTRAITS — #616 (Matthew's explicit direction at session close: "we need to
  create the same visuals for all of the coaches").** Only Elena/Park/Chen shipped; every other
  public-surface coach (~19: Webb, Reyes, Reeves, Patel, Okafor, Nakamura, Brandt, Rodriguez,
  Marsh, Calloway, Vance, Murthy, the Chair, Tanaka, …) is still sigil-only. Batch per runbook
  §2–§4: unused geometric bases, engine ids in `aliases`, silhouette litmus, contact sheet(s)
  through Matthew's gate. This is the first thing to pick up. Voice/semantic states (mouth-a/b
  speaking frames) remain a later story.
- Build dispatch beat for THIS session (the portraits story — gate rounds + silhouette litmus
  would make a strong beat) NOT distilled: one beat/session max and #606 used it. Next session.
- Uplevel roadmap #575 lanes (coherence kit, chart contract, motion v2) untouched; intelligence
  #535/#538/#543/#545 untouched.
