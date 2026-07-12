# Build dispatch checklist (#380, why-it-mattered layer #1120)

Every working session already produces a dense, honest engineering record — the
handover. This checklist distills it into ONE short public beat on the Story
door's **Build log** (`/story/build/`, fed by `site/story/build/beats.json`).
The beat is written by the session itself at wrap time — no new AI
infrastructure, no extra performance from Matthew.

## When to write one

At session close, **after** the wrap's verification step — and only when the
session's work is **merged to main AND deployed**. A PR that's open, a deploy
that's staged, a plan for next session: none of that is a beat. **If it isn't
merged and live, it doesn't exist here.**

**The gate is beat-or-explicit-skip, never silence (#736).** If the session
shipped nothing eligible, the wrap's handover records
`**Build beat:** none — <one-clause reason>` instead. An empty week is honest;
an unexplained empty slot is not — the skip line is what keeps the cadence
auditable across `handovers/`.

## The template (four sections, ~60–120 words each)

Append one object to `beats` in `site/story/build/beats.json`:

```json
{
  "id": "YYYY-MM-DD-short-slug",
  "date": "YYYY-MM-DD",
  "title": "A reader-facing title — the change, not the ticket",
  "shipped": "WHAT SHIPPED — the user-visible or platform-visible change, in plain language. Past tense, merged work only.",
  "why_it_mattered": "WHY IT MATTERED — the stakes: what this bought the experiment, the reader, or the platform's credibility, and what it cost while it was broken/absent. Significance, never fabricated outcomes (#1120).",
  "gotcha": "THE GOTCHA — the thing that bit during the work; the surprise a fellow builder would want to know. One honest paragraph.",
  "honest_miss": "THE HONEST MISS — what didn't work, was cut, remains open, or got measured and found wanting. Never omit this to look good; it's the differentiator.",
  "prs": [{ "label": "PR #NN", "url": "https://github.com/averagejoematt/life-platform/pull/NN" }]
}
```

All four prose sections are REQUIRED — `scripts/validate_beats.py` (wired into
`/wrap`) and `tests/test_build_dispatches.py` both reject a beat missing any of
them, so an entry structurally can't ship changelog-grade (#1120).

Distill from `handovers/HANDOVER_LATEST.md` — the shipped line, the gotchas
section, and the residuals are the raw material. Write for the reader, not the
operator: no internal codenames without a gloss, no file paths unless they're
the story.

**Writing `why_it_mattered`:** it answers "so what?" for a reader who doesn't
live in this codebase — what the change bought (trust, a closed failure mode,
a claim made checkable) and what it cost while broken or absent. Ground it in
the same shipped facts the other sections narrate. It may interpret stakes; it
may NOT invent outcomes: no reader reactions, no traffic effects, no "this
improved X" without a measurement to cite. The honest tense for impact that
hasn't been observed is future-conditional or plain stakes ("a reader who
catches one inflated label discounts every label after it"), never reported
fact.

## Hard rules (in order)

1. **Merged + deployed only.** No forward-looking claims presented as done.
   Verify: the PRs linked are merged, `main == live` for the touched surfaces.
2. **Content gates run on everything published.** The beat lives in `site/`,
   so CI's content-policy gate (`scripts/content_policy_scan.py`, #354) scans
   it on every push — but run it locally before committing:
   `python3 scripts/content_policy_scan.py`. The standing rules apply: no
   blocked vice terms, no banned real names, no genome identifiers, no private
   data (see `lambdas/privacy_guard.py` for the authoritative lists).
3. **Numbers must be real.** Any figure in a beat must come from the handover /
   PR / measured output it narrates — the same honest-numbers bar as the rest
   of the platform (ADR-104).
4. **One beat per session, max.** If a session shipped three things, the beat
   picks the story, and mentions the rest in a clause.

## Publish

The beat rides the session's own PR (it's a `site/` file — normal review +
CI). It reaches production with the next `bash deploy/sync_site_to_s3.sh`.
No extra invalidation needed beyond what the sync already does.
