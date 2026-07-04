"""#413 — 'where would you land': the reader participates, the site learns nothing.

Source-level pins (the interactive zero-write proof ran in the local Playwright
harness pre-merge: sleep/rhr/weight all placed, and the interaction produced
zero non-GET requests).
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html")).read()
STORY_JS = open(os.path.join(_REPO, "site/assets/js/story.js")).read()

_MIRROR = STORY_JS[STORY_JS.find("async function wireMirror") :]


def test_widget_is_purely_client_side():
    """The submit handler preventDefaults and contains no network or storage
    call — the reader's number cannot leave the page by construction."""
    handler = _MIRROR[_MIRROR.find('form.addEventListener("submit"') :]
    assert "e.preventDefault()" in handler
    for leak in ("fetch(", "sendBeacon", "localStorage", "sessionStorage", "XMLHttpRequest", "document.cookie", "getJSON("):
        assert leak not in handler, f"reader-input path must not call {leak}"


def test_reads_only_matthews_public_numbers():
    """The only fetches happen at render, against already-public endpoints."""
    reads = re.findall(r'getJSON\("([^"]+)"', _MIRROR)
    assert set(reads) == {"/public_stats.json", "/api/observatory_week?domain=sleep"}


def test_framing_is_n1_and_advice_free():
    assert "Nothing you type leaves this page" in HOME
    assert "N=1" in HOME[HOME.find("beat-mirror") :][:900]
    assert "not a benchmark or health advice" in HOME
    assert "your number was not sent or saved" in _MIRROR
    assert "single-subject comparison (n=1)" in _MIRROR
    # No prescriptive verbs in the rendered reads.
    for advice in ("you should", "aim for", "try to", "improve your"):
        assert advice not in _MIRROR.lower()


def test_honest_states():
    # No public numbers → the beat stays hidden, never seeded.
    assert "the beat stays honestly hidden" in _MIRROR
    # Implausible input is rejected, not placed.
    assert "plausible" in _MIRROR
