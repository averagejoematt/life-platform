"""
qa_smoke_lambda.py — Life Platform QA Smoke Test

Runs at 10:30 AM PT daily (30 min after the pipeline completes).
Checks data freshness, score sanity, link integrity, and key output files.
Sends a concise email report — green summary if all pass, red alert if anything fails.

Trigger: EventBridge cron(30 18 ? * * *)  (10:30 AM PT = 18:30 UTC)
Handler: qa_smoke_lambda.lambda_handler
Runtime: python3.12, 256 MB, timeout 120s
Env vars: TABLE_NAME, S3_BUCKET, EMAIL_RECIPIENT, EMAIL_SENDER
"""

import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key
from common.mcp_url import resolve_mcp_url  # SEC-02 #780: discover the URL at runtime, not a committed env var

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from common.platform_logger import get_logger

    logger = get_logger("qa-smoke")
except ImportError:
    logger = logging.getLogger("qa-smoke")
    logger.setLevel(logging.INFO)

# Genesis-aware checks (2026-06-08): on the day after an experiment reset, the
# dashboard validates *yesterday*, which is pre-genesis and legitimately has no
# day-grade. A missing grade for a pre-experiment date is expected, not a fault.
try:
    from common.constants import EXPERIMENT_START_DATE
except ImportError:
    EXPERIMENT_START_DATE = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
# #1894/#1225: the weight-truth assessors live in their own module (the size gate
# asks for a cohesive split, not a grandfather entry). Re-exported so
# qa_smoke_lambda.assess_hero_weight stays a valid public entrypoint.
# #1949: the raw-archive liveness check (raw_layout facets must be live-true)
# lives in its own module, same size-split pattern — this file owns the AWS
# clients and the nightly wiring, raw_archive_qa owns the logic.
from operational import (
    raw_archive_qa,  # noqa: E402
    weight_truth_qa,  # noqa: E402
)

# #1921: the result vocabulary (Check + its partitions) and the run's own EMF
# reporting live in operational/qa_check.py — one concern, lifted out when this
# module crossed the 1200-line ceiling. Re-exported so qa_smoke_lambda.Check,
# .emf_summary_line, .PARTITIONS et al. stay valid public entrypoints for the
# existing tests and callers.
from operational.qa_check import (  # noqa: E402,F401
    CONTENT_TRUTH,
    DEPLOY_HEALTH,
    PARTITIONS,
    QA_SMOKE_EMF_NAMESPACE,
    Check,
    emf_summary_line,
    split_warns,
)

# #1665 (2026-08-02): the five AWS-surface sweeps (S3 freshness, score sanity,
# blog links, Lambda secrets, avatar sprites) live in operational/qa_check_outputs.py
# — extracted when concurrent merges pushed this module back over the 1200-line
# ceiling. Re-exported so qa_smoke_lambda.check_* stay valid public entrypoints.
from operational.qa_check_outputs import (  # noqa: E402,F401
    check_avatar_assets,
    check_blog_links,
    check_lambda_secrets,
    check_s3_freshness,
    check_score_sanity,
)
from operational.weight_truth_qa import WEIGHT_RECONCILE_TOL, assess_hero_weight  # noqa: E402,F401

S3_BUCKET = os.environ["S3_BUCKET"]
RECIPIENT = os.environ["EMAIL_RECIPIENT"]
SENDER = os.environ["EMAIL_SENDER"]
USER_PREFIX = "USER#matthew#SOURCE#"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)
MCP_SECRET_NAME = os.environ.get("MCP_SECRET_NAME", "life-platform/mcp-api-key")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pt_now():
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Los_Angeles"))  # DST-aware (fixed -8 was PST year-round)


