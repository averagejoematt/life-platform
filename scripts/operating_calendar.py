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

USAGE
-----
    python3 scripts/operating_calendar.py            # human table, exit 0 always
    python3 scripts/operating_calendar.py --due      # dead-man: exit 1 if any OVERDUE
    python3 scripts/operating_calendar.py --due --today 2026-12-01   # deterministic (tests)
    python3 scripts/operating_calendar.py --check    # docs/OPERATING_CALENDAR.md drift → exit 1
    python3 scripts/operating_calendar.py --apply    # regenerate docs/OPERATING_CALENDAR.md

v1.0.0 — 2026-08-22 (#2832)
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


def _entry(skill, cadence_days, grace_days, attendance, probe, obligations, reason):
    return {
        "skill": skill,  # .claude/commands/<skill>.md, or None for a doc-only ritual
        "cadence_days": cadence_days,
        "grace_days": grace_days,
        "attendance": attendance,
        "probe": probe,  # (kind, relative dir-or-file, regex with one date group)
        "obligations": tuple(obligations),
        "reason": reason,
    }


CALENDAR: dict[str, dict] = {
    # ── Weekly ────────────────────────────────────────────────────────────────
    "fullreview-delta": _entry(
        skill="fullreview",
        cadence_days=7,
        grace_days=3,
        attendance=AUTONOMOUS,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta|_partial)?\.json$"),
        obligations=(),
        reason=(
            "The one review family that was still alive at #2832's filing — weekly-ish and "
            "shrinking (17→7 lenses). Weekly delta keeps the grades comparable session to "
            "session; any fullreview run (full, delta or partial) resets this clock, because "
            "the weekly claim is 'the platform was looked at', not 'the look was small'."
        ),
    ),
    # ── Monthly ───────────────────────────────────────────────────────────────
    "fullreview-full": _entry(
        skill="fullreview",
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
        skill="accuracy-review",
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^EDITORIAL_ACCURACY_REVIEW_(\d{4}-\d{2}-\d{2})\.md$"),
        obligations=(),
        reason=(
            "The truth audit of the public surface (does the site say what the data says?). "
            "Last full run 2026-07-10 at #2832's filing — six weeks dark while the nightly "
            "reader-truth oracle only samples. ADR-104/105 are enforced per-surface by gates; "
            "this is the whole-estate pass."
        ),
    ),
    "craft-review": _entry(
        skill="craft-review",
        cadence_days=31,
        grace_days=7,
        attendance=SESSION,
        probe=(NEWEST_DATED_FILE, "docs/reviews", r"^craft_grades_(\d{4}-\d{2}-\d{2})\.json$"),
        obligations=(),
        reason=(
            "Had NEVER executed at #2832's filing despite its own instruction to register a "
            "scheduled run — the exact silent-stop this calendar exists to make impossible. "
            "Its first run creates docs/reviews/craft_grades_<date>.json and starts the clock "
            "for real; until then the adoption anchor holds the window."
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
        # A step OF the monthly cost close, not a ritual of its own — and `skill` is
        # graded against the review-skill discovery set (names containing "review"),
        # so naming `cost-diligence` here would register as a phantom skill. The
        # obligation below carries the wiring instead.
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
        skill="sdlc-review",
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
}

# ── The set guard's exemptions ────────────────────────────────────────────────
# Discovery (see tests/test_operating_calendar_2832.py) enumerates every review-family
# skill in .claude/commands (*review*.md + frontier-plan.md). Each one is either ON the
# calendar above or HERE with a dated reason. An undated or reasonless exemption is the
# old failure mode — "we'll get to it" with no clock.
EXEMPT: dict[str, tuple[str, str]] = {
    "platform-review": (
        "2026-08-22",
        "Not in the #2832 adopted calendar: its ground (full-platform sweep) is covered by "
        "the monthly fullreview-full entry's panel; it has never run as a command since it "
        "landed. Revive deliberately with its own entry if the fullreview panel proves too "
        "narrow — do not let it half-exist off-calendar.",
    ),
    "site-review": (
        "2026-08-22",
        "Owner-attended editorial walkthrough of the public site — run when the site's "
        "story changes (a redesign, a new door), not on a clock. Cadencing an editorial "
        "judgment would manufacture runs with nothing to judge; the accuracy-full entry "
        "owns the site's monthly truth pass.",
    ),
    "journey-review": (
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
DUE = "DUE"  # inside the grace window — run it now, nothing screams yet
OVERDUE = "OVERDUE"  # past cadence + grace — the scheduled workflow reds on this


def status(entry: dict, today: date, repo: str = REPO) -> dict:
    """One ritual's dead-man verdict. Clock = max(newest artifact, ADOPTED)."""
    last = newest_run(entry, repo)
    clock = max(last, ADOPTED) if last else ADOPTED
    due_by = clock + timedelta(days=entry["cadence_days"])
    hard_by = due_by + timedelta(days=entry["grace_days"])
    if today > hard_by:
        state = OVERDUE
    elif today > due_by:
        state = DUE
    else:
        state = OK
    return {"last": last, "clock": clock, "due_by": due_by, "hard_by": hard_by, "state": state}


def due_report(today: date, repo: str = REPO) -> tuple[str, list[str]]:
    """(human table, [names of OVERDUE rituals])."""
    lines = [f"Platform Operating Calendar — dead-man sweep as of {today} (#2832)", ""]
    overdue: list[str] = []
    width = max(len(n) for n in CALENDAR)
    for name in sorted(CALENDAR, key=lambda n: CALENDAR[n]["cadence_days"]):
        st = status(CALENDAR[name], today, repo)
        last_s = st["last"].isoformat() if st["last"] else f"never (anchored {ADOPTED})"
        lines.append(
            f"  {name:<{width}}  every {CALENDAR[name]['cadence_days']:>3}d"
            f"  last {last_s:<26}  due {st['due_by']}  hard {st['hard_by']}  {st['state']}"
        )
        if st["state"] == OVERDUE:
            overdue.append(name)
    if overdue:
        lines += [
            "",
            f"❌ {len(overdue)} ritual(s) OVERDUE: {', '.join(overdue)}",
            "   A missed judgment ritual is the filing rate silently dropping to zero for",
            "   that lens. Run the ritual (its artifact resets the clock) — do not",
            "   re-anchor, and do not exempt without a dated reason in EXEMPT.",
        ]
    else:
        lines += ["", "✅ no ritual outside its window."]
    return "\n".join(lines), overdue


# ── The set guard, factored for mutation-proofing ─────────────────────────────
def review_skill_files(repo: str = REPO) -> set[str]:
    """Discovery: every review-family skill name in .claude/commands.

    Filename-based on purpose (*review* + frontier-plan): a skill's text can say
    anything, but its NAME is what sessions invoke. Blind spot, stated: a judgment
    ritual not named *review* (e.g. cost-diligence) is not discovered — the registry
    half still catches it the moment an entry or exemption names it.
    """
    d = os.path.join(repo, ".claude", "commands")
    names = {f[:-3] for f in os.listdir(d) if f.endswith(".md")}
    return {n for n in names if "review" in n} | ({"frontier-plan"} & names)


def classification_gaps(calendar: dict, exempt: dict, discovered: set[str]) -> tuple[set[str], set[str]]:
    """(unclassified, phantom): review skills with no calendar/exempt row, and
    calendar/exempt rows naming a skill that no longer exists. Both must be empty —
    guard the SET, not the instance."""
    classified = {e["skill"] for e in calendar.values() if e["skill"]} | set(exempt)
    return discovered - classified, {s for s in classified if s not in discovered}


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
        "| Ritual | Skill | Cadence | Grace | Attendance | Run artifact (the clock) |",
        "|---|---|---|---|---|---|",
    ]
    for name in sorted(CALENDAR, key=lambda n: (CALENDAR[n]["cadence_days"], n)):
        e = CALENDAR[name]
        skill = f"`/{e['skill']}`" if e["skill"] else "ledger re-read"
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
    out += ["", "## Off-calendar review skills (dated exemptions, the set guard's other half)", ""]
    for name in sorted(EXEMPT):
        d, reason = EXEMPT[name]
        out.append(f"- **{name}** ({d}) — {reason}")
    out += [
        "",
        "## The anchor rule",
        "",
        f"Every clock starts at `max(newest artifact, {ADOPTED})` — the calendar's adoption",
        "date. Without it the dead-man is born red on rituals that never ran (craft-review),",
        "which blocks on history instead of behavior. Never bump the anchor to silence an",
        "overdue ritual: the artifact is the only honest reset.",
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
        return 2
    report, overdue = due_report(today)
    print(report)
    return 1 if (args.due and overdue) else 0


if __name__ == "__main__":
    sys.exit(main())
