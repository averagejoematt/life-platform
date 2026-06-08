# PG-14 — "AI me dropping weight": Tier-A spike + go/no-go

**Date:** 2026-06-07 · **Status:** spike complete — **decision pending (owner)** · **Scope:** PG-14 (BACKLOG), ADR-078 Wedge-B
**Prototype:** `spikes/pg14_ai_me/index.html` (self-contained, no deps; **not** under `site/`, so it is **not deployed**)
**Sample frames:** `spikes/pg14_ai_me/frame_304.png` · `frame_245.png` · `frame_185.png`

> Matthew's idea: *"an AI version of myself that drops weight, like those creative AI videos — how hard would it be?"* This spike answers "how hard" by building the cheapest honest version and assessing fidelity, taste, and privacy **before** any larger build — per the PG-14 instruction to spike first.

---

## TL;DR recommendation

**GO — but only Tier A, and only as one contained, data-driven artifact.** The spike proves the most *honest* version of the idea is also the most *buildable*: a faceless, monochrome body silhouette whose girth is a direct function of the real weight number (304 → current → 185). It morphs convincingly, holds the brand's rigor, and hallucinates nothing.

**NO-GO (defer) on Tier B (photoreal "you") and Tier C (generative video)** — they fail the honesty and/or privacy bar the whole site is built on, and the quality isn't there yet. Details below.

This is a creative artifact, not an analytic engine — it stays *contained* (one element, not a new platform pillar), consistent with the ADR-078 build cap.

---

## What the spike actually is

A parametric front-view silhouette drawn as a single inline-SVG path (same no-deps, inline-SVG idiom as the live charts). One input — `weight` — drives a normalised "heaviness" `g = (weight − 185) / (304.3 − 185)`, clamped 0–1. Body landmarks (neck, shoulders, chest, **waist/belly ← most weight-sensitive**, hips, thighs, legs, feet) each carry a base width plus a `g`-scaled bulge, so the figure rounds out at 304 and tapers to a defined waist at 185. A scrubber, milestone buttons (304 / now-306 / 270 / 225 / 185), and a play-loop animate the morph.

Numbers are the **real** anchors from `/api/journey` (start 304.3 · current 306.0 · goal 185.0); hardcoded in the spike so it runs offline, but in production they'd be a live fetch. It even shows the honest truth that the current number is *up* 1.9 lb since the restart — the figure reflects that, it doesn't flatter it.

**Run it:** open `spikes/pg14_ai_me/index.html` in a browser. (~230 lines, one file.)

---

## Findings (hands-on, not theoretical)

| Dimension | Verdict |
|---|---|
| **Concept feasible?** | Yes. A real-data-driven morphing figure is straightforward in vanilla SVG — the prototype is one file, no deps, no backend. |
| **Honesty** | Strong. Generic silhouette, no face, no identity; the shape is a *deterministic function of the measured weight*, so there is nothing to hallucinate or "guess." Passes the Henning/Lena standard the rest of the site holds to. |
| **Privacy** | Strong. No photos, no face, nothing sent to a third-party model. Consistent with the site's pseudonymous-ish posture (no employer, partner unnamed). |
| **Brand fit** | Good, *if framed as a data figure, not a glamour shot.* Faceless + monochrome + number-labelled reads as "instrument," not "diet ad." The summit's exact worry (looking like a transformation-influencer before/after) is avoidable, and this framing avoids it. |
| **Fidelity ceiling** | The **torso morph is convincing** (where weight visibly shows). **Limbs are the weak link** in pure-procedural 2D — credible but stylised; anatomically-perfect legs/feet would need hand-authored keyframes or a real 3D mesh. Fine for an abstract figure; not "photoreal," and shouldn't pretend to be. |
| **Effort to here** | ~1 session, including catching a real bug (a 2- vs 3-element landmark array produced a `NaN` x that silently broke the path fill — exactly the kind of thing a spike surfaces). |

---

## The three tiers, re-assessed with evidence

- **Tier A — data-driven parametric figure (RECOMMENDED).** This spike. Honest, privacy-safe, on-brand, cheap, *moves with real progress* (so it reinforces the "more likely to reach 185?" test rather than fantasising past it). Ship as **one** element — e.g. a hero on `/evidence/results/`, or a recurring chronicle milestone graphic — never as a sprawling new section.
- **Tier B — photoreal identity-preserving "you" (DEFER / likely never).** Three blocking problems, none cosmetic: (1) a generated "you at 185" is a *guess presented as fact* — it violates the correlative-honesty standard outright unless loudly labelled motivational fiction; (2) feeding your face/body to third-party generative APIs is a real privacy decision that cuts against the site's posture; (3) identity consistency is still unreliable. **Gate (unchanged):** an explicit owner privacy decision + a label-as-fiction commitment. The spike did not move this bar.
- **Tier C — generative AI video (DEFER).** Consistent identity + accurate body-change across a journey is beyond reliable quality today; expect artifacts. Revisit as models improve. No work done; none recommended now.

---

## If Tier A is approved — productionization path

Small, contained, no new backend:

1. Lift the silhouette + morph into a vanilla-JS module (`site/assets/js/`), reading `weight_progress` / `journey` from the **existing** `/api/journey` (+ `/api/weight_progress`) — **no new Lambda, no inference, no IAM.**
2. Place **one** instance: candidate homes are the `/evidence/results/` hero or a chronicle milestone card. Default state = the honest current number; let the reader scrub start→goal.
3. Guardrails to bake in: always data-driven (never a hardcoded "after"); always the "representative figure — not a photo, nothing generated" disclaimer; respect `prefers-reduced-motion`; keep it monochrome/faceless.
4. Optional later: improve limb fidelity via 2–3 hand-authored keyframe silhouettes cross-faded by `g` (better quality, still no deps) before ever considering a Three.js/SMPL 3D figure.

**Estimated effort:** Tier-A productionization ≈ S–M (the hard part — the morph — is done). Hold until **after** the Monday reset so it anchors to the new genesis weight.

---

## Why this is in `spikes/`, not shipped

A spike's job is to retire risk and inform a decision, not to ship. It deliberately lives outside `site/` so `sync_site_to_s3.sh` never deploys it. **Nothing is live.** The decision to productionize Tier A — and *where* one instance lives — is the owner's call; this doc + the three frames are the evidence for that call.
