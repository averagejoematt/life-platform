"""tests/test_route_metric_coverage_2876.py — #2876's derivation guard.

Defect class owned (charter primitive 2, "guard the SET not the instance"):
`_emit_route_log` was only reached on the `ROUTES.get(path)` tail of the
dispatch in `lambda_handler`. 27 named routes (the issue's own list) plus all
16 `_SIMPLE_ROUTES` entries `return`ed straight out of `lambda_handler` before
that tail and so published no per-route latency/cold-start metric at all —
not slow, not fast, simply absent. Nothing distinguished "this route is fast"
from "this route is unmeasured" (ADR-104's class of defect).

The fix (see `lambdas/web/site_api_lambda.py`) restructures the dispatch to
ONE exit point: `_dispatch_route(event, path, method)` now resolves EVERY
route (`ROUTES`, `_SIMPLE_ROUTES`, and every inline `if path == "..."`
branch) and returns a dict, `None` (unmatched), or raises. `lambda_handler`
calls it exactly once and unconditionally emits `_emit_route_log` on
whatever comes back.

This file is the derivation guard for that shape, not a re-listing of the 27
routes: it enumerates route-specific branches FROM SOURCE (regex over the
whole file, not a hand-typed list) and asserts every one of them lives inside
`_dispatch_route` — so a newly-added early-return route anywhere in the file
fails `test_every_route_branch_lives_inside_the_single_dispatch_function`
the moment it's added outside that function, mirroring the exact defect this
issue closes. See the PR body for the mutation evidence (a deliberately
broken version of this test proven RED, then fixed and proven GREEN).

The behavioral tests below invoke the real `lambda_handler` (fixture must be
the wire, #2819's own technique) and inspect the printed EMF JSON — not a
mocked call count — for routes that were on the issue's "never emits" list.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

from web import site_api_lambda as L  # noqa: E402

SRC_PATH = os.path.join(_REPO, "lambdas", "web", "site_api_lambda.py")
SRC = open(SRC_PATH, encoding="utf-8").read()
SRC_LINES = SRC.splitlines()

_PATH_BRANCH_RE = re.compile(r'path (?:==|\.startswith\() ?"(/api/[^"]+)"')


def _function_line_span(func_name: str) -> tuple[int, int]:
    """1-indexed (start, end) line span of a top-level function in the module."""
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node.lineno, node.end_lineno
    raise AssertionError(f"{func_name!r} not found as a top-level function in {SRC_PATH}")


def _all_path_literal_branch_lines() -> list[int]:
    """Every line, anywhere in the file, that branches on a `/api/...` path
    literal — the raw, source-derived enumeration of every route-specific
    dispatch decision this module makes. Not hand-listed: a route added
    anywhere shows up here automatically."""
    return [i for i, line in enumerate(SRC_LINES, start=1) if _PATH_BRANCH_RE.search(line)]


# ── Structural guards (the derivation guard proper) ─────────────────────────


def test_every_route_branch_lives_inside_the_single_dispatch_function():
    """A route-specific branch outside `_dispatch_route` can never be reached
    by `lambda_handler`'s single `_emit_route_log` call — it would `return`
    straight out and go unmeasured, which is exactly #2876's defect.

    `/api/healthz` is the one sanctioned, pre-existing exception: it is
    handled before dispatch (no auth needed for a health check) and calls
    `_emit_route_log(200)` itself, explicitly, right there — that's why it
    was the ONE early-returning route the original issue found already
    measured.
    """
    start, end = _function_line_span("_dispatch_route")
    offenders = [ln for ln in _all_path_literal_branch_lines() if not (start <= ln <= end)]
    offenders = [ln for ln in offenders if 'path == "/api/healthz"' not in SRC_LINES[ln - 1]]
    assert offenders == [], (
        "route branch(es) outside _dispatch_route will never reach the single "
        f"_emit_route_log exit point (lines {offenders}): "
        f"{[SRC_LINES[ln - 1].strip() for ln in offenders]}"
    )


def test_dispatch_route_never_calls_the_emitter():
    """`_dispatch_route` must return to its caller, never emit itself — that is
    what makes the exit point single. If a future edit hoists `_emit_route_log`
    to module scope (today it's a closure local to `lambda_handler` and isn't
    even importable from here), this stops a call from creeping back in."""
    src = inspect.getsource(L._dispatch_route)
    assert "_emit_route_log" not in src


def test_lambda_handler_emits_on_all_three_outcomes():
    """AST-check the shape immediately around the `_dispatch_route` call in
    `lambda_handler`: the success tail, the 404 (`None`) branch, and the
    exception handler must each reach `_emit_route_log`."""
    tree = ast.parse(SRC)
    lh = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "lambda_handler")

    try_node = None
    for node in ast.walk(lh):
        if isinstance(node, ast.Try) and "_dispatch_route" in ast.dump(node):
            try_node = node
            break
    assert try_node is not None, "lambda_handler must call _dispatch_route inside a try block"
    assert len(try_node.handlers) == 1, "expected exactly one except handler around the dispatch call"
    assert "_emit_route_log" in ast.dump(try_node.handlers[0]), "the exception path must emit"

    after = [s for s in lh.body if s.lineno > try_node.end_lineno]
    after_src = "\n".join(ast.dump(s) for s in after)
    assert after_src.count("_emit_route_log") >= 2, "expected an emit for both the 404 (None) branch and the success tail"


# ── Behavioral proof: the real EMF wire shape, not a mocked call count ─────


def _event(path: str, method: str = "GET", qs: dict | None = None) -> dict:
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": method, "sourceIp": "203.0.113.9"}},
        "queryStringParameters": qs or {},
        "headers": {},
    }


def _emitted_route_metrics(event):
    """Invoke the real `lambda_handler` and return (response, [route_metric EMF lines])."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        resp = L.lambda_handler(event, None)
    lines = []
    for raw in buf.getvalue().splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if obj.get("_type") == "route_metric":
            lines.append(obj)
    return resp, lines


