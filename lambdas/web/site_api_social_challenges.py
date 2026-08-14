"""lambdas/web/site_api_social_challenges.py — the challenge surface: the current/active read, the catalog, the vote/follow
doors, the daily check-in write door, and the #2238 note screen.

Split out of ``lambdas/web/site_api_social.py`` (#2515) — the facade keeps the
routed entrypoints as thin delegators and this module holds the bodies. Handlers
read the facade's shared + monkeypatched state through the ``_g`` hand-off
(``_g`` is a delegator's ``globals()``), so routes, response contracts and the
test monkeypatch surface are unchanged. This module does NOT import the facade,
so there is no import cycle.
"""


def handle_current_challenge(*, _g) -> dict:
    """
    GET /api/current_challenge
    Returns the current weekly challenge from S3 config.
    Manually updated each Monday via:
      aws s3 cp current_challenge.json s3://matthew-life-platform/site/config/current_challenge.json
    Cache: 3600s (1 hr) — changes once/week, no need for shorter TTL.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _ok = _g["_ok"]
    boto3 = _g["boto3"]
    json = _g["json"]
    logger = _g["logger"]
    os = _g["os"]
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    S3_REGION = os.environ.get("S3_REGION", "us-west-2")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/current_challenge.json")
        data = json.loads(resp["Body"].read())
        return _ok({"current_challenge": data}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[site_api] current_challenge S3 fetch failed: {e}")
        # No active challenge → return null so the banner simply doesn't render. The old
        # "Check back soon" placeholder leaked to the UI as a fake day-0-of-7 challenge.
        # 300s not 60s (#2289): this door is unmetered by design, so the empty state
        # must be edge-cacheable too — a new Monday challenge appears within 5 min.
        return _ok({"current_challenge": None}, cache_seconds=300)


def _public_challenge_ids(*, _g) -> set | None:
    """Catalog ids a visitor may legitimately vote on — public challenges only
    (excludes public:false vice entries). Returns None when the catalog can't be
    loaded so callers fail *closed* (503) rather than accepting arbitrary ids.
    Shares handle_challenge_catalog's module cache."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _catalog_cached = _g["_catalog_cached"]
    cat = _catalog_cached()
    if not cat or not cat.get("challenges"):
        return None
    return {
        (ch.get("id") or "").strip().lower() for ch in cat.get("challenges", []) if ch.get("public", True) is not False and ch.get("id")
    }


