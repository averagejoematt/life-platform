# HANDOVER — full-cast portraits: enumerated → drawn → gated → APPROVED → LIVE — 2026-07-04 evening (session 13)

Session opened on the session-12 handover's ⭐ direction (#616, "the same visuals for all of
the coaches") with Matthew authorizing all PRs and deploys up front. **#616 is CLOSED: every
public-surface coach now has a signed live portrait or a recorded skip decision.** PRs #618
(staged candidates + dark wiring + build beat) and #619 (approved recipes + sign-off + lit-up
bundle) merged + deployed + live-verified; visual QA 33/33 pass. Matthew approved the round-1
contact sheet with a single word — one gate round, versus the pilot's four.

---

## What shipped (in ship order)

### Cast enumeration (the "~19" was really 17 → only 7 needed)
Explore-agent sweep over `config/personas.json` (canonical registry), board doc, engine, and
every site JS head call site. Dedup: the "real-expert" ids are aliases of the same characters
(layne_norton→Webb, peter_attia→Reyes, paul_conti→Reeves, rhonda_patrick→Patel,
andrew_huberman/the_integrator→Nakamura); there is only ONE Vance (Cora). **17 unique personas;
10 render as public heads; pilots covered 3; the batch = 7.**

### PR #618 — candidates + dark wiring + the build beat
- 7 hand-authored recipes staged UNSIGNED in `docs/design/portrait_candidates/2026-07-04/`,
  each claiming an unclaimed geometric base + one silhouette-carried signature + owned palette:
  **Webb** square/full beard (`nutrition_coach`) · **Reeves** pear/receding grey mane
  (`mind_coach`) · **Reyes** long rect/widow's peak + chin-spike goatee (`physical_coach`) ·
  **Patel** oval/side braid + round glasses (`glucose_coach`) · **Okafor** dome/only-bald +
  rect glasses (`labs_coach`) · **Brandt** tall/curl-cloud + askew accent tie
  (`explorer_coach`) · **Marsh** broad trapezoid/flat-top crew + only-mustache (no alias).
- **3 solo self-review render rounds before Matthew saw anything** (local Playwright render of
  the sheet → look → fix): silhouette exaggeration, brow-eye merge fix, Reeves de-feminized,
  Reyes de-muddled. This is likely why the gate took 1 round.
- Remaining head call sites joined `portrait(c) || sigil(c)` DARK (team-lead block + huddle
  marks in dispatches.js, convene cards in coaching.js, evidence coach grid + new import in
  evidence.js) — deployed byte-identical, verified.
- Build beat for the session-12 portraits story appended to `beats.json` (one beat/session —
  session 12's slot went to the forecast batch) — live on /story/build/.
- Recorded decisions on #616 + batch README: **Nakamura** deferred (renders by name only — no
  head call site exists); **the Chair** sigil-only (runbook §5: meta-role, not a person);
  **Murthy** no-portrait (real person's name — likeness fails ADR-106 reverse-image, and a
  non-likeness under the real name is incoherent; rename first if he ever needs a head);
  **Calloway/Rodriguez** email-only; **Tanaka** interim-sunset; **Cora Vance** inactive.

### The gate → PR #619 — approved, promoted, LIVE
Contact sheet artifact (silhouette litmus row shuffled + answer key, light/dark at 96/56/40,
sigil beside each, pilots included for cast-wide comparison):
https://claude.ai/code/artifact/6d473337-c9cf-4b79-8eb6-300878a1340e — **"approved"**.
All 7 promoted to `config/portraits/` with `_meta.sign_off` (sheet = that URL);
`portrait_data.js` = **10 signed recipes**; synced + invalidated. Live-verified: Webb's
portrait renders on the coaching coach detail **via the engine-id alias** (the #587 gotcha,
beaten this time), Elena byline intact, zero JS errors. `tests/visual_qa.py --screenshot
--ai-qa`: **33 passed / 0 failed** (7 warnings = pre-existing empty-screenshot transport
errors to Bedrock on some evidence tabs, not page failures).

## Gotchas learned
1. **At silhouette scale, the EARS are the widest point of every head** — a signature feature
   must beat the ear line (Webb's beard had to swallow it) or rise above the crown (Brandt's
   cloud, Park's bun) to register in the litmus. Interior details (hairlines, glasses) vanish
   in solid-shape renders.
2. **Self-review rounds are cheap gate rounds.** Rendering the sheet locally and LOOKING at it
   (screenshot → Read) caught "they look the same" failures the pilot needed live human rounds
   for. 3 solo rounds → 1 human round.
3. **The dispatches.js "My Team" view (CC-10) appears ORPHANED**: `/story/coaches/` 301s to
   `/coaching/coaches/` (coaching.js), and no shipped /story/ page mounts the `coaches` kind —
   so the team-lead block + huddle wiring is live-but-unreachable. Marsh's signed portrait
   lights up whenever that surface returns. Worth a look: either re-mount the team view or
   retire the dead code.
4. Duplicate `const` declarations kill an inlined multi-module page silently (sigils.js +
   portraits.js both define `escAttr`/`r2`) — the sheet builder strips them.

## Flags for Matthew (unactioned — his call)
- **GitHub Pages is enabled + public on the repo** (legacy Jekyll build of `main` at root →
  `averagejoematt.github.io/life-platform`, intermittently failing = the red runs in the
  watch item). An unintended public mirror; disable or bless.

## Watch
- ~~CI/CD pipeline on e1e30ca2~~ — **completed SUCCESS before session close** (site gate,
  pages, and the full pipeline all green; nothing to chase).
- **Sun 07-06** (unchanged): journal-seeded hypothesis engine; panelcast v2; inter-coach
  dialogue SKIPS. **Mon 07-07**: data-recon on derived rows.
- Forecast resolutions accruing since 07-05 (cockpit coverage line at n≥1).

## Next
- **This session's build beat is NOT distilled** (one beat/session — the slot carried the
  session-12 portraits story). The full-cast approval (17-persona enumeration, the ear-line
  lesson, 1-round gate) is a strong beat for next session.
- The orphaned team-view surface (gotcha 3) — re-mount or retire.
- Nakamura's portrait when the tensions/dispute UI gains heads; Cora Vance when the reading
  surface goes live; Murthy rename decision if he ever needs a head.
- Uplevel #575 lanes + intelligence #535/#538/#543/#545 untouched; speaking mouth-frames
  (mouth-a/b) still undriven.
