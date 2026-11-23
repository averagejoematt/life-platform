"""coach/recommendation_writer_lambda.py — `coach-recommendation-writer`, the Morning Brief pilot's dedicated writer (#6158).

Owner feedback 2026-11-22 on #6232: "avoid reusing the Morning Brief function's broadly privileged role for canonical
recommendation writes … approve a small dedicated internal writer with narrowly scoped IAM permissions. Make sure the
permission actually restricts the DynamoDB keys the function can write, and that creating a recommendation cannot
overwrite an existing record."

THE PRINCIPAL. This function's role (`role_policies_compute.compute_recommendation_writer`) may PutItem ONLY under the
partition key `USER#matthew#SOURCE#coach_recommendations` (`dynamodb:LeadingKeys`), may read only that partition and
the brief's trial partition, and has no UpdateItem, DeleteItem or batch write anywhere. The daily-brief function
invokes it synchronously and holds an explicit Deny on every write to the record partition. (Other functions' older
table-wide grants still reach the partition; that is a separate remediation, #6237 — this is the brief's path, not the
partition's only possible writer.) It runs on nothing else:
no schedule, no URL, no event source. DARK: nothing invokes it while `brief_recommendations.CANONICAL_INTAKE_LIVE`
is False.

NO OVERWRITE. IAM cannot require a condition expression on PutItem, so the guarantee is this module: every write is
`put_item(..., ConditionExpression="attribute_not_exists(sk)")`, there is no update, delete or batch write, and
tests/test_brief_rec_pilot_6158.py sweeps this file's AST for exactly that.

TWO ACTIONS (the event's `action`):

  offer  After SES ACCEPTED a hybrid send (a MessageId came back — accepted by the mail service, not proof of inbox
         delivery or reading). The brief's one linked recommendation either becomes a head (lifecycle `offered`,
         `delivery_state: accepted_by_mail_service`) or, when the brief already offered it (a REPEAT), one EXPOSURE
         event on that head: the new send recorded, no new decision asked, the response untouched. The payload must
         match the stamped token row the brief wrote for that send, or nothing is written.
  carry  His spent button answers -> one response event each, exactly once. A token counts only if the SEND# row of
         the brief that minted it lists its hash for that recommendation (`pilot_tokens`); its key is fixed by the
         token. Unspent, unbound, pre-activation and headless tokens are counted and left.

Never: an outcome, a follow-up date, an answer from sensor/training/nutrition data, a head without a MessageId, or a
row reconstructed later for a send whose offer failed.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from boto3.dynamodb.conditions import Key
from common.pacific_time import parse_iso_utc

from coach import brief_recommendations as seam, recommendation_record as rr

try:  # the platform's structured logger (INFO reaches CloudWatch); plain logging if it cannot load
    from common.platform_logger import get_logger

    logger = get_logger("coach-recommendation-writer")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("coach-recommendation-writer")
    logger.setLevel(logging.INFO)

USER_ID = "matthew"
TRIAL_PK = f"USER#{USER_ID}#SOURCE#{seam.TRIAL_SOURCE}"
TOKEN_PREFIX = "TOKEN#"  # noqa: S105 — a sort-key prefix, not a secret
SEND_PREFIX = "SEND#"
#: The response page's button -> the record's vocabulary (the page's keys are `seam.RESPONSES`; a test holds them equal).
BUTTON_RESPONSES: dict[str, str] = {"done": rr.ACCEPTED, "not_doing": rr.DECLINED, "still_deciding": rr.STILL_DECIDING}
_CONDITION = "attribute_not_exists(sk)"

_table = None  # tests inject a recording table here


def _tbl():
    global _table
    if _table is None:
        import boto3

        _table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
            os.environ.get("TABLE_NAME", "life-platform")
        )
    return _table


def _conditional_failed(e: Exception) -> bool:
    return "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e)


def _put_new(table, item: dict[str, Any]) -> bool:
    """THE write: create-only. True = written; False = a row with that key already exists (nothing replaced)."""
    try:
        table.put_item(Item=item, ConditionExpression=_CONDITION)
    except Exception as e:  # noqa: BLE001 — only a conditional failure is "already there"
        if not _conditional_failed(e):
            raise
        return False
    return True


def _instant(iso: str) -> str:
    dt = parse_iso_utc(iso)
    if dt is None:
        raise rr.RecommendationError("not an ISO instant")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── offer ────────────────────────────────────────────────────────────────────────────────────


def _bound_token(table, p: dict[str, Any]) -> Optional[str]:
    """Why the payload is NOT the brief's own stamped send, or None when it is."""
    th = str(p.get("token_hash") or "")
    # ConsistentRead: the brief put this row milliseconds before invoking us (brief_trial.record writes the stamped
    # token, THEN invokes the writer); an eventually consistent read could miss it and refuse a genuine offer.
    tok = table.get_item(Key={"pk": TRIAL_PK, "sk": TOKEN_PREFIX + th}, ConsistentRead=True).get("Item") if th else None
    if not tok:
        return "no stamped token row for this send"
    if tok.get("canonical_rec_id") != p.get("canonical_rec_id") or str(tok.get("send_day")) != str(p.get("send_day")):
        return "the token row does not match the offer"
    return None


