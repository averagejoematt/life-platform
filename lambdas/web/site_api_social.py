"""
lambdas/web/site_api_social.py — subscriber, experiment, challenge, and
nudge interaction handlers.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 4, 2026-05-26).

Endpoints:
  /api/verify_subscriber  — email → 24hr HMAC token
  /api/sub_count          — public subscriber count
  /api/nudge              — track in-page nudge clicks
  /api/submit_finding     — reader-submitted experiment findings (S3)
  /api/experiment_library, /api/experiment_vote, /api/experiment_follow,
  /api/experiment_detail, /api/experiment_suggest
  /api/challenge_catalog, /api/challenges, /api/current_challenge,
  /api/challenge_vote, /api/challenge_follow, /api/challenge_checkin

Also owns the supporting machinery — subscriber-token HMAC (which uses
the Anthropic API key as the signing secret), per-IP rate-limit stores
for nudge/submit_finding, and the rate-limit EMF metric emitter — since
nothing outside this cluster uses them.

CLASS RULE (#2289): every handler here is rate-limited OR an edge-cached public
read (``cache_seconds >= 300`` — CloudFront absorbs abuse; a DDB counter would
cost more than the read spend it counts). Full reasoning + enforcement:
``tests/test_unmetered_public_read_class_2289.py`` (a new unmetered,
under-cached public read fails the suite by name).
"""

import base64 as _b64
import copy
import hashlib
import hmac as _hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from common.client_ip import extract_client_ip  # #1221 — the ONE edge-observed client-IP helper
from content.social_signals import coach_route_of  # #1671 — training/mind coach-route classifier, reused read-side (#1674)
from experiment.phase_filter import with_phase_filter  # ADR-058
from ingestion.source_registry import SOURCE_REGISTRY  # #1679 — inbound channel live/dormant, read from the canonical registry
from privacy import social_provenance  # #1670 membrane — the origin:human predicate for the broadcast feed (#1672)

# ── Split handler modules (#2515) — the handler BODIES live there; this file keeps
# the routed entrypoints as thin delegators. Each delegator hands its own globals()
# over as `_g`, and the split handlers read the shared + monkeypatched state back
# through it (`_g["<name>"]`) — so routes, response contracts, and the test patch
# surface (social.table, social.boto3, social._load_cohort_config, …) are unchanged.
# The split modules do NOT import this one, so there is no import cycle.
from web import (
    site_api_social_challenges as _challenges,
    site_api_social_engage as _engage,
    site_api_social_experiments as _experiments,
    site_api_social_ladder as _ladder,
    site_api_social_membrane as _membrane,
)
from web.site_api_common import (
    PT,
    S3_REGION,
    STATUS_CACHE_TTL,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _envelope,
    _error,
    _is_blocked_vice,
    _load_s3_json,
    _ok,
    config_cache_valid,
    logger,
    table,
)

# These names have no in-file use of their own since #2515 — they are the facade's
# re-export / monkeypatch surface: the split handlers read them via the `_g` hand-off
# (`_g["<name>"]`, where `_g` is a delegator's globals()), and tests read/patch them on
# THIS module (social.extract_client_ip, social.with_phase_filter, …). Referenced here
# so the linter counts them as used. Never prune one without checking the `_g` reads.
__reexport__ = (copy, hashlib, timezone, Decimal, extract_client_ip, coach_route_of, with_phase_filter, _error, _ok)

# DynamoDB-backed rate limiting (survives warm-container distribution + cold
# starts). The site_api role already permits UpdateItem on the RATE#* partition
# (no IAM change needed).
#
# #2237: `_RATE_LIMITER_READY` must be read in EXACTLY ONE place — `_rate_check`
# below. Every public write door in this module calls that helper. Before #2237
# each door open-coded `if _RATE_LIMITER_READY:` for itself and five of the seven
# had no working fallback at all: `_handle_challenge_checkin`, `_handle_ritual_log`,
# `_handle_experiment_suggest` and `_handle_cohort_submit` had no `else` branch
# whatsoever, and `_handle_board_question`'s `else` set `allowed = True`
# unconditionally. A bundle missing `common/rate_limiter.py` therefore turned all
# five into unlimited anonymous write doors that still answered 200 — silently.
try:
    from common.rate_limiter import check_rate_limit as _ddb_rate_check

    _RATE_LIMITER_READY = True
except Exception:  # pragma: no cover — import guard
    _RATE_LIMITER_READY = False

# ── Module-owned globals ──────────────────────────────────
# These were originally module-level in site_api_lambda; they're only
# touched by the handlers in this file, so they move with the cluster.
_token_secret_cache = None

_nudge_counts: dict = {}  # ACCT-2: category -> approximate count
# S3 config caches for experiment + challenge endpoints
_challenges_cache = None
_challenges_cache_at = None  # #2019 — TTL stamp; None = pinned (test injection)
_challenge_catalog_cache: dict | None = None
_challenge_catalog_cache_at = None  # #2221 — TTL stamp; None = pinned (test injection)


