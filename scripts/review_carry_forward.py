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
  happened, so it does not advance the ritual's clock;
* ``withheld_missed_lenses`` — the withheld-issue control scored PER ROW (#5914). A planted
  false finding tests the verifiers, who see every row, so a confirmed one fails the run. A
  withheld issue tests ONE grader's recall in ONE area, so a miss fails that row: the lens
  keeps its expired from-scratch date and every other lens in the run advances. Two
  consecutive full runs (2026-10-31, 2026-11-13) refuted every planted control and were
  still voided whole — 17 rows each — by a single row's miss.

* ``control_defects`` / ``check_control_plan`` / ``grader_context`` — the two control-DESIGN
  defects of 2026-11-13, made checkable (#5914). A withheld issue nobody reproduced before
  launch may have nothing to find; one a prior artifact's calibration block already names is
  not blind. ``--check-controls PLAN.json`` refuses both before the run launches,
  ``--grader-context LENS`` prints the ONLY part of the prior artifact a grader may be handed
  (its lens's path-to-A list, minus any step naming a planned control), and the sweep names
  the lenses whose control in the newest run had either defect. Identities stay out of every
  line these print: a control is named by its lens, never by its issue.

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
# #5914: the verifiers passed every planted control and at least one lens found (or was not
# given) a withheld issue, but at least one lens missed its own. The run counts; the lenses
# that missed do not advance.
PARTIAL = "PARTIALLY_CALIBRATED"
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


def _issue_set(value) -> set[str]:
    return {str(v).strip() for v in value if str(v).strip()} if isinstance(value, (list, tuple, set)) else set()


def withheld_missed_lenses(run: dict) -> set[str] | None:
    """The lenses that missed a withheld issue of their OWN, or None when the artifact does
    not attribute its withheld issues to lenses (#5914).

    The per-row shape is `calibration.withheld_known_issues.by_lens`:
    ``{"security": {"withheld": ["#5543"], "found": [], "missed": ["#5543"]}}``. None means
    "this artifact cannot be scored per row" and the caller falls back to the run-level
    rule, so every artifact committed before #5914 keeps the verdict it had.

    Attribution has to be COMPLETE to count. If `missed_by_graders` names an issue that no
    lens's `missed` list owns, the artifact is claiming a miss nobody is accountable for —
    that is the run-level shape wearing a per-row label, and it is scored as the run-level
    shape (None). A lens that lists an issue as withheld and as neither found nor missed
    has an unreported outcome, which is a miss: silence is not a pass.
    """
    cal = run.get("calibration")
    withheld = cal.get("withheld_known_issues") if isinstance(cal, dict) else None
    by_lens = withheld.get("by_lens") if isinstance(withheld, dict) else None
    if not isinstance(by_lens, dict) or not by_lens:
        return None
    missed_lenses: set[str] = set()
    owned: set[str] = set()
    for lens, row in by_lens.items():
        if not isinstance(row, dict):
            return None
        missed = _issue_set(row.get("missed")) | (_issue_set(row.get("withheld")) - _issue_set(row.get("found")))
        owned |= missed
        if missed:
            missed_lenses.add(str(lens).strip().lower())
    if _issue_set(withheld.get("missed_by_graders")) - owned:
        return None
    return missed_lenses


def calibration_verdict(run: dict) -> str:
    """CALIBRATED / PARTIALLY_CALIBRATED / UNCALIBRATED / UNSTATED for one grades JSON.

    UNCALIBRATED is claimed two ways and either is enough: the run says so in
    `calibration.verdict`, or its own numbers say so (a planted false finding that came
    back CONFIRMED, or a withheld known issue nothing found). A run grading its own
    controls green while its numbers say otherwise is exactly the failure mode the
    controls exist to catch, so the numbers win.

    The two controls test different things and so fail different things (#5914). A planted
    false finding CONFIRMED is a verifier asleep, and verifiers read every row: the run is
    UNCALIBRATED. A withheld issue missed is one grader's recall in one area: when the
    artifact attributes every miss to its lens (`withheld_missed_lenses`), the run is
    PARTIALLY_CALIBRATED — it counts, and those lenses do not advance. With no attribution,
    or when every graded lens missed, the old run-level rule stands.
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
    missed_lenses = withheld_missed_lenses(run)
    if missed_lenses is None:
        if isinstance(withheld, dict) and withheld.get("missed_by_graders"):
            return UNCALIBRATED
    elif missed_lenses:
        graded = {str(k).strip().lower() for k in (run.get("lenses") or {})} - set(carried_lenses(run))
        return PARTIAL if graded - missed_lenses else UNCALIBRATED
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
        # #5914: a lens that missed its own withheld issue was not graded by an instrument
        # anyone can vouch for — the run counts, that row does not.
        graded -= withheld_missed_lenses(run) or set()
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


def _is_partial(run: dict) -> bool:
    """A `_partial` artifact re-grades the rows it names and says nothing about the rest.
    `load_grade_runs` stamps the filename; a run built in memory has none and is whole."""
    return str(run.get("_artifact", "")).endswith("_partial.json")


def claiming_runs(runs) -> list[tuple[date, dict]]:
    """The newest WHOLE artifact and every partial at or after it, oldest first (#5914).

    A partial run cannot retire a lens — it never looked at the others — so the standing set
    is not the newest file's alone. The 2026-11-14 security-only partial, read as "the newest
    artifact", made the cap govern one lens and report its verdict for a 17-row run of the
    same day that was only partially calibrated.
    """
    ordered = sorted(runs, key=lambda r: (r[0], _is_partial(r[1])))
    whole = [i for i, r in enumerate(ordered) if not _is_partial(r[1])]
    return ordered[whole[-1] :] if whole else ordered[-1:]


def expired_carry_forward(runs, today: date, max_days: int = CARRY_FORWARD_MAX_DAYS) -> list[dict]:
    """The standing lenses whose newest from-scratch grade is older than the cap. Sorted
    oldest first; a lens carried with no source run named is expired by construction (age
    None) — an unfalsifiable carry is not a fresh one."""
    if not runs:
        return []
    standing = set().union(*(standing_lenses(run) for _, run in claiming_runs(runs)))
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
                run = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(run, dict):
            run.setdefault("_artifact", name)  # `_partial` is a fact of the filename only
            runs.append((when, run))
    return runs


# ── the withheld control's DESIGN (#5914): pre-verified, and blind ───────────

#: The rows whose grade is mostly recall, so a run with no withheld issue for one of them
#: has not tested the thing the row is for (the review spine, Phase 2).
RECALL_SENSITIVE_LENSES = ("security", "data-architect", "observability", "integrations")


def _by_lens(run: dict) -> dict:
    cal = run.get("calibration") if isinstance(run, dict) else None
    withheld = cal.get("withheld_known_issues") if isinstance(cal, dict) else None
    by_lens = withheld.get("by_lens") if isinstance(withheld, dict) else None
    return by_lens if isinstance(by_lens, dict) else {}


def named_controls(run: dict) -> set[str]:
    """Every identity one artifact's calibration block spends as a withheld control —
    found, missed or voided. Once committed, none of them can be withheld blind again."""
    cal = run.get("calibration") if isinstance(run, dict) else None
    withheld = cal.get("withheld_known_issues") if isinstance(cal, dict) else None
    if not isinstance(withheld, dict):
        return set()
    out = _issue_set(withheld.get("found")) | _issue_set(withheld.get("missed_by_graders"))
    voided = withheld.get("voided_controls")
    out |= _issue_set(list(voided)) if isinstance(voided, (dict, list)) else set()
    for row in _by_lens(run).values():
        if isinstance(row, dict):
            out |= _issue_set(row.get("withheld")) | _issue_set(row.get("found")) | _issue_set(row.get("missed"))
    return out


def control_defects(run: dict, earlier: list[dict]) -> list[tuple[str, str]]:
    """[(lens, what is wrong with its withheld control)] for one run, given the runs before it.

    These do not change a verdict — a missed control is a miss whatever its design, and a
    found one advances the row either way. They say what the control was WORTH: a miss on an
    issue nobody reproduced may be a stale control (void it), and a find on one a prior
    artifact named is not evidence of recall.
    """
    spent = set().union(*(named_controls(r) for r in earlier)) if earlier else set()
    out: list[tuple[str, str]] = []
    for lens, row in sorted(_by_lens(run).items()):
        if not isinstance(row, dict) or not _issue_set(row.get("withheld")):
            continue
        if not str(row.get("verified_live") or "").strip():
            out.append((str(lens), "not pre-verified against live state (no `verified_live`)"))
        if row.get("blind") is False:
            out.append((str(lens), "recorded as not blind"))
        if _issue_set(row.get("withheld")) & spent:
            out.append((str(lens), "re-uses a control an earlier artifact's calibration block names"))
    return out


def _mentions(text: str, ident: str) -> bool:
    return bool(re.search(r"(?<![\w#])" + re.escape(ident) + r"(?!\w)", text))


def check_control_plan(plan: dict, repo: str = REPO) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a withheld-control plan, BEFORE the run launches.

    `plan` is the `by_lens` block the artifact will carry — `{lens: {withheld: [...],
    verified_live: "..."}}`, bare or under `by_lens` — kept in a scratch file, never in the
    repo. Errors stop the launch: a control with no recorded live reproduction, one owned by
    two lenses, one a committed calibration block already names. Warnings are for the driver
    to act on: a committed review file that mentions a control must not reach its grader,
    and a recall-sensitive row with no control is covered by the verifiers alone.
    """
    rows = plan.get("by_lens") if isinstance(plan.get("by_lens"), dict) else plan
    rows = {str(k).strip().lower(): v for k, v in rows.items() if isinstance(v, dict) and _issue_set(v.get("withheld"))}
    errors: list[str] = []
    warnings: list[str] = []
    spent = set().union(set(), *(named_controls(run) for _, run in load_grade_runs(repo)))
    texts: dict[str, str] = {}
    reviews = os.path.join(repo, GRADES_DIR)
    for name in sorted(os.listdir(reviews)) if os.path.isdir(reviews) else []:
        try:
            with open(os.path.join(reviews, name), encoding="utf-8") as fh:
                texts[name] = fh.read()
        except (OSError, ValueError):
            continue
    owners: dict[str, str] = {}
    for lens, row in sorted(rows.items()):
        if not str(row.get("verified_live") or "").strip():
            errors.append(f"{lens}: no `verified_live` — reproduce the issue in the graded tree or live, and record the command and result")
        for ident in sorted(_issue_set(row.get("withheld"))):
            if ident in owners:
                errors.append(f"{lens}: its control is also owned by {owners[ident]} — one owning lens per withheld issue")
            owners.setdefault(ident, lens)
            if ident in spent:
                errors.append(f"{lens}: its control is named in a committed calibration block — it cannot be withheld blind again")
                continue
            seen = [name for name, text in texts.items() if _mentions(text, ident)]
            if seen:
                warnings.append(
                    f"{lens}: its control is mentioned in {', '.join(seen)} — the grader must not be handed or pointed at these"
                )
    for lens in RECALL_SENSITIVE_LENSES:
        if lens not in rows:
            warnings.append(
                f"{lens}: recall-sensitive row with no withheld issue — covered by the verifier control alone; say so in the artifact"
            )
    return errors, warnings


def grader_context(lens: str, runs: list[tuple[date, dict]], controls=()) -> tuple[date | None, list, int]:
    """(source run date, the lens's prior path-to-A list, steps withheld from it).

    The ONLY part of a prior artifact a grader is handed. The lens's entry describes the
    findings filed from it, and an issue filed from the last review is exactly what gets
    withheld from this one; so a step that names a planned control is dropped, and the count
    goes to the driver (stderr), never into the brief. A step that describes a control
    without naming it cannot be caught here — read the list before it goes out.
    """
    lens = lens.strip().lower()
    for when, run in sorted(runs, key=lambda r: (r[0], _is_partial(r[1])), reverse=True):
        entry = {str(k).strip().lower(): v for k, v in (run.get("lenses") or {}).items()}.get(lens)
        if lens in carried_lenses(run) or not isinstance(entry, dict) or not isinstance(entry.get("path_to_A"), list):
            continue
        steps = [s for s in entry["path_to_A"] if not any(_mentions(json.dumps(s, ensure_ascii=False), c) for c in controls)]
        return when, steps, len(entry["path_to_A"]) - len(steps)
    return None, [], 0


def carry_forward_report(today: date, repo: str = REPO) -> tuple[list[str], list[dict]]:
    """(lines for the sweep, the expired rows). Empty second element = every lens grade a
    reader can see today was derived within the cap."""
    runs = load_grade_runs(repo)
    if not runs:
        return (["", "carry-forward: no `full`-lens grades artifact to measure (nothing carried, nothing claimed)."], [])
    expired = expired_carry_forward(runs, today)
    claiming = claiming_runs(runs)
    newest_date, newest = claiming[0]  # the newest WHOLE artifact; later partials are reported below it
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
    elif verdict == PARTIAL:
        held = ", ".join(sorted(withheld_missed_lenses(newest) or ()))
        lines.append(f"   the run counts; these lenses missed their own withheld issue and did NOT advance (#5914): {held}")
    for when, run in claiming[1:]:
        graded = ", ".join(sorted(str(k) for k in (run.get("lenses") or {}))) or "no lens"
        lines.append(f"   partial run {when} re-graded {graded}: calibration {calibration_verdict(run)}")
    for when, run in claiming:
        for lens, why in control_defects(run, [r for d, r in runs if d < when]):
            lines.append(f"   ⚠️  withheld control, {when} run, {lens}: {why} (#5914) — the row's result says less than it reads")
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


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="The /review full carried set and its withheld-control checks (#3603, #5914).")
    ap.add_argument("--check-controls", metavar="PLAN.json", help="pre-launch: refuse an unverified, shared or already-named control")
    ap.add_argument("--grader-context", metavar="LENS", help="print the lens's prior path-to-A list — all a grader gets of the prior run")
    ap.add_argument("--plan", metavar="PLAN.json", help="with --grader-context: drop steps naming a planned control")
    ap.add_argument("--repo", default=REPO)
    args = ap.parse_args(argv)

    def _plan(path: str) -> dict:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    if args.check_controls:
        errors, warnings = check_control_plan(_plan(args.check_controls), args.repo)
        for line in warnings:
            print(f"⚠️  {line}")
        for line in errors:
            print(f"❌ {line}")
        print("❌ do not launch on this plan." if errors else "✅ every planned control is pre-verified, singly owned and unspent.")
        return 1 if errors else 0
    if args.grader_context:
        controls: set[str] = set()
        if args.plan:
            plan = _plan(args.plan)
            rows = plan.get("by_lens") if isinstance(plan.get("by_lens"), dict) else plan
            controls = set().union(set(), *(_issue_set(v.get("withheld")) for v in rows.values() if isinstance(v, dict)))
        when, steps, dropped = grader_context(args.grader_context, load_grade_runs(args.repo), controls)
        if when is None:
            print(f"no prior run graded `{args.grader_context}` with a path-to-A list", file=sys.stderr)
            return 1
        print(f"source run {when}; {dropped} step(s) withheld from the list", file=sys.stderr)
        print(json.dumps(steps, indent=2, ensure_ascii=False))
        return 0
    lines, expired = carry_forward_report(date.today(), args.repo)
    print("\n".join(lines))
    return 1 if expired else 0


if __name__ == "__main__":
    raise SystemExit(main())
