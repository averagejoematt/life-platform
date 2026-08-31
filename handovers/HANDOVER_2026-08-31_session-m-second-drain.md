# Handover — 2026-08-31 (FABLE 5): Session M — the second drain, 13 closed, one P1 I caused

**Session:** Claude Fable 5, owner co-working from mobile, Fable orchestrating Opus/Sonnet
worktree lanes capped at 3–4 per wave (Session L's eight hit the monthly spend limit). Started
2026-08-31 ~01:15Z, wrapped ~06:30Z.

## The ask and the honest count

Owner: "same brief as last session — close as many issues as possible, Fable orchestrating,
without risking quality — cap concurrency at 3–4 lanes, check headroom before each wave." Order:
#3336 → PR #3335 (R1–R5+N1–N3) → un-swallow #3341/#3339 → #2848 cold-read proof → #3277 →
epic #2799 audit → boot hygiene. Then "if there's more we can squeeze in pre-wrap, let's do it."

**Closed 13:** #2848 (cold-read proof, 8/8) · #3336 (PR #3338) · #3318 (PR #3341) · #3325
(PR #3342) · #3337 (PR #3343) · #3315 (PR #3339) · #2834 (PR #3335) · #3277 (PR #3344) · #3324
(PR #3347) · #3329 (option B, PR #3348) · **epics #2842 (Kernel) and #2800 (calendar)** on their
Outcomes · plus #3340 re-homed to #3042. Working set **18 → 9** (4 epics, 5 owner-gated/blocked
stories). **Filed 3** (#3352 carrier for #2799's rollback-scope tail; #3353, #3354 from residuals
the closure sweep would not let me leave homeless). **14 PRs merged**, every one with a green-by-name
verdict + closing-set check; every closure has `**Shipped:**` + `**Outcome:**` with live evidence.

## What shipped (all merged AND deployed/verified by content)

- **#3336 / PR #3338** — `setup_remediation_role.sh` + `setup_github_oidc.sh` apply `infra/iam/*.json`
  verbatim (0 inline policy text); `tests/test_iam_twin_free_3336.py` entered the census PROVEN
  (MutationSpec, ARMED 1/1); `verify_oidc_iam.py --strict` CLEAN live.
- **#2834 / PR #3335** — the CISO review's R1–R5 + N1–N3 all landed (value-aware Code tolerance,
  S3 deletes refused on the bucket policy's Deny prefixes + replica dropped, control-plane actions
  forbidden, human-visible ALLOW record, ADR-anchored baselines, stack-name validation, steps
  reordered, wildcards an explicit decision); deploy role gained no permission; `guard::deploy/
  iam_additive_gate.py` proven. Owner-flagged residual: prefix-scoped PUTs on `site/*`/
  `remediation-log/*`/`raw/*` remain admitted (`S3_MUTABLE_BY_CI_TODAY`) — one Deny line flips them.
- **#3318 / PR #3341** — the closure contract (registry + detectors A/B, seamed into
  `wait_pr_green.sh`; `warn` posture). It caught my own three closing comments the same night.
- **#3315 / PR #3339** — the CI dark-flag sweep; live on main: 39 jobs / 261 steps / 0 violations.
- **#3337 / PR #3343** — reader-truth rulings decide on structure (13/13; 0 lexical); found and fixed
  `today_iso=None` on every production run since #2959; deployed to `qa-smoke` via the gated tip run
  (verified by bundle content: `reader_truth_evidence.py` + `phase["today"]`).
- **#3277 / PR #3344** — axe at 390px in the gating sweep, mobile ledgers, `role="group"` scroll
  regions; live re-measure **0/0 nodes across 15 pages × chromium+webkit**; webkit lane surfaces via
  the #1447 filer (dead SNS step deleted).
- **#3324 / PR #3347** — nullable-aware `diff_shape`, whole-value leak anchor, dated recapture; live
  `--check-drift` on main: **0 breaking, 0 leaks**.
- **#3329 / PR #3348** — the 6 unprovable gates are counted `not-applicable` verdicts with reasons;
  `BASELINE_UNPROVEN_GATES` is DOWN-ONLY; #2578 box 2 amended (owner: option B).
