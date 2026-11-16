"""site_api_reader_call.py — GET/POST /api/reader_call: a reader's own call beside a coach's open call (#6088, DARK).

Owner ruling 2026-11-16: "readers making their own prediction alongside the coaches" — lightweight, enjoyable, no
moderation, and it "must not alter my own historical evidence, grading records or experiments". The master switch
(``reader_call_rules.READER_CALL_LIVE``) is committed OFF: every request answers 404 "not available" before any read
or write, and the v9 control is built into no page.

WHAT A READER CAN DO. On an OPEN coach call — public (``web.call_publication`` decides, through the governed table
handle), words served by the ledger, a direction or number call, pending, before its due day — make the same kind of
call with one tap from a closed set (``reader_call_rules.CHOICES``). No account, no text, no email.

WHAT IS STORED (all under ``READERCALL#<call id>``, never ``USER#…`` or ``COACH#…``):
  * ``TAP#<salted identity>`` — the dedup marker, one per (identity, call), with a TTL a little past the due day.
    It holds no choice and no address: the identity is ``salted_ip_hash`` of the caller's /64 (IPv6) or address.
  * ``TALLY#<choice>`` — a counter, moved only by an atomic ``ADD``.

WRITE ORDER (dedup FIRST, then the counter — chosen over a TransactWriteItems pair). The conditional dedup put is
the decision: a replay, a concurrent duplicate or a changed choice from the same identity fails its condition and
never reaches the counter, so the tally can never move twice for one identity. If the counter ADD then fails, nothing
is deleted and the reader is told the tap was NOT recorded; the marker expires with its TTL. The failure mode is
therefore an under-count of one, never a double count. A transaction would remove even that, but it needs the
low-level client (typed attribute values) beside the resource table every other door uses, for a loss that only an
infrastructure error between two writes can cause — not worth a second write path. Both halves are tested.

THE TALLY FREEZES at the due day: POSTs are refused from the due day on (and once the call is graded), so what the
page shows beside the graded call is what readers said before the reading existed.

ABUSE CONTROLS, in order: the switch; the identity's salt (fail closed); a per-identity limit charged before any
other work and FAIL CLOSED (#6088); the honeypot field; the timing token (``reader_call_rules.check_token`` — issued
by the GET, bound to call + identity + instant, between 2 s and 1 h old); the public-pending-call check; the closed
choice set; the dedup marker. What this stops and does not stop is stated in the PR for #6088: it stops naive
scripts, replay and token harvesting across networks; it does not stop a distributed botnet holding many /64s — that
needs a rate rule at the edge — the edge firewall was removed in 2026-06, and whether it returns is an owner decision
recorded as overdue in docs/PROPORTIONALITY.md.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from boto3.dynamodb.conditions import Key
from coach import coach_record
from common.client_ip import extract_client_ip, salt_derived_key, salted_ip_hash
from common.pacific_time import pacific_today
from common.rate_limiter import check_rate_limit

from web import reader_call_rules as R

READ_LIMIT_PER_HOUR = 120
TAP_LIMIT_PER_HOUR = 30
NOT_AVAILABLE = "Reader calls are not available."
NOT_OPEN = "This call is not open for readers' calls."
UNAVAILABLE = "Reader calls are unavailable right now. Please try again shortly."
_GRADED = ("confirmed", "refuted")


def _method(event: dict) -> str:
    http = (event.get("requestContext") or {}).get("http") or {}
    return str(http.get("method") or event.get("httpMethod") or "GET").upper()


def _deps():
    from web.site_api_common import EXPERIMENT_START, _envelope, _error, logger, table

    return EXPERIMENT_START, _envelope, _error, logger, table


def _short_and_pid(call_id: str) -> Optional[tuple]:
    from web.site_api_coach_ledger import _CALIB_COACH_NAMES

    if not isinstance(call_id, str) or not R.CALL_ID_RE.match(call_id):
        return None
    shorts = sorted((s for s in _CALIB_COACH_NAMES if call_id.startswith(f"{s}-")), key=len, reverse=True)
    return (shorts[0], call_id[len(shorts[0]) + 1 :]) if shorts else None


def _presence(table: Any) -> list:
    from web.site_api_coach_ledger import _instrument_presence_safe

    return _instrument_presence_safe(_g={"table": table}) or []


def load_call(table: Any, call_id: str, today: str, *, genesis: Optional[str], presence: Callable = _presence) -> tuple:
    """``(view, None)`` for a call a reader may see a tally for, else ``(None, (status, message))``.

    The row is read through the GOVERNED handle (``narrative_publication.PublicationTable``), so a call that is not
    publication-eligible reads as absent; the item is then built by the ledger's own ``export_item`` and passed
    through its own journal-silence scrub, so this route can only ever name a call the ledger export serves — and
    only one whose words the ledger serves (a withheld or held claim is a 404, like an unknown id)."""
    from web.prediction_reason import _notes
    from web.site_api_ledger_export import export_item, servable

    sp = _short_and_pid(call_id)
    if sp is None:
        return None, (404, "Unknown call")
    short, pid = sp
    row = (table.get_item(Key={"pk": f"COACH#{short}_coach", "sk": f"PREDICTION#{pid}"}) or {}).get("Item")
    if not isinstance(row, dict) or coach_record.prediction_key(row) != pid or row.get("coach_id") == "":
        return None, (404, "Unknown call")
    if not coach_record.counts_this_cycle(row, genesis):
        return None, (404, "Unknown call")
    item = export_item(short, row, presence(table))
    kept, _ = servable([item])
    if not kept or not item.get("claim"):
        return None, (404, "Unknown call")
    spec = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
    kind = R.call_kind(spec)
    if kind is None or item.get("kind") != kind or item.get("sealed") or item.get("grading_held") or item.get("classification_review"):
        return None, (409, NOT_OPEN)
    due = item.get("due_date")
    status = item.get("status")
    view = {
        "call_id": call_id,
        "spec": spec,
        "kind": kind,
        "status": status,
        "due": due,
        "open": status == "pending" and bool(due) and today < str(due),
        "notes": _notes(row.get("outcome_notes")),
    }
    return view, None


def _tally(table: Any, call_id: str, spec: dict) -> Optional[dict]:
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(R.PK_PREFIX + call_id) & Key("sk").begins_with(R.TALLY_SK_PREFIX))
    except Exception:  # noqa: BLE001 — an unread tally is said, never shown as zero
        return None
    return R.tally_of(resp.get("Items"), spec)


def _meter(table: Any, ip_hash: str, tap: bool) -> tuple:
    """The two meters, FAIL CLOSED (#6088): a limiter error refuses rather than admits. Literal endpoints, so the
    fail-closed set guard (tests/test_reader_write_fail_closed_6088.py) can see both."""
    if tap:
        return check_rate_limit(
            table, endpoint="reader_call", ip_hash=ip_hash, limit=TAP_LIMIT_PER_HOUR, window_seconds=3600, fail_open=False
        )
    return check_rate_limit(
        table, endpoint="reader_call_read", ip_hash=ip_hash, limit=READ_LIMIT_PER_HOUR, window_seconds=3600, fail_open=False
    )


def _identity(event: dict, table: Any, tap: bool, deps) -> tuple:
    """``(ip_hash, None)`` or ``(None, refusal)`` — the salted identity, then the meter (charged first, FAIL CLOSED)."""
    _envelope, _error, logger = deps
    ip_hash = salted_ip_hash(extract_client_ip(event), logger)
    if ip_hash is None:
        return None, _error(503, UNAVAILABLE)
    allowed, _rem, retry = _meter(table, ip_hash, tap)
    if not allowed:
        return None, _envelope(429, {"error": "Too many requests from this network. Try again later."}, retry_after=retry or 60)
    return ip_hash, None


def _view_payload(view: dict, tally: Optional[dict]) -> dict:
    payload = {
        "available": True,
        "call": view["call_id"],
        "kind": view["kind"],
        "choices": R.choices(view["spec"]),
        "coach_choice": R.coach_choice(view["spec"]),
        "open": view["open"],
        "due_date": view["due"],
        "tally": tally,
        "copy": R.COPY,
        "note": R.NOT_EVIDENCE,
    }
    if view["status"] in _GRADED:
        payload["graded"] = {"coach_status": view["status"], "reading_side": R.reading_side(view["spec"], view["notes"])}
    return payload


def _get(event, table, now, today, genesis, presence, key_fn, deps) -> dict:
    _envelope, _error, logger = deps
    call_id = str(((event.get("queryStringParameters") or {}).get("call")) or "").strip()
    if not call_id:
        return _envelope(200, {"available": True})
    ip_hash, refusal = _identity(event, table, False, deps)
    if refusal:
        return refusal
    view, err = load_call(table, call_id, today, genesis=genesis, presence=presence)
    if err:
        return _error(*err)
    payload = _view_payload(view, _tally(table, call_id, view["spec"]))
    if view["open"]:
        key = key_fn(R.TOKEN_PURPOSE, logger)
        if key is None:
            return _error(503, UNAVAILABLE)
        payload["token"] = R.mint_token(key, call_id, ip_hash, now)
    return _envelope(200, payload)


def _ttl_for(due: str) -> int:
    end = datetime.strptime(str(due)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400
    return int(end) + R.DEDUP_GRACE_S


def _record(table, view: dict, ip_hash: str, choice: str, now: int, deps) -> dict:
    """Dedup FIRST (the decision), then the counter. See the module docstring for why and what each failure does."""
    _envelope, _error, logger = deps
    pk = R.PK_PREFIX + view["call_id"]
    try:
        table.put_item(
            Item={"pk": pk, "sk": R.TAP_SK_PREFIX + ip_hash, "tapped_at": int(now), "ttl": _ttl_for(view["due"])},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:  # noqa: BLE001
        if "ConditionalCheckFailedException" in str(e):
            return _error(409, "You have already made your call on this one.")
        logger.error(f"[reader_call] dedup write failed: {type(e).__name__}")
        return _error(503, UNAVAILABLE, recorded=False)
    try:
        table.update_item(
            Key={"pk": pk, "sk": R.TALLY_SK_PREFIX + choice},
            UpdateExpression="ADD #n :one",
            ExpressionAttributeNames={"#n": "count"},
            ExpressionAttributeValues={":one": 1},
        )
    except Exception as e:  # noqa: BLE001 — the marker stays; the tap is lost, never counted twice
        logger.error(f"[reader_call] tally write failed after the dedup marker: {type(e).__name__}")
        return _error(503, "Your call was not recorded.", recorded=False)
    return _envelope(
        200, {"recorded": True, "call": view["call_id"], "choice": choice, "tally": _tally(table, view["call_id"], view["spec"])}
    )


def _post(event, table, now, today, genesis, presence, key_fn, deps) -> dict:
    _envelope, _error, logger = deps
    ip_hash, refusal = _identity(event, table, True, deps)
    if refusal:
        return refusal
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:  # noqa: BLE001
        return _error(400, "Invalid JSON body")
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")
    if R.honeypot_filled(body):
        return _error(400, "Not recorded")
    call_id = body.get("call")
    if not isinstance(call_id, str) or not R.CALL_ID_RE.match(call_id):
        return _error(400, "call is required")
    key = key_fn(R.TOKEN_PURPOSE, logger)
    if key is None:
        return _error(503, UNAVAILABLE)
    why = R.check_token(key, body.get("token"), call_id, ip_hash, now)
    if why:
        logger.info(f"[reader_call] token refused: {why}")  # logged, never told to the caller
        return _error(403, "Please reload the page and try again.")
    view, err = load_call(table, call_id, today, genesis=genesis, presence=presence)
    if err:
        return _error(*err)
    if not view["open"]:
        return _error(409, "Readers' calls on this one are closed.")
    choice = body.get("choice")
    if not R.valid_choice(view["spec"], choice):
        return _error(400, "choice is not one of this call's choices")
    return _record(table, view, ip_hash, choice, now, deps)


def handle_reader_call(
    event: dict,
    *,
    table: Any = None,
    live: Optional[bool] = None,
    now: Optional[int] = None,
    today: Optional[str] = None,
    presence: Optional[Callable] = None,
    key_fn: Callable = salt_derived_key,
) -> dict:
    """GET /api/reader_call[?call=<id>] and POST /api/reader_call ``{call, choice, token, hp}`` — see the module docstring."""
    genesis, _envelope, _error, logger, default_table = _deps()
    if not (R.READER_CALL_LIVE if live is None else live):
        return _error(404, NOT_AVAILABLE)  # off: no read, no write, no meter
    table = default_table if table is None else table
    now = int(time.time()) if now is None else int(now)
    today = today or pacific_today()
    args = (event, table, now, today, genesis, presence or _presence, key_fn, (_envelope, _error, logger))
    return _post(*args) if _method(event) == "POST" else _get(*args)
