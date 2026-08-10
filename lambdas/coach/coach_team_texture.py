"""coach_team_texture.py — team texture + track-record humility (#2496, epic #2363).

Two humanity moves that are GROUNDED READS of rows that already exist, plus the
deterministic gate that keeps the first one from becoming a lie.

**(a) Team texture.** "We talked about you Tuesday" is the single most human thing
a coach on a real staff can say, and it is worthless the moment it is invented.
The only machine-written record of coaches actually talking to each other is the
inter-coach dialogue thread (``ENSEMBLE#dispute`` / ``THREAD#{iso-week}#{slug}``,
written by ``inter_coach_dialogue_lambda``): a real exchange, in each coach's own
voice, already through the ADR-104 grounding gate at write time. This module reads
those threads for the coach whose seat is at the table and renders the DAY, the
colleague, the topic, and the two verbatim lines. Nothing is inferred: a thread
with no ``created_at`` names no day and is therefore skipped, because a day the
coach cannot source is a day the coach may not claim.

**(b) Track-record humility.** ``coach_domain_facts`` already surfaces each coach's
still-OPEN preregistered calls (#2498). The calls that came back are the half that
humanises: a coach that names its own refuted call plainly is a colleague, and one
that only ever quotes its live positions is a brochure. So terminal outcomes join
the pack — and the selector *guarantees* a miss is shown whenever a miss exists,
because "newest first" alone lets a run of hits crowd out the one line worth
saying. ADR-105's bar rides along: the record line carries n (decided calls), and
the calls the evaluator could NOT decide are reported separately rather than
quietly counted as hits.

**The gate (why this module owns one).** The number and date classes cannot see the
failure mode here. "We talked about you Tuesday" contains no number and no calendar
date, so an invented meeting sails through every class ``grounded_generation``
arms. ``team_meeting_findings`` is the missing deterministic check, in two parts:

  1. **No meeting on record → any team-meeting claim is a finding.** The absence is
     read off the rendered block itself (``TEAM_ROOM_HEADING`` present or not), so
     the gate adjudicates against exactly what the model was shown.
  2. **A meeting on record → the DAY still has to be the right one.** #2343's whole
     lesson is that a real value pinned to the wrong day is the harder lie to
     catch; a real meeting narrated onto the wrong weekday is the same defect.

Composed in ``coach_chat_grounding.build_grounder`` rather than at each transport,
which is the #1967 lesson applied: per-caller wiring is how classes end up unarmed.

The refusal posture is regenerate-once-then-HOLD, inherited from ``run_turn``. An
ungrounded team-meeting claim must produce NOTHING — never a hedge. "I think we may
have discussed you at some point" is the failure this module exists to prevent, not
its fallback.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── The rendered headings (the gate's own evidence, so they are constants) ────
#
# The gate decides "is a meeting on record" by looking for TEAM_ROOM_HEADING in
# the material the model was given. That makes these two strings load-bearing in
# BOTH directions, which is exactly why the renderer and the gate import the same
# constant instead of each spelling it out.
TEAM_ROOM_HEADING = "TEAM ROOM — what your team actually said, on the record:"
TEAM_ROOM_EMPTY_HEADING = "TEAM ROOM — nothing on the record:"
TEAM_ROOM_EMPTY_LINE = (
    "No team meeting of yours is on record this cycle. You have not talked about him with a colleague "
    "on the record — so do not say you did, in any wording, however casual."
)
TRACK_RECORD_HEADING = "YOUR TRACK RECORD (your own graded calls — name a miss as plainly as a hit, never soften one into a maybe):"
TRACK_RECORD_EMPTY_LINE = "None of your calls has been graded yet this cycle. You have no track record to claim either way."

DISPUTE_PK = "ENSEMBLE#dispute"
MAX_MEETINGS = 2
MAX_QUOTE_CHARS = 180
_MAX_MEETING_PAGES = 2  # a chat turn is latency-bound; the partition is one thread/week

# Terminal grades. 'inconclusive'/'expired' are terminal too, but they are NOT
# outcomes — counting an undecidable call as anything but undecidable is the
# ADR-104 fabrication class pointed at the coach's own record.
_HIT, _MISS = "confirmed", "refuted"
_UNDECIDED = ("inconclusive", "expired")
MAX_TERMINAL_CALLS = 2

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _clip(text, limit: int = MAX_QUOTE_CHARS) -> str:
    """One-line, whitespace-collapsed, bounded — a prompt is not a transcript viewer."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


