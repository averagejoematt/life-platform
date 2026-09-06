"""
tests/test_budget_guard_fail_closed_2824.py — DIL-036 / #2824: the budget guard's
fail-open/fail-closed SPLIT on unreadable budget state.

The defect (verified in source 2026-08-23): current_tier() read SSM
/life-platform/budget-tier through a bare `except Exception: tier = 0` — pure
fail-open. An IAM grant regression, a deleted param, or an SSM outage silently
disabled the monthly ceiling, INCLUDING for the public anonymous endpoints
(/api/ask, /api/board_ask, /api/explain — feature `website_ai`), where an
attacker-facing surface then ran with no budget enforcement and nothing paged.

The owner-decided contract (mutation-proved in BOTH directions here):

  * unreadable tier  → every feature in budget_guard.FAIL_CLOSED_FEATURES is
    DENIED (tier-3-equivalent: the public surface serves its honest 'paused'
    output);
  * unreadable tier  → every OTHER feature keeps the fail-open tier-0 default —
    protect-longest is deliberate (daily_brief_ai, coach narratives, internal
    AI must not be taken down by an SSM blip);
  * readable tier 0  → website_ai allowed (no false closure);
  * each failure class logs the stable token BUDGET_TIER_UNREADABLE at ERROR
    with the class named (the budget-tier-unreadable alarm's metric filter);
  * cache: a cached-good tier keeps serving for the rest of its 5-min window
    (a blip mid-window must not flap the public surface); at the FIRST refresh
    after expiry a failed read flips to unreadable (no stale-grace beyond the
    TTL); an unreadable result is itself cached for the TTL (no SSM hammering).

Guard the SET, not the instance: every behavioral assertion derives its feature
lists from FAIL_CLOSED_FEATURES / _FEATURE_CUTOFF — nothing here hand-lists a
name into both the code and the test. The wire-path section pins that the REAL
public handlers (lambdas/web/site_api_ai_lambda.py) reach this exact enforcement
(fixture-must-be-the-wire), and that allow() is what consults the set.

Run:  python3 -m pytest tests/test_budget_guard_fail_closed_2824.py -v
"""

import ast
import logging
import os
import re
import sys
import time

import pytest
from botocore.exceptions import ClientError

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(_REPO, "lambdas")
sys.path.insert(0, _LAMBDAS)

from ai import budget_guard  # noqa: E402

_SITE_API_AI = os.path.join(_LAMBDAS, "web", "site_api_ai_lambda.py")
_BUDGET_GUARD = os.path.join(_LAMBDAS, "ai", "budget_guard.py")
_CDK_ALARMS = os.path.join(_REPO, "cdk", "stacks", "monitoring_budget_alarms.py")

# The failure classes the split must distinguish (#2824 design point 1).
_PARAM_NOT_FOUND = ClientError({"Error": {"Code": "ParameterNotFound", "Message": "x"}}, "GetParameter")
_ACCESS_DENIED = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetParameter")
_UNEXPECTED = RuntimeError("endpoint imploded")

_FAILURES = [
    (_PARAM_NOT_FOUND, "reason=ParameterNotFound"),
    (_ACCESS_DENIED, "reason=ClientError.AccessDeniedException"),
    (_UNEXPECTED, "reason=Unexpected.RuntimeError"),
]


class _Ssm:
    """Stub SSM client: counts calls; raises `exc` or serves `value`."""

    def __init__(self, exc=None, value="0"):
        self.exc = exc
        self.value = value
        self.calls = 0

    def get_parameter(self, Name):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return {"Parameter": {"Value": self.value}}


def _fresh(guard=budget_guard):
    guard._cache.update({"tier": 0, "ts": 0.0, "readable": True})


@pytest.fixture(autouse=True)
def _isolated_guard_state():
    """Reset the module cache + stub client around every test (the module is a
    process-wide singleton shared with the rest of the suite)."""
    old_ssm = budget_guard._ssm
    _fresh()
    yield
    budget_guard._ssm = old_ssm
    _fresh()


def _with_ssm(exc=None, value="0"):
    stub = _Ssm(exc=exc, value=value)
    budget_guard._ssm = stub
    return stub


# ── 1. Unreadable state → the SET fails closed, everything else fails open ────


@pytest.mark.parametrize("exc,_token", _FAILURES)
def test_unreadable_denies_every_fail_closed_feature(exc, _token):
    _with_ssm(exc=exc)
    for f in budget_guard.FAIL_CLOSED_FEATURES:
        _fresh()
        assert budget_guard.allow(f) is False, f"{f} must fail CLOSED on unreadable budget state"


