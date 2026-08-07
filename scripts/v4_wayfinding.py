"""The wayfinding layer — the causal loop made navigable from EVERY page (#1475).

`v4_kit.loop_ribbon` puts the loop in the `.page-hero` of the pages that have one (81 of
89 today). `v4_chrome.loop_forward` closes every page with the ONE next station. This
module is the third piece the two of those left open: a persistent **footer wayfinder**
that ships inside the canonical `.site-foot` — so it is on every chrome-bearing page by
construction, including the eight (home, 404, privacy, subscribe, confirm, the coaches
index, the agents page, the essay permalinks) that carry no page-hero ribbon at all.

`tokens.css` has always described the ribbon as living "in the page-hero **and the
footer** so the through-line is on every page"; DESIGN_SYSTEM_V5 §3 says the same of the
loop diagram ("the footer can carry a compact version"). The footer half was never built,
so the bottom of every page was a ~30-link directory with no opinion about where the
reader was — exactly the "generic link dump" this issue names.

What the wayfinder is
---------------------
One compact row of the five loop stations — ``Now · Data → Coaching → Protocols →
Story ↻`` — rendered as cards carrying each station's loop role, with three states the
reader can act on without reading a word of chrome:

  * **here**  — the station this page belongs to, ember, `aria-current="page"`, not a
    link (you're already there — the same grammar as `.lr-here`);
  * **next**  — the station the loop advances to, tagged `next`. This is the SAME
    forward step `v4_chrome.NEXT_STATION` proposes in the `.loop-forward` close, so the
    map and the close never disagree (the map shows the whole cycle; the close makes the
    argument for the one step);
  * **from**  — the station the loop arrived from, lifted out of the faint tier so the
    reader can walk the loop backwards too.

On a page with no door (home, `/gear/`, the utility pages) nothing is "here"; the
cockpit is tagged **start here**, matching `v4_chrome.DEFAULT_NEXT`. The ribbon still
orients — "this is the loop, click to enter".

Why the cockpit is a stop but not a menu column
-----------------------------------------------
The cockpit is the loop's *vantage*, not one of its four causal stages — it is today's
slice of the whole loop, and it has no sub-pages, so there is nothing to put in a footer
column for it. `v4_kit.loop_ribbon` already draws exactly this shape (``Now`` set apart
by a `·` from the four stages), and the footer mega-menu keeps its four stage columns.
The wayfinder is therefore the FIRST footer link to the cockpit the site has ever had.

The station keys are the `v4_chrome.DOORS` hrefs, so a Method/registry/game page — which
nav-highlights `/data/` because it is a deeper cut of the Data door, not a sixth door —
lands on the Data station here too, exactly as it inherits Data's next station in
`loop_forward`. One signal, three surfaces.

The interaction (CSS only, no JS)
---------------------------------
Each stop carries `data-station`; each loop-stage menu column below carries the same
`data-station`. `tokens.css` §11 uses `:has()` to light a column's ember rail while its
stop is hovered or keyboard-focused — the spine and the menu are the same object, and
touching a station shows you what it owns. It degrades to nothing in a browser without
`:has()`, needs no script, and cannot hide a link from a crawler or a reader with JS off.
"""

from __future__ import annotations

import html

# The loop, in order, as a CYCLE: cockpit → data → coaching → protocols → story →
# cockpit. `next`/`from` are computed off this list, which is why it must stay in the
# same order as `v4_chrome.NEXT_STATION` (asserted by tests/test_wayfinding.py).
#   (key, href, name, role)
# `role` is the station's loop role from docs/SITE_MAP_AND_INTENT.md, compressed to the
# few words that fit a footer card — the ribbon is a map, not a paragraph.
STATIONS = [
    ("cockpit", "/cockpit/", "Now", "today's slice"),
    ("data", "/data/", "Data", "the engine"),
    ("coaching", "/coaching/", "Coaching", "AI reads the data"),
    ("protocols", "/protocols/", "Protocols", "the levers"),
    ("story", "/story/", "Story", "narrates the loop"),
]

# Door href (what the doors nav marks `aria-current`) → station key. Identical set by
# construction: `tests/test_wayfinding.py` pins it against `v4_chrome.DOORS`.
STATION_BY_DOOR = {href: key for key, href, _, _ in STATIONS}

