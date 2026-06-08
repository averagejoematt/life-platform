#!/usr/bin/env python3
"""
tests/test_platform_logger.py — Unit tests for platform_logger exc_info handling.

Covers TD-20 (normalize exc_info=True / BaseException to tuple before passing
to makeRecord). Pre-fix, every error log line emitted a secondary
'TypeError: bool object is not subscriptable' from formatException because
Logger._log()'s normalization (True → sys.exc_info()) was bypassed by
PlatformLogger's custom _log_with_extras.

Run: python3 -m pytest tests/test_platform_logger.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

_import_err = None
try:
    import platform_logger as pl
except ImportError as _e:
    _import_err = _e
    pl = None  # type: ignore

if _import_err is not None:
    pytestmark = pytest.mark.skip(reason=f"platform_logger unavailable: {_import_err}")  # type: ignore


def _drain_handler_output(logger):
    """Force any buffered handler output to flush; return formatter output as
    a single string by re-rendering through a captured stream.

    Strategy: replace the StreamHandler's stream with an in-memory StringIO
    for the duration of one log call, then return contents.
    """
    from io import StringIO

    buf = StringIO()
    original_streams = []
    for h in logger.handlers:
        if hasattr(h, "stream"):
            original_streams.append((h, h.stream))
            h.stream = buf
    return buf, original_streams


def _restore_streams(originals):
    for h, s in originals:
        h.stream = s


class TestExcInfoNormalization:
    """TD-20: exc_info=True / BaseException / tuple all produce clean log output
    with no secondary TypeError from formatException."""

    def test_exc_info_true_inside_except_block(self):
        """Standard pattern: logger.error(msg, exc_info=True) inside except."""
        logger = pl.get_logger("test-td20-true")
        buf, originals = _drain_handler_output(logger)
        try:
            try:
                raise ValueError("expected test exception")
            except ValueError:
                logger.error("error happened", exc_info=True)
        finally:
            _restore_streams(originals)

        out = buf.getvalue()
        assert "TypeError" not in out, f"TD-20 regression: secondary TypeError leaked into log output:\n{out}"
        # Exception details should be in the log
        assert "ValueError" in out
        assert "expected test exception" in out

    def test_exc_info_baseexception_object(self):
        """logger.error(msg, exc_info=exc_obj) where exc_obj is a BaseException."""
        logger = pl.get_logger("test-td20-obj")
        buf, originals = _drain_handler_output(logger)
        try:
            try:
                raise RuntimeError("boom")
            except RuntimeError as e:
                logger.error("error", exc_info=e)
        finally:
            _restore_streams(originals)

        out = buf.getvalue()
        assert "TypeError" not in out, f"TD-20 regression with BaseException form: {out}"
        assert "RuntimeError" in out
        assert "boom" in out

    def test_exc_info_tuple_form(self):
        """Stdlib-style: logger.error(msg, exc_info=sys.exc_info())."""
        logger = pl.get_logger("test-td20-tuple")
        buf, originals = _drain_handler_output(logger)
        try:
            try:
                raise OSError("disk full")
            except OSError:
                logger.error("io error", exc_info=sys.exc_info())
        finally:
            _restore_streams(originals)

        out = buf.getvalue()
        assert "TypeError" not in out
        assert "OSError" in out

    def test_exc_info_none_happy_path(self):
        """Happy path: no exc_info, no exception machinery touched."""
        logger = pl.get_logger("test-td20-none")
        buf, originals = _drain_handler_output(logger)
        try:
            logger.info("just a message", request_id="abc-123")
        finally:
            _restore_streams(originals)

        out = buf.getvalue()
        assert "TypeError" not in out
        assert "just a message" in out
        # Structured field should land
        assert "abc-123" in out

    def test_exc_info_false_is_treated_as_none(self):
        """exc_info=False (or 0) → no exception block produced."""
        logger = pl.get_logger("test-td20-false")
        buf, originals = _drain_handler_output(logger)
        try:
            logger.error("failed but no traceback", exc_info=False)
        finally:
            _restore_streams(originals)

        out = buf.getvalue()
        assert "TypeError" not in out
        assert "failed but no traceback" in out
