"""lambdas/web/site_api_social_engage.py — the reader-engagement doors: subscriber verification/count, the nudge and
finding capture doors, the #769 evening-ritual one-tap write, predict-the-week,
and the board question door.

Split out of ``lambdas/web/site_api_social.py`` (#2515) — the facade keeps the
routed entrypoints as thin delegators and this module holds the bodies. Handlers
read the facade's shared + monkeypatched state through the ``_g`` hand-off
(``_g`` is a delegator's ``globals()``), so routes, response contracts and the
test monkeypatch surface are unchanged. This module does NOT import the facade,
so there is no import cycle.
"""


def _handle_verify_subscriber(event: dict, *, _g) -> dict:
    """
    GET /api/verify_subscriber?email=...
    Returns a 24hr token if the email is a confirmed subscriber.
    Frontend stores token in sessionStorage and sends as X-Subscriber-Token header
    to unlock 20 questions/hr instead of the default 5.

    #2239 — this door is a MEMBERSHIP ORACLE over the subscriber roster, and that
    is accepted, not overlooked. Recorded here so it is not "fixed" cosmetically
    later:

      * The endpoint's entire purpose is to hand back a credential IF AND ONLY IF
        the caller-supplied address is on the confirmed list. Any response that
        carries the token is therefore a perfect oracle regardless of its status
        code — uniforming 200/404 would only move the signal from `resp.status` to
        `"token" in body`, which the sole client already branches on. That is
        obfuscation, not a fix, and it would leave the leak while retiring the
        test that names it.
      * The only way to actually close it is to stop answering synchronously —
        mail the token to the address instead, so issuance requires proof of
        control. That is a product change (a new email door + a claim flow), out
        of scope here; see the PR for #2239.
      * So the mitigation is COST: the oracle is metered per IP, and both answers
        are metered by the SAME counter, before either reaches DynamoDB. Probing
        the roster is no longer free or unbounded.

    The limiter is deliberately fail-CLOSED: when DynamoDB is unreachable
    `_is_confirmed_subscriber` already returns False and the door answers 404 for
    everyone, so there is no legitimate flow to protect during an outage — only an
    unmetered enumeration window to close.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    VERIFY_SUBSCRIBER_RATE_LIMIT = _g["VERIFY_SUBSCRIBER_RATE_LIMIT"]
    VERIFY_SUBSCRIBER_RATE_WINDOW = _g["VERIFY_SUBSCRIBER_RATE_WINDOW"]
    _envelope = _g["_envelope"]
    _generate_subscriber_token = _g["_generate_subscriber_token"]
    _is_confirmed_subscriber = _g["_is_confirmed_subscriber"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    params = event.get("queryStringParameters") or {}
    email = (params.get("email") or "").strip().lower()

    if not email or "@" not in email or len(email) > 254:
        # Rejected BEFORE the rate check on purpose: a malformed address costs no
        # DynamoDB operation (not even the limiter's UpdateItem) and can answer no
        # membership question, so metering it would only spend writes on garbage.
        return _envelope(400, {"error": "Valid email required"})

    # Metered through the module chokepoint (#2237) like every other public door.
    # Keyed on the IP alone — NOT on the address — or each new probe address would
    # get its own fresh budget and enumeration would stay free.
    ip_hash = hashlib.sha256(extract_client_ip(event).encode()).hexdigest()[:16]
    allowed, _rem, retry_after = _rate_check(
        "verify_subscriber",
        ip_hash,
        limit=VERIFY_SUBSCRIBER_RATE_LIMIT,
        window_seconds=VERIFY_SUBSCRIBER_RATE_WINDOW,
        fail_open=False,
    )
    if not allowed:
        return _rate_limited(
            "verify_subscriber",
            "Too many verification attempts. Try again in a little while.",
            retry_after=retry_after or VERIFY_SUBSCRIBER_RATE_WINDOW,
        )

    if not _is_confirmed_subscriber(email):
        return _envelope(404, {"error": "Email not found. Subscribe at /subscribe/ to unlock more questions!"})

    token = _generate_subscriber_token(email)
    return _envelope(200, {"token": token, "message": "Verified! You now have 20 questions per hour.", "limit": 20})


def handle_subscriber_count(*, _g) -> dict:
    """
    GET /api/subscriber_count
    Returns count of confirmed subscribers (read-only query).
    Used by homepage and subscribe page for social proof.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    USER_ID = _g["USER_ID"]
    _ok = _g["_ok"]
    logger = _g["logger"]
    table = _g["table"]
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#subscribers"),
            Select="COUNT",
            FilterExpression="attribute_exists(#s) AND #s = :confirmed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":confirmed": "confirmed"},
        )
        count = resp.get("Count", 0)
    except Exception as e:
        # ADR-104 / #2221: a DDB blip used to publish `count: 0`, which the homepage
        # and /subscribe/ render as the FACT that nobody has subscribed. Absence is
        # None; both consumers already branch on `d.count != null`.
        logger.warning(f"[subscriber_count] DDB query failed: {e}")
        count = None
    return _ok({"count": count, "available": count is not None}, cache_seconds=600)


