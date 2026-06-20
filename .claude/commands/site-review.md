Run a holistic, human-in-the-loop review of averagejoematt.com — does each page's story land, does the site cohere into one throughline, and does the data corroborate and tell the right story. This is the product/UX/narrative/data layer ABOVE the render-only `/qa` sweep.

## Arguments: $ARGUMENTS

## Before anything: read the rubric
Always read `docs/SITE_REVIEW_METHODOLOGY.md` first — it carries the lenses (the Product Board standing questions), the audience hierarchy, the three-door "what good looks like," the editorial guardrails, and the findings schema. Reproduce its ⚠️ caveat (internal self-assessment, not external validation) at the top of any review doc you write.

Parse `$ARGUMENTS` to pick a mode. Default to `capture` if empty.

---

### Mode: `capture` (default, no args)
1. Run `python3 tests/site_review.py` (add `--door <home|cockpit|story|evidence>` or `--page <path>` to scope; the weekly default is one door). This needs `playwright install chromium`.
2. Report the run folder (`qa-screenshots/<date>/`), the page/PNG/endpoint counts, and **any cross-page consistency disagreements** (these are HIGH data-integrity findings before any visual review even starts).
3. Stop and tell the user they can optionally drop marked-up screenshots into `qa-screenshots/<date>/annotations/` (named `<slug>-<label>.png`) to point at specifics, then run `/site-review review`.

---

### Mode: `review [<date>]` (the main event)
Default `<date>` = the latest folder under `qa-screenshots/`. If no packet exists, run `capture` first.

1. **Load the packet.** Read `qa-screenshots/<date>/manifest.json` and `consistency.json`. Read `docs/SITE_REVIEW_METHODOLOGY.md` and skim `docs/V4_DESIGN_CONSTITUTION_2026_06_01.md` (§0 north star, §1 audience, §3 doors, §7 moat, §11 guardrails).
2. **Scope.** Review one door per invocation for the weekly cadence (`manifest.pages` filtered by `door`); do the full site only for a milestone pass. Walk pages in `narrative_order`.
3. **Per page** (this is where Claude Code's vision matters — actually Read the images):
   - **Read** the `screenshots.full` PNG and the `screenshots.mobile` PNG from the run folder. Read any `annotations/<slug>-*.png` present and treat the user's markup as a directed, **top-priority** finding.
   - Evaluate through the four questions in the methodology doc: (1) what is this page trying to say, for whom, does it land; (2) visual/type/IA; (3) narrative/throughline; (4) data integrity — compare each rendered number on the screenshot against that page's inline `api[].metrics` values in the manifest (and the captured `api/*.json` if you need more), and fold in any `consistency.json` disagreement for that page's metrics.
   - **Emit that page's findings immediately** to the review doc, then carry forward only a one-line story-spine note (not the images) — this keeps the session within context budget.
4. **Story spine.** Maintain a running "after this page, what does the visitor now believe/feel?" line per page. At the end, give a one-line throughline verdict: `COHERES` or `BREAKS AT <page>` with why.
5. **Write** `docs/site-reviews/SITE_REVIEW_<date>.md` using the methodology's findings schema (story spine → throughline verdict → top-10 work order → full findings table). Every finding cites a screenshot and/or `api/*.json` file. Categories: `visual|font|ia|narrative|data`; severity `critical|high|medium|low` (guardrail breach = critical; cross-page data disagreement ≥ high).
6. Read the doc back and present the **top-10 prioritized work order** in chat. Offer to implement the quick wins (S-effort visual/font/data fixes) — but remember the engine and `/api/*` contracts are read-only from the front-end; most fixes live in `site/` (HTML/CSS/JS) or the build scripts, and data-integrity fixes may need a `web/` site-api change (flag those as needing a deploy).

---

### Mode: a page path (e.g. `/now/`, `/evidence/sleep/`)
Single-page deep dive: run `python3 tests/site_review.py --page <path>`, then do the per-page review (step 3 above) for just that page and report findings inline (no full doc unless asked).

---

### Notes
- **Phase 1 is $0** — no Bedrock; Claude Code reads the PNGs itself.
- The binding map (`tests/site_review_bindings.py`) defines which endpoints back which page and which metrics are cross-checked; if a page looks un-corroborated, check that it has a binding entry (the self-check `python3 tests/site_review_bindings.py` asserts coverage).
- Cadence: weekly through the first 3 months, then monthly; rotate doors each week (see methodology §Cadence).
