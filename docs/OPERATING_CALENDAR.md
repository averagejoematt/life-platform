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

| Ritual | Skill | Cadence | Grace | Attendance | Run artifact (the clock) |
|---|---|---|---|---|---|
| fullreview-delta | `/fullreview` | 7d | +3d | autonomous | `docs/reviews/` · `^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta|_partial)?\.json$` |
| accuracy-full | `/accuracy-review` | 31d | +7d | session | `docs/reviews/` · `^EDITORIAL_ACCURACY_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| craft-review | `/craft-review` | 31d | +7d | session | `docs/reviews/` · `^craft_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| fullreview-full | `/fullreview` | 31d | +7d | session | `docs/reviews/` · `^fullreview_grades_(\d{4}-\d{2}-\d{2})\.json$` |
| frontier-plan | `/frontier-plan` | 92d | +14d | owner-attended | `docs/reviews/` · `^FRONTIER_REVIEW_(\d{4}-\d{2}-\d{2})\.md$` |
| proportionality-reread | ledger re-read | 92d | +14d | owner-attended | dated line in `docs/PROPORTIONALITY.md` · `^- Re-read: (\d{4}-\d{2}-\d{2})` |
| sdlc-review | `/sdlc-review` | 92d | +14d | owner-attended | `docs/reviews/` · `^sdlc_review_grades_(\d{4}-\d{2}-\d{2})\.json$` |

## Standing obligations (re-homed onto entries — they die with sessions otherwise)

- **proportionality-reread**: Walk the whole ledger: every posture either re-earns its keep or gets its demote trigger pulled (the ADR-129 worked precedent)
- **sdlc-review**: Re-grade the QA-strategy scorecard against the #1425 targets (the #1451 obligation — it stopped when this ritual did)
- **sdlc-review**: Revisit ADR-138's release-topology posture: are the compensating controls (3-layer QA, gating visual-QA, auto-rollback) still the honest staging substitute, and has the revisit trigger (real multi-user traffic) fired? (the #1338 obligation)

## Why each entry (registry reasons, verbatim)

- **accuracy-full** — The truth audit of the public surface (does the site say what the data says?). Last full run 2026-07-10 at #2832's filing — six weeks dark while the nightly reader-truth oracle only samples. ADR-104/105 are enforced per-surface by gates; this is the whole-estate pass.
- **craft-review** — Had NEVER executed at #2832's filing despite its own instruction to register a scheduled run — the exact silent-stop this calendar exists to make impossible. Its first run creates docs/reviews/craft_grades_<date>.json and starts the clock for real; until then the adoption anchor holds the window.
- **frontier-plan** — The full-horizon review (quantified self → quantified life). Its report is docs/reviews/FRONTIER_REVIEW_<date>.md — the command file names that path as canonical so a run cannot land its artifact somewhere this probe cannot see.
- **fullreview-delta** — The one review family that was still alive at #2832's filing — weekly-ish and shrinking (17→7 lenses). Weekly delta keeps the grades comparable session to session; any fullreview run (full, delta or partial) resets this clock, because the weekly claim is 'the platform was looked at', not 'the look was small'.
- **fullreview-full** — Deltas drift: each one grades against the last, so a slow slide can stay invisible to every individual delta. A monthly FULL run re-grades every area from scratch. The probe deliberately excludes _delta/_partial filenames — only a full-suffix-free grades file resets this clock.
- **proportionality-reread** — ADR-103/144's quarterly re-read was chained to two rituals that did not run. The probe reads the dated `- Re-read:` lines in the ledger's own Re-read log — NOT the `Verified:` stamp, which automation refreshes and which therefore cannot distinguish a real re-read from a literal bump (the stale-behind-a-fresh-timestamp class, #2986).
- **sdlc-review** — Grades the machinery and rituals themselves — ran once (2026-07-18), 'quarterly-ish', then silently stopped, taking its two standing obligations with it. Those obligations are now recorded HERE, on the calendar entry, so they cannot die with a session's memory again.

## Off-calendar review skills (dated exemptions, the set guard's other half)

- **journey-review** (2026-08-22) — Re-audits the chat↔platform integration after integration work, event-driven by construction. The #2832 calendar cadences standing judgment; a ritual whose trigger is 'the seam changed' has an event for a clock already.
- **platform-review** (2026-08-22) — Not in the #2832 adopted calendar: its ground (full-platform sweep) is covered by the monthly fullreview-full entry's panel; it has never run as a command since it landed. Revive deliberately with its own entry if the fullreview panel proves too narrow — do not let it half-exist off-calendar.
- **site-review** (2026-08-22) — Owner-attended editorial walkthrough of the public site — run when the site's story changes (a redesign, a new door), not on a clock. Cadencing an editorial judgment would manufacture runs with nothing to judge; the accuracy-full entry owns the site's monthly truth pass.

## The anchor rule

Every clock starts at `max(newest artifact, 2026-08-22)` — the calendar's adoption
date. Without it the dead-man is born red on rituals that never ran (craft-review),
which blocks on history instead of behavior. Never bump the anchor to silence an
overdue ritual: the artifact is the only honest reset.
