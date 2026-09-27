"""scripts/v7/hood.py — the "Under the hood" page body (#4182, plan §2a row 8; CONCEPT §3 row 8, §6).

The page is the receipts a sceptic checks: how a number is made, in one paragraph (Home's
own four "How it works" sentences, poured from the same served fields, plus the repo link
and the cost line); the corrections column — every call the code graded refuted, as three
sentences each, *what we said · what happened · what we changed*, the served record folded
under a <details>; the build log's last ten titles with their days; the gear — the
registry-derived device list (`source_registry.catalog_entries()`, the same list
`scripts/v4_build_gear.py` pours) with what each feeds and, from /api/source_freshness at
runtime, when it last reported — under the affiliate disclosure the live gear page carries
verbatim; and the dated return line.

WHAT IS STATIC. The headings, the entry order, the gear rows' names and what they feed
(registry facts, poured at build time — the coverage rule is the registry's own), the
disclosure, and one "loading" line per served slot. Every number, date and served sentence
is poured by `site/assets/js/v7_hood.js` — the static shell carries no served number, so it
can never go stale, and reads plainly with scripts off.

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
from v4_build_gear import DISCLOSURE  # noqa: E402 — the live gear page's FTC disclosure, verbatim

CSS = "/assets/css/v7_hood.css"
JS = "/assets/js/v7_hood.js"

REPO_URL = "https://github.com/averagejoematt/life-platform"

_PENDING = '<p class="hd-note hd-pending">Loading the numbers — this line fills from the site’s served data.</p>'


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


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


def body(base: str) -> str:  # noqa: ARG001 — every page body takes the base; this one links nothing under it
    """The inner HTML of `<main>` for /method/."""
    gear = (
        '<p class="hd-disclosure" id="hd-disclosure" role="note" aria-label="Affiliate disclosure">'
        f"{DISCLOSURE}</p>\n"
        '        <table class="hd-gear" data-src="source_registry.catalog_entries()">\n'
        '          <thead><tr><th scope="col">Device or app</th><th scope="col">What it feeds</th><th scope="col">Last reported</th></tr></thead>\n'
        "          <tbody>\n"
        f"{gear_rows()}"
        "          </tbody>\n"
        "        </table>\n"
        '        <p class="hd-note">The list is read from the site’s own source registry at build time — if it isn’t in the pipeline, it isn’t here.</p>'
    )
    parts = [
        "    <h1>Under the hood</h1>\n",
        '    <p class="v7-job">How a number is made, and the corrections column.</p>\n',
        _entry("hd-how", "How a number is made", f'<div id="hd-how-body">{_PENDING}</div>', "§"),
        _entry("hd-corrections", "The corrections column", f'<div id="hd-corrections-body">{_PENDING}</div>'),
        _entry("hd-log", "The build log", f'<div id="hd-log-body">{_PENDING}</div>'),
        _entry("hd-gear", "The gear", gear, "§"),
        _entry("hd-return", "Next", f'<div id="hd-return-body">{_PENDING}</div>', "→"),
    ]
    return "".join(parts)
