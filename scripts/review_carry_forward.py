#!/usr/bin/env python3
"""scripts/review_carry_forward.py — the carried set, aged (#3603, epic #3593).

WHY THIS EXISTS
---------------
A `/review full` delta re-grades the rows the change surface can have moved and carries the
rest forward in the artifact's `unchanged_lenses`. That claim was written honestly and aged
by nothing: at the 2026-09-05 baseline, 8 of the 17 panel rows were last graded from scratch
on 07-28/08-02 and had ridden two deltas since. A grade carried five weeks read exactly like
a grade carried a week, and the trend line drawn through them described a surface nobody had
looked at in over a month.

WHAT THIS IS
------------
The assembler for the carried set, and the reader of a run's planted-control result:

* ``carried_lenses`` — what one artifact claims it did NOT re-grade, and which run each
  carried grade came from;
* ``scratch_dates`` — per lens, the run that last graded it FROM SCRATCH. A citation can
  only ever make a grade older, never fresher: deltas cite each other, and believing a
  citation would launder a five-week-old grade into a one-week-old one on every hop;
* ``expired_carry_forward`` — the rows past ``CARRY_FORWARD_MAX_DAYS``. They are DROPPED
  from the carried set and surfaced as "expired, re-verify or refile";
* ``calibration_verdict`` / ``calibrated_run`` — a run whose verifiers CONFIRMED a planted
  false finding is UNCALIBRATED, and an uncalibrated run is not evidence that the ritual
  happened, so it does not advance the ritual's clock.

It lives beside ``scripts/operating_calendar.py`` rather than inside it because that file
is at its module-size ceiling (#1665) — the calendar imports these names and keeps owning
the clock.

v1.0.0 — 2026-09-19 (#3603)
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_date(s: str) -> date | None:
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


#: Days a lens grade may be carried forward from the run that last graded it FROM
#: SCRATCH. Past this, the carried grade is expired: it is dropped from the carried set,
#: surfaced as "re-verify or refile", and the next delta must select the row regardless of
#: what the diff touched. 28 days = four weekly deltas, the point at which "the platform
#: was looked at" stops being a defensible reading of a carried letter.
CARRY_FORWARD_MAX_DAYS = 28

#: The artifact family the cap is measured over (the `full` lens's grades JSONs).
GRADES_DIR = "docs/reviews"
GRADES_RE = re.compile(r"^fullreview_grades_(\d{4}-\d{2}-\d{2})(?:_delta|_partial)?\.json$")

CALIBRATED = "CALIBRATED"
UNCALIBRATED = "UNCALIBRATED"  # verifiers confirmed a planted false finding — the run is not evidence
UNSTATED = "UNSTATED"  # the artifact carries no calibration block (every run before #3603)
# #3919 (2026-09-20): calibration is MANDATORY for every review run from the day #3603's
# planted controls landed. An UNSTATED artifact dated on/after this day is treated as a
# MISSING run — it neither advances a lens's from-scratch date nor satisfies a review clock.
# Artifacts before it could not have stated a calibration and are grandfathered (the six
# committed runs 2026-07-16 → 2026-09-05 are all UNSTATED; arming a gate over history is how
# a gate is born red and then ignored). The date is #3603's own: v1.4.0 of operating_calendar.
CALIBRATION_REQUIRED_FROM = date(2026, 9, 19)


def run_counts(run: dict, when: date | None) -> bool:
    """May THIS artifact advance a clock? UNCALIBRATED never; UNSTATED only when dated
    before CALIBRATION_REQUIRED_FROM (or undated — a parse gap is not a verdict)."""
    verdict = calibration_verdict(run)
    if verdict == UNCALIBRATED:
        return False
    if verdict == UNSTATED and when is not None and when >= CALIBRATION_REQUIRED_FROM:
        return False
    return True


def artifact_date(path: str, run: dict | None = None) -> date | None:
    """The run's date: the filename's (the calendar's own keying), else the JSON's `date`."""
    m = GRADES_RE.match(os.path.basename(path))
    if m:
        return _parse_date(m.group(1))
    return _parse_date(str((run or {}).get("date", ""))[:10])


_DATE_IN_TEXT = re.compile(r"(\d{4}-\d{2}-\d{2})")


def calibration_verdict(run: dict) -> str:
    """CALIBRATED / UNCALIBRATED / UNSTATED for one grades JSON.

    UNCALIBRATED is claimed two ways and either is enough: the run says so in
    `calibration.verdict`, or its own numbers say so (a planted false finding that came
    back CONFIRMED, or a withheld known issue nothing found). A run grading its own
    controls green while its numbers say otherwise is exactly the failure mode the
    controls exist to catch, so the numbers win.
    """
    cal = run.get("calibration")
    if not isinstance(cal, dict):
        return UNSTATED
    if str(cal.get("verdict", "")).strip().upper() == UNCALIBRATED:
        return UNCALIBRATED
    planted = cal.get("planted_false_findings") or {}
    withheld = cal.get("withheld_known_issues") or {}
    if isinstance(planted, dict) and planted.get("confirmed_by_verifiers"):
        return UNCALIBRATED
    if isinstance(withheld, dict) and withheld.get("missed_by_graders"):
        return UNCALIBRATED
    return CALIBRATED if str(cal.get("verdict", "")).strip().upper() == CALIBRATED else UNSTATED


def calibrated_run(path: str) -> bool:
    """Entry qualifier: may this artifact advance a review clock? A JSON we cannot read is
    treated as a run (the probe's job is cadence, not schema validation — a parse error
    must not silently stop a clock), an UNCALIBRATED one is not."""
    try:
        with open(path, encoding="utf-8") as fh:
            run = json.load(fh)
    except (OSError, ValueError):
        return True
    return run_counts(run, artifact_date(path, run))  # #3919: UNSTATED after the cutoff is a missing run


def carried_lenses(run: dict) -> dict[str, date | None]:
    """{lens: the date of the run that graded it from scratch} from one artifact's
    `unchanged_lenses`, or {} if it carried nothing forward.

    The structured form is the contract going forward ({"cpo": "2026-08-02"}); the prose
    form is what four committed artifacts actually carry ("cpo, designer (2026-08-02 delta
    / 2026-07-28 partial) — grades stand."), so it is parsed best-effort: names before the
    citation, and the OLDEST date cited, because a grade carried through a chain is only as
    fresh as the run that actually looked. A carried lens naming no run at all maps to None
    — an unfalsifiable carry, which the cap treats as expired rather than as fresh.
    """
    raw = run.get("unchanged_lenses")
    out: dict[str, date | None] = {}
    if isinstance(raw, dict):
        for lens, since in raw.items():
            out[str(lens).strip().lower()] = _parse_date(str(since)[:10])
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                lens = str(item.get("lens", "")).strip().lower()
                if lens:
                    out[lens] = _parse_date(str(item.get("since") or item.get("from") or "")[:10])
            elif isinstance(item, str):
                out.update(carried_lenses({"unchanged_lenses": item}))
        return out
    if not isinstance(raw, str) or not raw.strip():
        return out
    for chunk in raw.split(";"):
        dates = [d for d in (_parse_date(m) for m in _DATE_IN_TEXT.findall(chunk)) if d]
        cited = min(dates) if dates else None
        head = chunk.split("(")[0] if "(" in chunk else re.split(r"—|--| see | from ", chunk)[0]
        for token in head.split(","):
            name = token.strip().strip(".").lower()
            if name and re.fullmatch(r"[a-z][a-z0-9/_-]{1,24}", name):
                out[name] = cited
    return out


def scratch_dates(runs: list[tuple[date, dict]]) -> dict[str, date | None]:
    """{lens: the newest date it was graded FROM SCRATCH} across a run history.

    A lens present in a run's `lenses` and NOT named in that run's `unchanged_lenses` was
    graded by that run. A lens the run carried forward inherits the date it cites, never
    the run's own date — the one-line statement of the whole defect — and a citation can
    only ever make a grade OLDER, never fresher (see the loop).
    """
    out: dict[str, date | None] = {}
    for run_date, run in sorted(runs, key=lambda r: r[0]):
        carried = carried_lenses(run)
        # #3919: a run that does not count (UNCALIBRATED, or UNSTATED after the cutoff) grades
        # nothing from scratch — it may still SEED a lens through a citation, never advance one.
        graded = ({str(k).strip().lower() for k in (run.get("lenses") or {})} - set(carried)) if run_counts(run, run_date) else set()
        for lens in graded:
            if lens not in out or out[lens] is None or run_date > out[lens]:
                out[lens] = run_date
        for lens, cited in carried.items():
            # A carry may SEED a lens we have never seen graded, and it may never ADVANCE
            # one we have. Deltas cite each other: a run that carries `qs` "from the
            # 2026-08-08 delta" is citing a run that carried it too, and believing that
            # citation would launder a five-week-old grade into a one-week-old one on every
            # hop. Only grading moves this date forward.
            if lens not in out:
                out[lens] = cited
    return out


def standing_lenses(run: dict) -> set[str]:
    """The lenses the newest artifact still CLAIMS — graded in it, or carried forward by it.

    The cap governs the carried set, and the carried set is whatever the newest artifact
    asserts still stands. Scoping here is load-bearing: `ai-quality` was graded in the
    2026-07-16 run and the panel later renamed it `aiq`, so an unscoped sweep reports a
    retired name as permanently stale — a red nobody can clear, which is how a gate gets
    ignored (the anchor rule, one level down).
    """
    return {str(k).strip().lower() for k in (run.get("lenses") or {})} | set(carried_lenses(run))


def expired_carry_forward(runs, today: date, max_days: int = CARRY_FORWARD_MAX_DAYS) -> list[dict]:
    """The standing lenses whose newest from-scratch grade is older than the cap. Sorted
    oldest first; a lens carried with no source run named is expired by construction (age
    None) — an unfalsifiable carry is not a fresh one."""
    if not runs:
        return []
    standing = standing_lenses(max(runs, key=lambda r: r[0])[1])
    out = []
    for lens, when in sorted(scratch_dates(runs).items(), key=lambda kv: (kv[1] is not None, kv[1] or date.min, kv[0])):
        if lens not in standing:
            continue
        age = (today - when).days if when else None
        if age is None or age > max_days:
            out.append({"lens": lens, "last_scratch": when, "age_days": age, "cap_days": max_days})
    return out


def load_grade_runs(repo: str = REPO) -> list[tuple[date, dict]]:
    """Every `full`-lens grades artifact, newest last. Unreadable files are skipped — the
    cap is a claim about grades, and a file that is not a grades JSON carries none."""
    d = os.path.join(repo, GRADES_DIR)
    runs: list[tuple[date, dict]] = []
    if not os.path.isdir(d):
        return runs
    for name in sorted(os.listdir(d)):
        m = GRADES_RE.match(name)
        when = _parse_date(m.group(1)) if m else None
        if not when:
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                runs.append((when, json.load(fh)))
        except (OSError, ValueError):
            continue
    return runs


def carry_forward_report(today: date, repo: str = REPO) -> tuple[list[str], list[dict]]:
    """(lines for the sweep, the expired rows). Empty second element = every lens grade a
    reader can see today was derived within the cap."""
    runs = load_grade_runs(repo)
    if not runs:
        return (["", "carry-forward: no `full`-lens grades artifact to measure (nothing carried, nothing claimed)."], [])
    expired = expired_carry_forward(runs, today)
    newest_date, newest = runs[-1]
    verdict = calibration_verdict(newest)
    lines = [
        "",
        f"carry-forward cap: {CARRY_FORWARD_MAX_DAYS}d since a lens was graded from scratch "
        f"(newest artifact {newest_date}, calibration {verdict})",
    ]
    if verdict == UNSTATED and run_counts(newest, newest_date):
        lines.append("   calibration UNSTATED — the run recorded no planted-control outcome; it counts, and says so (#3603).")
    elif verdict == UNSTATED:
        lines.append(
            f"   calibration UNSTATED on a run dated {newest_date} ≥ {CALIBRATION_REQUIRED_FROM} — calibration is mandatory; "
            "this artifact counts as a MISSING run and advances nothing (#3919)."
        )
    if not expired:
        lines.append("   ✅ every graded lens is within the cap.")
        return lines, expired
    for row in expired:
        age = f"{row['age_days']}d" if row["age_days"] is not None else "unknown age"
        since = row["last_scratch"].isoformat() if row["last_scratch"] else "no source run named"
        lines.append(f"   ❌ stale carry-forward: {row['lens']} (last graded from scratch {since}, {age}) — expired, re-verify or refile")
    lines += [
        f"   {len(expired)} lens grade(s) are older than the cap. They are DROPPED from the carried set: the next delta",
        "   selects those rows regardless of what the diff touched, and until it does, no artifact may carry them again.",
    ]
    return lines, expired