def _handle_challenge_vote(event: dict, *, _g) -> dict:
    """POST /api/challenge_vote — Rate-limited vote for challenge catalog entries.
    Body: {"catalog_id": "cold-shower-finish"}
    Rate limit: 1 vote per IP per challenge per 24 hours via DynamoDB TTL.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    # #2679: a well-formed non-object body (`"a-string"`, `[1,2]`, `7`) reached
    # `body.get` and raised out of the handler as a 502.
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")

    # #2679: type-guarded — `(body.get(k) or "").strip()` raised on any non-string
    # value. The default cap leaves the >80 check below as the thing that rejects a
    # long id, rather than truncating it into a valid one.
    catalog_id = _sanitise_text(body.get("catalog_id")).lower()
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required (max 80 chars)")

    # Reject votes for ids that aren't real public challenges — without this an
    # attacker can mint arbitrary VOTES#challenges/CH#<anything> rows.
    valid_ids = _public_challenge_ids(_g=_g)
    if valid_ids is None:
        return _error(503, "Challenge catalog unavailable — try again shortly")
    if catalog_id not in valid_ids:
        return _error(404, "Unknown challenge")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#CH#{catalog_id}"
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl_24h = now_epoch + 86400

    try:
        table.put_item(
            Item={
                "pk": rate_pk,
                "sk": rate_sk,
                "voted_at": now_epoch,
                "ttl": ttl_24h,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return _rate_limited("challenge_vote", "Already voted for this challenge in the last 24 hours")
        logger.error(f"[challenge_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#challenges"
    vote_sk = f"CH#{catalog_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET catalog_id = :cid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":cid": catalog_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[challenge_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return _envelope(200, {"catalog_id": catalog_id, "new_count": new_count})


def _handle_challenge_follow(event: dict, *, _g) -> dict:
    """POST /api/challenge_follow — Email follow for challenge catalog entries.
    Body: {"email": "user@example.com", "catalog_id": "cold-shower-finish"}
    Rate limit: 10 follows per IP per hour.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    FOLLOW_RATE_LIMIT = _g["FOLLOW_RATE_LIMIT"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    # #2679 — see _handle_challenge_vote.
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")

    email = _sanitise_text(body.get("email")).lower()
    catalog_id = _sanitise_text(body.get("catalog_id")).lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: FOLLOW_RATE_LIMIT follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"CHFOLLOW#{ip_hash}#{now_epoch // 3600}"
    try:
        result = table.update_item(
            Key={"pk": rate_pk, "sk": rate_sk},
            UpdateExpression="ADD follow_count :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":ttl": now_epoch + 7200,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("follow_count", 1))
        # `>` not `>=` (#2221): the counter is incremented BEFORE it is read, so the
        # first request already sees 1 and `>= FOLLOW_RATE_LIMIT` refused the TENTH
        # of the ten follows the docstring advertises.
        if count > FOLLOW_RATE_LIMIT:
            return _rate_limited("challenge_follow", "Too many follow requests. Try again later.")
    except Exception as e:
        logger.error(f"[challenge_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "CHALLENGE_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#CH#{catalog_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "catalog_id": catalog_id,
                "followed_at": now_epoch,
                "notified": False,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return _envelope(200, {"already_following": True, "catalog_id": catalog_id})
        logger.error(f"[challenge_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return _envelope(200, {"followed": True, "catalog_id": catalog_id})


def handle_challenge_catalog(*, _g) -> dict:
    """GET /api/challenge_catalog — Challenge catalog from S3 with vote counts.

    Returns the full catalog of challenges with metadata (icons, evidence,
    board recommenders, protocols) plus merged vote counts from DynamoDB.
    Dynamic status (active/completed/checkins) comes from /api/challenges.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    _catalog_cached = _g["_catalog_cached"]
    _decimal_to_float = _g["_decimal_to_float"]
    _ok = _g["_ok"]
    copy = _g["copy"]
    logger = _g["logger"]
    table = _g["table"]
    catalog = _catalog_cached()

    # Merge vote counts from DynamoDB
    vote_counts = {}
    try:
        vote_pk = "VOTES#challenges"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            cid = item.get("sk", "").replace("CH#", "")
            vote_counts[cid] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[challenge_catalog] Vote query failed (non-fatal): {e}")

    # Inject votes into each challenge (deep copy to avoid mutating the cache)
    result = copy.deepcopy(catalog)
    # Filter out private challenges (public: false)
    challenges = [ch for ch in result.get("challenges", []) if ch.get("public", True) is not False]
    total_votes = 0
    for ch in challenges:
        ch["votes"] = vote_counts.get(ch.get("id", ""), 0)
        total_votes += ch["votes"]
    result["challenges"] = challenges
    result["total_votes"] = total_votes

    return _ok(result, cache_seconds=900)


def _is_iso_date(value: str, *, _g) -> bool:
    """True only for a real YYYY-MM-DD calendar day ("2026-13-45" is not one)."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _ISO_DATE_RE = _g["_ISO_DATE_RE"]
    datetime = _g["datetime"]
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _sanitise_note(raw, *, _g) -> str:
    """The check-in note's slice of `_sanitise_text` — kept as its own name because
    `_screened_note` (the read-door re-screen) is written against it."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _sanitise_text = _g["_sanitise_text"]
    return _sanitise_text(raw)


def _screened_note(raw, *, _g) -> str:
    """A stored note, made safe to publish: HTML stripped, and emptied entirely if
    it carries blocked-vice vocabulary. Returns "" for anything withheld."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _is_blocked_vice = _g["_is_blocked_vice"]
    note = _sanitise_note(raw, _g=_g)
    if _is_blocked_vice(note):
        return ""
    return note


def _public_checkins(checkins, *, _g) -> list:
    """The read-side screen over a challenge's stored `daily_checkins` (#2238).

    Keeps the check-in day itself — that is Matthew's own progress data, and the
    completion arithmetic reads `completed`, never `note` — and withholds only the
    stranger-supplied text when it fails the screen.
    """
    out = []
    for entry in checkins or []:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        note = _screened_note(row.get("note"), _g=_g)
        if note:
            row["note"] = note
        else:
            row.pop("note", None)
        out.append(row)
    return out


def handle_challenges(*, _g) -> dict:
    """GET /api/challenges — live challenges overlaid on the full catalog.

    Live runs (USER#matthew#SOURCE#challenges, origin='live') are surfaced as
    "taken on / active". The challenge catalog (config/challenges_catalog.json,
    84 challenges) is always overlaid as origin='catalog' so the page shows the
    available + backlog pipeline even right after an experiment reset wipes the
    live partition. Blocked vices (the never-public categories) are filtered server-side.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    USER_ID = _g["USER_ID"]
    _decimal_to_float = _g["_decimal_to_float"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _load_s3_json = _g["_load_s3_json"]
    _ok = _g["_ok"]
    config_cache_valid = _g["config_cache_valid"]
    logger = _g["logger"]
    table = _g["table"]
    time = _g["time"]
    with_phase_filter = _g["with_phase_filter"]
    import re as _re

    live, live_ids = [], set()
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    try:
        resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot challenges
                    "KeyConditionExpression": Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
                    "ScanIndexForward": False,
                }
            )
        )
        for item in resp.get("Items", []):
            status = item.get("status", "candidate")
            # #2424: the deliberate public set — owner-activated statuses ONLY. LLM-authored 'candidate' rows
            # (challenge_generator, unreviewed) stay owner-side/MCP until Matthew activates; unknown stay private.
            if status not in ("active", "completed", "failed"):
                continue
            ch = _decimal_to_float(item)
            ch.pop("pk", None)
            sk_val = ch.pop("sk", "") or ""
            raw_id = sk_val.replace("CHALLENGE#", "")
            ch["challenge_id"] = raw_id
            ch["id"] = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", raw_id)
            # ER-06: check name AND id — a blocked keyword often lives only in the id; `name or id` missed it.
            if _is_blocked_vice(ch.get("name", "")) or _is_blocked_vice(ch.get("id", "")):
                continue
            # #2238: reader-supplied check-in notes publish with this row — screen them, incl. rows stored pre-#2238.
            if "daily_checkins" in ch:
                ch["daily_checkins"] = _public_checkins(ch.get("daily_checkins"), _g=_g)
            ch["origin"] = "live"
            if status == "active":
                checkins = ch.get("daily_checkins", [])
                duration = int(ch.get("duration_days", 7))
                completed_days = sum(1 for c in checkins if c.get("completed"))
                ch["progress"] = {
                    "checkin_days": len(checkins),
                    "completed_days": completed_days,
                    "duration_days": duration,
                    # #2221: clamped — the check-in door dedups on `date`, so extra rows
                    # really can exceed the duration and the progress bar ran past 100%.
                    "completion_pct": min(100, round(len(checkins) / duration * 100)) if duration else 0,
                    # ADR-104: a rate with an empty denominator is UNKNOWN, not 0%. Every
                    # challenge is in that state on its first day. `completed_days: 0`
                    # beside it is a genuine count and stays 0.
                    "success_rate": round(completed_days / len(checkins) * 100) if checkins else None,
                }
            live.append(ch)
            live_ids.add(ch["id"])
    except Exception as e:
        logger.warning(f"[challenges] DynamoDB query failed, catalog-only: {e}")

    # Overlay the catalog (always) — available + backlog the live partition lacks.
    catalog = []
    # The catalog cache lives on the FACADE (tests pin/patch social._challenges_cache),
    # so it is read AND written back through `_g` rather than a module-local `global`.
    if _g["_challenges_cache"] is None or not config_cache_valid(_g["_challenges_cache_at"]):
        _g["_challenges_cache"] = _load_s3_json("config/challenges_catalog.json", "challenges_catalog")
        _g["_challenges_cache_at"] = time.monotonic()
    for c in (_g["_challenges_cache"] or {}).get("challenges", []):
        if c.get("id") in live_ids:
            continue
        if _is_blocked_vice(c.get("name", "")) or _is_blocked_vice(c.get("id", "")):  # ER-06: check name AND id
            continue
        shelf = "available" if c.get("status") == "available" else "backlog"
        catalog.append(
            {
                "id": c.get("id"),
                "challenge_id": c.get("id"),
                "name": c.get("name", "Challenge"),
                "status": shelf,
                "origin": "catalog",
                "one_liner": c.get("one_liner", ""),
                "category": c.get("category", ""),
                "duration_days": c.get("duration_days"),
                "difficulty": c.get("difficulty"),
                "evidence_tier": c.get("evidence_tier"),
                "evidence_summary": c.get("evidence_summary", ""),
                "board_recommender": c.get("board_recommender", ""),
                "icon": c.get("icon", ""),
            }
        )
    catalog.sort(key=lambda x: (x["status"] != "available", (x.get("category") or ""), (x.get("name") or "").lower()))

    challenges = live + catalog
    summary = {
        "total": len(challenges),
        "active": sum(1 for c in live if c.get("status") == "active"),
        "available": sum(1 for c in catalog if c["status"] == "available"),
        "backlog": sum(1 for c in catalog if c["status"] == "backlog"),
        "completed": sum(1 for c in live if c.get("status") == "completed"),
    }
    return _ok({"challenges": challenges, "count": len(challenges), "summary": summary, "source": "catalog+live"}, cache_seconds=300)


def _handle_challenge_checkin(event: dict, *, _g) -> dict:
    """POST /api/challenge_checkin — Public check-in for active challenges.

    Body: {"challenge_id": "...", "completed": true/false, "note": "...", "date": "YYYY-MM-DD"}
    Uses localStorage on the client to prevent double-taps.
    Rate-limited: 1 check-in per IP per challenge per day (#358).
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    PT = _g["PT"]
    USER_ID = _g["USER_ID"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _ok = _g["_ok"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    # #2679 — see _handle_challenge_vote.
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")

    challenge_id = _sanitise_text(body.get("challenge_id"))
    completed = body.get("completed")
    # #2238: the note is free text from an anonymous stranger that ends up on the
    # public GET /api/challenges payload. HTML-strip it (sibling capture doors do
    # the same) and refuse blocked-vice vocabulary outright, as _handle_board_question does.
    note = _sanitise_note(body.get("note"), _g=_g)
    date_str = _sanitise_text(body.get("date"))

    if not challenge_id:
        return _error(400, "challenge_id required")
    if completed is None:
        return _error(400, "completed (true/false) required")
    if _is_blocked_vice(note):
        return _error(400, "That note can't be submitted.")
    # #2221: `date` was written verbatim into Matthew's own challenge row with no
    # format check and no length cap, and the dedup key IS that field — so every
    # bogus value minted a NEW check-in row (which is how completion_pct got past
    # 100). A supplied date must be a real ISO calendar day.
    if date_str and not _is_iso_date(date_str, _g=_g):
        return _error(400, "date must be YYYY-MM-DD")

    # Rate limit: 1 check-in per IP per challenge per day (#358). Applied
    # unconditionally via the module chokepoint (#2237) — never skipped.
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check(f"challenge_checkin:{challenge_id}", ip_hash, limit=1, window_seconds=86400)
    if not allowed:
        return _rate_limited("challenge_checkin", "Already checked in for this challenge today.", retry_after=86400)

    if not date_str:  # #2414: a check-in with no date lands on the reader's Pacific day
        date_str = datetime.now(PT).strftime("%Y-%m-%d")

    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    sk = f"CHALLENGE#{challenge_id}"

    # Verify challenge exists and is active
    try:
        item = table.get_item(Key={"pk": challenges_pk, "sk": sk}).get("Item")
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB get failed: {e}")
        return _error(500, "Database error")

    if not item:
        return _error(404, "Challenge not found")
    if item.get("status") != "active":
        return _error(400, f"Challenge is not active (status: {item.get('status')})")

    # Build checkin
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    checkin = {
        "date": date_str,
        "completed": bool(completed),
        "logged_at": now_iso,
        "source": "website",
    }
    if note:
        checkin["note"] = note

    # Idempotent write: replace any existing check-in for the same date instead
    # of blindly appending. A double-tap or a network retry must not create a
    # duplicate day — that would inflate completion_pct / success_rate. (Residual:
    # a truly simultaneous double-tap can still race this read-modify-write; the
    # common retry/double-tap case — writes seconds apart — is fully covered.)
    existing = item.get("daily_checkins", []) or []
    deduped = [c for c in existing if c.get("date") != date_str]
    deduped.append(checkin)
    try:
        table.update_item(
            Key={"pk": challenges_pk, "sk": sk},
            UpdateExpression="SET daily_checkins = :cl",
            ExpressionAttributeValues={":cl": deduped},
        )
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB update failed: {e}")
        return _error(500, "Failed to record check-in")

    total = len(deduped)
    duration = int(item.get("duration_days", 7) if item.get("duration_days") else 7)

    return _ok(
        {
            "checked_in": True,
            "challenge_id": challenge_id,
            "date": date_str,
            "completed": bool(completed),
            "total_checkins": total,
            "duration_days": duration,
            "completion_pct": min(100, round(total / duration * 100)) if duration else 0,
        },
        cache_seconds=0,
    )