def _catalog_cached() -> dict:
    """The `site/config/challenges_catalog.json` read, cached the way its sibling
    `_challenges_cache` is (#2019).

    Two bugs this closes (#2221). `_load_s3_json` returns `{}` on ANY failure and
    `{}` is not None, so the old `if _challenge_catalog_cache is None:` guard PINNED
    a warm container on an empty catalog after a single transient S3 error —
    /api/challenge_catalog served `{"challenges": []}` and /api/challenge_vote 503'd
    for the container's whole life. And with no expiry stamp at all, even a
    SUCCESSFUL load was never refreshed, so a published correction (including one
    that flips an entry to `public: false`) stayed dark until a recycle.
    """
    global _challenge_catalog_cache, _challenge_catalog_cache_at
    if _challenge_catalog_cache and config_cache_valid(_challenge_catalog_cache_at):
        return _challenge_catalog_cache
    loaded = _load_s3_json("site/config/challenges_catalog.json", "challenge_catalog")
    if not loaded:
        # A miss is never cached — the next request retries instead of serving an
        # empty catalog forever.
        return {}
    _challenge_catalog_cache = loaded
    _challenge_catalog_cache_at = time.monotonic()
    return _challenge_catalog_cache


# R17-04: separate Anthropic key for site-api (distinct from main ai-keys).
AI_SECRET_NAME = os.environ.get("AI_SECRET_NAME", "life-platform/site-api-ai-key")

# ── ACCT-2 / NEW-1 constants ──────────────────────────────
# Moved with their handlers in P1.1 Phase B step 7 (originally module-level
# in site_api_lambda.py — only _handle_nudge + _handle_submit_finding use them).
NUDGE_CATEGORIES = {"back_on_it", "watching", "take_your_time", "you_got_this"}
NUDGE_LABELS = {
    "back_on_it": "Get back on it 🔥",
    "watching": "We're watching 👀",
    "take_your_time": "Take your time ⏰",
    "you_got_this": "You've got this 💪",
}
FINDING_RATE_LIMIT = 3  # per IP per hour
FOLLOW_RATE_LIMIT = 10  # per IP per hour — shared by the experiment and challenge follow doors
# A run is DONE (not still running) in any of these terminal states. Read by BOTH the
# library pillar stats and the experiment-detail page so the two can't disagree (#2221).
COMPLETED_RUN_STATUSES = ("completed", "partial", "failed")


def _rate_limited(endpoint: str, message: str, retry_after=None, **extra) -> dict:
    """The ONE 429 in this module — emits the OBS-03 abuse metric, then answers.

    #2221: `_emit_rate_limit_metric` existed but only 3 of the module's 13 refusal
    paths called it, so the `LifePlatform/SiteApi RateLimitHit` metric under-reported
    abuse by ~77% and a flood against nudge/vote/follow/checkin/suggest/ritual/
    predict/cohort was invisible. Emitting inside the builder makes "a 429 that
    doesn't count" unexpressible; `tests/test_site_api_social_behavior.py` derives the
    429 set from the AST and asserts nothing else builds one.
    """
    _emit_rate_limit_metric(endpoint)
    return _envelope(429, {"error": message, **extra}, retry_after=retry_after)


def handle_current_challenge() -> dict:
    """GET /api/current_challenge — thin entrypoint; logic in the challenges split module."""
    return _challenges.handle_current_challenge(_g=globals())


_SUBSCRIBER_TOKEN_SECRET_NAME = os.environ.get("SUBSCRIBER_TOKEN_SECRET_NAME", "life-platform/subscriber-token-secret")


def _get_token_secret() -> str:
    """Fetch the dedicated subscriber-token HMAC secret from Secrets Manager.

    #106 (2026-05-30): migrated off `sha256("subscriber-token-v1:" + anthropic_api_key)`
    onto a dedicated 256-bit random key in Secrets Manager. Reasons:
      (1) AI-key rotation no longer invalidates every subscriber token.
      (2) AI-key compromise no longer enables token forgery.

    The pre-#106 fallback (derived from the Anthropic API key) was removed
    2026-06-12 — its 24h migration window expired 2026-05-31, and a loud
    failure beats silently signing with a derivable key.
    """
    global _token_secret_cache
    if _token_secret_cache:
        return _token_secret_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        _token_secret_cache = sm.get_secret_value(SecretId=_SUBSCRIBER_TOKEN_SECRET_NAME)["SecretString"]
        return _token_secret_cache
    except Exception as e:
        logger.error(f"[token_secret] Signing secret unavailable: {e}")
        raise RuntimeError("Token signing secret unavailable") from e


def _generate_subscriber_token(email: str) -> str:
    """Generate a 24hr HMAC token for a confirmed subscriber."""
    import time as _time

    expires = int(_time.time()) + 86400
    payload = f"{email.lower()}:{expires}"
    secret = _get_token_secret().encode()
    sig = _hmac.new(secret, payload.encode(), digestmod="sha256").hexdigest()[:32]
    return _b64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


# _validate_subscriber_token removed 2026-05-25 (P1.1): the live token validator
# now lives in lambdas/site_api_ai_lambda.py (ADR-036 split). This file's copy
# was only reachable from the dead inline /api/ask block in lambda_handler,
# which CloudFront routes to the AI Lambda instead.


def _is_confirmed_subscriber(email: str) -> bool:
    """Check DDB: USER#matthew#SOURCE#subscribers / EMAIL#{sha256} / status=confirmed"""
    import hashlib as _h

    email_hash = _h.sha256(email.strip().lower().encode()).hexdigest()
    try:
        resp = table.get_item(
            Key={
                "pk": f"USER#{USER_ID}#SOURCE#subscribers",
                "sk": f"EMAIL#{email_hash}",
            }
        )
        item = _decimal_to_float(resp.get("Item") or {})
        return item.get("status") == "confirmed"
    except Exception as e:
        logger.warning(f"[verify_subscriber] DDB lookup failed: {e}")
        return False


