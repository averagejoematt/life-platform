"""#2672 — a cockpit scope switch must be a navigation, not a silent mutation.

Switching Week / Month / Journey on `/cockpit/` mutated the view without pushing a
history entry. Two reader-facing consequences, both reproduced in-browser:

  1. Back ejected the reader off the cockpit entirely instead of returning to the
     previous scope.
  2. No scope but the default was linkable — every share of a Month view landed the
     recipient on Today.

The fix splits "apply the scope" from "record the navigation": `applyScope` does the
view work and the caller owns history, so the click path, a deep link and `popstate`
all run the SAME render. That matters more than it sounds — the #2673 regression a
few hours earlier was exactly a second code path that looked equivalent and was not.

These tests extract the SHIPPED source and run it under node (same pattern as
tests/test_cockpit_carry_scope_guards.py), so they exercise real code. The
end-to-end behaviour (Back actually returning, no console errors) is separately
verified in-browser against the deployed asset — a unit test cannot prove the
browser honours a pushState it never saw.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COCKPIT_JS = os.path.join(_ROOT, "site", "assets", "js", "cockpit.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _shipped(pattern: str, label: str) -> str:
    src = open(_COCKPIT_JS, encoding="utf-8").read()
    m = re.search(pattern, src, re.S | re.M)
    assert m, f"{label} not found in cockpit.js — the extraction, not the site, is broken"
    return m.group(0)


def _helpers() -> str:
    """The three pure helpers, lifted verbatim from the shipped file."""
    return "\n".join(
        (
            _shipped(r"^const SCOPES = \[.*?\];", "SCOPES"),
            _shipped(r"^function scopeFromUrl\(search = location\.search\) \{.*?^\}", "scopeFromUrl"),
            _shipped(r"^function urlForScope\(scope\) \{.*?^\}", "urlForScope"),
        )
    )


def _run(js: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.mjs")
        with open(p, "w", encoding="utf-8") as f:
            f.write("globalThis.location = { search: '' };\n" + js)
        out = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)  # nosec B603/B607
        assert out.returncode == 0, f"node failed: {out.stderr}\n{out.stdout}"
        return json.loads(out.stdout.strip().splitlines()[-1])


def test_each_scope_has_a_distinct_url_and_today_stays_bare():
    """Acceptance box 2. `today` is the bare page, not `?scope=today` — the default
    view must not have two addresses that differ only by a query string."""
    js = _helpers() + """
console.log(JSON.stringify({
  today: urlForScope("today"), week: urlForScope("week"),
  month: urlForScope("month"), journey: urlForScope("journey"),
}));
"""
    r = _run(js)
    assert r["today"] == "/cockpit/"
    assert r["week"] == "/cockpit/?scope=week"
    assert r["month"] == "/cockpit/?scope=month"
    assert r["journey"] == "/cockpit/?scope=journey"
    assert len({r["week"], r["month"], r["journey"]}) == 3, r


def test_a_scope_url_round_trips():
    """What urlForScope writes, scopeFromUrl must read back."""
    js = _helpers() + """
const out = {};
for (const s of ["week", "month", "journey"]) {
  const u = urlForScope(s);
  out[s] = scopeFromUrl(u.slice(u.indexOf("?")));
}
console.log(JSON.stringify(out));
"""
    assert _run(js) == {"week": "week", "month": "month", "journey": "journey"}


def test_an_unknown_scope_in_the_url_is_ignored_not_trusted():
    """`?scope=` is reader-supplied. An unknown value must fall back to the default
    rather than reaching applyScope and blanking the view."""
    js = _helpers() + """
console.log(JSON.stringify({
  bogus: scopeFromUrl("?scope=wat"), empty: scopeFromUrl(""),
  injected: scopeFromUrl("?scope=<script>"), none: scopeFromUrl("?date=2026-08-11"),
}));
"""
    r = _run(js)
    assert r == {"bogus": "", "empty": "", "injected": "", "none": ""}, r


def test_the_click_path_pushes_history_before_rendering():
    """Acceptance box 1. Pushing BEFORE the render means the entry exists even if a
    render throws — otherwise a failed render silently costs the reader their Back."""
    block = _shipped(r"b\.addEventListener\(\"click\", \(\) => \{.*?\n    \}\);", "scope click handler")
    assert "history.pushState" in block, f"the click path still mutates the view with no history entry: {block}"
    push_at = block.index("history.pushState")
    apply_at = block.index("applyScope(")
    assert push_at < apply_at, "pushState must precede applyScope so a throwing render cannot eat the entry"


def test_popstate_restores_scope_without_a_reload():
    """Acceptance box 3. It must call applyScope — a location assignment or reload
    would be a full page load, which is what the issue asks to avoid."""
    block = _shipped(r"window\.addEventListener\(\"popstate\".*?\n  \}\);", "popstate handler")
    assert "applyScope(" in block, block
    for reload_ish in ("location.reload", "location.href =", "location.assign", "window.location ="):
        assert reload_ish not in block, f"popstate does a full reload via {reload_ish}: {block}"


def test_popstate_falls_back_to_the_url_then_to_today():
    """An entry pushed before this shipped carries no state.scope; a hand-edited
    address carries no state at all. Neither may leave the view unchanged-but-wrong."""
    block = _shipped(r"window\.addEventListener\(\"popstate\".*?\n  \}\);", "popstate handler")
    assert "scopeFromUrl()" in block and '"today"' in block, block


def test_a_deep_link_boots_into_its_scope_and_seeds_history():
    """Acceptance box 2's other half — and the seeded entry is what gives the first
    Back somewhere to return to."""
    src = open(_COCKPIT_JS, encoding="utf-8").read()
    boot = _shipped(r"const _deepScope = scopeFromUrl\(\);.*?\n\}", "deep-link boot")
    assert "history.replaceState" in boot, boot
    assert "applyScope(_deepScope)" in boot, boot
    # ?date= must keep precedence — time travel is its own scope.
    assert "!_deepDate" in boot, f"a ?scope= link would override a ?date= deep link: {boot}"
    assert src.count("const _deepScope") == 1


def test_apply_scope_is_the_single_render_path():
    """The #2673 lesson, applied preventively: click / deep link / popstate must all
    go through ONE function, so there is no second path that looks equivalent."""
    src = open(_COCKPIT_JS, encoding="utf-8").read()
    assert src.count("function applyScope(") == 1
    # The old inline body must be gone from the click handler.
    click = _shipped(r"b\.addEventListener\(\"click\", \(\) => \{.*?\n    \}\);", "scope click handler")
    for moved in ("renderJourney()", "renderWeek()", "renderMonth()"):
        assert moved not in click, f"the click handler still renders inline ({moved}) — two paths again"
