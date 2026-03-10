"""
platform_logger.py — OBS-1: Structured JSON logging for all Life Platform Lambdas.

Shared module. Drop-in replacement for the stdlib `logging` pattern used across
all 37 Lambdas. Every log line becomes a structured JSON object that CloudWatch
Logs Insights can query, filter, and alarm on.

USAGE (replaces `logger = logging.getLogger(); logger.setLevel(logging.INFO)`):

    from platform_logger import get_logger
    logger = get_logger("daily-brief")           # source name = lambda function name
    logger.info("Sending email", subject=subject, grade=grade)
    logger.warning("Stale data", source="whoop", age_hours=4.2)
    logger.error("AI call failed", attempt=3, error=str(e))

    # Structured log emitted to CloudWatch:
    {
      "timestamp": "2026-03-08T18:00:01.234Z",
      "level": "INFO",
      "source": "daily-brief",
      "correlation_id": "daily-brief#2026-03-08",
      "lambda": "daily-brief",
      "message": "Sending email",
      "subject": "Morning Brief | Sun Mar 8 ...",
      "grade": "B+"
    }

CORRELATION ID:
  Set once per Lambda execution via logger.set_date(date_str).
  Pattern: "{source}#{date}" — enables cross-Lambda log grouping in CWL Insights.
  Example query: `filter correlation_id like "2026-03-08"` shows ALL Lambda executions
  for that date.

MIGRATION PATTERN (for Lambdas not yet migrated):
  Old: `logger.info("Sending email: " + subject)`
  New: `logger.info("Sending email", subject=subject)`
  — keyword args become top-level JSON fields (searchable in CWL Insights)

BACKWARD COMPATIBILITY:
  PlatformLogger inherits logging.Logger so existing `logger.info(msg)` calls
  (positional only) continue to work unchanged. Migration can be incremental.

v1.0.0 — 2026-03-08 (OBS-1)
v1.0.1 — 2026-03-10 — *args %s compat for all log methods (Bug B fix)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_LAMBDA_VERSION = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

# Map stdlib level names → integers (for external callers that pass strings)
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class StructuredFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Standard fields always present:
      timestamp, level, source, lambda, correlation_id, message

    Additional fields: any keyword arguments passed to the log call
    (stored in `record.extra_fields` by PlatformLogger).
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"

        doc = {
            "timestamp": ts,
            "level": record.levelname,
            "source": getattr(record, "platform_source", _LAMBDA_NAME),
            "lambda": _LAMBDA_NAME,
            "lambda_version": _LAMBDA_VERSION,
            "correlation_id": getattr(record, "correlation_id", "unknown"),
            "message": record.getMessage(),
        }

        # Merge any extra structured fields
        extra = getattr(record, "extra_fields", {})
        for k, v in extra.items():
            if k not in doc:  # don't overwrite standard fields
                doc[k] = _safe_json_value(v)

        # Include exception info if present
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)

        try:
            return json.dumps(doc, default=str, separators=(",", ":"))
        except Exception:
            # Last resort — never swallow a log line entirely
            return json.dumps({
                "timestamp": ts,
                "level": record.levelname,
                "source": getattr(record, "platform_source", _LAMBDA_NAME),
                "message": str(record.getMessage()),
                "serialization_error": True,
            })


def _safe_json_value(v):
    """Convert value to JSON-safe form without crashing."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_safe_json_value(i) for i in v]
    if isinstance(v, dict):
        return {str(kk): _safe_json_value(vv) for kk, vv in v.items()}
    return str(v)


