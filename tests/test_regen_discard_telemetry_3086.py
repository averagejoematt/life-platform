"""tests/test_regen_discard_telemetry_3086.py — #3086.

`grounded_generation.regen_once` is the shared corrective-rewrite path for ~15 AI
narrative surfaces. Before this fix it discarded a billed regeneration silently on
three arms — a bare `except`, an empty/blank regen response, and a rewrite that isn't
strictly better than the original — and only ONE caller (`ai_calls._ground_legacy_output`)
printed anything about it, and even that caller couldn't see the exception arm:
`regen_once` swallowed the exception internally before the caller's own try/except
ever ran, so "gate failed" and "not strictly better" were indistinguishable in the logs.

Each test below drives regen_once down exactly one discard path and asserts the
`regen_discard_telemetry.log_discard` call that path must now make — arm, surface, and
(for the two exception arms) the named exception class in `reason=`. These are
mutation-proof by construction: they assert the OBSERVABILITY call happened, not just
regen_once's return value (which is unchanged pre/post #3086 and would pass even with
every log/metric call deleted). Verified by hand: commenting out the `log_discard` call
on any one arm in a scratch copy of grounded_generation.py reds exactly that arm's test
here and none of the others (see the PR description for the transcript).
"""

import os
import sys
from unittest import mock

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from ai import grounded_generation as gg  # noqa: E402


def _one_finding(_text):
    """A findings_fn that always reports exactly one finding — never satisfied, so
    every path below reaches the code under test instead of short-circuiting on
    'no findings' or 'strictly improved'."""
    return [{"type": "fabricated_number", "detail": "x", "claimed": 1.0}]


# ── arm 1: the (former bare) except, now two named exception classes ──────────────


def test_transport_exception_arm_logs_discard_with_reason():
    def boom(_corr):
        raise ConnectionError("no route to host")

    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        text, findings, corrected = gg.regen_once("orig", _one_finding, boom, surface="test_surface_a")

    assert not corrected and text == "orig" and findings
    assert m.call_count == 1, "transport-error discard must emit exactly one telemetry call"
    args, kwargs = m.call_args
    assert args[0] == "transport_error"
    assert args[1] == "test_surface_a"
    assert args[2] == 1  # findings_count
    assert kwargs.get("reason") == "ConnectionError"


def test_unexpected_exception_arm_logs_discard_with_reason():
    def boom(_corr):
        raise ValueError("some other regen_fn failure")

    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        text, findings, corrected = gg.regen_once("orig", _one_finding, boom, surface="test_surface_b")

    assert not corrected and text == "orig" and findings
    assert m.call_count == 1, "unexpected-error discard must emit exactly one telemetry call"
    args, kwargs = m.call_args
    assert args[0] == "unexpected_error"
    assert args[1] == "test_surface_b"
    assert kwargs.get("reason") == "ValueError"


# ── arm 2: empty/blank regen response ──────────────────────────────────────────────


def test_empty_response_arm_logs_discard():
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        text, findings, corrected = gg.regen_once("orig", _one_finding, lambda _c: "   ", surface="test_surface_c")

    assert not corrected and text == "orig" and findings
    assert m.call_count == 1, "empty-response discard must emit exactly one telemetry call"
    args, _kwargs = m.call_args
    assert args[0] == "empty_response"
    assert args[1] == "test_surface_c"
    assert args[2] == 1


# ── arm 3: rewrite not strictly better ─────────────────────────────────────────────


def test_not_strictly_better_arm_logs_discard():
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        text, findings, corrected = gg.regen_once("orig", _one_finding, lambda _c: "an unimproved rewrite", surface="test_surface_d")

    assert not corrected and text == "orig" and findings
    assert m.call_count == 1, "not-strictly-better discard must emit exactly one telemetry call"
    args, _kwargs = m.call_args
    assert args[0] == "not_strictly_better"
    assert args[1] == "test_surface_d"


# ── negative controls: no discard telemetry on the two NON-discard paths ──────────


def test_no_findings_never_calls_discard_telemetry():
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        gg.regen_once("clean text", lambda _t: [], lambda _c: "unused", surface="test_surface_e")
    assert m.call_count == 0


def test_corrected_rewrite_never_calls_discard_telemetry():
    calls = {"n": 0}

    def findings_fn(_text):
        calls["n"] += 1
        return [{"type": "x", "detail": "placeholder"}] if calls["n"] == 1 else []

    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        _text, _findings, corrected = gg.regen_once("orig", findings_fn, lambda _c: "fixed", surface="test_surface_f")

    assert corrected and m.call_count == 0


# ── surface actually threads through from a real caller (#3086 acceptance) ────────


def test_default_surface_is_unknown_when_caller_omits_it():
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        gg.regen_once("orig", _one_finding, lambda _c: "   ")  # no surface kwarg
    args, _kwargs = m.call_args
    assert args[1] == "unknown"
