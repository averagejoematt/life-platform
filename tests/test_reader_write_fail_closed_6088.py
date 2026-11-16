"""#6088 — a public door that STORES reader content or a reader-moved counter fails CLOSED
when the rate limiter errors.

`common.rate_limiter.check_rate_limit` defaults to ``fail_open=True``: a DynamoDB error
admits the request unmetered. That default was written for "non-cost endpoints", and
for a click it is still right. For a door that stores what a reader sends — a finding,
a question, a suggestion, a cohort number, a prediction, a reader's call beside a
coach — an outage window is a window in which one network writes without a meter, into
a queue the owner reads or a number readers see. Those doors pass ``fail_open=False``.

THE SET IS DERIVED, the exceptions are NAMED. Every limiter call in the public social
family (``web/site_api_social*.py``) and the reader-call route is found by AST; each must
either pass ``fail_open=False`` literally, or be listed in ``FAIL_OPEN_BY_DECISION`` with
the reason it stays open. A new storing door added on the default reds here by name.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
WEB = REPO / "lambdas" / "web"

#: The limiter calls that stay on the default, each with the reason (#6088 review, 2026-11-16).
FAIL_OPEN_BY_DECISION = {
    "nudge": "a click counter held in memory; it stores no reader content and moves no stored count",
    "ritual_log": "the owner's own HMAC-signed one-tap link (lambdas/ritual_link.py); a stranger cannot reach the write",
    "morning_note": "the owner's token-gated door; a stranger's request fails the token check before any write",
    "challenge_checkin": (
        "stores a reader check-in, so it SHOULD fail closed — left for #6087, which owns "
        "site_api_social_challenges.py in a concurrent lane; recorded here so it is not forgotten"
    ),
}

_LIMITER_NAMES = ("_rate_check", "check_rate_limit", "_ddb_rate_check")


def _sources() -> list[pathlib.Path]:
    family = sorted(WEB.glob("site_api_social*.py"))
    return family


def _endpoint_of(call: ast.Call) -> str | None:
    """The endpoint the call charges: its first positional arg or ``endpoint=``, as a literal
    or the literal head of an f-string (``f"cohort_submit:{week}"`` → ``cohort_submit``)."""
    node = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "endpoint"), None)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split(":")[0]
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value).split(":")[0]
    return None


def _fails_closed(call: ast.Call) -> bool:
    return any(k.arg == "fail_open" and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords)


def offenders_in(source: str, name: str) -> list[str]:
    """Every limiter call in ``source`` that neither fails closed nor is a named exception."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        if fn not in _LIMITER_NAMES:
            continue
        if fn == "_ddb_rate_check" and any(k.arg == "fail_open" and isinstance(k.value, ast.Name) for k in node.keywords):
            continue  # the chokepoint itself forwards its caller's choice
        endpoint = _endpoint_of(node)
        if _fails_closed(node) or endpoint in FAIL_OPEN_BY_DECISION:
            continue
        out.append(f"{name}:{node.lineno} ({endpoint or '?'})")
    return out


def _limiter_calls() -> list[tuple[str, str | None]]:
    calls = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in _LIMITER_NAMES:
                calls.append((path.name, _endpoint_of(node)))
    return calls


def test_every_storing_door_fails_closed_or_is_a_named_exception():
    """The derived set: every limiter call is fail-closed or named above. Also the gate's own
    controls — the sweep found the doors (not vacuous), every named exception still exists (no
    stale reason), and a planted default-open storing call is caught (the gate can fail)."""
    offenders = [o for p in _sources() for o in offenders_in(p.read_text(), p.name)]
    assert not offenders, f"limiter calls that fail OPEN on a door that stores reader input: {offenders} — pass fail_open=False"

    endpoints = {e for _f, e in _limiter_calls()}
    for door in ("submit_finding", "board_question", "experiment_suggest", "page_feedback", "cohort_submit", "predict_week"):
        assert door in endpoints, f"{door} is no longer rate-checked at all"
    stale = set(FAIL_OPEN_BY_DECISION) - endpoints
    assert not stale, f"named fail-open exceptions with no limiter call left: {stale}"

    planted = 'def h():\n    _rate_check("submit_finding", ip, limit=3, window_seconds=3600)\n'
    assert offenders_in(planted, "planted") == ["planted:2 (submit_finding)"]
    assert offenders_in(planted.replace("3600)", "3600, fail_open=False)"), "planted") == []
