"""lambdas/web/site_api_social_experiments.py — the reader-facing experiment surface: the library, its vote/follow doors, the
per-experiment detail read, and the reader suggestion capture door.

Split out of ``lambdas/web/site_api_social.py`` (#2515) — the facade keeps the
routed entrypoints as thin delegators and this module holds the bodies. Handlers
read the facade's shared + monkeypatched state through the ``_g`` hand-off
(``_g`` is a delegator's ``globals()``), so routes, response contracts and the
test monkeypatch surface are unchanged. This module does NOT import the facade,
so there is no import cycle.
"""


def handle_experiment_library(*, _g) -> dict:
    """
    GET /api/experiment_library
    Returns the full experiment library from S3 config, merged with:
      - Vote counts from DynamoDB
      - Status from active/completed experiments (matched by library_id or name slug)
    Cache: 900s (15 min).
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    COMPLETED_RUN_STATUSES = _g["COMPLETED_RUN_STATUSES"]
    Key = _g["Key"]
    PT = _g["PT"]
    S3_REGION = _g["S3_REGION"]
    USER_PREFIX = _g["USER_PREFIX"]
    _decimal_to_float = _g["_decimal_to_float"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _ok = _g["_ok"]
    boto3 = _g["boto3"]
    datetime = _g["datetime"]
    json = _g["json"]
    logger = _g["logger"]
    os = _g["os"]
    re = _g["re"]
    table = _g["table"]
    with_phase_filter = _g["with_phase_filter"]
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_library] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    # ── Load vote counts from DynamoDB ──
    vote_counts = {}
    try:
        vote_pk = "VOTES#experiment_library"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            lib_id = item.get("sk", "").replace("LIB#", "")
            vote_counts[lib_id] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[experiment_library] Vote query failed (non-fatal): {e}")

    # ── Load active/completed experiments to merge status ──
    exp_status_map = {}
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(exp_pk),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            exp_id = item.get("sk", "").replace("EXP#", "")
            # #2240: the live overlay is a second door into this public payload —
            # screen the record's name AND id the same way the challenge routes do
            # before any of it can key or colour a published library entry.
            if _is_blocked_vice(item.get("name", "")) or _is_blocked_vice(exp_id):
                continue
            lib_id = item.get("library_id")
            status = item.get("status", "unknown")
            start = item.get("start_date", "")
            days_in = None
            if status == "active" and start:
                try:
                    days_in = (datetime.now(PT).replace(tzinfo=None) - datetime.strptime(start, "%Y-%m-%d")).days + 1
                except Exception:
                    pass

            entry = {
                "status": status,
                "experiment_id": exp_id,
                "days_in": days_in,
                "start_date": start,
                "outcome": item.get("outcome"),
                "grade": item.get("grade"),
                "hypothesis_confirmed": item.get("hypothesis_confirmed"),
            }
            if lib_id:
                exp_status_map[lib_id] = entry
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if name_slug:
                exp_status_map.setdefault(name_slug, entry)
    except Exception as e:
        logger.warning(f"[experiment_library] Experiment query failed (non-fatal): {e}")

    # ── Merge votes + experiment status into library entries ──
    # #2240: screen the catalog entries (name AND id — a keyword often lives only in
    # the id while the display name is benign, ER-06) before anything downstream can
    # count, group or publish them. total_experiments/total_votes are computed from
    # the screened list, so a blocked entry is not even visible as a count.
    experiments = [
        e for e in (library.get("experiments") or []) if not (_is_blocked_vice(e.get("name", "")) or _is_blocked_vice(e.get("id", "")))
    ]
    pillar_map = {}
    pillar_meta = library.get("pillars", {})
    pillar_order = library.get("pillar_order", list(pillar_meta.keys()))

    total_votes = 0
    for exp in experiments:
        lib_id = exp.get("id", "")
        exp["votes"] = vote_counts.get(lib_id, exp.get("votes", 0))
        total_votes += exp["votes"]

        matched = exp_status_map.get(lib_id)
        if matched:
            exp["status"] = matched["status"]
            exp["active_experiment_id"] = matched["experiment_id"]
            exp["days_in"] = matched.get("days_in")

        pillar_id = exp.get("pillar", "other")
        if pillar_id not in pillar_map:
            meta = pillar_meta.get(pillar_id, {})
            pillar_map[pillar_id] = {
                "id": pillar_id,
                "label": meta.get("label", pillar_id.title()),
                "icon": meta.get("icon", "circle"),
                "color": meta.get("color"),
                "experiments": [],
                "stats": {"total": 0, "active": 0, "completed": 0, "backlog": 0},
            }
        group = pillar_map[pillar_id]
        group["experiments"].append(exp)
        group["stats"]["total"] += 1
        s = exp.get("status", "backlog")
        if s == "active":
            group["stats"]["active"] += 1
        elif s in COMPLETED_RUN_STATUSES:
            group["stats"]["completed"] += 1
        else:
            group["stats"]["backlog"] += 1

    pillars = []
    for pid in pillar_order:
        if pid in pillar_map:
            group = pillar_map[pid]
            group["experiments"].sort(key=lambda e: (0 if e.get("status") == "active" else 1, -(e.get("votes") or 0)))
            pillars.append(group)
    for pid, group in pillar_map.items():
        if pid not in pillar_order:
            pillars.append(group)

    return _ok(
        {
            "pillars": pillars,
            "total_experiments": len(experiments),
            "total_votes": total_votes,
            "version": library.get("version", "1.0.0"),
        },
        cache_seconds=900,
    )


def _handle_experiment_vote(event: dict, *, _g) -> dict:
    """
    POST /api/experiment_vote
    Body: {"library_id": "post-dinner-walk"}
    Rate limit: 1 vote per IP per experiment per 24 hours via DynamoDB TTL.
    library_id must exist in the experiment library (anti-pollution, 2026-06-12).
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    _valid_library_ids = _g["_valid_library_ids"]
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
    # value. The default 500 cap is deliberate: it leaves the >80 check below the
    # thing that rejects a long id, rather than silently truncating it into a valid one.
    library_id = _sanitise_text(body.get("library_id")).lower()
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required (max 80 chars)")
    valid_ids = _valid_library_ids()
    if not valid_ids:
        return _error(503, "Experiment library unavailable — try again shortly")
    if library_id not in valid_ids:
        return _error(400, "Unknown experiment")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#LIB#{library_id}"
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
            return _rate_limited("experiment_vote", "Already voted for this experiment in the last 24 hours")
        logger.error(f"[experiment_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#experiment_library"
    vote_sk = f"LIB#{library_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET library_id = :lid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":lid": library_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[experiment_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return _envelope(200, {"library_id": library_id, "new_count": new_count})


def _handle_experiment_follow(event: dict, *, _g) -> dict:
    """
    POST /api/experiment_follow
    Body: {"email": "user@example.com", "library_id": "post-dinner-walk"}
    Stores interest so we can notify when experiment completes.
    Rate limit: 10 follows per IP per hour.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    FOLLOW_RATE_LIMIT = _g["FOLLOW_RATE_LIMIT"]
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    _valid_library_ids = _g["_valid_library_ids"]  # #2681: same id source as the vote door
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

    # #2679 — see _handle_experiment_vote.
    if not isinstance(body, dict):
        return _error(400, "Body must be a JSON object")

    email = _sanitise_text(body.get("email")).lower()
    library_id = _sanitise_text(body.get("library_id")).lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required")

    # #2681: the SAME existence check _handle_experiment_vote makes. Without it this
    # door returned 200 for any id, and since the sort key is EMAIL#<hash>#EXP#<id>,
    # arbitrary address × id pairs mint unbounded distinct rows — the exact thing the
    # vote door's "an attacker can mint arbitrary VOTES rows" comment guards against.
    # Kept identical to the sibling (including the 503) so the two doors cannot drift.
    valid_ids = _valid_library_ids()
    if not valid_ids:
        return _error(503, "Experiment library unavailable — try again shortly")
    if library_id not in valid_ids:
        return _error(400, "Unknown experiment")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: FOLLOW_RATE_LIMIT follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"FOLLOW#{ip_hash}#{now_epoch // 3600}"
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
            return _rate_limited("experiment_follow", "Too many follow requests. Try again later.")
    except Exception as e:
        logger.error(f"[experiment_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "EXPERIMENT_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#EXP#{library_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "library_id": library_id,
                "followed_at": now_epoch,
                "notified": False,
                # #2698/#2681 box 3: an address typed into a public form is UNVERIFIED —
                # a stranger can type a third party's. Recorded as state rather than
                # assumed, so a future notifier has to look at it. Nothing reads these
                # partitions today (tests/test_follow_consent_state_2698.py holds that
                # line), so no unconsented mail can be sent; the day one is added it must
                # filter on this flag, and the guard's failure message says so.
                "email_verified": False,
                "verified_at": None,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return _envelope(200, {"already_following": True, "library_id": library_id})
        logger.error(f"[experiment_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return _envelope(200, {"followed": True, "library_id": library_id})


def _handle_experiment_detail(event: dict, *, _g) -> dict:
    """
    GET /api/experiment_detail?id=post-dinner-walk
    Returns full detail for a single experiment from the library,
    merged with any active/completed DynamoDB experiment data + votes + followers.
    Cache: 900s.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    COMPLETED_RUN_STATUSES = _g["COMPLETED_RUN_STATUSES"]
    Key = _g["Key"]
    S3_REGION = _g["S3_REGION"]
    USER_PREFIX = _g["USER_PREFIX"]
    _decimal_to_float = _g["_decimal_to_float"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _ok = _g["_ok"]
    boto3 = _g["boto3"]
    datetime = _g["datetime"]
    json = _g["json"]
    logger = _g["logger"]
    os = _g["os"]
    re = _g["re"]
    table = _g["table"]
    timezone = _g["timezone"]
    with_phase_filter = _g["with_phase_filter"]
    params = event.get("queryStringParameters") or {}
    lib_id = (params.get("id") or "").strip().lower()
    if not lib_id:
        return _error(400, "id query parameter is required")

    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_detail] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    lib_exp = None
    for exp in library.get("experiments") or []:
        if exp.get("id") == lib_id:
            lib_exp = exp
            break
    # #2240: a screened entry is indistinguishable from an absent one — same 404,
    # same message, so the response can't confirm the entry exists.
    if lib_exp and (_is_blocked_vice(lib_exp.get("name", "")) or _is_blocked_vice(lib_exp.get("id", ""))):
        return _error(404, f"Experiment '{lib_id}' not found in library")
    if not lib_exp:
        return _error(404, f"Experiment '{lib_id}' not found in library")

    pillar_meta = (library.get("pillars") or {}).get(lib_exp.get("pillar", ""), {})
    lib_exp["pillar_label"] = pillar_meta.get("label", lib_exp.get("pillar", "").title())
    lib_exp["pillar_icon"] = pillar_meta.get("icon", "circle")

    # Vote count
    try:
        vote_resp = table.get_item(Key={"pk": "VOTES#experiment_library", "sk": f"LIB#{lib_id}"})
        vote_item = _decimal_to_float(vote_resp.get("Item"))
        lib_exp["votes"] = int(vote_item.get("vote_count", 0)) if vote_item else 0
    except Exception:
        lib_exp["votes"] = 0

    # Follower count
    try:
        follow_resp = table.query(
            KeyConditionExpression=Key("pk").eq("EXPERIMENT_FOLLOWS"),
            FilterExpression="library_id = :lid",
            ExpressionAttributeValues={":lid": lib_id},
            Select="COUNT",
        )
        lib_exp["follower_count"] = follow_resp.get("Count", 0)
    except Exception:
        lib_exp["follower_count"] = 0

    # Past runs from DynamoDB
    runs = []
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot experiments
                    "KeyConditionExpression": Key("pk").eq(exp_pk),
                    "ScanIndexForward": False,
                    "Limit": 100,
                }
            )
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            item_lib_id = item.get("library_id", "")
            # #2240: the run overlay is the second door into this payload — screen the
            # live record's name AND its experiment id before it joins `runs`.
            if _is_blocked_vice(item.get("name", "")) or _is_blocked_vice(item.get("sk", "").replace("EXP#", "")):
                continue
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if item_lib_id == lib_id or name_slug == lib_id:
                start = item.get("start_date", "")
                end = item.get("end_date")
                status = item.get("status", "unknown")
                days = None
                try:
                    end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
                    days = max(0, (end_d - datetime.strptime(start, "%Y-%m-%d")).days)
                except Exception:
                    pass
                runs.append(
                    {
                        "experiment_id": item.get("sk", "").replace("EXP#", ""),
                        "status": status,
                        "start_date": start,
                        "end_date": end,
                        "days": days,
                        "hypothesis": item.get("hypothesis"),
                        "outcome": item.get("outcome") or item.get("result_summary"),
                        "primary_metric": item.get("primary_metric"),
                        "baseline_value": item.get("baseline_value"),
                        "result_value": item.get("result_value"),
                        "grade": item.get("grade"),
                        "compliance_pct": item.get("compliance_pct"),
                        "reflection": item.get("reflection"),
                        "mechanism": item.get("mechanism"),
                        "key_finding": item.get("key_finding"),
                        "hypothesis_confirmed": item.get("hypothesis_confirmed"),
                        "iteration": item.get("iteration", 1),
                    }
                )
    except Exception as e:
        logger.warning(f"[experiment_detail] Experiment query failed: {e}")

    lib_exp["runs"] = runs
    lib_exp["total_runs"] = len(runs)
    lib_exp["active_run"] = next((r for r in runs if r["status"] == "active"), None)
    # #2221: the library pillar header counted a run as completed for any TERMINAL
    # status; the detail page it links to counted only literal "completed", so a
    # `failed` run made the two surfaces disagree about the same experiment.
    lib_exp["completed_runs_count"] = sum(1 for r in runs if r["status"] in COMPLETED_RUN_STATUSES)

    return _ok(lib_exp, cache_seconds=900)


