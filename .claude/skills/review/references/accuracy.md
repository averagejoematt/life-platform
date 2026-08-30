# Rubric — `/review accuracy`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **modes, the ground-truth sources, the artifact filenames and the bar** for the truth
audit.

**Clock:** the `accuracy-full` entry in `scripts/operating_calendar.py` (monthly + grace) — and
that clock is satisfied by the `full` mode's artifact only, not by the cheap deterministic pass.

## What this lens grades

Does the data + database + AI prompts materialize into a platform a fresh reader can treat as 100%
accurate? This is the editorial/factual/hallucination layer ABOVE the render-only `/qa` sweep and
above `/review site`'s narrative pass: it checks that the NUMBERS are true (not just fresh) and
that the AI PROSE is grounded (not just well-rendered).

Parse the rest of `$ARGUMENTS` for a mode. Default to `axis-a` if empty; `full` runs the
multi-agent sweep and is the one the calendar reads.

## Mode: `axis-a` (deterministic, no agents, ~1 min)

The numbers-are-true pass:

1. `python3 tests/site_review.py` — captures every page's screenshots + prose (`<slug>.txt`) +
   bound `api/*.json` + `consistency.json` into `qa-screenshots/<date>/`. (Needs
   `playwright install chromium`.)
2. `python3 tests/accuracy_audit.py` — over that capture: (a) cross-page metric consistency
   (`site_review_bindings.metric_observations` + `METRIC_TOLERANCE`), (b) API→DDB ground-truth
   spot-check of the headline RAW numbers (weight/HRV/RHR vs the latest `USER#matthew#SOURCE#*`
   record, us-west-2), (c) a sentinel/date scan (leaked `undefined`/`NaN`/`[object Object]`, raw
   ISO timestamps in prose). Writes `<run>/accuracy_audit.json`; exits non-zero on any HIGH finding.

Report the disagreements / divergences / leaks — these are the regressions that ship silently
today. **Axis A only validates RAW + cross-page numbers.** It cannot catch a *computed* value that
is internally consistent but semantically wrong (an impossible weekly rate, a negative CTL). Those
need `full`. **An `axis-a` run does not advance the calendar clock**, and saying it did would be
exactly the anchored-not-run lie the calendar exists to kill.

## Mode: `full` (the multi-agent truth audit — token-heavy, opt-in)

Everything in `axis-a`, then the prose-grounding + fresh-reader sweep. Confirm the user wants the
spend before launching.

1. **Capture artifacts + ground truth** (read-only, needs AWS creds):
   - S3 (bucket `matthew-life-platform`): `generated/journal/posts.json` (chronicle),
     `generated/panelcast/*.transcript.txt` + `episodes.json`, `generated/public_stats.json`.
   - DDB (`life-platform`, us-west-2): board + coach reads (`USER#matthew#SOURCE#ai_analysis`, sk
     `EXPERT#*`), chronicle (`SOURCE#chronicle`, `DATE#*`), and the RAW source windows
     (`SOURCE#{whoop,withings,eightsleep,garmin,strava,macrofactor,apple_health,habitify,hevy}`,
     `DATE#>=…`) — the fact-set the prose must stay inside.
   - Probe the POST AI endpoints live: `/api/ask` and `/api/board_ask` with a few representative
     questions; save the responses.
2. **Build the surface work-list** — pages from `visual_qa.PAGES` plus the AI artifacts and probes,
   each with its file paths.
3. **Fan out one auditor per surface** (spine Phase 1), then verify every HIGH/CRITICAL finding
   adversarially (spine Phase 2), then synthesize. Each auditor cross-checks claims and numbers
   against the captured data along three axes: (A) numeric accuracy, (B) hallucination /
   prose-grounding (fabrication, causal overreach, privacy leak, stale framing), (C) fresh-reader
   coherence. **Privacy rules are absolute:** no named vices or genes, no real public figures as
   coaches, no body-weight in the panelcast.

## Artifacts

`docs/reviews/EDITORIAL_ACCURACY_REVIEW_<date>.md` — verified findings (severity, exact quote,
contradicting evidence, fix) + a top-line verdict (*does it materialize as a fully-accurate
platform?*) + a fix backlog. This filename is what the `accuracy-full` dead-man probes. About half
of raw findings are false positives, so only adversarially-verified ones ship.

## Notes

- Read-only review — it surfaces and verifies risks; fixing them is separate work. Front-end fixes
  live in `site/`; number and grounding fixes usually need a `lambdas/web/` site-api or a prompt
  change, which means a deploy. Flag those.
- The capture + Axis A are re-runnable as an ongoing accuracy regression after any data or prompt
  change.
- Related: `/qa` (render + freshness), `/review site` (narrative coherence). This one is **truth**.

## The bar

A `/review accuracy` succeeds when, on top of the spine's bar: every published number in the
audited surface either reconciles against its ground-truth record or is named as a divergence with
its magnitude, and every AI narrative claim is traced to the data that licenses it — or reported as
ungrounded, with the quote.
