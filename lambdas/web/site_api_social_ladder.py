"""lambdas/web/site_api_social_ladder.py — the Engagement Ladder rung counts (#1393), the Replicator self-cert door, and
the Cohort Strip (#1394) submit/read pair.

Split out of ``lambdas/web/site_api_social.py`` (#2515) — the facade keeps the
routed entrypoints as thin delegators and this module holds the bodies. Handlers
read the facade's shared + monkeypatched state through the ``_g`` hand-off
(``_g`` is a delegator's ``globals()``), so routes, response contracts and the
test monkeypatch surface are unchanged. This module does NOT import the facade,
so there is no import cycle.
"""


def _ladder_subscriber_count(*, _g) -> int | None:
    """Confirmed-subscriber count — the same COUNT query behind /api/sub_count."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    USER_ID = _g["USER_ID"]
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
        return int(resp.get("Count", 0))
    except Exception as e:
        # ADR-104 / #2221: returning 0 here published, with a provenance block
        # vouching for it, the FACT that nobody has ever subscribed — during an
        # outage. None is absence; the `reader` rung already models it.
        logger.warning(f"[ladder] subscriber count failed: {e}")
        return None


def _ladder_predictor_count(*, _g) -> int | None:
    """Distinct predict-the-week participants in the active window.

    Counts DISTINCT ip_hash across the predict dedup rows (pk VOTES#rate_limit,
    sk PRED#{ip_hash}#{week}#{metric}). Those rows carry an 8-day TTL, so this is
    honestly 'participants in the current prediction window', not an all-time total —
    the provenance says exactly that. No new partition, no PII (ip_hash only, already
    the site's dedup primitive)."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    Key = _g["Key"]
    logger = _g["logger"]
    table = _g["table"]
    seen: set = set()
    try:
        kwargs: dict = {"KeyConditionExpression": Key("pk").eq("VOTES#rate_limit") & Key("sk").begins_with("PRED#")}
        for _ in range(50):  # page cap — bounded by the 8-day TTL window, personal scale
            resp = table.query(**kwargs)
            for it in resp.get("Items", []):
                parts = str(it.get("sk", "")).split("#")
                if len(parts) >= 2 and parts[1]:
                    seen.add(parts[1])
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:
        # A partial page walk is not a count — absence, not a floor (ADR-104, #2221).
        logger.warning(f"[ladder] predictor count failed: {e}")
        return None
    return len(seen)


def _ladder_replicator_count(*, _g) -> int | None:
    """Self-certified Replication Kit completions — the aggregate counter row."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _LADDER_REPLICATOR_PK = _g["_LADDER_REPLICATOR_PK"]
    _decimal_to_float = _g["_decimal_to_float"]
    logger = _g["logger"]
    table = _g["table"]
    try:
        resp = table.get_item(Key={"pk": _LADDER_REPLICATOR_PK, "sk": "COUNT"})
        item = _decimal_to_float(resp.get("Item") or {})
        return int(item.get("cert_count", 0) or 0)
    except Exception as e:
        logger.warning(f"[ladder] replicator count failed: {e}")
        return None


def _ladder_contributors(*, _g) -> tuple:
    """(count, credited_names) of verified+published reader findings.

    Reads the single published-findings index the moderation path maintains. Only
    opt-in display names are surfaced — never an email or reader identity. Fail-soft to
    (0, []) when nothing has been published yet."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _PUBLISHED_FINDINGS_INDEX_KEY = _g["_PUBLISHED_FINDINGS_INDEX_KEY"]
    _load_s3_json = _g["_load_s3_json"]
    idx = _load_s3_json(_PUBLISHED_FINDINGS_INDEX_KEY, "published_findings_index")
    entries = idx.get("published") if isinstance(idx, dict) else None
    if not isinstance(entries, list):
        return 0, []
    credited: list = []
    for e in entries:
        if isinstance(e, dict) and e.get("credit_opt_in") and isinstance(e.get("credit_name"), str):
            nm = e["credit_name"].strip()[:60]
            if nm:
                credited.append(nm)
    return len(entries), credited


def handle_ladder_counts(*, _g) -> dict:
    """GET /api/ladder_counts — public engagement-ladder rung counts + provenance.

    Read-only. Every published count is DERIVED FROM DATA (never hand-maintained) and
    carries a .provenance block naming its source + method. The Reader rung is the
    anonymous base — deliberately uncounted (no identity is tracked), which the
    provenance states rather than fabricating a number."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _ok = _g["_ok"]
    subscribers = _ladder_subscriber_count(_g=_g)
    predictors = _ladder_predictor_count(_g=_g)
    replicators = _ladder_replicator_count(_g=_g)
    contributors, credited = _ladder_contributors(_g=_g)
    rungs = {
        "reader": {
            "label": "Reader",
            "count": None,
            "countable": False,
            "provenance": {
                "source": "none",
                "method": "not counted — anonymous, no identity or PII is stored",
                "note": "everyone who reads; the base rung has no number by design",
            },
        },
        "subscriber": {
            "label": "Subscriber",
            "count": subscribers,
            "countable": True,
            "available": subscribers is not None,
            "provenance": {
                "source": "ddb:USER#matthew#SOURCE#subscribers",
                "method": "COUNT of confirmed (double-opt-in) subscriber records",
                "note": "the same query behind /api/sub_count",
            },
        },
        "predictor": {
            "label": "Predictor",
            "count": predictors,
            "countable": True,
            "available": predictors is not None,
            "provenance": {
                "source": "ddb:VOTES#rate_limit (PRED# dedup rows)",
                "method": "distinct participants who cast a predict-the-week call",
                "note": "the active window only — dedup rows carry an 8-day TTL",
            },
        },
        "replicator": {
            "label": "Replicator",
            "count": replicators,
            "countable": True,
            "available": replicators is not None,
            "provenance": {
                "source": "ddb:VOTES#ladder_replicator",
                "method": "self-certified Replication Kit completions, deduped per source",
                "note": "self-reported; no proof required or stored",
            },
        },
        "contributor": {
            "label": "Contributor",
            "count": contributors,
            "countable": True,
            "credited": credited,
            "provenance": {
                "source": "s3:generated/findings/_published_index.json",
                "method": "reader findings verified + published via the existing moderation path",
                "note": "named credit is opt-in only; no emails or identities are exposed",
            },
        },
    }
    return _ok(
        {
            "order": ["reader", "subscriber", "predictor", "replicator", "contributor"],
            "rungs": rungs,
        },
        cache_seconds=300,
    )


def _handle_replicate_certify(event: dict, *, _g) -> dict:
    """POST /api/replicate_certify — a reader self-certifies a completed Replication
    Kit run, bumping the public Replicator rung count.

    SELF-CERTIFIED by design (#1393): no proof is required and none is stored — the
    reader asserts they ran a kit. Deduped per source, PERMANENTLY (one cert per IP,
    ever — a no-ttl row on the shared VOTES#rate_limit partition, #1825) so a
    double-tap / retry / return-visit-after-the-old-8-day-window can't inflate the
    count; the published provenance says "deduped per source" with no window
    qualifier, so the dedup itself must not expire. No PII: only an ip_hash (already
    the site's dedup primitive) and an aggregate counter. ZERO moderation load —
    nothing lands in a review queue."""
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _LADDER_REPLICATOR_PK = _g["_LADDER_REPLICATOR_PK"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    source_ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    try:
        table.put_item(
            Item={
                "pk": "VOTES#rate_limit",
                "sk": f"REPL#{ip_hash}",
                "voted_at": now_epoch,
                # No ttl (#1825) — unlike the rate-limit-style dedup rows elsewhere in
                # this module, this one must never expire: the published provenance
                # promises a one-time-ever cert, not a rolling window.
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            # Idempotent: already counted this source. Report success so the reader's
            # own rung still resolves, but do NOT double-count.
            return _envelope(200, {"certified": True, "counted": False, "message": "Already counted — thanks for replicating."})
        logger.error(f"[replicate_certify] dedup write failed: {e}")
        return _error(500, "Could not record certification")
    try:
        table.update_item(
            Key={"pk": _LADDER_REPLICATOR_PK, "sk": "COUNT"},
            UpdateExpression="ADD cert_count :one SET last_certified = :ts",
            ExpressionAttributeValues={":one": 1, ":ts": now_epoch},
        )
    except Exception as e:
        logger.error(f"[replicate_certify] counter increment failed: {e}")
        return _error(500, "Could not record certification")
    return _envelope(200, {"certified": True, "counted": True, "message": "Logged — you're on the Replicator rung."})


def _handle_cohort_submit(event: dict, *, _g) -> dict:
    """POST /api/cohort_submit — one-tap weekly single-number submission (#1394).

    Body: {"value": <number>}. NO free text — a single number is the entire payload,
    so there is nothing to moderate. Reuses the check-in write class: same DynamoDB
    `table`, same DDB-backed `_ddb_rate_check` (1 submission / IP / week), same
    idempotent read-free write discipline as _handle_challenge_checkin.

    The write lands in the cohort partition `COHORT#<metric>#<week>` at sk
    `SUBMIT#<ip_hash>` — a re-tap from the same IP overwrites its own row (last-tap
    wins), so a double-tap can never inflate n. The individual value is never read
    back out for display; only the aggregate strip is ever served.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    COHORT_SUBMIT_WINDOW = _g["COHORT_SUBMIT_WINDOW"]
    Decimal = _g["Decimal"]
    _cohort_partition = _g["_cohort_partition"]
    _error = _g["_error"]
    _load_cohort_config = _g["_load_cohort_config"]
    _ok = _g["_ok"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    cfg = _load_cohort_config()
    if not cfg:
        return _error(404, "No cohort metric active this week")

    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")
    # #2679: this door's `value` handling is already fully type-guarded, but a
    # well-formed non-object body (`"a-string"`, `[1,2]`, `7`) still reached
    # `body.get` and raised out of the handler as a 502.
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")

    raw = body.get("value")
    if isinstance(raw, bool) or raw is None:
        return _error(400, "value (number) required")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _error(400, "value must be a number")
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf guard
        return _error(400, "value must be a finite number")

    amin, amax = float(cfg["axis_min"]), float(cfg["axis_max"])
    if not (amin <= value <= amax):
        return _error(400, f"value must be between {amin:g} and {amax:g} {cfg.get('unit', '')}".strip())

    metric_id = str(cfg["metric_id"])
    week = str(cfg["week"])

    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

    # Rate limit: 1 submission per IP per week — DDB-backed (the SAME limiter the
    # challenge check-in uses), survives warm-container distribution. Applied
    # unconditionally via the module chokepoint (#2237).
    allowed, _rem, _retry = _rate_check(f"cohort_submit:{week}", ip_hash, limit=1, window_seconds=COHORT_SUBMIT_WINDOW)
    if not allowed:
        return _rate_limited("cohort_submit", "You've already added your number this week.", retry_after=COHORT_SUBMIT_WINDOW)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        # pk INLINE via _cohort_partition — the cohort family, never a USER#…#SOURCE#
        # partition. sk keyed by ip_hash makes the write idempotent per participant.
        table.put_item(
            Item={
                "pk": _cohort_partition(metric_id, week),
                "sk": f"SUBMIT#{ip_hash}",
                "value": Decimal(str(value)),
                "week": week,
                "metric_id": metric_id,
                "logged_at": now_iso,
                "source": "website",
            }
        )
    except Exception as e:
        logger.error(f"[cohort_submit] DDB put failed: {e}")
        return _error(500, "Failed to record your number")

    logger.info(f"[cohort_submit] metric={metric_id} week={week} ip_hash={ip_hash}")
    # Never echo n or any other participant's number — the client refreshes the
    # aggregate strip through /api/cohort_strip, which enforces the k-anonymity floor.
    return _ok({"submitted": True, "metric_id": metric_id, "week": week}, cache_seconds=0)


def handle_cohort_strip(*, _g) -> dict:
    """GET /api/cohort_strip — the anonymous weekly distribution strip (#1394).

    Enforces the k-anonymity floor (n ≥ COHORT_K_FLOOR) as a HARD gate: below it the
    payload carries `visible: false` and NO distribution at all (a dignified
    "waiting for n≥5" state on the client, never a fabricated chart or band —
    ADR-105 confidence grammar). At or above the floor it returns AGGREGATES ONLY —
    a histogram + quartiles + Matthew's percentile. Individual submissions are never
    returned. Matthew's dot value comes from the weekly config, not the cohort
    partition, so his stats stay disjoint from the pool.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    COHORT_HIST_BINS = _g["COHORT_HIST_BINS"]
    COHORT_K_FLOOR = _g["COHORT_K_FLOOR"]
    Key = _g["Key"]
    _cohort_partition = _g["_cohort_partition"]
    _decimal_to_float = _g["_decimal_to_float"]
    _error = _g["_error"]
    _load_cohort_config = _g["_load_cohort_config"]
    _ok = _g["_ok"]
    logger = _g["logger"]
    table = _g["table"]
    cfg = _load_cohort_config()
    if not cfg:
        return _ok({"active": False}, cache_seconds=300)

    metric_id = str(cfg["metric_id"])
    week = str(cfg["week"])
    label = str(cfg.get("label", metric_id))
    unit = str(cfg.get("unit", ""))
    amin, amax = float(cfg["axis_min"]), float(cfg["axis_max"])
    matthew_value = cfg.get("matthew_value")
    try:
        matthew_value = float(matthew_value) if matthew_value is not None else None
    except (TypeError, ValueError):
        matthew_value = None

    base = {
        "active": True,
        "week": week,
        "metric_id": metric_id,
        "label": label,
        "unit": unit,
        "axis_min": amin,
        "axis_max": amax,
        "matthew_value": matthew_value,
        "floor": COHORT_K_FLOOR,
        "lower_is_better": bool(cfg.get("lower_is_better", False)),
    }

    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(_cohort_partition(metric_id, week)))
        items = resp.get("Items", []) or []
    except Exception as e:
        logger.error(f"[cohort_strip] DDB query failed: {e}")
        return _error(500, "Database error")

    values = []
    for it in items:
        v = _decimal_to_float(it.get("value"))
        if isinstance(v, (int, float)) and amin <= v <= amax:
            values.append(float(v))
    n = len(values)

    # HARD k-anonymity gate — below the floor, no distribution is emitted at all.
    # 300s (#2289 class rule): crossing the floor shows within 5 min; the held state
    # is the cheap-to-recompute one an unmetered crawler would otherwise hammer.
    if n < COHORT_K_FLOOR:
        return _ok({**base, "visible": False, "n": n}, cache_seconds=300)

    values.sort()
    span = amax - amin
    bins = [0] * COHORT_HIST_BINS
    for v in values:
        idx = int((v - amin) / span * COHORT_HIST_BINS)
        idx = min(COHORT_HIST_BINS - 1, max(0, idx))
        bins[idx] += 1

    def _pctile(p: float) -> float:
        if n == 1:
            return values[0]
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        return values[lo] + (values[hi] - values[lo]) * (k - lo)

    # Matthew's rank among the pool — a percentile, never his row exposed to others.
    m_pctile = None
    if matthew_value is not None:
        below = sum(1 for v in values if v < matthew_value)
        m_pctile = round(below / n * 100)

    return _ok(
        {
            **base,
            "visible": True,
            "n": n,
            "bins": bins,
            "bin_count": COHORT_HIST_BINS,
            "min": round(values[0], 2),
            "p25": round(_pctile(0.25), 2),
            "median": round(_pctile(0.5), 2),
            "p75": round(_pctile(0.75), 2),
            "max": round(values[-1], 2),
            "matthew_percentile": m_pctile,
        },
        # 300s not 120s (#2289): weekly distribution, unmetered by design — the
        # class rule wants every response of this door edge-cacheable at >=300.
        cache_seconds=300,
    )