def _handle_experiment_suggest(event: dict, *, _g) -> dict:
    """POST /api/experiment_suggest — Store reader experiment suggestion.

    Rate-limited: 3 suggestions per IP per hour (#358). Suggestions are stored
    with status="pending" so they're distinguishable from owner-created experiments
    and can be moderated before surfacing publicly.
    """
    # Facade state injected via `_g` (the delegator's globals()) — the same
    # module object the tests patch (see web/site_api_social.py's header).
    _envelope = _g["_envelope"]
    _error = _g["_error"]
    _is_blocked_vice = _g["_is_blocked_vice"]
    _rate_check = _g["_rate_check"]
    _rate_limited = _g["_rate_limited"]
    _sanitise_text = _g["_sanitise_text"]
    datetime = _g["datetime"]
    extract_client_ip = _g["extract_client_ip"]
    extract_idempotency_identity = _g["extract_idempotency_identity"]
    hashlib = _g["hashlib"]
    json = _g["json"]
    logger = _g["logger"]
    table = _g["table"]
    timezone = _g["timezone"]
    # Rate limit: 3 per IP per hour (#358). Applied unconditionally (#2237).
    ip = extract_client_ip(event)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    allowed, _rem, _retry = _rate_check("experiment_suggest", ip_hash, limit=3, window_seconds=3600)
    if not allowed:
        return _rate_limited("experiment_suggest", "Too many suggestions. Please try again later.", retry_after=3600)
    # #2221: this door was the module's only capture surface that (a) parsed with
    # `event.get("body", "{}")` — the DEFAULT form, which never fires for a Function
    # URL's `body: ""` — (b) applied a MINIMUM but no MAXIMUM length, (c) never
    # HTML-stripped, and (d) never ran the blocked-vice screen its two siblings run.
    # A malformed body therefore 500'd (5xx alarm noise for a reader's typo) and a
    # single POST could park a ~400 KB item in Matthew's moderation partition.
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")
    if not isinstance(body, dict):
        return _error(400, "Invalid JSON body")
    idea = _sanitise_text(body.get("idea"))
    source = _sanitise_text(body.get("source"))
    if not idea or len(idea) < 10:
        return _error(400, "Idea must be at least 10 characters")
    if _is_blocked_vice(idea) or _is_blocked_vice(source):
        return _error(400, "That suggestion can't be submitted.")
    # #2682: the sort key was a wall-clock timestamp, so an identical retry — a
    # double-click, a client retry, a flaky network — created a SECOND moderation row for
    # the same submission, and Matthew paid for it by reviewing the same idea twice.
    # Both sibling capture doors already derive their id from the content
    # (`_handle_submit_finding`, `_handle_board_question` in site_api_social_engage.py,
    # both `sha256(f"{ip_hash}:{content}")[:12]`); this one was the outlier.
    #
    # The write is CONDITIONAL rather than a plain overwrite, and that matters beyond
    # tidiness: an unconditional put on the same key would reset `created_at` and — worse
    # — stamp `status: "pending"` back over a moderation decision Matthew had already
    # made. A retry must be a no-op on an existing row, not a silent un-approval.
    #
    # #2932: the id derives from the IDEMPOTENCY identity, not the rate-limit
    # `ip_hash`. When CloudFront-Viewer-Address arrives they are the same viewer
    # address; when it doesn't, `ip_hash` is the shared fail-closed sentinel and the
    # conditional write below would silently swallow a SECOND reader's identical
    # idea as a "duplicate" — data loss the moderation queue can't see. The
    # idempotency identity is per-request unique in that state (dedup off, loudly
    # logged by common.client_ip), so both readers' rows persist.
    id_hash = hashlib.sha256(extract_idempotency_identity(event).encode()).hexdigest()[:16]
    suggestion_id = hashlib.sha256(f"{id_hash}:{idea}:{source}".encode()).hexdigest()[:12]
    now = datetime.now(timezone.utc).isoformat()
    try:
        duplicate = False
        try:
            table.put_item(
                Item={
                    "pk": "USER#matthew#SOURCE#experiment_suggestions",
                    "sk": f"SUGGEST#{suggestion_id}",
                    "suggestion_id": suggestion_id,
                    "idea": idea,
                    "source": source,
                    "status": "pending",
                    "submitted_by": "reader",
                    "created_at": now,
                },
                ConditionExpression="attribute_not_exists(sk)",
            )
        except Exception as e:
            if "ConditionalCheckFailedException" not in str(e):
                raise
            duplicate = True
        # The id is returned either way — a caller that cannot see the id cannot tell an
        # accepted retry from a new submission, which is the same opacity in a new place.
        return _envelope(200, {"status": "received", "id": suggestion_id, "duplicate": duplicate})
    except Exception as e:
        logger.error(f"[site_api] experiment_suggest failed: {e}")
        return _error(500, "Failed to submit suggestion")
