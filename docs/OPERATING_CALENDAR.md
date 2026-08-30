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
| fullreview-delta | `/review full` | 7d | +3d | autonomous | `docs/reviews/` · `^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta|_partial)?\.json$` |
| accuracy-full | `/review accuracy` | 31d | +7d | session | `docs/reviews/` · `^EDITORIAL_ACCURACY_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| craft-review | `/review craft` | 31d | +7d | session | `docs/reviews/` · `^craft_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| emf-series-census | ledger re-read | 31d | +7d | session | dated line in `docs/PROPORTIONALITY.md` · `^- EMF census: (\d{4}-\d{2}-\d{2})` |
| fullreview-full | `/review full` | 31d | +7d | session | `docs/reviews/` · `^fullreview_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| managed-where-reverify | ledger re-read | 31d | +7d | session | dated line in `docs/MANAGED_WHERE_LEDGER.md` · `^- Re-verified: (\d{4}-\d{2}-\d{2})` |
| frontier-plan | `/frontier-plan` | 92d | +14d | owner-attended | `docs/reviews/` · `^FRONTIER_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| proportionality-reread | ledger re-read | 92d | +14d | owner-attended | dated line in `docs/PROPORTIONALITY.md` · `^- Re-read: (\d{4}-\d{2}-\d{2})` |
| sdlc-review | `/review sdlc` | 92d | +14d | owner-attended | `docs/reviews/` · `^sdlc_review_grades_(\d{4}-\d{2}-\d{2})\.json$` |

## Standing obligations (re-homed onto entries — they die with sessions otherwise)

- **emf-series-census**: Run `python3 deploy/emf_series_census.py --strict`; resolve any over-budget or unregistered namespace in deploy/emf_namespace_ledger.py BEFORE appending the dated line the probe reads — a line appended over a red records a number nobody acted on
- **managed-where-reverify**: Walk every ledger row against LIVE state (gh api for the GitHub rows, read-only aws for the AWS rows); update each probed row's Verified cell and append the dated log line the probe reads
- **proportionality-reread**: Walk the whole ledger: every posture either re-earns its keep or gets its demote trigger pulled (the ADR-129 worked precedent)
- **sdlc-review**: Re-grade the QA-strategy scorecard against the #1425 targets (the #1451 obligation — it stopped when this ritual did)
- **sdlc-review**: Revisit ADR-138's release-topology posture: are the compensating controls (3-layer QA, gating visual-QA, auto-rollback) still the honest staging substitute, and has the revisit trigger (real multi-user traffic) fired? (the #1338 obligation)

## Why each entry (registry reasons, verbatim)

