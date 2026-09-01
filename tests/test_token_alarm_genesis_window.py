"""tests/test_token_alarm_genesis_window.py — #1961: the genesis rebuild
token-alarm suppression window.

Regression guard (the issue's acceptance criteria, literally):
  1. `token_alarm_window.is_within_token_alarm_window()` correctly bounds
     `[start, end)` and `window_for_genesis()` computes the right offsets.
  2. A platform-total token alarm breach INSIDE the stamped window routes
     digest-only (the automated urgent-triage dispatcher does not fire a
     `repository_dispatch`) — a breach OUTSIDE the window routes urgent as
     before.
  3. Non-token urgent alarms are UNAFFECTED by the window either way (the
     suppression is scoped to the platform-total token alarm specifically,
     never a blanket "genesis week = no pages" rule).

Uses the same `_drive_dispatcher` pattern as tests/test_oauth_alarm_coverage.py
(monkeypatch `_dispatch`/`_seen`/`_mark`, feed a synthetic SNS ALARM event).
"""

import importlib.util
import json
import os
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common import token_alarm_window as taw  # noqa: E402


def _load(name: str, subdir: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO, subdir, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("restart_pipeline", "deploy")


# ── 1. Pure window math ──────────────────────────────────────────────────────


def test_window_for_genesis_applies_the_before_after_offsets():
    start, end = taw.window_for_genesis("2026-08-03")
    assert start == "2026-08-02"  # WINDOW_DAYS_BEFORE = 1
    assert end == "2026-08-10"  # WINDOW_DAYS_AFTER = 7


def test_is_within_token_alarm_window_boundaries(monkeypatch):
    monkeypatch.setattr(taw, "TOKEN_ALARM_GENESIS_WINDOW", ("2026-08-02", "2026-08-10"))
    assert taw.is_within_token_alarm_window(date(2026, 8, 1)) is False  # before start
    assert taw.is_within_token_alarm_window(date(2026, 8, 2)) is True  # inclusive start
    assert taw.is_within_token_alarm_window(date(2026, 8, 6)) is True  # mid-window
    assert taw.is_within_token_alarm_window(date(2026, 8, 9)) is True  # last day inside
    assert taw.is_within_token_alarm_window(date(2026, 8, 10)) is False  # exclusive end
    assert taw.is_within_token_alarm_window(date(2026, 8, 11)) is False  # after end


def test_is_within_token_alarm_window_defaults_to_today(monkeypatch):
    monkeypatch.setattr(taw, "TOKEN_ALARM_GENESIS_WINDOW", ("2020-01-01", "2099-01-01"))
    assert taw.is_within_token_alarm_window() is True


def test_malformed_stamp_fails_safe_to_not_in_window(monkeypatch):
    """A corrupt/half-edited stamp must never silently suppress a real page —
    the safer failure mode is 'not in window' (alarm still pages)."""
    monkeypatch.setattr(taw, "TOKEN_ALARM_GENESIS_WINDOW", ("not-a-date", "also-not-a-date"))
    assert taw.is_within_token_alarm_window(date(2026, 8, 3)) is False


def test_stamped_module_constant_is_internally_consistent():
    """The committed TOKEN_ALARM_GENESIS_WINDOW must match what window_for_genesis
    would derive for SOME genesis (i.e. it was actually stamped by the pipeline
    formula, not hand-edited to something else)."""
    start, end = taw.TOKEN_ALARM_GENESIS_WINDOW
    # Reconstruct the genesis window_for_genesis would need to have produced this.
    from datetime import timedelta

    implied_genesis = date.fromisoformat(start) + timedelta(days=taw.WINDOW_DAYS_BEFORE)
    recomputed = taw.window_for_genesis(implied_genesis.isoformat())
    assert recomputed == (start, end), "stamped window doesn't match window_for_genesis() — was it hand-edited?"


# ── 2 + 3. Dispatcher routing ────────────────────────────────────────────────


def _sns_event(alarm_name, metric_name="AnthropicOutputTokens", namespace="LifePlatform/AI"):
    message = {
        "AlarmName": alarm_name,
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [183414.0] was greater than or equal to the threshold (150000.0).",
        "StateChangeTime": "2026-08-04T12:00:00.000+0000",
        "Trigger": {"MetricName": metric_name, "Namespace": namespace, "Dimensions": []},
    }
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


def _drive_dispatcher(monkeypatch, event, in_window):
    from operational import remediation_dispatcher_lambda as disp

    sent = []
    marked = []
    monkeypatch.setattr(disp, "_dispatch", lambda payload: sent.append(payload))
    monkeypatch.setattr(disp, "_seen", lambda key: False)
    monkeypatch.setattr(disp, "_mark", lambda key, payload: marked.append(payload))
    monkeypatch.setattr(disp, "is_within_token_alarm_window", lambda check_date=None: in_window)
    result = disp.lambda_handler(event, None)
    return sent, marked, json.loads(result["body"])


def test_token_platform_breach_inside_window_routes_digest_only(monkeypatch):
    sent, marked, body = _drive_dispatcher(monkeypatch, _sns_event("ai-tokens-platform-daily-total"), in_window=True)
    assert sent == [], "a predicted genesis-rebuild token spike must NOT fire an urgent repository_dispatch"
    assert body["skipped_genesis_window"] == 1
    assert body["dispatched"] == 0
    assert len(marked) == 1 and marked[0]["suppressed"] is True
    assert marked[0]["suppressed_reason"] == "genesis_rebuild_window"


def test_token_platform_breach_outside_window_routes_urgent(monkeypatch):
    sent, marked, body = _drive_dispatcher(monkeypatch, _sns_event("ai-tokens-platform-daily-total"), in_window=False)
    assert len(sent) == 1, "outside the stamped window a token-platform breach is unexplained and must still page"
    assert sent[0]["alarm_name"] == "ai-tokens-platform-daily-total"
    assert body["dispatched"] == 1
    assert body["skipped_genesis_window"] == 0
    assert marked[0]["suppressed"] is False


def test_unrelated_urgent_alarm_ignores_the_window(monkeypatch):
    """The window is scoped to the token-platform alarm ONLY — a genuinely
    unrelated urgent alarm (e.g. ddb-throttled) must page even while the genesis
    window is active. Proves this isn't a blanket 'quiet week' suppression."""
    sent, marked, body = _drive_dispatcher(
        monkeypatch,
        _sns_event("ddb-throttled-requests", metric_name="ThrottledRequests", namespace="AWS/DynamoDB"),
        in_window=True,
    )
    assert len(sent) == 1, "an unrelated urgent alarm must dispatch even during the genesis rebuild window"
    assert body["skipped_genesis_window"] == 0


# ── restart_pipeline.py's stamping function ──────────────────────────────────


def test_stamp_token_alarm_window_writes_the_computed_window(tmp_path, monkeypatch):
    """restart_pipeline.stamp_token_alarm_window() must actually rewrite the
    tuple to what window_for_genesis(target) computes, and must be idempotent
    on a second call with the same genesis. Operates on a scratch copy of the
    real module text so the test never touches the committed file."""
    real_text = taw.__file__
    with open(real_text) as f:
        original_source = f.read()
    scratch = tmp_path / "token_alarm_window.py"
    scratch.write_text(original_source)
    monkeypatch.setattr(pipeline, "TOKEN_ALARM_WINDOW_FILE", scratch)

    # DERIVE a genesis that is NOT the one already stamped in the committed
    # module — a pinned date here fails on exactly the cycle whose window is
    # committed (found live on the 2026-09-01 reset eve: the reset had already
    # stamped that genesis, so the "first" stamp was a no-op). Two weeks past
    # the committed window's start is never the committed genesis.
    committed_start = date.fromisoformat(taw.TOKEN_ALARM_GENESIS_WINDOW[0])
    target = (committed_start + timedelta(days=14 + taw.WINDOW_DAYS_BEFORE)).isoformat()
    want_start, want_end = taw.window_for_genesis(target)

    status1 = pipeline.stamp_token_alarm_window(target, apply=True)
    assert status1.startswith("stamped")
    new_text = scratch.read_text()
    assert f'TOKEN_ALARM_GENESIS_WINDOW = ("{want_start}", "{want_end}")' in new_text

    # Idempotent: re-stamping the SAME genesis is a no-op status.
    status2 = pipeline.stamp_token_alarm_window(target, apply=True)
    assert status2.startswith("already-stamped")

    # Dry-run never writes.
    before = scratch.read_text()
    status3 = pipeline.stamp_token_alarm_window("2026-10-15", apply=False)
    assert status3.startswith("would-stamp")
    assert scratch.read_text() == before


def test_non_urgent_alarm_still_skipped_by_the_ordinary_filter(monkeypatch):
    """Sanity: the new check sits AFTER the existing URGENT_PATTERNS filter, so a
    routine alarm that was never urgent in the first place is unaffected."""
    sent, marked, body = _drive_dispatcher(monkeypatch, _sns_event("garmin-ingestion-error"), in_window=True)
    assert sent == []
    assert body["skipped_filter"] == 1
    assert body["skipped_genesis_window"] == 0
