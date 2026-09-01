#!/usr/bin/env python3
"""scripts/operating_calendar.py — the Platform Operating Calendar (#2832, epic #2800).

WHY THIS EXISTS
---------------
The judgment rituals were designed but not operating. Measured at filing (2026-08-16
elite review, WS-F): of 5 review families only /fullreview was alive; /sdlc-review ran
once and its owned obligations (#1451 QA-scorecard re-grade, #1338 → ADR-138 deviation
register) silently stopped with it; /craft-review had NEVER executed despite its own
instruction to register a scheduled run; accuracy full-mode last ran 2026-07-10; the
PROPORTIONALITY quarterly re-read was chained to two rituals that did not run. All nine
scheduled GitHub automations were deterministic QA — ZERO judgment-bearing reviews were
scheduled, and nothing detected a missed run. Review cadence is what sets the filing
rate, so a silently-stopped ritual is not a hygiene problem: it is the platform slowly
going blind while every gate stays green.

WHAT THIS IS (charter primitives 1 + 5)
---------------------------------------
* **The registry** — ``CALENDAR`` below is the ONE cadence truth for every judgment
  ritual: skill, cadence, attendance, where its run artifact lands, and the standing
  obligations that ride on it. REVIEW_METHODOLOGY.md's cadence section is retired in
  favor of this file; the human-readable view is the generated
  ``docs/OPERATING_CALENDAR.md`` (#2986 DERIVED artifact, guard in the docs-ci lane).
* **The dead-man** — ``--due`` reds when a ritual's newest run artifact is older than
  its cadence window. It runs daily in ``.github/workflows/operating-calendar.yml``;
  a red scheduled workflow lands in the remediation agent's triage email, so a missed
  ritual screams instead of waiting for a session to remember it. This is the
  ``test_heartbeat_completeness`` pattern applied to reviews: absence must be louder
  than failure.

HOW "LAST RUN" IS MEASURED — and why not mtime or git dates
-----------------------------------------------------------
Each ritual's probe reads the DATE IN THE ARTIFACT'S OWN NAME (or a dated line inside a
ledger doc). Filesystem mtimes churn on checkout; git commit dates lie when a bot
refreshes a literal in a stale body (the #2986 catalog went a month stale behind a
timestamp the reconcile bot bumped daily). A ritual only advances its clock by
producing the dated artifact its own skill definition says a run produces — which is
exactly the claim the dead-man should be checking.

THE ANCHOR RULE (arming a gate needs a baseline)
------------------------------------------------
Every entry's clock starts at ``max(newest artifact, ADOPTED)``. Without the anchor the
gate would be born red — craft-review has never run, so its window would have expired
before the calendar existed — and an armed gate over un-baselined debt blocks the
pipeline on history instead of behavior (the 2026-08-21 reader-truth lesson). With it,
every ritual gets one full window from adoption; from then on the schedule is live.

AN ANCHOR IS A GRANT, NOT EVIDENCE (#3250)
------------------------------------------
v1.1 fixes the calendar's own version of the disease it was built to detect. Until now a
ritual that had NEVER produced its artifact printed the state word ``OK`` — the distinction
lived in the display string (``last never (anchored 2026-08-22)``) and was absent from the
verdict, so ``--due`` exited 0 and the daily sweep reported "✅ no ritual outside its
window" over two rituals nobody has ever run (craft-review, proportionality-reread). A
dead-man that is green because it was *anchored* rather than because the ritual *ran* is a
lying gauge, and this file's whole thesis is that absence must be louder than failure.

So: ``NEVER-RUN`` is now its own state, it is never ``OK``, and ``--due`` exits **3** on it
(distinct from OVERDUE's 1, so a reader — and the workflow log — can tell "nobody has ever
done this" from "somebody stopped doing this"). The anchor still holds the *window* open;
it no longer holds the *verdict* green. The only honest clearings are running the ritual
(its dated artifact) or a dated ``EXEMPT`` row.

THE SET IS LENSES NOW, NOT FILES (#3250, v1.2)
----------------------------------------------
The review family was nine separate command files. Three of them had already been retired by
a dated ``EXEMPT`` row here while their files sat in the tree as orphans; one was strictly
dominated by another; and the ADR-099 filing contract was restated in six of them. Every one
of those is the same shape this file exists to detect — **a registry entry greener than the
ritual it names** — so the fix was structural: one spine (``.claude/skills/review/SKILL.md``)
with a per-lens rubric in ``.claude/skills/review/references/<lens>.md``.

That moves the unit of ritual from a FILE to a LENS, so the set guard moves with it. Discovery
(``review_procedures()``) enumerates every lens rubric beside the spine, plus any review-family
skill still living outside it (``frontier-plan``). Each discovered procedure is either ON the
calendar below — an entry names it in ``lens`` (or in ``skill``, for a standalone) — or in
``EXEMPT`` with a dated reason. Both directions are asserted: an unclassified rubric is loud
rather than green-by-default, and a calendar entry naming a rubric that does not exist is a
phantom. That second direction is the enforcement half of "every calendar entry names a
procedure that exists": the phantom-procedure defect (``fullreview-delta`` counting down
toward a hard date for a mode nothing implemented) can no longer be written in the first place.

An exemption retires a CLOCK, not a capability. ``platform``/``site``/``journey`` are still
lenses anyone can run on request; what they no longer have — deliberately, with a date and a
reason — is a cadence and a dead-man.

DEFERRAL IS A DECISION, WITH A DATE AND A REASON (the ``hold`` field, #3250)
---------------------------------------------------------------------------
Sometimes a ritual should *not* run on schedule for a reason that is itself sound — e.g.
the instrument was just rewritten, so the next run has to be recorded as a new baseline
rather than compared against a reading the rewrite invalidated. That is a decision, and
the old options were both bad: run a meaningless comparison, or let the clock lapse
silently. An entry may now carry ``hold=(declared, until, reason)`` — a ONE-TIME, dated,
reasoned re-anchor of that entry's clock to ``until``, rendered verbatim into the generated
doc. Rules the guards enforce (tests/test_operating_calendar_2832.py): the reason must name
its cause issue, the window is bounded, and a hold NEVER suppresses the NEVER-RUN verdict —
deferring a ritual cannot manufacture evidence that it ever happened.

A RITUAL WHOSE FIRST OCCURRENCE IS IN THE FUTURE (the ``starts`` field, #3378)
------------------------------------------------------------------------------
The 2026-09-01 launch put three one-time judgment points on the calendar — the 30/60/90-day
operating checkpoints in ``docs/OPERATING_RHYTHM.md`` — whose first occurrence is a date that
has not arrived yet. Every existing state assumed a ritual should already be running: an entry
with no artifact reports NEVER-RUN and reds the daily sweep, which for a checkpoint due
2026-10-01 would mean a month of daily red over a ritual that is not late by anybody's
definition. A gate that reds for a month while nothing is wrong is how a gate gets ignored,
and this file's own thesis dies with it.

So an entry may declare ``starts=YYYY-MM-DD`` — the dated day its clock BEGINS (here, launch
day). Its first occurrence is then ``starts + cadence``, and until that day passes a never-run
entry reports ``SCHEDULED`` rather than NEVER-RUN. What ``starts`` may NOT do is the thing the
anchor and the hold may not do either: it does not touch DUE or OVERDUE. The day the first
occurrence passes, an artifact-less entry goes DUE and then OVERDUE exactly like every other
row, so absence is still louder than failure — just at the right time rather than a month
early. Parking a ritual permanently in the future is bounded out: a declared first occurrence
more than ``MAX_SCHEDULE_AHEAD_DAYS`` past adoption fails the guard, and the entry's reason
must state the first-occurrence date in full so registry and prose cannot drift apart.

USAGE
-----
    python3 scripts/operating_calendar.py            # human table, exit 0 always
    python3 scripts/operating_calendar.py --due      # dead-man: 1 = OVERDUE, 3 = never-run
    python3 scripts/operating_calendar.py --due --today 2026-12-01   # deterministic (tests)
    python3 scripts/operating_calendar.py --check    # docs/OPERATING_CALENDAR.md drift → exit 1
    python3 scripts/operating_calendar.py --apply    # regenerate docs/OPERATING_CALENDAR.md

Exit codes: 0 clean · 1 at least one OVERDUE · 2 bad --today · 3 no OVERDUE but at least
one ritual has never produced its artifact.

v1.3.0 — 2026-08-31 (launch checkpoints, `starts`) · v1.2.0 — 2026-08-30 (#3250, lens set) ·
v1.1.0 — 2026-08-27 (#3250) · v1.0.0 — 2026-08-22 (#2832)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOC_PATH = "docs/OPERATING_CALENDAR.md"

# The day the calendar was adopted (#2832). Clocks start here for rituals whose newest
# artifact predates it — see THE ANCHOR RULE above. Never bump this to silence the
# dead-man; a ritual that is overdue gets RUN, not re-anchored.
ADOPTED = date(2026, 8, 22)

# Probe kinds. `newest_dated_file`: scan a directory for filenames matching a regex
# whose one capture group is YYYY-MM-DD; newest date wins. `regex_in_file`: same, over
# one file's text (for ledger docs whose re-read is a dated line, not a new file).
NEWEST_DATED_FILE = "newest_dated_file"
REGEX_IN_FILE = "regex_in_file"

# Attendance is a fact about who must be present, not a wish: `autonomous` runs
# unattended (scheduled target), `session` runs inside a working session on cadence,
# `owner-attended` needs Matthew in the loop (grades and postures are his calls).
AUTONOMOUS = "autonomous"
SESSION = "session"
OWNER = "owner-attended"

_DATE_RE_GROUPS = 1  # every probe regex carries exactly one capture group: the date


#: The one review spine. Its LENSES are the rituals; the spine itself grades nothing on a
#: clock, so it is deliberately excluded from the discovered set (see review_procedures()).
REVIEW_SPINE = "review"


def _entry(skill, cadence_days, grace_days, attendance, probe, obligations, reason, hold=None, lens=None, starts=None):
    return {
        "skill": skill,  # resolved via skill_registry.skill_path(), or None for a doc-only ritual
        # The `/review <lens>` rubric this entry schedules — a name under
        # .claude/skills/review/references/. The set guard resolves it to a real file, so an
        # entry can no longer name a procedure nobody wrote (#3250). None for a standalone
        # skill (frontier-plan) or a doc-only ledger re-read.
        "lens": lens,
        "cadence_days": cadence_days,
        "grace_days": grace_days,
        "attendance": attendance,
        "probe": probe,  # (kind, relative dir-or-file, regex with one date group)
        "obligations": tuple(obligations),
        "reason": reason,
        # (declared YYYY-MM-DD, until YYYY-MM-DD, reason naming the cause issue) — a
        # one-time dated re-anchor of THIS entry's clock. See the module docstring.
        "hold": hold,
        # YYYY-MM-DD the clock BEGINS for a ritual whose first occurrence is still in the
        # future (first occurrence = starts + cadence_days). Before that day a never-run
        # entry reads SCHEDULED instead of NEVER-RUN; after it, ordinary DUE/OVERDUE apply.
        # See the module docstring — it moves the clock, never the lateness verdict.
        "starts": starts,
    }


# A hold may buy at most this many days. Longer than one cadence-and-a-bit is not a
# deferral, it is a retirement wearing a deferral's clothes — and a retirement goes
# through EXEMPT, which the set guard reads.
MAX_HOLD_DAYS = 45

# A declared first occurrence (`starts` + cadence) may sit at most this far past ADOPTED.
# Without a bound, `starts` would be a way to hold an entry SCHEDULED forever — a row on
# the calendar that can never be late is decoration, which is the shape #3250 killed one
# level down. The launch checkpoints' furthest first occurrence (2026-11-30) sits 100 days
# out; the bound leaves that room and nothing like a year of it.
MAX_SCHEDULE_AHEAD_DAYS = 120


CALENDAR: dict[str, dict] = {
    # ── Weekly ────────────────────────────────────────────────────────────────
    "fullreview-delta": _entry(
        skill=REVIEW_SPINE,
        lens="full",
        cadence_days=7,
        grace_days=3,
        attendance=AUTONOMOUS,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta|_partial)?\.json$"),
        obligations=(),
        reason=(
            "The one review family that was still alive at #2832's filing — weekly-ish and "
            "shrinking (17→7 lenses). Weekly delta keeps the grades comparable session to "
            "session; any run of the `full` lens (full, delta or partial) resets this clock, "
            "because the weekly claim is 'the platform was looked at', not 'the look was "
            "small'. Delta mode itself is defined in the `full` rubric's § 'Delta mode' "
            "(#3250) — the artifact this probe reads is named there, so the clock and the "
            "procedure cannot drift apart."
        ),
        hold=(
            "2026-08-27",
            "2026-09-06",
            "#3245 rewrote the review-skill corpus (102 files) — the instrument this clock "
            "measures. A delta grades the platform against the PREVIOUS run's anchors, so a "
            "delta run across an instrument rewrite produces a number that means nothing: the "
            "movement would be the rubric moving, not the platform. Decision (#3250, Session I): "
            "do NOT run a delta into the rewrite. The next fullreview run is recorded as a NEW "
            "BASELINE (a full, suffix-free grades file), and this clock is re-anchored once to "
            "2026-09-06 so the 2026-09-01 hard date is discharged by a written decision rather "
            "than by a silent lapse. This hold is one-time: after 2026-09-06 the ordinary "
            "cadence applies and a missed run reds like any other.",
        ),
    ),
    # ── Monthly ───────────────────────────────────────────────────────────────
    "fullreview-full": _entry(
        skill=REVIEW_SPINE,
        lens="full",
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^fullreview_grades_(\d{4}-\d{2}-\d{2})\.json$"),
        obligations=(),
        reason=(
            "Deltas drift: each one grades against the last, so a slow slide can stay "
            "invisible to every individual delta. A monthly FULL run re-grades every area "
            "from scratch. The probe deliberately excludes _delta/_partial filenames — only "
            "a full-suffix-free grades file resets this clock."
        ),
    ),
    "accuracy-full": _entry(
        skill=REVIEW_SPINE,
        lens="accuracy",
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^EDITORIAL_ACCURACY_REVIEW_(\d{4}-\d{2}-\d{2})\.md$"),
        obligations=(),
        reason=(
            "The truth audit of the public surface (does the site say what the data says?). "
            "Last full run 2026-07-10 at #2832's filing — six weeks dark while the nightly "
            "reader-truth oracle only samples. ADR-104/105 are enforced per-surface by gates; "
            "this is the whole-estate pass. The probe reads the `full` mode's report only — "
            "the cheap deterministic `axis-a` pass writes no dated artifact and deliberately "
            "does not advance this clock, because it cannot see the defect class (a computed "
            "value that is internally consistent and semantically wrong) that `full` exists for."
        ),
    ),
    "craft-review": _entry(
        skill=REVIEW_SPINE,
        lens="craft",
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^craft_grades_(\d{4}-\d{2}-\d{2})\.json$"),
        obligations=(),
        reason=(
            "Had NEVER executed at #2832's filing despite its own instruction to register a "
            "scheduled run — the exact silent-stop this calendar exists to make impossible. "
            "For its first five days on the calendar it read OK purely on the adoption anchor; "
            "#3250 made that state say NEVER-RUN out loud, and the first real run "
            "(2026-08-27) is what actually started this clock. The distinction matters: the "
            "clock is live now because an artifact exists, not because a date was granted."
        ),
    ),
    "managed-where-reverify": _entry(
        skill=None,  # not a command — a ledger re-verification, recorded as a dated line
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(REGEX_IN_FILE, "docs/MANAGED_WHERE_LEDGER.md", r"^- Re-verified: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Walk every ledger row against LIVE state (gh api for the GitHub rows, "
            "read-only aws for the AWS rows); update each probed row's Verified cell "
            "and append the dated log line the probe reads",
        ),
        reason=(
            "The out-of-IaC ledger sat self-stamped 'Verified 2026-07-09' for ~7 weeks "
            "while three GitHub rows inverted underneath it, and the 2026-08-23 external "
            "diligence review read the stale rows as current truth — manufacturing two "
            "P0 findings (DIL-004/DIL-006). A self-description doc is an external-"
            "assessment attack surface when stale; the probe reads the dated "
            "'- Re-verified:' log lines, not the header stamp, for the same reason "
            "proportionality-reread does (a bumped literal is not a re-read, #2986)."
        ),
    ),
    "emf-series-census": _entry(
        # A step OF the monthly cost close, not a ritual of its own — and `skill`/`lens`
        # are graded against the review-procedure discovery set, so naming `cost-diligence`
        # here would register as a phantom. The obligation below carries the wiring instead.
        skill=None,
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(REGEX_IN_FILE, "docs/PROPORTIONALITY.md", r"^- EMF census: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Run `python3 deploy/emf_series_census.py --strict`; resolve any over-budget "
            "or unregistered namespace in deploy/emf_namespace_ledger.py BEFORE appending "
            "the dated line the probe reads — a line appended over a red records a number "
            "nobody acted on",
        ),
        reason=(
            "#2837: CloudWatch MetricMonitorUsage grew 9x in three months (7.4 -> 66.9 "
            "metric-months, $0 -> $18.88) and flipped past AlarmMonitorUsage with nothing "
            "watching — 743 series across 35 namespaces had no inventory, budget or owner, "
            "so the only detector was the invoice. The ledger makes each namespace name a "
            "consumer; this entry is what keeps the count a LIVE measurement rather than a "
            "one-time audit. It rides the monthly cost close (cost-diligence Phase 5) "
            "because the series count is only meaningful next to the dollars it explains."
        ),
    ),
    # ── Quarterly ─────────────────────────────────────────────────────────────
    "sdlc-review": _entry(
        skill=REVIEW_SPINE,
        lens="sdlc",
        cadence_days=92,
        grace_days=14,
        attendance=OWNER,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^sdlc_review_grades_(\d{4}-\d{2}-\d{2})\.json$"),
        obligations=(
            "Re-grade the QA-strategy scorecard against the #1425 targets (the #1451 " "obligation — it stopped when this ritual did)",
            "Revisit ADR-138's release-topology posture: are the compensating controls "
            "(3-layer QA, gating visual-QA, auto-rollback) still the honest staging "
            "substitute, and has the revisit trigger (real multi-user traffic) fired? "
            "(the #1338 obligation)",
        ),
        reason=(
            "Grades the machinery and rituals themselves — ran once (2026-07-18), "
            "'quarterly-ish', then silently stopped, taking its two standing obligations "
            "with it. Those obligations are now recorded HERE, on the calendar entry, so "
            "they cannot die with a session's memory again."
        ),
    ),
    "proportionality-reread": _entry(
        skill=None,  # not a command — a ledger re-read, recorded as a dated line
        cadence_days=92,
        grace_days=14,
        attendance=OWNER,
        probe=(REGEX_IN_FILE, "docs/PROPORTIONALITY.md", r"^- Re-read: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Walk the whole ledger: every posture either re-earns its keep or gets its "
            "demote trigger pulled (the ADR-129 worked precedent)",
        ),
        reason=(
            "ADR-103/144's quarterly re-read was chained to two rituals that did not run. "
            "The probe reads the dated `- Re-read:` lines in the ledger's own Re-read log — "
            "NOT the `Verified:` stamp, which automation refreshes and which therefore "
            "cannot distinguish a real re-read from a literal bump (the "
            "stale-behind-a-fresh-timestamp class, #2986)."
        ),
    ),
    "frontier-plan": _entry(
        skill="frontier-plan",
        cadence_days=92,
        grace_days=14,
        attendance=OWNER,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^FRONTIER_REVIEW_(\d{4}-\d{2}-\d{2})\.md$"),
        obligations=(),
        reason=(
            "The full-horizon review (quantified self → quantified life). Its report is "
            "docs/reviews/FRONTIER_REVIEW_<date>.md — the command file names that path as "
            "canonical so a run cannot land its artifact somewhere this probe cannot see."
        ),
    ),
    # ── The launch checkpoints (one-time, dated; #3378) ───────────────────────
    "rhythm-checkpoint-30d": _entry(
        skill=None,  # not a command — the owner's read of his own operating rhythm
        cadence_days=30,
        grace_days=7,
        attendance=OWNER,
        starts="2026-09-01",
        probe=(REGEX_IN_FILE, "docs/OPERATING_RHYTHM.md", r"^- 30-day checkpoint: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Answer the 30-day section of docs/OPERATING_RHYTHM.md from OBSERVED behaviour "
            "(which surfaces were opened, which were not, which coaches were texted) rather "
            "than from memory, and append the dated log line this probe reads",
            "This is the first window in which a feature may be reconsidered at all — "
            "anything wanted before it waits, and anything wanted at it is filed as an issue "
            "with the lived usage that motivated it written into the body",
        ),
        reason=(
            "First occurrence 2026-10-01. From the 2026-09-01 launch the owner operates the "
            "platform instead of building it daily, and Claude sessions go bug-fix-only. Both "
            "failure modes of that switch are invisible from inside any single day: the rhythm "
            "quietly lapses, or feature work quietly resumes one 'small' change at a time. A "
            "dated checkpoint is the only thing that reads a month of behaviour as a month."
        ),
    ),
    "rhythm-checkpoint-60d": _entry(
        skill=None,  # not a command — the owner's cost + return read, on the closed month
        cadence_days=60,
        grace_days=7,
        attendance=OWNER,
        starts="2026-09-01",
        probe=(REGEX_IN_FILE, "docs/OPERATING_RHYTHM.md", r"^- 60-day checkpoint: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Read September's close in docs/COST_TRACKER.md against what the platform "
            "actually DID for the owner that month — named, specific things, not a feeling; "
            "an honest 'nothing I can name' is a valid and important answer",
            "Append the dated log line this probe reads, with the two numbers (spend, and the "
            "count of named returns) written down so the 90-day read has a prior",
        ),
        reason=(
            "First occurrence 2026-10-31, deliberately after the September cost close lands "
            "rather than during it — the first full month of user-mode spend is the first "
            "month whose cost can be read against use rather than against building. Cost "
            "without a return read is half an instrument, which is how a platform stays "
            "expensive and unquestioned (ADR-103/144's ledger asks the same question per "
            "subsystem; this asks it once, for the whole thing, from the owner's chair)."
        ),
    ),
    "rhythm-checkpoint-90d": _entry(
        skill=None,  # not a command — the owner's roadmap decision, from lived usage
        cadence_days=90,
        grace_days=7,
        attendance=OWNER,
        starts="2026-09-01",
        probe=(REGEX_IN_FILE, "docs/OPERATING_RHYTHM.md", r"^- 90-day checkpoint: (\d{4}-\d{2}-\d{2})"),
        obligations=(
            "Decide the next feature horizon from three months of lived usage — what was "
            "used, what was ignored, what was missed — and file it; speculation from before "
            "the launch does not qualify as evidence at this checkpoint",
            "Re-decide these three checkpoint rows themselves: each one is DELETED from the "
            "registry once it has served (an EXEMPT row cannot hold it — exemptions are for "
            "discovered review procedures, and the set guard reads a non-procedure key there "
            "as a phantom), or converted to a standing cadence with its own written reason",
        ),
        reason=(
            "First occurrence 2026-11-30. The roadmap decision is deferred to here on purpose: "
            "three months of use is the smallest sample that can distinguish 'I need this' from "
            "'I imagined I would need this', and every roadmap this platform has written from "
            "speculation has been re-written from usage within a cycle. Ninety days is also long "
            "enough that the checkpoint must be on a clock — nobody remembers a November date "
            "they set in August."
        ),
    ),
}

# ── The set guard's exemptions ────────────────────────────────────────────────
# Discovery (review_procedures() below) enumerates every `/review` lens rubric plus any
# review-family skill still standing outside the spine. Each one is either ON the calendar
# above or HERE with a dated reason. An undated or reasonless exemption is the old failure
# mode — "we'll get to it" with no clock.
#
# Keys are LENS names since #3250 (`platform`, not `platform-review`): the three files these
# rows retired had outlived their entry for six days as orphan commands, which is the
# registry-greener-than-reality shape one level down. They are deleted as standalone rituals
# and survive as on-request lenses of the one spine — an exemption retires a clock, not a
# capability.
EXEMPT: dict[str, tuple[str, str]] = {
    "platform": (
        "2026-08-22",
        "Not in the #2832 adopted calendar: its ground (a broad defect sweep) is covered by "
        "the monthly fullreview-full entry's panel, which grades the same surface with "
        "anchors and a trend line; it never ran as a command in its own right. Revive "
        "deliberately with its own entry if that panel proves too narrow for a defect hunt — "
        "do not let it half-exist off-calendar.",
    ),
    "site": (
        "2026-08-22",
        "Owner-attended editorial walkthrough of the public site — run when the site's "
        "story changes (a redesign, a new door), not on a clock. Cadencing an editorial "
        "judgment would manufacture runs with nothing to judge; the accuracy-full entry "
        "owns the site's monthly truth pass.",
    ),
    "journey": (
        "2026-08-22",
        "Re-audits the chat↔platform integration after integration work, event-driven by "
        "construction. The #2832 calendar cadences standing judgment; a ritual whose "
        "trigger is 'the seam changed' has an event for a clock already.",
    ),
}


# ── Probes ────────────────────────────────────────────────────────────────────
def _parse_date(s: str) -> date | None:
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def newest_run(entry: dict, repo: str = REPO) -> date | None:
    """The newest dated artifact this ritual's probe can see, or None (never ran)."""
    kind, target, pattern = entry["probe"]
    rx = re.compile(pattern)
    dates: list[date] = []
    if kind == NEWEST_DATED_FILE:
        d = os.path.join(repo, target)
        if os.path.isdir(d):
            for name in os.listdir(d):
                m = rx.match(name)
                if m:
                    parsed = _parse_date(m.group(1))
                    if parsed:
                        dates.append(parsed)
    elif kind == REGEX_IN_FILE:
        path = os.path.join(repo, target)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    m = rx.match(line)
                    if m:
                        parsed = _parse_date(m.group(1))
                        if parsed:
                            dates.append(parsed)
    else:  # pragma: no cover — well-formedness test pins the kinds
        raise ValueError(f"unknown probe kind {kind!r}")
    return max(dates) if dates else None


