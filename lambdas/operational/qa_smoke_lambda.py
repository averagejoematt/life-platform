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
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from mcp_url import resolve_mcp_url  # SEC-02 #780: discover the URL at runtime, not a committed env var

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("qa-smoke")
except ImportError:
    logger = logging.getLogger("qa-smoke")
    logger.setLevel(logging.INFO)

# Genesis-aware checks (2026-06-08): on the day after an experiment reset, the
# dashboard validates *yesterday*, which is pre-genesis and legitimately has no
# day-grade. A missing grade for a pre-experiment date is expected, not a fault.
try:
    from constants import EXPERIMENT_START_DATE
except ImportError:
    EXPERIMENT_START_DATE = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
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


class Check:
    """Single assertion result."""

    def __init__(self, name, category):
        self.name = name
        self.category = category
        self.passed = None  # True=green, False=red, None=yellow
        self.paused = False  # intentionally-paused surface: shown ⏸, not a fault
        self.message = ""

    def ok(self, msg=""):
        self.passed = True
        self.message = msg
        return self

    def fail(self, msg=""):
        self.passed = False
        self.message = msg
        return self

    def warn(self, msg=""):
        self.passed = None
        self.message = msg
        return self

    def pause(self, msg=""):
        # Surface is intentionally paused (will return later). Renders ⏸ and is
        # NOT counted as a failure or a warning — visible, but never a fault.
        self.passed = True
        self.paused = True
        self.message = msg
        return self


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
    from source_registry import qa_optional, qa_paused, qa_required

    REQUIRED = qa_required()
    OPTIONAL = qa_optional()
    PAUSED = qa_paused()

    for source, label in REQUIRED:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            c.ok(f"{label} record found for {yesterday}") if item else c.fail(f"{label} — no record for {yesterday}")
        except Exception as e:
            c.fail(f"{label} — DDB error: {e}")
        checks.append(c)

    for source, label in OPTIONAL:
        c = Check(f"DDB:{source}", "Data Freshness")
        try:
            resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + yesterday})
            item = resp.get("Item")
            c.ok(f"{label} found") if item else c.warn(f"{label} — no record (optional)")
        except Exception as e:
            c.warn(f"{label} — error: {e}")
        checks.append(c)

    for source, note in PAUSED:
        checks.append(Check(f"DDB:{source}", "Data Freshness").pause(note))

    return checks


# ---------------------------------------------------------------------------
# CHECK 2 — S3 output file freshness
# ---------------------------------------------------------------------------


def check_s3_freshness():
    checks = []

    # (s3_key, label, max_age_hours, non_critical)
    # 2026-05-03: paths corrected from dashboard/{file} → dashboard/matthew/{file}.
    # The canonical writer (output_writers.py) uses dashboard/{user_id}/data.json
    # for multi-user prep. qa-smoke had been checking the OLD pre-refactor path
    # since 2026-03-08, generating false S3-stale failures continuously.
    # 2026-06-03: buddy/data.json moved to a PAUSED check below (not freshness-checked
    # while the buddy surface is dormant; last written 2026-03-09). Kept visible so it
    # can be returned to.
    FILES = [
        ("dashboard/matthew/data.json", "Dashboard JSON", 4, False),
        ("dashboard/matthew/clinical.json", "Clinical JSON", 26, True),
    ]

    for key, label, max_hours, non_critical in FILES:
        c = Check(f"S3:{key}", "Output Files")
        try:
            head = s3.head_object(Bucket=S3_BUCKET, Key=key)
            age_h = (datetime.now(timezone.utc) - head["LastModified"]).total_seconds() / 3600
            if age_h <= max_hours:
                c.ok(f"{label} is current ({age_h:.1f}h ago)")
            elif non_critical:
                c.warn(f"{label} is stale ({age_h:.1f}h ago, max {max_hours}h) — non-critical")
            else:
                c.fail(f"{label} is STALE — last written {age_h:.1f}h ago (max {max_hours}h)")
        except Exception as e:
            if non_critical:
                c.warn(f"{label} — error (non-critical): {e}")
            else:
                c.fail(f"{label} — error: {e}")
        checks.append(c)

    checks.append(Check("S3:buddy/data.json", "Output Files").pause("Buddy JSON — paused (buddy surface dormant); will return"))
    return checks


