#!/usr/bin/env python3
"""scripts/www_smoke_pins.py — the root smoke's page assertions, read BEFORE the publish instead of after it (#6320).

`deploy/smoke_test_site.sh` asserts fixed strings on the live pages (`check_body_contains "<label>" "$FILE" '<needle>'
"$BASE/<route>"`). It runs only in the root deploy, after the sync, and a red row rolls the v9 paths back. On
2026-11-27 a merged change removed the front page's portrait tiles while the smoke still asserted `portrait-tiles`:
every pre-merge gate was green, the launch was published and rolled back, and the site sat on the previous build
until the row was corrected.

This reads those rows out of the smoke script itself (one source: the row is never copied here) and holds the BUILT
pages to them, so a stale assertion fails the web gate on the PR that makes it stale.

Only rows for a route the v9 build writes are held (`/`, `/story/`, `/data/` today; the rest of the smoke belongs to
`site/` pages this build does not make). A needle naming the production host is skipped: the gate grades the preview
base, whose canonical is not the root's. `check_body_not_contains` rows are not held — a preview build is `noindex`
by design, and the incident class is an assertion of something a change removed.

Used by scripts/check_www_build.py (the `scan` step). Stdlib only.
"""

from __future__ import annotations

import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE_SH = os.path.join(REPO, "deploy", "smoke_test_site.sh")

#: check_body_contains "<label>" "$VAR" '<needle>' "$BASE<route>"
ROW = re.compile(r"""^\s*check_body_contains\s+"(?P<label>[^"]+)"\s+"\$\w+"\s+'(?P<needle>[^']+)'\s+"\$BASE(?P<route>/[^"]*)"\s*$""")
#: a needle tied to the production base (the gate builds the preview base)
BASE_BOUND = re.compile(r"averagejoematt\.com")


def smoke_pins(smoke_sh: str = SMOKE_SH) -> list[tuple[str, str, str]]:
    """Every `check_body_contains` row of the smoke script as (label, route, needle), base-bound needles left out."""
    pins = []
    with open(smoke_sh, encoding="utf-8") as fh:
        for line in fh:
            m = ROW.match(line)
            if m and not BASE_BOUND.search(m.group("needle")):
                pins.append((m.group("label"), m.group("route"), m.group("needle")))
    return pins


def _page(dist: str, route: str) -> str | None:
    """The built page for a route, at the root or under the preview base; None when the build does not write it."""
    for base in ("", os.path.join("next", "v9")):
        path = os.path.join(dist, base, route.strip("/"), "index.html")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
    return None


def smoke_pin_misses(dist: str, smoke_sh: str = SMOKE_SH) -> tuple[list[str], int]:
    """(issues, held): each smoke row whose needle the built page does not carry, and how many rows were held.

    A row for a route the build does not write is not this build's (it belongs to a `site/` page) and is not held."""
    issues: list[str] = []
    held = 0
    pages: dict[str, str | None] = {}
    for label, route, needle in smoke_pins(smoke_sh):
        if route not in pages:
            pages[route] = _page(dist, route)
        html = pages[route]
        if html is None:
            continue
        held += 1
        if needle not in html:
            issues.append(
                f"the root smoke asserts {needle!r} on {route} ({label!r}, deploy/smoke_test_site.sh) and the built page does not carry it: "
                "the deploy would publish and roll back. Change the row in the same PR as the markup."
            )
    return issues, held