# ── The dead-man ──────────────────────────────────────────────────────────────
OK = "OK"
NEVER = "NEVER-RUN"  # #3250 — the artifact has never existed; an anchor is not a run
HELD = "HELD"  # a dated, reasoned, one-time deferral is in force (see `hold`)
SCHEDULED = "SCHEDULED"  # #3378 — declared `starts`; the first occurrence has not arrived yet
DUE = "DUE"  # inside the grace window — run it now, nothing screams yet
OVERDUE = "OVERDUE"  # past cadence + grace — the scheduled workflow reds on this

# The exit codes `main()` returns under --due. Named because the workflow log and the
# tests both read them, and an undocumented integer is how a distinct signal becomes
# invisible again.
EXIT_CLEAN = 0
EXIT_OVERDUE = 1
EXIT_BAD_ARG = 2
EXIT_NEVER_RUN = 3


def _hold_dates(entry: dict) -> tuple[date, date] | None:
    """(declared, until) for an entry carrying a hold, else None."""
    hold = entry.get("hold")
    if not hold:
        return None
    declared, until, _reason = hold
    d, u = _parse_date(declared), _parse_date(until)
    if d is None or u is None:  # pragma: no cover — well-formedness test pins the shape
        raise ValueError(f"hold dates must be YYYY-MM-DD, got {declared!r}/{until!r}")
    return d, u