# ---------------------------------------------------------------------------
# CHECK 3 — Score sanity (read dashboard/data.json, validate value ranges)
# ---------------------------------------------------------------------------


def check_score_sanity():
    checks = []

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="dashboard/matthew/data.json")
        data = json.loads(resp["Body"].read())
    except Exception as e:
        return [Check("dashboard:parse", "Score Sanity").fail(f"Cannot load dashboard/matthew/data.json: {e}")]

    expected_date = yesterday_str()
    actual_date = data.get("date", "")
    c = Check("dashboard:date", "Score Sanity")
    if actual_date == expected_date:
        c.ok(f"Date = {actual_date}")
    elif actual_date:
        c.fail(f"Stale date — expected {expected_date}, got {actual_date}")
    else:
        c.fail("Date field missing from dashboard JSON")
    checks.append(c)

    def _range_check(name, value, lo, hi, unit="", optional=False):
        c = Check(f"value:{name}", "Score Sanity")
        if value is None:
            return c.warn(f"{name} is null (may not have synced)") if optional else c.fail(f"{name} is null — expected data")
        if lo <= float(value) <= hi:
            return c.ok(f"{name} = {value}{unit}")
        return c.fail(f"{name} = {value}{unit} — outside plausible range [{lo},{hi}]")

    readiness = (data.get("readiness") or {}).get("score")
    sleep_s = (data.get("sleep") or {}).get("score")
    weight = (data.get("weight") or {}).get("current")
    hrv = (data.get("hrv") or {}).get("value")
    glucose = (data.get("glucose") or {}).get("avg")
    grade_l = (data.get("day_grade") or {}).get("letter")
    grade_s = (data.get("day_grade") or {}).get("score")
    hydration = (data.get("day_grade", {}).get("components") or {}).get("hydration")

    checks += [
        _range_check("readiness", readiness, 0, 100, "%", optional=True),
        _range_check("sleep", sleep_s, 0, 100, "", optional=True),
        _range_check("weight", weight, 150, 450, " lbs"),
        _range_check("hrv", hrv, 5, 250, " ms", optional=True),
        _range_check("glucose", glucose, 50, 300, " mg/dL", optional=True),
    ]

    c = Check("score:day_grade", "Score Sanity")
    if grade_l and grade_s is not None:
        c.ok(f"Day grade = {grade_l} ({grade_s}/100)")
    elif EXPERIMENT_START_DATE and actual_date and actual_date < EXPERIMENT_START_DATE:
        c.ok(f"Day grade absent for pre-genesis day {actual_date} (experiment starts {EXPERIMENT_START_DATE}) — expected")
    else:
        c.fail(f"Day grade missing — grade={grade_l}, score={grade_s}")
    checks.append(c)

    c = Check("score:hydration", "Score Sanity")
    if hydration is None:
        c.warn("Hydration null — Apple Health water likely didn't sync")
    elif hydration < 30:
        c.warn(f"Hydration = {hydration} — low, possible HAE sync gap (may be valid if <1L consumed)")
    else:
        c.ok(f"Hydration = {hydration}")
    checks.append(c)

    cs = data.get("character_sheet") or {}
    c = Check("character_sheet", "Score Sanity")
    lvl, tier = cs.get("level"), cs.get("tier")
    if lvl and tier:
        xp = cs.get("xp", 0)
        c.ok(f"Level {lvl} {tier} ({xp:,} XP)")
    else:
        c.fail(f"Character sheet missing — level={lvl}, tier={tier}")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 4 — Blog link integrity
# ---------------------------------------------------------------------------


def check_blog_links():
    checks = []

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key="blog/index.html")
        index_html = resp["Body"].read().decode("utf-8")
    except Exception as e:
        # Blog index may not exist yet — non-critical
        return [Check("blog:index", "Blog Links").warn(f"blog/index.html not found (non-critical): {e}")]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="blog/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        return [Check("blog:list", "Blog Links").fail(f"Cannot list blog/ objects: {e}")]

    linked = set(re.findall(r'href="(week-[\w.]+\.html)"', index_html))

    if not linked:
        checks.append(Check("blog:links", "Blog Links").warn("No week-*.html links found in blog index"))
        return checks

    broken, ok_count = [], 0
    for fname in sorted(linked):
        if "blog/" + fname in existing:
            ok_count += 1
        else:
            broken.append(fname)

    c = Check("blog:links", "Blog Links")
    if broken:
        c.fail(f"{len(broken)} broken link(s): {', '.join(broken)} — linked from index but not in S3")
    else:
        c.ok(f"All {ok_count} blog post link(s) resolve")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 5 — Lambda secret health
