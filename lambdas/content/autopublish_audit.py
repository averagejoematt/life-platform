"""content/autopublish_audit.py — the deterministic audit an UNAPPROVED chronicle must pass to publish itself (#4694).

The live weekly path has two ways to publish a chronicle: Matthew's approve click, and chronicle-approve's daily
stale-draft sweep (SS-01), which publishes a draft nobody approved once it is 48 h old. Every week from 2026-09-08 to
2026-10-06 went out through the sweep, and Week 5 (2026-10-06) went out carrying the Story Desk's own unresolved
findings: a claimed 23-day training streak the dossier contradicts, a "season high" that was not one, and a quote the
platform does not hold. The desk had flagged every one of them on the draft row; nothing read the flags before publish.

The story-auditor (#4549) is a Claude Code agent, which a Lambda cannot run. This is the deterministic subset of it that
a Lambda CAN run, and the sweep runs it before it publishes anything nobody approved (option (c) of #4694 — both):

  * the desk's own residual findings, stored on the row at draft time (``desk_findings_json``): the figures against the
    dossier (``ungrounded number``), the fact read, the exact-quote gate, the callback gate, completeness and the story
    door, for the post AND the episode the Panel renders from the same row. Style findings (``craft:`` and ``repeat:``)
    are a writer's notes, not claims, and do not block. Every other finding blocks — an unknown prefix included, so a
    gate the desk adds later is blocking until someone decides otherwise.
  * no desk record at all (the legacy writer wrote the week, or the row predates the desk) is itself blocking: there is
    no audit to read, and an unaudited draft is exactly what the sweep must not publish.
  * the shared reader-surface door (``story_checks.reader_surface``), re-run on the stored text at publish time, so a
    rule tightened between draft and publish still holds the week.
  * dated weekdays: "Monday, October 6" must name the weekday October 6 actually fell on.

An owner approval is the other way through and is untouched: the approve click publishes whatever he approved.
Pure functions — no boto3, no model calls.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from content import story_checks

# The literal the sweep logs when it refuses; a CloudWatch MetricFilter on it pages (cdk/stacks/monitoring_silence_alarms.py,
# alarm `chronicle-autopublish-held`). Twin-pinned by tests/test_chronicle_autopublish_audit_4694.py.
HELD_TOKEN = "CHRONICLE-AUTOPUBLISH-HELD"  # noqa: S105 — a log token, not a credential

# A writer's notes, not claims about the world: length, figure density, a repeated phrase. They do not block a publish.
STYLE_PREFIXES = ("craft:", "repeat:")

# The wrappers the desk puts in front of a finding — the dek's "dek: " and an episode turn's "turn 3 (elena): ".
_WRAPPER = re.compile(r"^(?:dek:\s*|turn\s+\d+\s*\([^)]*\):\s*)+", re.IGNORECASE)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_DATED_WEEKDAY = re.compile(
    r"\b(?P<wd>" + "|".join(_WEEKDAYS) + r"),?\s+(?:the\s+)?(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


# An N/A outcome: the fact reader saying a fact does not apply ("... not reportable. → N/A"). It reports nothing wrong,
# so it never blocks whatever prefix it was written under (#4749).
_NA_OUTCOME = re.compile(r"(?:→|->)\s*n/?a\.?\s*$", re.IGNORECASE)


def is_na_outcome(finding: str) -> bool:
    """True for a finding whose corrected-wording slot is N/A — a non-finding, not a claim to fix."""
    return bool(_NA_OUTCOME.search(str(finding or "").strip()))


def is_style_finding(finding: str) -> bool:
    """True for a finding that is a writer's note (``craft:``/``repeat:``), however the desk wrapped it."""
    return _WRAPPER.sub("", str(finding or "").strip()).lower().startswith(STYLE_PREFIXES)


def desk_blocking(raw: Any) -> List[str]:
    """The blocking items in the row's ``desk_findings_json``. Absent or unreadable is blocking — never a pass."""
    if raw in (None, ""):
        return ["no audit on record: the Story Desk did not write this week, so nothing checked it against the dossier"]
    try:
        found = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ["the desk's audit record is unreadable"]
    if not isinstance(found, dict) or not isinstance(found.get("post"), list) or not isinstance(found.get("episode"), list):
        return ["the desk's audit record is not {post: [...], episode: [...]}"]
    out: List[str] = []
    for part in ("post", "episode"):
        out += [f"desk {part}: {f}" for f in found[part] if not is_style_finding(f) and not is_na_outcome(f)]
    return out


def episode_blocking(raw: Any) -> List[str]:
    """The episode half only — what the Panel checks before it renders the desk's script (#4694)."""
    return [f for f in desk_blocking(raw) if not f.startswith("desk post: ")]


def _year_for(month: int, day: int, anchor: date) -> Optional[date]:
    """The date a "<Month> <day>" in the week ending ``anchor`` means: this year, or last year when this year's would
    sit more than 60 days after the installment (a January post recalling December)."""
    for year in (anchor.year, anchor.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d <= anchor + timedelta(days=60):
            return d
    return None


def weekday_mismatches(text: str, anchor_iso: str) -> List[str]:
    """Findings for a dated weekday ("Monday, October 6") that names the wrong weekday or an impossible date."""
    try:
        anchor = datetime.strptime(str(anchor_iso)[:10], "%Y-%m-%d").date()  # a calendar day, not an instant
    except ValueError:
        return []
    out: List[str] = []
    for m in _DATED_WEEKDAY.finditer(text or ""):
        month, day = _MONTHS[m.group("mon").lower()], int(m.group("day"))
        d = _year_for(month, day, anchor)
        if d is None:
            out.append(f"dated weekday: {m.group(0)!r} is not a real date")
        elif _WEEKDAYS[d.weekday()] != m.group("wd").lower():
            out.append(f"dated weekday: {m.group(0)!r} — {d.isoformat()} was a {_WEEKDAYS[d.weekday()].title()}")
    return out


def blocking_items(item: Dict[str, Any]) -> List[str]:
    """Every reason the sweep may NOT publish this unapproved draft. Empty means the deterministic audit passed."""
    text = "\n".join(str(item.get(k) or "") for k in ("title", "stats_line", "content_markdown"))
    out = desk_blocking(item.get("desk_findings_json"))
    if not str(item.get("content_markdown") or "").strip():
        out.append("no stored text to audit")
    out += [f"reader surface: {f}" for f in story_checks.reader_surface(text)]
    out += weekday_mismatches(text, item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))
    return out