def status(entry: dict, today: date, repo: str = REPO) -> dict:
    """One ritual's dead-man verdict.

    Clock = max(newest artifact, ADOPTED, hold.until, starts). The clock floor is what the
    anchor, a hold and a declared start move; the STATE is what none of them may fake.
    `never_ran` travels beside `state` so a caller can act on the distinction the display
    used to own alone.
    """
    last = newest_run(entry, repo)
    hold = _hold_dates(entry)
    starts = _parse_date(entry["starts"]) if entry.get("starts") else None
    floor = ADOPTED
    if hold:
        floor = max(floor, hold[1])
    if starts:
        floor = max(floor, starts)
    clock = max(last, floor) if last else floor
    due_by = clock + timedelta(days=entry["cadence_days"])
    hard_by = due_by + timedelta(days=entry["grace_days"])
    if today > hard_by:
        state = OVERDUE
    elif today > due_by:
        state = DUE
    elif last is None:
        # #3250: this is the branch that used to say OK. A ritual with no artifact has
        # produced no evidence, and a hold does NOT override it — deferring a ritual
        # cannot manufacture a run that never happened.
        #
        # #3378: unless the entry declared a dated FIRST occurrence that has not arrived
        # (`starts`), in which case "never run" is a schedule fact, not an absence — and
        # note the two branches above already ran, so a declared start can no more hide a
        # DUE or an OVERDUE than the anchor can.
        state = SCHEDULED if starts else NEVER
    elif hold and today <= hold[1]:
        state = HELD
    else:
        state = OK
    return {
        "last": last,
        "clock": clock,
        "due_by": due_by,
        "hard_by": hard_by,
        "state": state,
        "never_ran": last is None,
        "held_until": hold[1] if hold else None,
        "starts": starts,
    }


