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

import json
import os
import time
import hashlib
import hmac
import urllib.request
import urllib.error
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("canary")
except ImportError:
    logger = logging.getLogger("canary")
    logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────────────────────────
REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET  = os.environ["S3_BUCKET"]
MCP_URL    = os.environ.get("MCP_FUNCTION_URL", "")   # set from deploy script
MCP_SECRET = os.environ.get("MCP_SECRET_NAME", "life-platform/mcp-api-key")
SENDER     = os.environ["EMAIL_SENDER"]
RECIPIENT  = os.environ["EMAIL_RECIPIENT"]

CANARY_PK  = "CANARY#matthew"

# ── AWS clients ────────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(TABLE_NAME)
s3       = boto3.client("s3", region_name=REGION)
ses      = boto3.client("sesv2", region_name=REGION)
cw       = boto3.client("cloudwatch", region_name=REGION)
secrets  = boto3.client("secretsmanager", region_name=REGION)

CW_NAMESPACE = "LifePlatform/Canary"


# ── Metric emission ────────────────────────────────────────────────────────────

def emit(metric_name: str, value: float, unit: str = "Count"):
    try:
        cw.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
                "Timestamp": datetime.now(timezone.utc),
            }],
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
            return (secret_dict.get("mcp_api_key")
                    or secret_dict.get("MCP_API_KEY")
                    or secret_dict.get("api_key"))
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
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": f"canary-{canary_ts}",
        "params": {},
    }).encode("utf-8")

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

def lambda_handler(event, context):
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

        # ── Alert if any failures ───────────────────────────────────────────────
        if failures:
            print(f"  Sending alert: {len(failures)} failure(s)")
            send_alert(failures, canary_ts)

        all_ok = len(failures) == 0
        print(f"Canary complete: {'ALL PASS ✅' if all_ok else f'{len(failures)} FAILURES ❌'}")

        return {
            "statusCode": 200 if all_ok else 500,
            "body": json.dumps({
                "canary_ts": canary_ts,
                "all_pass": all_ok,
                "failures": len(failures),
                "results": results,
            }),
        }
    except Exception as e:
        logger.error("lambda_handler failed: %s", e, exc_info=True)
        raise
