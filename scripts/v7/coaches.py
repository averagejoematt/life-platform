"""scripts/v7/coaches.py — the body of "The coaches" (/coaching/), v7 page 5 (#4182, plan §2a row 5).

THE DESIGN SOURCE is Prototype C screen II (the owner's pick, R5 36/50): one coach's read at
the top, opened by its ledger lines; where two disagree, a table with the engine's number
between them; the record as "K of N so far", never a bare percentage; the roster one tap
down. Every figure is poured by `site/assets/js/v7_coaches.js` from the served endpoints
(`/api/coaching-dashboard`, `/api/coach/<id>`, `/api/coach_docket`, `/api/calibration`,
`/api/sleep_detail`, `/api/source_freshness`, `/api/coaches`) and carries `data-src`.

WHAT THE STATIC SHELL SAYS. Only the frame and, in each block, "Loading the numbers…" plus
one <noscript> line — never an absence sentence, because a static "No checked call yet."
would ASSERT on JS-off or a 404 (R6 red team, fix 1). The JS writes each block's honest
state from the served fact: the fact, its absence ("No checked call yet."), or "not served
right now" on a null fetch (ADR-104). No ruled glossary term appears in this text (tests/test_site_vocabulary_registry.py
sweeps site/next/** like any reader page) and no "cycle"/"reset"/"attempt" word (owner
ruling 2026-09-26: the public frame is the experiment and the day).

Type: Prototype C set Newsreader / IBM Plex Sans / IBM Plex Mono. The site self-hosts
Fraunces (serif), Instrument Sans (interface) and IBM Plex Mono (`tokens.css`), so the
substitution is Newsreader → Fraunces and Plex Sans → Instrument Sans; the mono is exact.
"""

from __future__ import annotations

# Both are root-absolute and v7_-prefixed (plan D4): deploy/hash_site_assets.py rewrites them.
CSS = "/assets/css/v7_coaches.css"
JS = "/assets/js/v7_coaches.js"


def body(base: str) -> str:  # noqa: ARG001 — the base is the builder's; this body links nothing under it
    return (
        "    <h1>The coaches</h1>\n"
        '    <p class="v7-job">The witnesses, on the record.</p>\n'
        '    <p class="v7c-intro">Eight AI characters — software, not people — read his numbers each morning. '
        "Every dated claim they make is checked later by code, and the misses stay on the record. "
        '<span id="v7c-through" data-src="api_calibration.as_of"></span></p>\n'
        '    <noscript><p class="v7c-absent">This page pours its numbers with JavaScript; with it off, nothing here is a claim.</p></noscript>\n'
        # ── (1) today's read: one coach, opened by the ledger line ──
        '    <section class="v7c-entry" id="v7c-read" aria-labelledby="v7c-read-h">\n'
        '      <div class="v7c-m" id="v7c-read-m" aria-hidden="true"></div>\n'
        '      <div class="v7c-body">\n'
        '        <h2 id="v7c-read-h" class="v7c-h">Today’s read</h2>\n'
        '        <div id="v7c-read-body">\n'
        '          <p class="v7c-absent">Loading the numbers…</p>\n'
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        # ── (2) where two disagree: the docket as a table ──
        '    <section class="v7c-entry" id="v7c-docket" aria-labelledby="v7c-docket-h">\n'
        '      <div class="v7c-m" id="v7c-docket-m" aria-hidden="true"></div>\n'
        '      <div class="v7c-body">\n'
        '        <h2 id="v7c-docket-h" class="v7c-h">Where two of them disagree</h2>\n'
        '        <div id="v7c-docket-body">\n'
        '          <p class="v7c-absent">Loading the numbers…</p>\n'
        "        </div>\n"
        "      </div>\n"
        "    </section>\n"
        # ── (3) the record: K of N, never a bare percentage ──
        '    <section class="v7c-entry" id="v7c-record" aria-labelledby="v7c-record-h">\n'
        '      <div class="v7c-m" id="v7c-record-m" aria-hidden="true"></div>\n'
        '      <div class="v7c-body">\n'
        '        <h2 id="v7c-record-h" class="v7c-h">The record</h2>\n'
        '        <div id="v7c-record-body">\n'
        '          <p class="v7c-absent">Loading the numbers…</p>\n'
        "        </div>\n"
        '        <p class="v7c-note">Per-coach hit rates are not printed here yet: three scorekeepers disagree on the same day. '
        "What is printed above is each checked call, one by one, from the coach’s own ledger — a list a reader can count, "
        "not a rate the site cannot yet stand behind.</p>\n"
        '        <details class="v7c-details" id="v7c-roster">\n'
        '          <summary id="v7c-roster-sum">The staff</summary>\n'
        '          <div id="v7c-roster-body"><p class="v7c-absent">Loading the numbers…</p></div>\n'
        "        </details>\n"
        "      </div>\n"
        "    </section>\n"
    )
