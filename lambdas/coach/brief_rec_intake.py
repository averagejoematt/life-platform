"""coach/brief_rec_intake.py — the Morning Brief's side of the recommendation-record pilot (#6158). READS ONLY.

Owner rulings 2026-11-22 ("Morning Brief recommendation pilot — APPROVED IN PRINCIPLE", and his feedback on #6232) and
2026-11-23 (#6226). DARK: nothing here runs unless `coach.brief_recommendations.CANONICAL_INTAKE_LIVE` is True; while
it is False `emails.brief_trial` never imports this module.

This module never writes the record. The daily-brief function's role holds an explicit Deny on every write to the
record partition; every write goes through the dedicated writer, `coach-recommendation-writer`
(`coach.recommendation_writer_lambda`), which this module invokes synchronously (`invoke_writer`).

  1. PLAN (before the send). The brief's one linked recommendation is ELIGIBLE when it is a coaching recommendation
     from the brief's AI guidance and the record's own admission rule admits its words (a readiness colour is a
     fixed-weight score; housekeeping is never one). If the brief already offered it (a REPEAT of this run), the send
     links to that head and will be recorded as an EXPOSURE — and if he has already given a settled answer, the
     brief shows that answer instead of asking again. Otherwise its id is `rec_id_for(lead, brief day, exact words)`.
     The link's token row carries that canonical id: the ACTIVATION MARKER.
  2. ATTRIBUTION. The lead (`rr.LEAD_COACH_ID`) is ACCOUNTABLE for every brief recommendation; the ORIGIN is where the
     words came from (`ORIGIN_BY_SOURCE`) — the brief's AI guidance call, a platform rule, a named coach — and an
     unrecognised source is recorded as unknown, never as the lead.
  3. ONE DUE FOLLOW-UP he agreed to, on a head the brief offered (`rr.due_follow_ups(surface=brief)`), asked once.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from boto3.dynamodb.conditions import Key
from common.pacific_time import shift_day_key

from coach import recommendation_record as rr

logger = logging.getLogger("brief-rec-intake")

USER_ID = "matthew"
COACH_ID = rr.LEAD_COACH_ID  # ACCOUNTABLE (owner feedback 2026-11-22: "Approve Eli Marsh as the accountable lead")
WRITER_FUNCTION = "coach-recommendation-writer"
ELIGIBLE_SOURCES = frozenset({"ai_guidance"})
#: The brief's recommendation sources (`content.brief_hybrid.Rec.source`) -> (origin_kind, origin_id). The AI guidance
#: is ONE model call with no persona (`ai.ai_calls.call_tldr_and_guidance`), so its origin is that system — not a coach.
ORIGIN_BY_SOURCE: dict[str, tuple[str, Optional[str]]] = {
    "ai_guidance": (rr.ORIGIN_SYSTEM, "ai_calls.call_tldr_and_guidance"),
    "readiness": (rr.ORIGIN_RULE, "readiness_score"),
    "food_export": (rr.ORIGIN_RULE, "food_export_check"),
}
#: Answers that settle a recommendation: a repeat after one of these shows his answer and asks nothing new.
SETTLED = frozenset({rr.ACCEPTED, rr.DECLINED, rr.PARTIALLY_FOLLOWED})


def origin_of(source: Any) -> tuple[str, Optional[str]]:
    """Never the lead by default: a source this table does not know is `unknown`, with no id."""
    return ORIGIN_BY_SOURCE.get(str(source), (rr.ORIGIN_UNKNOWN, None))


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
    new: bool  # False = a REPEAT: an exposure on the head the brief already wrote
    origin_kind: str = rr.ORIGIN_UNKNOWN
    origin_id: Optional[str] = None
    answer: str = rr.NOT_RECORDED  # his current answer on the existing head (repeats only)
    answer_label: str = ""
    answered_at: Optional[str] = None

    @property
    def settled(self) -> bool:
        return (not self.new) and self.answer in SETTLED


def plan_offer(table, rec: Any, data_day: str) -> tuple[Optional[Offer], str]:
    """(offer, "") or (None, why not). READS the record (raises if it cannot — the caller degrades)."""
    ok, why = eligibility(rec)
    if not ok:
        return None, why
    day = brief_day(data_day)
    views = rr.fold(rr.read_rows(table, USER_ID))
    existing = next((v for v in views if v.get("recorded_by") == rr.RECORDED_BY_BRIEF and v.get("brief_rec_id") == rec.rec_id), None)
    status = "NEW" if rec.day_n <= 1 else f"REPEAT, day {rec.day_n} of a run that began {rec.first_seen}"
    kind, oid = origin_of(rec.source)
    o = Offer(
        canonical_rec_id=existing["rec_id"] if existing else rr.rec_id_for(COACH_ID, day, rec.text),
        brief_rec_id=rec.rec_id,
        day=day,
        text=rec.text,
        source=rec.source,
        evidence=[e for e in (rec.evidence, "Confidence " + str(rec.confidence) + ". " + str(rec.basis)) if e],
        context=f"Morning Brief for {day} ({status}). Accountable: the lead coach. Origin: {kind}" + (f" ({oid})." if oid else "."),
        new=existing is None,
        origin_kind=kind,
        origin_id=oid,
    )
    if existing:
        o.answer, o.answer_label, o.answered_at = existing["response"], existing["response_label"], existing.get("response_recorded_at")
    return o, ""


def offer_payload(offer: Offer, *, send_day: str, token_hash: str, ses_message_id: Optional[str], accepted_at: str) -> dict[str, Any]:
    """The writer's `offer` event: the brief's own recommendation and its accepted send — nothing it did not offer."""
    return {
        "action": "offer",
        "new": offer.new,
        "canonical_rec_id": offer.canonical_rec_id,
        "brief_rec_id": offer.brief_rec_id,
        "brief_day": offer.day,
        "send_day": send_day,
        "text": offer.text,
        "source": offer.source,
        "evidence": offer.evidence,
        "context": offer.context,
        "origin_kind": offer.origin_kind,
        "origin_id": offer.origin_id,
        "token_hash": token_hash,
        "ses_message_id": ses_message_id,
        "accepted_at": accepted_at,
    }


class WriterFailed(RuntimeError):
    """The writer ran and failed (its own exception); `error_type` is the class it reported."""

    def __init__(self, error_type: str):
        super().__init__("recommendation writer failed: " + error_type)
        self.error_type = error_type


def failure_class(e: Exception) -> str:
    """The class name the SEND# row records for a failed invoke: the writer's own exception, the Lambda service's
    error code (TooManyRequestsException = throttled), or the client's (ReadTimeoutError = timed out)."""
    if isinstance(e, WriterFailed):
        return e.error_type
    code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code")
    return str(code or type(e).__name__)


