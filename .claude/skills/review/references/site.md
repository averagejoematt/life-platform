# Rubric — `/review site`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **modes, the per-page procedure, the artifact filenames and the bar** for the site's
editorial review.

**No clock — and that is a decision, not a lapse.** `scripts/operating_calendar.py` carries a dated
exemption for this lens: an owner-attended editorial walkthrough runs when the site's story changes
(a redesign, a new door), not on a schedule. Cadencing an editorial judgment manufactures runs with
nothing to judge; `/review accuracy` owns the site's monthly truth pass. Revive it onto the
calendar deliberately, with its own entry, if that stops being true.

## What this lens grades

Does each page's story land, does the site cohere into one throughline, and does the data
corroborate and tell the right story. This is the product / UX / narrative / data layer ABOVE the
render-only `/qa` sweep and beside `/review accuracy`'s numeric truth pass.

## Before anything: read the rubric source

Read `docs/SITE_REVIEW_METHODOLOGY.md` first — it carries the lenses (the Product Board standing
questions), the audience hierarchy, the three-door "what good looks like", the editorial guardrails
and the findings schema. Reproduce its ⚠️ caveat (internal self-assessment, not external
validation) at the top of any review doc you write.

Parse the rest of `$ARGUMENTS` for a mode. Default to `capture` if empty.

## Mode: `capture` (default)

1. Run `python3 tests/site_review.py` (add `--door <home|cockpit|story|evidence>` or
   `--page <path>` to scope; the default is one door). Needs `playwright install chromium`.
2. Report the run folder (`qa-screenshots/<date>/`), the page/PNG/endpoint counts, and **any
   cross-page consistency disagreements** — these are HIGH data-integrity findings before any
   visual review even starts.
3. Stop and tell the user they can optionally drop marked-up screenshots into
   `qa-screenshots/<date>/annotations/` (named `<slug>-<label>.png`) to point at specifics, then
   run `/review site review`.

## Mode: `review [<date>]` (the main event)

Default `<date>` = the latest folder under `qa-screenshots/`. If no packet exists, run `capture`
first.

1. **Load the packet.** Read `qa-screenshots/<date>/manifest.json` and `consistency.json`. Read
   `docs/SITE_REVIEW_METHODOLOGY.md` and skim
   `docs/archive/V4_DESIGN_CONSTITUTION_2026_06_01.md` (§0 north star, §1 audience, §3 doors,
   §7 moat, §11 guardrails).
2. **Scope.** One door per invocation for the routine pass (`manifest.pages` filtered by `door`);
   the full site only for a milestone pass. Walk pages in `narrative_order`.
3. **Per page** — this is where the session's vision matters, so actually Read the images:
   - Read the `screenshots.full` PNG and the `screenshots.mobile` PNG from the run folder. Read any
     `annotations/<slug>-*.png` present and treat the user's markup as a directed, **top-priority**
     finding.
   - Evaluate through the four questions in the methodology doc: (1) what is this page trying to
     say, for whom, does it land; (2) visual/type/IA; (3) narrative/throughline; (4) data integrity
     — compare each rendered number on the screenshot against that page's inline `api[].metrics`
     values in the manifest (and the captured `api/*.json` if you need more), and fold in any
     `consistency.json` disagreement for that page's metrics.
   - **Emit that page's findings immediately** to the review doc, then carry forward only a one-line
     story-spine note (not the images) — this keeps the session within context budget.
4. **Story spine.** Maintain a running "after this page, what does the visitor now believe/feel?"
   line per page. At the end, give a one-line throughline verdict: `COHERES` or
   `BREAKS AT <page>` with why.
5. **Write** `docs/site-reviews/SITE_REVIEW_<date>.md` using the methodology's findings schema
   (story spine → throughline verdict → top-10 work order → full findings table). Every finding
   cites a screenshot and/or `api/*.json` file. Categories: `visual|font|ia|narrative|data`;
   severity `critical|high|medium|low` (guardrail breach = critical; cross-page data disagreement
   ≥ high).
6. Read the doc back and present the **top-10 prioritized work order** in chat. Offer to implement
   the quick wins (S-effort visual/font/data fixes) — but the engine and `/api/*` contracts are
   read-only from the front-end; most fixes live in `site/` (HTML/CSS/JS) or the build scripts, and
   data-integrity fixes may need a `lambdas/web/` site-api change. Flag those as needing a deploy.

## Mode: a page path (e.g. `/cockpit/`, `/data/sleep/`)

Single-page deep dive: run `python3 tests/site_review.py --page <path>`, then do the per-page review
(step 3 above) for just that page and report findings inline (no full doc unless asked).

## Notes

- **The capture phase is $0** — no Bedrock; the session reads the PNGs itself.
- The binding map (`tests/site_review_bindings.py`) defines which endpoints back which page and
  which metrics are cross-checked; if a page looks un-corroborated, check that it has a binding
  entry (the self-check `python3 tests/site_review_bindings.py` asserts coverage).
- **Site shells are generator output.** If a page has a matching `scripts/v4_build_*.py`, a finding
  whose fix is an HTML-only edit is mis-scoped — name the generator.

## The bar

A `/review site` succeeds when, on top of the spine's bar: every page reviewed has an explicit
"what does the visitor now believe" line, the throughline verdict is stated as `COHERES` or
`BREAKS AT <page>`, and every data finding cites the captured artifact it disagrees with.
