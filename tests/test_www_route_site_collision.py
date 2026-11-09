"""No v9 (www/) route may land on a page the site/ tree serves unless www/owned_paths.json claims it (2026-11-09).

Why: HS1's timeline was built at /story/timeline/ — the URL of the established v8 page, served from
site/story/timeline/index.html by deploy/sync_site_to_s3.sh and the target of three redirects. The dark routes (the
Coaching Room, the Laboratory, the Human Story) are injected by Astro integrations, not read off src/pages/, so they
never reach owned_paths.json until the switch is on — the deploy-time collision check (deploy/www_owned_paths.py
--check-dist) would only have caught it at go-live, on the live build. This guard holds it on every PR, statically:

  * every route the build owns or declares (owned_paths.json `routes` + `static_routes`), and
  * every route a dark integration CAN inject (the `path:` values of ROOM_ROUTES / LAB_ROUTES / STORY_ROUTES, read off
    the JS helpers by scripts/check_www_build.py::room_paths — a `[param]` segment matches any one directory)

is checked against site/: a route whose `site/<route>index.html` exists is a collision unless owned_paths.json's
`routes` claims that exact route (the four replaced destinations do). src/pages `[param]` patterns are data-dependent
and stay with --check-dist on the live build. The mutation controls plant the original collision and must red.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)

import check_www_build  # noqa: E402 — room_paths(): the injected routes, read off each helper

from deploy import www_owned_paths  # noqa: E402 — the one reader of owned_paths.json

SITE = os.path.join(REPO, "site")
HELPERS = {
    "room": os.path.join(REPO, "www", "src", "lib", "room.js"),
    "lab": os.path.join(REPO, "www", "src", "lib", "lab.js"),
    "story": os.path.join(REPO, "www", "src", "lib", "story_dark.js"),
}


def injected_routes(helpers: dict[str, str] = HELPERS) -> dict[str, str]:
    """route → the helper that can inject it."""
    out: dict[str, str] = {}
    for name, path in helpers.items():
        for r in check_www_build.room_paths(path):
            out[r] = name
    return out


def site_pages_for(route: str, site: str = SITE) -> list[str]:
    """The site/ pages a route would write over: `<route>index.html`, a `[param]` segment matching one directory."""
    parts = re.split(r"(\[[^\]]+\])", route.strip("/"))
    rel = "".join("*" if re.fullmatch(r"\[[^\]]+\]", p) else glob.escape(p) for p in parts)
    target = os.path.join(glob.escape(site), rel, "index.html") if rel else os.path.join(glob.escape(site), "index.html")
    return sorted(os.path.relpath(p, site) for p in glob.glob(target) if os.path.isfile(p))


def collisions(owned: dict, extra: dict[str, str] | None = None, site: str = SITE) -> list[str]:
    claimed = set(owned["routes"])
    candidates = {r: "owned_paths.json" for r in [*owned["routes"], *owned["static_routes"]]}
    candidates.update(injected_routes())
    candidates.update(extra or {})
    bad = []
    for route, origin in sorted(candidates.items()):
        if route in claimed:
            continue  # owned: the site/ deploy excludes exactly this path (one owner per path, #5534)
        for page in site_pages_for(route, site):
            bad.append(f"{route} ({origin}) lands on site/{page}, and owned_paths.json does not claim it")
    return bad


def test_no_www_route_lands_on_an_unclaimed_site_page():
    owned = www_owned_paths.load()
    assert collisions(owned) == []


def test_the_guard_sees_every_dark_helper():
    routes = injected_routes()
    assert {"room", "lab", "story"} <= set(routes.values()), routes  # a helper that reads as empty would blind the guard
    assert "/data/lab/" in routes and "/story/so-far/" in routes


def test_mutation_control_the_original_collision_reds():
    owned = www_owned_paths.load()
    assert os.path.isfile(os.path.join(SITE, "story", "timeline", "index.html")), "the kept page this guard protects"
    bad = collisions(owned, extra={"/story/timeline/": "story (planted)"})
    assert any(b.startswith("/story/timeline/ (story (planted)) lands on site/story/timeline/index.html") for b in bad), bad
    # a [param] dark route matches any one directory: planted under /story/, it must find the kept story pages
    bad = collisions(owned, extra={"/story/[id]/": "story (planted)"})
    assert any("site/story/timeline/index.html" in b for b in bad) and any("site/story/chronicle/index.html" in b for b in bad), bad


def test_mutation_control_a_claimed_route_passes_and_a_replaced_destination_is_claimed():
    owned = json.loads(json.dumps(www_owned_paths.load()))
    # the four replaced destinations collide with site/ by design and are claimed — the exemption the guard relies on
    for r in ("/", "/story/", "/data/", "/privacy/"):
        assert site_pages_for(r), r
        assert r in owned["routes"], r
    # a deliberate takeover would claim the route; the planted collision then passes
    owned["routes"].append("/story/timeline/")
    assert collisions(owned, extra={"/story/timeline/": "story (planted)"}) == []
