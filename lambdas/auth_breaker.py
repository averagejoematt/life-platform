"""
auth_breaker.py — Phase 3.6 (2026-05-16): standalone OAuth/auth-failure circuit
breaker.

Extracted from ingestion_framework.py so non-framework ingestion Lambdas (Whoop,
Garmin, Strava, etc. — none of which use SIMP-2 today) can opt in without full
framework migration. ADR-052 explains the design.

The circuit breaker writes a DDB marker on the first 401/403 failure. While the
marker is fresh (<24h), subsequent invocations short-circuit and never reach
the source API. A single alert fires on the first failure; further alarm spam
is suppressed for 24h until the operator rotates the credential.

The marker auto-expires via DDB TTL (table-level TTL on the `ttl` attribute is
already enabled — Phase 1.7).

Usage in an existing Lambda:

    from auth_breaker import check_breaker, mark_failure, clear_failure, looks_like_auth_failure

    def lambda_handler(event, context):
        marker = check_breaker(table, source_name="whoop", user_id=USER_ID, logger=logger)
        if marker:
            return {"statusCode": 200, "body": json.dumps({
                "skipped": "auth_failure_circuit_breaker",
                "marked_at": marker.get("marked_at"),
                "error": marker.get("error"),
            })}
        try:
            do_ingestion()
            clear_failure(table, source_name="whoop", user_id=USER_ID, logger=logger)
        except Exception as e:
            if looks_like_auth_failure(e):
                mark_failure(table, source_name="whoop", user_id=USER_ID, error_msg=e, logger=logger)
            raise

This module is in `lambdas/` so it's bundled with every Lambda via the CDK
asset packager. No layer rebuild needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

_AUTH_FAIL_SK = "AUTH_FAILURE"
_AUTH_FAIL_TTL_SECONDS = 24 * 3600  # 24 hours

_AUTH_FAIL_HTTP_CODES = ("401", "403")
_AUTH_FAIL_KEYWORDS = (
    "unauthorized",
    "forbidden",
    "invalid token",
    "expired token",
    "token expired",
    "auth failed",
    "authentication failed",
)


_METRIC_NAMESPACE = "LifePlatform/OAuth"
_METRIC_NAME = "IngestAuthHealthy"


def _emit_auth_health(healthy: int, source_name: str, logger) -> None:
    """Emit IngestAuthHealthy (1 = auth working this run, 0 = broken / breaker
    short-circuited) so a tripped breaker on ANY source is alarmable.

    This closes the same silent-death gap that hid the Garmin/Strava deaths: a
    tripped breaker returns a healthy-looking 200 "skip", so the freshness /
    error heartbeat reads green while the source is suppressed for 24h. Emitting
    a 0 on every mark + short-circuit makes that visible.

    Dimensionless on purpose — one fleet-wide alarm (Min < 1) catches whichever
    source goes unhealthy; the source name goes to the log for diagnosis.
    Best-effort: never raises (a metric hiccup must not break ingestion).
    Ingestion roles already hold cloudwatch:PutMetricData (role_policies
    _ingestion_base), so no IAM change is required.
    """
    try:
        import boto3

        boto3.client("cloudwatch").put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=[{"MetricName": _METRIC_NAME, "Value": healthy, "Unit": "None"}],
        )
    except Exception as e:  # noqa: BLE001 — observability is best-effort
        if logger:
            logger.warning(f"auth_breaker_metric_failed source={source_name}: {e}")


def looks_like_auth_failure(exc: Exception) -> bool:
    """Heuristic: does this exception indicate an OAuth/API auth failure?"""
    msg = str(exc).lower()
    if any(code in msg for code in _AUTH_FAIL_HTTP_CODES):
        return True
    if any(kw in msg for kw in _AUTH_FAIL_KEYWORDS):
        return True
    # urllib.error.HTTPError exposes .code
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return True
    return False


def _pk(source_name: str, user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#{source_name}"


def check_breaker(table, source_name: str, user_id: str, logger) -> dict | None:
    """Return the active marker if one exists and is still fresh, else None."""
    try:
        resp = table.get_item(Key={"pk": _pk(source_name, user_id), "sk": _AUTH_FAIL_SK})
    except Exception as e:
        if logger:
            logger.warning(f"auth_breaker_lookup_failed source={source_name}: {e}")
        return None
    item = resp.get("Item")
    if not item:
        return None
    marked_at_iso = item.get("marked_at")
    if not marked_at_iso:
        return None
    try:
        marked_at = datetime.fromisoformat(marked_at_iso)
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - marked_at).total_seconds()
    if age >= _AUTH_FAIL_TTL_SECONDS:
        return None
    # Breaker is tripped and this run is being short-circuited (returns a 200
    # "skip" to EventBridge). Emit 0 so the suppression is visible, not silent.
    _emit_auth_health(0, source_name, logger)
    return item


def mark_failure(table, source_name: str, user_id: str, error_msg, logger) -> None:
    """Write the auth-failure marker with a 24h DDB TTL."""
    now = datetime.now(timezone.utc)
    item = {
        "pk": _pk(source_name, user_id),
        "sk": _AUTH_FAIL_SK,
        "marked_at": now.isoformat(),
        "error": str(error_msg)[:500],
        "ttl": int(now.timestamp()) + _AUTH_FAIL_TTL_SECONDS,
    }
    try:
        table.put_item(Item=item)
        if logger:
            logger.warning(f"auth_breaker_marked source={source_name} ttl=24h")
    except Exception as e:
        if logger:
            logger.warning(f"auth_breaker_mark_failed source={source_name}: {e}")
    # Auth just broke → unhealthy, regardless of whether the marker write stuck.
    _emit_auth_health(0, source_name, logger)


def clear_failure(table, source_name: str, user_id: str, logger) -> None:
    """Remove the marker after a successful run."""
    try:
        table.delete_item(Key={"pk": _pk(source_name, user_id), "sk": _AUTH_FAIL_SK})
    except Exception as e:
        if logger:
            logger.warning(f"auth_breaker_clear_failed source={source_name}: {e}")
    # Successful run → auth is healthy. Emitted every success so the alarm has a
    # steady 1 baseline and self-clears once a previously-broken source recovers.
    _emit_auth_health(1, source_name, logger)
