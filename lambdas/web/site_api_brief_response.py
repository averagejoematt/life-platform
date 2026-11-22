"""lambdas/web/site_api_brief_response.py — the Morning Brief's optional response door (#6175, owner ruling 2026-11-22 §2).

The trial brief's one recommendation carries one link: ``/api/brief_response?t=<opaque token>``.

  GET  — a confirmation PAGE and nothing else. It reads the token row and shows three buttons; it
         records nothing. A mail scanner or link previewer that fetches the link changes no state.
  POST — from that page's form only (t + response). The ONE write: a conditional update of the token
         row (exists, unused, unexpired) that records the answer and spends the token, then the same
         answer on the send's measurement row.

The token (``coach.brief_recommendations``): 256 random bits minted by the brief, the URL carries it
and nothing else (no recommendation text, id, date or address); the table holds only its SHA-256, so
neither the table nor a log line can mint a working link. Scope: one recommendation of one send, one
recipient (the row carries the recipient hash). Expiry: 48 hours. Single use: the conditional write.

Residual risk, stated (the PR says it too): anyone holding the link before it is spent or expires —
a forwarded email, a scanner that SUBMITS forms — can record one answer. Mitigations: nothing records
on a fetch; the page names no recommendation; one answer per link, then the link is dead; 48 h.

The page and the answer are private by construction: no recommendation text is rendered (only the
brief's day), responses are ``no-store`` + ``noindex`` + ``no-referrer``, and no public route reads
the partition. Rate-limited on both verbs by the shared DynamoDB limiter, FAIL CLOSED (a limiter outage refuses).
Its only writes outside the ``brief_trial`` partition are that limiter's own ``RATE#`` counters; a GET records
no answer and touches no trial row. An HTML door, not a JSON one — so it lives outside the ``site_api_social``
family (whose envelope contracts are JSON) the way ``site_api_reader_call`` does.
"""

from __future__ import annotations

import base64
import html as _html
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs

from coach import brief_recommendations as rr
from common.client_ip import extract_client_ip, salted_ip_hash
from common.pacific_time import day_in_words
from common.rate_limiter import check_rate_limit

RATE_LIMIT_PER_HOUR = 20  # both verbs share it; a GET reads one row, a POST spends one token

_PAGE_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store, private",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
}
_CSS = (
    "body{font-family:-apple-system,Segoe UI,sans-serif;background:#0b1220;color:#e2e8f0;max-width:520px;margin:40px auto;padding:0 20px}"
    "button{display:block;width:100%;margin:10px 0;padding:14px;font-size:16px;border-radius:8px;border:1px solid #475569;"
    "background:#1e293b;color:#f8fafc;cursor:pointer}p{line-height:1.5}.s{color:#94a3b8;font-size:13px}"
)


def _page(status: int, title: str, body: str) -> dict:
    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'
        + _html.escape(title)
        + "</title><style>"
        + _CSS
        + "</style></head><body><h1>"
        + _html.escape(title)
        + "</h1>"
        + body
        + "</body></html>"
    )
    return {"statusCode": status, "headers": dict(_PAGE_HEADERS), "body": doc}


def _gone(reason: str) -> dict:
    return _page(410 if reason != "invalid" else 404, "This link can't record an answer", "<p>" + _html.escape(_GONE[reason]) + "</p>")


_GONE = {
    "invalid": "This link is not valid. Nothing was recorded.",
    "expired": "This link has expired (links last 48 hours). Nothing was recorded. Tomorrow's brief carries a new one.",
    "used": "An answer was already recorded with this link. Nothing more was recorded.",
}


def _state(row: dict | None, now: int) -> str:
    if not row:
        return "invalid"
    if row.get("used_at"):
        return "used"
    try:
        if int(row.get("expires_at") or 0) <= now:
            return "expired"
    except (TypeError, ValueError):
        return "invalid"
    return "open"


def _read_token(table, token: str) -> dict | None:
    return table.get_item(Key={"pk": "USER#matthew#SOURCE#brief_trial", "sk": "TOKEN#" + rr.token_hash(token)}).get("Item")