# ── (a) Team texture: the inter-coach threads this coach was actually in ─────


def _pacific_day(iso_ts: str) -> Optional[str]:
    """The PACIFIC calendar date of a stored UTC timestamp, or None.

    Pacific because every other day-naming surface on this platform is Pacific
    (``feedback_site_pacific_time``); a thread written at 18:00 UTC is a Sunday
    morning in the room where it happened, and the coach has to name the day
    Matthew lived, not the day the lambda's clock was in.
    """
    try:
        from common.pacific_time import pacific_date_of

        return pacific_date_of(str(iso_ts or "")) or None
    except Exception as e:  # pragma: no cover — bundle edge
        logger.warning("[team_texture] pacific conversion failed: %s", e)
        return None


def _weekday_of(day_iso: str) -> Optional[str]:
    from datetime import datetime

    try:
        return datetime.strptime(day_iso, "%Y-%m-%d").strftime("%A")
    except (TypeError, ValueError):
        return None


def _fetch_threads(table) -> list:
    """Every visible inter-coach thread, newest first, through the phase filter.

    ADR-058 is not optional here: the restart wipe tombstones + pilot-tags every
    ``ENSEMBLE#dispute`` thread (#1085), and an unguarded read has already shipped
    the WIPED cycle's argument to a reader surface once. A coach recounting a
    meeting from a deleted cycle is the same bug with a warmer voice.
    """
    from experiment.phase_filter import with_phase_filter

    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": DISPUTE_PK, ":prefix": "THREAD#"},
        "ScanIndexForward": False,
    }
    items: list = []
    for _page in range(_MAX_MEETING_PAGES):
        resp = table.query(**with_phase_filter(kwargs))
        items.extend(resp.get("Items") or [])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _meeting_line(coach_id: str, rec: dict) -> Optional[str]:
    """One thread → one fact line, or None when the thread cannot be sourced.

    None on a missing day, a missing own-line, or a missing colleague is the whole
    honesty contract in three branches: an exchange the coach cannot place, cannot
    quote itself from, or cannot name the other party to is an exchange it may not
    bring up. Half a memory is not a memory.
    """
    day = _pacific_day(rec.get("created_at"))
    weekday = _weekday_of(day) if day else None
    if not day or not weekday:
        return None
    turns = [t for t in (rec.get("turns") or []) if isinstance(t, dict) and str(t.get("line") or "").strip()]
    mine = [t for t in turns if str(t.get("speaker") or "") == coach_id]
    theirs = [t for t in turns if str(t.get("speaker") or "") != coach_id]
    if not mine or not theirs:
        return None
    other_name = str(theirs[-1].get("name") or theirs[-1].get("speaker") or "").strip()
    if not other_name:
        return None
    topic = _clip(rec.get("topic"), 120)
    return (
        f"{weekday} {day} — you and {other_name} went back and forth about {topic}. "
        f'You said: "{_clip(mine[-1].get("line"))}". {other_name} said: "{_clip(theirs[-1].get("line"))}".'
    )


def team_meeting_lines(coach_id: str, table) -> list:
    """This coach's on-record team exchanges, newest first — at most MAX_MEETINGS.

    Read-only and fail-soft: a storage surprise costs the section, and the section's
    absence is itself the safe state (the gate then refuses every team-meeting
    claim). Failing OPEN here would be the one unacceptable direction.
    """
    try:
        threads = _fetch_threads(table)
    except Exception as e:
        logger.warning("[team_texture] dispute threads unavailable for %s: %s", coach_id, e)
        return []
    mine = [t for t in threads if coach_id in (str(t.get("coach_a") or ""), str(t.get("coach_b") or ""))]
    mine.sort(key=lambda t: (str(t.get("created_at") or ""), str(t.get("sk") or "")), reverse=True)
    lines = [ln for ln in (_meeting_line(coach_id, rec) for rec in mine) if ln]
    return lines[:MAX_MEETINGS]


