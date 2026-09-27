"""scripts/v7/hood.py — the "Under the hood" page body (#4182, plan §2a row 8; CONCEPT §3 row 8, §6).

The page is the receipts a sceptic checks: how a number is made, in one paragraph (Home's
own four "How it works" sentences, poured from the same served fields, plus the repo link
and the cost line); the corrections column — every call the code graded refuted, as three
sentences each, *what we said · what happened · what we changed*, the served record folded
under a <details>; the build log's last ten titles with their days; the gear — the
registry-derived device list (`source_registry.catalog_entries()`, the same list
`scripts/v4_build_gear.py` pours) with what each feeds and, from /api/source_freshness at
runtime, when it last reported — names only, none of them linked, so the live gear page's
FTC disclosure is NOT carried (it would describe links this page does not have); and the
dated return line.

WHAT IS STATIC. The headings, the entry order, the gear rows' names and what they feed
(registry facts, poured at build time — the coverage rule is the registry's own; the
table folds under a plain-words key so the page holds ~5 screens at 390, R6 class 6), the
engine's-score explainer (the one collapsed paragraph that absorbs
`/method/character/`, plan risk 8 — keyed in plain words, no live number in it), one
"loading" line per served slot and one <noscript> line. Every number, date and served
sentence is poured by `site/assets/js/v7_hood.js` — the static shell carries no served
number and asserts no fact, so it can never go stale and says nothing false with scripts
off (R6 class 9). The JS splits empty from unreachable (R6 class 1): a failed fetch
prints "<what> is not served right now.", a served-empty list prints the fact sentence.
The page's one "Data through <day>" line (/api/vitals) sits in the return entry.

No authored copy here uses a ruled glossary term as its own word (the registry names
the gear rows carry — Whoop, Hevy, HRV — are keep-with-gloss terms the build-time gloss
pass wraps in <dfn>), and none of it counts anything before day 1 or names an earlier
start (the owner's ruling on Prototype C, 2026-09-26): the corrections column says
"since <the served start date>" and "early in the experiment", never a count of starts.
"""

from __future__ import annotations

import html
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if os.path.join(_ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from ingestion.source_registry import catalog_entries  # noqa: E402 — the authoritative device list

CSS = "/assets/css/v7_hood.css"
JS = "/assets/js/v7_hood.js"

REPO_URL = "https://github.com/averagejoematt/life-platform"

_PENDING = '<p class="hd-note hd-pending">Loading the numbers — this line fills from the site’s served data.</p>'


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


_WORDS = ("No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def _count_word(n: int) -> str:
    """A small count in words, numerals past ten — entry_age.countWord's rule, for a build-time figure."""
    return _WORDS[n] if 0 <= n <= 10 else f"{n:,}"


def _entry(anchor: str, heading: str, inner: str, margin: str = "") -> str:
    """One logbook entry: the dated margin (filled at runtime unless a glyph is given) and the body."""
    m = f'<span class="d">{_esc(margin)}</span>' if margin else ""
    return (
        f'    <section class="hd-entry" id="{anchor}" aria-labelledby="{anchor}-h">\n'
        f'      <div class="hd-m" data-margin>{m}</div>\n'
        f'      <div class="hd-body">\n'
        f'        <h2 class="hd-h" id="{anchor}-h">{heading}</h2>\n'
        f"        {inner}\n"
        f"      </div>\n"
        f"    </section>\n"
    )


def gear_rows() -> str:
    """The registry's catalogue as table rows — name · what it feeds · last seen (runtime).

    Derived from `catalog_entries()` at build time, the same call the live gear page makes,
    so a source that joins the registry joins this page on the next build. The last-seen
    cell is poured from /api/source_freshness by id (the `data-source` attribute — never
    printed) and says so plainly until it loads.
    """
    rows = []
    for e in catalog_entries():
        rows.append(
            f'          <tr data-source="{_esc(e["id"])}">'
            f'<td class="hd-gear-name">{_esc(e["name"])}</td>'
            f'<td class="hd-gear-feeds">{_esc(e["metrics"])}</td>'
            f'<td class="hd-gear-seen" data-src="api_source_freshness.sources[].last_update">not loaded yet</td>'
            f"</tr>\n"
        )
    return "".join(rows)


# `/method/character/`'s explainer, absorbed as one collapsed paragraph in plain words (plan
# risk 8; CONCEPT §14). Static by design: the live number is never here, so it cannot drift.
# "Areas", not the ruled word; the tier names and the day counts are the engine's own rules.
CHARACTER_FOLD = (
    '<details class="hd-fold hd-explainer" id="hd-score">'
    "<summary>The engine’s one score, explained</summary>"
    '<p class="hd-prose hd-explainer-p">Besides the figures above, the engine keeps one score that tries to answer '
    "“is the whole life moving, or just one corner of it?” Each day it scores seven areas of his life — sleep, "
    "movement, eating, metabolic health, mind, relationships and consistency — from their own real data, weighs "
    "them, and rolls them into one level from 1 to 100. The hundred levels sit in five bands of twenty: "
    "Foundation, Momentum, Discipline, Mastery, Elite. A level moves only after a sustained shift — roughly five "
    "or more days of real improvement to go up, seven or more of decline to go down — so one great or terrible day "
    "cannot swing it, and a rise is earned. It cuts both ways: when the logging goes quiet, what is not happening "
    "scores zero and the levels fall. It is a motivational lens on real data, not a medical score. The live number "
    "is on the numbers page, never written here.</p>"
    "</details>"
)


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /method/."""
    entries = catalog_entries()
    gear = (
        '<p class="hd-small" id="hd-gear-lead">'
        f'<span data-src="source_registry.catalog_entries()">{_count_word(len(entries))}</span> devices and apps are on this list. '
        '<span id="hd-gear-cover" data-src="api_source_freshness.summary.total"></span></p>\n'
        '        <details class="hd-fold hd-gear-fold" id="hd-gear-list"><summary>The list, and when each last reported</summary>\n'
        '        <table class="hd-gear" data-src="source_registry.catalog_entries()">\n'
        '          <thead><tr><th scope="col">Device or app</th><th scope="col">What it feeds</th><th scope="col">Last reported</th></tr></thead>\n'
        "          <tbody>\n"
        f"{gear_rows()}"
        "          </tbody>\n"
        "        </table>\n"
        "        </details>\n"
        '        <p class="hd-note">The list is read from the site’s own list of sources when the page is built — if a device or app does not feed the site, it is not here.</p>'
    )
    parts = [
        "    <h1>Under the hood</h1>\n",
        '    <p class="v7-job">How a number is made, and the corrections column.</p>\n',
        '    <noscript><p class="hd-note">Every number on this page is drawn from the site’s served data when scripts run. With scripts off the entries below name what each one holds, not the numbers.</p></noscript>\n',
        _entry("hd-how", "How a number is made", f'<div id="hd-how-body">{_PENDING}</div>\n        {CHARACTER_FOLD}', "§"),
        _entry("hd-corrections", "The corrections column", f'<div id="hd-corrections-body">{_PENDING}</div>'),
        _entry("hd-log", "The build log", f'<div id="hd-log-body">{_PENDING}</div>'),
        _entry("hd-gear", "The gear", gear, "§"),
        _entry(
            "hd-return",
            "Next",
            f'<div id="hd-return-body">{_PENDING}</div>\n        <p class="hd-note hd-through" id="hd-through" data-src="api_vitals.vitals.as_of_date"></p>',
            "→",
        ),
    ]
    return "".join(parts)
