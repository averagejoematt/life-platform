# Handover — 2026-08-22 ~15:45 → ~17:15 PT: max opus paydown — and every closure I tried to make honest found a defect underneath it

**Session:** Opus 5, interactive, with merge + deploy authority granted twice. The driving
instruction was *"max pay down of opus issues without shortcutting on quality"*, against a plan
I presented and Matthew approved as-is. Previous wrap archived as
`HANDOVER_2026-08-22_machinery-first.md`.

**The plan's premise was right and its cost estimate was wrong.** 30 open `model:opus` issues
decomposed cleanly: 7 epics, 6 not session-startable (`gate:owner` / `blocked:dep`), 17
startable — and **7 of those 17 were one cluster**, the cost epic #2801. Lane 0 was budgeted as
"verification work, no new code": three issues sitting at the finish line. It produced **three
live defects instead**, consumed most of the session, and never reached #2892 or #2888. That is
the honest trade — three shipped-and-verified fixes plus two epics' worth of acceptance
verification, instead of four cost stories touched and none proven.

**Build beat:** none — nothing reader-visible shipped. The four merges are an ingestion request
fix, a wrap-gate check, an AI cost seam and a SCHEMA correction; `docs/content/BUILD_DISPATCH_CHECKLIST.md`
wants reader-facing work, and the one reader-facing thing in play (#3003) is deliberately still open.

**Docs:** `docs/SCHEMA.md` (the segmental paragraph — PR #3004), `docs/engines/COACH_STANCE.md`
(#973 re-verify against the #2889 change), `docs/alarm_citations.json` (the whole registry
re-baselined), `docs/INCIDENT_LOG.md` (+4 rows, Patterns regenerated 157→161 by its own writer).

**Decisions:** none needed — no governance-consequential choice. The closest was scoping
`dead_citations()` to lit alarms and exempting prose citations, which is a design detail
recorded in the script header and the registry `_comment`, not an architecture posture.

**Main:** red — CI/CD run `32601989142` (sha `67b5fa1e`) concluded failure on `Visual + AI-vision
QA`: two NEW high reader-truth findings the deploy did not cause (`/story/timeline/`,
`/data/habits/`), filed as **#3003** and deliberately not baselined. Deploy, Smoke and the
post-deploy integration checks all passed; auto-rollback correctly skipped (its `needs` excludes
visual-qa).

**Incidents:** 4 rows added — the 6-day silent segmental-field drop (P2), the post-deploy
visual-QA red on two new reader-truth findings (P3), `report.json` storing its own evidence
truncated (P4), and a production-approval lease found waiting 1.3h by the wrap gate rather than
by anyone watching (P4).

**Alarms:** 0 red >72h uncited — and the registry itself was the session's second finding (below).

**CI warnings:** unverified — the latest completed main run isn't green, so `check_ci_warnings.py`
has nothing to triage; (e2) owns that state.

**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.

**Backlog:** Now live at 14 actionable; no refill needed. No stale `Later` issues printed. Four
hygiene violations appeared — all on issues filed this session — and all four were fixed before
the wrap commit (#3003 gained `## Outcome` + `## Acceptance`; #2578 and #2799 gained the five new
stories in their `## Stories` lists).

**Closures:** #2994, #2996, #2797, #2734 commented.

**Ledger:** none — no standing machinery shipped. `dead_citations()` is a new check inside the
existing `check_alarm_citations.py` subsystem, which already carries its row; it adds no new
schedule, no new alarm and no new artifact.

---

## What shipped

| PR | Issue | What | State |
|---|---|---|---|
| #2995 | #2994 | withings `getmeas` requests every meastype the transform can parse | merged, **deployed 23:15:18Z, verified live** |
| #2998 | #2996 | a lit alarm's cited `#N` must be OPEN + the full registry baseline | merged |
| #3001 | #2889 | fingerprint the STRUCTURED brief, not the rendered prompt | merged |
| #3004 | #2994 | SCHEMA.md: the 15 segmental fields are verified-live | merged |

### The flagship — a documented signal that was never once written

Verifying epic #2797's last folded finding (*"nothing automated confirms the next weigh-in row
carries the 15 segmental fields"*) found something worse than unverified. `_fetch_range` built the
`getmeas` request from `MEAS_TYPES` alone; PR #2794 had put types 173/174/175 in a **separate**
`SEGMENTAL_TYPES` dict and never touched the request. The transform grew a branch for data the
fetch could not return.

Measured, not inferred: the last weigh-in's raw payload — `fetched_at 2026-08-17T05:05:45Z`,
**after** #2794 merged — contains no 173/174/175, and its DDB row had 34 fields and zero
segmental. `docs/SCHEMA.md` documented all 15 as shipped the entire time.

**The fixture was not the wire.** `test_withings_bodyscan2_scalars_and_segments` fed a fixture
with 173/174/175 inline and passed continuously — it mirrored the spike's *unfiltered exploratory*
`getmeas`, not the filtered request production issues.

The guard is the deliverable, not the one-line fix: SET-equality in both directions **plus** an
AST derivation of every module-level meastype table `_parse_measurements` consults, so a *third*
table cannot join the transform without joining the request. Both mutation-proved, and the
mutation proof calls the same derivation the real check does rather than a re-implementation.

Live verification after deploy (`LastModified 2026-08-22T23:15:18Z`, post-dating the 22:16Z
merge) via a `date_override` re-fetch of `2026-08-16`: **34 → 49 fields, all 15 present**, and the
device invariant holds exactly — the five type-173 values sum to **92.08 = the scalar
`fat_free_mass_kg`**. The magnitude-inferred `SEGMENT_POSITIONS` map is confirmed against its own
prediction: #2782 reasoned the torso would carry ~48.76 of 92.08 before any of it was reachable;
live it is torso 48.76, legs 15.48/15.35, arms 6.33/6.16.

### A citation string is not an owner

Trying to close #2734 honestly meant checking whether the alarm citing it would be left pointing
at a closed issue. Nothing could see that: the #1959 gate asserts a citation *string* exists and,
past 14 days, that it contains a `#N`. Neither asks whether the issue is open.

**4 of 7 registry entries pointed at closed issues; 3 of those were on alarms lit at that moment**,
two past the gate's own 72h threshold. Two were not merely dead but semantically wrong —
`qa-smoke-failures` cited an August 1st decision about oracle partitioning while its live cause
(`recall:corpus_freshness`, `FailCount ≥ 1` on all 8 days measured) was owned by the **open**
#2977 all along.

`dead_citations()` is narrow by construction so it cannot manufacture a red: prose citations with
no `#N` are exempt (a dated self-clearing state — `token-alarm-genesis-window-active`'s window
expires 2026-08-24 — is honestly cited in prose, and the registry-shape test now makes that prose
carry a concrete ISO date), an unreadable issue is UNKNOWN rather than dead, and a stale entry on
a **recovered** alarm is a pruning chore. Baselined in the same change, each disposition measured.

**A correction found by shipping:** pruning the recovered `weekly-signal-delivery-heartbeat` entry
immediately red the #2912 flap gate — its only episode (the arming transition of the #2820
dead-man) was inside the 72h flap window. Two rules disagreed. The prune rule is now *"OK for
longer than the flap window"*, not *"the moment it clears"*.

### ADR-126's cache could never hit

`canonicalize()` strips bookkeeping by dict **key**; the only production call site hashed
`system_prompt` + `user_message_full` — rendered strings with `json.dumps(brief)` baked in. So
`generation_date` (already in `_VOLATILE_KEYS`, beside `as_of` and `computed_at`) rode into the
digest as text, the strip list was a no-op where it mattered, and the digest changed daily by
construction. Live: `GenerationSkippedUnchanged` never emitted, all 8 cache rows `reuse_count = 0`,
`first_generated == last_generated`.

The honesty invariant is not weakened, and its **ceiling is now asserted rather than assumed**: a
test pins that `gap_days` still busts. A brief saying *"it has been 4 days"* may never be reused on
day 5 — and `gap_days` ticks daily during exactly the quiet stretches the feature exists to save
on, so the achievable skip rate is bounded well below 100%.

The miss reason is no longer unmeasurable — *"the metric never fired"* could not distinguish a
wrong fingerprint from genuinely-changing inputs, which is why this sat two months behind a green
suite. Per-part digests are stored and a miss now logs which parts changed. A **log line, not a
dimensioned metric**, because #2837 is an open 743-series finding and this would have added ~40.

## Two epics judged on acceptance, not on their children

**#2797 CLOSED.** All 13 children closed, but each of the four Done-when boxes was re-checked
against live state: the privacy-tier gate is 17 tests that collect under `-m premerge` and is
mutation-proved by construction; `_BROADCAST_SOURCES`/`SOCIAL_CHANNELS_ENV`/daily-brief are all
registry-derived; the AST edge map shipped at 99.4% against an 85% bar; SCHEMA carries both new
signals. Both folded findings dispositioned rather than dropped on closure — one was already
corrected by PR #2914, the other became #2994.

**#2578 did NOT close**, as predicted. Every child is closed and the acceptance is **7 proven
verdicts out of 490 gates — 1.4%** — while `gate_census` appears in **zero** workflows, so a newly
added gate still enters unverified. Boxes 1 and 3 are genuinely met (and box 3 is better than
asked: error bars in both directions, 41 unadjudicated workflow steps published by label, and a
list of the five failure shapes the census structurally cannot see). Filed #2999 and #3000.

## Gotchas worth carrying

- **Two gates made the work better by refusing it.** The #1665 module-size guard rejected the
  first #2889 cut (+40 lines on a file baselined at 2396 as debt being drained); rather than raise
  the ceiling the seam moved into `generation_cache.py`, where it belonged, and `ai_calls.py`
  landed at **exactly 2396**. The #973 engine-doc gate then fired on `COACH_STANCE.md`; its
  checklist was worked rather than date-bumped — read the change, ruled not material, AST-re-derived
  all four citations, **none moved**, and verified them byte-identical against `origin/main` because
  an equal line count can still hide a shifted span.
- **A piped gate reports the pipe's exit.** `python3 scripts/check_alarm_citations.py | head` printed
  `EXIT=0` while the script itself exited 1. Re-ran unpiped to get the real code.
- **`agent_commit.sh` refuses doc-literal files by design**; `ALLOW_DOC_LITERALS=1` is the documented
  opt-out and was needed four times (`docs/TESTING.md`, `site_api_common.py`, `alarm_citations.json`,
  `SCHEMA.md`). The `test_count` literal drifted on every one of the three test-adding PRs.
- **The registry prevented a self-inflicted wrong turn.** I constructed
  `raw/matthew/withings/2026/08/…` and got a 404; the real prefix is
  `raw/matthew/withings/measurements/…`, which is exactly what the `raw_layout` facet exists to stop
  me doing.

## Residual / next picks

- **#3003** — render `/story/timeline/` and `/data/habits/`, then baseline-or-fix; also make
  `report.json` store the untruncated note. This holds the publish path.
- **#2889** — open by design: the fix makes the cache *able* to hit; the first honest observation is
  tomorrow's 17:00 UTC daily brief. Either `GenerationSkippedUnchanged` fires for the first time in
  two months, or the `[GEN-CACHE-MISS]` lines name which part changed and the ceiling question gets
  answered with data.
- **#2837** — the inventory landed as a comment (734 series / 30 namespaces; 65% of the estate is two
  dimension choices; SiteAPI's 322 series carry ONE alarm and MCP's 153 carry none). The active-series
  measurement and the namespace ledger remain.
- **#3002** — the `SiteAPI`/`SiteApi` casing twin, with `ContentFilterFallback` stranded unwatched in
  the twin. Do this before #2892.
- **#2892** — hold until **#2974** lands: the CI caller class is exactly the one currently missing from
  the metric, so shipping the dimension first gives a dimension with a known hole.
- **#2999 / #3000** — epic #2578's remaining half.
- Cycle 14 has had **no weigh-in since 2026-08-16** (6 days) — *not-work — an observation for Matthew,
  not a backlog item.*