- **accuracy-full** — The truth audit of the public surface (does the site say what the data says?). Last full run 2026-07-10 at #2832's filing — six weeks dark while the nightly reader-truth oracle only samples. ADR-104/105 are enforced per-surface by gates; this is the whole-estate pass. The probe reads the `full` mode's report only — the cheap deterministic `axis-a` pass writes no dated artifact and deliberately does not advance this clock, because it cannot see the defect class (a computed value that is internally consistent and semantically wrong) that `full` exists for.
- **craft-review** — Had NEVER executed at #2832's filing despite its own instruction to register a scheduled run — the exact silent-stop this calendar exists to make impossible. For its first five days on the calendar it read OK purely on the adoption anchor; #3250 made that state say NEVER-RUN out loud, and the first real run (2026-08-27) is what actually started this clock. The distinction matters: the clock is live now because an artifact exists, not because a date was granted.
- **emf-series-census** — #2837: CloudWatch MetricMonitorUsage grew 9x in three months (7.4 -> 66.9 metric-months, $0 -> $18.88) and flipped past AlarmMonitorUsage with nothing watching — 743 series across 35 namespaces had no inventory, budget or owner, so the only detector was the invoice. The ledger makes each namespace name a consumer; this entry is what keeps the count a LIVE measurement rather than a one-time audit. It rides the monthly cost close (cost-diligence Phase 5) because the series count is only meaningful next to the dollars it explains.
- **frontier-plan** — The full-horizon review (quantified self → quantified life). Its report is docs/reviews/FRONTIER_REVIEW_<date>.md — the command file names that path as canonical so a run cannot land its artifact somewhere this probe cannot see.
- **fullreview-delta** — The one review family that was still alive at #2832's filing — weekly-ish and shrinking (17→7 lenses). Weekly delta keeps the grades comparable session to session; any run of the `full` lens (full, delta or partial) resets this clock, because the weekly claim is 'the platform was looked at', not 'the look was small'. Delta mode itself is defined in the `full` rubric's § 'Delta mode' (#3250) — the artifact this probe reads is named there, so the clock and the procedure cannot drift apart.
- **fullreview-full** — Deltas drift: each one grades against the last, so a slow slide can stay invisible to every individual delta. A monthly FULL run re-grades every area from scratch. The probe deliberately excludes _delta/_partial filenames — only a full-suffix-free grades file resets this clock.
- **managed-where-reverify** — The out-of-IaC ledger sat self-stamped 'Verified 2026-07-09' for ~7 weeks while three GitHub rows inverted underneath it, and the 2026-08-23 external diligence review read the stale rows as current truth — manufacturing two P0 findings (DIL-004/DIL-006). A self-description doc is an external-assessment attack surface when stale; the probe reads the dated '- Re-verified:' log lines, not the header stamp, for the same reason proportionality-reread does (a bumped literal is not a re-read, #2986).
- **proportionality-reread** — ADR-103/144's quarterly re-read was chained to two rituals that did not run. The probe reads the dated `- Re-read:` lines in the ledger's own Re-read log — NOT the `Verified:` stamp, which automation refreshes and which therefore cannot distinguish a real re-read from a literal bump (the stale-behind-a-fresh-timestamp class, #2986).
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
| full | `.claude/skills/review/references/full.md` | `fullreview-delta`, `fullreview-full` |
| journey | `.claude/skills/review/references/journey.md` | EXEMPT (2026-08-22) |
| platform | `.claude/skills/review/references/platform.md` | EXEMPT (2026-08-22) |
| sdlc | `.claude/skills/review/references/sdlc.md` | `sdlc-review` |
| site | `.claude/skills/review/references/site.md` | EXEMPT (2026-08-22) |

### Dated exemptions (the set guard's other half)

- **journey** (2026-08-22) — Re-audits the chat↔platform integration after integration work, event-driven by construction. The #2832 calendar cadences standing judgment; a ritual whose trigger is 'the seam changed' has an event for a clock already.
- **platform** (2026-08-22) — Not in the #2832 adopted calendar: its ground (a broad defect sweep) is covered by the monthly fullreview-full entry's panel, which grades the same surface with anchors and a trend line; it never ran as a command in its own right. Revive deliberately with its own entry if that panel proves too narrow for a defect hunt — do not let it half-exist off-calendar.
- **site** (2026-08-22) — Owner-attended editorial walkthrough of the public site — run when the site's story changes (a redesign, a new door), not on a clock. Cadencing an editorial judgment would manufacture runs with nothing to judge; the accuracy-full entry owns the site's monthly truth pass.

## Dated holds (a deferral is a decision, #3250)

- **fullreview-delta** — declared 2026-08-27, resumes 2026-09-06. #3245 rewrote the review-skill corpus (102 files) — the instrument this clock measures. A delta grades the platform against the PREVIOUS run's anchors, so a delta run across an instrument rewrite produces a number that means nothing: the movement would be the rubric moving, not the platform. Decision (#3250, Session I): do NOT run a delta into the rewrite. The next fullreview run is recorded as a NEW BASELINE (a full, suffix-free grades file), and this clock is re-anchored once to 2026-09-06 so the 2026-09-01 hard date is discharged by a written decision rather than by a silent lapse. This hold is one-time: after 2026-09-06 the ordinary cadence applies and a missed run reds like any other.

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
