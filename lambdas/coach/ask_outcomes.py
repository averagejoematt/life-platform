"""coach/ask_outcomes.py — the ONE reader of Matthew's ask responses (owner, 2026-11-12). Reads; never writes.

An ask response is Matthew's own structured answer to one coach ask (``coach/advice_links.py`` holds the record, the
owner MCP tool ``log_advice_link`` with ref_kind='commitment' is its only writer). This module turns the stored
revisions into the two shapes anything else may see:

  ``public_outcomes(table, user_id, coach_id)`` — the PUBLIC projection, ``{ask_id: {ask_id, state, responded_on,
      self_reported: True}}``, for the asks whose newest revision is acted_on / declined / partially_followed. An
      unanswered ask, a withdrawn one and a ``not_yet_decided`` one are simply absent: the page reads "not recorded".
      Nothing else of a revision (the private note, the decision pointer, the history) is ever returned. Served by
      ``/api/coach/<id>`` (``web/site_api_coach_profile.py``) on each ask row of the dossier.
  ``owner_answers(table, user_id, coach_ids)`` — the OWNER-side view, ``{(coach_id, ask_id): {state, recorded_at,
      revisions}}`` — the current answer (``not_yet_decided`` included) and how many revisions it has, no note. MCP only
      (``get_advice_link_queue``).

What it reads: the ask-response revisions and NOTHING else — no workout, meal, weight, habit or any behaviour source,
so no public state can be inferred from what the data shows (``tests/test_ask_responses.py`` holds that by AST). A
read error publishes nothing (fail-closed to "not recorded"), never a guess.
"""

from __future__ import annotations

import logging

from common.pacific_time import pacific_date_of
from experiment.phase_filter import singleton_visible

from coach import advice_links as _al

logger = logging.getLogger(__name__)

#: Answers that leave an ask open on the owner's queue: taken back, or not yet decided.
UNSETTLED_STATES: frozenset[str] = frozenset({_al.WITHDRAWN, _al.NOT_YET_DECIDED})


def _revisions(table, user_id: str, prefix: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(_al.ask_response_pk(user_id)) & Key("sk").begins_with(prefix)}
    rows: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs = {**kwargs, "ExclusiveStartKey": resp["LastEvaluatedKey"]}
    # A wiped cycle's revision (tombstoned or tagged at a reset) is not an answer to a current ask.
    return [r for r in rows if singleton_visible(r) and str(r.get("sk") or "").startswith(prefix)]


def public_outcomes(table, user_id: str, coach_id: str) -> dict[str, dict]:
    """{ask_id: public outcome} for one coach — the public projection only. Fail-closed: an error returns {}."""
    try:
        rows = _revisions(table, user_id, _al.ask_response_prefix(coach_id))
    except Exception as e:  # noqa: BLE001 — a failed read publishes nothing; every ask reads "not recorded"
        logger.warning(f"[ask_outcomes] {coach_id}: {e}")
        return {}
    out: dict[str, dict] = {}
    for (cid, ask_id), latest in _al.latest_by_ask(rows).items():
        if cid != coach_id:
            continue
        outcome = _al.public_ask_outcome(latest, pacific_date_of(str(latest.get("recorded_at") or "")))
        if outcome:
            out[ask_id] = outcome
    return out


def owner_answers(table, user_id: str, coach_ids: list[str]) -> dict[tuple[str, str], dict]:
    """(coach_id, ask_id) -> {state, recorded_at, revisions} — owner-side (MCP), no note. Fail-soft per coach."""
    out: dict[tuple[str, str], dict] = {}
    for cid in coach_ids:
        try:
            rows = _revisions(table, user_id, _al.ask_response_prefix(cid))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ask_outcomes] owner {cid}: {e}")
            continue
        by_ask: dict[str, list[dict]] = {}
        for r in rows:
            by_ask.setdefault(str(r.get("ask_id") or ""), []).append(r)
        for ask_id, revs in by_ask.items():
            view = _al.owner_ask_view(revs)
            out[(cid, ask_id)] = {"state": view["state"], "recorded_at": view["recorded_at"], "revisions": len(view["history"])}
    return out