def _handle_nudge(event: dict, *, _g) -> dict:
    """
    POST /api/nudge
    Body: {"category": "back_on_it" | "watching" | "take_your_time" | "you_got_this"}
    Rate limit: 1 nudge per category per IP per hour — DynamoDB-backed (survives
    cold starts / warm-container spread; in-memory fallback only).
    NOTE: the per-category display *counts* are still approximate/in-memory — a
    durable counts schema remains future work, separate from this rate limit.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    NUDGE_CATEGORIES = _g["NUDGE_CATEGORIES"]
    NUDGE_LABELS = _g["NUDGE_LABELS"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _nudge_counts = _g["_nudge_counts"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    source_ip = extract_client_ip(event)
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    category = (body.get("category") or "").strip().lower()
    if category not in NUDGE_CATEGORIES:
        return _error(400, f"Invalid category. Must be one of: {sorted(NUDGE_CATEGORIES)}")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    # Rate limit: 1 per IP per category per hour. Per-category endpoint key so a
    # nudge in one category doesn't consume another's budget.
    allowed, _rem, _retry = _rate_check(f"nudge:{category}", ip_hash, limit=1, window_seconds=3600)
    if not allowed:
        return _rate_limited("nudge", "Already sent this reaction recently. Come back later.", retry_after=3600, category=category)

    # Increment in-memory count
    _nudge_counts[category] = _nudge_counts.get(category, 0) + 1
    logger.info(f"[nudge] category={category} ip_hash={ip_hash} total_this_session={_nudge_counts[category]}")

    return _envelope(
        200,
        {
            "success": True,
            "category": category,
            "label": NUDGE_LABELS[category],
            "message": "Reaction sent. Matthew will see this in his daily brief.",
        },
    )


def _handle_submit_finding(event: dict, *, _g) -> dict:
    """
    POST /api/submit_finding
    Body: {"metric_a": str, "metric_b": str, "finding": str, "email": str (optional)}
    Stores visitor-discovered correlation findings in S3 for Matthew's review.
    Rate limit: 3 per IP per hour.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    FINDING_RATE_LIMIT = _g["FINDING_RATE_LIMIT"]
    S3_REGION = _g["S3_REGION"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    boto3 = _g["boto3"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    os = _g["os"]
    re = _g["re"]
    timezone = _g["timezone"]
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    # Rate limit: FINDING_RATE_LIMIT per IP per hour — DynamoDB-backed (survives
    # cold starts; bounded in-memory fallback only, #2237).
    allowed, remaining, _retry = _rate_check("submit_finding", ip_hash, limit=FINDING_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        return _rate_limited("submit_finding", f"Rate limit reached. {FINDING_RATE_LIMIT} submissions per hour.", retry_after=3600)

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")

    metric_a = re.sub(r"<[^>]+>", "", (body.get("metric_a") or "").strip())[:100]
    metric_b = re.sub(r"<[^>]+>", "", (body.get("metric_b") or "").strip())[:100]
    finding = re.sub(r"<[^>]+>", "", (body.get("finding") or "").strip())[:500]
    email = re.sub(r"<[^>]+>", "", (body.get("email") or "").strip())[:254]

    if not metric_a or not metric_b:
        return _error(400, "Both metric_a and metric_b are required.")
    if not finding or len(finding) < 10:
        return _error(400, "Finding description must be at least 10 characters.")
    if email and "@" not in email:
        return _error(400, "Invalid email format.")
    # #2221: the sibling capture door (_handle_board_question) screens blocked-vice
    # text AT THE DOOR; this one — same shape, same S3 moderation queue, same public
    # POST — screened nothing. Both metric names are screened too: the finding is
    # rendered next to them.
    if _is_blocked_vice(finding) or _is_blocked_vice(metric_a) or _is_blocked_vice(metric_b):
        return _error(400, "That finding can't be submitted.")

    # Build finding record
    timestamp = datetime.now(timezone.utc).isoformat()
    # Content-based id (no timestamp): a same-day network retry of the identical
    # submission overwrites the same S3 object instead of creating a duplicate
    # pending finding for Matt to triage.
    finding_id = hashlib.sha256(f"{ip_hash}:{metric_a}:{metric_b}:{finding}".encode()).hexdigest()[:12]
    record = {
        "id": finding_id,
        "metric_a": metric_a,
        "metric_b": metric_b,
        "finding": finding,
        "email": email if email else None,
        "submitted_at": timestamp,
        "ip_hash": ip_hash,
        "status": "pending",
    }

    # Write to S3
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    s3_key = f"generated/findings/{timestamp[:10]}_{finding_id}.json"  # same instant as submitted_at (UTC key prefix, not reader-facing)
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(record, indent=2),
            ContentType="application/json",
        )
        logger.info(f"[submit_finding] Stored: {s3_key} metric_a={metric_a} metric_b={metric_b}")
    except Exception as e:
        logger.error(f"[submit_finding] S3 write failed: {e}")
        return _error(503, "Unable to store finding. Try again later.")

    return _envelope(
        200,
        {
            "success": True,
            "finding_id": finding_id,
            "message": "Finding submitted! Matthew will review it and may promote it to a Discovery or seed an Experiment.",
            "remaining": remaining,
        },
    )


def _handle_ritual_log(event: dict, *, _g) -> dict:
    """GET /api/ritual_log — one-tap write for the evening ritual (#769, ADR-124).

    Query params: date=YYYY-MM-DD, metric=connection|mood_valence, value=0-4, token=<hex32>.
    The token is an HMAC-SHA256 over (date, metric, value) minted by evening_nudge_lambda
    with the dedicated ritual-token secret (lambdas/ritual_link.py) — forging a different
    value for the same link requires the secret, matching the chronicle-approve /
    subscriber-token precedent (signed link, no separate auth scheme).

    Idempotency: last-tap-wins. A second tap (retry, or Matthew changing his mind from the
    same email) overwrites the metric + its logged_at — no read-modify-write, no dedup list,
    just a plain SET on the day's record. Two independent metrics on the same day are two
    independent SETs, so tapping connection doesn't disturb an already-logged mood_valence.

    Rate limit: RITUAL_LOG_RATE_LIMIT per IP per hour (DynamoDB-backed, matches nudge/checkin).
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Decimal = _g["Decimal"]
    PT = _g["PT"]
    RITUAL_LOG_RATE_LIMIT = _g["RITUAL_LOG_RATE_LIMIT"]
    USER_PREFIX = _g["USER_PREFIX"]
    _error = _g["_error"]
    _get_ritual_token_secret = _g["_get_ritual_token_secret"]
    _ok = _g["_ok"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    from content.ritual_link import RITUAL_METRICS, RITUAL_VALUE_MAX, RITUAL_VALUE_MIN, verify_ritual_token

    qs = event.get("queryStringParameters") or {}
    date_str = (qs.get("date") or "").strip()
    metric = (qs.get("metric") or "").strip().lower()
    value_raw = (qs.get("value") or "").strip()
    token = (qs.get("token") or "").strip()

    if metric not in RITUAL_METRICS:
        return _error(400, f"metric must be one of: {sorted(RITUAL_METRICS)}")

    try:
        value = int(value_raw)
    except (TypeError, ValueError):
        return _error(400, "value must be an integer")
    if not (RITUAL_VALUE_MIN <= value <= RITUAL_VALUE_MAX):
        return _error(400, f"value must be between {RITUAL_VALUE_MIN} and {RITUAL_VALUE_MAX}")

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return _error(400, "date must be YYYY-MM-DD")

    # Defense in depth beyond the signature: a link is only ever minted for "today"
    # (Pacific), so bound how stale a tap can be — a week of headroom covers an
    # unread nudge email without leaving the window open indefinitely.
    today_pt = datetime.now(PT).date()
    if date_obj > today_pt or (today_pt - date_obj).days > 7:
        return _error(400, "date outside the allowed window")

    try:
        secret = _get_ritual_token_secret()
    except RuntimeError:
        return _error(503, "Ritual logging temporarily unavailable")

    if not verify_ritual_token(secret, date_str, metric, value, token):
        return _error(403, "Invalid or tampered link")

    # Rate limit: RITUAL_LOG_RATE_LIMIT per IP per hour — DynamoDB-backed (survives
    # cold starts; bounded in-memory fallback only, #2237). Public GET, so it needs
    # the same protection as every other write endpoint in this module.
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check("ritual_log", ip_hash, limit=RITUAL_LOG_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        return _rate_limited("ritual_log", "Too many taps recently. Try again in a bit.", retry_after=3600)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # #1405: private-class metrics land in their own Matthew-private partition —
    # never the evening_ritual record the public wellbeing aggregate reads. The
    # write path is shared (same signed link, same rate limit); only the
    # destination differs, so the public read surface structurally can't see it.
    from content.ritual_link import PRIVATE_RITUAL_METRICS, TIME_AFFLUENCE_PROBE_METRICS, WEEKLY_PROBE_METRICS

    try:
        table.update_item(
            # ALL destinations INLINE as USER_PREFIX-joined literals — the orphan
            # gate (tests/test_site_partition_orphans.py) resolves web writers only
            # inside the put/update call itself; a hoisted or dynamic pk makes
            # evening_ritual read as writerless (redded e1bcf766's Unit Tests).
            # #1409: weekly felt-reality probe taps land in felt_probe (their own
            # cadence + the calibration engine's read surface), never the daily
            # evening_ritual aggregate.
            # #1408: the weekly Time-Affluence probe (felt_time) lands in its own
            # time_affluence partition — read by the proxy + hypothesis-engine edge.
            Key={
                "pk": (
                    f"{USER_PREFIX}private_intake"
                    if metric in PRIVATE_RITUAL_METRICS
                    else (
                        f"{USER_PREFIX}time_affluence"
                        if metric in TIME_AFFLUENCE_PROBE_METRICS
                        else f"{USER_PREFIX}felt_probe" if metric in WEEKLY_PROBE_METRICS else f"{USER_PREFIX}evening_ritual"
                    )
                ),
                "sk": f"DATE#{date_str}",
            },
            UpdateExpression="SET #m = :v, #ts = :ts, #src = :src",
            ExpressionAttributeNames={
                "#m": metric,
                "#ts": f"{metric}_logged_at",
                "#src": "source",
            },
            ExpressionAttributeValues={
                ":v": Decimal(value),
                ":ts": now_iso,
                ":src": "evening_nudge_link",
            },
        )
    except Exception as e:
        logger.error(f"[ritual_log] DDB update failed: {e}")
        return _error(500, "Failed to record tap")

    logger.info(f"[ritual_log] date={date_str} metric={metric} value={value} ip_hash={ip_hash}")
    return _ok(
        {
            "logged": True,
            "date": date_str,
            "metric": metric,
            "value": value,
        },
        cache_seconds=0,
    )


def _predict_tallies(week_id, metric, *, _g):
    """Aggregate {up,down,flat: count} for one week+metric from VOTES#predict_week."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    logger = _g["logger"]
    table = _g["table"]
    out = {"up": 0, "down": 0, "flat": 0}
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq("VOTES#predict_week") & Key("sk").begins_with(f"WK#{week_id}#M#{metric}#C#"))
        for it in resp.get("Items", []):
            c = it.get("choice")
            if c in out:
                out[c] = int(it.get("vote_count", 0))
    except Exception as e:
        logger.error(f"[predict_week] tally read failed: {e}")
    return out


def _handle_predict_week(event: dict, *, _g) -> dict:
    """POST /api/predict_week — a reader predicts which way this week's metric moves.

    Body: {"week_id", "metric", "choice"} with choice ∈ {up, down, flat}.
    One prediction per IP per week per metric (DynamoDB dedup row, 8-day TTL).
    Validated against the live current_challenge's predict_metrics (fail-closed).
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _PREDICT_CHOICES = _g["_PREDICT_CHOICES"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _predict_subject = _g["_predict_subject"]
    _rate_limited = _g["_rate_limited"]
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

    subj = _predict_subject()
    if subj is None:
        return _error(404, "No active prediction this week")

    week_id = (body.get("week_id") or "").strip()
    metric = (body.get("metric") or "").strip().lower()
    choice = (body.get("choice") or "").strip().lower()
    if week_id != subj["week_id"]:
        return _error(409, "That prediction window has closed")
    if metric not in subj["metrics"]:
        return _error(404, "Unknown metric")
    if choice not in _PREDICT_CHOICES:
        return _error(400, "choice must be up, down, or flat")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    try:
        table.put_item(
            Item={
                "pk": "VOTES#rate_limit",
                "sk": f"PRED#{ip_hash}#{week_id}#{metric}",
                "voted_at": now_epoch,
                "ttl": now_epoch + 8 * 86400,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return _rate_limited("predict_week", "You already predicted this metric this week")
        logger.error(f"[predict_week] dedup check failed: {e}")
        return _error(500, "Prediction rate check failed")

    try:
        table.update_item(
            Key={"pk": "VOTES#predict_week", "sk": f"WK#{week_id}#M#{metric}#C#{choice}"},
            UpdateExpression="ADD vote_count :one SET week_id = :w, metric = :m, choice = :c, last_voted = :ts",
            ExpressionAttributeValues={":one": 1, ":w": week_id, ":m": metric, ":c": choice, ":ts": now_epoch},
        )
    except Exception as e:
        logger.error(f"[predict_week] increment failed: {e}")
        return _error(500, "Failed to record prediction")

    return _envelope(200, {"week_id": week_id, "metric": metric, "tallies": _predict_tallies(week_id, metric, _g=_g)})


def handle_predict_week_tally(event: dict, *, _g) -> dict:
    """GET /api/predict_week — read-only reader-consensus tallies for the week.

    Returns {"active": False} when there's no prediction subject (the widget then
    hides). Otherwise returns the metrics, per-metric tallies, and the actual
    outcome (`result`) once Matthew sets it on the challenge — so the front-end can
    show "readers said UP 64% · it actually went DOWN."
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _error = _g["_error"]
    _ok = _g["_ok"]
    _predict_subject = _g["_predict_subject"]
    subj = _predict_subject()
    if subj is None:
        # 300s (#2289 class rule): unmetered public read → every response edge-cached.
        return _ok({"active": False}, cache_seconds=300)
    qs = (event.get("queryStringParameters") or {}) or {}
    metric = (qs.get("metric") or "").strip().lower()
    if metric and metric not in subj["metrics"]:
        return _error(404, "Unknown metric")
    metrics = [metric] if metric else list(subj["metrics"].keys())
    tallies = {m: _predict_tallies(subj["week_id"], m, _g=_g) for m in metrics}
    return _ok(
        {
            "active": True,
            "week_id": subj["week_id"],
            "metrics": subj["metrics"],
            "result": subj.get("result"),
            "tallies": tallies,
        },
        # 300s not 60s (#2289): the tally is the only thing between an abusive
        # crawler and a DDB query per hit — the class rule trades ≤5 min of tally
        # staleness for edge absorption. The reader's own POST is unaffected.
        cache_seconds=300,
    )