- **#3325 / PR #3342** + **PR #3350** — two data-driven contrast defects (FDR-flagged rows; paused
  supplement cards) fixed at the token level; both live.
- **PR #3345** — the #2799 folded-items pass: 6 of 7 already fixed by children, 3 false
  compensating-control claims corrected, visual-qa's dead SNS notifier deleted.
- **PR #3346** — `docs/OPERATOR_GUIDE.md`'s measured weekly operator touch (#2800's last item).
- **PR #3349 + PR #3351** — the site sync uploads hashed assets first and HTML last (the 7-second
  asset race behind 43 false reds), and the Data-JSON sync excludes `*.html` (see Incidents).

## Incidents (both rows in `docs/INCIDENT_LOG.md`)

1. **P3 — the asset race:** the #3277 deploy uploaded HTML 7 s before the hashed JS it referenced;
   the edge cached a 404; ci-cd's un-raced visual QA read 43 pages red. Root-caused from the deploy
   log timestamps; fixed structurally (#3349) with a mutation-proven order guard.
2. **P1 — self-inflicted, ~22 min:** that reorder put the Data-JSON sync (stamps
   `application/json`, no html exclude) ahead of the HTML sync; it also covered
   `site/data/**/index.html`, so the whole `/data/*` door served JSON. The gate caught it; the
   auto-rollback **re-ran the same script and re-broke it identically**, then reported success.
   Restored by an in-place `aws s3 cp --metadata-directive REPLACE` + `/data/*` invalidation; fixed
   in #3351; the next site deploy (manual dispatch, `3baa9c3`) verified the order
   (Hashed → Data JSON → HTML) and every door `text/html`. Lesson homed in CONVENTIONS §7 + memory.

## Verification state
- Every lease disposed: approved the tips (`53511af98`, `6badbea56`, `253bc2a3e`, `f45ad6db6`),
  rejected 9 ancestors by name; two runs cancelled by concurrency; `bbd19b112` had no deploy job.
- Live: site build `3baa9c3` (05:40Z), `qa-smoke` bundle carries #3337, `verify_oidc_iam --strict`
  CLEAN, `--check-drift` 0/0, dark-flag sweep 0, census 584 → 587 on main with the not-applicable
  partition printing.
- Governor at boot: **tier 2** (mtd $176.64 / $200 August ceiling, drift 1.21x); reverts to the
  $215 base at 00:00Z 09-01 → reads tier 1. The 08:00Z cycle was not read (wrapped before it).

## Gotchas (durable ones → memory + CONVENTIONS §7)
- **Stacked census PRs**: rebase each onto the previous PR's tip (+1 each), run CI concurrently, merge
  in order — and re-rebase the rest after EACH squash (GitHub reports CONFLICTING; the rebase is clean).
- **`gh run list --jq` does not take `--arg`**, and the system bash is 3.2 (no `declare -A`) — two
  of my watcher scripts died silently and produced phantom "no run minted" events. The fixed
  watcher is `scratchpad/watch_runs.sh`-shaped: inline the jq string, no associative arrays,
  require 3 consecutive empty reads before calling a swallow.
- **A resolver whose assert fails must not be chained to `git rebase --continue`** — twice I
  committed conflict markers that way; the census then "lost" two registry ids. Resolve, `ast.parse`,
  THEN continue.
- **Local axe is blind to `color-mix()` contrast** (0 locally, 16 in CI) — prove by arithmetic.
- **Reordering sync steps changes ownership** — see Incident 2.

## Residual / next picks
- **#2799** stays open on its honest tail: #3352 (rollback scope-check + `/api/ai_analysis`
  `content_as_of`) and #3353 (WebKit 32767px screenshot cap) — both filed tonight.
- **#2578**: box 2 re-scoped (owner B); the installed base shrinks opportunistically — #3354 is its
  newest child. #3040-class hygiene is done.
- **#3042** (A-Grade): NOT closeable — the 08-29 re-grade's external ≥9/10 box; #3340 now lives here.
- **Owner-gated, unchanged:** #3340 (cfn-exec boundary — an owner-run re-bootstrap), #2883 (soak;
  n=30 bar decision), #2978 (30-day re-measure due ~2026-09-2x; two shape-(a)-class datums added
  tonight), #1407 Roadmap product pick (see Backlog).
