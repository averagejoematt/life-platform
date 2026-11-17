#!/usr/bin/env python3
"""scripts/alarm_citation_causes.py — the cause-identity rule for alarm citations (#5934).

Imported by `scripts/check_alarm_citations.py` (the /wrap gate). It lives in its own module,
like `alarm_citation_age.py` (#4034), because the gate file sits near the module-size ceiling.

WHAT WAS WRONG (2026-11-15/16, tracker #6053)
  `cause_mismatches` (#3501) required the citation's declared `cause` SET to EQUAL the live
  qa-smoke cause set. That is right for a FAIL alarm with one defect under it and wrong for
  `qa-smoke-warnings`, a standing any-WARN alarm whose live cause line is the union of
  several intermittent WARN ids. Consecutive runs on 2026-11-16 read
  `public_brief:cycle_liveness,reader_truth:verdict` then
  `public_brief:cycle_liveness,weeks:absence_agreement`: no hand-written citation can equal
  both, so the scheduled `wrap-alarm-citations` leg was red by construction and every
  re-cite chased its tail. Measured 2026-11-16 over 168h of `[QA] CAUSE warn` lines in
  /aws/lambda/life-platform-qa-smoke: 7 distinct ids in 17 distinct combinations.

THE RULE NOW — two directions, each one-sided
  * live ⊆ declared. A live cause id is EXPLAINED iff the citation declares it.
    `uncovered_live_causes` flags only live ids the citation does NOT declare. That is the
    rule's actual purpose — a lit alarm must never be red for a reason nobody wrote down —
    and it still catches every incident that shaped #3501/#3793: a cause that CHANGED under
    a count-aggregated alarm (#3501, `cross_surface:weight` -> `reader_truth:frozen_artifacts`)
    is an undeclared live id; an entry with no `cause` at all stays `undeclared_causes`'
    finding (#3793), unchanged.
  * declared ⊆ recently seen. Without this a citation could pre-declare every id and never
    prune one. `stale_declared_causes` flags a declared id that has not appeared in ANY
    `[QA] CAUSE` line for that alarm within DECLARED_CAUSE_STALE_HOURS. The evidence is the
    live channel itself (every run in the window, not a hand-typed date that would rot), so
    pruning is owed exactly when a cause has actually gone quiet — once, not every night.

  The window is 7 days because qa-smoke's cadence-bound WARNs are WEEKLY:
  `public_brief:macrofactor_export_age` warns from Saturday until the Monday brief and
  `public_brief:cycle_liveness` is a Monday-cycle check. A shorter window would demand the
  declaration back out between two weekly recurrences (the re-cite treadmill again, in the
  other direction); a longer one lets a cured cause sit declared for weeks.

WHAT THIS DELIBERATELY DOES NOT REOPEN
  * an empty latest run with the alarm still lit (the self-clearing case) passes the subset
    rule — but only while every declared id was seen in the window, so a citation for a
    cause that has been quiet for 7 days still reds. (The 2026-11-13 review's shape —
    cited `reader_truth:confirm,verdict`, latest run `none` — now passes while those ids
    keep recurring, which they did several times a day, and reds a week after they stop.);
  * no live reading for an alarm at all is UNKNOWN, never flagged — in both directions;
  * a declared id must also be NAMED in the entry's own prose (`unexplained_declared_ids`,
    enforced offline over the committed registry): a bare id list is not a reason written
    down, which is the whole point of declaring it.

Pure functions only; the log read stays in check_alarm_citations.fetch_qa_smoke_causes.
"""

from __future__ import annotations

# 7 days — see the module docstring: the weekly-cadence WARNs set the floor.
DECLARED_CAUSE_STALE_HOURS = 168


def declared_ids(entry) -> set:
    """The cause ids a registry entry declares — `cause` as a list or a comma string."""
    cited = (entry or {}).get("cause")
    if not cited:
        return set()
    items = cited if isinstance(cited, list) else str(cited).split(",")
    return {str(c).strip() for c in items if str(c).strip()}


def uncovered_live_causes(alarms, citations, live_causes):
    """(alarm_name, declared_csv, uncovered_csv) for every lit alarm whose LATEST live run
    names a cause id its citation does not declare (live ⊄ declared).

    Silent when the entry declares no `cause` (`undeclared_causes`, #3793, owns that), when
    the alarm has no live reading (UNKNOWN), and when every live id is declared — including
    the empty, self-clearing run (`stale_declared_causes` bounds that case instead).
    """
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        if a.get("by_construction"):
            continue
        cited = declared_ids(citations.get(name))
        live = live_causes.get(name)
        if not cited or live is None:
            continue
        uncovered = set(live) - cited
        if uncovered:
            out.append((name, ",".join(sorted(cited)), ",".join(sorted(uncovered))))
    return out


def seen_cause_ids(messages, parse, kind_to_alarm):
    """{alarm_name: set(ids)} — the union of every id in every `[QA] CAUSE` line in
    `messages`, per alarm. Order-independent by construction (#3729 cannot bite a union).
    An alarm whose kind had at least one parsed line maps to a set (possibly empty); an
    alarm with no line at all is absent, which callers read as UNKNOWN."""
    seen = {}
    for message in messages:
        parsed = parse(message)
        if parsed is None:
            continue
        kind, _fingerprint, ids = parsed
        alarm = kind_to_alarm.get(kind)
        if alarm:
            seen.setdefault(alarm, set()).update(ids)
    return seen


def stale_declared_causes(alarms, citations, seen):
    """(alarm_name, stale_csv) for every lit alarm whose citation declares an id that never
    appeared in that alarm's cause channel over the whole stale window. No reading for the
    alarm (absent from `seen`, or `seen` is None) is UNKNOWN, never flagged."""
    if seen is None:
        return []
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        if a.get("by_construction") or name not in seen:
            continue
        stale = declared_ids(citations.get(name)) - set(seen[name])
        if stale:
            out.append((name, ",".join(sorted(stale))))
    return out


def unexplained_declared_ids(citations, channel_alarms):
    """(alarm_name, id) for every declared cause id the entry's own citation/note text never
    names. Offline lint over the committed registry: a declared id is a claim that someone
    wrote down WHY it is firing, so the prose must at least say which id it is about.

    Scoped to `channel_alarms` (the alarms with a machine-readable cause channel — the qa-smoke
    pair): everywhere else `cause` is free prose with no channel to compare it against."""
    out = []
    for name, entry in sorted((citations or {}).items()):
        if name not in channel_alarms or not isinstance(entry, dict):
            continue
        text = f"{entry.get('citation', '')} {entry.get('note', '')}"
        out.extend((name, cid) for cid in sorted(declared_ids(entry)) if cid not in text)
    return out


def render_stale_lines(stale) -> list:
    if not stale:
        return []
    days = DECLARED_CAUSE_STALE_HOURS // 24
    lines = [
        f"❌ {len(stale)} lit alarm(s) whose citation declares a cause id the live channel has not named in {days} days (#5934) — "
        "prune it, or the declaration list only ever grows:"
    ]
    lines += [f"   - {name}  (declared, unseen for {days}d: {ids})" for name, ids in sorted(stale)]
    lines.append("   Remove the id from the entry's `cause` (and its sentence), or — if it still fires — name where it was seen.")
    return lines