def team_room_section(lines: list) -> str:
    """The rendered TEAM ROOM block — headed one way when there is a record and the
    other way when there is not. The empty form is deliberately NOT silence: a coach
    told nothing about its team fills the gap from the persona's general idea of
    what a coaching staff does, and that is precisely the invented meeting."""
    if not lines:
        return TEAM_ROOM_EMPTY_HEADING + "\n- " + TEAM_ROOM_EMPTY_LINE
    return TEAM_ROOM_HEADING + "\n" + "\n".join(f"- {ln}" for ln in lines)


# ── (b) Track-record humility: the calls that came back ──────────────────────


def _grade_line(rec: dict, verdict: str) -> str:
    claim = _clip(rec.get("claim_natural"))
    made = str(rec.get("created_date") or "").strip()
    graded = str(rec.get("outcome_date") or "").strip()
    when = ", ".join(p for p in ((f"made {made}" if made else ""), (f"graded {graded}" if graded else "")) if p)
    return f'Graded {verdict}: "{claim}"' + (f" ({when})." if when else ".")


def terminal_prediction_lines(items: list) -> list:
    """The coach's decided calls — misses first-class, and the record with its n.

    ``items`` are the PREDICTION# rows already fetched for the open-calls surface
    (#2498); this deliberately takes rows rather than a table so one chat turn makes
    one query of one partition.

    The selection rule is the point of the story. Newest-first alone lets three
    fresh hits bury the one refuted call, and the refuted call is the humanising
    line — so if the newest slice contains no miss and a miss exists, the oldest
    chosen slot is given to the newest miss. A coach is not allowed to present a
    flattering sample of its own record as its record (ADR-104/105).
    """
    graded = [i for i in items if str(i.get("status") or "").strip().lower() in (_HIT, _MISS) and str(i.get("claim_natural") or "").strip()]
    undecided = [i for i in items if str(i.get("status") or "").strip().lower() in _UNDECIDED]
    if not graded:
        return [TRACK_RECORD_EMPTY_LINE] if items else []

    def _recency(rec):
        return (str(rec.get("outcome_date") or ""), str(rec.get("created_date") or ""), str(rec.get("sk") or ""))

    graded.sort(key=_recency, reverse=True)
    misses = [i for i in graded if str(i.get("status")).strip().lower() == _MISS]
    chosen = graded[:MAX_TERMINAL_CALLS]
    if misses and not any(str(c.get("status")).strip().lower() == _MISS for c in chosen):
        chosen = chosen[: MAX_TERMINAL_CALLS - 1] + [misses[0]]

    lines = [_grade_line(rec, "WRONG" if str(rec.get("status")).strip().lower() == _MISS else "RIGHT") for rec in chosen]
    hits = len(graded) - len(misses)
    record = f"Your graded record this cycle: {hits} right, {len(misses)} wrong out of {len(graded)} decided calls"
    lines.append(record + (f" ({len(undecided)} more could not be decided — those count as neither)." if undecided else "."))
    return lines


def track_record_section(lines: list) -> str:
    return TRACK_RECORD_HEADING + "\n" + "\n".join(f"- {ln}" for ln in lines) if lines else ""


# ── The gate: an invented meeting produces nothing, never a hedge ────────────