def _confirm_page(token: str, row: dict) -> dict:
    buttons = "".join(
        '<form method="post" action="' + rr.RESPONSE_PATH + '">'
        '<input type="hidden" name="t" value="' + _html.escape(token) + '">'
        '<input type="hidden" name="response" value="' + key + '">'
        '<button type="submit">' + _html.escape(word) + "</button></form>"
        for key, word in rr.RESPONSE_WORDS.items()
    )
    when = day_in_words(str(row.get("send_day") or ""), weekday=True)
    return _page(
        200,
        "Your answer to the brief",
        "<p>The Morning Brief built from "
        + _html.escape(when)
        + "'s data asked you about one recommendation. What did you do with it?</p>"
        + buttons
        + '<p class="s">Opening this page recorded nothing. Only a button records an answer, once. '
        "If this email was forwarded to you, please close this page.</p>",
    )


def _deps():
    from web.site_api_common import logger, table

    return table, logger


def _meter(table, ip_hash: str) -> tuple:
    """FAIL CLOSED (#6088): a limiter error refuses rather than admits — on both verbs."""
    return check_rate_limit(
        table, endpoint="brief_response", ip_hash=ip_hash, limit=RATE_LIMIT_PER_HOUR, window_seconds=3600, fail_open=False
    )


def handle_brief_response(event: dict, *, table=None) -> dict:
    """GET -> confirmation page (no write). POST -> the one recorded answer."""
    default_table, logger = _deps()
    table = default_table if table is None else table
    method = ((event.get("requestContext", {}).get("http", {}) or {}).get("method") or event.get("httpMethod") or "GET").upper()
    ip_hash = salted_ip_hash(extract_client_ip(event), logger)
    if ip_hash is None:
        return _page(503, "Try again shortly", "<p>The answer page is unavailable. Nothing was recorded.</p>")
    allowed, _rem, retry = _meter(table, ip_hash)
    if not allowed:
        out = _page(429, "Too many requests", "<p>Too many requests from this network. Nothing was recorded. Try again later.</p>")
        out["headers"]["Retry-After"] = str(retry or 3600)
        return out

    if method != "POST":
        token = ((event.get("queryStringParameters") or {}).get("t") or "").strip()
        if not rr.token_valid_shape(token):
            return _gone("invalid")
        try:
            row = _read_token(table, token)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[brief_response] token read failed: {e}")
            return _page(503, "Try again shortly", "<p>The answer page is unavailable. Nothing was recorded.</p>")
        state = _state(row, int(time.time()))
        return _confirm_page(token, row) if state == "open" else _gone(state)

    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:  # noqa: BLE001
            return _gone("invalid")
    try:
        form = parse_qs(raw, max_num_fields=4)
    except ValueError:
        return _gone("invalid")
    token = (form.get("t") or [""])[0].strip()
    choice = (form.get("response") or [""])[0].strip()
    if not rr.token_valid_shape(token) or choice not in rr.RESPONSES:
        return _gone("invalid")
    now = int(time.time())
    now_iso = datetime.now(timezone.utc).isoformat()
    status = rr.RESPONSES[choice]
    try:
        upd = table.update_item(
            Key={"pk": "USER#matthew#SOURCE#brief_trial", "sk": "TOKEN#" + rr.token_hash(token)},
            UpdateExpression="SET used_at = :u, response = :r, response_status = :s",
            ConditionExpression="attribute_exists(sk) AND attribute_not_exists(used_at) AND expires_at > :now",
            ExpressionAttributeValues={":u": now_iso, ":r": choice, ":s": status, ":now": now},
            ReturnValues="ALL_NEW",
        )
    except Exception as e:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(e) or "ConditionalCheckFailed" in type(e).__name__:
            try:
                return _gone(_state(_read_token(table, token), now))
            except Exception:  # noqa: BLE001
                return _gone("invalid")
        logger.error(f"[brief_response] write failed: {e}")
        return _page(503, "Try again shortly", "<p>The answer could not be recorded. Nothing was recorded; the link still works.</p>")
    row = upd.get("Attributes") or {}
    # The send's measurement row carries the same answer (best effort — the token row is the record).
    try:
        if row.get("send_day"):
            table.update_item(
                Key={"pk": "USER#matthew#SOURCE#brief_trial", "sk": "SEND#" + str(row["send_day"])},
                UpdateExpression="SET response = :s, response_word = :r, response_at = :u, response_rec_id = :id",
                ConditionExpression="attribute_exists(sk)",
                ExpressionAttributeValues={":s": status, ":r": choice, ":u": now_iso, ":id": row.get("rec_id") or ""},
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[brief_response] send-row update failed (token row holds the answer): {e}")
    logger.info(f"[brief_response] recorded: send_day={row.get('send_day')} status={status}")
    return _page(200, "Recorded", "<p>Recorded: <strong>" + _html.escape(rr.RESPONSE_WORDS[choice]) + "</strong>. Thank you.</p>")
