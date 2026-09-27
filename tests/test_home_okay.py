"""#789 → ADR-157 — "Is he okay this week?" is an entry of the v7 Home log.

The friends' question was buried ~2,250 px down the v4 Home (#4182 B1 audit); the
2026-09-26 panel put it under the claim, and the v7 cut-over (ADR-157) keeps it as the
fourth dated entry of the log, after the fold, every weigh-in and his own words, before
"Also on the record". Source-level pins on the committed shell (scripts/v7/home.py) and the
renderer (site/assets/js/v7_home.js):

  1. the entry is present, headed in the reader's words, in the log's order;
  2. it is written by ONE renderer (`okayBlock`) from served fields the page already
     fetches — no new fetch, no AI call, every figure with its `data-src`;
  3. absence reads as absence ("is not served", "No food log is served"), never a filler;
  4. the body links no page but the repo (the reach rule) and speaks in the third person.
"""

import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = open(os.path.join(_REPO, "site/index.html"), encoding="utf-8").read()
HOME_JS = open(os.path.join(_REPO, "site/assets/js/v7_home.js"), encoding="utf-8").read()
HOME_CSS = open(os.path.join(_REPO, "site/assets/css/v7_home.css"), encoding="utf-8").read()

MAIN = HOME[HOME.index('<main id="main"') : HOME.index("</main>")]
ORDER = ["v7h-fold", "v7h-weighins", "v7h-words", "v7h-okay", "v7h-record", "v7h-how", "v7h-next", "v7h-follow"]


def _okay_fn() -> str:
    start = HOME_JS.index("export function okayBlock(")
    end = HOME_JS.index("\n// ──", start)
    return HOME_JS[start:end]


def test_okay_entry_present_and_in_the_logs_order():
    assert 'id="v7h-okay"' in MAIN
    assert "<h2>Is he okay this week?</h2>" in MAIN
    idx = [MAIN.index(f'id="{s}"') for s in ORDER]
    assert idx == sorted(idx), "the log's entries are out of order"
    assert MAIN.index('id="v7h-fold"') < MAIN.index('id="v7h-okay"') < MAIN.index('id="v7h-record"')


def test_okay_is_rendered_from_served_fields_no_new_fetch_or_ai():
    body = _okay_fn()
    assert 'put("v7h-okay-body", okayBlock(' in HOME_JS, "okayBlock is not wired to its slot"
    assert "fetch(" not in body and "getJSON(" not in body, "the block must render from the page's own fetches"
    for src in (
        "sleep_detail.total_sleep_hours",
        "vitals.recovery_pct",
        "nutrition_overview.nutrition.days_logged",
        "training_overview.training.strength_sessions_30d",
    ):
        assert src in body, f"a served figure lost its data-src: {src}"


def test_absent_data_reads_honestly_absent():
    body = _okay_fn()
    assert "is not served." in body and "No food log is served." in body
    assert "coming soon" not in body.lower()


def test_no_page_link_and_third_person():
    hrefs = re.findall(r'href="([^"]+)"', MAIN)
    assert all(
        h.startswith(("https://github.com/", "mailto:")) for h in hrefs
    ), f"a page link inside the Home body (the reach rule): {hrefs}"
    visible = re.sub(r"<[^>]+>", " ", re.sub(r"<noscript>.*?</noscript>", "", MAIN, flags=re.S))
    assert not re.search(r"\byou(r|rs)?\b", visible, re.I), "Home speaks about Matthew in the third person"


def test_styles_use_design_tokens():
    assert HOME_CSS.count("var(--") > 50
    assert "var(--font-serif)" in HOME_CSS
