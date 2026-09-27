"""scripts/v7/numbers.py — the "His numbers" page body (#4182, plan §2a row 4; Prototype C screen IV).

One scroll in C's logbook frame: weight · sleep · eating · training · blood tests, each
ONE chart drawn to scale from the served series plus ONE sentence with its day and n;
then the absence strip (what is not being recorded, stated as absence); then the
engine's own score folded under a `<details>` with a plain key. "CSV" under every chart
is a client-side download of the JSON the page already fetched; "see all N" expands
the full series in place. Every number is poured by `site/assets/js/v7_numbers.js`
from the served feeds — this module writes only the skeleton and the honest
not-yet-loaded state a no-JS reader sees, so the static shell carries no number that
could go stale.

No authored copy here uses a ruled glossary term (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any page) and none of it counts starts, resets or attempts
(the owner's ruling on Prototype C, 2026-09-26): the page says "since <day>" and "so far".
"""

from __future__ import annotations

CSS = "/assets/css/v7_numbers.css"
JS = "/assets/js/v7_numbers.js"

_PENDING = '<p class="nm-note nm-pending">Not loaded yet.</p>'

# (anchor, heading) in the design order. The margin column takes the section's own
# latest served day at runtime; the body takes the chart, the sentence and the tools row.
SECTIONS = (
    ("nm-weight", "Weight"),
    ("nm-sleep", "Sleep"),
    ("nm-eating", "Eating"),
    ("nm-training", "Training"),
    ("nm-labs", "Blood tests"),
    ("nm-absent", "Not being recorded"),
)


def _entry(anchor: str, heading: str, inner: str = _PENDING) -> str:
    return (
        f'    <section class="nm-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="nm-m" data-margin></div>\n'
        f'      <div class="nm-body">\n'
        f'        <h2 class="nm-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /data/."""
    return (
        "    <h1>His numbers</h1>\n"
        '    <p class="v7-job">The evidence: weight, sleep, eating, training, blood tests — one chart and one sentence each.</p>\n'
        '    <p class="nm-through" id="nm-through" data-src="api_journey.journey.last_weighin_date"></p>\n'
        + "".join(_entry(a, h) for a, h in SECTIONS)
        + '    <details class="nm-engine" id="nm-engine">\n'
        "      <summary>The engine’s score</summary>\n"
        '      <div class="nm-engine-body" id="nm-engine-body">\n'
        "        " + _PENDING + "\n"
        "      </div>\n"
        "    </details>\n"
    )
