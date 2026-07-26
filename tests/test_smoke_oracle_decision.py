"""tests/test_smoke_oracle_decision.py — regression guard for the smoke-oracle
fail-open closure (#1345).

The post-deploy smoke-test job in ci-cd.yml used to treat an UNPARSEABLE
qa-smoke / canary response as `::warning` + PASS. That let a silently-broken
oracle pass the pipeline, so the Lambda-side auto-rollback could never fire on a
mangled response — the backend half of detect-and-revert was proven only on
paper.

The decision logic now lives in deploy/lib/smoke_oracle_decision.py and both
workflow steps call it. The load-bearing assertion here is that PARSE_ERROR is
GATING: main() returns a NON-ZERO exit on an unparseable result. This test FAILS
against the pre-fix inline logic (which returned 0 / warning-and-pass on
PARSE_ERROR) and PASSES after the fix — that before/after is the whole point of
the regression guard (#1345 AC).

#1831 adds coverage for the OTHER fail-open path: a COMPLETED invocation that
reports a real health failure. Pre-fix, a numeric statusCode >= 400 (canary_
lambda's real shape) and a failing JSON-encoded `body` string (qa_smoke_
lambda's real shape — it always returns statusCode 200) both read as PASS.
The new test cases below reproduce those exact real-world payload shapes.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "lib" / "smoke_oracle_decision.py"
_spec = importlib.util.spec_from_file_location("smoke_oracle_decision", _SCRIPT)
sod = importlib.util.module_from_spec(_spec)
sys.modules["smoke_oracle_decision"] = sod
_spec.loader.exec_module(sod)


def _write(tmp_path, text):
    p = tmp_path / "result.json"
    p.write_text(text)
    return str(p)


# ── PARSE_ERROR is GATING (the #1345 fix; fails pre-fix) ───────────────────────


def test_unparseable_json_exits_nonzero(tmp_path):
    """The core regression guard: garbage output must FAIL the step, not warn+pass."""
    path = _write(tmp_path, "this is not json {{{")
    verdict, _ = sod.decide(path)
    assert verdict == "PARSE_ERROR"
    # main() is what the workflow step's exit code comes from.
    assert sod.main([path, "Smoke test"]) != 0


def test_truncated_json_exits_nonzero(tmp_path):
    path = _write(tmp_path, '{"status": "ok"')  # truncated — real Lambda-invoke fail mode
    assert sod.decide(path)[0] == "PARSE_ERROR"
    assert sod.main([path, "Smoke test"]) != 0


def test_non_object_payload_is_parse_error(tmp_path):
    """A JSON list/scalar has no status field — old inline code hit AttributeError
    and fell into PARSE_ERROR; preserve that, and gate on it."""
    path = _write(tmp_path, "[1, 2, 3]")
    assert sod.decide(path)[0] == "PARSE_ERROR"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) != 0


def test_missing_file_is_gating(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    assert sod.decide(path)[0] == "PARSE_ERROR"
    assert sod.main([path, "Smoke test"]) != 0


# ── PASS / FAIL behavior preserved from the prior inline logic ─────────────────


def test_status_ok_passes(tmp_path):
    path = _write(tmp_path, '{"status": "ok"}')
    assert sod.decide(path)[0] == "PASS"
    assert sod.main([path, "Smoke test"]) == 0


def test_statuscode_200_passes(tmp_path):
    path = _write(tmp_path, '{"statusCode": 200}')
    assert sod.decide(path)[0] == "PASS"
    assert sod.main([path, "Smoke test"]) == 0


def test_status_error_fails(tmp_path):
    path = _write(tmp_path, '{"status": "error: dynamo timeout"}')
    assert sod.decide(path)[0] == "FAIL"
    assert sod.main([path, "Smoke test"]) != 0


def test_status_fail_fails(tmp_path):
    path = _write(tmp_path, '{"status": "FAILED"}')
    assert sod.decide(path)[0] == "FAIL"
    assert sod.main([path, "Smoke test"]) != 0


def test_empty_status_fails(tmp_path):
    """No status field at all → empty → FAIL (was already gating; keep it)."""
    path = _write(tmp_path, "{}")
    assert sod.decide(path)[0] == "FAIL"
    assert sod.main([path, "Smoke test"]) != 0


# ── canary-only "healthy" acceptance via --ok-extra ────────────────────────────


def test_canary_healthy_passes(tmp_path):
    path = _write(tmp_path, '{"status": "healthy"}')
    assert sod.decide(path, ["healthy"])[0] == "PASS"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) == 0


def test_ok_extra_exact_match_overrides_fail_token(tmp_path):
    """Proves --ok-extra genuinely plumbs through: a status containing the
    'fail' token would FAIL by default, but an EXACT ok-extra entry accepts it
    (the `s in ok` clause short-circuits the fail-token check)."""
    path = _write(tmp_path, '{"status": "failover-complete"}')
    assert sod.decide(path)[0] == "FAIL"  # default: contains 'fail'
    assert sod.decide(path, ["failover-complete"])[0] == "PASS"  # exact allow
    assert sod.main([path, "Canary", "--ok-extra", "failover-complete"]) == 0


# ── #1831: numeric statusCode >= 400 is a real failure signal ──────────────────
# The old logic only string-matched 'error'/'fail' — a bare numeric statusCode
# like 500 or 403 contains neither substring and isn't in OK_BASE, so it fell
# through to PASS. canary_lambda returns exactly this shape (statusCode: 500
# when all_ok is False, lambdas/operational/canary_lambda.py:584-594).


def test_statuscode_500_fails(tmp_path):
    path = _write(tmp_path, '{"statusCode": 500}')
    assert sod.decide(path)[0] == "FAIL"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) != 0


def test_statuscode_403_fails(tmp_path):
    path = _write(tmp_path, '{"statusCode": 403}')
    assert sod.decide(path)[0] == "FAIL"
    assert sod.main([path, "Smoke test"]) != 0


def test_statuscode_string_500_fails(tmp_path):
    """A stringified numeric statusCode ("500" not 500) must FAIL the same way —
    AWS CLI invoke output can serialize either form."""
    path = _write(tmp_path, '{"statusCode": "500"}')
    assert sod.decide(path)[0] == "FAIL"


# ── #1831: a JSON-encoded `body` string can carry the real failure signal ──────
# qa_smoke_lambda ALWAYS returns statusCode 200 — even on real failures — with
# the failure count inside a JSON-encoded `body` string
# (lambdas/operational/qa_smoke_lambda.py:1060: '{"failed": N, ...}'). The old
# oracle never parsed `body` at all, so this always read as PASS.


def test_qa_smoke_shaped_failing_body_fails(tmp_path):
    """statusCode 200 at the top level, but body.failed > 0 — the qa_smoke_lambda
    real-world failure shape (#1831's core reported bug)."""
    path = _write(
        tmp_path,
        '{"statusCode": 200, "body": "{\\"failed\\": 7, \\"warned\\": 1, \\"emailed\\": true}"}',
    )
    verdict, detail = sod.decide(path)
    assert verdict == "FAIL"
    assert "7" in detail
    assert sod.main([path, "Smoke test"]) != 0


def test_qa_smoke_shaped_healthy_body_passes(tmp_path):
    """The genuinely-healthy qa_smoke_lambda shape (failed: 0) must still PASS —
    proves the body check doesn't over-fire on a zero/absent failure count."""
    path = _write(tmp_path, '{"statusCode": 200, "body": "{\\"failed\\": 0, \\"warned\\": 0, \\"emailed\\": false}"}')
    assert sod.decide(path)[0] == "PASS"
    assert sod.main([path, "Smoke test"]) == 0


def test_canary_shaped_failing_body_fails(tmp_path):
    """canary_lambda-shaped body with all_pass: false must FAIL even if the
    top-level statusCode were ever 200 (belt-and-suspenders alongside the
    statusCode>=400 numeric check, since real canary_lambda pairs all_pass:
    false with statusCode 500 — lambdas/operational/canary_lambda.py:584-594)."""
    path = _write(
        tmp_path,
        '{"statusCode": 200, "body": "{\\"canary_ts\\": \\"2026-07-26T00:00:00Z\\", \\"all_pass\\": false, \\"failures\\": 2}"}',
    )
    verdict, detail = sod.decide(path, ["healthy"])
    assert verdict == "FAIL"
    assert "all_pass" in detail
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) != 0


def test_canary_shaped_healthy_body_passes(tmp_path):
    """canary_lambda's real healthy shape: statusCode 200, body.all_pass true."""
    path = _write(
        tmp_path,
        '{"statusCode": 200, "body": "{\\"canary_ts\\": \\"2026-07-26T00:00:00Z\\", \\"all_pass\\": true, \\"failures\\": 0}"}',
    )
    assert sod.decide(path)[0] == "PASS"
    assert sod.main([path, "Canary", "--ok-extra", "healthy"]) == 0


def test_unparseable_body_string_falls_back_to_status(tmp_path):
    """A `body` that's present but not valid JSON must not itself become a
    PARSE_ERROR (the top-level payload parsed fine) — it just means no
    body-level signal is available, so the top-level status still decides."""
    path = _write(tmp_path, '{"statusCode": 200, "body": "not json {{{"}')
    assert sod.decide(path)[0] == "PASS"