- **Time-gated boot hygiene, not done this session:** governor 08:00Z cycle read (#2883 soak) ·
  Monday 14:45Z remediation run ends at "Run remediation agent" with a CallerClass=remediation
  datapoint (#3308 verification) · prune the `qa-smoke-failures` registry entry after 14:06Z if
  still OK (not-work — registry hygiene per its own dated note) · the `qa-smoke-warnings` alarm is
  now a self-clearing scale-gap state (re-cited, expiry 09-03 wrap).
- **BotFather for #2363** — not-work — owner action, 10 minutes.
- **09-08 Architect ritual runs ITSELF** — not-work — scheduled machinery (#2849 reopen trigger).
- **Main's last completed run reads red** on the incident-window visual-QA job; the approved
  `f45ad6db6` run is the green proof in flight — not-work — check its result at next boot.

## Gate lines
**Build beat:** 2026-08-31-thirteen-closed-and-the-door-i-broke
**Docs:** docs/CONVENTIONS.md §7 (+3 gotchas), docs/OPERATING_KNOWLEDGE_LEDGER.md (+3 rows, snapshot 377), docs/alarm_citations.json (qa-smoke-warnings re-cited to its self-clearing data cause), docs/INCIDENT_LOG.md (+2 rows via PRs #3349/#3351), docs/OPERATOR_GUIDE.md (PR #3346), docs/DECISIONS.md ADR-065 amendment (PR #3335), docs/PROPORTIONALITY.md (PRs #3341/#3348), docs/OPERATING_DISCIPLINE.md untouched
**Decisions:** none needed — governance landed as dated ADR amendments in the merged PRs (ADR-065 2026-08-30 via #3335); the #3329 option-B and #2842 close decisions are recorded on-issue and in #2578's amended box 2
**Main:** red — the latest completed run (253bc2a3e) failed only its Visual + AI-vision QA job, on 9 /data pages probed inside the 2026-08-31 P1 JSON-door window (INCIDENT_LOG row); its Deploy + smoke succeeded; the tip run f45ad6db6 is approved and in flight as the green proof
**Incidents:** 2 rows added — the 7-second asset race (P3, 43 false reds, fixed #3349) and the /data door served as JSON for ~22 min (P1, self-inflicted, rollback re-ran the defect, fixed #3351)
**Stash/hooks:** clean
**Closures:** #2848, #3336, #3318, #3325, #3337, #3315, #2834, #3277, #3324, #3329, #2842, #2800 commented (Shipped + Outcome, live evidence on each); #3251, #3314, #3317, #3327 (Session L's, same UTC day) given the `**Outcome:**` marker over their existing verdicts · DoD: scanned 16, hits 2 — #3317 post-close-comment = Session L's own verdict posted +18m, benign; #3318 post-close-assertion = the closing comment quotes the sweep's own output containing "REOPENED", lexical not an assertion; #2848 dispositioned in the registry
**Backlog:** Now 2 actionable (filed #3353, #3354 — lever 1 of the refill plan, both evidence-backed from tonight's residuals); NO REMEDY IN THE CORPUS for the third — the sanctioned walk's only pick is the Roadmap product pick #1407 (Monarch, ADR-099 ¶3 one-per-cycle), which is the owner's call, asked and not taken tonight; Later sweep — no stale Later issues printed
**Alarms:** 4 red >72h, all cited — qa-smoke-warnings re-cited from closed #3337 to its self-clearing data cause (Withings scale gap, expiry 09-03 wrap); ai-tokens-platform-daily-total, compute-pipeline-stale, cost-metric-drift-sustained carry their standing citations
**CI warnings:** none to triage — the latest completed main run is not green (incident-window visual QA, decoded on the Main line), so the warning triage keys on the last green run (bbd19b112, Deploy skipped) — no warning annotations there
**Ledger:** rows added via the merged PRs — closure contract (#3341), gate-census posture (B) (#3348), additive-IAM gate (#3335); the two sync-script guards ride the existing site-deploy row