# #2239 — per-IP budget for /api/verify_subscriber. Generous against the ONE
# legitimate shape (a reader types their address once and the token then lives 24h
# in sessionStorage), tight against enumeration: 10/hr turns "probe the roster at
# line speed" into ~240 addresses/day/IP instead of unbounded. Sibling capture
# doors in this module sit at 1-5 per IP per window.
VERIFY_SUBSCRIBER_RATE_LIMIT = 10
VERIFY_SUBSCRIBER_RATE_WINDOW = 3600


def _handle_verify_subscriber(event: dict) -> dict:
    """GET /api/verify_subscriber?email=... — thin entrypoint; logic in the engage split module."""
    return _engage._handle_verify_subscriber(event, _g=globals())


def handle_subscriber_count() -> dict:
    """GET /api/subscriber_count — thin entrypoint; logic in the engage split module."""
    return _engage.handle_subscriber_count(_g=globals())


# ── #2237: the ONE rate-limit chokepoint for this module ─────────────────────
# Keyed "endpoint|ip_hash" -> newest timestamps inside the window. One store for
# every door, so a new write door cannot ship with its own (or no) fallback.
_FALLBACK_RATE_STORE: dict = {}
_FALLBACK_STORE_MAX_KEYS = 4096  # bounded — see _memory_rate_check's fail-closed branch


def _memory_rate_check(endpoint: str, ip_hash: str, limit: int, window_seconds: int) -> tuple:
    """Per-container sliding-window limiter, used ONLY when `common.rate_limiter`
    failed to import at module load.

    This is the degraded mode CLAUDE.md documents ("an in-memory dict is the
    fail-open fallback only"), previously open-coded at two of the seven doors and
    absent from the other five. Degraded, not absent: the window is per warm
    container rather than per fleet, so the effective ceiling becomes
    `limit x live containers` instead of `limit`. That is bounded and small.
    Skipping the check outright — the shipped behaviour #2237 found — was not
    bounded by anything.

    FAIL CLOSED at capacity. If the store already holds `_FALLBACK_STORE_MAX_KEYS`
    distinct (endpoint, ip) windows after pruning the expired ones, the write is
    REFUSED rather than admitted. The distributed flood is exactly the case an
    unbounded in-memory limiter cannot police, so it ends in 429s here instead of
    an unmetered write path plus an ever-growing dict in a 20-concurrency Lambda.

    Returns the shared limiter's (allowed, remaining, retry_after) triple.
    """
    now = int(time.time())
    key = f"{endpoint}|{ip_hash}"
    recent = [t for t in _FALLBACK_RATE_STORE.get(key, []) if t > now - window_seconds]

    if not recent and len(_FALLBACK_RATE_STORE) >= _FALLBACK_STORE_MAX_KEYS:
        for stale in [k for k, ts in _FALLBACK_RATE_STORE.items() if not any(t > now - window_seconds for t in ts)]:
            _FALLBACK_RATE_STORE.pop(stale, None)
        if len(_FALLBACK_RATE_STORE) >= _FALLBACK_STORE_MAX_KEYS:
            logger.warning(f"[rate_limit] in-memory fallback at capacity — refusing {endpoint} (fail closed)")
            return False, 0, window_seconds

    if len(recent) >= limit:
        _FALLBACK_RATE_STORE[key] = recent[-limit:]
        return False, 0, window_seconds

    recent.append(now)
    _FALLBACK_RATE_STORE[key] = recent[-max(limit, 1) :]
    return True, max(0, limit - len(recent)), window_seconds


def _rate_check(endpoint: str, ip_hash: str, limit: int, window_seconds: int, fail_open: bool = True) -> tuple:
    """The single door every rate-limited write in this module passes through.

    Uses the shared DynamoDB limiter when it is available and the bounded
    in-memory fallback when it is not — but NEVER returns "allowed" without having
    applied a limit. `_RATE_LIMITER_READY` is read here and nowhere else, which is
    what `tests/test_site_api_social_behavior.py` pins: a future write door that
    forgets its fallback is not expressible, because there is only one fallback.
    """
    if _RATE_LIMITER_READY:
        return _ddb_rate_check(table, endpoint=endpoint, ip_hash=ip_hash, limit=limit, window_seconds=window_seconds, fail_open=fail_open)
    return _memory_rate_check(endpoint, ip_hash, limit, window_seconds)


def _emit_rate_limit_metric(endpoint: str) -> None:
    """OBS-03: EMF metric emitted when a rate limit is hit. Zero-config via stdout."""
    import json as _json
    import time as _t

    try:
        emf = {
            "_aws": {
                "Timestamp": int(_t.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "LifePlatform/SiteApi",
                        "Dimensions": [["Endpoint"]],
                        "Metrics": [{"Name": "RateLimitHit", "Unit": "Count"}],
                    }
                ],
            },
            "Endpoint": endpoint,
            "RateLimitHit": 1,
        }
        # sys.stdout.write so CloudWatch EMF parser sees pure JSON without
        # the logger formatter prefix; same reason as site_api_common.py.
        import sys

        sys.stdout.write(_json.dumps(emf) + "\n")
    except Exception:
        pass


def _handle_nudge(event: dict) -> dict:
    """POST /api/nudge — thin entrypoint; logic in the engage split module."""
    return _engage._handle_nudge(event, _g=globals())


def _handle_submit_finding(event: dict) -> dict:
    """POST /api/submit_finding — thin entrypoint; logic in the engage split module."""
    return _engage._handle_submit_finding(event, _g=globals())