@pytest.mark.parametrize("exc,_token", _FAILURES)
def test_unreadable_keeps_every_other_feature_fail_open(exc, _token):
    """Protect-longest preserved: the daily brief, coach narratives and internal
    AI are untouched by an SSM blip — derived from the cutoff table, never a
    hand list."""
    _with_ssm(exc=exc)
    fail_open = set(budget_guard._FEATURE_CUTOFF) - set(budget_guard.FAIL_CLOSED_FEATURES)
    assert "daily_brief_ai" in fail_open  # the contract's named exemplar
    for f in sorted(fail_open):
        _fresh()
        assert budget_guard.allow(f) is True, f"{f} must stay FAIL-OPEN on unreadable budget state"


def test_unreadable_hard_stop_path_for_website_ai_matches_tier3():
    """The public surface behaves exactly as at tier 3: allow() is False, i.e.
    the wire's _ai_paused_response() serves the same honest 'paused' payload a
    real tier 3 produces. (bedrock_client's feature-agnostic backstop stays
    fail-open by design — enforcement for website_ai lives at this gate.)"""
    _with_ssm(value="3")
    at_tier3 = {f: budget_guard.allow(f) for f in budget_guard.FAIL_CLOSED_FEATURES}
    _fresh()
    _with_ssm(exc=_ACCESS_DENIED)
    unreadable = {f: budget_guard.allow(f) for f in budget_guard.FAIL_CLOSED_FEATURES}
    assert at_tier3 == unreadable == {f: False for f in budget_guard.FAIL_CLOSED_FEATURES}


def test_unreadable_current_tier_still_reports_zero():
    """current_tier()'s RETURN stays fail-open 0 (the fleet's protect-longest
    consumers, incl. bedrock_client's tier-3 backstop, must not see a phantom
    tier 3 that would take the daily brief down with it)."""
    _with_ssm(exc=_ACCESS_DENIED)
    assert budget_guard.current_tier() == 0


def test_garbage_tier_value_is_unreadable_not_tier0():
    """An unparseable SSM value is unreadable state (Unexpected.ValueError),
    never a silent tier 0 for the public surface."""
    _with_ssm(value="banana")
    for f in budget_guard.FAIL_CLOSED_FEATURES:
        _fresh()
        assert budget_guard.allow(f) is False


# ── 2. No false closure ───────────────────────────────────────────────────────


def test_readable_tier0_allows_website_ai():
    _with_ssm(value="0")
    for f in budget_guard.FAIL_CLOSED_FEATURES:
        _fresh()
        assert budget_guard.allow(f) is True, f"{f} must run normally on a readable tier 0"


def test_readable_tiers_keep_the_ladder_semantics():
    """The split changes NOTHING while the tier is readable — the whole ladder
    (tests/test_budget_guard_ladder.py) still holds; spot-pin the edges here."""
    for tier, expect in (("0", True), ("2", True), ("3", False)):
        _fresh()
        _with_ssm(value=tier)
        for f in budget_guard.FAIL_CLOSED_FEATURES:
            assert budget_guard.allow(f) is expect, (f, tier)


# ── 3. Observability: each failure class names itself, loudly ─────────────────


@pytest.mark.parametrize("exc,token", _FAILURES)
def test_unreadable_logs_the_stable_token_with_the_class_named(exc, token, caplog):
    _with_ssm(exc=exc)
    with caplog.at_level(logging.ERROR, logger="ai.budget_guard"):
        budget_guard.current_tier()
    hits = [r for r in caplog.records if "BUDGET_TIER_UNREADABLE" in r.getMessage()]
    assert len(hits) == 1, "exactly one loud ERROR per failed refresh"
    assert hits[0].levelno == logging.ERROR
    assert token in hits[0].getMessage(), f"the failure class must be named: {hits[0].getMessage()}"


def test_alarm_metric_filter_token_matches_the_logged_literal():
    """The CDK metric filter (cdk/stacks/monitoring_budget_alarms.py) and the
    guard's log line must share one literal — pinned so they cannot drift."""
    src = open(_CDK_ALARMS, encoding="utf-8").read()
    m = re.search(r'UNREADABLE_TOKEN\s*=\s*"([A-Z_]+)"', src)
    assert m, "monitoring_budget_alarms.py must pin UNREADABLE_TOKEN"
    token = m.group(1)
    guard_src = open(_BUDGET_GUARD, encoding="utf-8").read()
    assert f'"{token} reason=%s' in guard_src, "budget_guard must log the exact token the metric filter matches"
    assert '"/aws/lambda/life-platform-site-api-ai"' in src, "the filter must scope to the ENFORCING public consumer's log group"


# ── 4. Cache semantics (the contract in the module docstring) ─────────────────


