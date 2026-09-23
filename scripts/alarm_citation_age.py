#!/usr/bin/env python3
"""scripts/alarm_citation_age.py — the 72h AGE predicate for alarm citations (#4034 box 4).

Imported by `scripts/check_alarm_citations.py` (the /wrap gate) with a three-line hook in its
`main()`. It lives in its own module so the gate file — which sits near the module-size
ceiling and is concurrently extended by other work (#3597's cause/date predicate) — changes
by a few lines only.

THE QUESTION
  An alarm red longer than 72h must cite something. The existing legs ask whether a citation
  EXISTS (#1959), whether its `#N` is still open (#2996) and whether it was written on a
  calendar day BEFORE the current episode (#3501 — deliberately lenient: same-day passes).
  None asks whether anybody looked AFTER the alarm went red. A citation written the morning
  of the transition, about the previous cause, reads identical to one written that evening
  about this one — and after 72h the difference is the whole question.

THE PREDICATE
  A lit alarm older than AGE_HOURS whose citation carries no timestamp that POST-DATES its
  StateTransitionedTimestamp is flagged. The citation's timestamp is `cause_observed`, else
  `added` (the same precedence #3501 uses):
    * a full ISO timestamp post-dates iff it is strictly later than the transition;
    * a bare YYYY-MM-DD can only prove it post-dates when it is a LATER CALENDAR DAY than the
      transition — a same-day date cannot tell morning from evening, so it does not count;
    * no timestamp at all cannot post-date anything and is flagged.
  Re-stamping `cause_observed` after re-deriving the live cause clears it — once, not every
  72h. An alarm with no citation at all is the #1959 leg's finding, not this one's; a
  by-construction suppressor inside its window (#3503/#4034) is excluded like everywhere else.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

AGE_HOURS = 72

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def citation_stamp(entry) -> str | None:
    """The citation's own timestamp string (`cause_observed` wins over `added`), or None."""
    for field in ("cause_observed", "added"):
        value = str((entry or {}).get(field) or "").strip()
        if value:
            return value
    return None


def post_dates(stamp: str | None, transitioned) -> bool:
    """True only when `stamp` provably post-dates the episode start."""
    if not stamp or transitioned is None:
        return False
    if _DATE_ONLY.match(stamp):
        return stamp > transitioned.date().isoformat()
    when = _parse(stamp)
    return when is not None and when > transitioned


def aged_unrefreshed_citations(alarms, citations, now=None, age_hours=AGE_HOURS):
    """(alarm_name, red_hours, stamp_or_None, episode_start_iso) for every lit alarm older
    than `age_hours` whose citation does not post-date its current episode. Pure."""
    now = now or datetime.now(timezone.utc)
    out = []
    for a in alarms:
        name = a.get("name") or "?"
        if a.get("by_construction"):
            continue
        transitioned = _parse(a.get("transitioned") or a.get("updated"))
        if transitioned is None:
            continue
        red_hours = (now - transitioned).total_seconds() / 3600.0
        entry = citations.get(name)
        if red_hours <= age_hours or not entry:
            continue
        stamp = citation_stamp(entry)
        if not post_dates(stamp, transitioned):
            out.append((name, red_hours, stamp, transitioned.isoformat()))
    return out


def render_lines(aged) -> list[str]:
    if not aged:
        return []
    lines = [
        f"❌ {len(aged)} alarm(s) red >{AGE_HOURS}h whose citation does not POST-DATE the current episode (#4034) — "
        "nobody has provably looked since it went red:"
    ]
    for name, hours, stamp, start in sorted(aged):
        lines.append(f"   - {name}  (red {hours / 24:.1f}d since {start}; citation stamp {stamp or 'NONE'})")
    lines.append(
        "   Re-derive the live cause and stamp `cause_observed` with a timestamp after the episode began "
        "(a bare date must be a LATER day than the transition) — or name the shortfall in the handover and --decoded."
    )
    return lines