def handle_experiment_library() -> dict:
    """GET /api/experiment_library — thin entrypoint; logic in the experiments split module."""
    return _experiments.handle_experiment_library(_g=globals())


_library_ids_cache: tuple = (0.0, frozenset())  # (loaded_at_epoch, ids)


def _valid_library_ids() -> frozenset:
    """Experiment ids from the S3 library, cached 15 min. Votes are validated
    against this set so arbitrary library_ids can't mint unbounded DDB records."""
    global _library_ids_cache
    import time as _time

    loaded_at, ids = _library_ids_cache
    if ids and _time.time() - loaded_at < 900:
        return ids
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        resp = s3_client.get_object(Bucket=bucket, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
        # #2240: a screened-out entry is not votable either — the vote allowlist is
        # derived from the same catalog and must not readmit what the read doors drop.
        ids = frozenset(
            (e.get("id") or "").lower()
            for e in (library.get("experiments") or [])
            if e.get("id") and not (_is_blocked_vice(e.get("name", "")) or _is_blocked_vice(e.get("id", "")))
        )
        _library_ids_cache = (_time.time(), ids)
    except Exception as e:
        logger.warning(f"[experiment_vote] Library allowlist load failed: {e}")
        # Keep serving a stale allowlist if we ever had one; empty set → 503 upstream.
    return _library_ids_cache[1]


def _handle_experiment_vote(event: dict) -> dict:
    """POST /api/experiment_vote — thin entrypoint; logic in the experiments split module."""
    return _experiments._handle_experiment_vote(event, _g=globals())


def _handle_experiment_follow(event: dict) -> dict:
    """POST /api/experiment_follow — thin entrypoint; logic in the experiments split module."""
    return _experiments._handle_experiment_follow(event, _g=globals())


def _handle_experiment_detail(event: dict) -> dict:
    """GET /api/experiment_detail?id=post-dinner-walk — thin entrypoint; logic in the experiments split module."""
    return _experiments._handle_experiment_detail(event, _g=globals())


def _handle_challenge_vote(event: dict) -> dict:
    """POST /api/challenge_vote — thin entrypoint; logic in the challenges split module."""
    return _challenges._handle_challenge_vote(event, _g=globals())


def _handle_challenge_follow(event: dict) -> dict:
    """POST /api/challenge_follow — thin entrypoint; logic in the challenges split module."""
    return _challenges._handle_challenge_follow(event, _g=globals())


def handle_challenge_catalog() -> dict:
    """GET /api/challenge_catalog — thin entrypoint; logic in the challenges split module."""
    return _challenges.handle_challenge_catalog(_g=globals())


# ── #2238: the check-in `note` screen ────────────────────────────────────────
# `note` is the only reader-supplied FREE TEXT in this module that reaches a
# public payload. It is captured by an anonymous POST (_handle_challenge_checkin),
# stored inside the challenge row's `daily_checkins`, and `handle_challenges`
# publishes that row WHOLE on GET /api/challenges. Until #2238 it was only
# length-capped: no HTML strip (unlike _handle_submit_finding / _handle_board_question,
# which both run the same re.sub) and no blocked-vice screen (unlike this module's
# challenge name/id filters). A stored `<script>` tag and blocked-vice vocabulary
# both came back verbatim to every reader of /protocols.
#
# Screened on BOTH sides deliberately: the write door rejects loudly (400, the
# _handle_board_question precedent) so the submitter is told, and the read door
# re-screens because rows written before this landed are still in the table and
# no backfill touches Matthew's own challenge records.


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _sanitise_text(raw, cap: int = 500) -> str:
    """HTML-strip + length-cap one reader-supplied free-text field — the treatment
    every capture door in this module gives its text (`finding` 500, `metric_a/b`
    100, `question` 500, `note` 500, `idea`/`source` 500)."""
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return ""
    return re.sub(r"<[^>]+>", "", str(raw)).strip()[:cap]


def handle_challenges() -> dict:
    """GET /api/challenges — thin entrypoint; logic in the challenges split module."""
    return _challenges.handle_challenges(_g=globals())


def _handle_challenge_checkin(event: dict) -> dict:
    """POST /api/challenge_checkin — thin entrypoint; logic in the challenges split module."""
    return _challenges._handle_challenge_checkin(event, _g=globals())


# ── #769 (ADR-124): evening-ritual one-tap write path ──────────────────────────
# The C floor of the fulfillment capture channel — the evening nudge mints two
# tappable links (connection 0-4, mood valence 0-4); tapping one hits this GET
# endpoint directly from the email client, no app-switching, no free text.

_RITUAL_TOKEN_SECRET_NAME = os.environ.get("RITUAL_TOKEN_SECRET_NAME", "life-platform/ritual-token-secret")
_ritual_token_secret_cache = None
RITUAL_LOG_RATE_LIMIT = 20  # per IP per hour — generous (legitimate re-taps happen), still floods-abuse-proof


def _get_ritual_token_secret() -> str:
    """Fetch the dedicated ritual-link HMAC secret from Secrets Manager.

    Same shape as `_get_token_secret` (subscriber tokens): a dedicated random
    key, never derived from another credential, so its compromise/rotation is
    isolated from every other signed surface.
    """
    global _ritual_token_secret_cache
    if _ritual_token_secret_cache:
        return _ritual_token_secret_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        _ritual_token_secret_cache = sm.get_secret_value(SecretId=_RITUAL_TOKEN_SECRET_NAME)["SecretString"]
        return _ritual_token_secret_cache
    except Exception as e:
        logger.error(f"[ritual_log] Signing secret unavailable: {e}")
        raise RuntimeError("Ritual token signing secret unavailable") from e


def _handle_ritual_log(event: dict) -> dict:
    """GET /api/ritual_log — thin entrypoint; logic in the engage split module."""
    return _engage._handle_ritual_log(event, _g=globals())


def _handle_experiment_suggest(event: dict) -> dict:
    """POST /api/experiment_suggest — thin entrypoint; logic in the experiments split module."""
    return _experiments._handle_experiment_suggest(event, _g=globals())


# ─────────────────────────────────────────────────────────────────────────────
# Reader engagement loop — "predict the week" + "ask the board".
# Both reuse the existing sanctioned write surface (atomic VOTES# counters with a
# per-IP dedup row; S3 capture for Matthew to moderate). No new AI is called here:
# "ask the board" only CAPTURES a question — the answer reuses the already-gated
# /api/board_ask. The predict-week DDB writes need no IAM change (the site_api role
# already writes the table unconditionally); the board-question S3 write needs
# generated/board_questions/* added to the role (one additive line).
# ─────────────────────────────────────────────────────────────────────────────

_PREDICT_CHOICES = {"up", "down", "flat"}
BOARD_QUESTION_RATE_LIMIT = 3  # per IP per hour


def _current_iso_week() -> str:
    """The reader's current ISO week id (e.g. '2026-W29'), computed in Pacific Time.

    The site renders every user-facing date in PT, so 'this week' — the window the
    predict-the-week widget invites bets on — rolls over on the reader's Monday,
    not UTC's.
    """
    iso = datetime.now(PT).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _predict_subject():
    """The current week's prediction subject from current_challenge.json, or None.

    Returns {"week_id", "metrics": {key: label}, "result": {...}|None} when the
    weekly challenge defines a `predict_metrics` list AND its week_id is the
    current ISO week; None otherwise, so the feature fails *closed* — the widget
    doesn't render and POSTs are rejected when there's no active subject. Read
    fresh (no module cache) so a new Monday challenge is picked up without waiting
    for a cold start.
    """
    try:
        s3 = boto3.client("s3", region_name=S3_REGION)
        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        data = json.loads(s3.get_object(Bucket=bucket, Key="site/config/current_challenge.json")["Body"].read())
    except Exception:
        return None
    metrics = data.get("predict_metrics") or []
    week_id = (data.get("week_id") or data.get("id") or "").strip()
    mmap = {}
    for m in metrics:
        k = (m.get("key") or "").strip().lower()
        if k:
            mmap[k] = m.get("label") or k
    if not week_id or not mmap:
        return None
    # #1198 — fail closed on a stale week. current_challenge.json is a MANUAL,
    # per-week S3 artifact (no lambda writes it); if a Monday passes without a
    # re-seed, or a cycle reset leaves the outgoing cycle's frozen week live, its
    # week_id lags the real ISO week. Serving it would solicit predictions on a
    # window that already closed — votes land in a VOTES#predict_week bucket that
    # can never be revealed. Refuse: callers already treat None as "no active
    # subject" (the widget self-hides, POSTs 404).
    current = _current_iso_week()
    if week_id != current:
        logger.warning("[predict_week] stale subject week_id=%r != current ISO week %r; failing closed", week_id, current)
        return None
    return {"week_id": week_id, "metrics": mmap, "result": data.get("result")}


def _handle_predict_week(event: dict) -> dict:
    """POST /api/predict_week — thin entrypoint; logic in the engage split module."""
    return _engage._handle_predict_week(event, _g=globals())


def handle_predict_week_tally(event: dict) -> dict:
    """GET /api/predict_week — thin entrypoint; logic in the engage split module."""
    return _engage.handle_predict_week_tally(event, _g=globals())


def _handle_board_question(event: dict) -> dict:
    """POST /api/board_question — thin entrypoint; logic in the engage split module."""
    return _engage._handle_board_question(event, _g=globals())


# ═══════════════════════════════════════════════════════════════════════════════
# The Social Membrane — the Broadcast feed (#1672, epic #1668, story S4)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/broadcast — the read-only source for /story/broadcast/, the site's
# canonical home for Matthew's own public voice. Reverse-chron facade cards
# (thumbnail + caption + link-out) of the ingested social posts (#1669/#1670),
# filtered to the CLEARED, human-origin set. Modeled on handle_journey_timeline:
# read-only, aggregate-only, fail-soft, one _ok() envelope.

# The ingested-post partitions (#1669, extended #1676). All three are dormant until the
# owner provisions their respective identity (channel id / handle / instance+handle); as
# more inbound channels land they append here and the feed picks them up with no other
# change. pk = USER#matthew#SOURCE#<source>, sk = DATE#<date>#<post_id>, one row per post
# (youtube_lambda / bluesky_lambda / mastodon_lambda .transform — same shape).
_BROADCAST_SOURCES = ("youtube", "bluesky", "mastodon")
_BROADCAST_LIMIT = 60  # newest N cleared posts; the feed is a voice highlight, not an archive

# ── S5 sensitivity gate seam — RECONCILED to #1673 (PR #1701) ────────────────────
# #1672 ships the origin:human feed; #1673 lands the FAIL-CLOSED auto-publish
# sensitivity gate. This is the ONE place the seam composes. Reconciled to #1673's
# ACTUAL contract (its `gate` module): the row attribute is `sensitivity_status`
# (== gate.STATUS_ATTR) and the publishable verdict is the literal "cleared"
# (NOT "clear") — i.e. gate.is_cleared(post). FAIL CLOSED — a missing / "pending" /
# "flagged" / any non-"cleared" status is WITHHELD, so a flagged post is absent from
# the rendered feed (AC) and the feed is honestly empty until #1673 stamps posts.
#
# #1673's `gate` module isn't in this branch yet (unmerged sibling PR #1701), so we
# MIRROR its contract rather than import it. On merge, collapse to the single source
# of truth: `from <gate_module> import is_cleared` and make _is_sensitivity_cleared a
# one-line delegate to it (its helpers: is_cleared / filter_cleared / STATUS_ATTR /
# cleared_filter_expression). The literals below match #1673 exactly.
SENSITIVITY_STATUS_ATTR = "sensitivity_status"  # == #1673 gate.STATUS_ATTR
SENSITIVITY_CLEARED = "cleared"  # == #1673's publishable verdict (gate.is_cleared)


def _is_sensitivity_cleared(post: dict) -> bool:
    """FAIL-CLOSED mirror of #1673 gate.is_cleared: only sensitivity_status == "cleared" publishes."""
    return (post or {}).get(SENSITIVITY_STATUS_ATTR) == SENSITIVITY_CLEARED


def _is_broadcast_visible(post: dict) -> bool:
    """The ONE membrane predicate for the broadcast feed — kept in a single place so
    #1673's real gate reconciles trivially:

      S2 (#1670) origin:human  AND  S5 (#1673) sensitivity-clear (fail-closed).

    origin:human treats an UNSTAMPED row as human (membrane default, #1670); the
    sensitivity gate is the opposite posture — unstamped is NOT cleared — because a
    post no gate has vetted must never auto-publish.
    """
    return social_provenance.is_displayable_voice(post) and _is_sensitivity_cleared(post)


def _broadcast_card(post: dict) -> dict:
    """Reduce an ingested-post DDB row to a facade card (thumbnail + caption + link).

    A FACADE by design (#1672): a link-out to where the post lives, never a
    third-party iframe — so the feed needs zero CSP change (img-src already allows
    any HTTPS thumbnail). Native players are a later story (S10)."""
    pid = str(post.get("post_id") or post.get("sk", "").split("#")[-1] or "")
    return {
        "id": pid,
        "date": post.get("date") or str(post.get("sk", "")).replace("DATE#", "").split("#")[0],
        "channel": post.get("channel", ""),
        "caption": post.get("title", ""),
        "excerpt": post.get("description", ""),
        "thumbnail_url": post.get("thumbnail_url", ""),
        "link_out": post.get("url", ""),  # where the post actually lives (facade target)
        "permalink": f"/story/broadcast/#{pid}" if pid else "/story/broadcast/",
    }


def _membrane_source_rows() -> list:
    """Every ingested-post row (#1669), UNGATED — the raw read behind the membrane.

    Split out of _membrane_visible_rows (#1679) because the membrane dashboard has to
    report on what the gate REJECTED (how many platform-origin echoes it kept out),
    which is unanswerable from the post-gate set. Everything reader-facing still goes
    through _membrane_visible_rows below; this function is the shared QUERY, never a
    second gate. Fail-soft per source (a query error on one channel never breaks a
    feed). Newest-first within each source; callers merging sources re-sort."""
    rows: list = []
    for source in _BROADCAST_SOURCES:
        pk = f"{USER_PREFIX}{source}"
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                ScanIndexForward=False,  # newest-first
            )
            rows.extend(_decimal_to_float(resp.get("Items", [])))
        except Exception as e:  # noqa: BLE001 — one bad channel must not break the feed
            logger.warning("[site_api] social membrane: source %s query failed (non-fatal): %s", source, e)
    return rows