def invoke_writer(payload: dict[str, Any], client=None) -> dict[str, Any]:
    """Synchronous invoke of `coach-recommendation-writer`. Raises when the writer failed (the caller logs and goes on)."""
    if client is None:
        import boto3

        client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    resp = client.invoke(FunctionName=os.environ.get("REC_WRITER_FUNCTION", WRITER_FUNCTION), Payload=json.dumps(payload, default=str))
    body = json.loads(resp["Payload"].read() or b"{}")
    if resp.get("FunctionError"):
        raise WriterFailed(str((body or {}).get("errorType") or "error"))
    return body


def due_follow_up(table, trial_pk: str, day: str) -> Optional[dict[str, Any]]:
    """The ONE brief-owned follow-up due on `day` that no earlier brief has asked, or None."""
    for v in rr.due_follow_ups(rr.fold(rr.read_rows(table, USER_ID)), day, surface=rr.SURFACE_BRIEF):
        since = shift_day_key(str(v["follow_up_on"]), -1)  # SEND# rows are keyed by data day = brief day - 1
        sends = rr._query_all(table, Key("pk").eq(trial_pk) & Key("sk").between("SEND#" + since, "SEND#9999-12-31"))
        if not any(s.get("follow_up_rec_id") == v["rec_id"] for s in sends):
            return {"rec_id": v["rec_id"], "text": v["text"], "follow_up_on": v["follow_up_on"], "date": v["date"]}
    return None
