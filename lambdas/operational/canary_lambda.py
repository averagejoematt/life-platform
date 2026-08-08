"""
canary_lambda.py — REL-4: Synthetic End-to-End Health Check Canary
CI/CD Pipeline Version: v3.9.4 — first automated deploy test

Runs every 4 hours. Verifies the platform's three critical data paths:
  1. DynamoDB write → read round-trip (STORE layer)
  2. S3 write → read round-trip (STORE layer)
  3. MCP Lambda reachability via Function URL (SERVE layer)

Each check writes a known synthetic record, reads it back, verifies integrity,
and cleans up. If any check fails it emits a CloudWatch metric and sends an SES alert.

Design:
  - Writes to a dedicated canary partition: pk=CANARY#matthew, sk=CANARY#<timestamp>
  - S3 writes to canary/ prefix (separate from all real data paths)
  - MCP check: HTTP POST to Function URL with a lightweight ping tool call
  - All canary records are deleted immediately after verification
  - TTL set to +1 hour as safety net if delete fails
  - Never touches real data partitions

CloudWatch metrics emitted (namespace: LifePlatform/Canary):
  CanaryDDBPass / CanaryDDBFail
  CanaryS3Pass  / CanaryS3Fail
  CanaryMCPPass / CanaryMCPFail
  CanaryLatencyDDB_ms / CanaryLatencyS3_ms / CanaryLatencyMCP_ms

Alarm: life-platform-canary-failure — any Fail metric > 0 → SNS

Severity lanes (#2051):
  Checks report into TWO lanes, defined once in operational/canary_lanes.py:
    • infra        — live round-trips (DDB/S3/MCP/Bedrock/subscribe flow). A
                     failure here is plausible evidence about the code that
                     just shipped, so it GATES the CI smoke oracle and can
                     trigger the auto-rollback. Reflected in `statusCode`.
    • stored_state — postconditions about data at rest (#1954 residue, the
                     cleanup delete). These describe rows that may predate the
                     deploy by weeks, and a rollback cannot delete a row —
                     they alarm, email on FIRST occurrence, and are surfaced
                     as a CI warning, but they never gate.
  The response body carries both counts: `failed_deploy_health` (infra, the
  same key qa-smoke publishes for #1921) and `failed_stored_state`. `all_pass`
  and `failures` remain the honest UNION of both lanes.

Lambda: life-platform-canary
Schedule: rate(4 hours)
IAM role: lambda-canary-role
Timeout: 60s
Memory: 256 MB
"""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from common.mcp_url import resolve_mcp_url  # SEC-02 #780: discover the URL at runtime, not a committed env var
from common.send_guard import guarded_send_email, is_dry_run  # #2222: SES send-suppressor gate

from operational.canary_lanes import (  # #2051: one registry decides what gates a rollback
    LANE_INFRA,
    LANE_STORED_STATE,
    label_for,
    lane_counts,
    lane_for,
    lane_summary,
)

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from common.platform_logger import get_logger

    logger = get_logger("canary")
except ImportError:
    logger = logging.getLogger("canary")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
MCP_SECRET = os.environ.get("MCP_SECRET_NAME", "life-platform/mcp-api-key")

# Reentry sweep (2026-05-03): Anthropic API canary — catches the "API access
# turned off" failure mode (key disabled for billing) that hit at 9:10 AM PT
# on 2026-05-03, surfacing only when the daily brief came back Grade F at 10 AM.
# Tiny call (Haiku, max_tokens=1) ≈ $0.0001/run × 6 runs/day = $0.0006/day.
ANTHROPIC_SECRET = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
ANTHROPIC_CANARY_MODEL = os.environ.get("ANTHROPIC_CANARY_MODEL", "claude-haiku-4-5-20251001")
SENDER = os.environ["EMAIL_SENDER"]
RECIPIENT = os.environ["EMAIL_RECIPIENT"]

CANARY_PK = "CANARY#matthew"

