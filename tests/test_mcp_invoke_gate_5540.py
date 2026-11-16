"""tests/test_mcp_invoke_gate_5540.py — the MCP function's privileged branches and the bridge
both refuse before they run anything (#5540).

Defect class: a privileged, no-request branch of `mcp.handler.lambda_handler` (the two
constant-input jobs and the scheduled cache warmer) ran on ANY function that received the payload
shape, before any auth check — and the bridge transport skipped its `x-api-key` check whenever the
key could not be read from Secrets Manager (fail-open), comparing with `!=`.

What this proves, driven through the real `lambda_handler`:
  1. an unauthenticated invoke of each privileged payload on the request-serving function (or with
     no context) reaches NO job path — every job entry and the warmer are patched to explode;
  2. on the warmer, a scheduled event must name one of the MCP stack's schedules in `resources`;
  3. the real live payloads (the warmer schedule's envelope, the two job inputs) still run on the
     warmer — the gate does not break the schedules it protects;
  4. the bridge fails closed on a Secrets Manager failure and compares constant-time;
  5. the gate's two constants agree with the CDK declarations they mirror, and every job the
     handler dispatches is one the gate knows (the SET, not the instance).
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import (
    core,  # noqa: E402
    handler as h,  # noqa: E402
    invoke_gate as gate,  # noqa: E402
)

_REPO = Path(__file__).resolve().parent.parent
_ACCT = "205930651321"
_REGION = "us-west-2"
_SCHEDULE_ARN = f"arn:aws:scheduler:{_REGION}:{_ACCT}:schedule/default/LifePlatformMcp-McpWarmerPacificSchedule-EUBYOMGCWN9I"


def _ctx(fn: str) -> SimpleNamespace:
    return SimpleNamespace(function_name=fn, invoked_function_arn=f"arn:aws:lambda:{_REGION}:{_ACCT}:function:{fn}")


WARMER = _ctx(gate.WARMER_FUNCTION_NAME)
MAIN = _ctx("life-platform-mcp")


def _envelope(resources):
    """The live warmer schedule's input, as EventBridge Scheduler delivers it (placeholders filled)."""
    return {
        "version": "0",
        "id": "exec-1",
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "account": _ACCT,
        "time": "2026-11-08T17:10:00Z",
        "region": _REGION,
        "resources": resources,
        "detail": {},
    }


PRIVILEGED_PAYLOADS = {
    "nightly_predraft": {"job": "nightly_predraft"},
    "panel_weekly_grade": {"job": "panel_weekly_grade"},
    "scheduled envelope": _envelope([_SCHEDULE_ARN, f"arn:aws:lambda:{_REGION}:{_ACCT}:function:{gate.WARMER_FUNCTION_NAME}"]),
    "bare source": {"source": "aws.events"},
    "bare detail-type": {"detail-type": "Scheduled Event"},
}


class _NoPrivilegedPath:
    """Patch every privileged entry to explode, and record auth-failure metric emissions."""

    def __enter__(self):
        self._patches = [
            patch("mcp.nightly_predraft.lambda_entry", side_effect=AssertionError("nightly_predraft reached")),
            patch("mcp.panel_weekly_grade.lambda_entry", side_effect=AssertionError("panel_weekly_grade reached")),
            patch.object(h, "nightly_cache_warmer", side_effect=AssertionError("cache warmer reached")),
            patch.object(h, "_process_jsonrpc", side_effect=AssertionError("JSON-RPC reached")),
        ]
        self.metric = patch.object(h, "_emit_auth_failure_metric")
        for p in self._patches:
            p.start()
        self.emitted = self.metric.start()
        return self

    def __exit__(self, *exc):
        self.metric.stop()
        for p in reversed(self._patches):
            p.stop()
        return False


