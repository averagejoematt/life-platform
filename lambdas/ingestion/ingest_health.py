"""
ingest_health.py — infra-liveness decision core for ingestion sources (ER-01).

The existing `freshness_checker` + `slo-source-freshness` alarm are *behavioral*
checks: "is the newest DATE# record recent?". On a personal platform that signal is
structurally ambiguous — "no new data" can mean the user didn't log / didn't wear the
device (benign) OR the ingestion Lambda has been erroring on every run for weeks
(critical). That ambiguity is exactly why the 2026 Garmin outage ran 44 days unseen.

The missing signal is **infra-liveness, not data-freshness**: for each active
OAuth/API source, did the ingestion Lambda *run and complete its upstream fetch
without error* on its expected schedule — independent of whether new data came back?
A source whose API 200s but returns an empty set is healthy; a source whose OAuth
refresh has been 401-ing for a week is dead even if the user also happened not to log.

This module is the pure decision core (no AWS, no I/O) so it is fully offline-testable:

  - classify_error(exc)            → one of auth / throttle / transport / parse
  - update_outcome(prev, ...)      → the next INGEST_HEALTH sentinel (streak math)
  - evaluate_source_health(s, ...) → ok / stale / failing verdict (+ alert flag)
  - emf_metric_line(...)           → an EMF log line CloudWatch extracts to a metric

`ingestion_framework.run_ingestion()` writes the sentinel + EMF at every terminal
path; `pipeline_health_check_lambda` reads the sentinels and evaluates them daily.
The two metrics (behavioral StaleSourceCount, infra UnhealthySourceCount) stay
separate, with separate alarms — the S-06(b) split, now mandatory.
"""

from __future__ import annotations

import json

# ── Constants ────────────────────────────────────────────────────────────────

SYSTEM_PK = "USER#system"
ERROR_CLASSES = ("auth", "throttle", "transport", "parse", "none")

# Default streak length before a *failing* (running-but-erroring) source alerts.
# Mirrors the canary's 2-consecutive-fail buffer precedent — a single blip stays
# silent; a sustained streak of the same failure class is the real signal.
DEFAULT_FAILURE_STREAK_THRESHOLD = 3

# Default staleness budget (minutes) for the *attempt-staleness* arm — i.e. "the
# cron silently stopped / the Lambda hasn't run". Deliberately generous: every
# active source runs at least once per day, and overnight gaps (hourly sources
# pause 10 PM–4 AM) must NOT false-fire. ~26h catches "hasn't run in over a day"
# (de-scheduled / dead) while the streak arm catches "running but erroring" fast.
DEFAULT_MAX_ATTEMPT_GAP_MINUTES = 1560  # 26 hours

EMF_NAMESPACE = "LifePlatform/IngestLiveness"


def ingest_health_sk(source: str) -> str:
    """SK for a source's liveness sentinel under the USER#system partition."""
    return f"INGEST_HEALTH#{source}"


# ── Error classification ──────────────────────────────────────────────────────

_AUTH_TOKENS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "invalid token",
    "expired token",
    "token expired",
    "auth failed",
    "authentication failed",
    "invalid_grant",
    "invalid_client",
)
_THROTTLE_TOKENS = ("429", "rate limit", "rate-limit", "ratelimit", "too many requests", "throttl", "quota")
_PARSE_TOKENS = ("jsondecode", "expecting value", "keyerror", "schema", "unexpected key", "no records after transform")
_TRANSPORT_TOKENS = (
    "timeout",
    "timed out",
    "connection",
    "network",
    "urlerror",
    "name resolution",
    "reset by peer",
    "500",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
)


def classify_error(exc) -> str:
    """Map an exception (or error string) to one of ERROR_CLASSES (minus 'none').

    Order matters: throttle (429) before auth, because a 429 string can co-occur
    with retry/auth wording; parse before transport; transport is the catch-all.
    """
    if exc is None:
        return "transport"
    msg = str(exc).lower()
    code = getattr(exc, "code", None)  # urllib.error.HTTPError exposes .code

    if code == 429 or any(t in msg for t in _THROTTLE_TOKENS):
        return "throttle"
    if code in (401, 403) or any(t in msg for t in _AUTH_TOKENS):
        return "auth"
    if code in (500, 502, 503, 504) or any(t in msg for t in _TRANSPORT_TOKENS):
        return "transport"
    # JSON / schema / shape errors raised while transforming the upstream payload:
    # a ValueError from json.loads, or a KeyError/TypeError in transform().
    if _is_json_error(exc) or any(t in msg for t in _PARSE_TOKENS):
        return "parse"
    if isinstance(exc, (KeyError, TypeError)):
        return "parse"
    return "transport"


def _is_json_error(exc) -> bool:
    return isinstance(exc, json.JSONDecodeError)


# ── Sentinel update (streak math) ─────────────────────────────────────────────


