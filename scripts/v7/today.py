"""scripts/v7/today.py — the "Today" page body (#4182, plan §2a row 2; CONCEPT §3 row 2).

Matthew's morning screen, open to anyone: the three questions (How's the week? · Last
night? · Today?) as three_questions.js already answers them, the session as the routine
serves it (kind and counts — the exercises and loads stay on his phone until /api/session
exists), the one ask with its lateness, what he skips in one vocabulary, a one-line note
that this is his screen, and the dated return line. Nothing after it. Every number is
poured by `site/assets/js/v7_today.js` from the served feeds — this module writes only the
skeleton and the honest not-yet-loaded state a no-JS reader sees.

No authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page) and none of it counts anything before day 1 (the
owner's ruling on Prototype C, 2026-09-26). The PWA island (boot_sw.js) lives on this
page only — plan §1b item 6.
"""

from __future__ import annotations

CSS = "/assets/css/v7_today.css"
JS = "/assets/js/v7_today.js"

_PENDING = '<p class="td-note td-pending">Not loaded yet.</p>'


def _entry(anchor: str, heading: str, inner: str = _PENDING) -> str:
    return (
        f'    <section class="td-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="td-m" data-margin></div>\n'
        f'      <div class="td-body">\n'
        f'        <h2 class="td-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /cockpit/."""
    return (
        "    <h1>Today</h1>\n"
        '    <p class="v7-job">Matthew’s morning screen, open to anyone.</p>\n'
        '    <p class="td-through" id="td-through" data-src="api_snapshot.vitals.as_of_date | api_snapshot.journey.last_weighin_date | api_nutrition_overview.nutrition.latest_date"></p>\n'
        + _entry("td-week", "How’s the week?")
        + _entry("td-night", "Last night?")
        + _entry("td-today", "Today?")
        + _entry("td-ask", "The one ask")
        + _entry("td-skips", "What he skips")
        + _entry(
            "td-return",
            "This page",
            '<p class="td-note">This is Matthew’s morning screen — you’re welcome to look.</p>\n'
            '        <p class="td-note td-pending" id="td-return-line">Not loaded yet.</p>',
        )
        + '    <script src="/assets/js/boot_sw.js"></script>\n'
    )