# ---------------------------------------------------------------------------


def check_lambda_secrets():
    """Verify every Lambda's SECRET_NAME env var points to an existing secret."""
    lm = boto3.client("lambda", region_name=REGION)
    sm = boto3.client("secretsmanager", region_name=REGION)

    # Build set of existing (non-deleted) secrets
    existing = set()
    try:
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate():
            for s in page["SecretList"]:
                if s.get("DeletedDate") is None:
                    existing.add(s["Name"])
    except Exception as e:
        return [Check("secrets:inventory", "Lambda Secrets").fail(f"Cannot list secrets: {e}")]

    stale = []
    try:
        paginator = lm.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page["Functions"]:
                secret_name = fn.get("Environment", {}).get("Variables", {}).get("SECRET_NAME")
                if secret_name and secret_name not in existing:
                    stale.append(f"{fn['FunctionName']} → {secret_name}")
    except Exception as e:
        return [Check("secrets:sweep", "Lambda Secrets").fail(f"Cannot list functions: {e}")]

    c = Check("secrets:lambda_refs", "Lambda Secrets")
    if stale:
        c.fail(f"{len(stale)} stale SECRET_NAME(s): " + "; ".join(stale))
    else:
        c.ok(f"All Lambda SECRET_NAME references resolve ({len(existing)} secrets in inventory)")
    return [c]


# ---------------------------------------------------------------------------
# CHECK 6 — Avatar PNG assets
# ---------------------------------------------------------------------------


def check_avatar_assets():
    TIERS = ["foundation", "momentum", "discipline", "mastery", "elite"]
    FRAMES = [1, 2, 3]

    try:
        paginator = s3.get_paginator("list_objects_v2")
        existing = set()
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="dashboard/avatar/base/"):
            for obj in page.get("Contents", []):
                existing.add(obj["Key"])
    except Exception as e:
        # ListBucket permission may be missing — non-critical (IAM least-privilege)
        return [Check("avatar:sprites", "Avatar Assets").warn(f"Cannot list avatar assets (non-critical): {e}")]

    missing = [
        f"{tier}-frame{frame}.png" for tier in TIERS for frame in FRAMES if f"dashboard/avatar/base/{tier}-frame{frame}.png" not in existing
    ]

    c = Check("avatar:sprites", "Avatar Assets")
    total = len(TIERS) * len(FRAMES)
    if missing:
        c.fail(f"Missing {len(missing)}/{total} sprites: {', '.join(missing)}")
    else:
        c.ok(f"All {total} avatar sprites present")
    return [c]


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
        return [Check("mcp:config", "MCP Integration").warn("MCP Function URL unresolved — skipping")]

    # Fetch MCP API key
    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        api_key = sm.get_secret_value(SecretId=MCP_SECRET_NAME)["SecretString"]
    except Exception as e:
        return [Check("mcp:auth", "MCP Integration").fail(f"Cannot fetch MCP API key: {e}")]

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
    c = Check("mcp:get_sources", "MCP Integration")
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
    c = Check("mcp:get_todoist_snapshot", "MCP Integration")
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
    c = Check("mcp:cache_warm", "MCP Integration")
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("CACHE#matthew") & Key("sk").begins_with("TOOL#"),
            Select="COUNT",
        )
        n = resp.get("Count", 0)
        if n >= 10:
            c.ok(f"Cache has {n} warm entries")
        elif n >= 1:
            c.warn(f"Cache has only {n} entries — warmer may have partially failed")
        else:
            c.fail("Cache empty — nightly warmer has not run or failed entirely")
    except Exception as e:
        c.fail(f"Cache query error: {e}")
    checks.append(c)

    return checks


