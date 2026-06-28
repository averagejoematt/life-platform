# Editorial & Accuracy Review ("Truth Audit") — averagejoematt.com

**Date:** 2026-06-27 · **Method:** 3-axis page-by-page truth audit (`/accuracy-review`), 31 surfaces, 50 agents, adversarially verified · **Capture:** `qa-screenshots/2026-06-27/`

> ⚠️ **This is an internal self-assessment, not external validation.** It checks whether the site's own data, database, and AI prompts cohere into something a fresh reader could take at face value. It does not validate the underlying health science.

---

## Top-line verdict

**The plumbing is trustworthy; the storytelling is not yet 100% accurate.**

The *raw* numbers are faithful end-to-end: every headline figure traces DDB → API → page within tolerance (weight 301 ≈ DDB 300.77, HRV 25.2 ≈ 25.18, RHR exact), cross-page consistency is clean (0 disagreements), and no `undefined`/`NaN` leaks to the UI. A reader can trust that "301 lbs" is really what the scale said.

But a health-literate first-time visitor who treats **every word** as true **would hit contradictions that erode trust**, and a few numbers are **flatly impossible**. The risk is concentrated in two layers the raw-number check can't see:

1. **Computed/derived metrics** (`public_stats.json`) — several values are impossible or mislabeled (a negative "fitness" of −955, a goal date requiring 115 lb of loss in 5 weeks, a "weekly rate" that is really the 14-day total).
2. **AI prose grounding** — coaches, the chronicle, and chart captions assert specific numbers, scenes, and causal reads that don't match the data, and the *same* metric is described **inconsistently across surfaces** (protein target appears as 140 g, 170 g, and 190 g; last night's recovery as both 30% and 86%).

Plus two **privacy** exposures: unpublished chronicle drafts name a real person (Layne Norton) and a vice (marijuana); the live `/api/board_ask` panel presents personas under real public figures' surnames.

**Reassuring counterweight:** none of this is malicious fabrication. The AI's dominant failure mode is *inconsistency and staleness*, not invention — and notably `/api/ask` **refuses to fabricate** (it says "I don't have that data" rather than guessing). The bones are sound; the connective tissue needs a pass.

**Findings:** 77 raw → 19 sent to adversarial verify → **14 upheld** + **1 the verifier wrongly refuted that I re-confirmed by hand** (the 404s) → **15 verified HIGH+ findings**, plus 58 medium/low.

---

## Critical / High (verified)

### C1 — Five `/data/` topic pages 404 on direct load *(broken-state; verifier missed this, hand-confirmed)*
`/data/intelligence/`, `/data/predictions/`, `/data/benchmarks/`, `/data/board/`, `/data/pipeline/` all render the site's **"SIGNAL LOST · 404"** page on a direct visit (verified live; `/data/sleep/` etc. render fine). They are **not** built in `site/data/`, **not** in the sitemap, and **not** linked from the live Data hub — so live-visitor blast radius is **low** (stale inbound/legacy links only). But the v5 IA silently dropped them and **the QA harness still lists them as if they exist** (`visual_qa.EVIDENCE_TOPICS`, `site_review_bindings`), so the harness is testing five non-existent pages and the visual-QA gate passes them because the 404 page itself renders cleanly.
> *Note: the adversarial verifier refuted this finding by reasoning "the API has data, so the page works" — a reasoning error. The rendered page is a 404. This is why top-stakes findings get a human re-check.*
**Fix:** either build/restore the five under `/data/`, or remove them from `visual_qa.EVIDENCE_TOPICS` + `site_review_bindings` + redirects so harness and reality agree.