# #1954: the REAL subscriber partition the subscribe-flow check writes a
# synthetic (source='canary') row into. After cleanup, the canary asserts this
# partition holds ZERO synthetic rows — on 2026-07-21 a silent cleanup failure
# left a stray canary row sitting there for 12 days.
SUBSCRIBERS_PK = "USER#matthew#SOURCE#subscribers"
# Bounded pagination for the residue count — a pathological LastEvaluatedKey
# (or a MagicMock in tests) must never spin the loop forever.
CANARY_COUNT_MAX_PAGES = 50

# ── AWS clients ────────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)
ses = boto3.client("sesv2", region_name=REGION)
cw = boto3.client("cloudwatch", region_name=REGION)
secrets = boto3.client("secretsmanager", region_name=REGION)

CW_NAMESPACE = "LifePlatform/Canary"


# ── Metric emission ────────────────────────────────────────────────────────────


def emit(metric_name: str, value: float, unit: str = "Count"):
    try:
        cw.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Value": value,
                    "Unit": unit,
                    "Timestamp": datetime.now(timezone.utc),
                }
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch emit failed ({metric_name}): {e}")


# ── Check 1: DynamoDB round-trip ───────────────────────────────────────────────


def check_dynamodb(canary_ts: str, payload: dict) -> tuple[bool, str, float]:
    """Write a synthetic record, read it back, verify hash, delete. Returns (ok, msg, latency_ms)."""
    sk = f"CANARY#{canary_ts}"
    ttl = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())

    record = {
        "pk": CANARY_PK,
        "sk": sk,
        "canary_payload": payload["hash"],
        "canary_ts": canary_ts,
        "source": "canary",
        "ttl": ttl,
    }

    t0 = time.monotonic()
    try:
        # Write
        table.put_item(Item=record)

        # Read back
        result = table.get_item(Key={"pk": CANARY_PK, "sk": sk})
        item = result.get("Item")

        if not item:
            return False, "DDB read returned no item after write", (time.monotonic() - t0) * 1000

        # Verify integrity
        stored_hash = item.get("canary_payload")
        if stored_hash != payload["hash"]:
            return False, f"DDB integrity mismatch: wrote {payload['hash']}, read {stored_hash}", (time.monotonic() - t0) * 1000

        latency = (time.monotonic() - t0) * 1000
        return True, f"DDB round-trip OK ({latency:.0f}ms)", latency

    except Exception as e:
        return False, f"DDB exception: {e}", (time.monotonic() - t0) * 1000
    finally:
        # Always attempt cleanup
        try:
            table.delete_item(Key={"pk": CANARY_PK, "sk": sk})
        except Exception as e:
            print(f"[WARN] DDB canary cleanup failed: {e}")


# ── Check 2: S3 round-trip ────────────────────────────────────────────────────


def check_s3(canary_ts: str, payload: dict) -> tuple[bool, str, float]:
    """Write a synthetic object, read it back, verify content, delete."""
    s3_key = f"canary/{canary_ts}.json"
    body = json.dumps({"canary": True, "hash": payload["hash"], "ts": canary_ts})

    t0 = time.monotonic()
    try:
        # Write
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

        # Read back
        response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
        read_body = response["Body"].read().decode("utf-8")
        read_obj = json.loads(read_body)

        # Verify
        if read_obj.get("hash") != payload["hash"]:
            return False, "S3 integrity mismatch", (time.monotonic() - t0) * 1000

        latency = (time.monotonic() - t0) * 1000
        return True, f"S3 round-trip OK ({latency:.0f}ms)", latency

    except Exception as e:
        return False, f"S3 exception: {e}", (time.monotonic() - t0) * 1000
    finally:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        except Exception as e:
            print(f"[WARN] S3 canary cleanup failed: {e}")


# ── Check 3: MCP Lambda reachability ─────────────────────────────────────────


