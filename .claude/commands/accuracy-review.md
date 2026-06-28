Run the **truth audit** of averagejoematt.com — does the data + database + AI prompts materialize into a platform a fresh reader can treat as 100% accurate? This is the editorial/factual/hallucination layer ABOVE the render-only `/qa` sweep and the narrative `/site-review`: it checks that the NUMBERS are true (not just fresh) and that the AI PROSE is grounded (not just well-rendered).

## Arguments: $ARGUMENTS

Parse `$ARGUMENTS` for a mode. Default to `axis-a` (the cheap deterministic pass) if empty; `full` runs the multi-agent sweep.

---

### Mode: `axis-a` (default — deterministic, no agents, ~1 min)
The numbers-are-true pass. Run:
1. `python3 tests/site_review.py` — captures every page's screenshots + prose (`<slug>.txt`) + bound `api/*.json` + `consistency.json` into `qa-screenshots/<date>/`. (Needs `playwright install chromium`.)
2. `python3 tests/accuracy_audit.py` — over that capture: (a) cross-page metric consistency (`site_review_bindings.metric_observations` + `METRIC_TOLERANCE`), (b) API→DDB ground-truth spot-check of the headline RAW numbers (weight/HRV/RHR vs the latest `USER#matthew#SOURCE#*` record, us-west-2), (c) a sentinel/date scan (leaked `undefined`/`NaN`/`[object Object]`, raw ISO timestamps in prose). Writes `<run>/accuracy_audit.json`; exits non-zero on any HIGH finding.

Report the disagreements / divergences / leaks. These are the regressions that ship silently today. NOTE Axis A only validates RAW + cross-page numbers — it cannot catch a *computed* value that is internally consistent but semantically wrong (an impossible weekly rate, a negative CTL). Those need `full`.

---

### Mode: `full` (the multi-agent truth audit — token-heavy, opt-in)
Everything in `axis-a`, then the prose-grounding + fresh-reader sweep. Confirm the user wants the spend before launching.

1. **Capture artifacts + ground truth** (read-only, needs AWS creds):
   - S3 (bucket `matthew-life-platform`): `generated/journal/posts.json` (chronicle), `generated/panelcast/*.transcript.txt` + `episodes.json`, `generated/public_stats.json`.
   - DDB (`life-platform`, us-west-2): board+coach reads (`USER#matthew#SOURCE#ai_analysis`, sk `EXPERT#*`), chronicle (`SOURCE#chronicle`, `DATE#*`), and the RAW source windows (`SOURCE#{whoop,withings,eightsleep,garmin,strava,macrofactor,apple_health,habitify,hevy}`, `DATE#>=…`) — the fact-set the prose must stay inside.
   - Probe the POST AI endpoints live: `/api/ask` and `/api/board_ask` with a few representative questions; save the responses.
2. **Build the surface work-list** (pages from `visual_qa.PAGES` + the AI artifacts/probes), each with its file paths.
3. **Run the workflow** `scratchpad/.../wf_truth_audit.js` (or re-author it): a fan-out of one auditor per surface → adversarial verify of every HIGH/CRITICAL finding → synthesis. Each auditor cross-checks claims/numbers against the data along three axes: (A) numeric accuracy, (B) hallucination/prose-grounding (fabrication, causal-overreach, privacy leak, stale framing), (C) fresh-reader coherence. Privacy rules are absolute: no named vices/genes, no real public figures as coaches, no body-weight in the panelcast.
4. **Write** `docs/reviews/EDITORIAL_ACCURACY_REVIEW_<date>.md` — verified findings (severity, exact quote, contradicting evidence, fix) + a top-line verdict (*does it materialize as a fully-accurate platform?*) + a fix backlog. ~half of raw findings are false positives, so only ship adversarially-verified ones.

---

### Notes
- Read-only review — it surfaces and verifies risks; fixing them is separate work (front-end fixes live in `site/`; number/grounding fixes usually need a `web/` site-api or a prompt change → a deploy).
- The capture + Axis A are re-runnable as an ongoing accuracy regression after any data or prompt change.
- Related: `/qa` (render + freshness), `/site-review` (narrative coherence). This one is **truth**.