def due_report(today: date, repo: str = REPO) -> tuple[str, list[str], list[str]]:
    """(human table, [names of OVERDUE rituals], [names of rituals that NEVER ran])."""
    lines = [f"Platform Operating Calendar — dead-man sweep as of {today} (#2832, #3250)", ""]
    overdue: list[str] = []
    never: list[str] = []
    held: list[str] = []
    scheduled: list[str] = []
    width = max(len(n) for n in CALENDAR)
    for name in sorted(CALENDAR, key=lambda n: CALENDAR[n]["cadence_days"]):
        st = status(CALENDAR[name], today, repo)
        if st["last"]:
            last_s = st["last"].isoformat()
        elif st["state"] == SCHEDULED:
            # "never (anchored ...)" would be true and misleading here: this row's clock
            # has not started, so there is nothing yet to be absent (#3378).
            last_s = f"not started (starts {st['starts']})"
        else:
            last_s = f"never (anchored {ADOPTED})"
        lines.append(
            f"  {name:<{width}}  every {CALENDAR[name]['cadence_days']:>3}d"
            f"  last {last_s:<26}  due {st['due_by']}  hard {st['hard_by']}  {st['state']}"
        )
        if st["state"] == OVERDUE:
            overdue.append(name)
        # The NEVER *state*, not the raw `never_ran` fact: an entry whose declared first
        # occurrence has not arrived reads SCHEDULED, and calling that "never ran" would
        # red the daily sweep for a month over a ritual nobody is late for (#3378).
        if st["state"] == NEVER:
            never.append(name)
        if st["state"] == HELD:
            held.append(name)
        if st["state"] == SCHEDULED:
            scheduled.append(name)
    if held:
        lines += ["", "⏸  held by a dated decision (clock re-anchored once, reason in the registry):"]
        for name in held:
            declared, until, reason = CALENDAR[name]["hold"]
            lines.append(f"   {name}: declared {declared}, resumes {until} — {reason.split('.')[0]}.")
    if scheduled:
        lines += ["", "🗓  scheduled — declared first occurrence has not arrived (never-run is not late here):"]
        for name in scheduled:
            st = status(CALENDAR[name], today, repo)
            lines.append(f"   {name}: starts {CALENDAR[name]['starts']}, first due {st['due_by']}, hard {st['hard_by']}.")
    if overdue:
        lines += [
            "",
            f"❌ {len(overdue)} ritual(s) OVERDUE: {', '.join(overdue)}",
            "   A missed judgment ritual is the filing rate silently dropping to zero for",
            "   that lens. Run the ritual (its artifact resets the clock) — do not",
            "   re-anchor, and do not exempt without a dated reason in EXEMPT.",
        ]
    if never:
        lines += [
            "",
            f"⚠️  {len(never)} ritual(s) have NEVER produced their artifact: {', '.join(never)}",
            "   Their windows are open because of the adoption anchor, not because anything",
            "   ran. An anchor is a grant, not evidence — this sweep cannot say these rituals",
            "   happened, and it will not print OK as if it could (#3250). Clear it by RUNNING",
            "   the ritual, or by retiring it with a dated EXEMPT row. Re-anchoring is not a",
            f"   clearing. (--due exits {EXIT_NEVER_RUN} on this state.)",
        ]
    if not overdue and not never:
        tail = " (the scheduled rows above have not reached their first occurrence)." if scheduled else "."
        lines += ["", f"✅ no ritual outside its window, and every started ritual has run at least once{tail}"]
    return "\n".join(lines), overdue, never