# Deliberately narrow. Every pattern asserts a conversation about Matthew held
# with someone who is NOT Matthew — which is what makes "we talked about your
# sleep" (the coach and Matthew, in this very thread) not a match while "we talked
# about you" is. Breadth here would flag honest sentences and teach the regen loop
# to hedge, which is the outcome this whole module refuses.
_TEAM_CLAIM_PATTERNS = (
    re.compile(r"\bwe(?:'ve|'d| have| had| were)?\s+(?:been\s+)?(?:talk(?:ed|ing)|spok(?:e|en)|chatt(?:ed|ing))\s+about\s+you\b", re.I),
    re.compile(
        r"\b(?:the team|the staff|the board|the rest of us|all of us|the others)\s+(?:talked|discussed|were talking|met|brought)", re.I
    ),
    re.compile(r"\bbrought you up\b", re.I),
    re.compile(r"\byour name came up\b", re.I),
    re.compile(r"\bcompared notes\b", re.I),
    re.compile(r"\b(?:in|at|during)\s+(?:our|the)\s+(?:team\s+)?(?:meeting|huddle|all[-\s]hands|sync|stand[-\s]?up)\b", re.I),
)

UNGROUNDED_TEAM_MEETING = "ungrounded_team_meeting"
WRONG_TEAM_MEETING_DAY = "wrong_team_meeting_day"


def _team_room_evidence(sources_text: str) -> Optional[str]:
    """The TEAM ROOM section of what the model was shown, or None when no meeting
    is on record. None and "" are different answers and must stay different: None
    means "the coach was told it has no meetings", which is what makes any claim a
    finding."""
    text = sources_text or ""
    at = text.find(TEAM_ROOM_HEADING)
    if at < 0:
        return None
    rest = text[at + len(TEAM_ROOM_HEADING) :]
    end = rest.find("\n\n")
    return rest if end < 0 else rest[:end]


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind(".", 0, index), text.rfind("\n", 0, index), text.rfind("?", 0, index)) + 1
    stops = [p for p in (text.find(".", index), text.find("\n", index), text.find("?", index)) if p >= 0]
    return text[start : (min(stops) if stops else len(text))]


def team_meeting_findings(text: str, sources_text: str) -> list:
    """Deterministic findings for team-meeting claims. [] = grounded.

    Two classes, both invisible to every class ``grounding_findings`` arms:

      ungrounded_team_meeting — a team conversation asserted with no thread on
        record behind it. The invented meeting.
      wrong_team_meeting_day  — a real meeting narrated onto a weekday it did not
        happen on. #2343's shape: the thing is real, the DAY is the lie.
    """
    body = text or ""
    hits = [m for pattern in _TEAM_CLAIM_PATTERNS for m in pattern.finditer(body)]
    if not hits:
        return []
    evidence = _team_room_evidence(sources_text or "")
    if evidence is None:
        return [
            {
                "type": UNGROUNDED_TEAM_MEETING,
                "detail": (
                    f'"{_clip(_sentence_around(body, hits[0].start()), 120)}" claims a conversation with a colleague about him, '
                    "and no inter-coach thread of yours is on record. Do not mention a team conversation at all."
                ),
            }
        ]
    on_record = {day for day in _WEEKDAYS if re.search(rf"\b{day}\b", evidence, re.I)}
    findings, flagged = [], set()
    for match in sorted(hits, key=lambda m: m.start()):
        sentence = _sentence_around(body, match.start())
        wrong = {d for d in _WEEKDAYS if re.search(rf"\b{d}\b", sentence, re.I)} - on_record
        for day in sorted(wrong):
            if day in flagged:
                continue
            flagged.add(day)
            findings.append(
                {
                    "type": WRONG_TEAM_MEETING_DAY,
                    "detail": (
                        f"you place a team conversation on {day}; the exchanges on record happened on "
                        + (", ".join(sorted(on_record)) if on_record else "no day you were given")
                        + ". Name the day on record or name no day."
                    ),
                }
            )
    return findings


def with_team_meeting_gate(grounder: Callable[[str], list], *sources: str) -> Callable[[str], list]:
    """Compose the team-texture gate onto an existing grounder closure.

    Kept a composition rather than a ``grounding_findings`` class on purpose: this
    check needs the RENDERED block (its heading is the evidence), not the fact dict,
    and every other surface in the wiring registry would have to take a decision on
    a class that can only ever apply to the chat transport.
    """
    joined = "\n\n".join(s for s in sources if s)

    def gated(text: str) -> list:
        return list(grounder(text) or []) + team_meeting_findings(text, joined)

    return gated
