"""scripts/v7/today.py — the "Today" page body (#4182, plan §2a row 2; CONCEPT §3 row 2).

Matthew's morning screen, open to anyone: the three questions (How's the week? · Last
night? · Today?) as three_questions.js already answers them, the session as the routine
serves it (kind and counts — the exercises and loads stay on his phone until /api/session
exists), the one ask with its lateness, what he skips in one vocabulary, a one-line note
that this is his screen, and the dated return line. Nothing after it. Every number is
poured by `site/assets/js/v7_today.js` from the served feeds — this module writes only the
skeleton and the honest not-yet-loaded state a no-JS reader sees.

WHAT THE STATIC SHELL SAYS (R6 red team, fix 1 — the class the coaches page failed): one
<noscript> line, and in each entry a pending line that names WHAT THE ENTRY HOLDS, never an
absence sentence — a static "No open ask this morning." would ASSERT on JS-off or a 404.
The JS writes each entry's honest state from the served fact: the fact, its absence, or
"not served right now" on a null fetch (ADR-104).

The `<!-- cockpit-proof:start/end -->` pair is the cut-over anchor for
`scripts/v4_build_cockpit_proof.py` (plan §2.12 item 2): empty in the preview, filled with
the <noscript> proof bake when this template is poured at `/cockpit/`.

No authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page) and none of it counts anything before day 1 (the
owner's ruling on Prototype C, 2026-09-26). The PWA island (boot_sw.js) lives on this
page only — plan §1b item 6.
"""

from __future__ import annotations

CSS = "/assets/css/v7_today.css"
JS = "/assets/js/v7_today.js"


def _pending(holds: str) -> str:
    """The JS-off / not-yet-poured line: what the entry holds, asserting nothing."""
    return f'<p class="td-note td-pending">This entry holds {holds}.</p>'


def _entry(anchor: str, heading: str, inner: str) -> str:
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
        # The cut-over anchor (ADR-157, plan §3c): empty in the preview, filled with the
        # <noscript> proof bake by scripts/v4_build_cockpit_proof.py when poured at /cockpit/.
        "    <!-- cockpit-proof:start -->\n"
        "    <!-- cockpit-proof:end -->\n"
        "    <!-- cockpit-proof:start -->\n"
        "    <!-- cockpit-proof:end -->\n"
        '    <noscript><p class="td-note">Every line on this page is poured from the site’s served data when scripts run. With scripts off, each entry names what it holds, not the numbers.</p></noscript>\n'
        + _entry("td-week", "How’s the week?", _pending("the latest weigh-in and the weekly rate"))
        + _entry("td-night", "Last night?", _pending("last night’s sleep and recovery"))
        + _entry("td-today", "Today?", _pending("today’s session and the latest day of the food log"))
        + _entry("td-ask", "The one ask", _pending("the one open ask from a coach, with how late it is"))
        + _entry("td-skips", "What he skips", _pending("what went unlogged, counted in days"))
        + _entry(
            "td-return",
            "This page",
            '<p class="td-note">This is Matthew’s morning screen — you’re welcome to look.</p>\n'
            '        <p class="td-note td-pending" id="td-return-line">This entry holds the day of the next weigh-in.</p>',
        )
        + '    <script src="/assets/js/boot_sw.js"></script>\n'
    )
