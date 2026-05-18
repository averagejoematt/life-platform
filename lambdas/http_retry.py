"""
http_retry.py — Phase 3.5 (2026-05-16): generic HTTP retry for ingestion
Lambdas that call non-Anthropic APIs (Strava, Withings, Eight Sleep, Habitify,
Notion, etc.).

Lighter than retry_utils.py — no CloudWatch metric emission, no Anthropic-
specific response parsing. Just retry on 429/5xx with exponential backoff.

Usage:
    from http_retry import urlopen_with_retry
    with urlopen_with_retry(req, timeout=30) as resp:
        data = json.loads(resp.read())

Retry policy:
  - 3 attempts total (initial + 2 retries)
  - Backoff: 2s, 8s
  - Retryable status: 429, 500, 502, 503, 504
  - Retryable network errors: URLError (timeout, connection reset)
  - 4xx auth failures (401, 403) raise IMMEDIATELY — no point retrying;
    the auth_breaker pattern handles those
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request


_BACKOFF_DELAYS = [2, 8]  # 3 attempts: initial + 2 retries
_RETRYABLE_HTTP = frozenset([429, 500, 502, 503, 504])

_logger = logging.getLogger("http_retry")


class _ResponseWrapper:
    """Mimics urllib.request.urlopen context manager around a buffered response."""

    def __init__(self, raw_bytes: bytes, headers, status: int):
        self._raw = raw_bytes
        self._headers = headers
        self._status = status

    def read(self):
        return self._raw

    def getheader(self, name, default=None):
        return self._headers.get(name, default) if self._headers else default

    @property
    def status(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def urlopen_with_retry(req, timeout: int = 30):
    """Drop-in replacement for urllib.request.urlopen with retry on transient errors.

    Returns a context-manager wrapping a buffered response (so .read() can be
    called inside the `with` block, same as urlopen).
    """
    max_attempts = len(_BACKOFF_DELAYS) + 1
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                # Buffer the body so we can return a re-usable wrapper.
                body = r.read()
                return _ResponseWrapper(body, dict(r.headers or {}), r.status)
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code in _RETRYABLE_HTTP and attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                _logger.warning("http_retry HTTP %d attempt %d/%d — retry in %ds",
                                e.code, attempt, max_attempts, delay)
                time.sleep(delay)
                continue
            # 4xx (incl. auth) and final-attempt 5xx: raise
            raise
        except urllib.error.URLError as e:
            last_exc = e
            if attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                _logger.warning("http_retry network error attempt %d/%d — retry in %ds: %s",
                                attempt, max_attempts, delay, e)
                time.sleep(delay)
                continue
            raise

    # Should be unreachable; safety net.
    if last_exc:
        raise last_exc
    raise RuntimeError("urlopen_with_retry exhausted attempts without exception")
