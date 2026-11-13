# The Platform Operating Calendar

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-22

> **GENERATED** from `scripts/operating_calendar.py` (#2832, epic #2800) — edit the
> registry, run `python3 scripts/operating_calendar.py --apply`, never this file.
> Live due-state: `python3 scripts/operating_calendar.py --due` (the dead-man runs
> daily in `.github/workflows/operating-calendar.yml`; a red run reaches the
> remediation agent's triage email). This file is the ONE cadence truth —
> `docs/REVIEW_METHODOLOGY.md`'s cadence section is retired in its favor.

A judgment ritual that silently stops running is the filing rate dropping to zero
for that lens while every deterministic gate stays green. The calendar makes the
miss louder than the run: each ritual advances its clock only by producing its
dated artifact, and the dead-man reds when a window closes empty.

| Ritual | Procedure | Cadence | Grace | Attendance | Run artifact (the clock) |
|---|---|---|---|---|---|
| live-contract-recapture | ledger re-read | 25d | +4d | session | dated line in `tests/api_schemas/api_edition.json` · `^  "captured_at": "(\d{4}-\d{2}-\d{2})T` |
| rhythm-checkpoint-30d | ledger re-read | 30d | +7d | owner-attended | dated line in `docs/OPERATING_RHYTHM.md` · `^- 30-day checkpoint: (\d{4}-\d{2}-\d{2})` |
| accuracy-full | `/review accuracy` | 31d | +7d | session | `docs/reviews/` · `^EDITORIAL_ACCURACY_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| craft-review | `/review craft` | 31d | +7d | session | `docs/reviews/` · `^craft_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| emf-series-census | ledger re-read | 31d | +7d | session | dated line in `docs/PROPORTIONALITY.md` · `^- EMF census: (\d{4}-\d{2}-\d{2})` |
| fullreview-full | `/review full` | 31d | +7d | session | `docs/reviews/` · `^fullreview_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| managed-where-reverify | ledger re-read | 31d | +7d | session | dated line in `docs/MANAGED_WHERE_LEDGER.md` · `^- Re-verified: (\d{4}-\d{2}-\d{2})` |
| rhythm-checkpoint-60d | ledger re-read | 60d | +7d | owner-attended | dated line in `docs/OPERATING_RHYTHM.md` · `^- 60-day checkpoint: (\d{4}-\d{2}-\d{2})` |
| rhythm-checkpoint-90d | ledger re-read | 90d | +7d | owner-attended | dated line in `docs/OPERATING_RHYTHM.md` · `^- 90-day checkpoint: (\d{4}-\d{2}-\d{2})` |
| frontier-plan | `/frontier-plan` | 92d | +14d | owner-attended | `docs/reviews/` · `^FRONTIER_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| proportionality-reread | ledger re-read | 92d | +14d | owner-attended | dated line in `docs/PROPORTIONALITY.md` · `^- Re-read: (\d{4}-\d{2}-\d{2})` |
| sdlc-review | `/review sdlc` | 92d | +14d | owner-attended | `docs/reviews/` · `^sdlc_review_grades_(\d{4}-\d{2}-\d{2})\.json$` |

## Standing obligations (re-homed onto entries — they die with sessions otherwise)

- **emf-series-census**: Run `python3 deploy/emf_series_census.py --strict`; resolve any over-budget or unregistered namespace in deploy/emf_namespace_ledger.py BEFORE appending the dated line the probe reads — a line appended over a red records a number nobody acted on
- **fullreview-full**: Run `python3 scripts/prediction_publication_registry.py review` (read-only) and hand the owner the private proposed-manifest path it prints — the calls, asks and bets waiting for publication review. Approve nothing, and never copy the proposal's ids, words or size into the repo, a PR or the grades file
- **live-contract-recapture**: Run `python3 tests/test_live_contract_shapes_fresh.py` for the two commands, run the `--check-drift` one first (read-only GETs of every route the v9 site reads, shapes only) and read what moved — a removed key a page still reads is a defect to fix, not a baseline to update — then run the capture one
- **managed-where-reverify**: Walk every ledger row against LIVE state (gh api for the GitHub rows, read-only aws for the AWS rows); update each probed row's Verified cell and append the dated log line the probe reads
- **proportionality-reread**: Walk the whole ledger: every posture either re-earns its keep or gets its demote trigger pulled (the ADR-129 worked precedent)
- **rhythm-checkpoint-30d**: Answer the monthly use read in docs/OPERATING_RHYTHM.md from OBSERVED behaviour (which surfaces were opened, which were not, which coaches were texted) rather than from memory, and append the dated log line this probe reads
- **rhythm-checkpoint-30d**: Name what shipped in the month that has not been used once — each is a prune candidate or an issue with the reason it is still wanted, never a silent keep
- **rhythm-checkpoint-60d**: Read the latest closed month in docs/COST_TRACKER.md against what the platform actually DID for the owner that month — named, specific things, not a feeling; an honest 'nothing I can name' is a valid and important answer
- **rhythm-checkpoint-60d**: Append the dated log line this probe reads, with the two numbers (spend, and the count of named returns) written down so the next read has a prior
- **rhythm-checkpoint-90d**: Decide the next feature horizon from three months of lived usage — what was used, what was ignored, what was missed — and file it; speculation from before the launch does not qualify as evidence at this checkpoint
- **rhythm-checkpoint-90d**: Re-decide these three checkpoint rows themselves: each one is DELETED from the registry once it has served (an EXEMPT row cannot hold it — exemptions are for discovered review procedures, and the set guard reads a non-procedure key there as a phantom), or converted to a standing cadence with its own written reason
- **sdlc-review**: Re-grade the QA-strategy scorecard against the #1425 targets (the #1451 obligation — it stopped when this ritual did)
- **sdlc-review**: Revisit ADR-138's release-topology posture: are the compensating controls (3-layer QA, gating visual-QA, auto-rollback) still the honest staging substitute, and has the revisit trigger (real multi-user traffic) fired? (the #1338 obligation)

## Why each entry (registry reasons, verbatim)

- **accuracy-full** — The truth audit of the public surface (does the site say what the data says?). Last full run 2026-07-10 at #2832's filing — six weeks dark while the nightly reader-truth oracle only samples. ADR-104/105 are enforced per-surface by gates; this is the whole-estate pass. The probe reads the `full` mode's report only — the cheap deterministic `axis-a` pass writes no dated artifact and deliberately does not advance this clock, because it cannot see the defect class (a computed value that is internally consistent and semantically wrong) that `full` exists for.
- **craft-review** — Had NEVER executed at #2832's filing despite its own instruction to register a scheduled run — the exact silent-stop this calendar exists to make impossible. For its first five days on the calendar it read OK purely on the adoption anchor; #3250 made that state say NEVER-RUN out loud, and the first real run (2026-08-27) is what actually started this clock. The distinction matters: the clock is live now because an artifact exists, not because a date was granted.
- **emf-series-census** — #2837: CloudWatch MetricMonitorUsage grew 9x in three months (7.4 -> 66.9 metric-months, $0 -> $18.88) and flipped past AlarmMonitorUsage with nothing watching — 743 series across 35 namespaces had no inventory, budget or owner, so the only detector was the invoice. The ledger makes each namespace name a consumer; this entry is what keeps the count a LIVE measurement rather than a one-time audit. It rides the monthly cost close (cost-diligence Phase 5) because the series count is only meaningful next to the dollars it explains.
- **frontier-plan** — The full-horizon review (quantified self → quantified life). Its report is docs/reviews/FRONTIER_REVIEW_<date>.md — the command file names that path as canonical so a run cannot land its artifact somewhere this probe cannot see.
- **fullreview-full** — Deltas drift: each one grades against the last, so a slow slide can stay invisible to every individual delta. A monthly FULL run re-grades every area from scratch. The probe deliberately excludes _delta/_partial filenames — only a full-suffix-free grades file resets this clock. Owner ruling 2026-11-13 (the review cadence for rapid development): this monthly adversarial run is the ONE clocked full review. The weekly `fullreview-delta` clock is retired (delta mode stays an on-demand procedure); a full run is also owed after a material architectural or publication-policy change, a focused `/review <lens>` after a serious privacy or integrity incident, and a full run whenever the owner asks. Continuous coverage between runs is the automated gates on every PR and deploy. The change reset no clock: the next calibrated run is the baseline.
- **live-contract-recapture** — Owner ruling 2026-11-13: the v8 kit captures were frozen as historical evidence (ADR-166) and their 30-day rule retired; the live API's freshness moved to tests/test_live_contract_shapes_fresh.py, which reds main when any v9 route's shape baseline is over 30 days old — so the recapture is a dated task, not a surprise on main. Re-pointed from `preview-fixture-recapture` (kit manifest probe, first captured 2026-10-13); the probe reads /api/edition's baseline, which the one recapture command writes with the rest.
- **managed-where-reverify** — The out-of-IaC ledger sat self-stamped 'Verified 2026-07-09' for ~7 weeks while three GitHub rows inverted underneath it, and the 2026-08-23 external diligence review read the stale rows as current truth — manufacturing two P0 findings (DIL-004/DIL-006). A self-description doc is an external-assessment attack surface when stale; the probe reads the dated '- Re-verified:' log lines, not the header stamp, for the same reason proportionality-reread does (a bumped literal is not a re-read, #2986).
- **proportionality-reread** — ADR-103/144's quarterly re-read was chained to two rituals that did not run. The probe reads the dated `- Re-read:` lines in the ledger's own Re-read log — NOT the `Verified:` stamp, which automation refreshes and which therefore cannot distinguish a real re-read from a literal bump (the stale-behind-a-fresh-timestamp class, #2986).
- **rhythm-checkpoint-30d** — First occurrence 2026-10-01, written for the 2026-09-01 'operate, don't build' plan (Claude bug-fix-only, feature work frozen until this read). Owner ruling 2026-11-13: that premise ended — the platform is in rapid development (owner ruling 2026-11-07) — so the freeze gate is retired and the checkpoint is kept for what still holds: building fast makes unused surfaces accumulate faster, and only a dated read of a month of real use sees them. The clock was not reset by this change; it is overdue until it is run.
- **rhythm-checkpoint-60d** — First occurrence 2026-10-31. Cost without a return read is half an instrument, which is how a platform stays expensive and unquestioned (ADR-103/144's ledger asks the same question per subsystem; this asks it once, for the whole thing, from the owner's chair). Owner ruling 2026-11-13: kept through the rapid-development phase, where spend moves fastest; it reads the latest closed month rather than September's. Not reset by this change.
- **rhythm-checkpoint-90d** — First occurrence 2026-11-30. The roadmap decision is deferred to here on purpose: three months of use is the smallest sample that can distinguish 'I need this' from 'I imagined I would need this', and every roadmap this platform has written from speculation has been re-written from usage within a cycle. Ninety days is also long enough that the checkpoint must be on a clock — nobody remembers a November date they set in August. Owner ruling 2026-11-13: in the rapid-development phase the roadmap is no longer held for this date; the checkpoint stays as the usage-evidenced read of it and the place the three rhythm rows are re-decided.
- **sdlc-review** — Grades the machinery and rituals themselves — ran once (2026-07-18), 'quarterly-ish', then silently stopped, taking its two standing obligations with it. Those obligations are now recorded HERE, on the calendar entry, so they cannot die with a session's memory again.

## The guarded SET — every judgment procedure, classified (#3250)

Discovered from the tree, not hand-listed: each `/review <lens>` rubric beside
`.claude/skills/review/SKILL.md`, plus any review-family skill still standing outside
the spine. Every row below is either ON the calendar above or carries a dated exemption
underneath. Both directions are asserted — an unclassified rubric fails the guard, and
so does a calendar entry naming a rubric nobody wrote. That second direction is what
makes the phantom-procedure defect (a clock counting down toward a mode nothing
implements) unwritable rather than merely noticed.

| Procedure | Defined in | Classified as |
|---|---|---|
| accuracy | `.claude/skills/review/references/accuracy.md` | `accuracy-full` |
| craft | `.claude/skills/review/references/craft.md` | `craft-review` |
| frontier-plan | `.claude/skills/frontier-plan/SKILL.md` | `frontier-plan` |
| full | `.claude/skills/review/references/full.md` | `fullreview-full` |
| journey | `.claude/skills/review/references/journey.md` | EXEMPT (2026-08-22) |
| platform | `.claude/skills/review/references/platform.md` | EXEMPT (2026-08-22) |
| sdlc | `.claude/skills/review/references/sdlc.md` | `sdlc-review` |
| site | `.claude/skills/review/references/site.md` | EXEMPT (2026-08-22) |
| training-review | `.claude/skills/training-review/SKILL.md` | EXEMPT (2026-10-19) |

### Dated exemptions (the set guard's other half)

- **journey** (2026-08-22) — Re-audits the chat↔platform integration after integration work, event-driven by construction. The #2832 calendar cadences standing judgment; a ritual whose trigger is 'the seam changed' has an event for a clock already.
- **platform** (2026-08-22) — Not in the #2832 adopted calendar: its ground (a broad defect sweep) is covered by the monthly fullreview-full entry's panel, which grades the same surface with anchors and a trend line; it never ran as a command in its own right. Revive deliberately with its own entry if that panel proves too narrow for a defect hunt — do not let it half-exist off-calendar.
- **site** (2026-08-22) — Owner-attended editorial walkthrough of the public site — run when the site's story changes (a redesign, a new door), not on a clock. Cadencing an editorial judgment would manufacture runs with nothing to judge; the accuracy-full entry owns the site's monthly truth pass.
- **training-review** (2026-10-19) — #5079: the training block retro — an owner-attended ritual run at the end of each training block, whose cadence is the training charter's calibration.block_retro, not a repo clock. Its run artifacts are owner-only by ruling (the RETRO# row on training_constraints and a tab in his private review doc) and never land in this repo, so a repo-artifact probe here could only ever read NEVER-RUN. A missed block shows in the next retro's compared_with (it names the retro it compared against) — revive as an entry if a repo-side dated artifact is ever ruled acceptable.

## Scheduled first occurrences (a ritual whose clock starts later, #3378)

An entry may declare `starts` — the dated day its clock BEGINS — when its first
occurrence is genuinely in the future (the 2026-09-01 launch checkpoints). Until that
first occurrence passes, a row with no artifact reads `SCHEDULED` rather than
`NEVER-RUN`, because a checkpoint due in October is not a ritual anybody has stopped
doing. `starts` moves the CLOCK only: the day the first occurrence passes, an
artifact-less row goes `DUE` and then `OVERDUE` like any other, so absence is still
louder than failure — at the right time instead of a month early. A first occurrence
more than 120 days past adoption fails the guard: a row that can
never be late is decoration.

| Ritual | Clock starts | First occurrence | Hard by |
|---|---|---|---|
| rhythm-checkpoint-30d | 2026-09-01 | 2026-10-01 | 2026-10-08 |
| rhythm-checkpoint-60d | 2026-09-01 | 2026-10-31 | 2026-11-07 |
| rhythm-checkpoint-90d | 2026-09-01 | 2026-11-30 | 2026-12-07 |

## Dated holds (a deferral is a decision, #3250)

_None in force._

A hold re-anchors ONE entry's clock ONE time, with a date and a written reason, so a
deliberate skip is discharged by a decision instead of a silent lapse. It is bounded
(at most 45 days) and it never suppresses the NEVER-RUN verdict below:
deferring a ritual cannot manufacture evidence that it ever happened. A skip that
wants to be permanent belongs in the exemption list above, not in a hold.

## The anchor rule — and what an anchor may NOT do

Every clock starts at `max(newest artifact, 2026-08-22)` — the calendar's adoption
date. Without it the dead-man is born red on rituals that never ran (craft-review),
which blocks on history instead of behavior. Never bump the anchor to silence an
overdue ritual: the artifact is the only honest reset.

The anchor holds the **window** open. Since #3250 it no longer holds the **verdict**
green: a ritual with no artifact reports `NEVER-RUN`, never `OK`, and `--due` exits
`3` for it (`1` stays reserved for OVERDUE, so the log
distinguishes 'somebody stopped doing this' from 'nobody has ever done this'). The
distinction used to live only in the display string `last never (anchored …)` while
the verdict said OK — a dead-man green because it was anchored rather than because
the ritual ran is the exact lying-gauge shape this calendar exists to kill.