# ---------------------------------------------------------------------------
# CHECK 8 — Reader Truth (#1096): phase-aware narrative-truth QA, nightly
# ---------------------------------------------------------------------------
# A temporal contradiction ("Day 2" narrating a 30-day trend) can sit live for
# days BETWEEN deploys with nothing looking at it — the post-deploy CI pass
# (#1095) only fires on a deploy. This check fetches a small surface set over
# HTTPS and runs the SAME rubric (lambdas/reader_truth_qa.py, Haiku per ADR-049).
# Posture: budget-aware (internal QA pauses first, tier >= 1 per ADR-125 —
# reported as an explicit ⏸ skip, never silent green) and fail-SOFT on Bedrock/
# fetch errors (a Bedrock outage must never red the nightly). Only a HIGH truth
# finding is a failure (lands in the alert email); med/low are warnings.

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://averagejoematt.com")

# Small, reader-critical set: the cockpit, home, the coaching read, data vitals —
# plus the two API payloads whose narrative values those pages bind. One Haiku
# batch (<= 6 surfaces), pennies per night.
READER_TRUTH_SURFACES = [
    ("/", "Home"),
    ("/now/", "Cockpit"),
    ("/coaching/", "Coaching read"),
    ("/data/vitals/", "Data · vitals"),
]
READER_TRUTH_APIS = [
    ("/api/vitals", "API · vitals"),
    ("/api/coaches", "API · coaches"),
]


