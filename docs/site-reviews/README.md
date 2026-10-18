# Site Reviews

Holistic, human-in-the-loop reviews of averagejoematt.com produced by the `/review site`
skill. Each file is `SITE_REVIEW_<date>.md` — a story-spine + throughline verdict + a
prioritized work order, graded against `docs/SITE_REVIEW_METHODOLOGY.md`.

These are **internal self-assessments**, not external validation (see the caveat at the
top of each review and in the methodology doc). The screenshot/data packets they're based
on live under `qa-screenshots/<date>/` (gitignored — ephemeral); only the findings persist here.

- Methodology & lenses: `docs/SITE_REVIEW_METHODOLOGY.md`
- Capture tooling: `qa/site_review.py`, `qa/site_review_bindings.py`; the 2026-10-18 pass rendered the kit gate's fixtures (`tests/fixtures/kit_pages_4586`) instead.
- Cadence: event-driven, no clock (the lens runs when the site's story changes — see the methodology's "Cadence & scope").

## Reviews, newest first

| Date | File | Scope | Verdict |
|---|---|---|---|
| 2026-10-18 | [SITE_REVIEW_2026-10-18.md](SITE_REVIEW_2026-10-18.md) · [site_grades_2026-10-18.json](site_grades_2026-10-18.json) | the twelve v8 kit pages (#4580): eight independent graders, two verifiers (144 of 363 findings confirmed), six fix lanes into PR #4988, a fresh pair after | round 1 BREAKS AT day; after round 1 COHERES on the premise and the one number, still breaks at story / coaches / built |
| 2026-06-21 | [SITE_REVIEW_2026-06-21.md](SITE_REVIEW_2026-06-21.md) | v4 full site, all four doors (superseded by the v7/v8 rebuild) | COHERES |
| 2026-06-20 | [SITE_REVIEW_2026-06-20.md](SITE_REVIEW_2026-06-20.md) | v4 Story door | BREAKS |