def _handle_board_question(event: dict, *, _g) -> dict:
    """POST /api/board_question — capture a reader question for the AI board.

    A near-clone of _handle_submit_finding: rate-limited per IP, HTML-stripped and
    length-capped, vice-filtered, written to S3 with status=pending for Matthew to
    moderate. NO AI is invoked here — the answer is produced later via the already
    budget/rate-gated /api/board_ask and published as a dispatch. The optional email
    is stored privately for a reply and is never echoed back or published.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    BOARD_QUESTION_RATE_LIMIT = _g["BOARD_QUESTION_RATE_LIMIT"]
    S3_REGION = _g["S3_REGION"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    boto3 = _g["boto3"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    os = _g["os"]
    re = _g["re"]
    timezone = _g["timezone"]
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]

    # #2237: this door's old `else` branch set `allowed = True` unconditionally —
    # an unmetered S3 write path whenever the shared limiter was unavailable. It
    # now shares the module chokepoint with every other door.
    allowed, remaining, _retry = _rate_check("board_question", ip_hash, limit=BOARD_QUESTION_RATE_LIMIT, window_seconds=3600)
    if not allowed:
        return _rate_limited("board_question", f"Rate limit reached. {BOARD_QUESTION_RATE_LIMIT} questions per hour.", retry_after=3600)

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")

    question = re.sub(r"<[^>]+>", "", (body.get("question") or "").strip())[:500]
    email = re.sub(r"<[^>]+>", "", (body.get("email") or "").strip())[:254]
    if not question or len(question) < 10:
        return _error(400, "Question must be at least 10 characters.")
    if email and "@" not in email:
        return _error(400, "Invalid email format.")
    # Fail-closed on blocked-vice terms (privacy). Capture is moderated by Matthew
    # before any answer is published, but reject the obvious cases at the door.
    if _is_blocked_vice(question):
        return _error(400, "That question can't be submitted.")

    timestamp = datetime.now(timezone.utc).isoformat()
    # Content-based id so a same-month retry overwrites rather than duplicating.
    qid = hashlib.sha256(f"{ip_hash}:{question}".encode()).hexdigest()[:12]
    record = {
        "id": qid,
        "question": question,
        "email": email if email else None,
        "submitted_at": timestamp,
        "ip_hash": ip_hash,
        "status": "pending",
    }

    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    s3_key = f"generated/board_questions/{month}_{qid}.json"
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=json.dumps(record, indent=2), ContentType="application/json")
        logger.info(f"[board_question] Stored: {s3_key}")
    except Exception as e:
        logger.error(f"[board_question] S3 write failed: {e}")
        return _error(503, "Unable to store question. Try again later.")

    return _envelope(
        200,
        {
            "success": True,
            "id": qid,
            "message": "Question received — Matthew reviews these and the board answers a selection.",
            "remaining": remaining,
        },
    )