def get_mcp_api_key() -> str | None:
    """Fetch MCP API key from Secrets Manager.

    The MCP API key is stored as a raw string (not JSON) in
    life-platform/mcp-api-key. It is used to derive the HMAC Bearer token.
    """
    try:
        resp = secrets.get_secret_value(SecretId=MCP_SECRET)
        raw = resp["SecretString"]
        # Secret is stored as a raw string (the key itself), not JSON
        # Try JSON parse as fallback for legacy format
        try:
            secret_dict = json.loads(raw)
            return secret_dict.get("mcp_api_key") or secret_dict.get("MCP_API_KEY") or secret_dict.get("api_key")
        except (json.JSONDecodeError, AttributeError):
            return raw.strip()
    except Exception as e:
        print(f"[WARN] Could not fetch MCP API key: {e}")
        return None


def derive_mcp_bearer_token(api_key: str) -> str:
    """Derive the HMAC Bearer token from the MCP API key.

    R13-F14 + R13-F05: The MCP handler derives its expected Bearer token via:
      sig = hmac.new(api_key.encode(), b'life-platform-bearer-v1', sha256).hexdigest()
      token = f'lp_{sig}'
    The canary must use the same derivation — sending the raw api_key
    as an x-api-key header was the old bridge pattern and is no longer valid
    after R13-F05 made auth fail-closed.
    """
    sig = hmac.new(api_key.encode(), b"life-platform-bearer-v1", hashlib.sha256).hexdigest()
    return f"lp_{sig}"


def check_mcp(canary_ts: str) -> tuple[bool, str, float]:
    """
    Send a lightweight MCP ping to the Function URL.
    Uses the tools/list method (low cost, no data read) to verify Lambda is alive.
    """
    mcp_url = resolve_mcp_url()
    if not mcp_url:
        return None, "MCP Function URL unresolved — skipping", 0.0

    api_key = get_mcp_api_key()
    if not api_key:
        return None, "MCP API key unavailable — skipping", 0.0

    # MCP tools/list request — lowest-cost reachability check
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": f"canary-{canary_ts}",
            "params": {},
        }
    ).encode("utf-8")

    # Derive Bearer token (R13-F05: fail-closed auth requires HMAC Bearer, not raw x-api-key)
    bearer = derive_mcp_bearer_token(api_key)

    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            mcp_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")

        latency = (time.monotonic() - t0) * 1000

        if status != 200:
            return False, f"MCP returned HTTP {status}", latency

        # Verify response looks like a valid MCP tools/list response
        try:
            data = json.loads(body)
            tools = (data.get("result") or {}).get("tools") or []
            tool_count = len(tools)
            # ER-04 #395 (2026-07-08): registry audited down to 60 tools (docs/MCP_TOOL_AUDIT.md).
            # Floor sits just below the audited count — a partial/broken deploy shows far fewer;
            # any further audited prune must update this alongside the ledger.
            if tool_count < 55:
                return False, f"MCP tools/list returned only {tool_count} tools (expected ≥55)", latency
            return True, f"MCP reachable OK — {tool_count} tools listed ({latency:.0f}ms)", latency
        except (json.JSONDecodeError, AttributeError):
            # Response came back but wasn't parseable — Lambda alive but something wrong
            return False, f"MCP response unparseable: {body[:100]}", latency

    except urllib.error.HTTPError as e:
        return False, f"MCP HTTP error: {e.code} {e.reason}", (time.monotonic() - t0) * 1000
    except urllib.error.URLError as e:
        return False, f"MCP URL error: {e.reason}", (time.monotonic() - t0) * 1000
    except Exception as e:
        return False, f"MCP exception: {e}", (time.monotonic() - t0) * 1000


# ── Alerting ───────────────────────────────────────────────────────────────────

# ── Check 4: Anthropic API reachability (reentry sweep, 2026-05-03) ─────────


