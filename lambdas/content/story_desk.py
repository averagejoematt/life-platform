"""content/story_desk.py — the editor's desk: what this week's story IS (#4534).

The 2026-10-01 continuity review found the chronicle and the Panel had no step that asked
the question a human desk asks first — of everything that happened this week, what are the
best stories, and what do we leave out? So one thesis (training past the ramp) led three
weeks running, a journaling gap was treated as news every week, and a two-week prediction
scoring the prologue promised never came.

This module is that step. One structured call reads the week's dossier and the season
ledger and returns a STORY BUDGET — lead, secondary stories, what is omitted and why, a tone
calibrated to the data, the coach to feature, last week's bet scored and the next one set,
and what each thread does. The chronicle (Elena's post) and the Panel (the episode) both
write from the same budget, so the blog and the show report one week from two angles.

The rubric is written down here, not left to taste, so it can be read, argued with and
changed in one place.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from ai import structured_json  # the shared JSON seam (#4276)
from ai.model_defaults import NARRATIVE_MODEL as DESK_MODEL  # noqa: E402 — the one narrative default (#4275/#4278)

from content import story_checks, story_ledger

DESK_MAX_TOKENS = 12000  # the craft-standard schema measured past 6000 on wk2 (2026-10-01)

_STR = {"type": "string"}


def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STORY = _obj({"thread_id": _STR, "angle": _STR, "why": _STR, "evidence": {"type": "array", "items": _STR}})

BUDGET_SCHEMA: Dict[str, Any] = _obj(
    {
        "lead": _STORY,
        "secondary": {"type": "array", "items": _STORY},
        "omitted": {"type": "array", "items": _obj({"item": _STR, "why": _STR})},
        "tone": _obj({"register": {"type": "string", "enum": ["encouraged", "steady", "mixed", "concerned"]}, "why": _STR}),
        "featured_coaches": {"type": "array", "items": _STR},
        "coach_angle": _STR,
        "thread_actions": {
            "type": "array",
            "items": _obj(
                {
                    "thread_id": _STR,
                    "action": {"type": "string", "enum": ["open", "advance", "resolve", "retire", "hold"]},
                    "title": _STR,
                    "note": _STR,
                }
            ),
        },
        "bet_scored": _obj({"result": {"type": "string", "enum": ["none", "right", "wrong", "not_gradable"]}, "note": _STR}),
        "bets_scored": {
            "type": "array",
            "items": _obj(
                {
                    "bet_week": {"type": "integer"},
                    "result": {"type": "string", "enum": ["right", "wrong", "not_gradable"]},
                    "winner": _STR,
                    "note": _STR,
                }
            ),
        },
        "bet": _obj({"claim": _STR, "metric": _STR, "rule": _STR, "window_days": {"type": "integer"}}),
        "beats_used": {"type": "array", "items": _STR},
        "arc_updates": {"type": "array", "items": _obj({"who": _STR, "line": _STR})},
        "title_ideas": {"type": "array", "items": _STR},
        "cold_reader_context": _STR,
        "top_line": _STR,
        "throughline_advanced": _STR,
        "cliffhanger": _STR,
        "coach_asks": {"type": "array", "items": _obj({"coach_id": _STR, "ask": _STR, "follow_up_by": _STR})},
        "asks_followed_up": {"type": "array", "items": _obj({"ask": _STR, "outcome": _STR})},
        "owner_lines_to_use": {"type": "array", "items": _STR},
        "data_caveats": {"type": "array", "items": _STR},
    }
)

RUBRIC = """NEWS JUDGEMENT — how this desk decides what the week's story is.
You are the editor of a small team (a journalist, Elena Voss, and a podcast she hosts with one coach a week)
covering one man's year-long health experiment as it happens. You have every number from the week in front of
you. Decide what a thoughtful human desk would run, the way reporters covering this for the first time would.

Rank the candidate stories by, in order:
 1. CHANGE — a direction that turned, a first, a milestone crossed, a programme change, a new pattern.
 2. A PREDICTION TESTED — a pre-registered call or a coach's forecast confirmed or refuted this week. This is
    how the coaches develop as characters: who has been right, who has been wrong, who changed their mind.
 3. CONSEQUENCE — what this means for where the experiment is going (the plan's waypoints, the risk flags
    the platform itself raises, the pace against the plan).
 4. SURPRISE — something nobody on the team expected, or the data and the plan disagreeing.
 5. HUMAN INTEREST — what he did, chose, tried, or endured; the texture of the actual days.

