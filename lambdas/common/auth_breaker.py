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

    from common.auth_breaker import check_breaker, mark_failure, clear_failure, looks_like_auth_failure

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
_SOURCE_DIMENSION = "Source"


def auth_health_metric_data(healthy: int, source_name: str) -> list:
    """The MetricData payload every auth-health emission writes (#1960).

    TWO datapoints, one PutMetricData call — deliberately, not redundantly:

      * **dimensionless** — the fleet-wide stream the existing
        `ingest-auth-unhealthy-24h` alarm reads (Min < 1 over 24h fires if ANY
        breaker source went unhealthy). CloudWatch treats a dimensioned metric
        and its dimensionless namesake as two SEPARATE metrics, so *replacing*
        the dimensionless emission with a dimensioned one would have silently
        blinded that alarm the moment this shipped. It stays, byte-identical.
      * **Source=<name>** — the new per-source stream. Until #1960 the metric was
        dimensionless "on purpose" (source name to the log only), which meant the
        URGENT page could not name WHICH OAuth source died, and made the
        remediation agent's "duplicate, covered by source-specific alarms" ack
        factually wrong for every source outside the 5-alarm consecutive-failures
        set. The per-source `ingest-auth-unhealthy-{src}` alarms in
        monitoring_stack.py read this stream.

    Split out (and public) so the unit tests can assert the dimension contract
    without patching boto3.
    """
    point = {"MetricName": _METRIC_NAME, "Value": healthy, "Unit": "None"}
    dimensioned = dict(point, Dimensions=[{"Name": _SOURCE_DIMENSION, "Value": str(source_name)}])
    return [point, dimensioned]


def _emit_auth_health(healthy: int, source_name: str, logger) -> None:
    """Emit IngestAuthHealthy (1 = auth working this run, 0 = broken / breaker
    short-circuited) so a tripped breaker on ANY source is alarmable.

    This closes the same silent-death gap that hid the Garmin/Strava deaths: a
    tripped breaker returns a healthy-looking 200 "skip", so the freshness /
    error heartbeat reads green while the source is suppressed for 24h. Emitting
    a 0 on every mark + short-circuit makes that visible.

    Emitted BOTH dimensionless (the fleet aggregate) and with Source=<name> (so
    the page names the culprit) — see auth_health_metric_data for why both.
    Best-effort: never raises (a metric hiccup must not break ingestion).
    Ingestion roles already hold cloudwatch:PutMetricData (role_policies
    _ingestion_base), so no IAM change is required.
    """
    try:
        import boto3

        boto3.client("cloudwatch").put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=auth_health_metric_data(healthy, source_name),
        )
    except Exception as e:  # noqa: BLE001 — observability is best-effort
        if logger:
            logger.warning(f"auth_breaker_metric_failed source={source_name}: {e}")


def mark_as_auth_failure(exc: Exception) -> Exception:
    """Attach an EXPLICIT, call-site-asserted auth-failure classification to
    `exc` and return it (typical use: `mark_as_auth_failure(e); raise` —
    mutate then bare-`raise` so the original traceback is preserved).

    #2069: the generic 401/403 + keyword heuristic below is deliberately NOT
    extended to recognize a bare '400' — a data-fetch 400 is not an auth
    failure, and adding '400' to the code list would misclassify it. But some
    call sites know MORE than the status code: whoop_lambda.authenticate()
    gets a 400 from the TOKEN endpoint, re-reads the stored secret to rule out
    a concurrent invocation having already rotated it, and only THEN concludes
    "genuine auth failure" — logging exactly that. That conclusion is real
    information the generic heuristic can't see from the exception alone, so
    the call site marks it explicitly instead of the classifier guessing.

    `looks_like_auth_failure` checks for this marker FIRST, before falling
    back to the generic heuristic. Best-effort: some exception types may
    reject attribute assignment (e.g. a class using `__slots__`); a failure to
    mark is swallowed rather than raised — the caller's real exception must
    still propagate.
    """
    try:
        exc.auth_context = True  # type: ignore[attr-defined]
    except Exception:
        pass
    return exc


def looks_like_auth_failure(exc: Exception) -> bool:
    """Heuristic: does this exception indicate an OAuth/API auth failure?

    Checks, in order:
      1. An explicit call-site classification via `mark_as_auth_failure` —
         see that function's docstring for why this exists (#2069).
      2. The generic 401/403 + keyword heuristic (unchanged).
    """
    if getattr(exc, "auth_context", False):
        return True
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