def test_a_previously_uncovered_route_now_emits_on_the_wire():
    """`/api/coaching-dashboard` was one of the issue's own 27 examples. It
    self-catches its DDB errors (returns a degraded 200), so it's invocable
    end-to-end with fake credentials and no mocking."""
    resp, emitted = _emitted_route_metrics(_event("/api/coaching-dashboard"))
    assert resp["statusCode"] == 200
    assert len(emitted) == 1, "must emit exactly once"
    emf = emitted[0]
    assert emf["Route"] == "/api/coaching-dashboard"
    assert emf["Method"] == "GET"

    directives = emf["_aws"]["CloudWatchMetrics"]
    assert len(directives) == 1
    d = directives[0]
    assert d["Namespace"] == "LifePlatform/SiteAPI"
    assert {m["Name"] for m in d["Metrics"]} == {"DurationMs", "ColdStart"}
    # Both dimension sets: the pre-existing per-route detail (UNCHANGED shape —
    # cdk/stacks/monitoring_dashboards.py's TOP_ROUTES panels don't regress)
    # plus the new #2876 dimensionless aggregate (a future fleet-wide alarm
    # can watch every route without enumerating any of them).
    assert ["Route", "Method"] in d["Dimensions"]
    assert [] in d["Dimensions"]


def test_a_previously_uncovered_route_emits_on_a_handled_500_too():
    """`/api/vitals?date=...` is another of the 27. Unlike coaching-dashboard
    it does NOT self-catch, so with fake credentials it raises down inside
    the handler. Before #2876 that exception escaped `lambda_handler`
    uncaught and never reached `_emit_route_log` (or #2819's Handled5xx
    emitter) at all — see the companion behavior-change proof in
    test_api_input_validation_bugbash_2026_08_14.py::test_vitals_still_accepts_a_real_date_shape.
    """
    resp, emitted = _emitted_route_metrics(_event("/api/vitals", qs={"date": "2026-08-12"}))
    assert resp["statusCode"] == 500
    assert len(emitted) == 1
    assert emitted[0]["Route"] == "/api/vitals"
    assert emitted[0]["status"] == 500


def test_a_simple_routes_entry_now_emits_too():
    """`_SIMPLE_ROUTES` routes were ALSO never measured before #2876 — same
    defect class, just not named in the issue's list (that list is scoped to
    GET reader routes; `_SIMPLE_ROUTES` is mostly POST mutation endpoints).
    The single exit point covers them too, by construction, with no separate
    code path to remember."""
    resp, emitted = _emitted_route_metrics(_event("/api/nudge", method="POST"))
    assert len(emitted) == 1
    assert emitted[0]["Route"] == "/api/nudge"
    assert emitted[0]["Method"] == "POST"


def test_unmatched_path_still_emits_a_404():
    resp, emitted = _emitted_route_metrics(_event("/api/this-route-does-not-exist"))
    assert resp["statusCode"] == 404
    assert len(emitted) == 1
    assert emitted[0]["status"] == 404


def test_an_already_covered_route_keeps_its_exact_shape():
    """Non-regression: `/api/healthz` was already measured before #2876 (the
    one pre-existing explicit-emit exception). Its shape must be unchanged
    apart from gaining the new aggregate dimension set, or the deployed
    `life-platform-site-api-dashboard` (which reads exactly this shape for
    six TOP_ROUTES) would silently go blank."""
    resp, emitted = _emitted_route_metrics(_event("/api/healthz"))
    assert resp["statusCode"] == 200
    assert len(emitted) == 1
    d = emitted[0]["_aws"]["CloudWatchMetrics"][0]
    assert ["Route", "Method"] in d["Dimensions"]