def yesterday_str():
    return (pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CHECK 1 — DynamoDB data freshness
# ---------------------------------------------------------------------------


def check_ddb_freshness():
    yesterday = yesterday_str()
    checks = []

    # REQUIRED = sources that write a record EVERY day. A missing record here is
    # a real ingestion failure. 2026-05-28 recalibration: only genuinely-daily
    # sources stay required. macrofactor removed (MacroFactor Tier 1 torn down —
    # dead since 2026-04-11). withings (weigh-ins) and strava (workouts) demoted
    # to OPTIONAL: they're event-driven, so a missing day is normal, not a fault
    # (Garmin already covers daily steps/activity). This was the source of the
    # chronic "🔴 QA: 3 failures" emails.
    # #498 (X-10): the three tiers derive from the registry's qa_tier + paused
    # facets — this list previously drifted twice (strava sat mislabeled "paused
    # (API 402)" for two weeks; the phantom "journal" partition was checked
    # instead of notion). Tier semantics unchanged: REQUIRED missing = FAIL,
    # OPTIONAL missing = warn, PAUSED = ⏸ never a fault.
    from ingestion.source_registry import qa_optional, qa_paused, qa_required

    REQUIRED = qa_required()
    OPTIONAL = qa_optional()
    PAUSED = qa_paused()

    for source, label in REQUIRED:
        c = Check(f"DDB:{source}", "Data Freshness", CONTENT_TRUTH)
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            c.ok(f"{label} record found for {yesterday}") if item else c.fail(f"{label} — no record for {yesterday}")
        except Exception as e:
            c.fail(f"{label} — DDB error: {e}")
        checks.append(c)

    for source, label in OPTIONAL:
        c = Check(f"DDB:{source}", "Data Freshness", CONTENT_TRUTH)
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            # #1958: a missing day on an OPTIONAL (event-driven/manual) source is
            # the definition of the chronic timing class — it recurs on a healthy
            # platform, so it must not hold the qa-smoke-warnings alarm red.
            # `chronic` derives from the registry's qa_tier facet (this whole
            # branch only runs for qa_optional() sources), never a name list.
            # A DDB ERROR on the same source is NOT chronic: that's a real,
            # novel fault and stays on the alarmed side below.
            c.ok(f"{label} found") if item else c.warn(f"{label} — no record (optional)", chronic=True)
        except Exception as e:
            c.warn(f"{label} — error: {e}")
        checks.append(c)

    for source, note in PAUSED:
        checks.append(Check(f"DDB:{source}", "Data Freshness", CONTENT_TRUTH).pause(note))

    return checks


# ---------------------------------------------------------------------------
# CHECK 1b — HAE days-dark truth (#2001)
# ---------------------------------------------------------------------------
# The D-4/#468 honesty surface exists to say "dark N days" — but the liveness
# scan's newest-N window used to LOSE the number exactly when the lapse was
# longest (BP ~114d / SoM ~122d rendered unnumbered while in-window lapses
# carried numbers). The checker now deep-scans past its window; this guard
# asserts the contract holds: any dark datatype whose partition holds ANY
# historical record for its fields must carry a numeric age. Unnumbered dark is
# only honest when the partition truly has nothing inside the deep horizon.


def _hae_record_exists_within(fields, floor_date, max_pages=10):
    """True if any apple_health DATE# record in [floor_date, now] carries any of
    `fields` non-None. Bounded newest-first filtered pagination — read-only."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":pk": USER_PREFIX + "apple_health", ":lo": f"DATE#{floor_date}", ":hi": "DATE#~"},
        "FilterExpression": " OR ".join(f"attribute_exists({f})" for f in fields),
        "ScanIndexForward": False,
        "ProjectionExpression": "sk, " + ", ".join(fields),
    }
    for _ in range(max_pages):
        resp = table.query(**kwargs)
        if any(any(it.get(f) is not None for f in fields) for it in resp.get("Items", [])):
            return True
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return False
        kwargs["ExclusiveStartKey"] = lek
    return False


def check_hae_liveness_truth():
    """#2001: a dark:true HAE datatype with days_dark null while its partition
    holds a findable historical record = the honesty surface lost its number."""
    c = Check("HAE:days-dark-truth", "Data Freshness", CONTENT_TRUTH)
    try:
        from emails.freshness_checker_lambda import HAE_LIVENESS_MAX_LOOKBACK_DAYS as _lookback
    except Exception:  # packaging drift — fall back to the checker's env-var default
        _lookback = int(os.environ.get("HAE_LIVENESS_MAX_LOOKBACK_DAYS", "400"))
    try:
        from ingestion.source_registry import hae_datatype_thresholds

        sent = table.get_item(Key={"pk": USER_PREFIX + "apple_health", "sk": "DATATYPE_LIVENESS"}).get("Item")
    except Exception as e:
        return [c.warn(f"HAE liveness sentinel read failed: {e}")]
    if not sent:
        return [c.warn("no DATATYPE_LIVENESS sentinel yet (freshness checker has not run)")]
    fields_by_key = {d["key"]: d["fields"] for d in hae_datatype_thresholds()}
    floor_date = (pt_now().date() - timedelta(days=_lookback)).isoformat()
    violations = []
    for d in sent.get("datatypes", []):
        if not d.get("dark") or d.get("age_days") is not None:
            continue  # numbered dark (or not dark) — honest
        fields = fields_by_key.get(str(d.get("key")), [])
        try:
            if fields and _hae_record_exists_within(fields, floor_date):
                violations.append(str(d.get("key")))
        except Exception as e:
            logger.warning("HAE days-dark truth probe failed for %s: %s", d.get("key"), e)
    if violations:
        return [
            c.fail(
                f"dark datatype(s) {', '.join(sorted(violations))} render days_dark:null while the partition holds a "
                f"findable record within {_lookback}d — the liveness scan lost the 'dark N days' number (#2001)"
            )
        ]
    return [c.ok("every dark HAE datatype carries a numeric days_dark (or truly has no record in the deep horizon)")]


# ---------------------------------------------------------------------------
# CHECK 7 — MCP integration: 2 tool calls + cache warm verification
# ---------------------------------------------------------------------------


def check_mcp_tool_calls():
    """
    Three sub-checks:
    a) get_sources        → ≥10 sources listed  (auth + DDB read path)
    b) get_task_load_summary → has active/overdue keys  (compute path)
    c) DDB cache warm     → CACHE#matthew has ≥10 TOOL# entries  (nightly warmer ran)
    """
    checks = []

    mcp_function_url = resolve_mcp_url()
    if not mcp_function_url:
        return [Check("mcp:config", "MCP Integration", DEPLOY_HEALTH).warn("MCP Function URL unresolved — skipping")]

    # Fetch MCP API key
    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        api_key = sm.get_secret_value(SecretId=MCP_SECRET_NAME)["SecretString"]
    except Exception as e:
        return [Check("mcp:auth", "MCP Integration", DEPLOY_HEALTH).fail(f"Cannot fetch MCP API key: {e}")]

    # 2026-05-03: MCP Function URL uses Bearer auth (HMAC-derived from api_key),
    # not x-api-key. Compute the deterministic Bearer token the same way the MCP
    # handler does — see mcp/handler.py::_get_bearer_token. Note `lp_` prefix.
    _sig = hmac.new(api_key.encode(), b"life-platform-bearer-v1", hashlib.sha256).hexdigest()
    bearer_token = f"lp_{_sig}"

    def _mcp_call(tool_name, arguments):
        """Single MCP tools/call. Returns (ok: bool, data_or_error_str)."""
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": f"qa-{tool_name}",
                "params": {"name": tool_name, "arguments": arguments},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            mcp_function_url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer_token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read().decode("utf-8"))
            if "error" in body:
                return False, f"RPC error: {body['error']}"
            content = body.get("result", {}).get("content", [])
            if not content:
                return False, "Empty result content"
            return True, json.loads(content[0].get("text", "{}"))
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return False, str(e)

    # a) get_sources
    c = Check("mcp:get_sources", "MCP Integration", DEPLOY_HEALTH)
    ok, data = _mcp_call("get_sources", {})
    if not ok:
        c.fail(f"get_sources failed: {data}")
    else:
        sources = data.get("sources", data) if isinstance(data, dict) else data
        n = len(sources) if isinstance(sources, (list, dict)) else 0
        if n >= 10:
            c.ok(f"{n} sources available")
        else:
            c.fail(f"Only {n} sources returned (expected ≥10) — DDB may be unreadable")
    checks.append(c)

    # b) get_todoist_snapshot (dispatcher) — verifies SIMP-1 dispatcher routing is live
    c = Check("mcp:get_todoist_snapshot", "MCP Integration", DEPLOY_HEALTH)
    ok, data = _mcp_call("get_todoist_snapshot", {"view": "load"})
    if not ok:
        c.fail(f"get_todoist_snapshot dispatcher failed: {data}")
    elif isinstance(data, dict) and ("active" in data or "active_count" in data or "error" not in data):
        active = data.get("active", data.get("active_count", "?"))
        overdue = data.get("overdue", data.get("overdue_count", "?"))
        c.ok(f"dispatcher routed ok — {active} active tasks, {overdue} overdue")
    else:
        c.warn(f"Unexpected dispatcher response: {str(data)[:120]}")
    checks.append(c)

    # c) Cache warm — query CACHE#matthew / TOOL#* entries
    c = Check("mcp:cache_warm", "MCP Integration", DEPLOY_HEALTH)
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("CACHE#matthew") & Key("sk").begins_with("TOOL#"),
            Select="COUNT",
        )
        n = resp.get("Count", 0)
        if n >= 10:
            c.ok(f"Cache has {n} warm entries")
        elif n >= 1:
            # #1958: a partially-warm cache recurs by timing (the warmer's cadence
            # vs this 10:30 PT sweep) — chronic, kept out of the alarmed WarnCount.
            # A fully EMPTY cache stays a FAIL: that means the warmer never ran.
            c.warn(f"Cache has only {n} entries — warmer may have partially failed", chronic=True)
        else:
            c.fail("Cache empty — nightly warmer has not run or failed entirely")
    except Exception as e:
        c.fail(f"Cache query error: {e}")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 8 — Reader Truth (#1096): phase-aware narrative-truth QA, nightly
# ---------------------------------------------------------------------------
# Extracted to operational/qa_check_reader_truth.py (#1665 module-size ceiling,
# crossed when #1922 added the deterministic phase-plausibility pass). Re-exported
# here so the handler below and every existing importer keep the same entrypoint.
from operational.qa_check_reader_truth import (  # noqa: F401,E402
    SITE_BASE_URL,  # used by four other checks in this module
    check_reader_truth,  # re-export: the handler's entrypoint
)

# ---------------------------------------------------------------------------
# CHECK 9 — Predict-the-week freshness (#1198)
# ---------------------------------------------------------------------------
# The cockpit's predict-the-week widget solicits votes on "this week." Its subject
# is a MANUAL, per-week S3 artifact (site/config/current_challenge.json) that no
# lambda refreshes — if a Monday passes without a re-seed, or a cycle reset leaves
# the outgoing cycle's week live, the widget keeps taking bets on a window that
# already closed (votes land in a bucket that can never be revealed). The site-api
# now fails closed on that mismatch (_predict_subject), so /api/predict_week must
# report active:false the moment the subject goes stale. This nightly tripwire
# catches a REGRESSION of that guard: if the API ever returns active:true with a
# week_id that isn't the current PT ISO week, fail loudly — it fires the Monday a
# subject goes stale, before a reader can bet on a dead week.
#
# #1953: the INVERSE blind spot — active:false used to be unconditionally ok, so
# the widget being dark for 6 consecutive days of a fresh cycle produced 6 green
# nightlies (the third "off state printed as green" of the season, after
# reader_truth #1920/ADR-147 and the leak sweep #1931). The check now
# distinguishes three states:
#   (a) active on the current ISO week            -> ok
#   (b) fail-closed with NO live cycle running    -> ok (pre-genesis countdown —
#       dark is the honest state; live-cycle awareness derives from
#       EXPERIMENT_START_DATE, same as the genesis-grace checks above)
#   (c) DARK during a live-cycle week             -> WARN on the first dark day,
#       escalating to a content_truth FAIL at >= 2 consecutive dark days
# The consecutive-day streak persists in one DDB state row
# (SOURCE#qa_predict_dark / STATE#predict_dark — same single-row snapshot
# pattern as pipeline_health_check's ingest_liveness; SYSTEM_STATE in the phase
# taxonomy). Streak bookkeeping is fail-soft: a DDB blip degrades to the
# single-day WARN, never a crash, never a phantom FAIL — and never a green.

_PREDICT_DARK_SK = "STATE#predict_dark"
# Consecutive dark live-cycle days before the WARN escalates to a FAIL (#1953).
PREDICT_DARK_FAIL_DAYS = 2


def _live_cycle_today(today):
    """True when an experiment cycle is live on `today` (a PT date): genesis is
    known and has arrived. Pre-genesis (the countdown) or no genesis constant at
    all = no live cycle, so a dark predict widget is the honest fail-closed state."""
    if not EXPERIMENT_START_DATE:
        return False
    try:
        return today >= date.fromisoformat(EXPERIMENT_START_DATE)
    except ValueError:
        return False


def _advance_predict_dark_streak(today):
    """Read + advance the consecutive-dark-day counter for tonight's run.

    Idempotent per PT day (a same-day re-invoke keeps the stored streak), continues
    only from exactly yesterday (a live day in between restarts at 1), and is
    Decimal-safe: the streak round-trips as int (DDB Numbers read back as Decimal),
    never float. Fail-soft on any DDB error: returns 1 — tonight's observation
    alone — so a missing grant or table blip yields the WARN, not a crash.
    """
    today_s = today.strftime("%Y-%m-%d")
    yesterday_s = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = 1
    try:
        prev = table.get_item(Key={"pk": USER_PREFIX + "qa_predict_dark", "sk": _PREDICT_DARK_SK}).get("Item") or {}
        last_dark = str(prev.get("last_dark_date") or "")
        prev_streak = int(prev.get("streak") or 0)
        if last_dark == today_s:
            streak = max(prev_streak, 1)  # re-run tonight: don't double-count the day
        elif last_dark == yesterday_s:
            streak = prev_streak + 1
    except Exception as e:  # noqa: BLE001 — streak read must never break the sweep
        print(f"[QA] predict-dark streak read failed (fail-soft, counting tonight only): {str(e)[:120]}")
    try:
        table.put_item(
            Item={
                "pk": USER_PREFIX + "qa_predict_dark",
                "sk": _PREDICT_DARK_SK,
                "last_dark_date": today_s,
                "streak": streak,  # int — Decimal-safe for DDB (never float)
                "updated_at": pt_now().isoformat(),
            }
        )
    except Exception as e:  # noqa: BLE001 — streak write must never break the sweep
        print(f"[QA] predict-dark streak write failed (fail-soft): {str(e)[:120]}")
    return streak


def check_receipt_replay():
    """#1373: progression-receipt drift alarm (nightly leg).

    Replays the last 7 stored character_receipt records through the LIVE
    bundled engine + the LIVE S3 config:
      - a mismatch with UNCHANGED config hash + engine version = real
        nondeterminism (or a tampered receipt) → RED (the drift alarm);
      - config/engine changed since a receipt was written → YELLOW (expected
        exactly once after a deliberate change; new receipts re-baseline on
        the next compute);
      - all digests reproduce → green.
    No receipts at all is YELLOW until the first post-#1373 compute lands.
    """
    c = Check("character:receipt_replay", "Character Receipts", DEPLOY_HEALTH)
    try:
        from health import character_engine, progression_receipts as pr

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(USER_PREFIX + "character_receipt") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=7,
        )
        items = [it for it in resp.get("Items", []) if not it.get("tombstone")]
        if not items:
            c.warn("no progression receipts stored yet — the first one lands on the next character-sheet compute (#1373)")
            return [c]
        config = character_engine.load_character_config(s3, S3_BUCKET)
        if not config:
            c.warn("character config unavailable from S3 — replay skipped this run")
            return [c]
        # #1412: replay against the SAME effective config the nightly compute
        # hashed into the receipt (personal-variance targets overlaid) — the raw
        # S3 config alone would read as permanent unlabeled config drift.
        from health import personal_baselines

        config = personal_baselines.effective_character_config(config, table, USER_PREFIX)
        drifted, mismatched = [], []
        for it in items:
            date = str(it.get("date") or it.get("sk", "")).replace("DATE#", "")[:10]
            verdict = pr.replay(it, config, engine=character_engine)
            if verdict["verified"]:
                continue
            if verdict["config_drift"] or verdict["engine_drift"]:
                drifted.append(date)
            else:
                mismatched.append(date)
        if mismatched:
            c.fail(
                f"replay MISMATCH with unchanged config+engine on {mismatched} — deterministic replay no longer "
                f"reproduces the stored digest; the progression math cannot be trusted until this is explained (#1373)"
            )
        elif drifted:
            c.warn(
                f"config/engine changed since receipt(s) {drifted} were written — expected once after a deliberate "
                f"change; nightly computes re-baseline going forward"
            )
        else:
            c.ok(f"{len(items)} receipt(s) replay clean against the live engine + config")
    except Exception as e:
        c.warn(f"receipt replay check errored: {e}")
    return [c]


def _iso_week_id(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def check_predict_week_freshness():
    check = Check("predict_week:freshness", "Predict-the-Week Freshness", CONTENT_TRUTH)
    url = SITE_BASE_URL + "/api/predict_week"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "life-platform-qa-smoke"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # Fail-soft: a fetch/parse blip must never red the nightly.
        return [check.warn(f"/api/predict_week fetch failed (fail-soft): {str(e)[:120]}")]
    if not data.get("active"):
        today = pt_now().date()
        if not _live_cycle_today(today):
            return [check.ok("no active prediction subject (fail-closed) — no live cycle running, no stale bets solicited")]
        # #1953: a cycle is LIVE, so a subject SHOULD exist — dark is a defect,
        # not the fail-closed happy path. WARN day 1, FAIL at >= 2 consecutive days.
        streak = _advance_predict_dark_streak(today)
        if streak >= PREDICT_DARK_FAIL_DAYS:
            return [
                check.fail(
                    f"predict-the-week is DARK during a live-cycle week: no active subject for {streak} consecutive "
                    f"days while cycle day {today.isoformat()} (genesis {EXPERIMENT_START_DATE}) is live — the primary "
                    "reader-participation hook is invisible (re-seed site/config/current_challenge.json; #1953)"
                )
            ]
        return [
            check.warn(
                f"predict-the-week is DARK during a live-cycle week (day {streak} of the dark streak) — no active "
                f"subject on {today.isoformat()} with genesis {EXPERIMENT_START_DATE} live; escalates to FAIL at "
                f"{PREDICT_DARK_FAIL_DAYS} consecutive dark days (re-seed site/config/current_challenge.json; #1953)"
            )
        ]
    week_id = (data.get("week_id") or "").strip()
    current = _iso_week_id(pt_now())
    if week_id != current:
        return [
            check.fail(
                f"predict-the-week is LIVE on a stale week: /api/predict_week week_id={week_id!r} "
                f"!= current ISO week {current!r} — readers are betting on a window that already "
                "closed (re-seed or clear current_challenge.json; #1198)"
            )
        ]
    return [check.ok(f"active subject on the current ISO week ({current})")]


# ---------------------------------------------------------------------------
# CHECK 10 — Hero weight arithmetic reconciliation (#1225)
# ---------------------------------------------------------------------------
# The home hero's first data claim must survive mental arithmetic: the displayed
# "now" weight minus the displayed "start" weight has to equal the displayed
# delta, on the SAME rounded values a reader sees. A prior bug rounded the shown
# weight to an int (316) while computing the delta off the raw 315.6, so the stat
# row read "316 at last weigh-in · start 314 · 1.6 up" and 316 − 314 = 2 ≠ 1.6.
# It also enforces the trend-honesty contract: an "in N days" trend claim (rendered
# by story.js) is only emitted with >= 2 weigh-ins, so /api/journey must carry a
# weighin_count and a single weigh-in must span 0 days (no multi-day trend off one
# reading — ADR-105). Pure assessor so it's unit-testable offline.

# assess_hero_weight + WEIGHT_RECONCILE_TOL now live in operational/weight_truth_qa
# (re-exported at import for the existing public surface).


def check_hero_weight_arithmetic():
    check = Check("hero_weight:arithmetic", "Reader Truth", CONTENT_TRUTH)
    url = SITE_BASE_URL + "/api/journey"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "life-platform-qa-smoke"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # Fail-soft: a fetch/parse blip must never red the nightly.
        return [check.warn(f"/api/journey fetch failed (fail-soft): {str(e)[:120]}")]
    journey = data.get("journey", data) if isinstance(data, dict) else {}
    ok, msg = assess_hero_weight(journey)
    return [check.ok(msg) if ok else check.fail(msg)]


# ---------------------------------------------------------------------------
# CHECK 10b — Coach labs truth (#1993)
# ---------------------------------------------------------------------------
# A served coach card must never narrate an empty labs store ("zero results …
# a total sync failure") while /api/labs serves real draws. Lives in
# operational/qa_check_coach_labs.py (the module-size ceiling split idiom,
# #1665/#1944); re-exported here so qa_smoke_lambda.check_coach_labs_truth and
# .assess_coach_labs_truth are valid public entrypoints for tests and callers.
from operational.qa_check_coach_labs import (  # noqa: F401,E402
    assess_coach_labs_truth,
    check_coach_labs_truth,
)

# ---------------------------------------------------------------------------
# CHECK 10c — Content cadence next-installment guard (#1972)
# ---------------------------------------------------------------------------
# The chronicle/podcast list pages must carry either a next-date line or an
# explicit honest-pending line — never neither. Purely deterministic (no
# LLM/Bedrock), so it never pauses under the budget ladder. Lives in
# operational/qa_check_content_cadence.py (the module-size ceiling split
# idiom, #1665/#1944/#1993); re-exported here so qa_smoke_lambda.check_content_cadence
# and .assess_content_cadence are valid public entrypoints for tests and callers.
from operational.qa_check_content_cadence import (  # noqa: F401,E402
    assess_content_cadence,
    check_content_cadence,
)

# ---------------------------------------------------------------------------
# CHECK 10d — Subscriber promise <-> kill-switch agreement (#1951)
# ---------------------------------------------------------------------------
# /subscribe/ and the confirmation email promise a weekly send unconditionally;
# delivery is gated behind each subscriber-facing sender's EXTERNAL_EMAILS_ENABLED
# env var. FAILS when the page is live-soliciting AND confirmed subscribers > 0
# AND any subscriber-facing weekly sender is not enabled — the growth-1 class
# (docs/reviews/FULLREVIEW_2026-08-02_DELTA.md) where the switch was pinned off
# for ~3 months with nothing coupling it to the live promise. Lives in
# operational/qa_check_subscriber_promise.py (module-size ceiling split idiom,
# #1665/#1944/#1972/#1993); re-exported here so qa_smoke_lambda.check_subscriber_promise_truth
# and .assess_subscriber_promise_truth are valid public entrypoints for tests and callers.
from operational.qa_check_subscriber_promise import (  # noqa: F401,E402
    assess_subscriber_promise_truth,
    check_subscriber_promise_truth,
)

# ---------------------------------------------------------------------------
# CHECK 11 — Legacy redirect spot-check (#1430)
# ---------------------------------------------------------------------------
# 84 legacy pages 301 via the CloudFront v4-redirects function, generated 1:1
# from redirects.map — nothing continuously verified those redirects still
# resolve correctly, so a CloudFront function edit or a redirects.map drift
# could silently rot old-URL link equity and reader bookmarks. Sampling
# design (deterministic per-week bucket, full-map rotation, no-redirect-
# follow HTTP verification) lives in lambdas/redirect_spotcheck.py — pure and
# unit-tested offline; this Check just wires it to the WEEKLY cadence the
# issue asks for (a rotating ~1/N_BUCKETS slice every night would hammer the
# edge for no benefit — one pass a week, deterministically bucketed by ISO
# week number, still covers the whole map in ~N_BUCKETS weeks (~1 month)).
# On non-scheduled nights this reports an explicit paused line — visible,
# never silently skipped.

REDIRECT_SPOTCHECK_WEEKDAY = 0  # Monday (datetime.weekday(): Mon=0 .. Sun=6)


def check_redirect_spotcheck():
    check = Check("redirect_spotcheck:sample", "Legacy Redirects", CONTENT_TRUTH)
    now = pt_now()
    if now.weekday() != REDIRECT_SPOTCHECK_WEEKDAY:
        return [check.pause(f"redirect spot-check runs Mondays — skipped ({now.strftime('%A')} PT); rotates over ~1 month")]

    try:
        from operational import redirect_spotcheck

        iso_week = now.isocalendar()[1]
        result = redirect_spotcheck.run_spotcheck(SITE_BASE_URL, iso_week)
    except FileNotFoundError as e:
        # Bundle didn't stage redirects.map — a packaging regression, not a
        # redirect regression. Warn (visible in the digest) rather than fail.
        return [check.warn(f"redirects.map not found (fail-soft): {str(e)[:150]}")]
    except Exception as e:
        return [check.warn(f"redirect spot-check errored (fail-soft): {str(e)[:150]}")]

    checks = []
    for err in result["errors"]:
        checks.append(Check("redirect_spotcheck:fetch", "Legacy Redirects", CONTENT_TRUTH).warn(err))

    where = f"bucket {result['bucket']}/{result['n_buckets']}, ISO week {iso_week}, {result['n_sampled']}/{result['n_total']} sampled"
    if result["failures"]:
        checks.append(check.fail(f"{len(result['failures'])} broken redirect(s) ({where}): " + "; ".join(result["failures"][:5])))
    else:
        checks.append(check.ok(f"all sampled redirects resolve correctly ({where})"))
    return checks


# ---------------------------------------------------------------------------
# CHECK 12 — Notion Template schema drift (#1840)
# ---------------------------------------------------------------------------
# #1572/#1573 shipped Video Diary + Solo Recording template support in
# notion_lambda.py's TEMPLATE_SK, but the live Notion Journal database's
# `Template` select property never got the matching options added — the
# Notion API silently rejected any page carrying those values, so both
# channels were unreachable from the moment the code shipped, and NOTHING
# caught it: the "unknown template" fallback (notion_lambda.parse_page) only
# logs when a template string IS present-but-unrecognized; here the value
# could never be set on a page at all, so even that never fired. This check
# reads the LIVE Notion schema nightly and asserts every non-fallback
# TEMPLATE_SK entry is a real option on the live select property — the same
# class of drift can never again ship inert without a loud, red qa-smoke
# result the next morning.
#
# Fail-open, honestly: a Notion API problem (auth failure, outage, network)
# reports as a WARN ("skipped"), never a false green (.ok()) and never a
# .fail() that pages someone for an unrelated Notion outage. Only an actual
# schema/code mismatch — confirmed against a successfully-fetched live
# schema — is a .fail().

NOTION_SECRET_NAME = os.environ.get("NOTION_SECRET_NAME", "life-platform/ingestion-keys")
# Matches lambdas/ingestion/notion_lambda.py's pinned NOTION_VERSION — keep in sync;
# a version bump there should be mirrored here or this check reads a different API shape.
NOTION_API_VERSION = "2022-06-28"


def check_notion_template_schema():
    check = Check("notion:template_schema", "Notion Schema", DEPLOY_HEALTH)

    try:
        from ingestion.notion_lambda import TEMPLATE_SK
    except ImportError as e:
        return [check.warn(f"Cannot import TEMPLATE_SK from notion_lambda — skipping: {e}")]

    expected = set(TEMPLATE_SK) - {"journal"}  # "journal" is the synthetic fallback, not a real select option

    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        try:
            from common.secret_cache import get_secret_json

            secret = get_secret_json(NOTION_SECRET_NAME, sm)
        except ImportError:
            secret = json.loads(sm.get_secret_value(SecretId=NOTION_SECRET_NAME)["SecretString"])
    except Exception as e:
        return [check.warn(f"Cannot fetch Notion secret {NOTION_SECRET_NAME} — skipping: {e}")]

    api_key = secret.get("notion_api_key") or secret.get("api_key")
    database_id = secret.get("notion_database_id") or secret.get("database_id")
    if not api_key or not database_id:
        return [check.warn("Notion secret missing api_key/database_id — skipping")]

    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_API_VERSION,
            "User-Agent": "life-platform-qa-smoke",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            db = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return [check.warn(f"Notion API {e.code} fetching database schema — skipping (fail-open): {e.reason}")]
    except Exception as e:
        return [check.warn(f"Notion API unreachable — skipping (fail-open): {e}")]

    template_prop = (db.get("properties") or {}).get("Template") or {}
    live_options = {opt.get("name") for opt in template_prop.get("select", {}).get("options", []) if opt.get("name")}

    if not live_options:
        return [check.warn("Live Notion database has no 'Template' select property (or no options) — skipping")]

    missing = expected - live_options
    if missing:
        check.fail(
            f"Live Notion 'Template' select is missing option(s) the code depends on: {sorted(missing)} "
            f"— TEMPLATE_SK/code shipped ahead of the live Notion schema (see #1840). Live options: {sorted(live_options)}"
        )
    else:
        check.ok(f"all {len(expected)} non-fallback TEMPLATE_SK option(s) present in the live Notion schema")
    return [check]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #1956 — AI-canary grounded-check precision (the sensor that watches sensors)
# ---------------------------------------------------------------------------

CANARY_LOG_PREFIX = "ai-canary-log"
CANARY_PRECISION_WINDOW_DAYS = 14
CANARY_PRECISION_WARN_RATE = 0.2  # >20% of runs alarming grounded = chronic
CANARY_PRECISION_MIN_RUNS = 5  # below this, a rate is noise — report, don't judge


def check_canary_precision():
    """#1956: a false-positive-rate line for the AI quality canary's
    grounded-digits check. The canary's 07-03→07-31 era fired grounded ALARMs on
    provably TRUE numbers (its fact universe was narrower than the ask
    pipeline's serving context) — and nothing measured that precision decay, so
    the alarm quietly became the boy who cried wolf. This line makes the rate a
    nightly, queryable fact: read the trailing dated ai-canary-log records and
    report how often the grounded check alarmed. Post-fix a grounded ALARM
    should be a rare, true fabrication — a chronic rate (> 20% across >= 5
    sighted runs) is the cried-wolf signature, surfaced as WARN (ground truth
    for any single firing is not deterministically knowable here, so never
    FAIL). Budget-paused and transport-BLIND runs carry no grounded verdict and
    are excluded from the denominator. Fail-soft: an unreadable log prefix
    degrades to WARN naming the missing grant, never a crash."""
    c = Check("canary:grounded_precision", "AI Canary", CONTENT_TRUTH)
    today = pt_now().date()
    runs, alarmed_dates = 0, []
    try:
        for i in range(1, CANARY_PRECISION_WINDOW_DAYS + 1):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            try:
                obj = s3.get_object(Bucket=S3_BUCKET, Key=f"{CANARY_LOG_PREFIX}/{d}.json")
            except s3.exceptions.NoSuchKey:
                continue
            rec = json.loads(obj["Body"].read())
            if rec.get("skipped") or rec.get("blind"):
                continue  # no grounded verdict exists for these runs
            runs += 1
            if any(str(a).endswith(":grounded") for a in rec.get("alarms", [])):
                alarmed_dates.append(d)
    except Exception as e:
        return [c.warn(f"canary precision unreadable ({e}) — fail-soft; needs s3:GetObject on {CANARY_LOG_PREFIX}/* (#1956)")]
    if runs == 0:
        return [c.warn(f"no sighted canary runs in trailing {CANARY_PRECISION_WINDOW_DAYS}d — grounded precision unmeasurable")]
    rate = len(alarmed_dates) / runs
    line = f"grounded-ALARM rate {len(alarmed_dates)}/{runs} ({rate:.0%}) over trailing {CANARY_PRECISION_WINDOW_DAYS}d"
    if runs >= CANARY_PRECISION_MIN_RUNS and rate > CANARY_PRECISION_WARN_RATE:
        return [c.warn(f"{line} — chronic firing, precision suspect (#1956 cried-wolf signature): {', '.join(alarmed_dates)}")]
    return [c.ok(line)]


def build_report_html(all_checks, run_time_str):
    fails = [c for c in all_checks if c.passed is False]
    warns = [c for c in all_checks if c.passed is None]
    paused = [c for c in all_checks if c.paused]
    passes = [c for c in all_checks if c.passed is True and not c.paused]

    # #1921: the email must say which SIDE failed. A content-truth failure no
    # longer reverts the fleet, so this line is the reader's only cue that a red
    # run did not (and should not have) triggered a rollback.
    n_deploy = sum(1 for c in fails if c.partition == DEPLOY_HEALTH)
    n_content = sum(1 for c in fails if c.partition == CONTENT_TRUTH)
    split = f" &middot; {n_deploy} deploy-health &middot; {n_content} content-truth" if fails else ""

    overall = "ALL CLEAR" if not fails else f"{len(fails)} FAILURE(S)"
    banner_emoji = "✅" if not fails else "🔴"
    hdr_bg = "#064e3b" if not fails else "#450a0a"
    hdr_fg = "#d1fae5" if not fails else "#fecaca"

    cats = {}
    for c in all_checks:
        cats.setdefault(c.category, []).append(c)

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0f0f23;font-family:'SF Pro Display','Segoe UI',sans-serif;">
<div style="max-width:600px;margin:0 auto;background:#1a1a2e;">
  <div style="background:{hdr_bg};padding:20px 24px;border-bottom:3px solid #2d2d5e;">
    <p style="color:#94a3b8;font-size:10px;margin:0 0 4px;font-weight:700;">LIFE PLATFORM · QA SMOKE TEST</p>
    <h1 style="color:{hdr_fg};font-size:24px;font-weight:700;margin:0 0 4px;">{banner_emoji} {overall}</h1>
    <p style="color:#94a3b8;font-size:11px;margin:0;">{run_time_str} &middot; {len(passes)} passed &middot; {len(paused)} paused &middot; {len(warns)} warnings &middot; {len(fails)} failed{split}</p>
  </div>"""

    for cat, checks in cats.items():
        cat_fails = sum(1 for c in checks if c.passed is False)
        cat_warns = sum(1 for c in checks if c.passed is None)
        cat_paused = sum(1 for c in checks if c.paused)
        if cat_fails:
            icon = "🔴"
        elif cat_warns:
            icon = "🟡"
        elif cat_paused and cat_paused == len(checks):
            icon = "⏸️"
        else:
            icon = "🟢"
        html += f"""
  <div style="padding:14px 24px;border-bottom:1px solid #2d2d5e;">
    <p style="color:#64748b;font-size:10px;margin:0 0 8px;font-weight:700;">{icon} {cat.upper()}</p>"""
        for c in checks:
            if c.paused:
                ci, cc = ("⏸️", "#94a3b8")
            elif c.passed is True:
                ci, cc = ("✅", "#22c55e")
            elif c.passed is False:
                ci, cc = ("❌", "#f87171")
            else:
                ci, cc = ("⚠️", "#fbbf24")
            html += f"""    <p style="margin:2px 0;font-size:11px;">
      <span style="color:{cc}">{ci} <strong>{c.name}</strong></span>
      <span style="color:#9ca3af;"> — {c.message}</span></p>"""
        html += "\n  </div>"

    html += """
  <div style="background:#111827;padding:10px 24px;text-align:center;">
    <p style="color:#374151;font-size:9px;margin:0;">Life Platform QA · auto-generated</p>
  </div>
</div></body></html>"""

    return html


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event, context):
    try:
        run_time = pt_now()
        run_time_str = run_time.strftime("%A, %b %-d at %-I:%M %p PT")
        print(f"[QA] Smoke test starting — {run_time_str}")

        all_checks = []
        all_checks += check_ddb_freshness()
        all_checks += check_hae_liveness_truth()  # #2001: dark HAE datatypes must carry a numeric days_dark when one is findable
        all_checks += check_s3_freshness()
        # #1949: raw_layout facets must be live-true (DDB-fresh/raw-dead reds a check)
        all_checks += raw_archive_qa.check_raw_archive_liveness(table, s3, S3_BUCKET, Check, CONTENT_TRUTH, pt_now)
        all_checks += check_score_sanity()
        all_checks += check_lambda_secrets()
        all_checks += check_avatar_assets()  # character avatar visuals — kept (real check)
        all_checks += check_mcp_tool_calls()
        all_checks += check_reader_truth()  # #1096: phase-aware narrative truth (Haiku, budget-aware, fail-soft)
        all_checks += check_predict_week_freshness()  # #1198: predict-the-week never live on a stale ISO week
        all_checks += check_hero_weight_arithmetic()  # #1225: home hero stat row reconciles + trend-honest
        all_checks += check_coach_labs_truth()  # #1993: no served coach text may narrate an empty labs store against real draws
        # #1972: chronicle/podcast lists must carry a next-date OR an honest-pending line, never neither
        all_checks += check_content_cadence()
        # #1951: the /subscribe/ weekly-send promise must agree with each sender's live kill switch
        all_checks += check_subscriber_promise_truth()
        all_checks += weight_truth_qa.checks(Check, SITE_BASE_URL, CONTENT_TRUTH)  # #1894: home/cockpit vs the coaching door
        all_checks += check_receipt_replay()  # #1373: progression-receipt drift alarm (deterministic replay)
        all_checks += check_redirect_spotcheck()  # #1430: weekly legacy-redirect sample, rotates over redirects.map
        all_checks += check_notion_template_schema()  # #1840: code TEMPLATE_SK vs live Notion schema drift gate
        all_checks += check_canary_precision()  # #1956: AI-canary grounded-check false-positive-rate line (sensor on the sensor)
        # blog moved to /story/ in v4 — shown paused (not failed) so it's not forgotten.
        all_checks.append(
            Check("blog:links", "Blog Links", CONTENT_TRUTH).pause(
                "Blog — paused (chronicle now lives at /story/ in v4); will return if revived"
            )
        )

        # #1345 DR-drill hook: an explicit {"synthetic_fail": true} invoke payload
        # injects ONE clearly-labeled synthetic FAIL so the CI smoke→rollback path can
        # be proven by an actual firing in a controlled window (ci-cd.yml passes it
        # only on a `drill_smoke=true` workflow_dispatch). Scheduled/normal invokes
        # carry no flag = zero effect. Self-cleaning: the rollback the drill triggers
        # reverts qa-smoke to its previous zip.
        if isinstance(event, dict) and event.get("synthetic_fail") is True:
            all_checks.append(
                Check("drill:synthetic", "DR Drill", DEPLOY_HEALTH).fail(
                    "SYNTHETIC failure (synthetic_fail invoke flag) — #1345 rollback drill, NOT a real defect"
                )
            )

        html = build_report_html(all_checks, run_time_str)

        fails = [c for c in all_checks if c.passed is False]
        warns = [c for c in all_checks if c.passed is None]
        paused = [c for c in all_checks if c.paused]
        passes = [c for c in all_checks if c.passed is True and not c.paused]

        # #1921: split the failures by partition. Only deploy_health failures are
        # evidence about the deploy in flight, so only they may gate ci-cd's
        # smoke-test job (deploy/lib/smoke_oracle_decision.py reads
        # failed_deploy_health). content_truth failures are NOT muted — they still
        # send the same red email, still land in the log above, still count in the
        # EMF FailCount that monitoring_stack alarms on, and still make the
        # scheduled nightly a failed run. They simply stop reverting code that
        # cannot have caused them and that reverting cannot fix.
        fails_deploy = [c for c in fails if c.partition == DEPLOY_HEALTH]
        fails_content = [c for c in fails if c.partition == CONTENT_TRUTH]

        # #1958: split the warns the same way — through qa_check.split_warns, the
        # one chokepoint both check modules share. Alarmed (novel) warns are what
        # qa-smoke-warnings fires on; chronic warns (the enumerated recurring
        # timing set) stay fully visible here, in the email, and in their own
        # ChronicWarnCount metric, but can no longer hold the alarm red.
        warns_alarmed, warns_chronic = split_warns(all_checks)

        # #1610: itemize every fail/warn to the LOG, not just the failure email.
        # The specific failing check used to appear ONLY in the emailed report, so a
        # latched daily FailCount alarm was undiagnosable from CloudWatch without inbox
        # access. Now the check category/name/message rides stdout on any non-clean run
        # (queryable via Logs Insights), matching the existing `[QA]` print convention.
        # Messages carry only freshness/sanity metadata, secret NAMES (already in-repo),
        # and public-dashboard values — no sensitive values.
        # #1921: the partition rides every FAIL line. Which side a failure landed
        # on is the whole question when a rollback did (or did not) fire, and
        # reconstructing it later from the check name is guesswork.
        for c in fails:
            print(f"[QA] FAIL [{c.partition}] {c.category} / {c.name}: {c.message}")
        for c in warns:
            # #1958: the chronic tag rides every WARN line so Logs Insights can
            # tell a recurring timing warn from a novel one without the metric.
            print(f"[QA] WARN [{c.partition}]{' [chronic]' if c.chronic else ''} {c.category} / {c.name}: {c.message}")

        # #1920: a POSITIVE EXECUTION RECEIPT. Check.pause() sets passed=True and
        # printed nothing, so a paused check and a passing one were byte-identical
        # in every recorded signal — that is how `reader_truth` sat budget-paused
        # for 26 consecutive days (2026-07-06 → 08-01) while reporting green, and
        # why its precision could not be measured after the fact. A skipped check
        # and a passing check must never look alike again.
        for c in paused:
            print(f"[QA] PAUSE [{c.partition}] {c.category} / {c.name}: {c.message}")

        # #1445: emit the EMF summary on EVERY run — including all-green — so
        # the nightly QA layer has a heartbeat and its warnings/failures are
        # queryable metrics, not just the inside of an email nobody reads
        # until it's a failure. See emf_summary_line()'s docstring above.
        print(
            emf_summary_line(
                passed=len(passes),
                warned=len(warns_alarmed),  # #1958: WarnCount = alarmed warns only
                failed=len(fails),
                paused=len(paused),
                timestamp_ms=int(run_time.timestamp() * 1000),
                failed_deploy_health=len(fails_deploy),
                failed_content_truth=len(fails_content),
                warned_chronic=len(warns_chronic),
            )
        )

        # 2026-05-28: only email on real FAILURES. Warnings (sporadic optional
        # sources with no record yesterday) are normal and were firing a yellow
        # email almost every day — pure noise. They remain visible in logs and
        # in the failure email's body when a failure does occur.
        # #1921: `failed` stays the TOTAL — it is the nightly's own verdict and
        # every existing consumer (alarms, the remediation agent, tests) reads it
        # unchanged. The two partitioned counts are ADDITIVE, and only
        # failed_deploy_health gates the pipeline. `paused` names ride along as
        # the #1920 execution receipt, so a caller can tell a green run from a
        # run where the check never executed.
        def _body(emailed):
            return json.dumps(
                {
                    "failed": len(fails),
                    "failed_deploy_health": len(fails_deploy),
                    "failed_content_truth": len(fails_content),
                    # `warned` stays the TOTAL (the run's own verdict, unchanged
                    # for existing consumers); `warned_chronic` is ADDITIVE and
                    # names how many of them are the recurring timing class (#1958).
                    "warned": len(warns),
                    "warned_chronic": len(warns_chronic),
                    "paused": sorted(c.name for c in paused),
                    "emailed": emailed,
                }
            )

        if not fails:
            print(
                f"[QA] {len(warns)} warning(s) ({len(warns_alarmed)} alarmed, {len(warns_chronic)} chronic), "
                "0 failures — no email (warnings not emailed standalone)"
            )
            return {"statusCode": 200, "body": _body(False)}

        subject = (
            f"🔴 QA: {len(fails)} failure{'s' if len(fails)>1 else ''} "
            f"({len(fails_deploy)} deploy-health, {len(fails_content)} content-truth) — {run_time.strftime('%b %-d')}"
        )

        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
                }
            },
        )

        print(
            f"[QA] Done — {len(fails)} failures "
            f"({len(fails_deploy)} deploy_health, {len(fails_content)} content_truth), "
            f"{len(warns)} warnings, email sent"
        )
        return {"statusCode": 200, "body": _body(True)}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