def _membrane_visible_rows() -> list:
    """The ingested-post rows that pass the ONE membrane predicate (origin:human +
    sensitivity-clear, fail-closed). Shared by /api/broadcast (#1672),
    /api/social_context (#1674) and /api/membrane (#1679) so there's exactly one
    query + one gate, never copies drifting apart."""
    return [r for r in _membrane_source_rows() if _is_broadcast_visible(r)]


def handle_broadcast() -> dict:
    """GET /api/broadcast — thin entrypoint; logic in the membrane split module."""
    return _membrane.handle_broadcast(_g=globals())


# ═══════════════════════════════════════════════════════════════════════════════
# Contextual social embeds (#1674, epic #1668, story S6)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/social_context?route=training|mind — the SAME cleared, human-origin
# membrane as /api/broadcast (_membrane_visible_rows), narrowed to the posts whose
# ENRICHED content (#1671 social_signals.coach_route_of — the same router the
# training/Mind coach surfaces already read, ai_context._social_posts_by_route)
# routes to the requested surface. A training-flavoured post (exercise_context, or
# a concrete training keyword in its themes/behaviors/entities) surfaces on
# /data/training/; a reflective post surfaces on the Mind pillar (/data/mind/).
#
# Facade cards only — reuses _broadcast_card, so this is a pure narrowing of the
# broadcast feed, never a second card shape. Zero CSP change: no third-party
# iframe, same as #1672. #1678 (native embeds via a scoped frame-src/media-src
# amendment) is a separate, owner-gated security decision — this endpoint stays a
# facade regardless of how that lands.
#
# Only ACTUALLY-ENRICHED posts (enriched_at present) are eligible: an unenriched
# post has no content signal to route on, so classify_coach_route's "mind" default
# would silently misroute a training post that just hasn't been enriched yet. It
# stays in the general /story/broadcast/ feed until enrichment stamps a route.
_CONTEXT_ROUTES = frozenset({"training", "mind"})
_CONTEXT_LIMIT = 6  # a contextual sidebar highlight, not the full archive — see /story/broadcast/ for that