def update_outcome(prev: dict | None, *, attempted: bool, succeeded: bool, error_class: str, now_iso: str, source: str = None) -> dict:
    """Compute the next INGEST_HEALTH sentinel from the previous one.

    Pure: no clock, no I/O — the caller supplies `now_iso`. A success resets the
    failure streak and stamps last_success_ts; a failure increments the streak and
    records last_error_class. `attempted` stamps last_attempt_ts regardless of
    outcome (the Lambda ran), which is what the attempt-staleness arm reads.
    """
    prev = prev or {}
    streak = int(prev.get("consecutive_failures", 0) or 0)

    out = {
        "last_success_ts": prev.get("last_success_ts"),
        "last_attempt_ts": prev.get("last_attempt_ts"),
        "consecutive_failures": streak,
        "last_error_class": prev.get("last_error_class", "none"),
    }
    if source is not None:
        out["source"] = source
    elif prev.get("source"):
        out["source"] = prev["source"]

    if attempted:
        out["last_attempt_ts"] = now_iso

    if succeeded:
        out["last_success_ts"] = now_iso
        out["consecutive_failures"] = 0
        out["last_error_class"] = "none"
    else:
        out["consecutive_failures"] = streak + 1
        out["last_error_class"] = error_class if error_class in ERROR_CLASSES else "transport"

    return out


# ── Health decision ───────────────────────────────────────────────────────────


def _minutes_between(then_iso: str | None, now) -> float | None:
    if not then_iso:
        return None
    from datetime import datetime

    try:
        then = datetime.fromisoformat(then_iso)
    except (ValueError, TypeError):
        return None
    if then.tzinfo is None and now.tzinfo is not None:
        then = then.replace(tzinfo=now.tzinfo)
    return (now - then).total_seconds() / 60.0


def evaluate_source_health(
    sentinel: dict | None,
    *,
    now,
    max_gap_minutes: int = DEFAULT_MAX_ATTEMPT_GAP_MINUTES,
    failure_streak_threshold: int = DEFAULT_FAILURE_STREAK_THRESHOLD,
    source: str = None,
) -> dict:
    """Decide a source's infra-liveness from its sentinel.

    Returns a verdict dict: {source, status, alert, severity, reason,
    consecutive_failures, last_error_class, minutes_since_attempt}.

    status:
      - "unknown" — no sentinel yet (never ran, or just added). Non-alerting:
        avoids a first-deploy flood. The de-scheduled case is caught once a
        source HAS run (its sentinel then goes stale).
      - "failing" — running but erroring: streak >= threshold. ALERTS.
      - "stale"   — attempt-staleness: hasn't run within max_gap (cron stopped /
        Lambda dead). ALERTS. This is the arm that notices a silently-removed cron.
      - "ok"      — recent attempt, streak under the buffer. No alert. Includes the
        genuinely-unfed source (ran, 200'd, no new data) — succeeded, streak 0.
    """
    src = source or (sentinel or {}).get("source") or "unknown"
    if not sentinel:
        return {
            "source": src,
            "status": "unknown",
            "alert": False,
            "severity": "none",
            "reason": "no liveness sentinel yet",
            "consecutive_failures": 0,
            "last_error_class": "none",
            "minutes_since_attempt": None,
        }

    streak = int(sentinel.get("consecutive_failures", 0) or 0)
    err_class = sentinel.get("last_error_class", "none")
    mins = _minutes_between(sentinel.get("last_attempt_ts"), now)

    base = {
        "source": src,
        "consecutive_failures": streak,
        "last_error_class": err_class,
        "minutes_since_attempt": round(mins, 1) if mins is not None else None,
    }

    # Failure-streak arm — running but erroring. Tight threshold; fires fast.
    if streak >= failure_streak_threshold:
        return {
            **base,
            "status": "failing",
            "alert": True,
            "severity": "critical" if err_class in ("auth", "throttle") else "warning",
            "reason": f"{streak} consecutive {err_class} failures (>= {failure_streak_threshold})",
        }

    # Attempt-staleness arm — cron silently stopped / Lambda not running.
    if mins is not None and mins > max_gap_minutes:
        return {
            **base,
            "status": "stale",
            "alert": True,
            "severity": "critical",
            "reason": f"no ingestion attempt in {round(mins / 60, 1)}h (> {round(max_gap_minutes / 60, 1)}h budget)",
        }

    # Below the buffer (single/double blip) or healthy → no alert.
    return {
        **base,
        "status": "ok",
        "alert": False,
        "severity": "none",
        "reason": (f"{streak} recent failure(s), under the {failure_streak_threshold}-streak buffer" if streak else "healthy"),
    }


# ── EMF metric line ────────────────────────────────────────────────────────────


def emf_metric_line(*, source: str, succeeded: bool, consecutive_failures: int, error_class: str, timestamp_ms: int) -> str:
    """Build an Embedded-Metric-Format log line CloudWatch extracts to metrics.

    Emits RunSuccess (0/1) + ConsecutiveFailures in LifePlatform/IngestLiveness,
    dimensioned by Source — cheap (a structured log line, no put_metric_data call
    per ingestion run).
    """
    doc = {
        "_aws": {
            "Timestamp": int(timestamp_ms),
            "CloudWatchMetrics": [
                {
                    "Namespace": EMF_NAMESPACE,
                    "Dimensions": [["Source"]],
                    "Metrics": [{"Name": "RunSuccess"}, {"Name": "ConsecutiveFailures"}],
                }
            ],
        },
        "Source": source,
        "RunSuccess": 1 if succeeded else 0,
        "ConsecutiveFailures": int(consecutive_failures),
        "ErrorClass": error_class,
    }
    return json.dumps(doc)