# ── 1. unauthenticated: no job path, on the main function or with no context ──────────────────────
def test_no_privileged_payload_reaches_a_job_path_off_the_warmer():
    offenders = []
    for ctx_name, ctx in (("life-platform-mcp", MAIN), ("no context", None), ("other fn", _ctx("life-platform-site-api"))):
        for name, payload in PRIVILEGED_PAYLOADS.items():
            with _NoPrivilegedPath() as probe:
                try:
                    resp = h.lambda_handler(json.loads(json.dumps(payload)), ctx)
                except AssertionError as e:  # a privileged path ran
                    offenders.append(f"{ctx_name} / {name}: {e}")
                    continue
                if resp.get("statusCode") != 403:
                    offenders.append(f"{ctx_name} / {name}: status {resp.get('statusCode')}, expected 403")
                if probe.emitted.call_count != 1:
                    offenders.append(f"{ctx_name} / {name}: auth-failure metric emitted {probe.emitted.call_count}x")
    assert not offenders, "privileged branch reachable without the warmer:\n  " + "\n  ".join(offenders)


# ── 2. on the warmer, the scheduled branch needs a known schedule in `resources` ─────────────────
_UNKNOWN_SCHEDULES = {
    "missing": None,
    "empty": [],
    "fn-only": [f"arn:aws:lambda:{_REGION}:{_ACCT}:function:{gate.WARMER_FUNCTION_NAME}"],
    "other-account": [f"arn:aws:scheduler:{_REGION}:999999999999:schedule/default/LifePlatformMcp-McpWarmerPacificSchedule-X"],
    "other-region": [f"arn:aws:scheduler:us-east-1:{_ACCT}:schedule/default/LifePlatformMcp-McpWarmerPacificSchedule-X"],
    "other-stack": [f"arn:aws:scheduler:{_REGION}:{_ACCT}:schedule/default/LifePlatformCompute-SomethingPacificSchedule-X"],
    "legacy-rule": [f"arn:aws:events:{_REGION}:{_ACCT}:rule/life-platform-nightly-warmer"],
    "not-a-list": "arn:aws:scheduler:not-a-list",
}


def test_scheduled_event_on_the_warmer_needs_a_known_schedule():
    offenders = []
    for name, resources in _UNKNOWN_SCHEDULES.items():
        event = _envelope(resources)
        if resources is None:
            event.pop("resources")
        with _NoPrivilegedPath() as probe:
            try:
                resp = h.lambda_handler(event, WARMER)
            except AssertionError as e:
                offenders.append(f"{name}: {e}")
                continue
        if resp["statusCode"] != 403 or probe.emitted.call_count != 1:
            offenders.append(f"{name}: status {resp['statusCode']}, metric x{probe.emitted.call_count}")
    assert not offenders, "\n  ".join(offenders)


# ── 3. the live payloads still run where they are scheduled ────────────────────────────────────────
def test_the_live_schedule_payloads_still_run_on_the_warmer():
    with patch.object(h, "nightly_cache_warmer", return_value={"ok": True}) as warm:
        resp = h.lambda_handler(PRIVILEGED_PAYLOADS["scheduled envelope"], WARMER)
    assert resp["statusCode"] == 200 and warm.call_count == 1
    with patch("mcp.nightly_predraft.lambda_entry", return_value={"statusCode": 200}) as entry:
        h.lambda_handler({"job": "nightly_predraft"}, WARMER)
    entry.assert_called_once()
    with patch("mcp.panel_weekly_grade.lambda_entry", return_value={"statusCode": 200}) as entry:
        h.lambda_handler({"job": "panel_weekly_grade"}, WARMER)
    entry.assert_called_once()


# ── 4. the bridge fails closed and compares constant-time ──────────────────────────────────────────
def _bridge(key):
    return {
        "headers": {"x-api-key": key} if key is not None else {},
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
    }


