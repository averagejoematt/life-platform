# Site Review — 2026-06-20 · The Story door (`/story/`)

> ⚠️ **Internal self-assessment**, not external validation. This grades conformance to
> the site's own stated intent (V4 Design Constitution + Product Board lenses), not
> market quality. The only true arbiter is a real target-audience member using it cold.
> See `docs/SITE_REVIEW_METHODOLOGY.md`.

**Scope:** Story door — hub + chronicle, AI lab notes, journal, coaches (roster + per-coach), about, panel.
**Packet:** `qa-screenshots/2026-06-20/` (12 screenshots, 8 endpoints). Genesis = `2026-06-14` (cycle 4).
**Inputs:** Matt's manual QA notes (folded in as directed `annotation` findings) + an independent Claude Code pass (visual via screenshot Read + data via captured `api/*.json`).

---

## Story spine (as a visitor walks it)

1. **Story hub** → "this is the written, honest arc — a chronicle, a podcast, coaches, my journal." Promise set. ✅
2. **Chronicle** → but the *latest* essay is dated `2026-05-03`, six weeks **before** the experiment began (`2026-06-14`). A reader who reads dates senses a reset seam / staleness. Belief dips.
3. **AI Lab Notes** → "the AI's weekly read" — but with no visible Matt response it reads one-sided, not the "me vs them" dialogue the section promises.
4. **The Coaches** → "a whole AI team argues about him" — the strongest moat moment — but it's one dense page with shifting type, so the visitor can't actually follow any single coach.
5. **In My Own Words** → expects Matt's raw voice; instead finds 7 polished essays that read AI-shaped. The "his own words" promise is undercut.
6. **About** → expects the person; gets the homepage tagline again. The human behind the data stays abstract.

## Throughline verdict: **BREAKS**

The narrative *scaffolding* is strong and on-brand (anti-Blueprint, the interpretation layer, honesty). What breaks the throughline is mostly **data-state**, not design: stale post-reset dates (chronicle), AI content standing in for Matt's voice (journal), and the missing Matt-response (lab notes) — plus one IA decision (Coaching is buried as a tab). Fix those seams and this door coheres.

---

## Top work order (prioritized)

| # | Finding | Sev | Effort |
|---|---------|-----|--------|
| 1 | **Journal isn't blank** — `/story/journal/` shows 7 posts (2026-02-22…05-04); none written by Matt. Should be an honest empty state until he writes one. | high | M |
| 2 | **Chronicle dates are pre-genesis** — all 5 posts dated 2026-02-22…05-03 (prior cycles); per-reset they should re-date near genesis and stale issues shouldn't surface. | high | M |
| 3 | **No Episode 1** — expected a Fri 6/19 drop; only Episode 0 (6/18) exists. Verify the panelcast cron fired + HELD (thin cycle-4 data is a by-design fail-closed) and surface *why* on the Panel tab. | high | S→M |
| 4 | **Break Coaches into its own top-level "Coaching" section**; move AI Lab Notes under it. It's buried as one of 7 Story tabs. | med | L |
| 5 | **Per-coach page: unify the type** — 3-4 competing faces (serif stance / mono "Track record" / dense body / small-caps labels) make one coach hard to follow; split into disclosed sections. | med | M-L |
| 6 | **About is impersonal** — reuses the home-hero positioning line verbatim; write a personable About from the prior site's about/story. | med | M |
| 7 | **AI Lab Notes → make it "me vs them"** — AI Sunday findings + Matt's response, or an explicit "pending Matt's response" (the `has_matthew_response` flag already exists, currently false). | med | M |
| 8 | **Rename "The Panel" → "Podcast"** (or a podcast-implying name, the way "Chronicle" implies the story). | low-med | S |

---

## Findings