def test_cached_good_tier_survives_a_mid_window_blip():
    """A blip mid-window must not flap the public surface: a good tier cached
    within the TTL keeps serving even while SSM is down."""
    stub = _with_ssm(value="0")
    assert budget_guard.allow("website_ai") is True
    assert stub.calls == 1
    stub.exc = _ACCESS_DENIED  # SSM dies mid-window
    assert budget_guard.allow("website_ai") is True, "cached-good tier must keep serving inside the TTL"
    assert stub.calls == 1, "no re-read inside the TTL"


def test_expired_cache_plus_failed_read_fails_closed_immediately():
    """No stale-grace beyond the TTL: the FIRST refresh after expiry that fails
    flips the public surface closed."""
    stub = _with_ssm(value="0")
    assert budget_guard.allow("website_ai") is True
    stub.exc = _ACCESS_DENIED
    budget_guard._cache["ts"] = time.time() - budget_guard._CACHE_TTL_S - 1  # expire the window
    assert budget_guard.allow("website_ai") is False, "post-TTL failed read must fail closed, not coast on stale state"
    assert budget_guard.current_tier() == 0  # fleet stays fail-open


def test_unreadable_state_is_cached_for_the_ttl_no_ssm_hammering():
    stub = _with_ssm(exc=_ACCESS_DENIED)
    assert budget_guard.allow("website_ai") is False
    for _ in range(5):
        assert budget_guard.allow("website_ai") is False
    assert stub.calls == 1, "the unreadable result must be cached like a tier — one read per TTL window"


def test_recovery_lands_at_the_next_refresh():
    stub = _with_ssm(exc=_ACCESS_DENIED)
    assert budget_guard.allow("website_ai") is False
    stub.exc = None  # SSM comes back
    budget_guard._cache["ts"] = time.time() - budget_guard._CACHE_TTL_S - 1
    assert budget_guard.allow("website_ai") is True, "one TTL after SSM recovers, the public surface reopens"
    assert stub.calls == 2


# ── 5. Guard the SET + fixture-must-be-the-wire ───────────────────────────────


def test_fail_closed_membership_is_the_public_surface_and_classified():
    assert "website_ai" in budget_guard.FAIL_CLOSED_FEATURES
    for f in budget_guard.FAIL_CLOSED_FEATURES:
        assert f in budget_guard._FEATURE_CUTOFF, f"{f} must be a classified ladder feature"
        assert budget_guard._FEATURE_CUTOFF[f] == budget_guard._HARD_STOP_TIER, (
            f"{f}: only band-3 public surfaces belong in FAIL_CLOSED_FEATURES — "
            "a lower-band feature failing closed would invert protect-longest"
        )


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def test_allow_consults_the_set_not_an_instance():
    """AST: the enforcement in allow() reads FAIL_CLOSED_FEATURES — behavior and
    membership derive from the ONE exported set."""
    tree = ast.parse(open(_BUDGET_GUARD, encoding="utf-8").read())
    names = {n.id for n in ast.walk(_func(tree, "allow")) if isinstance(n, ast.Name)}
    assert "FAIL_CLOSED_FEATURES" in names, "allow() must consult FAIL_CLOSED_FEATURES"


def test_no_call_site_hand_lists_the_fail_closed_membership():
    """No lambdas/ or mcp/ call site re-declares its own fail-closed list — the
    set lives in budget_guard alone."""
    offenders = []
    for root in (_LAMBDAS, os.path.join(_REPO, "mcp")):
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                if os.path.samefile(path, _BUDGET_GUARD):
                    continue
                text = open(path, encoding="utf-8").read()
                if re.search(r"FAIL_CLOSED_FEATURES\s*=", text):
                    offenders.append(path)
    assert offenders == [], f"fail-closed membership re-declared outside budget_guard: {offenders}"


def test_wire_path_public_handlers_gate_on_the_guard():
    """Fixture must be the wire: the REAL public handlers in
    site_api_ai_lambda.py each check _ai_paused_response() FIRST, and that
    helper consults allow(\"website_ai\") — so the fail-closed denial lands on
    the exact call path a reader (or attacker) executes."""
    src = open(_SITE_API_AI, encoding="utf-8").read()
    tree = ast.parse(src)
    paused = _func(tree, "_ai_paused_response")
    paused_src = ast.get_source_segment(src, paused)
    assert re.search(r'allow\(\s*["\']website_ai["\']\s*\)', paused_src), "_ai_paused_response must consult allow('website_ai')"
    for handler in ("_handle_ask", "_handle_explain", "_handle_board_ask"):
        node = _func(tree, handler)
        calls = [
            n.func.id
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_ai_paused_response"
        ]
        assert calls, f"{handler} must gate on _ai_paused_response() — the wire the fail-closed contract enforces"