def offer(table, p: dict[str, Any]) -> dict[str, Any]:
    """One accepted send -> a new head, or an exposure on the head the brief already wrote."""
    msg = str(p.get("ses_message_id") or "").strip()
    if not msg:
        return {"state": "refused", "reason": "no mail-service message id: not accepted for delivery, nothing recorded"}
    why = _bound_token(table, p)
    if why:
        return {"state": "refused", "reason": why}
    rid = str(p["canonical_rec_id"])
    head = table.get_item(Key={"pk": rr.pk(USER_ID), "sk": rr.head_sk(rid)}, ConsistentRead=True).get("Item")
    if head is None:
        if not p.get("new"):
            return {"state": "refused", "reason": "a repeat of a recommendation the record does not hold"}
        row = rr.build_offered_head(
            user_id=USER_ID,
            coach_id=rr.LEAD_COACH_ID,
            origin_kind=str(p.get("origin_kind") or rr.ORIGIN_UNKNOWN),
            origin_id=p.get("origin_id"),
            text=str(p.get("text") or ""),
            day=str(p.get("brief_day")),
            send_day=str(p.get("send_day")),
            accepted_at=_instant(str(p.get("accepted_at"))),
            ses_message_id=msg,
            brief_rec_id=str(p.get("brief_rec_id")),
            source=str(p.get("source")),
            evidence=p.get("evidence"),
            context=p.get("context"),
            recorded_at=rr.now_instant(),
        )
        if row["rec_id"] != rid:
            return {"state": "refused", "reason": "planned and constructed recommendation ids differ"}
        return {"state": "offered" if _put_new(table, row) else "duplicate", "rec_id": rid}
    if head.get("recorded_by") != rr.RECORDED_BY_BRIEF:
        return {"state": "refused", "reason": "the head was not offered by the brief"}
    return {"state": exposure(table, head, p, msg), "rec_id": rid}


def exposure(table, head: dict[str, Any], p: dict[str, Any], msg: str) -> str:
    """A repeat: record the new send on the existing head. One per send day; the head's own send is its first."""
    send_day = str(p.get("send_day"))
    if send_day == str(head.get("first_send_day")):
        return "duplicate"
    rows = rr.read_rows(table, USER_ID, head["rec_id"])
    if any(r.get("kind") == rr.EVENT_EXPOSURE and str(r.get("send_day")) == send_day for r in rows):
        return "duplicate"
    ev = rr.build_exposure_event(
        user_id=USER_ID,
        rec=head,
        send_day=send_day,
        accepted_at=_instant(str(p.get("accepted_at"))),
        ses_message_id=msg,
        brief_rec_id=str(p.get("brief_rec_id")),
    )
    return "exposure_recorded" if _put_new(table, ev) else "duplicate"


# ── carry ────────────────────────────────────────────────────────────────────────────────────


def carry(table) -> dict[str, int]:
    """Spent, bound tokens -> one response event each, exactly once."""
    tokens = rr._query_all(table, Key("pk").eq(TRIAL_PK) & Key("sk").begins_with(TOKEN_PREFIX))
    sends = rr._query_all(table, Key("pk").eq(TRIAL_PK) & Key("sk").begins_with(SEND_PREFIX))
    bound: dict[str, str] = {}
    for s in sends:
        for th, rid in (s.get("pilot_tokens") or {}).items():
            bound[str(th)] = str(rid)
    rows = rr.read_rows(table, USER_ID)
    heads = {r["rec_id"]: r for r in rows if r.get("record_type") == "recommendation" and r.get("sk") == rr.head_sk(r.get("rec_id", ""))}
    carried = {r.get("token_hash") for r in rows if r.get("record_type") == "recommendation_event" and r.get("token_hash")}
    n = {"carried": 0, "already": 0, "unanswered": 0, "pre_activation": 0, "unbound": 0, "no_head": 0, "refused": 0}
    for tok in tokens:
        rid, th = tok.get("canonical_rec_id"), str(tok.get("sk", ""))[len(TOKEN_PREFIX) :]
        if not rid:
            n["pre_activation"] += 1  # minted before the pilot, or while the record was unreadable: never carried
        elif bound.get(th) != rid:
            n["unbound"] += 1  # no SEND# row minted this hash for this recommendation: altered or forged, never carried
        elif not tok.get("used_at"):
            n["unanswered"] += 1  # silence is not an answer
        elif th in carried:
            n["already"] += 1
        elif rid not in heads:
            n["no_head"] += 1  # the offer was never recorded: his answer stays on the trial row only
        else:
            try:
                ev = rr.build_button_response(
                    user_id=USER_ID,
                    rec=heads[rid],
                    response=BUTTON_RESPONSES.get(str(tok.get("response"))),
                    answered_at=_instant(tok["used_at"]),
                    token_hash=th,
                    send_day=str(tok.get("send_day")),
                    word=seam.RESPONSE_WORDS.get(str(tok.get("response")), ""),
                )
                if _put_new(table, ev):
                    n["carried"] += 1
                    carried.add(th)
                else:
                    n["already"] += 1
            except Exception as e:  # noqa: BLE001 — one bad row never costs the others
                n["refused"] += 1
                logger.warning("[rec_writer] answer not carried rec=%s: %s", rid, type(e).__name__)
    return n


def lambda_handler(event, context=None):
    """{"action": "offer", ...} | {"action": "carry"}. Returns a small status dict; never raises for one bad row."""
    try:
        action = (event or {}).get("action")
        if action == "offer":
            out = offer(_tbl(), event)
        elif action == "carry":
            out = {"state": "carried", "counts": carry(_tbl())}
        else:
            out = {"state": "refused", "reason": "unknown action"}
        logger.info("[rec_writer] action=%s state=%s", action, out.get("state"))
        return out
    except Exception as e:  # noqa: BLE001 — the brief logs the class; an Errors datapoint is the alarm
        logger.error("[rec_writer] failed: %s", type(e).__name__)
        raise
