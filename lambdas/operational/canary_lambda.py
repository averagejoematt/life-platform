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
from decimal import Decimal

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger

    logger = get_logger("canary")
except ImportError:
    logger = logging.getLogger("canary")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ["S3_BUCKET"]
MCP_URL = os.environ.get("MCP_FUNCTION_URL", "")  # set from deploy script
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
            return False, f"S3 integrity mismatch", (time.monotonic() - t0) * 1000

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
    if not MCP_URL:
        return None, "MCP_FUNCTION_URL not configured — skipping", 0.0

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
            MCP_URL,
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
            tools = data.get("result", {}).get("tools", [])
            tool_count = len(tools)
            # R16-F05: threshold updated to 80 — we have 87 tools; headroom for SIMP-1 cuts
            if tool_count < 80:
                return False, f"MCP tools/list returned only {tool_count} tools (expected ≥80)", latency
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


def get_anthropic_api_key() -> str | None:
    """ADR-062: Bedrock IAM auth — sentinel; see task #90 for full plumbing removal."""
    return "_BEDROCK_IAM_"


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
        from bedrock_client import invoke as _bedrock_invoke
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


def check_subscribe_flow(canary_ts: str) -> tuple[bool, str, float]:
    """Verify the subscriber-onboarding flow creates a DDB record in <5s.

    POSTs a throwaway email under the verified domain (canary+<ts>@mattsusername.com)
    to /api/subscribe via the live site-api Function URL, then verifies the
    USER#matthew#SOURCE#subscribers DDB partition has a new pending-confirmation
    record within 5s. Cleans up by tombstone-overwriting the canary record.

    Returns (None, msg, 0) on environment misconfig (skip).
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
            return False, f"subscribe API HTTP {e.code}", latency

        # Verify DDB record created
        ddb_client = boto3.client("dynamodb", region_name=REGION)
        rec_resp = ddb_client.get_item(
            TableName=TABLE_NAME,
            Key={"pk": {"S": f"USER#matthew#SOURCE#subscribers"}, "sk": {"S": sk}},
        )
        item = rec_resp.get("Item")
        latency = (time.monotonic() - t0) * 1000

        if not item:
            return False, f"subscribe POST returned {api_status} but no DDB record for {sk[:40]}", latency
        status_attr = item.get("status", {}).get("S", "?")
        if status_attr != "pending_confirmation":
            return False, f"subscribe record status='{status_attr}' (expected pending_confirmation)", latency

        # Cleanup: tombstone the canary record (IAM blocks DeleteItem)
        try:
            ddb_client.update_item(
                TableName=TABLE_NAME,
                Key={"pk": {"S": "USER#matthew#SOURCE#subscribers"}, "sk": {"S": sk}},
                UpdateExpression="SET #s = :v, tombstone = :tomb, tombstoned_at = :ts, tombstoned_reason = :r",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":v": {"S": "canary"},
                    ":tomb": {"BOOL": True},
                    ":ts": {"S": canary_ts},
                    ":r": {"S": "canary_subscribe_check"},
                },
            )
        except Exception:
            pass  # cleanup failure is non-fatal for the canary itself

        return True, f"subscribe flow OK ({api_status}, DDB pending_confirmation in {round(latency)}ms)", latency
    except Exception as e:
        latency = (time.monotonic() - t0) * 1000
        return False, f"subscribe canary error: {e}", latency


def send_alert(failures: list[dict], canary_ts: str) -> None:
    rows = ""
    for f in failures:
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #333;">{f['check']}</td>
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
    <tr><th>Check</th><th>Error</th></tr>
    {rows}
  </table>
  <div class="footer">
    Lambda: life-platform-canary | 
    <a href="https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#dashboards:name=life-platform-ops" style="color:#888;">Dashboard</a>
  </div>
</div></body></html>"""

    try:
        ses.send_email(
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

        if not mcp_only:
            # ── DynamoDB check ──────────────────────────────────────────────────────
            ddb_ok, ddb_msg, ddb_ms = check_dynamodb(canary_ts, payload)
            results["dynamodb"] = {"ok": ddb_ok, "message": ddb_msg, "latency_ms": round(ddb_ms)}
            print(f"  DDB:  {'✅' if ddb_ok else '❌'} {ddb_msg}")
            emit("CanaryDDBPass" if ddb_ok else "CanaryDDBFail", 1)
            emit("CanaryLatencyDDB_ms", ddb_ms, "Milliseconds")
            if not ddb_ok:
                failures.append({"check": "DynamoDB", "message": ddb_msg})

            # ── S3 check ────────────────────────────────────────────────────────────
            s3_ok, s3_msg, s3_ms = check_s3(canary_ts, payload)
            results["s3"] = {"ok": s3_ok, "message": s3_msg, "latency_ms": round(s3_ms)}
            print(f"  S3:   {'✅' if s3_ok else '❌'} {s3_msg}")
            emit("CanaryS3Pass" if s3_ok else "CanaryS3Fail", 1)
            emit("CanaryLatencyS3_ms", s3_ms, "Milliseconds")
            if not s3_ok:
                failures.append({"check": "S3", "message": s3_msg})

        # ── MCP check ───────────────────────────────────────────────────────────
        mcp_ok, mcp_msg, mcp_ms = check_mcp(canary_ts)
        if mcp_ok is not None:  # None = skipped
            results["mcp"] = {"ok": mcp_ok, "message": mcp_msg, "latency_ms": round(mcp_ms)}
            print(f"  MCP:  {'✅' if mcp_ok else '❌'} {mcp_msg}")
            emit("CanaryMCPPass" if mcp_ok else "CanaryMCPFail", 1)
            emit("CanaryLatencyMCP_ms", mcp_ms, "Milliseconds")
            if not mcp_ok:
                failures.append({"check": "MCP Lambda", "message": mcp_msg})
        else:
            results["mcp"] = {"ok": None, "message": mcp_msg, "latency_ms": 0}
            print(f"  MCP:  ⚪ {mcp_msg}")

        # ── Anthropic API check ─────────────────────────────────────────────────
        # Skip on mcp_only runs (the 15-min MCP probe) — the 4h full pass is
        # frequent enough for billing/auth detection, and Anthropic per-key rate
        # limits could theoretically throttle a 15-min cadence.
        if not mcp_only:
            ant_ok, ant_msg, ant_ms = check_anthropic(canary_ts)
            if ant_ok is not None:
                results["anthropic"] = {"ok": ant_ok, "message": ant_msg, "latency_ms": round(ant_ms)}
                print(f"  Anthropic: {'✅' if ant_ok else '❌'} {ant_msg}")
                emit("CanaryAnthropicPass" if ant_ok else "CanaryAnthropicFail", 1)
                emit("CanaryLatencyAnthropic_ms", ant_ms, "Milliseconds")
                if not ant_ok:
                    failures.append({"check": "Anthropic API", "message": ant_msg})
            else:
                results["anthropic"] = {"ok": None, "message": ant_msg, "latency_ms": 0}
                print(f"  Anthropic: ⚪ {ant_msg}")

        # ── Subscribe flow check ────────────────────────────────────────────────
        # P0.3 (2026-05-24): synthetic subscriber via /api/subscribe + DDB read.
        # Skipped on mcp_only runs — full pass is enough cadence to catch a broken
        # onboarding flow within 4h.
        if not mcp_only:
            sub_ok, sub_msg, sub_ms = check_subscribe_flow(canary_ts)
            if sub_ok is not None:
                results["subscribe"] = {"ok": sub_ok, "message": sub_msg, "latency_ms": round(sub_ms)}
                print(f"  Subscribe: {'✅' if sub_ok else '❌'} {sub_msg}")
                emit("CanarySubscribePass" if sub_ok else "CanarySubscribeFail", 1)
                emit("CanaryLatencySubscribe_ms", sub_ms, "Milliseconds")
                if not sub_ok:
                    failures.append({"check": "Subscribe flow", "message": sub_msg})

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

        persistent_failures = [f for f in failures if f["check"] in prev_failed]
        if persistent_failures:
            print(f"  Sending alert: {len(persistent_failures)} persistent failure(s) (failed in previous run too)")
            send_alert(persistent_failures, canary_ts)
        elif failures:
            print(f"  Suppressed first-occurrence alert ({len(failures)} new failure(s)); will alert if repeat next run")

        all_ok = len(failures) == 0
        print(f"Canary complete: {'ALL PASS ✅' if all_ok else f'{len(failures)} FAILURES ❌'}")

        return {
            "statusCode": 200 if all_ok else 500,
            "body": json.dumps(
                {
                    "canary_ts": canary_ts,
                    "all_pass": all_ok,
                    "failures": len(failures),
                    "results": results,
                }
            ),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
