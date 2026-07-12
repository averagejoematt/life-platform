"""Shared v5 page-kit helpers for the site builders (#578).

One source of truth for the `.loop-ribbon` — the platform's causal-loop spine made
literal and clickable — so it can't drift across the evidence / coaching / dispatches
builders (and the hand-authored Home + Cockpit shells reuse the same markup).

The ribbon: Now · Data → Coaching → Protocols → Story, cycling back. `Now` (the live
cockpit vantage) leads, set apart by a faint separator from the four causal-loop
stages; the current door is marked ember (.lr-here). On pages that are neither the
vantage nor a stage (Home, the footer-tier Method) nothing is marked — the ribbon
still orients ("here's the loop, click to enter").

`current_door` is the door key: "cockpit" | "data" | "coaching" | "protocols" |
"story" — anything else (e.g. "home", "method") marks nothing.
"""

from __future__ import annotations

LOOP_VANTAGE = ("/cockpit/", "Now", "cockpit")
LOOP_NODES = [
    ("/data/", "Data", "data"),
    ("/coaching/", "Coaching", "coaching"),
    ("/protocols/", "Protocols", "protocols"),
    ("/story/", "Story", "story"),
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
