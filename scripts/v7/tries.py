"""scripts/v7/tries.py — the "What he's trying" page body (#4182, plan §2a row 6; CONCEPT §3 row 6).

Prototype C's logbook frame: dated entries with the day in the margin. Four entries —
what he takes (the served stack, each compound as what · should move · how we'd know,
the August correction folded under the cards), what he's testing (what is running,
what is ready to start, the honest count of ideas waiting), his calls in his words
(the decisions he chose to publish, verbatim and dated) and the dated return line.
Every figure is served (`/api/supplements`, `/api/experiments`, `/api/protocols`,
`/api/decisions`, `/api/content_cadence`) and carries a `data-src`; nothing is typed here.

No authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page) and none of it counts starts (the owner's ruling on
Prototype C, 2026-09-26).
"""

from __future__ import annotations

CSS = "/assets/css/v7_tries.css"
JS = "/assets/js/v7_tries.js"

_PENDING = '<p class="tr-note tr-pending">Not loaded yet.</p>'


def _entry(anchor: str, heading: str, inner: str = _PENDING) -> str:
    return (
        f'    <section class="tr-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="tr-m" data-margin></div>\n'
        f'      <div class="tr-body">\n'
        f'        <h2 class="tr-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /protocols/."""
    return (
        "    <h1>What he’s trying</h1>\n"
        '    <p class="v7-job">What he takes and tests, what each one should move, and how we’d know.</p>\n'
        '    <p class="tr-through" id="tr-through" data-src="api_supplements.as_of_date"></p>\n'
        + _entry("tr-takes", "What he takes")
        + _entry("tr-testing", "What he’s testing")
        + _entry("tr-calls", "His calls, in his words")
        + _entry("tr-next", "Next")
    )
