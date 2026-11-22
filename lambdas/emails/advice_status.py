"""emails/advice_status.py — the ONE seam the Sunday email reads advice status through (#6176).

WHAT IT ANSWERS. For a week: how many decisions he logged, which of them he himself linked to a coach recommendation
and with what state, which coach asks he answered, and whether he has an ask marked "not yet decided" — the one
decision the Sunday email may put in front of him. Everything else reads "not recorded".

WHAT IT READS. The decisions partition only (``USER#<user>#SOURCE#decisions``): ``DECISION#`` rows (his logged
decisions), ``ADVICELINK#`` rows (his own decision-to-recommendation links, ``coach/advice_links.py``) and
``ASKRESPONSE#`` revisions (his own answers to coach asks). Every one of them is written by the owner-facing MCP tool
and nothing else. It reads NO workout, meal, weight, sleep or habit source, so no state can ever be inferred from
behaviour (owner ruling 2026-11-02 decision F; ruling 2026-11-22 rule 11). A read error returns ``readable: False``
and the email says the status could not be read — never zero, never a guess.

WHY A SEAM. The recommendation record (#6158) is being built beside this lane. When it lands, its reader replaces the
body of ``read`` and the email does not change: the email only ever sees the dict documented on ``read``.
"""

from __future__ import annotations

from typing import Any, Optional

from coach import advice_links as AL
from experiment.phase_filter import singleton_visible


def _rows(table: Any, user_id: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(f"USER#{user_id}#SOURCE#decisions")}
    out: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return [r for r in out if singleton_visible(r)]
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _in(day: str, start: str, end: str) -> bool:
    return bool(day) and start <= day[:10] <= end


def summarize(rows: list[dict], start: str, end: str, prior_start: str, prior_end: str) -> dict:
    """Pure: the advice-status dict for one week, from the partition's visible rows."""
    decisions = [r for r in rows if str(r.get("sk", "")).startswith(AL.DECISION_SK_PREFIX)]
    links = [r for r in rows if str(r.get("sk", "")).startswith(AL.SK_PREFIX)]
    answers = [r for r in rows if str(r.get("sk", "")).startswith(AL.ASK_RESPONSE_SK_PREFIX)]

    def _decision_day(r: dict) -> str:
        return str(r.get("date") or str(r.get("sk", ""))[len(AL.DECISION_SK_PREFIX) :])[:10]

    this_week = [r for r in decisions if _in(_decision_day(r), start, end)]
    last_week = [r for r in decisions if _in(_decision_day(r), prior_start, prior_end)]
    this_sks = {str(r.get("sk")) for r in this_week}

    link_states: dict[str, int] = {}
    for r in links:
        if not any(str(r.get("sk", "")).startswith(f"{AL.SK_PREFIX}{sk[len(AL.DECISION_SK_PREFIX):]}#") for sk in this_sks):
            continue
        state = AL.effective_state(r)
        link_states[state] = link_states.get(state, 0) + 1

    # The newest revision per ask is its answer (append-only revisions, coach/advice_links.py).
    newest: dict[tuple, dict] = {}
    for r in answers:
        key = (r.get("coach_id"), r.get("ask_id"))
        if key not in newest or str(r.get("recorded_at", "")) > str(newest[key].get("recorded_at", "")):
            newest[key] = r
    answered_this_week: dict[str, int] = {}
    for r in newest.values():
        if _in(str(r.get("recorded_at", "")), start, end) and r.get("state") in (AL.ACTED_ON, AL.DECLINED, AL.PARTIALLY_FOLLOWED):
            answered_this_week[r["state"]] = answered_this_week.get(r["state"], 0) + 1
    undecided = sorted((r for r in newest.values() if r.get("state") == AL.NOT_YET_DECIDED), key=lambda r: str(r.get("recorded_at", "")))
    open_decision: Optional[dict] = None
    if undecided:
        r = undecided[0]
        open_decision = {"coach_id": r.get("coach_id"), "ask_id": r.get("ask_id"), "since": str(r.get("recorded_at", ""))[:10]}

    return {
        "readable": True,
        "decisions_this_week": len(this_week),
        "decisions_last_week": len(last_week),
        "linked_states": link_states,
        "linked_decisions": sum(link_states.values()),
        "ask_answers_this_week": answered_this_week,
        "open_decision": open_decision,
    }


def read(table: Any, user_id: str, start: str, end: str, prior_start: str, prior_end: str) -> dict:
    """The advice-status dict for the week ``start..end`` (Pacific days), or ``{"readable": False, "error": ...}``.

    Keys: ``decisions_this_week``, ``decisions_last_week``, ``linked_states`` ({state: n} over this week's decisions,
    owner-recorded links only), ``linked_decisions``, ``ask_answers_this_week`` ({state: n}), ``open_decision``
    (the oldest ask he marked not-yet-decided: {coach_id, ask_id, since}, or None).
    """
    try:
        rows = _rows(table, user_id)
    except Exception as e:  # noqa: BLE001 — unreadable is reported as unreadable, never as zero
        return {"readable": False, "error": type(e).__name__}
    return summarize(rows, start, end, prior_start, prior_end)
