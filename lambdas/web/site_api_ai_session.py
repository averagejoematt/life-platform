"""lambdas/web/site_api_ai_session.py — the #546 board follow-up session store.

Extracted from ``site_api_ai_lambda.py`` rather than grown inside it: that module
sits at its recorded size ceiling (`tests/test_module_size_guard.py`), and the
guard's rule is to pay for new lines out of an extracted sibling instead of
raising the number. Same shape as the ``site_api_ai_request.py`` split (#2688).

Deliberately has NO import of the lambda module (no cycle): the DynamoDB table
resource is handed in by the caller, so every function here is drivable offline.

Security posture (this backs a PUBLIC, unauthenticated endpoint):
  * token is opaque + unguessable (``secrets.token_urlsafe``) — never sequential
    or derived from any request field; the token itself carries NO PII.
  * the record stores only an IP hash (already collected for rate limiting), the
    coach transcript, a turn counter, and a DDB TTL — no PII.
  * the session is bound to the originating IP hash, so a leaked token cannot be
    replayed from another network.
  * TTL ≤ 1h (DDB TTL attribute) AND a defensive in-code expiry check, since
    DynamoDB TTL deletion is lazy (an expired item can linger briefly).
  * the follow-up cap is enforced atomically (a conditional UpdateItem), and every
    follow-up still consumes a per-IP board_ask rate-limit token.

#3118 (DIL-025 census) — REPLAY IDENTITY. The cap condition used to enforce the
cap and the IP and nothing else, so a duplicate delivery of the SAME follow-up
appended the turn twice and burned two of the reader's three turns. Turn identity
is now first-class, at two levels:

  * ``replayed_turn`` lets the handler recognise a redelivery BEFORE any model
    spend and serve the stored answer (a replay costs $0 and costs no turn); and
  * ``append_board_turn`` records a ``turn_ids`` set and refuses to append an id
    already present, which closes the truly-simultaneous race the pre-check can't.

Both are keyed on ``turn_id`` = the coach plus the normalised question, which is
the "content hash of the question" identity #3118 asked for.
"""

import hashlib
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger()

SESSION_PK_PREFIX = "BOARDSESS#"
SESSION_TTL_SECONDS = 3600  # ≤ 1 hour — the acceptance ceiling (#546)
MAX_FOLLOWUPS = 3  # ≤ 3 follow-ups per session (cost + focus bound)
# token_urlsafe(24) → 32 url-safe chars; the shape gate rejects anything else
# BEFORE a DDB read (no guessable/sequential ids, no PII in the token itself).
_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def valid_session_token(token: str) -> bool:
    """True only for the opaque url-safe token shape we mint. Cheap gate run
    BEFORE any DDB read so malformed/probe tokens never touch the table."""
    return bool(token) and bool(_SESSION_TOKEN_RE.match(token))


def _norm(question: str) -> str:
    """Whitespace/case-normalised question text — the replay identity. Two
    deliveries of one reader keystroke-identical question must collide here even
    if a retrying client re-wraps the whitespace."""
    return " ".join(str(question or "").split()).casefold()


def turn_id(persona: str, question: str) -> str:
    """Stable id for one follow-up turn: the coach it was addressed to plus the
    normalised question. Same question to two coaches is two distinct turns."""
    return hashlib.sha256(f"{persona}:{_norm(question)}".encode()).hexdigest()[:16]


def replayed_turn(session: Dict[str, Any], persona: str, question: str) -> Optional[Dict[str, Any]]:
    """The already-stored follow-up turn this request is a redelivery of, or None.

    Index 0 of a thread is the OPENING ``board_ask`` turn, not a follow-up — it is
    deliberately excluded so that echoing the opening question as a genuine
    follow-up ("you said X — why?") is still a real, billable turn.
    """
    turns = (session.get("threads") or {}).get(persona) or []
    want = _norm(question)
    for turn in turns[1:]:
        if isinstance(turn, dict) and _norm(str(turn.get("q") or "")) == want:
            return turn
    return None