def _fetch_reader_truth_surfaces():
    """Fetch the reader-truth surface set. Returns (surfaces, fetch_warnings).

    Pages are tag-stripped to visible-ish text (static-HTML approximation of the
    browser innerText the CI pass sees); API payloads go in as raw JSON text.
    Every failure is a warning string, never an exception (fail-soft).
    """
    import reader_truth_qa

    surfaces, warnings = [], []
    for path, name in READER_TRUTH_SURFACES + READER_TRUTH_APIS:
        try:
            req = urllib.request.Request(SITE_BASE_URL + path, headers={"User-Agent": "life-platform-qa-smoke"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", "replace")
            prose = body if path.startswith("/api/") else reader_truth_qa.html_to_text(body)
            surfaces.append({"name": name, "path": path, "prose": prose})
        except Exception as e:
            warnings.append(f"{name} ({path}) — fetch failed: {str(e)[:100]}")
    return surfaces, warnings


def check_reader_truth():
    checks = []
    verdict = Check("reader_truth:verdict", "Reader Truth")

    # Budget gate — internal QA pauses first (ADR-125). Explicit ⏸, never silent.
    try:
        import budget_guard
        import reader_truth_qa

        if not budget_guard.allow(reader_truth_qa.BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            return [verdict.pause(f"Reader Truth AI skipped — budget tier {tier} (internal QA pauses first, ADR-125)")]
    except Exception as e:
        # Import/SSM blip: same fail-open posture as budget_guard itself — but if
        # the shared module is missing the sweep below can't run either, so warn.
        logger.warning("reader-truth budget gate degraded: %s", e)

    try:
        import reader_truth_qa

        surfaces, fetch_warnings = _fetch_reader_truth_surfaces()
        for w in fetch_warnings:
            checks.append(Check("reader_truth:fetch", "Reader Truth").warn(f"{w} (fail-soft)"))
        if not surfaces:
            checks.append(verdict.warn("no surfaces fetched — Reader Truth skipped this run (fail-soft)"))
            return checks

        import bedrock_client

        findings, errors = reader_truth_qa.assess_prose(surfaces, bedrock_client.invoke)
        phase = reader_truth_qa.phase_context()
        day = f"{phase['days_until_start']}d pre-start" if phase["pre_start"] else f"Day {phase['day_n']}"
    except Exception as e:
        # Bedrock outage / missing module / AccessDenied — an explicit soft skip.
        checks.append(verdict.warn(f"Reader Truth AI unavailable — skipped this run (fail-soft): {str(e)[:120]}"))
        return checks

    for err in errors:
        checks.append(Check("reader_truth:batch", "Reader Truth").warn(f"AI batch error (fail-soft): {err}"))

    def _fmt(f):
        return f"{f['page']} [{f['category']}] {f['note'][:90]}"

    highs = [f for f in findings if f["severity"] == "high"]
    lower = [f for f in findings if f["severity"] != "high"]
    if highs:
        verdict.fail(f"{len(highs)} high truth finding(s) at {day}: " + "; ".join(_fmt(f) for f in highs[:4]))
    elif lower:
        verdict.warn(f"{len(lower)} low/med truth finding(s) at {day}: " + "; ".join(_fmt(f) for f in lower[:4]))
    elif errors:
        verdict.warn(f"no verdict at {day} — all {len(errors)} AI batch(es) errored (fail-soft)")
    else:
        verdict.ok(f"{len(surfaces)} surfaces clean at {day} — no truth findings")
    checks.append(verdict)
    return checks


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


def _iso_week_id(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def check_predict_week_freshness():
    check = Check("predict_week:freshness", "Predict-the-Week Freshness")
    url = SITE_BASE_URL + "/api/predict_week"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "life-platform-qa-smoke"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # Fail-soft: a fetch/parse blip must never red the nightly.
        return [check.warn(f"/api/predict_week fetch failed (fail-soft): {str(e)[:120]}")]
    if not data.get("active"):
        return [check.ok("no active prediction subject (fail-closed) — no stale bets solicited")]
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

WEIGHT_RECONCILE_TOL = 0.05


def assess_hero_weight(journey):
    """Validate the /api/journey weight row reconciles + is trend-honest.

    Returns (ok: bool, message: str). Pure — no network, no clock. A pre-start
    payload (weight fields nulled by design, #931) is a clean pass.
    """
    if not isinstance(journey, dict):
        return False, "journey payload is not an object"
    if journey.get("pre_start") or journey.get("current_weight_lbs") is None:
        return True, "pre-start / no weigh-in — no weight claim to reconcile"

    now = journey.get("current_weight_lbs")
    start = journey.get("start_weight_lbs")
    lost = journey.get("lost_lbs")
    if start is None or lost is None:
        return False, f"weight row incomplete — current={now}, start={start}, lost={lost}"

    # (a) Arithmetic: DISPLAYED now − DISPLAYED start must equal the DISPLAYED delta.
    #     lost_lbs is start − now, so (now − start) must equal −lost_lbs.
    residual = float(now) - float(start) + float(lost)
    if abs(residual) > WEIGHT_RECONCILE_TOL:
        return False, (
            f"stat row fails arithmetic: now {now} − start {start} = {round(float(now) - float(start), 2)} "
            f"but the delta shows {lost} (residual {round(residual, 2)}) — a numerate reader can't reconcile it (#1225)"
        )

    # (b) Trend honesty: "up/down X in N days" needs >= 2 weigh-ins. The payload must
    #     carry the count, and a single weigh-in must span 0 days (story.js gates the
    #     elapsed-days copy on exactly this).
    n = journey.get("weighin_count")
    if n is None:
        return False, "journey payload is missing weighin_count — story.js can't gate the 'in N days' trend claim (#1225)"
    span = journey.get("weighin_span_days") or 0
    if int(n) < 2 and float(span) > 0:
        return False, (
            f"single weigh-in (count={n}) but weighin_span_days={span} > 0 — that would let story.js claim an "
            f"N-day trend off one reading (#1225)"
        )
    return True, f"stat row reconciles (now {now} − start {start} → {lost} delta) · {n} weigh-in(s), span {span}d"


def check_hero_weight_arithmetic():
    check = Check("hero_weight:arithmetic", "Reader Truth")
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
# #1445: EMF summary metrics — emitted on EVERY run, including all-green
# ---------------------------------------------------------------------------
# Before this, qa-smoke only spoke by SENDING AN EMAIL, and only on a real
# FAILURE — a green run and a run that never happened at all looked
# identical from the outside (no metric, no heartbeat, nothing for the
# remediation agent to see). This EMF line is CloudWatch-extracted into
# LifePlatform/QaSmoke metrics regardless of outcome:
#   PassCount / WarnCount / FailCount / PausedCount — per-run check tallies.
#   RunCompleted=1 — the heartbeat target (monitoring_stack.py's
#     qa-smoke-heartbeat fires BREACHING if this is absent for 2 straight
#     days, i.e. the Lambda stopped running or died before reaching here).
# monitoring_stack.py also alarms FailCount>=1 and WarnCount>=1 (both
# digest-routed, matching this file's own "routine, not urgent" posture) —
# a warnings-only run now surfaces in the next daily digest email even
# though it never triggers this Lambda's own direct failure alert, and both
# alarms are ordinary CloudWatch alarms the remediation agent's existing
# `describe_alarms(StateValue="ALARM")` sweep already ingests as a source.
QA_SMOKE_EMF_NAMESPACE = "LifePlatform/QaSmoke"


def emf_summary_line(*, passed: int, warned: int, failed: int, paused: int, timestamp_ms: int) -> str:
    """Build the EMF log line CloudWatch extracts to LifePlatform/QaSmoke metrics."""
    doc = {
        "_aws": {
            "Timestamp": int(timestamp_ms),
            "CloudWatchMetrics": [
                {
                    "Namespace": QA_SMOKE_EMF_NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": [
                        {"Name": "PassCount"},
                        {"Name": "WarnCount"},
                        {"Name": "FailCount"},
                        {"Name": "PausedCount"},
                        {"Name": "RunCompleted"},
                    ],
                }
            ],
        },
        "PassCount": int(passed),
        "WarnCount": int(warned),
        "FailCount": int(failed),
        "PausedCount": int(paused),
        "RunCompleted": 1,
    }
    return json.dumps(doc)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report_html(all_checks, run_time_str):
    fails = [c for c in all_checks if c.passed is False]
    warns = [c for c in all_checks if c.passed is None]
    paused = [c for c in all_checks if c.paused]
    passes = [c for c in all_checks if c.passed is True and not c.paused]

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
    <p style="color:#94a3b8;font-size:11px;margin:0;">{run_time_str} &middot; {len(passes)} passed &middot; {len(paused)} paused &middot; {len(warns)} warnings &middot; {len(fails)} failed</p>
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
        all_checks += check_s3_freshness()
        all_checks += check_score_sanity()
        all_checks += check_lambda_secrets()
        all_checks += check_avatar_assets()  # character avatar visuals — kept (real check)
        all_checks += check_mcp_tool_calls()
        all_checks += check_reader_truth()  # #1096: phase-aware narrative truth (Haiku, budget-aware, fail-soft)
        all_checks += check_predict_week_freshness()  # #1198: predict-the-week never live on a stale ISO week
        all_checks += check_hero_weight_arithmetic()  # #1225: home hero stat row reconciles + trend-honest
        # blog moved to /story/ in v4 — shown paused (not failed) so it's not forgotten.
        all_checks.append(
            Check("blog:links", "Blog Links").pause("Blog — paused (chronicle now lives at /story/ in v4); will return if revived")
        )

        html = build_report_html(all_checks, run_time_str)

        fails = [c for c in all_checks if c.passed is False]
        warns = [c for c in all_checks if c.passed is None]
        paused = [c for c in all_checks if c.paused]
        passes = [c for c in all_checks if c.passed is True and not c.paused]

        # #1445: emit the EMF summary on EVERY run — including all-green — so
        # the nightly QA layer has a heartbeat and its warnings/failures are
        # queryable metrics, not just the inside of an email nobody reads
        # until it's a failure. See emf_summary_line()'s docstring above.
        print(
            emf_summary_line(
                passed=len(passes),
                warned=len(warns),
                failed=len(fails),
                paused=len(paused),
                timestamp_ms=int(run_time.timestamp() * 1000),
            )
        )

        # 2026-05-28: only email on real FAILURES. Warnings (sporadic optional
        # sources with no record yesterday) are normal and were firing a yellow
        # email almost every day — pure noise. They remain visible in logs and
        # in the failure email's body when a failure does occur.
        if not fails:
            print(f"[QA] {len(warns)} warning(s), 0 failures — no email (warnings not emailed standalone)")
            return {"statusCode": 200, "body": json.dumps({"failed": 0, "warned": len(warns), "emailed": False})}

        subject = f"🔴 QA: {len(fails)} failure{'s' if len(fails)>1 else ''} — {run_time.strftime('%b %-d')}"

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

        print(f"[QA] Done — {len(fails)} failures, {len(warns)} warnings, email sent")
        return {"statusCode": 200, "body": json.dumps({"failed": len(fails), "warned": len(warns), "emailed": True})}
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
