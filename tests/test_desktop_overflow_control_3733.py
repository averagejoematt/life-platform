"""tests/test_desktop_overflow_control_3733.py — #3733's must-fail control.

Before #3733, `capture_page`'s horizontal-overflow measurement (`_mobile_overflow`)
only ever ran at the 390px mobile viewport (#1013). A table pushed past its own
container at a FULL DESKTOP width (1216px `.rd-tbl` inside an `overflow-x: visible`
`.rd-sec`, blowing /method/ and /method/cycles/ out sideways by 248px at 1440) had no
gate at all — the sweep could not have caught it even if it had looked, because
nothing measured desktop overflow.

This pins the fix: `capture_page` now runs the SAME `_mobile_overflow` measurement
once at the desktop context's own viewport (skipped only when `context_mobile=True`,
since that pass already opened at 390px and is checked by the existing mobile control
below it). A widened table must red the check; it must never silently push the page.
"""

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import visual_qa  # noqa: E402


class _FakeOverflowPage:
    """Minimal capture_page-compatible fake — every DOM-dependent helper the
    real page would need is monkeypatched by `_isolate_helpers` below; this
    class only has to answer the handful of calls capture_page makes directly."""

    def __init__(self):
        self.viewport_size = {"width": 1440, "height": 900}

    def add_init_script(self, *a, **k):
        pass

    def on(self, *a, **k):
        pass

    def goto(self, url, wait_until=None, timeout=None):
        return None

    def wait_for_timeout(self, ms):
        pass

    def wait_for_selector(self, *a, **k):
        pass

    def set_viewport_size(self, size):
        self.viewport_size = size

    def query_selector_all(self, sel):
        return []

    def query_selector(self, sel):
        return None

    def evaluate(self, script, *a, **k):
        if "__perf" in script:
            return {}
        return None

    def screenshot(self, path=None, full_page=False):
        raise AssertionError("screenshot should not be called — save_screenshots=False")

    def close(self):
        pass


def _isolate_helpers(monkeypatch, overflow_by_call):
    """Neutralize every other capture_page helper and drive `_mobile_overflow`
    from a queue — item 0 answers the desktop-context call (this test's
    subject), item 1 answers the 390px mobile call (#1013, unchanged)."""
    calls = {"n": 0}

    def fake_overflow(page):
        i = min(calls["n"], len(overflow_by_call) - 1)
        calls["n"] += 1
        return overflow_by_call[i]

    for name, value in (
        ("_scroll_and_reveal", lambda page: None),
        ("_check_sections_for_blank", lambda page: []),
        ("_check_stale_text", lambda page: []),
        ("_mobile_overflow", fake_overflow),
        ("_stuck_reveals", lambda page, sel: []),
        ("_app_bar_overflow", lambda page: 0),
        ("_viewport_meta_ok", lambda page: True),
        ("_tap_target_audit", lambda page, sel: []),
        ("_svg_text_floor_findings", lambda page, w: []),
        ("_html_text_floor_findings", lambda page, w: []),
    ):
        monkeypatch.setattr(visual_qa, name, value)
    return calls


def _capture(monkeypatch, overflow_by_call, context_mobile):
    _isolate_helpers(monkeypatch, overflow_by_call)
    page = _FakeOverflowPage()
    context = SimpleNamespace(new_page=lambda: page)
    page_def = {"path": "/method/cycles/", "name": "Cycle vs cycle", "tier": 2}
    return visual_qa.capture_page(
        context,
        page_def,
        screenshot_dir="/tmp/unused-3733",
        save_screenshots=False,
        context_mobile=context_mobile,
        mobile_first_load=False,
    )


def test_desktop_overflow_reds_the_check():
    """Positive control: a table 248px past its container at the desktop
    viewport (the exact live #3733 finding) must red the check by name."""
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _capture(monkeypatch, overflow_by_call=[248, 0], context_mobile=False)
    finally:
        monkeypatch.undo()
    assert result["status"] == "FAIL"
    assert any("Horizontal overflow at desktop viewport" in i and "248px" in i for i in result["issues"]), result["issues"]


def test_no_desktop_overflow_is_clean():
    """Negative case: a table that fits its container (0px overflow) must not
    gate — proving the control isn't a permanent red."""
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _capture(monkeypatch, overflow_by_call=[0, 0], context_mobile=False)
    finally:
        monkeypatch.undo()
    assert result["status"] == "PASS"
    assert not any("Horizontal overflow at desktop viewport" in i for i in result["issues"])


def test_mobile_context_skips_the_desktop_check_not_the_mobile_one():
    """A `--mobile` sweep context (`context_mobile=True`) never opens a real
    desktop viewport — the top-of-function pass IS already at 390px — so the
    desktop-labelled check must be skipped there; the pre-existing 390px
    control (#1013) still fires on the same overflow value."""
    import pytest

    monkeypatch = pytest.MonkeyPatch()
    try:
        result = _capture(monkeypatch, overflow_by_call=[37], context_mobile=True)
    finally:
        monkeypatch.undo()
    assert not any("desktop viewport" in i for i in result["issues"])
    assert any("Horizontal overflow at 390px" in i and "37px" in i for i in result["issues"]), result["issues"]