| ID | Page | Cat | Sev | Lens | Finding | Evidence | Fix | Eff |
|----|------|-----|-----|------|---------|----------|-----|-----|
| F-01 | /story/journal/ | data | high | annotation | "In My Own Words" shows 7 posts (2026-02-22…2026-05-04) but Matt has written none — current entries aren't his voice. | `journal-posts.json` (count 7) | Source journal only from Matt-authored posts; honest empty state until then. | M |
| F-02 | /story/chronicle/ | data | high | annotation | All 5 chronicle posts predate genesis (2026-06-14): wk −4…5 dated 2026-02-22…05-03. Reset should re-date near start; prior-cycle issues shouldn't surface unless intended lead-ins. | `chronicle-posts.json` | Re-curate chronicle for cycle 4 (`restart_pipeline --keep-chronicle` / curator); drop unintended pre-genesis issues. | M |
| F-03 | /story/ (Panel) | data/ops | high | annotation | Expected Episode 1 to auto-drop Fri 6/19; only Episode 0 (2026-06-18) present. Likely the Fri 17:00 cron fail-closed HELD on thin cycle-4 data (5 days post-genesis) — by-design, but unverified and unexplained to the reader. | `panelcast-episodes.json` (1 ep) | Confirm the 6/19 run fired + HELD (lambda logs / `PANELCAST#` series_state); if HELD, surface "next episode pending — N days of data" on the tab. | S→M |
| F-04 | /story/coaches/ | ia | med | annotation·Mara·Ava | The Coaches is buried as one of 7 Story tabs; warrants its own top-level "Coaching" section with AI Lab Notes moved under it. | `story.png` (tabs+footer) | Promote Coaching to top-level nav; regroup AI lab notes under it. | L |
| F-05 | /story/coaches/#coach | font/visual | med | annotation·Tyrell | Per-coach page uses 3-4 competing type treatments (serif stance headline, mono "Track record accruing", dense body, small-caps labels) → hard to follow one coach. | `story-coaches-#sleep_coach.png` | One type hierarchy per coach; disclose stance / report card / track record as sections, not a long stack. | M-L |
| F-06 | /story/coaches/ | ia | med | Mara | "My Team" packs huddle + tension map + per-coach quotes on one canvas — "one page trying to cover everything." | `story-coaches.png` | Master-detail (team overview → per-coach); part of the F-04 breakout. | L |
| F-07 | /story/ (naming) | content/ia | low-med | annotation·Ava | "The Panel" doesn't signal "podcast" the way "Chronicle" signals the story. | `story.png` tab + footer | Rename tab/section/nav label to "Podcast" (or podcast-implying). | S |
| F-08 | /story/about/ | narrative | med | annotation·Ava | About is thin/impersonal — reuses the home-hero positioning statement verbatim; a Home→About visitor reads the same line twice. | `story-about.png` vs `home.png` | Write a personable About building on the prior site's about/story; distinct from the hero. | M |
| F-09 | /story/ (lab notes) | narrative/data | med | annotation·Ava | AI Lab Notes isn't structured as the "me vs them" dialogue — no Matt response surfaced. | `api-field_notes.json` (`has_matthew_response: false`) | Render: AI Sunday summary → Matt's response, or explicit "pending Matt's response." | M |
| F-10 | /story/ | ia | low | Mara | Story hub carries 7 tabs — tab overload; relieved by F-04 (Coaching out) + F-07 (rename) + F-01 (journal empty). | `story.png` | Subsumed by F-04. | — |

---

## Resonance with Matt's manual notes

The independent Claude Code pass corroborated **all 8** of Matt's notes and added precision the eyeball pass couldn't:
- stale chronicle = *exact* dates (latest 2026-05-03 vs genesis 2026-06-14);
- journal = *count* (7 posts that shouldn't be there);
- podcast = *state* (only Episode 0 exists, likely fail-closed HOLD);
- lab-notes = the enabling data already exists (`has_matthew_response`);
- about = it literally *duplicates* the home hero line.

Plus one additive finding (F-10, tab overload). This is the intended division of labour: Matt's notes carry intent and taste; the harness supplies the receipts and catches the data seams. No cross-page metric disagreements (the Story door is narrative — `consistency.json` checked 0, as expected).