# The four causal stages own a footer menu column; the vantage does not (see the module
# docstring). Used by `v4_chrome.site_footer` to key the columns and by the tests.
COLUMN_STATIONS = ("data", "coaching", "protocols", "story")


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _neighbours(current_key: str | None) -> tuple[str | None, str | None]:
    """(from_key, next_key) around `current_key` on the cycle.

    With no current station there is no "from"; the cockpit is the proposed entry point
    (`v4_chrome.DEFAULT_NEXT`), so it gets the forward tag and the ribbon reads as an
    invitation rather than a position.
    """
    keys = [key for key, _, _, _ in STATIONS]
    if current_key not in keys:
        return None, keys[0]
    i = keys.index(current_key)
    return keys[i - 1], keys[(i + 1) % len(keys)]


def _stop(key: str, href: str, name: str, role: str, current_key: str | None, from_key: str | None, next_key: str | None) -> str:
    # The state class comes FIRST and the vantage modifier last, so `wf-stop is-here`
    # is a stable literal the guards (and a grep) can anchor on.
    classes = ["wf-stop"]
    tag = ""
    if key == current_key:
        classes.append("is-here")
    elif key == next_key:
        classes.append("is-next")
        tag = '<span class="wf-tag">next</span>' if current_key else '<span class="wf-tag">start here</span>'
    elif key == from_key:
        classes.append("is-from")
        tag = '<span class="wf-tag">from</span>'
    if key == STATIONS[0][0]:
        classes.append("is-vantage")
    inner = f'<span class="wf-name">{_esc(name)}</span><span class="wf-role">{_esc(role)}</span>{tag}'
    cls = " ".join(classes)
    if key == current_key:
        # The station you're on is not a link — same grammar as `.loop-ribbon .lr-here`.
        # Its hub stays one click away in the mega-menu column directly below.
        return f'<span class="{cls}" data-station="{key}" aria-current="page">{inner}</span>'
    return f'<a class="{cls}" data-station="{key}" href="{href}">{inner}</a>'


def wayfinder(current_door: str | None = None) -> str:
    """The footer wayfinder for a page whose doors nav marks `current_door`.

    `current_door` is the door HREF (`"/data/"`, `"/story/"`, …) — the same value passed
    to `v4_chrome.doors_nav()` and `v4_chrome.loop_forward()`, so all three chrome
    surfaces agree about where the reader is. `None` (home, `/gear/`, the utility pages)
    renders the unmarked, inviting form.
    """
    current_key = STATION_BY_DOOR.get(current_door) if current_door else None
    from_key, next_key = _neighbours(current_key)
    lede = "you are here on the loop" if current_key else "the loop"
    parts = [
        '<nav class="wayfinder" aria-label="The loop">',
        f'<p class="wf-lede label">{lede}</p>',
        '<div class="wf-ribbon">',
    ]
    for i, (key, href, name, role) in enumerate(STATIONS):
        if i == 1:
            # The vantage is set apart from the four causal stages by a faint separator,
            # not an arrow — it is today's slice of the whole loop, not a step in it.
            parts.append('<span class="wf-sep" aria-hidden="true">&middot;</span>')
        elif i:
            parts.append('<span class="wf-arrow" aria-hidden="true">&rarr;</span>')
        parts.append(_stop(key, href, name, role, current_key, from_key, next_key))
    parts.append('<span class="wf-arrow wf-cycle" aria-hidden="true">&#8635;</span>')
    parts.append("</div></nav>")
    return "".join(parts)


def menu_column(heading: str, links_html: str, station: str | None = None, is_here: bool = False) -> str:
    """One mega-menu column, keyed to its loop station.

    `station` is the station key the column belongs to (`None` for the two meta columns —
    The Technology and Follow &amp; context — which sit outside the loop). `is_here` marks
    the column the reader is currently inside, which is the ONLY place ember appears in
    the mega-menu: before this every column heading was ember, so the accent carried no
    information at all. Ember now means "you are here", nothing else.
    """
    classes = "sf-col"
    if is_here:
        classes += " is-here"
    attr = f' data-station="{station}"' if station else ""
    return f'<div class="{classes}"{attr}><p class="sf-h label">{heading}</p>{links_html}</div>'
