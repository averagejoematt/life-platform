"""#403 — 'explain this page': server-grounded, injection-closed by construction.

Pins the contract: the client sends ONLY an allowlisted surface name (unknown
surfaces 400 before any fetch or model spend), the server refetches the real
JSON itself, the payload handed to the model is deterministically bounded, the
prompt enforces narrate-don't-calculate + honest-empty-state rules, and the
routing (lambda + CloudFront) exists.
"""

import glob
import json
import os
import sys

from bundle_stubs import stub_bundled_module

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_STACK_SRC = open(os.path.join(_REPO, "cdk/stacks/web_stack.py")).read()
EXPLAIN_JS = open(os.path.join(_REPO, "site/assets/js/explain.js")).read()
# #581: evidence.js split into a router + per-family evidence_*.js modules — concatenate
# the whole graph so a moved renderer (e.g. sleepCorrelationBoard) still gets found.
EVIDENCE_JS_ALL = "\n".join(open(p).read() for p in sorted(glob.glob(os.path.join(_REPO, "site/assets/js/evidence*.js"))))


def _ai():
    from web import site_api_ai_lambda as ai

    return ai


def _post_event(body: dict) -> dict:
    return {
        "rawPath": "/api/explain",
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.9"}},
        "body": json.dumps(body),
        "headers": {},
    }


def test_unknown_surface_400s_before_any_spend(monkeypatch):
    ai = _ai()
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)

    def _boom(*a, **k):
        raise AssertionError("fetch/model must not run for an unknown surface")

    monkeypatch.setattr(ai, "_fetch_surface_json", _boom)
    resp = ai._handle_explain(_post_event({"surface": "../../etc/passwd"}))
    assert resp["statusCode"] == 400


def test_client_numbers_are_never_trusted(monkeypatch):
    """The body carries only a surface name — any client-supplied 'data' is
    ignored; the server refetches. We assert the fetched payload (not the
    client junk) reaches the model."""
    ai = _ai()
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_ask_rate_check", lambda ip, limit=5: (True, 4))
    monkeypatch.setattr(ai, "_fetch_surface_json", lambda s: {"deltas": [{"label": "Recovery", "delta": 3.7}]})
    captured = {}

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            captured["user"] = req["messages"][0]["content"]
            return {"content": [{"type": "text", "text": "Recovery moved 3.7 this month."}], "usage": {}}

    stub_bundled_module(monkeypatch, "ai.bedrock_client", _FakeBedrock)
    resp = ai._handle_explain(_post_event({"surface": "what_changed", "data": {"weight": 12345}}))
    assert resp["statusCode"] == 200
    assert "3.7" in captured["user"]
    assert "12345" not in captured["user"]  # client junk never reaches the model
    assert json.loads(resp["body"])["explanation"].startswith("Recovery moved")


def test_ungrounded_numbers_fail_closed(monkeypatch):
    ai = _ai()
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_ask_rate_check", lambda ip, limit=5: (True, 4))
    monkeypatch.setattr(ai, "_fetch_surface_json", lambda s: {"deltas": []})

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            return {"content": [{"type": "text", "text": "HRV climbed from 48 to 63 ms this month."}], "usage": {}}

    stub_bundled_module(monkeypatch, "ai.bedrock_client", _FakeBedrock)
    resp = ai._handle_explain(_post_event({"surface": "what_changed"}))
    body = json.loads(resp["body"])
    assert "rather not narrate numbers" in body["explanation"]
    assert "48" not in body["explanation"] and "63" not in body["explanation"]