def create_board_session(table: Any, ip_hash: str, threads: Dict[str, Any]) -> Optional[str]:
    """Mint an opaque session token and persist the opening transcript.

    `threads` maps coach_id → [{"q", "a"}] (one opening turn per coach that
    actually answered). Returns the token, or None on any write failure (the
    reader still gets their answers — the session is a best-effort add-on).
    Decimal for the numeric attributes (boto3 rejects float). No PII is written.
    """
    if not threads:
        return None
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    try:
        table.put_item(
            Item={
                "pk": f"{SESSION_PK_PREFIX}{token}",
                "sk": "SESSION",
                "record_type": "board_session",
                "ip_hash": ip_hash,  # NOT PII — the same 16-char hash used for rate limiting
                "followup_count": Decimal(0),
                "threads": {
                    pid: [{"q": str(t.get("q", ""))[:500], "a": str(t.get("a", ""))[:1200]} for t in (turns or [])]
                    for pid, turns in threads.items()
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ttl": Decimal(now + SESSION_TTL_SECONDS),  # ≤ 1h — DDB TTL auto-purges
            }
        )
        return token
    except Exception as e:
        logger.warning(f"[board_ask] session create failed (non-fatal): {e}")
        return None


def load_board_session(table: Any, token: str) -> Optional[Dict[str, Any]]:
    """Fetch a session by opaque token. Returns None if absent OR expired —
    a defensive in-code expiry check backstops DDB's lazy TTL deletion so an
    expired thread can never be resumed. Decimal coercion stays the caller's job."""
    try:
        item = table.get_item(Key={"pk": f"{SESSION_PK_PREFIX}{token}", "sk": "SESSION"}).get("Item")
        if not item:
            return None
        if int(item.get("ttl") or 0) < int(time.time()):
            return None  # expired but not yet reaped by DDB
        return item
    except Exception as e:
        logger.warning(f"[board_ask] session load failed: {e}")
        return None


def append_board_turn(table: Any, token: str, ip_hash: str, persona: str, question: str, answer: str) -> bool:
    """Atomically append a follow-up turn and bump the counter, gated on the
    ≤3 cap, the originating IP, AND the turn's own identity (#3118). The
    ConditionExpression makes the cap a hard, race-safe ceiling (a burst can't
    double-spend past it) and makes a redelivered turn a no-op rather than a
    second append. Returns True on write, False if the condition failed (cap
    reached / IP mismatch / turn already recorded) or on error. Does NOT extend
    the TTL — total session life stays ≤ 1h from mint.
    """
    tid = turn_id(persona, question)
    try:
        table.update_item(
            Key={"pk": f"{SESSION_PK_PREFIX}{token}", "sk": "SESSION"},
            UpdateExpression=(
                "ADD followup_count :one, turn_ids :tids " "SET threads.#pid = list_append(if_not_exists(threads.#pid, :empty), :turn)"
            ),
            ConditionExpression=(
                "attribute_exists(pk) AND followup_count < :cap AND ip_hash = :ip "
                "AND (attribute_not_exists(turn_ids) OR NOT contains(turn_ids, :tid))"
            ),
            ExpressionAttributeNames={"#pid": persona},
            ExpressionAttributeValues={
                ":one": Decimal(1),
                ":cap": Decimal(MAX_FOLLOWUPS),
                ":empty": [],
                ":turn": [{"q": str(question)[:500], "a": str(answer)[:1200]}],
                ":ip": ip_hash,
                ":tid": tid,
                ":tids": {tid},
            },
        )
        return True
    except Exception as e:
        # ConditionalCheckFailedException lands here too — cap reached, IP moved,
        # or (#3118) this exact turn was already recorded by a first delivery.
        logger.warning(f"[board_ask] follow-up persist skipped for {persona} (non-fatal): {e}")
        return False
