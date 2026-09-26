"""Shared v5 page-kit helpers for the site builders (#578).

One source of truth for the `.loop-ribbon` — the platform's causal-loop spine made
literal and clickable — so it can't drift across the evidence / coaching / dispatches
builders (and the hand-authored Home + Cockpit shells reuse the same markup).

The ribbon: Today · The numbers → The coaches → What he tries → The story, cycling back
(labels since #4182). `Today` (the live
cockpit vantage) leads, set apart by a faint separator from the four causal-loop
stages; the current door is marked ember (.lr-here). On pages that are neither the
vantage nor a stage (Home, the footer-tier Method) nothing is marked — the ribbon
still orients ("here's the loop, click to enter").

`current_door` is the door key: "cockpit" | "data" | "coaching" | "protocols" |
"story" — anything else (e.g. "home", "method") marks nothing.
"""

from __future__ import annotations

# #4182: the ribbon names the doors in the nav's own words (the owner's 2026-09-26 pick),
# so the page-hero spine, the doors nav and the footer wayfinder say one thing.
LOOP_VANTAGE = ("/cockpit/", "Today", "cockpit")
LOOP_NODES = [
    ("/data/", "The numbers", "data"),
    ("/coaching/", "The coaches", "coaching"),
    ("/protocols/", "What he tries", "protocols"),
    ("/story/", "The story", "story"),
]


def _lr_node(href: str, label: str, key: str, current_door: str) -> str:
    if key == current_door:
        return f'<span class="lr-here" aria-current="page">{label}</span>'
    return f'<a href="{href}">{label}</a>'


def loop_ribbon(current_door: str) -> str:
    parts = ['<nav class="loop-ribbon" aria-label="Where this sits in the loop">']
    parts.append(_lr_node(*LOOP_VANTAGE, current_door))
    parts.append('<span class="lr-sep" aria-hidden="true">&middot;</span>')
    for i, (href, label, key) in enumerate(LOOP_NODES):
        if i:
            parts.append('<span class="lr-arrow" aria-hidden="true">&rarr;</span>')
        parts.append(_lr_node(href, label, key, current_door))
    parts.append('<span class="lr-arrow" aria-hidden="true">&#8635;</span>')
    parts.append("</nav>")
    return "".join(parts)