def _handle_social_context(event: dict) -> dict:
    """GET /api/social_context?route=training|mind — thin entrypoint; logic in the membrane split module."""
    return _membrane._handle_social_context(event, _g=globals())


# ═══════════════════════════════════════════════════════════════════════════════
# The bidirectional membrane dashboard (#1679, epic #1668, story S11)
# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/membrane — "what I said, where it went, what came back" in one payload.
# The loop the epic describes has three stages and this endpoint reports each one
# from ITS OWN system of record, never from a derived summary:
#
#   said / went  ← the BROADCAST_ORIGIN# ledger (#1670). One row per post the
#                  platform's outbound syndication path created, keyed by
#                  (channel, post_id). That ledger IS "where it went".
#   came back    ← the SAME _membrane_visible_rows() the Broadcast feed reads.
#                  Not a second query and not a second predicate — the dashboard
#                  cannot disagree with /story/broadcast/ about what is human.
#   the membrane ← the count of ingested rows the origin gate classified as
#                  platform echoes. This is the join the epic asks to be visible:
#                  an echo is displayed as an echo and never counted as inbound.
#
# NO vanity metrics (#1402's no-gloss ethos): no followers, no likes, no reach, no
# impressions. Nothing here is an engagement number — every figure is a count of
# records the platform itself wrote, which is the only thing it can honestly claim.
#
# HONEST ABSENCE (ADR-104). Today every partition below is empty, and "empty" has
# two different meanings that must not be flattened into one 0:
#   * a channel that is not wired yet is `dormant` — the absence of a pipe, not the
#     absence of posting. Derived from the source registry's own `active_api` facet,
#     never hand-stated here (the #2003 drift class).
#   * a channel that IS wired and has no rows is `empty` — a real zero.
# The payload carries the state, and the page renders the two differently.
#
# PRIVACY. Everything published here is already public by construction: outbound
# rows describe posts the platform made in public, and inbound items are exactly the
# membrane-cleared set /story/broadcast/ already serves. The sensitivity gate's HELD
# set is deliberately NOT published — not the content and not the count. Publishing
# "3 held" would disclose that flagged material exists, which is the one thing a
# fail-closed gate is supposed to keep quiet. That is also why no raw ingested total
# is returned: with a total, held would be derivable by subtraction.