def check_anthropic(canary_ts: str) -> tuple[bool, str, float]:
    """Make a tiny (max_tokens=1) Bedrock call to verify Claude inference is live.

    ADR-062 (2026-05-27): migrated from direct Anthropic API to Bedrock. This
    canary now catches the Bedrock-equivalent failure modes:
      • AccessDeniedException — IAM lost bedrock:InvokeModel, OR the Anthropic
        use-case form was never submitted / lapsed (the gate that blocked the
        migration cutover). This is the new "key disabled / credits exhausted"
        equivalent — surfaces within 4h instead of via an F-grade brief.
      • ThrottlingException — account throughput limits.
      • ResourceNotFoundException — model/profile access revoked.

    Returns (None, msg, 0) if Bedrock client can't init (skip — not a failure).
    """
    t0 = time.monotonic()
    try:
        import botocore.exceptions as _bce
        from ai.bedrock_client import invoke as _bedrock_invoke
    except Exception as e:
        return None, f"bedrock_client import failed — skipping: {e}", 0.0

    body = {
        "model": ANTHROPIC_CANARY_MODEL,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "."}],
    }
    try:
        resp = _bedrock_invoke(body)
        latency = (time.monotonic() - t0) * 1000
        # Any well-formed response = inference path healthy.
        if resp.get("content"):
            return True, f"Bedrock OK ({ANTHROPIC_CANARY_MODEL}, {len(str(resp))}B)", latency
        return False, f"Bedrock returned no content: {str(resp)[:200]}", latency
    except _bce.ClientError as e:
        latency = (time.monotonic() - t0) * 1000
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", "")[:200]
        if code == "AccessDeniedException":
            return False, f"Bedrock access denied (IAM lost bedrock:InvokeModel OR Anthropic use-case form not submitted): {msg}", latency
        if code == "ThrottlingException":
            return False, f"Bedrock throttled: {msg}", latency
        if code == "ResourceNotFoundException":
            return False, f"Bedrock model/profile not found (access revoked?): {msg}", latency
        return False, f"Bedrock {code}: {msg}", latency
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return False, f"Bedrock error: {e}", latency


def count_canary_subscriber_rows(ddb_client) -> int:
    """#1954: READ-ONLY count of synthetic (source='canary') rows left in the
    real subscriber partition after cleanup.

    Query (not Scan) on the single partition, Select=COUNT (no item data
    leaves DDB), ConsistentRead so the row this run just deleted is not
    counted back. `source` is a DynamoDB reserved word, hence the
    ExpressionAttributeNames indirection. Pagination is bounded — never trust
    a LastEvaluatedKey to terminate the loop."""
    count = 0
    kwargs = {
        "TableName": TABLE_NAME,
        "KeyConditionExpression": "pk = :pk",
        "FilterExpression": "#src = :canary",
        "ExpressionAttributeNames": {"#src": "source"},
        "ExpressionAttributeValues": {":pk": {"S": SUBSCRIBERS_PK}, ":canary": {"S": "canary"}},
        "Select": "COUNT",
        "ConsistentRead": True,
    }
    for _ in range(CANARY_COUNT_MAX_PAGES):
        resp = ddb_client.query(**kwargs)
        count += int(resp.get("Count") or 0)
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return count


