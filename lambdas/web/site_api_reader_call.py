"""site_api_reader_call.py — GET/POST /api/reader_call: a reader's own call beside a coach's open call (#6088, #6114).

Owner rulings 2026-11-16 (ADR-169 binds the isolation): "Can an ordinary reader predict the outcome as well as the AI
coaches?" — shown as audience participation beside the formal coach and baseline records, never as equivalent evidence.
Two switches, both must say open: the committed ``reader_call_rules.READER_CALL_LIVE`` (off) AND the runtime kill
switch, SSM ``/life-platform/reader-call`` = ``on`` (read with a 60-second cache, FAIL CLOSED: missing, unreadable or
any other value shuts the door). A shut door answers 404 "not available" before it parses, meters, reads or writes.

ELIGIBLE CALLS. Public (read through the governed ``PublicationTable``, so a private call reads as absent), counted in
this cycle, built by the ledger's own ``export_item`` and kept by its journal-silence scrub, a direction or number call,
not sealed, not retired, not under an owner grading hold or classification review, with a measure that has reader words
(``prediction_reason.METRIC_WORDS``). The call's WORDS need not be published: the question is stated only from fields
its own page already prints for a words-withheld call (``reader_call_rules.question``). The coach's direction is not
repeated by this route before the call is graded.

THE LOCK. Taps are accepted only while the call is OPEN: pending, no outcome field on the row, and before the close day
(the earlier of the due day and the day the outcome can first be read). A late, replayed or post-outcome request moves
no counter. Before the close day no response carries a count or a split — only the reader's own recorded call and the
day the reader calls open. Once closed, the counts of reader calls are served; once graded, beside the coach's call.

WHAT IS STORED (all under ``READERCALL#<public item id>``): ``TAP#<salted identity>`` — the dedup marker carrying the
reader's own choice and a TTL (no address, no text); ``TALLY#<choice>`` — a counter moved only by an atomic ``ADD``.
Dedup first, then the counter: a failed ADD loses one tap (an under-count), never counts twice.

ABUSE CONTROLS, in order: both switches; a body cap and the JSON content type; the identity's salt (fail closed); a
per-identity meter charged before other work and FAIL CLOSED; strict body keys; the honeypot; the timing token; the
eligibility and lock checks; the closed choice set; the dedup marker. Every accepted call and every refusal (with its
reason as a log property) is an EMF line, so a spike is alarmable (``reader-call-accepted-spike``) and the reasons are
queryable in Logs Insights. A distributed botnet holding many networks is the edge rate rule's job (#6114's first box).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from boto3.dynamodb.conditions import Key
from coach import coach_record, prediction_windows
from common.client_ip import extract_client_ip, salt_derived_key, salted_ip_hash
from common.metric_namespaces import SITE_API_METRIC_NAMESPACE
from common.pacific_time import pacific_today
from common.rate_limiter import check_rate_limit

from web import reader_call_rules as R

READ_LIMIT_PER_HOUR = 120
TAP_LIMIT_PER_HOUR = 30
MAX_BODY_BYTES = 2048
BODY_KEYS = frozenset({"call", "choice", "token", "hp"})
NOT_AVAILABLE = "Reader calls are not available."
NOT_OPEN = "This call is not open for reader calls."
CLOSED = "Reader calls on this one are closed."
UNAVAILABLE = "Reader calls are unavailable right now. Please try again shortly."
_GRADED = ("confirmed", "refuted")

#: The runtime kill switch (#6114): `aws ssm put-parameter --name /life-platform/reader-call --value off --type String
#: --overwrite` shuts the door within SWITCH_CACHE_S without a deploy. Only the literal "on" opens it.
SWITCH_PARAM = "/life-platform/reader-call"
SWITCH_CACHE_S = 60
_SWITCH: dict = {"at": 0.0, "on": False}
_SWITCH_LOCK = threading.Lock()
_ssm_client: list = []


def _ssm():
    if not _ssm_client:
        import boto3

        _ssm_client.append(boto3.client("ssm", region_name="us-west-2"))
    return _ssm_client[0]


def runtime_switch_on(*, get_parameter: Optional[Callable] = None, now: Optional[float] = None) -> bool:
    """True only when SSM `/life-platform/reader-call` reads exactly ``on``. Missing, unreadable, empty or any other
    value is OFF (fail closed). Cached for SWITCH_CACHE_S, so a flip takes effect within a minute without a deploy."""
    t = time.monotonic() if now is None else now
    with _SWITCH_LOCK:
        if _SWITCH["at"] and t - _SWITCH["at"] < SWITCH_CACHE_S:
            return _SWITCH["on"]
    try:
        get = get_parameter or _ssm().get_parameter
        value = str(((get(Name=SWITCH_PARAM) or {}).get("Parameter") or {}).get("Value") or "")
        on = value.strip() == "on"
    except Exception as e:  # noqa: BLE001 — an unreadable switch is a shut door
        print(f"[reader_call] kill switch unreadable ({type(e).__name__}) — door SHUT", file=sys.stderr)
        on = False
    with _SWITCH_LOCK:
        _SWITCH.update(at=t, on=on)
    return on


def emit(event_name: str, reason: Optional[str] = None) -> None:
    """One EMF line: ``ReaderCallAccepted`` or ``ReaderCallRefused`` (dimensionless — two billed streams in all), with
    the refusal ``Reason`` as a plain property (queryable in Logs Insights, never a per-reason billed metric)."""
    name = "ReaderCallAccepted" if event_name == "accepted" else "ReaderCallRefused"
    line = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {"Namespace": SITE_API_METRIC_NAMESPACE, "Dimensions": [[]], "Metrics": [{"Name": name, "Unit": "Count"}]}
            ],
        },
        name: 1,
        "ReaderCallEvent": event_name,
    }
    if reason:
        line["Reason"] = reason
    try:
        sys.stdout.write(json.dumps(line) + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 — telemetry never breaks the door
        pass


def _method(event: dict) -> str:
    http = (event.get("requestContext") or {}).get("http") or {}
    return str(http.get("method") or event.get("httpMethod") or "GET").upper()


def _deps():
    from web.site_api_common import EXPERIMENT_START, _envelope, _error, logger, table

    return EXPERIMENT_START, _envelope, _error, logger, table


def _short_and_pid(item_id: str) -> Optional[tuple]:
    from web.site_api_coach_ledger import _CALIB_COACH_NAMES

    if not isinstance(item_id, str) or not R.ITEM_ID_RE.match(item_id):
        return None
    short, pid = item_id.split(":", 1)
    return (short, pid) if short in _CALIB_COACH_NAMES else None


def _presence(table: Any) -> list:
    from web.site_api_coach_ledger import _instrument_presence_safe

    return _instrument_presence_safe(_g={"table": table}) or []


def load_call(table: Any, item_id: str, today: str, *, genesis: Optional[str], presence: Callable = _presence) -> tuple:
    """``(view, None)`` for an eligible call, else ``(None, (status, message, reason))``. See the module docstring."""
    from web.prediction_reason import _notes, metric_unit, metric_words
    from web.site_api_ledger_export import export_item, servable

    sp = _short_and_pid(item_id)
    if sp is None:
        return None, (404, "Unknown call", "unknown_call")
    short, pid = sp
    row = (table.get_item(Key={"pk": f"COACH#{short}_coach", "sk": f"PREDICTION#{pid}"}) or {}).get("Item")
    if not isinstance(row, dict) or coach_record.prediction_key(row) != pid or row.get("coach_id") == "":
        return None, (404, "Unknown call", "unknown_call")
    if not coach_record.counts_this_cycle(row, genesis):
        return None, (404, "Unknown call", "unknown_call")
    item = export_item(short, row, presence(table))
    kept, _ = servable([item])
    if not kept or item.get("item_id") != item_id:
        return None, (404, "Unknown call", "unknown_call")
    ev = row.get("evaluation")
    spec: dict = ev if isinstance(ev, dict) else {}
    kind = R.call_kind(spec)
    measure = metric_words(spec.get("metric"))
    if (
        kind is None
        or item.get("kind") != kind
        or not measure
        or item.get("sealed")
        or item.get("retired")
        or item.get("grading_held")
        or item.get("classification_review")
    ):
        return None, (409, NOT_OPEN, "not_eligible")
    eff = prediction_windows.effective_window_days(spec, row.get("subdomain", ""))
    made = item.get("logged_date")
    close = R.closes_on(spec, made, eff, item.get("due_date"))
    unit = metric_unit(spec.get("metric"))
    q = R.question(spec, measure, made, eff, unit)
    if not q or not close:
        return None, (409, NOT_OPEN, "not_eligible")
    status = item.get("status")
    view = {
        "item_id": item_id,
        "spec": spec,
        "kind": kind,
        "status": status,
        "question": q,
        "unit": unit,
        "due": item.get("due_date"),
        "closes_on": close,
        "open": R.is_open(row, status, close, today),
        "graded": status in _GRADED,
        "notes": _notes(row.get("outcome_notes")),
    }
    return view, None


def _tally(table: Any, item_id: str, spec: dict) -> Optional[dict]:
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(R.PK_PREFIX + item_id) & Key("sk").begins_with(R.TALLY_SK_PREFIX))
    except Exception:  # noqa: BLE001 — an unread count is said, never shown as zero
        return None
    return R.reader_calls_of(resp.get("Items"), spec)


def _your_call(table: Any, item_id: str, ip_hash: str) -> Optional[str]:
    try:
        item = (table.get_item(Key={"pk": R.PK_PREFIX + item_id, "sk": R.TAP_SK_PREFIX + ip_hash}) or {}).get("Item") or {}
    except Exception:  # noqa: BLE001
        return None
    choice = item.get("choice")
    return choice if isinstance(choice, str) else None


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


def _refuse(deps, status: int, message: str, reason: str, **extra) -> dict:
    _envelope, _error, _logger = deps
    emit("refused", reason)
    if status == 429:
        return _envelope(429, {"error": message}, retry_after=extra.get("retry_after") or 60)
    return _error(status, message)


def _identity(event: dict, table: Any, tap: bool, deps) -> tuple:
    """``(ip_hash, None)`` or ``(None, refusal)`` — the salted identity, then the meter (charged first, FAIL CLOSED)."""
    _envelope, _error, logger = deps
    ip_hash = salted_ip_hash(extract_client_ip(event), logger)
    if ip_hash is None:
        return None, _refuse(deps, 503, UNAVAILABLE, "salt")
    allowed, _rem, retry = _meter(table, ip_hash, tap)
    if not allowed:
        return None, _refuse(deps, 429, "Too many requests from this network. Try again later.", "rate", retry_after=retry)
    return ip_hash, None


def view_payload(view: dict, reader_calls: Optional[dict], your_call: Optional[str]) -> dict:
    """What a reader may see. Before the close day: the question, the choices, the reader's own call and the day the
    reader calls open — NO count and NO split (so an early majority cannot steer later calls). Closed: the counts of
    reader calls. Graded: the coach's call and the side the reading came down on, beside them."""
    payload = {
        "available": True,
        "call": view["item_id"],
        "kind": view["kind"],
        "question": view["question"],
        "choices": R.choices(view["spec"], view["unit"]),
        "open": view["open"],
        "closes_on": view["closes_on"],
        "closes_on_words": R.day_words(view["closes_on"]),
        "result_due": view["due"],
        "result_due_words": R.day_words(view["due"]),
        "your_call": your_call,
        "copy": R.COPY,
        "note": R.NOT_EVIDENCE,
    }
    if not view["open"]:
        payload["reader_calls"] = reader_calls
        if view["graded"]:
            payload["graded"] = {
                "coach_status": view["status"],
                "coach_choice": R.coach_choice(view["spec"]),
                "reading_side": R.reading_side(view["spec"], view["notes"]),
            }
    return payload