# The outbound channels whose ledger partition is queried. Mirrors _BROADCAST_SOURCES
# above: adding a channel appends here and the dashboard picks it up with no other
# change. Kept in sync by hand with the posting surface's own platform list
# (scripts/post_social.py --platform), which is a local operator script the Lambda
# cannot import.
_OUTBOUND_CHANNELS = ("bluesky", "x")
_MEMBRANE_LIMIT = 20  # newest N per side — a legible loop, not an archive


def _inbound_channel_live(source: str) -> bool:
    """Is an inbound channel actually pulling yet? Read from the source registry's own
    `active_api` facet — the canonical place a source's live/dormant state is recorded
    (CLAUDE.md: read the registry, don't hand-state it). A source absent from the
    registry is treated as not live."""
    try:
        return bool((SOURCE_REGISTRY.get(source) or {}).get("active_api"))
    except Exception:  # noqa: BLE001 — a registry read must never break the dashboard
        return False


def handle_membrane() -> dict:
    """GET /api/membrane — thin entrypoint; logic in the membrane split module."""
    return _membrane.handle_membrane(_g=globals())


# ═══════════════════════════════════════════════════════════════════════════════
# The Engagement Ladder (#1393, epic #1366) — Reader → Subscriber → Predictor →
# Replicator → Contributor.
# ═══════════════════════════════════════════════════════════════════════════════
# Participation made legible as rungs. The reader's OWN rung is computed CLIENT-side
# from the EXISTING subscriber HMAC token + localStorage (engagement_ladder.js) — no
# auth system is built, no new identity, no PII stored server-side. This module
# publishes only the PUBLIC, aggregate rung COUNTS, each DERIVED FROM DATA already in
# the system and stamped with a `.provenance` block (never a hand-maintained number).
# Two endpoints:
#   GET  /api/ladder_counts     — read-only public counts + provenance (the only thing
#                                 rendered on the site).
#   POST /api/replicate_certify — a reader self-certifies a completed Replication Kit
#                                 run; a per-source-deduped aggregate counter, no PII.
# SDT note (the design warning the story carries): the streak/participation surface is
# INFORMATION ONLY — never loss-framed, gaps neutral, skippable. That copy lives in
# engagement_ladder.js; the server only reports counts.