def check_subscribe_flow(canary_ts: str) -> tuple[bool, str, float, dict]:
    """Verify the subscriber-onboarding flow creates a DDB record in <5s.

    POSTs a throwaway email under the verified domain (canary+<ts>@mattsusername.com)
    to /api/subscribe via the live site-api Function URL, then verifies the
    USER#matthew#SOURCE#subscribers DDB partition has a new pending-confirmation
    record within 5s. Cleans up by deleting the canary record.

    Returns ``(ok, msg, latency_ms, extras)``.

    #2051 — the return is a 4-tuple because this one check answers TWO
    different questions and they must not share a verdict:

      * ``ok`` is the INFRA round-trip only: did the live /api/subscribe path
        accept a subscriber and did the row appear? That gates.
      * ``extras`` carries the STORED-STATE lane results keyed by check key
        (``subscribe_cleanup``, ``subscribe_residue``) — postconditions about
        rows sitting in the partition, possibly written weeks ago by an
        earlier run. Those never gate; the handler routes them into their own
        lane, metrics and first-occurrence alert.

    Returns (None, msg, 0, {}) on environment misconfig (skip).
    """
    import hashlib as _h

    canary_email = f"canary+{int(time.time())}@mattsusername.com"
    email_hash = _h.sha256(canary_email.lower().encode()).hexdigest()
    sk = f"EMAIL#{email_hash}"
    site_url = os.environ.get("SITE_URL", "https://averagejoematt.com")
    api_url = f"{site_url}/api/subscribe"

    t0 = time.monotonic()
    try:
        # POST the subscribe request
        body = json.dumps({"email": canary_email, "source": "canary"}).encode()
        req = urllib.request.Request(
            api_url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "life-platform-canary/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                api_status = resp.status
        except urllib.error.HTTPError as e:
            latency = (time.monotonic() - t0) * 1000
            return False, f"subscribe API HTTP {e.code}", latency, {}

        # Verify DDB record created
        ddb_client = boto3.client("dynamodb", region_name=REGION)
        rec_resp = ddb_client.get_item(
            TableName=TABLE_NAME,
            Key={"pk": {"S": "USER#matthew#SOURCE#subscribers"}, "sk": {"S": sk}},
        )
        item = rec_resp.get("Item")
        latency = (time.monotonic() - t0) * 1000

        if not item:
            return False, f"subscribe POST returned {api_status} but no DDB record for {sk[:40]}", latency, {}
        status_attr = item.get("status", {}).get("S", "?")
        if status_attr != "pending_confirmation":
            return False, f"subscribe record status='{status_attr}' (expected pending_confirmation)", latency, {}

        # ── Everything below here is STORED STATE, not deploy health (#2051) ──
        extras = {}

        # Cleanup: delete the canary record — the role has DeleteItem.
        # (The comment "IAM blocks DeleteItem" was wrong; the role has it since day 1.
        # The previous update_item approach was failing because UpdateItem is NOT granted.)
        # #2051: a failure here is now a REPORTED check of its own, not a lone
        # print. The silent cleanup failure is the root cause of the 12-day
        # stray row — #1954's counter only ever saw the aftermath.
        try:
            ddb_client.delete_item(
                TableName=TABLE_NAME,
                Key={"pk": {"S": SUBSCRIBERS_PK}, "sk": {"S": sk}},
            )
            extras["subscribe_cleanup"] = {"ok": True, "message": "canary subscriber row deleted"}
        except Exception as e:
            print(f"[WARN] subscribe canary cleanup delete failed: {e}")
            extras["subscribe_cleanup"] = {"ok": False, "message": f"cleanup delete failed — this run's synthetic row is now residue: {e}"}

        # #1954 postcondition: the partition must hold ZERO synthetic rows.
        # Fails loudly on any survivor (this run's or a previous run's) — and
        # fails too if the count itself is unreadable, because an unverifiable
        # assertion must never report green (ADR-104 posture).
        #
        # #2051: "loudly" now means alarm + first-occurrence email + a CI
        # warning, NOT a rollback. A survivor may have been written weeks
        # earlier by an unrelated run; reverting the code that just shipped
        # neither caused it nor deletes it. An unreadable count stays in this
        # lane for the same reason — what it asserts is about stored state.
        try:
            residue = count_canary_subscriber_rows(ddb_client)
        except Exception as e:
            extras["subscribe_residue"] = {
                "ok": False,
                "message": f"residue count failed (postcondition unverifiable): {e}",
                "residue_rows": None,
            }
            latency = (time.monotonic() - t0) * 1000
            return True, f"subscribe flow OK ({api_status}, DDB pending_confirmation in {round(latency)}ms)", latency, extras

        emit("CanarySubscribeResidueRows", residue)  # positive confirmation: 0 on every clean run
        extras["subscribe_residue"] = {
            "ok": residue == 0,
            "message": (
                "0 synthetic canary rows in the subscriber partition"
                if residue == 0
                else f"{residue} synthetic canary row(s) survived cleanup in the subscriber partition — delete them (#1954)"
            ),
            "residue_rows": residue,
        }
        latency = (time.monotonic() - t0) * 1000
        return True, f"subscribe flow OK ({api_status}, DDB pending_confirmation in {round(latency)}ms)", latency, extras
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return False, f"subscribe canary error: {e}", latency, {}


def send_alert(failures: list[dict], canary_ts: str, dry_run: bool = False) -> None:
    rows = ""
    for f in failures:
        # #2051: name the lane in the email. "Canary failed" was ambiguous
        # between "the platform is down" and "a test row needs deleting" —
        # and the reader of this email is the person who has to tell them apart.
        lane = f.get("lane", LANE_INFRA)
        lane_note = (
            "infra — gates deploys" if lane == LANE_INFRA else "stored state — does NOT gate deploys; needs a data fix, not a rollback"
        )
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #333;">{f['check']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #333;color:#888;font-size:12px;">{lane_note}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #333;color:#ff6b6b;">{f['message']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head><style>
  body {{ font-family: -apple-system, Arial, sans-serif; background: #1a1a1a; color: #e0e0e0; padding: 20px; }}
  .container {{ max-width: 700px; margin: 0 auto; background: #242424; border-radius: 8px; padding: 24px; }}
  h2 {{ color: #ff6b6b; margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th {{ text-align: left; padding: 8px 12px; background: #333; color: #aaa; font-size: 12px; text-transform: uppercase; }}
  .footer {{ margin-top: 16px; font-size: 12px; color: #666; }}
</style></head>
<body><div class="container">
  <h2>🔴 Canary Failure — {len(failures)} check{'s' if len(failures) > 1 else ''} failed</h2>
  <p style="color:#aaa;">Synthetic health check at {canary_ts} UTC detected failures:</p>
  <table>
    <tr><th>Check</th><th>Lane</th><th>Error</th></tr>
    {rows}
  </table>
  <div class="footer">
    Lambda: life-platform-canary |
    <a href="https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#dashboards:name=life-platform-ops" style="color:#888;">Dashboard</a>
  </div>
</div></body></html>"""

    try:
        guarded_send_email(
            ses,
            dry_run,
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Content={
                "Simple": {
                    "Subject": {"Data": f"🔴 Life Platform canary: {len(failures)} failure(s) at {canary_ts[:16]}"},
                    "Body": {"Html": {"Data": html}},
                }
            },
        )
        print(f"Alert sent: {len(failures)} failures")
    except Exception as e:
        print(f"[WARN] SES alert failed: {e}")


# ── Handler ────────────────────────────────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:  # Phase 4.12 type hints
    dry_run = is_dry_run(event)
    try:
        canary_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Generate a unique payload hash for this canary run
        payload_hash = hashlib.sha256(f"canary-{canary_ts}".encode()).hexdigest()[:16]
        payload = {"hash": payload_hash, "ts": canary_ts}

        # R13-F14: mcp_only=true skips DDB/S3 for the 15-min MCP probe
        mcp_only = event.get("mcp_only", False)
        mode = "mcp-only" if mcp_only else "full"
        print(f"Canary run ({mode}): {canary_ts} | hash={payload_hash}")

        results = {}
        failures = []

        def record(check_key: str, ok, message: str, latency_ms: float = 0.0) -> None:
            """Store one check result + its lane, and enroll a failure.

            #2051: the lane comes from operational/canary_lanes.py — the ONLY
            place the gating question is answered. `ok is None` means skipped
            (never a failure in either lane).
            """
            lane = lane_for(check_key)
            results[check_key] = {"ok": ok, "message": message, "latency_ms": round(latency_ms), "lane": lane}
            if ok is False:
                failures.append({"check": label_for(check_key), "check_key": check_key, "lane": lane, "message": message})

        if not mcp_only:
            # ── DynamoDB check ──────────────────────────────────────────────────────
            ddb_ok, ddb_msg, ddb_ms = check_dynamodb(canary_ts, payload)
            record("dynamodb", ddb_ok, ddb_msg, ddb_ms)
            print(f"  DDB:  {'✅' if ddb_ok else '❌'} {ddb_msg}")
            emit("CanaryDDBPass" if ddb_ok else "CanaryDDBFail", 1)
            emit("CanaryLatencyDDB_ms", ddb_ms, "Milliseconds")

            # ── S3 check ────────────────────────────────────────────────────────────
            s3_ok, s3_msg, s3_ms = check_s3(canary_ts, payload)
            record("s3", s3_ok, s3_msg, s3_ms)
            print(f"  S3:   {'✅' if s3_ok else '❌'} {s3_msg}")
            emit("CanaryS3Pass" if s3_ok else "CanaryS3Fail", 1)
            emit("CanaryLatencyS3_ms", s3_ms, "Milliseconds")

        # ── MCP check ───────────────────────────────────────────────────────────
        mcp_ok, mcp_msg, mcp_ms = check_mcp(canary_ts)
        if mcp_ok is not None:  # None = skipped
            record("mcp", mcp_ok, mcp_msg, mcp_ms)
            print(f"  MCP:  {'✅' if mcp_ok else '❌'} {mcp_msg}")
            emit("CanaryMCPPass" if mcp_ok else "CanaryMCPFail", 1)
            emit("CanaryLatencyMCP_ms", mcp_ms, "Milliseconds")
        else:
            record("mcp", None, mcp_msg, 0)
            print(f"  MCP:  ⚪ {mcp_msg}")

        # ── Anthropic API check ─────────────────────────────────────────────────
        # Skip on mcp_only runs (the 15-min MCP probe) — the 4h full pass is
        # frequent enough for billing/auth detection, and Anthropic per-key rate
        # limits could theoretically throttle a 15-min cadence.
        if not mcp_only:
            ant_ok, ant_msg, ant_ms = check_anthropic(canary_ts)
            if ant_ok is not None:
                record("anthropic", ant_ok, ant_msg, ant_ms)
                print(f"  Anthropic: {'✅' if ant_ok else '❌'} {ant_msg}")
                emit("CanaryAnthropicPass" if ant_ok else "CanaryAnthropicFail", 1)
                emit("CanaryLatencyAnthropic_ms", ant_ms, "Milliseconds")
            else:
                record("anthropic", None, ant_msg, 0)
                print(f"  Anthropic: ⚪ {ant_msg}")

        # ── Subscribe flow check ────────────────────────────────────────────────
        # P0.3 (2026-05-24): synthetic subscriber via /api/subscribe + DDB read.
        # Skipped on mcp_only runs — full pass is enough cadence to catch a broken
        # onboarding flow within 4h.
        if not mcp_only:
            sub_ok, sub_msg, sub_ms, sub_extras = check_subscribe_flow(canary_ts)
            if sub_ok is not None:
                record("subscribe", sub_ok, sub_msg, sub_ms)
                print(f"  Subscribe: {'✅' if sub_ok else '❌'} {sub_msg}")
                emit("CanarySubscribePass" if sub_ok else "CanarySubscribeFail", 1)
                emit("CanaryLatencySubscribe_ms", sub_ms, "Milliseconds")

            # ── Stored-state postconditions (#2051) ─────────────────────────
            # Same subscribe probe, different question: what is sitting in the
            # partition. Own results, own metrics, own alarms — and, crucially,
            # own lane, so a row written twelve days ago cannot revert today's
            # deploy (2026-08-02 incident).
            for extra_key, extra_metric in (
                ("subscribe_cleanup", "CanarySubscribeCleanup"),
                ("subscribe_residue", "CanarySubscribeResidue"),
            ):
                extra = sub_extras.get(extra_key)
                if not extra:
                    continue
                extra_ok = extra.get("ok")
                record(extra_key, extra_ok, extra.get("message", ""))
                if extra.get("residue_rows") is not None:
                    results[extra_key]["residue_rows"] = extra["residue_rows"]
                print(f"  {label_for(extra_key)}: {'✅' if extra_ok else '❌'} {extra.get('message', '')}")
                emit(f"{extra_metric}Pass" if extra_ok else f"{extra_metric}Fail", 1)

        # ── Alert only if the SAME check has failed in 2 consecutive runs ──────
        # Persistence is what's load-bearing; transient blips (Anthropic 503,
        # MCP cold start) shouldn't email the operator. State is kept in DDB at
        # USER#system / CANARY#last_state — read previous failed checks, alert
        # only on the intersection, then persist current.
        current_failed = sorted({f["check"] for f in failures})
        try:
            _state_key = {"pk": {"S": "USER#system"}, "sk": {"S": "CANARY#last_state"}}
            _ddb_cli = boto3.client("dynamodb", region_name=REGION)
            _prev = _ddb_cli.get_item(TableName=TABLE_NAME, Key=_state_key).get("Item") or {}
            prev_failed = set((_prev.get("failed_checks", {}).get("SS") or []))
            # Persist current state for the next run's comparison
            _ddb_cli.put_item(
                TableName=TABLE_NAME,
                Item={
                    **_state_key,
                    "failed_checks": {"SS": current_failed} if current_failed else {"SS": ["__none__"]},
                    "ts": {"S": canary_ts},
                },
            )
        except Exception as _se:
            print(f"[WARN] canary state read/write failed (defaulting to no-alert): {_se}")
            prev_failed = set()

        # #2051: the two-consecutive-runs suppression is right for INFRA checks
        # (a Bedrock 503 or an MCP cold start is genuinely transient) and wrong
        # for stored state — a leftover row is not a blip, it is a fact that
        # persists until someone deletes it, and it no longer has a rollback to
        # make it loud. So stored-state failures alert on FIRST occurrence.
        persistent_failures = [f for f in failures if f["check"] in prev_failed]
        _persistent_keys = {f["check"] for f in persistent_failures}
        first_occurrence_stored_state = [f for f in failures if f["lane"] == LANE_STORED_STATE and f["check"] not in _persistent_keys]
        to_alert = persistent_failures + first_occurrence_stored_state
        if to_alert:
            print(
                f"  Sending alert: {len(persistent_failures)} persistent + "
                f"{len(first_occurrence_stored_state)} first-occurrence stored-state failure(s)"
            )
            send_alert(to_alert, canary_ts, dry_run=dry_run)
        elif failures:
            print(f"  Suppressed first-occurrence alert ({len(failures)} new infra failure(s)); will alert if repeat next run")

        # ── Lane verdicts (#2051) ───────────────────────────────────────────
        # Derived from `results` itself, so the lane counts and the reported
        # checks can never disagree.
        counts = lane_counts(results)
        infra_failed = counts.get(LANE_INFRA, 0)
        stored_state_failed = counts.get(LANE_STORED_STATE, 0)
        all_ok = len(failures) == 0
        print(
            f"Canary complete: {'ALL PASS ✅' if all_ok else f'{len(failures)} FAILURES ❌'} "
            f"(infra {infra_failed}, stored-state {stored_state_failed})"
        )

        return {
            # statusCode is the INFRA verdict: it is what the CI smoke oracle
            # may act on, and the only thing a rollback could plausibly fix.
            # The body below stays fully honest about both lanes.
            "statusCode": 200 if infra_failed == 0 else 500,
            "body": json.dumps(
                {
                    "canary_ts": canary_ts,
                    # Union across both lanes — unchanged meaning, still false
                    # whenever anything at all failed.
                    "all_pass": all_ok,
                    "failures": len(failures),
                    # #1921's key, published by qa-smoke too: the ONLY count the
                    # smoke oracle gates on.
                    "failed_deploy_health": infra_failed,
                    # Loud, alarmed, emailed — never gating.
                    "failed_stored_state": stored_state_failed,
                    "lanes": lane_summary(results),
                    "results": results,
                }
            ),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
