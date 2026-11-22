"""emails/advice_status.py — the ONE seam the Sunday email reads advice status through (#6176).

WHAT IT ANSWERS. For a week: how many decisions he logged, which coach asks he answered (and how), and whether he has
an ask marked "not yet decided" — the one decision the Sunday email may put in front of him. Everything else reads
"not recorded".

WHAT IT READS, and only through the sanctioned doors (``tests/test_advice_links_5612.py``):
  * his logged decisions — the decisions partition narrowed on the ``DECISION#`` prefix, so no other family that
    shares the partition is ever counted as a decision;
  * his answers to coach asks — ``coach.ask_outcomes.owner_answers``, the ONE reader of that family (owner-side view:
    the current state and when, no note).
It does NOT read the decision-to-recommendation links: their one reader is the owner's MCP tool, so the email points
there instead of re-reading them. It reads NO workout, meal, weight, sleep or habit source, so no state can ever be
inferred from behaviour (owner ruling 2026-11-02 decision F; ruling 2026-11-22 rule 11). A read error returns
``readable: False`` and the email says the status could not be read — never zero, never a guess.

WHY A SEAM. The recommendation record (#6158) is being built beside this lane. When it lands, its reader replaces the
body of ``read`` and the email does not change: the email only ever sees the dict documented on ``read``.
"""

from __future__ import annotations

from typing import Any, Optional

from experiment.phase_filter import singleton_visible

#: The answered states an ask can carry, in the email's words (comparison only — never assigned to a record).
ANSWER_WORDS = {"acted_on": "acted on", "declined": "declined", "partially_followed": "partly followed"}
UNDECIDED = "not_yet_decided"


def _decisions(table: Any, user_id: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{user_id}#SOURCE#decisions") & Key("sk").begins_with("DECISION#")}
    out: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return [r for r in out if singleton_visible(r)]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _answers(table: Any, user_id: str) -> dict:
    from coach import ask_outcomes, persona_registry as pr

    coach_ids = sorted(set(pr.CHAT_COACH_IDS) | set(pr.OPERATIONAL_COACH_IDS) | set(pr.RETIRED_COACH_IDS))
    return ask_outcomes.owner_answers(table, user_id, coach_ids)


def _in(day: str, start: str, end: str) -> bool:
    return bool(day) and start <= day[:10] <= end


def summarize(decisions: list[dict], answers: dict, start: str, end: str, prior_start: str, prior_end: str) -> dict:
    """Pure: the advice-status dict for one week, from his visible decisions and his current ask answers."""

    def _day(r: dict) -> str:
        return str(r.get("date") or str(r.get("sk", ""))[len("DECISION#") :])[:10]

    answered: dict[str, int] = {}
    undecided = []
    for (coach_id, ask_id), a in sorted(answers.items()):
        state, when = a.get("state"), str(a.get("recorded_at") or "")
        if state in ANSWER_WORDS and _in(when, start, end):
            answered[state] = answered.get(state, 0) + 1
        if state == UNDECIDED:
            undecided.append((when, coach_id, ask_id))
    open_decision: Optional[dict] = None
    if undecided:
        when, coach_id, ask_id = min(undecided)
        open_decision = {"coach_id": coach_id, "ask_id": ask_id, "since": when[:10]}
    return {
        "readable": True,
        "decisions_this_week": sum(1 for r in decisions if _in(_day(r), start, end)),
        "decisions_last_week": sum(1 for r in decisions if _in(_day(r), prior_start, prior_end)),
        "ask_answers_this_week": answered,
        "open_decision": open_decision,
    }


def read(table: Any, user_id: str, start: str, end: str, prior_start: str, prior_end: str) -> dict:
    """The advice-status dict for the week ``start..end`` (Pacific days), or ``{"readable": False, "error": ...}``.

    Keys: ``decisions_this_week``, ``decisions_last_week``, ``ask_answers_this_week`` ({state: n}, his own answers
    recorded this week), ``open_decision`` (the oldest ask he marked not-yet-decided: {coach_id, ask_id, since}, or None).
    """
    try:
        decisions = _decisions(table, user_id)
        answers = _answers(table, user_id)
    except Exception as e:  # noqa: BLE001 — unreadable is reported as unreadable, never as zero
        return {"readable": False, "error": type(e).__name__}
    return summarize(decisions, answers, start, end, prior_start, prior_end)