def test_bridge_fails_closed_when_secrets_manager_fails():
    with patch.object(core.secrets, "get_secret_value", side_effect=RuntimeError("AccessDenied")), _NoPrivilegedPath():
        for provided in (None, "", "anything", "None"):
            resp = h.lambda_handler(_bridge(provided), MAIN)
            assert resp["statusCode"] == 401, (provided, resp)


def test_bridge_rejects_a_wrong_or_missing_key_and_accepts_the_right_one():
    with patch.object(h, "get_api_key", return_value="secret"), _NoPrivilegedPath():
        for provided in (None, "", "secre", "secret ", ["secret"]):
            assert h.lambda_handler(_bridge(provided), MAIN)["statusCode"] == 401, provided
    with (
        patch.object(h, "get_api_key", return_value="secret"),
        patch.object(h, "_process_jsonrpc", return_value={"jsonrpc": "2.0", "id": 1, "result": {}}),
        patch.object(h.hmac, "compare_digest", wraps=h.hmac.compare_digest) as cmp,
    ):
        assert h.lambda_handler(_bridge("secret"), MAIN)["statusCode"] == 200
    assert cmp.call_count == 1, "the bridge key compare must go through hmac.compare_digest"


def test_bridge_source_has_no_plain_key_comparison():
    src = ast.get_source_segment(Path(h.__file__).read_text(encoding="utf-8"), _fn(h, "handle_bridge_invoke"))
    assert "provided_key != expected_key" not in src and "provided_key == expected_key" not in src
    assert "if expected_key:" not in src, "the fail-open shape (skip the check when the key is unreadable) is back"


def _fn(module, name):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


# ── 5. contracts: the gate's constants vs CDK, and the handler's job set vs the gate's ─────────────
def test_warmer_name_and_schedule_prefix_match_the_cdk_declarations():
    stack_src = (_REPO / "cdk" / "stacks" / "mcp_stack.py").read_text(encoding="utf-8")
    m = re.search(r'^WARMER_FUNCTION_NAME\s*=\s*"([^"]+)"', stack_src, re.M)
    assert m and m.group(1) == gate.WARMER_FUNCTION_NAME
    app_src = (_REPO / "cdk" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'McpStack\(\s*app\s*,\s*"([^"]+)"', app_src)
    assert m and f"{m.group(1)}-" == gate.SCHEDULE_NAME_PREFIX
    # the factory schedule's envelope is what carries the schedule ARN the gate requires
    helpers = (_REPO / "cdk" / "stacks" / "lambda_helpers.py").read_text(encoding="utf-8")
    assert '"resources": ["<aws.scheduler.schedule-arn>"' in helpers


def test_every_job_the_handler_dispatches_is_gated():
    """The handler dispatches on `kind` only (never on a raw `event["job"]`), and every job literal it
    compares `kind` against is in the gate's PRIVILEGED_JOBS — a new job added to the handler without
    the gate knowing it would otherwise fall through to the bridge, or worse, run ungated."""
    node = _fn(h, "lambda_handler")
    raw_job_reads = [
        ast.unparse(n)
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
        if isinstance(n.args[0], ast.Constant) and n.args[0].value in ("job", "source", "detail-type")
    ]
    assert not raw_job_reads, f"lambda_handler reads a privileged key directly (bypassing the gate): {raw_job_reads}"
    compared = {
        c.value
        for n in ast.walk(node)
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "kind"
        for c in n.comparators
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    }
    assert compared and compared <= set(gate.PRIVILEGED_JOBS), compared
    assert set(gate.PRIVILEGED_JOBS) <= compared, f"gate knows a job the handler never dispatches: {set(gate.PRIVILEGED_JOBS) - compared}"


def test_the_gate_runs_before_the_first_dispatch():
    """Order, not just presence: the refusal check is the first statement that can return."""
    body = _fn(h, "lambda_handler").body
    first_if = next(s for s in body if isinstance(s, ast.If))
    assert "refusal_reason" in ast.unparse(first_if), "the first branch in lambda_handler must be the #5540 gate"
