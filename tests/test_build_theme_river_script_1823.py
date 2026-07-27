"""tests/test_build_theme_river_script_1823.py — #1823: the theme-river BUILD script.

Two defects, both in `scripts/v4_build_theme_river.py::build_artifact` (the
aggregation itself, `lambdas/theme_river.py`, is covered by
tests/test_theme_river_1381.py and is untouched here):

  1. Inverted window: `build_artifact` used `start = EXPERIMENT_START,
     end = date.today()` with no clamp. A pre-genesis run (today before the
     experiment's start date — e.g. the countdown window ahead of a reset's
     genesis) emitted a window with end < start. Fixed by clamping
     `end = max(start, today)`.
  2. Wired into no deploy path — covered structurally below by asserting the
     build step actually appears in deploy/sync_site_to_s3.sh alongside its
     v4_build_* siblings (the regression that would silently reintroduce a
     hand-run-only artifact).
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import v4_build_theme_river as vbtr  # noqa: E402


def test_pre_genesis_window_is_not_inverted(monkeypatch):
    """today before EXPERIMENT_START must clamp to end == start, never end < start."""
    monkeypatch.setattr(vbtr, "EXPERIMENT_START", "2026-07-27")

    class _FakeDate:
        @staticmethod
        def today():
            import datetime as _dt

            return _dt.date(2026, 7, 26)

    monkeypatch.setattr(vbtr, "date", _FakeDate)
    artifact = vbtr.build_artifact(live=False)
    assert artifact["window"]["start"] == "2026-07-27"
    assert artifact["window"]["end"] == "2026-07-27", "end must clamp up to start, never invert"
    assert artifact["window"]["weeks"] >= 1


def test_post_genesis_window_uses_today_as_end(monkeypatch):
    """Once today is on/after EXPERIMENT_START, the window still runs start..today."""
    monkeypatch.setattr(vbtr, "EXPERIMENT_START", "2026-07-27")

    class _FakeDate:
        @staticmethod
        def today():
            import datetime as _dt

            return _dt.date(2026, 8, 5)

    monkeypatch.setattr(vbtr, "date", _FakeDate)
    artifact = vbtr.build_artifact(live=False)
    assert artifact["window"]["start"] == "2026-07-27"
    assert artifact["window"]["end"] == "2026-08-05"


def test_build_script_wired_into_deploy_path():
    """#1823's core defect: the generator ran nowhere but a human's terminal. Assert
    it's invoked from sync_site_to_s3.sh alongside its v4_build_* siblings so a future
    edit can't silently drop it back off the deploy path."""
    sync_script = os.path.join(_REPO, "deploy", "sync_site_to_s3.sh")
    with open(sync_script, encoding="utf-8") as f:
        content = f.read()
    assert "v4_build_theme_river.py" in content, "theme-river build must run as part of the site deploy path"
