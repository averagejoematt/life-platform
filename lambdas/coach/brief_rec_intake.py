"""coach/brief_rec_intake.py — the Morning Brief as the recommendation record's first intake (#6158 pilot).

Owner rulings 2026-11-22 ("Morning Brief recommendation pilot — APPROVED IN PRINCIPLE") and 2026-11-23 (#6226).
DARK: nothing here runs unless `coach.brief_recommendations.CANONICAL_INTAKE_LIVE` is True; while it is False
`emails.brief_trial` never imports this module.

WHAT IT DOES, and the only things it does (the daily-brief function is the caller, owner-side):

  1. PLAN (before the send, reads only). The brief's one linked recommendation is ELIGIBLE when it is a coaching
     recommendation from the brief's AI guidance and the record's own admission rule admits its words (a
     readiness colour is a fixed-weight score, not a coach's advice; housekeeping is never one). If a head the
     brief wrote already carries this run's brief id (a REPEAT of an offered recommendation), the send is LINKED
     to it; otherwise its id is `rec_id_for(lead, brief day, exact words)`. The link's token row is stamped with
     that canonical id — the ACTIVATION MARKER: only a token minted while the pilot is live carries one, and only
     a stamped token is ever carried into the record.
  2. OFFER (after the send). Only when SES ACCEPTED the send (a MessageId came back): one conditional put of the
     head (`build_offered_head`), recorded by the brief, never by the owner. A retry or a duplicate send of the same
     day's words makes the same id and the put refuses it; a reworded REPEAT links to the existing head. No send,
     no head. A failed write is logged and left: there is NO reconciliation path that writes a head later.
  3. CARRY HIS ANSWERS (the next run). A spent token stamped with a canonical id whose head exists becomes ONE
     response event (`build_button_response`): `recorded_by: owner` (the press is his), its instant his press,
     its key fixed by the token so a replay refuses. Unspent / expired = nothing: silence is not an answer.
  4. ONE DUE FOLLOW-UP. A follow-up date exists only when he agreed one (the owner tool's `follow_up` action). For
     a head the brief wrote, the brief is the one channel that asks it (`rr.due_follow_ups(surface=brief)`; the
     conversation's default surface excludes it), once: the SEND# row that asked it carries its id.

Never: an outcome, a follow-up date, or any answer from sensor, training or nutrition data — this module reads the
recommendation partition and the brief's own trial partition and nothing else (tests/test_brief_rec_pilot_6158.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from boto3.dynamodb.conditions import Key
from common.pacific_time import shift_day_key

from coach import brief_recommendations as seam, recommendation_record as rr

logger = logging.getLogger("brief-rec-intake")

USER_ID = "matthew"
#: The brief's guidance is not written in a persona's voice; the owner named the lead as the pilot's coordinating
#: coach (ruling 2026-11-22 §1), so the record attributes it to the lead and says how (`ATTRIBUTION`).
COACH_ID = rr.LEAD_COACH_ID
ATTRIBUTION = "Morning Brief guidance, attributed to the coordinating lead"
ELIGIBLE_SOURCES = frozenset({"ai_guidance"})
#: The response page's button -> the record's vocabulary (the page's keys are `seam.RESPONSES`; a test holds them equal).
BUTTON_RESPONSES: dict[str, str] = {"done": rr.ACCEPTED, "not_doing": rr.DECLINED, "still_deciding": rr.STILL_DECIDING}
TOKEN_PREFIX = "TOKEN#"  # noqa: S105 — a sort-key prefix, not a secret


def _conditional_failed(e: Exception) -> bool:
    return "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e)


def brief_day(data_day: str) -> str:
    """The day the brief is FOR (it is built from yesterday's data and read this morning)."""
    return shift_day_key(data_day, 1)


def eligibility(rec: Any) -> tuple[bool, str]:
    if rec is None:
        return False, "no recommendation carried the response link"
    if getattr(rec, "kind", None) != "coaching" or getattr(rec, "source", None) not in ELIGIBLE_SOURCES:
        return False, f"not a coach's recommendation (source {getattr(rec, 'source', None)})"
    verdict = rr.admit(getattr(rec, "text", ""))
    return (True, "") if verdict["admitted"] else (False, "not admitted: " + "; ".join(verdict["reasons"]))


@dataclass
class Offer:
    canonical_rec_id: str
    brief_rec_id: str
    day: str
    text: str
    source: str
    evidence: list
    context: str
    new: bool  # False = a REPEAT linked to the head the brief already wrote


def _brief_heads(rows: list) -> list:
    return [r for r in rows if r.get("record_type") == "recommendation" and r.get("recorded_by") == rr.RECORDED_BY_BRIEF]


def plan_offer(table, rec: Any, data_day: str) -> tuple[Optional[Offer], str]:
    """(offer, "") or (None, why not). READS the record (raises if it cannot — the caller degrades)."""
    ok, why = eligibility(rec)
    if not ok:
        return None, why
    day = brief_day(data_day)
    existing = next((h for h in _brief_heads(rr.read_rows(table, USER_ID)) if h.get("brief_rec_id") == rec.rec_id), None)
    status = "NEW" if rec.day_n <= 1 else f"REPEAT, day {rec.day_n} of a run that began {rec.first_seen}"
    return (
        Offer(
            canonical_rec_id=existing["rec_id"] if existing else rr.rec_id_for(COACH_ID, day, rec.text),
            brief_rec_id=rec.rec_id,
            day=day,
            text=rec.text,
            source=rec.source,
            evidence=[e for e in (rec.evidence, "Confidence " + str(rec.confidence) + ". " + str(rec.basis)) if e],
            context=f"Morning Brief for {day} ({status}). {ATTRIBUTION}.",
            new=existing is None,
        ),
        "",
    )


def write_offer(table, offer: Offer, *, ses_message_id: Optional[str], offered_at: str) -> str:
    """After the send. Returns the state for the SEND# row: recorded | duplicate | linked | not_delivered.
    Raises on any other write failure (the caller logs it; nothing is retried or reconstructed later)."""
    if not ses_message_id:
        return "not_delivered"
    if not offer.new:
        return "linked"
    head = rr.build_offered_head(
        user_id=USER_ID,
        coach_id=COACH_ID,
        text=offer.text,
        day=offer.day,
        offered_at=offered_at,
        ses_message_id=ses_message_id,
        brief_rec_id=offer.brief_rec_id,
        source=offer.source,
        evidence=offer.evidence,
        context=offer.context,
        recorded_at=rr.now_instant(),
    )
    if head["rec_id"] != offer.canonical_rec_id:  # the id stamped on the link must be the id written
        raise rr.RecommendationError("planned and written recommendation ids differ")
    try:
        table.put_item(Item=head, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only a conditional failure is a duplicate
        if not _conditional_failed(e):
            raise
        return "duplicate"
    return "recorded"


def _instant(iso: str) -> str:
    """The token row's `used_at` (isoformat, UTC) in the record's instant format."""
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def carry_responses(table, trial_pk: str) -> dict[str, int]:
    """Spent, pilot-stamped tokens -> one response event each, exactly once. Counts by outcome (never raises
    for one bad row; a read failure raises to the caller)."""
    tokens = rr._query_all(table, Key("pk").eq(trial_pk) & Key("sk").begins_with(TOKEN_PREFIX))
    rows = rr.read_rows(table, USER_ID)
    heads = {r["rec_id"]: r for r in rows if r.get("record_type") == "recommendation" and r.get("sk") == rr.head_sk(r.get("rec_id", ""))}
    carried = {r.get("token_hash") for r in rows if r.get("record_type") == "recommendation_event" and r.get("token_hash")}
    n = {"carried": 0, "already": 0, "unanswered": 0, "pre_activation": 0, "no_head": 0, "refused": 0}
    for tok in tokens:
        rid, th = tok.get("canonical_rec_id"), str(tok.get("sk", ""))[len(TOKEN_PREFIX) :]
        if not rid:
            n["pre_activation"] += 1  # minted before the pilot (or while the record was unreadable): never folded
        elif not tok.get("used_at"):
            n["unanswered"] += 1
        elif th in carried:
            n["already"] += 1
        elif rid not in heads or str(tok.get("send_day") or "") < str(shift_day_key(heads[rid].get("date"), -1)):
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
                table.put_item(Item=ev, ConditionExpression="attribute_not_exists(sk)")
                n["carried"] += 1
            except Exception as e:  # noqa: BLE001 — one bad row never costs the others
                n["already" if _conditional_failed(e) else "refused"] += 1
                if not _conditional_failed(e):
                    logger.warning("[brief_rec_pilot] answer not carried rec=%s: %s", rid, type(e).__name__)
    return n


def due_follow_up(table, trial_pk: str, day: str) -> Optional[dict[str, Any]]:
    """The ONE brief-owned follow-up due on `day` that no earlier brief has asked, or None."""
    for v in rr.due_follow_ups(rr.fold(rr.read_rows(table, USER_ID)), day, surface=rr.SURFACE_BRIEF):
        since = shift_day_key(str(v["follow_up_on"]), -1)  # SEND# rows are keyed by data day = brief day - 1
        sends = rr._query_all(table, Key("pk").eq(trial_pk) & Key("sk").between("SEND#" + since, "SEND#9999-12-31"))
        if not any(s.get("follow_up_rec_id") == v["rec_id"] for s in sends):
            return {"rec_id": v["rec_id"], "text": v["text"], "follow_up_on": v["follow_up_on"], "date": v["date"]}
    return None