class PlatformLogger(logging.Logger):
    """Drop-in replacement for stdlib Logger with structured JSON output.

    Extends logging.Logger to:
    1. Accept keyword arguments on all log calls → JSON fields
    2. Carry a correlation_id that updates per date
    3. Default to structured JSON output (CloudWatch-queryable)

    Backward compatible: positional `logger.info(msg)` calls work unchanged.
    """

    def __init__(self, source: str):
        super().__init__(source)
        self._source = source
        self._correlation_id = source  # updated by set_date()
        self.setLevel(_LEVEL_MAP.get(LOG_LEVEL, logging.INFO))
        self._setup_handler()

    def _setup_handler(self):
        """Attach structured formatter to stdout (Lambda captures stdout → CWL)."""
        # Remove any existing handlers (avoids duplicate lines in warm starts)
        self.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        self.addHandler(handler)
        self.propagate = False  # don't also write to root logger

    def set_date(self, date_str: str):
        """Set correlation_id for this execution. Call at start of lambda_handler.

        Args:
            date_str: YYYY-MM-DD string — the date this execution is processing.

        Effect: all subsequent log calls include `correlation_id: "{source}#{date_str}"`
        """
        self._correlation_id = f"{self._source}#{date_str}"

    def set_correlation_id(self, correlation_id: str):
        """Manually set correlation_id (for non-date-based Lambdas)."""
        self._correlation_id = correlation_id

    # ── Overridden log methods that accept keyword args ────────────────────────

    def _log_with_extras(self, level: int, msg: str, args: tuple, kwargs: dict):
        """Shared implementation — attach extra_fields to record.

        Supports both call styles:
          logger.info("msg: %s", value)          # positional %s (stdlib compat)
          logger.info("msg", key=value)           # keyword args → JSON fields
        """
        if not self.isEnabledFor(level):
            return
        # Interpolate %s args if provided (stdlib backward compat)
        if args:
            try:
                msg = msg % args
            except (TypeError, ValueError):
                msg = f"{msg} {args}"  # fallback: append args if interpolation fails
        record = self.makeRecord(
            self.name,
            level,
            "(unknown file)",
            0,
            msg,
            args=(),
            exc_info=kwargs.pop("exc_info", None),
        )
        record.platform_source = self._source
        record.correlation_id = self._correlation_id
        record.extra_fields = kwargs  # all remaining kwargs become JSON fields
        self.handle(record)

    def debug(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.DEBUG, msg, args, kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.INFO, msg, args, kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.WARNING, msg, args, kwargs)

    def warn(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.WARNING, msg, args, kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.ERROR, msg, args, kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log_with_extras(logging.CRITICAL, msg, args, kwargs)

    # ── Convenience helpers for common patterns ────────────────────────────────

    def ingestion_start(self, date_str: str, lookback_days: int = None):
        """Log Lambda start for ingestion Lambdas."""
        self.set_date(date_str)
        self.info(
            "Ingestion starting",
            date=date_str,
            lookback_days=lookback_days,
        )

    def ingestion_complete(self, date_str: str, records_written: int, sources: list = None):
        """Log successful ingestion completion."""
        self.info(
            "Ingestion complete",
            date=date_str,
            records_written=records_written,
            sources=sources,
        )

    def source_missing(self, source: str, date_str: str):
        """Log a missing data source (common warning across all ingestion Lambdas)."""
        self.warning(
            "Source data missing",
            source=source,
            date=date_str,
        )

    def ai_call_start(self, call_name: str, model: str, max_tokens: int):
        """Log AI call start."""
        self.info(
            "AI call starting",
            call_name=call_name,
            model=model,
            max_tokens=max_tokens,
        )

    def ai_call_complete(self, call_name: str, tokens_in: int, tokens_out: int, latency_ms: float = None):
        """Log AI call completion with token counts."""
        self.info(
            "AI call complete",
            call_name=call_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round(latency_ms, 1) if latency_ms else None,
        )

    def ai_call_failed(self, call_name: str, error: str, attempt: int = 1):
        """Log AI call failure."""
        self.error(
            "AI call failed",
            call_name=call_name,
            error=error,
            attempt=attempt,
        )

    def validation_error(self, source: str, date_str: str, errors: list, warnings: list = None):
        """Log data validation failure."""
        self.warning(
            "Validation errors",
            source=source,
            date=date_str,
            errors=errors,
            warnings=warnings or [],
            error_count=len(errors),
        )

    def validation_skipped(self, source: str, date_str: str, reason: str):
        """Log that DDB write was skipped due to validation."""
        self.error(
            "DDB write skipped — validation failure",
            source=source,
            date=date_str,
            reason=reason,
        )

    def email_sent(self, recipient: str, subject: str):
        """Log successful email send."""
        self.info(
            "Email sent",
            recipient=recipient,
            subject=subject[:120],
        )

    def ddb_write(self, source: str, date_str: str, size_bytes: int = None):
        """Log DynamoDB write."""
        self.info(
            "DDB write",
            source=source,
            date=date_str,
            size_bytes=size_bytes,
        )

    def s3_write(self, key: str, size_bytes: int = None):
        """Log S3 write."""
        self.info(
            "S3 write",
            key=key,
            size_bytes=size_bytes,
        )


# ── Module-level registry — one logger per source ─────────────────────────────
_loggers: dict[str, PlatformLogger] = {}


def get_logger(source: str = None) -> PlatformLogger:
    """Get (or create) a PlatformLogger for the given source.

    Args:
        source: Human-readable source name — typically the Lambda function name
                minus "life-platform-" prefix, e.g. "daily-brief", "strava",
                "character-sheet-compute". Defaults to AWS_LAMBDA_FUNCTION_NAME.

    Returns:
        PlatformLogger instance (singleton per source name).

    Example:
        logger = get_logger("daily-brief")
        logger.set_date("2026-03-08")
        logger.info("Starting", sections=15)
    """
    if source is None:
        source = _LAMBDA_NAME

    if source not in _loggers:
        _loggers[source] = PlatformLogger(source)

    return _loggers[source]


# ── CloudWatch Logs Insights query helpers (reference strings) ─────────────────

CWL_QUERIES = {
    "errors_today": (
        "filter level = 'ERROR' "
        "| sort @timestamp desc "
        "| limit 50"
    ),
    "validation_errors": (
        "filter message = 'Validation errors' "
        "| stats count(*) by source "
        "| sort count desc"
    ),
    "ai_failures": (
        "filter message = 'AI call failed' "
        "| stats count(*) by call_name "
        "| sort count desc"
    ),
    "ingestion_by_date": (
        "filter message = 'Ingestion complete' "
        "| stats sum(records_written) by date "
        "| sort date desc"
    ),
    "source_gaps": (
        "filter message = 'Source data missing' "
        "| stats count(*) by source, date "
        "| sort date desc, source"
    ),
    "slow_ai_calls": (
        "filter message = 'AI call complete' and latency_ms > 30000 "
        "| fields call_name, latency_ms, tokens_out "
        "| sort latency_ms desc"
    ),
    "cross_lambda_by_date": (
        # Replace DATE with target date
        "filter correlation_id like 'DATE' "
        "| sort @timestamp asc"
    ),
}