Tone is calibrated to the data, not to a template. When the trend is good, the coverage is encouraged — say so
plainly. Critique belongs where the data shows a consequence. Never moralise.

ABSENCES (a habit not done, a journal not written, a log not landed) are a story ONLY when (a) the absence is new
this week, or (b) the data shows a consequence of it. Otherwise give it at most a passing line, or omit it and
say why in "omitted". Never lead two weeks running on an absence. A source whose window has not fully EXPORTED
yet is a data caveat ("not yet exported"), never a behaviour.

ATTRIBUTION: the training sessions are PROGRAMMED by the coaching team, and he has said he often goes past the
prescription and skips rest days by his own choice. Never assign motive for the volume (impatience, the coaches'
push, anything) except in his own words from owner_voice; otherwise report what was programmed and what was done.

CONTINUITY: the season ledger lists open threads. Every open thread must be accounted for (advance, resolve,
retire, or hold with a reason in the note). A thread flagged stale MUST be resolved or retired by name. Open new
threads only for things worth following for weeks. Thread ids are short snake_case and stable across weeks.
The lead may not run on the same thread three weeks in a row. Do not reuse a beat from "beats_already_used".

FEATURED COACH: pick one (two at most) whose week has the most at stake — a call graded, a disagreement, their
domain leading the news. Do not feature a coach featured in either of the last two installments unless no one
else has a stake. Prefer a coach who has NOT yet been featured this season when they have a graded call this week —
the audience should meet the whole team. coach ids come from the roster in the dossier.

THE BET: the podcast closes on one bet about the coming week that code can grade: a metric that is in the
dossier, a threshold or direction, and a window that CLOSES ON OR BEFORE the last day of next week's window (the
next episode scores it with data in hand). No bets on absences, on journaling, or on anything the
dossier does not measure. Score last week's open bet against this week's dossier (right / wrong / not_gradable,
with the numbers in the note); "none" when there was no open bet. ALSO list EVERY open bet in the ledger whose window
has closed in "bets_scored" — carried ones included — each with who won (Elena or the guest who took the side).

