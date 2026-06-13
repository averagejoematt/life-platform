"""tests/test_experiment_date_window.py — guard against the future-genesis 500.

When a reset sets EXPERIMENT_START to a future date (genesis = tomorrow), the
site-API's _experiment_date(N) used to return that future date as a query lower
bound. Handlers that call Key('sk').between(_experiment_date(N), today) DIRECTLY
(e.g. handle_habits) then threw a DynamoDB ValidationException — '/api/habits'
500'd and the visual-QA gate failed (2026-06-13, cycle-4 genesis 2026-06-14).

_experiment_date now clamps the result to today, so the range is always valid
(empty [today, today] = 'no data yet') instead of crashing. These tests pin that.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "web"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")

import site_api_common as C  # noqa: E402


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_future_genesis_clamps_to_today(monkeypatch):
    """Genesis in the future → lower bound must not exceed today (no ValidationException)."""
    future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
    monkeypatch.setattr(C, "EXPERIMENT_START", future)
    start = C._experiment_date(90)
    assert start <= _today(), f"lower bound {start} exceeds today {_today()} — Key.between would 500"
    assert start == _today(), "future genesis should yield the empty [today, today] window"


def test_normal_genesis_unchanged(monkeypatch):
    """Genesis well in the past → behaves exactly as before (N days ago)."""
    past = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    monkeypatch.setattr(C, "EXPERIMENT_START", past)
    start = C._experiment_date(90)
    expected = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    assert start == expected, f"expected 90d-ago {expected}, got {start}"


def test_genesis_today_is_valid(monkeypatch):
    """Genesis == today → lower bound == today (valid single-day range)."""
    monkeypatch.setattr(C, "EXPERIMENT_START", _today())
    start = C._experiment_date(90)
    assert start == _today() and start <= _today()
