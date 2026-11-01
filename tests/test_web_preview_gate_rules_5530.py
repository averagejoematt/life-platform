"""tests/test_web_preview_gate_rules_5530.py — the render gate's static rules, pinned (#5530).

The leak rule is POSITIONAL on purpose: `undefined` and `NaN` are English words in the methods
registry's own prose ("skill is undefined against a degenerate base rate"), so the gate flags
the shapes a template binding produces — a token alone in an element, or beside a number, a
unit or a separator — and leaves the sentence alone. `[object Object]` is always a leak (it is
how an un-flattened Astro reference() renders, caught on nine pages on 2026-10-31).
No Playwright here: these are the pure functions the gate runs before it opens a browser.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("web_preview_gate", os.path.join(HERE, "web_preview_gate.py"))
gate = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "html",
    [
        "<span>undefined</span>",
        "<b>3 of undefined</b>",
        "<span>undefined lb</span>",
        "<i>Lisa Park · undefined</i>",
        "<td>NaN</td>",
        "<p>Weight: null</p>",
        "<span>undefined undefined</span>",
    ],
)
def test_a_value_position_leak_is_flagged(html):
    assert gate._leaked_values(html), html


@pytest.mark.parametrize(
    "html",
    [
        "<p>None when fewer than 2 pairs or every outcome is identical (skill is undefined against a degenerate base rate).</p>",
        "<p>An undefined skill (degenerate base rate) is treated as no skill.</p>",
        "<p>The null hypothesis is that nothing changes.</p>",
        "<p>A NaN-safe mean.</p>",
    ],
)
def test_the_english_word_in_prose_is_not_a_leak(html):
    assert gate._leaked_values(html) == [], html


def test_object_object_is_always_a_leak_and_inline_scripts_are_named():
    issues = gate._static_checks("<p>[object Object]</p><script>var x=1</script>", "/x/")
    assert any("leaked non-value" in i for i in issues)
    assert any("inline <script>" in i for i in issues)


def test_iso_dates_and_the_age_are_forbidden_words():
    issues = gate._static_checks("<p>since 2026-10-31</p><p>Thirty-seven, British</p>", "/x/")
    assert any("ISO date" in i for i in issues) and any("the age" in i for i in issues)
    assert gate._static_checks("<p>since 31 October 2026</p><script src=/a.js></script>", "/x/") == []