### C2 — Chronicle drafts name a real person + a vice *(privacy-leak; latent — unpublished)*
The next-to-publish **Week 2 draft** (`SOURCE#chronicle / DATE#2026-06-23`, "Eight Sessions and a Rounding Error", `status=draft`) contains: *"I called **Dr. Layne Norton** about this… 'The training is impressive… some of what's coming off isn't fat.'"* — a real public figure named and given a **fabricated quote**. Two older drafts (`06-02`, `05-19`) name **"marijuana"** explicitly. These are **not live** (drafts only), but the chronicle auto-publishes weekly, so an unguarded publish leaks them. Root cause = stale drafts generated before the `_FALLBACK_ELENA_PROMPT` privacy fix (#215).
**Fix:** purge/regenerate the stored drafts; confirm the publish path can never emit a draft that predates the privacy guard.

### H1 — `/api/board_ask` personas impersonate real public figures *(privacy-leak; LIVE)*
The public panel returns persona keys **`norton`, `clear`, `goggins`, `patrick`** — all surnames of real people — and the prose is unmistakable impersonation (`goggins`: "stay hard… Nobody is coming to save you"; `clear`: Atomic-Habits voice). The privacy rule (fictional coaches only) is breached on a live, unauthenticated endpoint.
**Fix:** rename to the fictional coach roster used elsewhere (Webb, etc.) and strip trademark catchphrases.

### H2 — `public_stats.json` ships impossible computed numbers *(numeric-error; feeds home/cockpit)*
- `ctl_fitness: -955.5`, `atl_fatigue: -955.0`, `tsb_form: -961.5` — CTL/ATL are exponentially-weighted loads and are **mathematically non-negative**; −955 is a computation bug (25 real Strava activities exist in-window, so not a data gap), and TSB=CTL−ATL would be −0.5, not −961.5 (mutually inconsistent too).
- `projected_goal_date: 2026-07-31` — reaching 185 lb (115.8 lb to go) by July 31 is **3.4 lb/day**; physically impossible.
- `weekly_rate_lbs: -13.75` — that is the **entire 14-day loss** mislabeled as a weekly rate (true ≈ 6.9 lb/wk), overstating the pace ~2×.

*Home dodges these by binding the corrected `/api/journey` (`-7.33`, `rate_provisional`, no finish line) — good — but any surface rendering the `public_stats` journey/training block would show them.*
**Fix:** correct the CTL/ATL/TSB and projection/rate computations at the source; make `public_stats` consume the same corrected journey logic Home already uses.

### H3 — Same metric, different night, same label *(coherence; `/data/sleep/`)*
Two "last night" panels both stamped **"THE NIGHT OF JUN 25"** show contradictory numbers — **recovery 30 vs 86**, **HRV 25.2 vs 51.5**, efficiency 72% vs 92% — because one reads `sleep_detail` (Jun-27 latest row) and the other `sleep_reconciliation` (Jun-25 night). A reader sees two irreconcilable "last nights."
**Fix:** align the two panels to the same night, or label each with its actual source/date.

### H4 — Coaches contradict each other on protein *(coherence/factual; board)*
Real value: `avg_protein_g = 140.7`, target `190`. Yet the **Labs** and **Glucose** coaches both narrate "maintaining **170 g** protein daily" as fact, while the **Nutrition** coach (correctly) builds its whole read on protein being **stuck at ~140 g**. Three different protein numbers (140/170/190) across the board the reader is asked to trust.
**Fix:** ground every coach's cited figures to the shared `data_snapshot`; the board synthesis should reconcile, not multiply, the numbers.

---

## Medium — the "fresh-reader confusion" tier (28 findings; representative)

The throughline: **AI prose asserts specifics the data contradicts, and stale copy outlives the data it described.**

- **Cross-day mismatch (recurring):** vitals show recovery **30% (red)** while the narrative blocks insist *"your body is genuinely ready — recovery 86%, HRV 51 ms"* (Jun-27 vitals vs Jun-26 narrative). Same split drives the cockpit, the sleep page, and `/api/ask` saying *"recovery isn't loading"* when it's 30%.
- **Wrong units:** `/coaching/lab-notes/` reports **"HRV 44.7 bpm"** (twice) — HRV is in **ms**; bpm is heart rate. A category error the target (health-literate) audience will catch.
- **Mis-dated / mis-counted scenes:** the Week-2 chronicle dates the eighth session "Sunday" (it was Tuesday); claims protein hit 190 g "twice all week" (logged max 162 g; met **zero** times); "across 17 nights" inside a note framed as one week.
- **Captions fight their own charts:** vitals/physical autonomic captions say *"both lines rising = downshifting into recovery"* on a day the engine flags **low**-recovery and "HRV DOWN"; the physical rate-tempo caption calls the 7-day rate "runs hot" when it's the **slowest** of four windows.
- **Stale-window bars:** physical "30-day" and "90-day" rate bars are **identical** to the 12-day bar — only 13 days of data exist.
- **Contradictory states:** `/story/journal/` says *"Nothing published here yet"* while its feed has 3 posts; protocols labels emerging-evidence (20%) supplements "MODERATE SUPPORT"; the My-Team page says protein is "40% below target" when it's ~18%.
- **Board internal contradictions:** Glucose coach says both "1500-calorie deficit" and "315-calorie daily deficit"; the integrator cites "HRV dropped to 42 yesterday, lowest in your 41-night window" — unsupported by the data.

Full list: 28 medium + 30 low in `qa-screenshots/2026-06-27/` agent transcripts; categories — coherence 31, stale-framing 10, numeric-error 8, broken-state 5, unsupported-claim 3, hallucination 1.

---

## What's sound (the reassuring half)

- **Axis A clean:** page↔API↔DDB raw numbers faithful; 0 cross-page disagreements; 0 sentinel leaks. The data pipeline does not lie about what was measured.
- **Home is honest about uncertainty:** binds the corrected `/api/journey`, shows *"Too early to project… No fake finish line,"* suppresses the bad projection.
- **`/api/ask` fails safe:** it refuses to fabricate, explicitly says "I don't have that data," and volunteers "correlation, never causation." The honest failure mode.
- **Privacy guards mostly hold in published content:** the three *live* chronicle posts are clean; the leaks are in *unpublished* drafts and the *generalist* board_ask (both fixable without touching live narrative).
- **Most data pages render their real numbers correctly** — the failures are in the *interpretive* layer, not the measurement layer.

---

## Prioritized fix backlog

| # | Fix | Layer | Effort |
|---|-----|-------|--------|
| 1 | Purge/regenerate pre-#215 chronicle drafts (Norton, marijuana); block publishing any draft older than the privacy guard | lambda/data | M |
| 2 | Rename `/api/board_ask` personas to fictional roster; strip trademark catchphrases | `web/` site-api | S |
| 3 | Fix `public_stats.json` CTL/ATL/TSB (non-negative), projection, and weekly-rate; reuse the corrected `/api/journey` logic | compute lambda | M |
| 4 | Resolve the five 404'd `/data/` pages — build them or remove from harness + redirects | site build / harness | S–M |
| 5 | Ground coach prose to one shared `data_snapshot` (kills the 140/170/190 protein split and the cross-coach contradictions) | intelligence lambda prompt | M |
| 6 | Align the two `/data/sleep/` "last night" panels to one night/source | `web/` + site | S |
| 7 | Make narrative blocks read the *same* day's vitals the headline shows (kills the 30%-vs-86% split, incl. `/api/ask` context-fetch gap) | compute + `web/` | M |
| 8 | Fix HRV unit (bpm→ms) in field-notes prompt; week-aware "this is week one" disclaimer; stale-window bar labels | prompts + site | S |

**Recommended order:** the two privacy items (1, 2) first — they're the only ones that are *reputationally* dangerous — then the impossible computed numbers (3), then the grounding/coherence batch (5–8), with the 404 cleanup (4) whenever the IA is next touched.

---

## How this was produced (re-runnable)

`tests/site_review.py` captured every page (screenshots + prose `.txt` + bound `api/*.json`); `tests/accuracy_audit.py` ran the deterministic Axis-A pass (cross-page consistency + API→DDB ground truth + sentinel scan); the `truth-audit` workflow fanned one auditor per surface against the raw DDB ground-truth windows, then adversarially verified every HIGH/CRITICAL finding. Re-run after any data/prompt change with `/accuracy-review full`. Fixing the findings is **separate work** — this review only surfaces and verifies them.