def _get(event, table, now, today, genesis, presence, key_fn, deps) -> dict:
    _envelope, _error, logger = deps
    item_id = str(((event.get("queryStringParameters") or {}).get("call")) or "").strip()
    if not item_id:
        return _envelope(200, {"available": True})
    ip_hash, refusal = _identity(event, table, False, deps)
    if refusal:
        return refusal
    view, err = load_call(table, item_id, today, genesis=genesis, presence=presence)
    if err:
        return _refuse(deps, *err)
    mine = _your_call(table, item_id, ip_hash)
    payload = view_payload(view, None if view["open"] else _tally(table, item_id, view["spec"]), mine)
    if view["open"] and mine is None:
        key = key_fn(R.TOKEN_PURPOSE, logger)
        if key is None:
            return _refuse(deps, 503, UNAVAILABLE, "salt")
        payload["token"] = R.mint_token(key, item_id, ip_hash, now)
    return _envelope(200, payload)


def _ttl_for(due: str) -> int:
    end = datetime.strptime(str(due)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400
    return int(end) + R.DEDUP_GRACE_S


def _record(table, view: dict, ip_hash: str, choice: str, now: int, deps) -> dict:
    """Dedup FIRST (the decision, carrying the reader's own choice), then the counter."""
    _envelope, _error, logger = deps
    pk = R.PK_PREFIX + view["item_id"]
    try:
        table.put_item(
            Item={"pk": pk, "sk": R.TAP_SK_PREFIX + ip_hash, "choice": choice, "tapped_at": int(now), "ttl": _ttl_for(view["due"])},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:  # noqa: BLE001
        if "ConditionalCheckFailedException" in str(e):
            return _refuse(deps, 409, "You have already made your call on this one.", "duplicate")
        logger.error(f"[reader_call] dedup write failed: {type(e).__name__}")
        emit("refused", "write_failed")
        return _error(503, UNAVAILABLE, recorded=False)
    try:
        table.update_item(
            Key={"pk": pk, "sk": R.TALLY_SK_PREFIX + choice},
            UpdateExpression="ADD #n :one",
            ExpressionAttributeNames={"#n": "count"},
            ExpressionAttributeValues={":one": 1},
        )
    except Exception as e:  # noqa: BLE001 — the marker stays; the tap is lost, never counted twice
        logger.error(f"[reader_call] count write failed after the dedup marker: {type(e).__name__}")
        emit("refused", "write_failed")
        return _error(503, "Your call was not recorded.", recorded=False)
    emit("accepted")
    return _envelope(
        200,
        {
            "recorded": True,
            "call": view["item_id"],
            "your_call": choice,
            "closes_on": view["closes_on"],
            "closes_on_words": R.day_words(view["closes_on"]),
            "result_due_words": R.day_words(view["due"]),
        },
    )


def _parse(event: dict, deps) -> tuple:
    """``(body, None)`` or ``(None, refusal)``: size cap, JSON content type, a JSON object, only the four known keys."""
    raw = event.get("body") or ""
    if len(raw.encode("utf-8", errors="replace") if isinstance(raw, str) else bytes(raw)) > MAX_BODY_BYTES:
        return None, _refuse(deps, 413, "Request too large", "bad_request")
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    if not headers.get("content-type", "").lower().startswith("application/json"):
        return None, _refuse(deps, 415, "Content-Type must be application/json", "bad_request")
    try:
        body = json.loads(raw or "{}")
    except Exception:  # noqa: BLE001
        return None, _refuse(deps, 400, "Invalid JSON body", "bad_request")
    if not isinstance(body, dict) or not set(body) <= BODY_KEYS:
        return None, _refuse(deps, 400, "Body must be a JSON object with call, choice, token and hp only", "bad_request")
    return body, None


def _post(event, table, now, today, genesis, presence, key_fn, deps) -> dict:
    _envelope, _error, logger = deps
    body, refusal = _parse(event, deps)
    if refusal:
        return refusal
    ip_hash, refusal = _identity(event, table, True, deps)
    if refusal:
        return refusal
    if R.honeypot_filled(body):
        return _refuse(deps, 400, "Not recorded", "honeypot")
    item_id = body.get("call")
    if not isinstance(item_id, str) or not R.ITEM_ID_RE.match(item_id):
        return _refuse(deps, 400, "call is required", "bad_request")
    key = key_fn(R.TOKEN_PURPOSE, logger)
    if key is None:
        return _refuse(deps, 503, UNAVAILABLE, "salt")
    why = R.check_token(key, body.get("token"), item_id, ip_hash, now)
    if why:
        logger.info(f"[reader_call] token refused: {why}")  # logged, never told to the caller
        return _refuse(deps, 403, "Please reload the page and try again.", f"token_{why}")
    view, err = load_call(table, item_id, today, genesis=genesis, presence=presence)
    if err:
        return _refuse(deps, *err)
    if not view["open"]:
        return _refuse(deps, 409, CLOSED, "closed")
    choice = body.get("choice")
    if not R.valid_choice(view["spec"], choice):
        return _refuse(deps, 400, "choice is not one of this call's choices", "bad_choice")
    return _record(table, view, ip_hash, choice, now, deps)


def handle_reader_call(
    event: dict,
    *,
    table: Any = None,
    live: Optional[bool] = None,
    runtime: Optional[Callable[[], bool]] = None,
    now: Optional[int] = None,
    today: Optional[str] = None,
    presence: Optional[Callable] = None,
    key_fn: Callable = salt_derived_key,
) -> dict:
    """GET /api/reader_call[?call=<item id>] and POST /api/reader_call ``{call, choice, token, hp}``."""
    genesis, _envelope, _error, logger, default_table = _deps()
    committed = R.READER_CALL_LIVE if live is None else live
    if not committed or not (runtime or runtime_switch_on)():
        return _error(404, NOT_AVAILABLE)  # shut: no parse, no meter, no read, no write
    table = default_table if table is None else table
    now = int(time.time()) if now is None else int(now)
    today = today or pacific_today()
    args = (event, table, now, today, genesis, presence or _presence, key_fn, (_envelope, _error, logger))
    return _post(*args) if _method(event) == "POST" else _get(*args)
