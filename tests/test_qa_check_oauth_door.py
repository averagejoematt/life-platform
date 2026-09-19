"""#3620 (security ROW6) — the OAuth-door leg, and the allowlist it depends on.

Two things are under test and they fail for different reasons:

  A. The leg's VERDICT MAPPING. A probe that reports PASS on an open door is
     worse than no probe, and a probe that reports FAIL when it merely could not
     reach the host trains people to ignore it. So every arm is exercised against
     a stubbed transport: the open-door shapes must be FAIL, the refusal shapes
     PASS, and every could-not-observe shape YELLOW (`passed is None`).

  B. The ALLOWLIST RATCHET the box asks for. `mcp/handler.py`'s
     `_DEFAULT_REDIRECT_HOSTS` is the only thing that stops `/register`'s
     arbitrary `redirect_uris` becoming an open redirect that mints a real code.
     It is read by AST here — never imported, because importing mcp/handler runs
     its module-level AWS wiring — so adding a host is a deliberate two-file
     edit with a reviewer looking at the diff.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import qa_check_oauth_door as door  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HANDLER = os.path.join(_REPO, "mcp", "handler.py")

# The ratchet. Growing this requires editing BOTH this tuple and mcp/handler.py.
_RATCHET_REDIRECT_HOSTS = ("claude.ai", "claude.com", "anthropic.com")


def _default_redirect_hosts():
    """Read `_DEFAULT_REDIRECT_HOSTS` out of mcp/handler.py by AST, no import."""
    tree = ast.parse(open(_HANDLER).read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_DEFAULT_REDIRECT_HOSTS" in names:
                return tuple(ast.literal_eval(node.value))
    raise AssertionError("_DEFAULT_REDIRECT_HOSTS not found in mcp/handler.py — the allowlist moved; re-point this ratchet")


# ── B: the allowlist ratchet ────────────────────────────────────────────────
def test_redirect_host_allowlist_has_not_grown():
    live = _default_redirect_hosts()
    added = set(live) - set(_RATCHET_REDIRECT_HOSTS)
    assert not added, (
        f"mcp/handler.py now allows OAuth callbacks on {sorted(added)}. That host can receive a minted "
        f"authorization code. If intended, add it to _RATCHET_REDIRECT_HOSTS here in the same PR."
    )


def test_the_ratchet_reads_a_real_tuple():
    """Control: an AST read that silently returned () would pass the ratchet forever."""
    assert "claude.ai" in _default_redirect_hosts()


def test_the_probe_targets_an_allowlisted_host():
    """The leg's own premise: probe 1 is only meaningful if its redirect IS allowed."""
    from urllib.parse import urlparse

    host = urlparse(door._ALLOWED_REDIRECT).hostname
    assert host in _default_redirect_hosts(), f"{host} is not allowlisted — probe 1 would FAIL for the wrong reason"
    foreign = urlparse(door._FOREIGN_REDIRECT).hostname
    assert foreign not in _default_redirect_hosts(), "the 'foreign' probe target is allowlisted — probe 3 is vacuous"


# ── A: verdict mapping ──────────────────────────────────────────────────────
def _stub(monkeypatch, responses):
    """`responses` maps a URL substring -> (status, headers, body) or an Exception."""

    def fake(url, *, method="GET", data=None, headers=None):
        for frag, resp in responses.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"probe hit an unstubbed URL: {url}")

    monkeypatch.setattr(door, "_request", fake)


BASE = "https://example-mcp.lambda-url.us-west-2.on.aws"


def test_consent_form_pass(monkeypatch):
    _stub(monkeypatch, {"/authorize": (200, {}, "<html><form method=post>…</form></html>")})
    c = door._check_consent_form(BASE)
    assert c.passed is True, c.message


def test_consent_form_auto_approval_is_fail(monkeypatch):
    """#893's defect: a 302 straight back to the client, no consent."""
    _stub(monkeypatch, {"/authorize": (302, {"Location": f"{door._ALLOWED_REDIRECT}?code=x"}, "")})
    c = door._check_consent_form(BASE)
    assert c.passed is False
    assert "AUTO-APPROVED" in c.message


def test_consent_form_5xx_is_yellow(monkeypatch):
    _stub(monkeypatch, {"/authorize": (503, {}, "")})
    assert door._check_consent_form(BASE).passed is None