# ── The set guard, factored for mutation-proofing ─────────────────────────────
def _skill_registry():
    """Import the ONE skill registry lazily (keeps module import cheap and test-stubbable)."""
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill_registry.py")
    spec = importlib.util.spec_from_file_location("_skill_registry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def review_lenses(repo: str = REPO) -> dict[str, str]:
    """Every `/review <lens>` rubric: lens name -> repo-relative rubric path.

    Filesystem-derived through the ONE skill registry, never a hand list: a rubric file is
    discovered the moment it exists, which is what makes an unclassified lens loud instead
    of green-by-default. Only `references/*.md` beside the spine count — a nested helper or
    a non-markdown asset is content, not a lens.
    """
    reg = _skill_registry()
    return {p.stem: reg.rel(p) for p in reg.skill_references(REVIEW_SPINE) if p.suffix == ".md" and p.parent.name == "references"}


def standalone_review_skills(repo: str = REPO) -> dict[str, str]:
    """Review-family skills still living OUTSIDE the spine: name -> repo-relative path.

    Name-based on purpose (*review* + frontier-plan): a skill's text can say anything, but
    its NAME is what sessions invoke. The spine itself is excluded — it grades nothing on
    its own clock; its lenses do, and counting it would demand a meaningless calendar row.
    Blind spot, stated: a judgment ritual named neither *review* nor frontier-plan (e.g.
    cost-diligence) is not discovered — the registry half still catches it the moment an
    entry or exemption names it.
    """
    reg = _skill_registry()
    skills = reg.skills()
    fam = {n for n in skills if "review" in n} | ({"frontier-plan"} & set(skills))
    return {n: reg.rel(skills[n]) for n in sorted(fam - {REVIEW_SPINE})}


def review_procedures(repo: str = REPO) -> dict[str, str]:
    """The full discovered set: procedure name -> the file that DEFINES it.

    Two namespaces, ONE set, because since #3250 the unit of ritual is a LENS rather than a
    file. A collision between the two halves would silently hide one of them, so it raises
    rather than resolving quietly (the `duplicates()` precedent in the skill registry).
    """
    lenses, standalone = review_lenses(repo), standalone_review_skills(repo)
    clash = set(lenses) & set(standalone)
    if clash:  # pragma: no cover — well-formedness test pins the invariant
        raise ValueError(f"a /review lens and a standalone review skill share a name: {sorted(clash)}")
    return {**lenses, **standalone}


def classification_gaps(calendar: dict, exempt: dict, discovered) -> tuple[set[str], set[str]]:
    """(unclassified, phantom): discovered procedures with no calendar/exempt row, and
    calendar/exempt rows naming a procedure that does not exist. Both must be empty —
    guard the SET, not the instance.

    `discovered` may be the dict from review_procedures() or a bare set of names. The
    phantom direction is what enforces "every calendar entry names a procedure that
    EXISTS" (#3250): a `lens` with no rubric file, or an exemption for a deleted ritual,
    is a phantom the moment it is written rather than the day someone notices.
    """
    classified = {e["lens"] for e in calendar.values() if e.get("lens")}
    classified |= {e["skill"] for e in calendar.values() if e["skill"] and e["skill"] != REVIEW_SPINE}
    classified |= set(exempt)
    found = set(discovered)
    return found - classified, {s for s in classified if s not in found}


# ── The generated doc (#2986 DERIVED: writer --apply, guard --check, lane docs-ci) ──
def render_doc() -> str:
    out = [
        "# The Platform Operating Calendar",
        "",
        "> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-22",
        "",
        "> **GENERATED** from `scripts/operating_calendar.py` (#2832, epic #2800) — edit the",
        "> registry, run `python3 scripts/operating_calendar.py --apply`, never this file.",
        "> Live due-state: `python3 scripts/operating_calendar.py --due` (the dead-man runs",
        "> daily in `.github/workflows/operating-calendar.yml`; a red run reaches the",
        "> remediation agent's triage email). This file is the ONE cadence truth —",
        "> `docs/REVIEW_METHODOLOGY.md`'s cadence section is retired in its favor.",
        "",
        "A judgment ritual that silently stops running is the filing rate dropping to zero",
        "for that lens while every deterministic gate stays green. The calendar makes the",
        "miss louder than the run: each ritual advances its clock only by producing its",
        "dated artifact, and the dead-man reds when a window closes empty.",
        "",
        "| Ritual | Procedure | Cadence | Grace | Attendance | Run artifact (the clock) |",
        "|---|---|---|---|---|---|",
    ]
    for name in sorted(CALENDAR, key=lambda n: (CALENDAR[n]["cadence_days"], n)):
        e = CALENDAR[name]
        if e["lens"]:
            skill = f"`/{e['skill']} {e['lens']}`"
        elif e["skill"]:
            skill = f"`/{e['skill']}`"
        else:
            skill = "ledger re-read"
        kind, target, pattern = e["probe"]
        probe_s = f"`{target}/` · `{pattern}`" if kind == NEWEST_DATED_FILE else f"dated line in `{target}` · `{pattern}`"
        out.append(f"| {name} | {skill} | {e['cadence_days']}d | +{e['grace_days']}d | {e['attendance']} | {probe_s} |")
    out += ["", "## Standing obligations (re-homed onto entries — they die with sessions otherwise)", ""]
    for name in sorted(CALENDAR):
        for ob in CALENDAR[name]["obligations"]:
            out.append(f"- **{name}**: {ob}")
    out += ["", "## Why each entry (registry reasons, verbatim)", ""]
    for name in sorted(CALENDAR):
        out.append(f"- **{name}** — {CALENDAR[name]['reason']}")
    procedures = review_procedures()
    out += [
        "",
        "## The guarded SET — every judgment procedure, classified (#3250)",
        "",
        "Discovered from the tree, not hand-listed: each `/review <lens>` rubric beside",
        "`.claude/skills/review/SKILL.md`, plus any review-family skill still standing outside",
        "the spine. Every row below is either ON the calendar above or carries a dated exemption",
        "underneath. Both directions are asserted — an unclassified rubric fails the guard, and",
        "so does a calendar entry naming a rubric nobody wrote. That second direction is what",
        "makes the phantom-procedure defect (a clock counting down toward a mode nothing",
        "implements) unwritable rather than merely noticed.",
        "",
        "| Procedure | Defined in | Classified as |",
        "|---|---|---|",
    ]
    for name in sorted(procedures):
        on_calendar = sorted(n for n, e in CALENDAR.items() if e.get("lens") == name or (e["skill"] == name and not e.get("lens")))
        where = ", ".join(f"`{n}`" for n in on_calendar) if on_calendar else f"EXEMPT ({EXEMPT[name][0]})"
        out.append(f"| {name} | `{procedures[name]}` | {where} |")
    out += ["", "### Dated exemptions (the set guard's other half)", ""]
    for name in sorted(EXEMPT):
        d, reason = EXEMPT[name]
        out.append(f"- **{name}** ({d}) — {reason}")
    out += [
        "",
        "## Scheduled first occurrences (a ritual whose clock starts later, #3378)",
        "",
        "An entry may declare `starts` — the dated day its clock BEGINS — when its first",
        "occurrence is genuinely in the future (the 2026-09-01 launch checkpoints). Until that",
        "first occurrence passes, a row with no artifact reads `SCHEDULED` rather than",
        "`NEVER-RUN`, because a checkpoint due in October is not a ritual anybody has stopped",
        "doing. `starts` moves the CLOCK only: the day the first occurrence passes, an",
        "artifact-less row goes `DUE` and then `OVERDUE` like any other, so absence is still",
        "louder than failure — at the right time instead of a month early. A first occurrence",
        f"more than {MAX_SCHEDULE_AHEAD_DAYS} days past adoption fails the guard: a row that can",
        "never be late is decoration.",
        "",
    ]
    scheduled = [n for n in sorted(CALENDAR) if CALENDAR[n]["starts"]]
    if scheduled:
        out += ["| Ritual | Clock starts | First occurrence | Hard by |", "|---|---|---|---|"]
        for name in scheduled:
            e = CALENDAR[name]
            first = _parse_date(e["starts"]) + timedelta(days=e["cadence_days"])
            hard = first + timedelta(days=e["grace_days"])
            out.append(f"| {name} | {e['starts']} | {first} | {hard} |")
    else:
        out.append("_None declared._")
    out += ["", "## Dated holds (a deferral is a decision, #3250)", ""]
    holds = [n for n in sorted(CALENDAR) if CALENDAR[n]["hold"]]
    if holds:
        for name in holds:
            declared, until, reason = CALENDAR[name]["hold"]
            out.append(f"- **{name}** — declared {declared}, resumes {until}. {reason}")
    else:
        out.append("_None in force._")
    out += [
        "",
        "A hold re-anchors ONE entry's clock ONE time, with a date and a written reason, so a",
        "deliberate skip is discharged by a decision instead of a silent lapse. It is bounded",
        f"(at most {MAX_HOLD_DAYS} days) and it never suppresses the NEVER-RUN verdict below:",
        "deferring a ritual cannot manufacture evidence that it ever happened. A skip that",
        "wants to be permanent belongs in the exemption list above, not in a hold.",
        "",
        "## The anchor rule — and what an anchor may NOT do",
        "",
        f"Every clock starts at `max(newest artifact, {ADOPTED})` — the calendar's adoption",
        "date. Without it the dead-man is born red on rituals that never ran (craft-review),",
        "which blocks on history instead of behavior. Never bump the anchor to silence an",
        "overdue ritual: the artifact is the only honest reset.",
        "",
        "The anchor holds the **window** open. Since #3250 it no longer holds the **verdict**",
        "green: a ritual with no artifact reports `NEVER-RUN`, never `OK`, and `--due` exits",
        f"`{EXIT_NEVER_RUN}` for it (`{EXIT_OVERDUE}` stays reserved for OVERDUE, so the log",
        "distinguishes 'somebody stopped doing this' from 'nobody has ever done this'). The",
        "distinction used to live only in the display string `last never (anchored …)` while",
        "the verdict said OK — a dead-man green because it was anchored rather than because",
        "the ritual ran is the exact lying-gauge shape this calendar exists to kill.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--due", action="store_true", help="dead-man sweep; exit 1 on any OVERDUE ritual")
    ap.add_argument("--today", default=None, help="override today (YYYY-MM-DD) — tests/reproduction")
    ap.add_argument("--check", action="store_true", help=f"exit 1 if {DOC_PATH} drifted from the registry")
    ap.add_argument("--apply", action="store_true", help=f"regenerate {DOC_PATH}")
    args = ap.parse_args(argv)

    doc_abs = os.path.join(REPO, DOC_PATH)
    if args.apply:
        with open(doc_abs, "w", encoding="utf-8") as fh:
            fh.write(render_doc())
        print(f"✅ wrote {DOC_PATH} ({len(CALENDAR)} rituals, {len(EXEMPT)} exemptions)")
        return 0
    if args.check:
        current = open(doc_abs, encoding="utf-8").read() if os.path.isfile(doc_abs) else ""
        if current != render_doc():
            print(f"❌ {DOC_PATH} is STALE against scripts/operating_calendar.py — fix: python3 scripts/operating_calendar.py --apply")
            return 1
        print(f"✅ {DOC_PATH} matches the registry.")
        return 0

    today = _parse_date(args.today) if args.today else date.today()
    if args.today and not today:
        print(f"❌ --today {args.today!r} is not YYYY-MM-DD")
        return EXIT_BAD_ARG
    report, overdue, never = due_report(today)
    print(report)
    if not args.due:
        return EXIT_CLEAN
    if overdue:
        return EXIT_OVERDUE
    return EXIT_NEVER_RUN if never else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