# The self-cert Replicator aggregate lives under a VOTES#* pk, so it is already covered
# by the site_api role's LeadingKeys (VOTES#*) — no IAM change. The per-IP dedup rows
# ride the shared VOTES#rate_limit partition, REPL# prefixed.
#
# UNLIKE predict-week's PRED#{ip_hash}#{week}#{metric} rows, REPL# rows carry NO ttl
# (#1825). Predict-week's dedup is intentionally a per-week RATE LIMIT (the TTL window
# is disclosed in its own provenance: "the active window only"); the Replicator rung's
# published provenance instead promises a ONE-TIME EVER cert — "deduped per source", no
# window qualifier. An 8-day TTL row previously made that dedup reset every 8 days, so
# the same source could keep re-certifying and inflating the monotonic cert_count
# counter forever (VOTES# is SYSTEM_STATE — no reset ever corrects it either). Dropping
# the ttl makes the dedup row (and therefore the count) actually match what's published.
_LADDER_REPLICATOR_PK = "VOTES#ladder_replicator"
# The Contributor rung wires to the EXISTING findings moderation path: when Matthew
# verifies + publishes a reader-submitted finding, that path appends it to this single
# index object ({id, credit_opt_in, credit_name} — never an email/identity). The
# site-api has GetObject on generated/* (NOT ListBucket), so it reads this ONE known key
# rather than enumerating the findings queue. Absent/empty ⇒ an honest 0.
_PUBLISHED_FINDINGS_INDEX_KEY = "generated/findings/_published_index.json"


def handle_ladder_counts() -> dict:
    """GET /api/ladder_counts — thin entrypoint; logic in the ladder split module."""
    return _ladder.handle_ladder_counts(_g=globals())


def _handle_replicate_certify(event: dict) -> dict:
    """POST /api/replicate_certify — thin entrypoint; logic in the ladder split module."""
    return _ladder._handle_replicate_certify(event, _g=globals())


# ── #1394 (epic #1366): The Cohort Strip — "where do I sit this week?" ──────────
# A weekly ANONYMOUS distribution of participant-reported single numbers (one
# metric per week) with Matthew's dot marked. One-tap submission reuses this
# module's check-in write class verbatim — the same DynamoDB `table` and the same
# DDB-backed `_ddb_rate_check` that _handle_challenge_checkin uses (no fork, no new
# rate limiter). There is NO free-text field, so there is zero moderation surface.
#
# Structural isolation (the load-bearing privacy invariant): cohort submissions
# live in their OWN partition family, `COHORT#<metric>#<week>` — deliberately NOT a
# `USER#matthew#SOURCE#…` partition. Matthew's stats/calibration pipelines only ever
# query his own `USER#…#SOURCE#…` partitions, so they can never read pooled cohort
# numbers. tests/test_cohort_strip_isolation_1394.py asserts this both directions.
# Matthew's dot on the strip is his own metric value, supplied by the weekly config
# (not read back out of the cohort partition), keeping the two data sets disjoint.
COHORT_PK_PREFIX = "COHORT#"  # the cohort partition family — NEVER a USER#…#SOURCE# key
COHORT_K_FLOOR = 5  # k-anonymity: the strip stays hidden until n ≥ this (a HARD gate, not copy)
COHORT_SUBMIT_WINDOW = 604800  # 1 submission per IP per week (7 days), DDB-backed
COHORT_HIST_BINS = 12  # inline-SVG histogram resolution across the metric's axis
_cohort_config_cache: dict = {}
_cohort_config_cache_ts = 0.0


def _cohort_partition(metric_id: str, week: str) -> str:
    """The one place a cohort pk is minted — `COHORT#<metric>#<week>`.

    Kept literal-prefixed with COHORT_PK_PREFIX so the isolation test can prove no
    stats/calibration module references this family and both handlers only ever
    touch it (never a USER#…#SOURCE# partition).
    """
    return f"{COHORT_PK_PREFIX}{metric_id}#{week}"


def _load_cohort_config() -> dict | None:
    """Load the active weekly cohort metric from S3 config (module-cached).

    Shape (site/config/cohort_week.json):
      {"metric_id": "resting_heart_rate", "label": "Resting heart rate",
       "unit": "bpm", "week": "2026-W30", "matthew_value": 52,
       "axis_min": 40, "axis_max": 90, "lower_is_better": true}

    Absent/malformed → None, which both handlers treat as "no active cohort week"
    (the strip self-hides; submissions 404) — never a fabricated metric.

    Cached for STATUS_CACHE_TTL seconds (matches handle_status's pattern), and
    ONLY once a load actually returns a config — a miss/error is never cached
    (#1821: the prior "cache forever, including the miss" pattern held a warm
    container on `{"active": false}` until recycle, and at week rollover let
    different containers disagree for their whole remaining lifetime about
    which week's partition to write/read, splitting submissions across a dead
    week and a live one).
    """
    global _cohort_config_cache, _cohort_config_cache_ts
    import time as _time

    now_ts = _time.time()
    if not _cohort_config_cache or now_ts - _cohort_config_cache_ts >= STATUS_CACHE_TTL:
        _cohort_config_cache = _load_s3_json("site/config/cohort_week.json", "cohort_week") or {}
        _cohort_config_cache_ts = now_ts
    cfg = _cohort_config_cache
    if not cfg or not cfg.get("metric_id") or not cfg.get("week"):
        return None
    try:
        amin = float(cfg["axis_min"])
        amax = float(cfg["axis_max"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (amax > amin):
        return None
    return cfg


def _handle_cohort_submit(event: dict) -> dict:
    """POST /api/cohort_submit — thin entrypoint; logic in the ladder split module."""
    return _ladder._handle_cohort_submit(event, _g=globals())


def handle_cohort_strip() -> dict:
    """GET /api/cohort_strip — thin entrypoint; logic in the ladder split module."""
    return _ladder.handle_cohort_strip(_g=globals())
