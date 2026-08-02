# HANDOVER — The Mirror ships, the funnel unbreaks — 2026-08-02 (overnight)

> Instruction thread: unattended overnight, my recommendation accepted by default — warm-up on
> the funnel cluster (#1952–#1955, fanned to 4 worktree implementers), flagship = **The Mirror
> (#1392)** with delegated design latitude. Hard limits held: no emails, no social, no DDB
> mutations, no reset, no ceiling change, nothing `gate:owner`. Session interrupted ~9h by
> laptop sleep (06:50→16:00Z), resumed clean.

## The headline: The Mirror is live

**`/method/mirror/` — a reader drops their Whoop CSV export and gets scored in their own browser
by the deployed instruments, overlaid on the published year.** PR **#2015**, merged, auto-deployed
(site-deploy green: smoke + visual QA, no rollback), then **live-verified by real execution**:
demo scores render on production, and the network audit measured **zero non-GET requests, zero
request bodies — the only data request is the static `mirror_distributions.json`**.

What makes it the platform's, not just a feature:

- **Parity is enforced, not asserted.** 131 test vectors generated FROM the deployed Python
  (`scripts/gen_mirror_vectors.py`) pin `mirror-core.js` to exact equality (banker's rounding via
  the shared `pyRound`) — `tests/test_mirror_parity.py` + `tests/js/mirror_core.test.mjs`.
  Negative-tested three ways (doctored weight / rogue fetch / stale vector — each fires).
- **The privacy control is the absence of code.** No upload endpoint exists; a structural test
  pins the module graph to exactly one `fetch(DIST_URL)` and zero XHR/beacon/WS/EventSource.
- **ADR-104/105 applied to the reader:** TSB absent-not-zero with the renormalisation said out
  loud; their own HRV band derives from their distribution past the same MIN_N=30 floor-guard,
  labelled population-fallback below it. HRV comparability disclosed (Whoop RMSSD; Apple SDNN is
  why v1 is Whoop-only).
- **`site/data/mirror_distributions.json`** — full sorted daily samples (exact midrank
  percentiles), six already-public metrics, n=341/359, window stamped. A test pins the metric
  set: a seventh metric is a PRE-13-class publication decision, not a code change.

**The near-miss that became a feature:** `/method/mirror/` already existed — the old
type-three-numbers evidence widget — and my builder **silently clobbered it** (caught by
qa_manifest's duplicate gate, memory rule filed). Resolution: the new page replaces it at the
same URL, keeps the zero-friction rung (type-a-number now compares against the 341-day year, not
the old 7-day window), and a new **`"external"` registry flag** lets a curated page keep its
archive-nav tile without the evidence build ever overwriting it (evidence.js follows the link
for real; `renderMirror` + the `/api/pulse_history` binding removed).

Render-QA earned its keep: two real findings (a `display:inline` label overpainting its
instructions 21px; a degenerate demo walk marching resting HR to 13 bpm) — both fixed and
re-verified before merge.

## The funnel wave — all four merged via /reconcile-branch, literals regenerated per merge

| # | what | PR | deploy state |
|---|---|---|---|
| #1953 | qa-smoke distinguishes dark-during-live-cycle (WARN→FAIL ≥2d, `qa_predict_dark` streak row) | **#2011** | **deployed** 16:23Z, bytes verified — IAM PutItem grant still pending (fail-soft WARN until CDK deploy) |
| #1954 | Monday digest subscriber-funnel section + canary zero-residue assertion | **#2012** | merged; code+IAM ride the CDK deploy |
| #1955 | one PT day-frame (`common/pacific_time.py`) for share card + vitals | **#2013** | site-api **deployed + live-verified** ("Day 7" PT-correct); og tags bake on next proof-builder run |
| #1952 | seeder stamps the GENESIS ISO week; restart-verify asserts the hook live | **#2014** | merged; deploy-tools only |

Full suite green after the wave (**8,486 passed**) and again on the Mirror tree (**8,490**, +
185 JS). The only deselect both times: the documented `i16` live-data flake (only Withings fresh
— Whoop dark, #1934).

**#2010 progress:** qa-smoke's stranded gates (`phase_plausibility`, `qa_check_reader_truth`)
are **deployed and byte-verified**; site-api deployed. Still stranded: the email/compute-side
gates (#1896/#1897) behind the Plan red below.

## Blocked on you — the numbered ask (batched per convention)

1. **`bash deploy/cdk_deploy.sh LifePlatformOperational -- --require-approval never`** — the
   classifier only clears CDK deploys on your in-the-moment ask (memory rule confirmed tonight).
   Ships the #2011/#2012 IAM grants + digest/canary code, and **un-reds every ci-cd Plan**
   (R8-ST6 currently fails every push on main — 5 runs tonight, all only-Plan-red).
2. Then **`deploy_all=true` dispatch + approve** — ships the #1896/#1897 fleet gates (#2010).
3. **The stray canary row delete** — command in PR #2012's body, discovery query in its comments
   (I held the no-DDB-mutations line; the new canary assertion will loudly flag the row until
   deleted).
4. **PR #2012 revision-history purge** — a subagent pasted the subscriber row's hashed key into
   the public PR body; I redacted it, but GitHub keeps public edit history (PR → "edited"
   dropdown → delete revision). Incident row filed; memory rule written so implementer briefs
   demand discovery-queries, not concrete keys.
5. **#1934 Whoop OAuth** (`python3 setup/setup_whoop_auth.py --backfill`) — dark since 08-01
   12:00Z, gap now ~2 days, feeds readiness/brief/vitals **and the new Mirror's freshest
   comparison data**.
6. Standing from the prior wrap, still yours: PRE-13 (genome/per-variant publication — the
   Mirror's distribution artifact is deliberately scope-pinned to the six long-public metrics),
   #1927 ceiling number, growth-1/#1951 subscriber kill-switch, #1940 public correction.

## Gotchas hit

- **The classifier is not overridable by standing authority** — the CDK deploy block held even
  with the handover's explicit grant; the memory rule ("clears only when Matthew asks in the
  moment") is exactly right. Plan accordingly: IAM-touching merges in an unattended session
  strand the CI deploy path until the owner's next touch.
- **Check the URL before building a page** — the flagship nearly shipped by silently destroying
  an existing reader feature. `git ls-files site/<path>` + a REGISTRY grep first, always
  (memory: `reference_check_existing_page_before_building`).
- **A `<label>` computes `display:inline`** — vertical padding takes no layout space and the
  box overpaints the paragraph above; render-QA's screenshot pass caught what 34 DOM checks
  missed. Also: seedless demo data needs its arithmetic checked (`(i*3)%3` is always 0).
- **A 9-hour laptop sleep mid-deploy** produced an `InvalidSignatureException` clock-skew
  failure on the settle-waiter — the code update itself had already succeeded (CodeSha256
  printed); verify function state before re-running, don't re-deploy on reflex.

## Verified

- 8,490 tests + 185 JS on the final tree; doc-sync truth-gate green after every merge in the
  wave; every new guard negative-tested by breaking the fix.
- Deployed bytes read back (qa-smoke gate modules; site-api PT frame) rather than run
  conclusions; The Mirror executed on production with a full network capture.

**Main:** red — only the Plan job (R8-ST6 IAM-review, by design) on every run since #2011
merged; lint/tests/deploy-critical all green; clears with ask #1.
**Build beat:** 2026-08-02-the-mirror.
**Docs:** SITE_MAP_AND_INTENT (Mirror entry + external flag), INCIDENT_LOG (+1 row);
SCHEMA/qa rows landed in the PRs themselves.
**Decisions:** none needed — the "external" registry flag is an implementation pattern
documented in-code + SITE_MAP_AND_INTENT; no governance posture changed.
**Incidents:** 1 row added — subscriber-key paste into public PR #2012 (redacted; purge is ask #4).
**Closures:** #1952 #1953 #1954 #1955 #1392 commented; backfilled #1931 #1922 #1897 #1893 #1892
from the delta session (uncommented at its close).
**Stash/hooks:** clean (empty stash; hook 🟢).
**Backlog:** Now live at 5 (top actionable #1989, #1896-remainder); no stale Later issues;
hygiene 0 violations / 2 pre-existing advisories (#1677/#1679 class).

## Residual / next picks

1. **Watch tonight's qa-smoke** (22:30Z): expect a truthful WARN on the dark predict widget
   (day 1 of the new check's streak; FAIL at day 2) — that is #1953 working, not a regression
   (`not-work — expected-alarm note, no action unless it fires on something else`).
2. **#1989** — cockpit scope-button contrast (top-ranked actionable Now story).
3. **#1896 remainder** — the DDB remediation half (tombstones + false THREAD row) stayed
   deliberately unshipped (owner-adjacent DDB mutations).
4. **#1937** — the ~13 remaining UTC anchors in vitals; #2013 carried the cross-reference.
5. **#1946-class data-1** — countdown-gap rows in coach reads (from the delta review's queue).
6. Mirror follow-ons worth filing only if Matthew wants them: ZIP ingestion + Apple Health
   (SDNN-aware) — recorded in PR #2015's decision notes (`not-work — awaiting owner interest,
   scope decision recorded in the PR`).