def test_consent_form_network_error_is_yellow(monkeypatch):
    _stub(monkeypatch, {"/authorize": TimeoutError("timed out")})
    c = door._check_consent_form(BASE)
    assert c.passed is None and "could not observe" in c.message


def test_token_refusal_is_pass(monkeypatch):
    _stub(monkeypatch, {"/token": (400, {}, '{"error":"invalid_grant"}')})
    assert door._check_token_without_code(BASE).passed is True


def test_token_200_on_unminted_code_is_fail(monkeypatch):
    _stub(monkeypatch, {"/token": (200, {}, '{"access_token":"…"}')})
    c = door._check_token_without_code(BASE)
    assert c.passed is False and "NEVER minted" in c.message


def test_foreign_redirect_refusal_is_pass(monkeypatch):
    _stub(monkeypatch, {"/register": (201, {}, "{}"), "/authorize": (400, {}, '{"error":"invalid_request"}')})
    c = door._check_foreign_redirect_refused(BASE)
    assert c.passed is True and "/register → 201" in c.message


def test_foreign_redirect_302_is_open_redirect_fail(monkeypatch):
    _stub(monkeypatch, {"/register": (201, {}, "{}"), "/authorize": (302, {"Location": door._FOREIGN_REDIRECT}, "")})
    c = door._check_foreign_redirect_refused(BASE)
    assert c.passed is False and "OPEN REDIRECT" in c.message


def test_register_failure_does_not_mask_the_authorize_verdict(monkeypatch):
    """A /register that 404s must not turn probe 3 green or yellow — the property
    under test is what /authorize does, registered or not."""
    _stub(monkeypatch, {"/register": ConnectionError("refused"), "/authorize": (302, {"Location": door._FOREIGN_REDIRECT}, "")})
    c = door._check_foreign_redirect_refused(BASE)
    assert c.passed is False
    assert "/register unreachable" in c.message


def test_bearer_required_pass(monkeypatch):
    _stub(monkeypatch, {"on.aws": (401, {}, "unauthorized")})
    assert door._check_mcp_requires_bearer(BASE).passed is True


def test_anonymous_tool_surface_is_fail(monkeypatch):
    _stub(monkeypatch, {"on.aws": (200, {}, '{"result":{"tools":[]}}')})
    c = door._check_mcp_requires_bearer(BASE)
    assert c.passed is False and "ANONYMOUS" in c.message


def test_undiscoverable_url_yields_four_yellows(monkeypatch):
    monkeypatch.setattr(door, "resolve_mcp_url", lambda: "")
    out = door.checks()
    assert len(out) == 4
    assert all(c.passed is None for c in out)
    assert all("could not observe" in c.message for c in out)


def test_all_four_probes_run_when_the_url_resolves(monkeypatch):
    monkeypatch.setattr(door, "resolve_mcp_url", lambda: BASE)
    _stub(
        monkeypatch,
        {
            "/authorize?": (400, {}, "{}"),  # both authorize probes land here
            "/token": (400, {}, "{}"),
            "/register": (201, {}, "{}"),
            "on.aws": (401, {}, ""),
        },
    )
    out = door.checks()
    assert [c.name for c in out] == [
        "oauth:consent_form",
        "oauth:token_unbound",
        "oauth:foreign_redirect",
        "oauth:bearer_required",
    ]


def test_the_leg_is_registered_in_qa_smoke():
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")).read()
    assert "qa_check_oauth_door.checks" in src, "the leg exists but nothing runs it nightly"


def test_no_metric_series_was_minted():
    """#3620's rent block: aggregate EMF counts only — a per-check series is
    $0.30/mo for information the run already carries."""
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_check_oauth_door.py")).read()
    for forbidden in ("put_metric_data", "PutMetricData", "_aws", "CloudWatchMetrics"):
        assert forbidden not in src, f"the leg emits its own metric ({forbidden})"


@pytest.mark.parametrize("partition_attr", ["partition"])
def test_every_check_is_content_truth(monkeypatch, partition_attr):
    """A DEPLOY_HEALTH verdict here would wire the door probe to fleet auto-rollback,
    which cannot repair an allowlist or a Function-URL auth-mode change."""
    monkeypatch.setattr(door, "resolve_mcp_url", lambda: "")
    assert all(getattr(c, partition_attr) == "content_truth" for c in door.checks())