THE SEASON SPINE: the ledger carries the season question and its throughlines. Name the throughline this week's
lead advances ("throughline_advanced" = its id). Write "top_line": two plain sentences a stranger understands in five
seconds — the day, the scale's direction, the one thing at stake — no jargon, no device names, and no stronger a verb than
the instrument earns (a scale's body-composition reading "suggests", it does not "confirm"). Write "cliffhanger":
one concrete unknown that will be true or false by a NAMED day in the coming week.

HIS VOICE: if the dossier has "owner_voice" answers, the week should turn on them — pick at most two lines to quote
exactly ("owner_lines_to_use"), never anything marked off the record. If there are none, the week is told from what
he did; do not make the absence a story.

COACH ASKS: when a coach asks something concrete of him this week (a rest day, a backup protein, a bedtime), record
it in "coach_asks" with the day by which it can be checked. Every open ask in the ledger gets an "asks_followed_up"
entry with what the data shows happened. Coaches who ask and are ignored, or who prescribe and get proved right, are
the story's characters.

PRIVACY (absolute): no cycle, reset, restart or attempt counts — the frame is THE experiment and the day. Never
name a vice or substance; journal material is off the record (its weather may inform, its specifics may not:
no job details, no named or described third parties). No real-world experts — only the fictional team.

Write every field for the writers who come after you: specific, with the dossier's numbers in "evidence"."""


def desk_messages(dossier: Dict[str, Any], ledger: Dict[str, Any], *, week: int) -> Dict[str, Any]:
    """The Messages body (minus model) for one week's budget call."""
    view = story_ledger.ledger_for_prompt(ledger, week)
    user = (
        f"WEEK {week} DOSSIER (every number you may use):\n{json.dumps(dossier, indent=1, default=str)}\n\n"
        f"SEASON LEDGER (what the series has told so far):\n{json.dumps(view, indent=1, default=str)}\n\n"
        "Return this week's story budget."
    )
    return {"system": RUBRIC, "messages": [{"role": "user", "content": user}], "max_tokens": DESK_MAX_TOKENS, "temperature": 0.4}


def _schema_less(body: Dict[str, Any]) -> Dict[str, Any]:
    """The request without ``output_config``: the schema rides in the system prompt instead (#4535)."""
    out = {k: v for k, v in body.items() if k != "output_config"}
    out["system"] = (
        f"{body.get('system', '')}\n\nReturn ONLY one JSON object (no prose, no code fence) matching this JSON Schema "
        f"exactly — every required key, no others:\n{json.dumps(BUDGET_SCHEMA)}"
    )
    return out


# ── the absence rule, in code (#4534) ────────────────────────────────────────
# The rubric says an absence leads only with a consequence in the data; this is the check that holds the
# model to it. "Lead" here is the lead's SUBJECT — its thread id and angle — never its "why", which may
# legitimately mention a gap while explaining why something else leads.
_ABSENCE = re.compile(
    r"\b(?:gaps?|missing|missed|skip(?:ped|s)?|silen(?:t|ce)|absen(?:t|ce)|unlogged|not\s+logged|didn['’]?t\s+log|"
    r"stopped\s+logging|no\s+(?:log|logs|entr(?:y|ies)|journal\w*|data)|went\s+(?:quiet|dark)|lapsed?|blank)\b",
    re.IGNORECASE,
)
_JOURNAL = re.compile(r"\b(?:journal\w*|diar(?:y|ies))\b", re.IGNORECASE)
# a source's reader-facing names, so a lead about "the food log" is matched to macrofactor's watermark
_SOURCE_WORDS = {"macrofactor": r"food|meals?|nutrition|macros?|calories|protein|macrofactor"}


def _subject(story: Dict[str, Any]) -> str:
    return f"{str(story.get('thread_id') or '').replace('_', ' ')} {story.get('angle') or ''}"


def _not_yet_exported_sources(dossier: Dict[str, Any]) -> List[str]:
    out = {s for s, w in (dossier.get("export_watermarks") or {}).items() if (w or {}).get("not_yet_exported_dates")}
    if (dossier.get("nutrition") or {}).get("not_yet_exported_dates"):
        out.add("macrofactor")
    return sorted(out)


def absence_lead_findings(budget: Dict[str, Any], dossier: Dict[str, Any]) -> List[str]:
    """An absence leads only with a data consequence (#4534).

    * a journal lead is refused outright — journal content is off the record and its presence is not a story
      this experiment (the dossier's own caveat), so there is no consequence it could cite;
    * an absence whose source is NOT YET EXPORTED is export lag, never behaviour, so it cannot lead;
    * any other absence lead must carry, in its evidence, at least one item that is not itself the absence
      and whose figures are all in the dossier — the consequence the absence had."""
    lead = budget.get("lead") or {}
    subject = _subject(lead)
    if _JOURNAL.search(subject):
        return [
            f"lead {lead.get('thread_id')!r} is about the journal — journal presence is never a lead (off the record, no data "
            "consequence); lead on what the data shows"
        ]
    if not _ABSENCE.search(subject):
        return []
    for src in _not_yet_exported_sources(dossier):
        if re.search(rf"\b(?:{_SOURCE_WORDS.get(src, re.escape(src))})\b", subject, re.IGNORECASE):
            return [f"lead {lead.get('thread_id')!r} is an absence in {src}, whose window is not yet exported — export lag is not a story"]
    allowed = story_checks.allowed_numbers(dossier)
    for ev in lead.get("evidence") or []:
        ev = str(ev)
        if _ABSENCE.search(ev) or _JOURNAL.search(ev):
            continue
        # a measured figure (not a small count of days, which restates the absence) and every figure from the dossier
        measured = story_checks.ungrounded_numbers(ev, set())
        if measured and not story_checks.ungrounded_numbers(ev, allowed):
            return []
    return [
        f"lead {lead.get('thread_id')!r} is an absence with no data consequence in its evidence — an absence leads only when "
        "the dossier shows what it cost; otherwise lead on the week's best story and omit the gap with a reason"
    ]


def validate(budget: Dict[str, Any], dossier: Dict[str, Any], ledger: Dict[str, Any], *, week: int) -> List[str]:
    """Code-side checks a schema cannot express. Empty = the budget is runnable."""
    findings = story_ledger.continuity_findings(ledger, budget, week)
    findings += absence_lead_findings(budget, dossier)
    roster = {c.get("coach_id") for c in dossier.get("roster", [])}
    for c in budget.get("featured_coaches", []):
        if roster and c not in roster:
            findings.append(f"featured coach {c!r} is not on the roster {sorted(roster)}")
    ever = {f.get("coach_id") for f in ledger.get("featured", [])}
    graded_this_week = {g.get("coach_id") for g in (dossier.get("predictions") or {}).get("graded_this_week", [])}
    unmet_with_stake = (graded_this_week - ever) & roster
    lead_coach = (budget.get("featured_coaches") or [None])[0]
    if week > 1 and lead_coach in ever and len(unmet_with_stake) >= 1:
        findings.append(
            f"featured coach {lead_coach!r} has guested before while {sorted(unmet_with_stake)} had a graded call this week and has "
            "never been featured — introduce the rest of the team"
        )
    spine_ids = {t.get("id") for t in (ledger.get("spine") or {}).get("throughlines", [])}
    if spine_ids and week > 0 and budget.get("throughline_advanced") not in spine_ids:
        findings.append(
            f"throughline_advanced {budget.get('throughline_advanced')!r} is not one of the season's throughlines {sorted(spine_ids)}"
        )
    if week > 0 and not re.search(
        r"\b(?:Day \d+|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\w+ \d{1,2}(?:st|nd|rd|th)?)\b",
        budget.get("cliffhanger") or "",
    ):
        findings.append("cliffhanger names no day — it must be checkable by a named day")
    open_asks = [a.get("ask") for a in ledger.get("asks", []) if a.get("status") in (None, "", "open")]
    followed = " ".join(a.get("ask", "") for a in budget.get("asks_followed_up", []))
    for a in open_asks:
        if a and a[:40] not in followed and len(budget.get("asks_followed_up", [])) < len(open_asks):
            findings.append(f"an open coach ask is not followed up: {a!r}")
            break
    if not budget.get("featured_coaches"):
        findings.append("no featured coach")
    recent = set(story_ledger.recently_featured(ledger, 2))
    if week > 1 and set(budget.get("featured_coaches", [])) & recent and len(roster - recent) >= 2:
        findings.append(f"featured coach repeats one of the last two installments ({sorted(recent)}) while others had a stake")
    return findings


def run_desk(
    dossier: Dict[str, Any],
    ledger: Dict[str, Any],
    *,
    week: int,
    invoke: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """The budget for one week: one structured call, validated in code, one corrective retry."""
    if invoke is None:
        from ai import bedrock_client

        invoke = bedrock_client.invoke_with_retry
        cfg = bedrock_client.structured_output_config(BUDGET_SCHEMA)
    else:
        cfg = {"format": {"type": "json_schema", "schema": BUDGET_SCHEMA}}
    body = desk_messages(dossier, ledger, week=week)
    body["output_config"] = cfg
    findings: List[str] = []
    budget: Dict[str, Any] = {}
    for attempt in (1, 2):
        if findings:
            body["messages"] = body["messages"][:1] + [
                {"role": "assistant", "content": json.dumps(budget)},
                {
                    "role": "user",
                    "content": "The desk's checks rejected this budget:\n- " + "\n- ".join(findings) + "\nReturn a corrected budget.",
                },
            ]
        try:
            resp = invoke(body, DESK_MODEL)
        except Exception as e:  # noqa: BLE001 — only a schema/grammar refusal is absorbed; all else re-raises
            if "output_config" not in body or not structured_json.grammar_rejected(e):
                raise
            log(f"desk: strict schema refused ({str(e)[:120]}) — schema-less, shape checked in code")
            body = _schema_less(body)
            resp = invoke(body, DESK_MODEL)
        if resp.get("stop_reason") != "end_turn":
            raise RuntimeError(f"desk: budget call stopped with {resp.get('stop_reason')!r} — not a complete budget")
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        parsed = structured_json.parse_json_span(text.strip())
        budget = parsed if isinstance(parsed, dict) else {}
        findings = structured_json.schema_findings(budget, BUDGET_SCHEMA) if budget else ["the reply was not a JSON object"]
        findings = findings or validate(budget, dossier, ledger, week=week)
        if not findings:
            return budget
        log(f"desk: week {week} attempt {attempt} rejected: {findings}")
    raise RuntimeError(f"desk: week {week} budget failed validation twice: {findings}")