def _simulate_partial_bundle_missing(monkeypatch, dotted: str) -> None:
    """Simulate #2393's real-world failure mode: a partial deploy bundle where
    ``dotted`` (e.g. "ai.grounded_generation") is simply absent from the zip while
    sibling modules (bedrock_client) import fine.

    Setting ``sys.modules[dotted] = None`` alone is not enough — CPython's
    ``from package import name`` first checks whether the PARENT package already has
    ``name`` bound as an attribute (true as soon as anything in the process imported
    it for real, which earlier tests in this suite will have done) and returns that
    attribute WITHOUT ever raising, silently ignoring the None sentinel (see
    ``tests/bundle_stubs.py``'s docstring for the same trap). So both the sys.modules
    entry AND the parent-package attribute must be cleared for the import to actually
    fail the way a missing bundle file would.
    """
    import importlib

    pkg_name, _, attr = dotted.rpartition(".")
    pkg = importlib.import_module(pkg_name)
    monkeypatch.delattr(pkg, attr, raising=False)
    monkeypatch.setitem(sys.modules, dotted, None)


def test_partial_bundle_importerror_fails_closed(monkeypatch):
    """#2393 mutation proof: the ADR-104 gate used to sit inside a bare
    ``except ImportError: pass`` — a partial bundle regression (grounded_generation
    or grounding_gate_params missing while bedrock_client imports fine, so execution
    gets past the surface fetch and the model call) served the model's raw,
    ungrounded output with zero signal. The gate must now fail CLOSED: same refusal
    copy as a normal ungrounded-numbers finding, not the raw text."""
    ai = _ai()
    monkeypatch.setattr(ai, "_ai_paused_response", lambda: None)
    monkeypatch.setattr(ai, "_ask_rate_check", lambda ip, limit=5: (True, 4))
    monkeypatch.setattr(ai, "_fetch_surface_json", lambda s: {"deltas": []})

    class _FakeBedrock:
        @staticmethod
        def invoke(req):
            # A number that appears NOWHERE in the fetched payload — exactly what the
            # grounding gate exists to catch. If the gate is silently skipped (the
            # bug), this ungated text serves verbatim.
            return {"content": [{"type": "text", "text": "HRV climbed from 48 to 63 ms this month."}], "usage": {}}

    stub_bundled_module(monkeypatch, "ai.bedrock_client", _FakeBedrock)
    _simulate_partial_bundle_missing(monkeypatch, "ai.grounded_generation")

    resp = ai._handle_explain(_post_event({"surface": "what_changed"}))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "rather not narrate numbers" in body["explanation"]
    assert "48" not in body["explanation"] and "63" not in body["explanation"]


def test_shrink_bounds_lists_not_midtoken():
    ai = _ai()
    fat = {"deltas": [{"i": i, "label": f"metric-{i}"} for i in range(400)]}
    out = ai._shrink_for_prompt(fat)
    parsed = json.loads(out)  # still valid JSON — lists trimmed, text not cut
    assert len(parsed["deltas"]) == 12


def test_prompt_carries_the_honesty_rules():
    ai = _ai()
    assert "never compute, average, or extrapolate" in ai._EXPLAIN_SYSTEM
    assert "never causal claims, never health advice" in ai._EXPLAIN_SYSTEM
    assert "say so honestly" in ai._EXPLAIN_SYSTEM
    assert "The reader is NOT Matthew" in ai._EXPLAIN_SYSTEM


def test_surface_allowlist_is_the_named_dense_surfaces():
    ai = _ai()
    assert set(ai._EXPLAIN_SURFACES) == {"observatory_week", "what_changed", "sleep_correlations"}


def test_routing_exists_lambda_and_cloudfront():
    idx = WEB_STACK_SRC.find('path_pattern="/api/explain"')
    assert idx != -1
    assert 'target_origin_id="AiLambdaOrigin"' in WEB_STACK_SRC[idx : idx + 300]
    ai_src = open(os.path.join(_REPO, "lambdas/web/site_api_ai_lambda.py")).read()
    assert '"/api/explain"' in ai_src


def test_frontend_sends_only_the_surface_name():
    assert "JSON.stringify({ surface: mount.dataset.explain })" in EXPLAIN_JS
    # And the mounts exist on the three named dense surfaces.
    cockpit = open(os.path.join(_REPO, "site/assets/js/cockpit.js")).read()
    assert 'explainMount("observatory_week")' in cockpit
    assert 'explainMount("what_changed")' in cockpit
    assert 'explainMount("sleep_correlations")' in EVIDENCE_JS_ALL
