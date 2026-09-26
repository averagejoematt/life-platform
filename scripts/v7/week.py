"""scripts/v7/week.py — the "This week" page body (#4182, plan §2a row 3; Prototype C screen III).

The page is the instalment: the latest write-up (its title verbatim, the day in words,
the word count, the weight that week from its own stat line, the opening lines as
served), the two before it with the prologue folded away, the week so far in served
numbers, his testimony (honest-empty until he answers), and what comes next. Every
number is poured by `site/assets/js/v7_week.js` from the served feeds — this module
writes only the skeleton and the honest not-yet-loaded state a no-JS reader sees.

No authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page) and none of it counts anything before day 1 (the
owner's ruling on Prototype C, 2026-09-26).
"""

from __future__ import annotations

CSS = "/assets/css/v7_week.css"
JS = "/assets/js/v7_week.js"

_PENDING = '<p class="wk-note wk-pending">Not loaded yet.</p>'


def _entry(anchor: str, heading: str, inner: str = _PENDING) -> str:
    return (
        f'    <section class="wk-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="wk-m" data-margin></div>\n'
        f'      <div class="wk-body">\n'
        f'        <h2 class="wk-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /story/."""
    return (
        "    <h1>This week</h1>\n"
        '    <p class="v7-job">The write-up of the week, with the page before and the page after.</p>\n'
        '    <p class="wk-through" id="wk-through" data-src="api_journey.journey.last_weighin_date"></p>\n'
        + _entry("wk-latest", "The latest write-up")
        + _entry("wk-previously", "Previously")
        + _entry("wk-sofar", "This week, so far")
        + _entry("wk-testimony", "His testimony")
        + _entry("wk-next", "Next")
    )
