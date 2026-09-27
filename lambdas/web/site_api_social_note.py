"""lambdas/web/site_api_social_note.py — the morning-note door (#4189): four words before the number.

An OWNER door, not a reader capture door. ``POST /api/morning_note`` stores the owner's
four words for one Pacific morning under his identity — the per-day owner token signed
with the ritual-link secret (``content.ritual_link.sign_morning_note_token``; site-api's
one owner check, per #4207's finding that nothing else here authenticates the owner).
``GET /api/morning_note`` serves the latest note per its stored privacy tier — Tier 1
(the owner's 2026-09-26 ruling): the words and the day.

Split from ``site_api_social_engage.py`` (#1665 line ceiling): the facade
(``site_api_social.py``) keeps the routed entrypoints as thin delegators and this module
holds the bodies, reading the facade's shared + monkeypatched state through the ``_g``
hand-off exactly as the engage module does. The read derivation lives in
``coach.morning_note`` so the GET, the coach packet and the coach input read ONE shape.

GUARD ORDER (every refusal before the write):
  1. salted ip_hash, fail-closed (503)      4. owner token for THAT day (403)
  2. rate limit, MORNING_NOTE_RATE_LIMIT/h  5. content gate, second arm: blocked-vice (400)
  3. JSON object; tool-call residue (#4190)  6. conditional put — a second note the same day is
     refused in its own words; the four           REFUSED (409) unless ``replace: true``
     fields + date validated RAW (400)
"""

from coach import morning_note as _mn
from common.text_guards import has_tool_call_residue

from web.site_api_social_engage import _salt_unavailable, _salted_ip_hash


def _handle_morning_note(event: dict, *, _g) -> dict:
    """POST /api/morning_note (#4189) — the owner's four words for today (Pacific).

    Body: {"sleep_word", "body_word", "mood_word": str (1-24 chars, letters/spaces/hyphens),
           "felt_recovered": bool, "token": <owner token for today>,
           "date": "YYYY-MM-DD" (optional; must be today PT), "replace": bool (optional)}
    """
    MORNING_NOTE_RATE_LIMIT = _g["MORNING_NOTE_RATE_LIMIT"]
    PT = _g["PT"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _get_ritual_token_secret = _g["_get_ritual_token_secret"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    from content.ritual_link import verify_morning_note_token

    # 1. Salted ip_hash, fail-closed (#3620) — the rate-limit identity.
    ip_hash = _salted_ip_hash(extract_client_ip(event), _g)
    if ip_hash is None:
        return _salt_unavailable(_g)

    # 2. Rate limit before any parsing work (and before the token check — a guess costs a slot).
    allowed, _remaining, _retry = _rate_check("morning_note", ip_hash, limit=MORNING_NOTE_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        return _rate_limited("morning_note", f"Rate limit reached. {MORNING_NOTE_RATE_LIMIT} per hour.", retry_after=3600)

    # 3. Parse; a well-formed non-object body is a 400, never a 5xx (#2679). Fields RAW.
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")
    if isinstance(body, dict) and any(has_tool_call_residue(body.get(f)) for f in _mn.WORD_FIELDS):
        # 3a. #4190's refusal FIRST, in its own words: the shape regex below would also refuse
        # the markup, but "1-24 characters" is not the reason, and the guard must be the guard.
        return _error(400, "tool-call residue in a word — retype it (#4190)")
    fields, reason = _mn.validate_note_body(body)
    if fields is None:
        return _error(400, reason or "invalid note")
    today_pt = datetime.now(PT).strftime("%Y-%m-%d")
    date_str = body.get("date", today_pt)
    if not isinstance(date_str, str) or date_str != today_pt:
        return _error(400, f"date must be today (Pacific): {today_pt}")
    replace = body.get("replace", False)
    if not isinstance(replace, bool):
        return _error(400, "replace must be true or false")

    # 4. The owner check: the per-day token signed with the ritual-link secret.
    try:
        secret = _get_ritual_token_secret()
    except RuntimeError:
        return _error(503, "Morning note temporarily unavailable")
    if not verify_morning_note_token(secret, date_str, body.get("token")):
        return _error(403, "Invalid or missing owner token")

    # 5. The content gate's second arm, BEFORE anything is stored: the four words are free text.
    words = " ".join(fields[f] for f in _mn.WORD_FIELDS)
    if _is_blocked_vice(words):
        return _error(400, "That note can't be stored.")

    # 6. One note per Pacific day: conditional put; `replace: true` is the owner's explicit overwrite (#4307).
    written_at = datetime.now(timezone.utc).isoformat()
    item = {
        # The pk literal lives INSIDE the put_item call on purpose (tests/test_site_partition_orphans.py
        # credits a site-api self-write only from pk-forms found within the write call itself);
        # `coach.morning_note.MORNING_NOTE_PK` is the read side's spelling and a test holds them equal.
        "pk": "USER#matthew#SOURCE#morning_note",
        "sk": _mn.sk_for(date_str),
        "date": date_str,
        **fields,
        "written_at": written_at,
        "tier": _mn.NOTE_TIER_PUBLIC,
        "source": _mn.SOURCE_LABEL,
    }
    if replace:
        item["replaced"] = True
    try:
        table.put_item(Item=item, **({} if replace else {"ConditionExpression": "attribute_not_exists(sk)"}))
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return _error(409, f"a note already exists for {date_str}; send replace: true to overwrite it", date=date_str)
        logger.error(f"[morning_note] write failed: {e}")
        return _error(503, "Unable to store the note. Try again later.")
    logger.info(f"[morning_note] {'Replaced' if replace else 'Stored'}: date={date_str}")
    return _envelope(200, {"ok": True, "date": date_str, "written_at": written_at, "replaced": replace, "note": _mn.public_view(item)})


def handle_morning_note_read(event: dict, *, _g) -> dict:
    """GET /api/morning_note[?days=N] (#4189) — the latest note, served per its tier.

    Tier 1: {state: "served", date, sleep_word, body_word, mood_word, felt_recovered, written_at}
    plus `notes` (newest first) when `days` is given; {state: "absent", reason: "no note yet"}
    when the window holds none; 503 when the read fails (never an empty week).
    """
    PT = _g["PT"]
    _error = _g["_error"]
    _ok = _g["_ok"]
    datetime = _g["datetime"]
    table = _g["table"]

    qs = event.get("queryStringParameters") or {}
    raw_days = qs.get("days")
    days = _mn.DEFAULT_LOOKBACK_DAYS
    if raw_days is not None:
        try:
            days = int(str(raw_days).strip())
        except (TypeError, ValueError):
            return _error(400, "days must be an integer")
        if not (1 <= days <= _mn.MAX_LOOKBACK_DAYS):
            return _error(400, f"days must be between 1 and {_mn.MAX_LOOKBACK_DAYS}")
    today_pt = datetime.now(PT).strftime("%Y-%m-%d")
    rows = _mn.read_notes(table, today_pt, days)
    if rows is None:
        return _error(503, "Morning note read unavailable")
    if not rows:
        return _ok({"state": "absent", "reason": "no note yet", "days_searched": days, "as_of": today_pt}, cache_seconds=60)
    latest = _mn.public_view(rows[0])
    payload = {**latest, "days_searched": days, "as_of": today_pt}
    if raw_days is not None:
        payload["notes"] = [_mn.public_view(r) for r in rows]
    return _ok(payload, cache_seconds=60)
