"""GET /api/coach_brief?coach=<persona_id> — the public-safe coaching brief, served for the Coaching Room (dark).

Owner ruling 2026-11-09 (third, E). The producer is ``coach.public_brief``; the policy, the input whitelist and the dark
switch are ``common.public_brief_policy``. While ``PUBLICATION_LIVE`` is False this route answers 404 for every coach —
the brief, its calls and its evidence are not publicly visible until the owner turns it on with the Coaching Room.

EVERY READ GOES THROUGH THE PUBLIC CHOKEPOINT. The table handed in is ``web.site_api_common.table`` — the
``narrative_publication.PublicationTable`` — so a brief row, an evidence row or a revision row whose provenance names a
private, unknown or missing family reaches this serializer withheld, and a brief call the call policy does not publish
does not reach it at all. This module then OMITS, never marks: a withheld brief is left out with its evidence and
revisions; a withheld evidence or revision row is left out; a call the ledger does not serve is left out together with
its frozen criteria. No count of what was left out is served.

The six sections are served apart, exactly as the producer stored them:
  ``observations`` + ``interpretations`` · ``predictions`` (with the ledger's current status) · ``evaluation_criteria``
  (frozen at filing) · ``recommendations`` · ``owner_actions`` (recorded evidence with its source and days, or a state
  that says why there is none) · ``revisions`` (append-only, each naming the item it revises).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from common import public_brief_policy as POL

MAX_BRIEFS = 12


def _f(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _f(x) for k, x in v.items() if not str(k).startswith("_")}
    if isinstance(v, list):
        return [_f(x) for x in v]
    return v


def _withheld(row: Any) -> bool:
    from web.narrative_publication import is_withheld

    return not isinstance(row, dict) or is_withheld(row)


def _owner_action(rec: dict, evidence: Optional[dict], cycle: str, today: str) -> dict:
    if not rec.get("check"):
        return {"recommendation_id": rec.get("id"), "state": "not_measured"}
    if evidence is None:
        settled = (datetime.strptime(POL.cycle_end(cycle), "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") <= today
        return {"recommendation_id": rec.get("id"), "state": "not_recorded" if settled else "pending"}
    keys = ("state", "metric", "condition", "threshold", "window_start", "window_end", "days_in_window", "days_with_data")
    out = {"recommendation_id": rec.get("id"), **{k: evidence.get(k) for k in keys}}
    out.update(
        days_meeting=evidence.get("days_meeting"), readings=evidence.get("readings") or [], source_refs=evidence.get("source_refs") or []
    )
    out["as_of"] = evidence.get("as_of")
    return out


def serve(rows: list, get_call: Callable[[str, str], Optional[dict]], today: str) -> list:
    """The served briefs, newest first, from the gated rows of one coach's ``PUBLIC_BRIEF#`` range."""
    briefs: dict = {}
    evidence: dict = {}
    revisions: dict = {}
    for r in rows or []:
        sk = str((r or {}).get("sk") or "")
        if not sk.startswith(POL.BRIEF_SK_PREFIX) or _withheld(r):
            continue
        r = _f(r)
        cycle = str(r.get("brief_cycle") or "")
        if POL.EVIDENCE_TAG in sk:
            evidence.setdefault(cycle, {})[r.get("recommendation_id")] = r
        elif POL.REVISION_TAG in sk:
            revisions.setdefault(cycle, []).append(r)
        elif sk == POL.brief_sk(cycle):
            briefs[cycle] = r
    out = []
    for cycle in sorted(briefs, reverse=True)[:MAX_BRIEFS]:
        b = briefs[cycle]
        coach_id = str(b.get("coach_id") or "")
        preds, criteria = [], []
        served_ids = set()
        for p in b.get("predictions") or []:
            call = get_call(coach_id, str(p.get("prediction_id") or ""))
            if not isinstance(call, dict) or _withheld(call) or not call.get("claim_natural"):
                continue
            served_ids.add(p.get("prediction_id"))
            preds.append({**p, "ledger": {"status": call.get("status"), "outcome_date": call.get("outcome_date")}})
        criteria = [c for c in b.get("evaluation_criteria") or [] if c.get("prediction_id") in served_ids]
        recs = b.get("recommendations") or []
        ev = evidence.get(cycle, {})
        out.append(
            {
                "cycle": cycle,
                "cycle_end": b.get("cycle_end"),
                "data_through": b.get("data_through"),
                "generated_at": b.get("generated_at"),
                "observations": b.get("observations") or [],
                "interpretations": b.get("interpretations") or [],
                "predictions": preds,
                "evaluation_criteria": criteria,
                "recommendations": recs,
                "owner_actions": [_owner_action(r, ev.get(r.get("id")), cycle, today) for r in recs],
                "revisions": [
                    {k: v.get(k) for k in ("target", "kind", "text", "reason", "revised_in_cycle", "generated_at")}
                    for v in sorted(revisions.get(cycle, []), key=lambda x: str(x.get("sk")))
                ],
            }
        )
    return out


def handle_coach_brief(event: dict, *, table: Any = None, live: Optional[bool] = None, today: Optional[str] = None) -> dict:
    from web.site_api_common import _error, _ok

    if not (POL.PUBLICATION_LIVE if live is None else live):
        return _error(404, "Not found")
    from coach.public_brief import brief_coaches

    coach = str(((event or {}).get("queryStringParameters") or {}).get("coach") or "").strip()
    if coach not in brief_coaches():
        return _error(404, "Not found")
    if table is None:
        from web.site_api_common import table as _table

        table = _table
    if today is None:
        from common.pacific_time import pacific_today

        today = pacific_today()
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :p)",
        "ExpressionAttributeValues": {":pk": f"COACH#{coach}", ":p": POL.BRIEF_SK_PREFIX},
        "ScanIndexForward": False,
    }
    rows: list = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def get_call(coach_id: str, prediction_id: str) -> Optional[dict]:
        if not prediction_id:
            return None
        return table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"PREDICTION#{prediction_id}"}).get("Item")

    briefs = serve(rows, get_call, today)
    newest = briefs[0]["generated_at"] if briefs else None
    return _ok({"coach_id": coach, "method": POL.method_block(), "briefs": briefs}, cache_seconds=300, content_as_of=newest)
