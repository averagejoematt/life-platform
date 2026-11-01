#!/usr/bin/env python3
"""deploy/www_owned_paths.py — the ONE reader of www/owned_paths.json (#5534, epic #5529).

Two deploy paths write s3://matthew-life-platform/site/: the site/ tree (deploy/sync_site_to_s3.sh on
every merge touching site/**, and deploy/rollback_site.sh on a red sweep) and the v9 build (www/dist,
deploy/www_preview_sync.sh). Without one owner per path, the next site/ push or a red sweep re-syncs
the v8 front page over the launch. This module turns the build's committed route manifest into:

  * the `--exclude` set the site/ syncs pass to `aws s3 sync` (exact paths, never a prefix that could
    swallow a kept page — site/story/chronicle/ stays site-owned even though /story/*/ is a v9 pattern);
  * the collision rule the root deploy applies to the LIVE build before it syncs: a v9 route that
    lands on a kept site/ page outside the declared replaced set is refused (the owner's rulings:
    no URL changes meaning, nothing is deleted, no redirects);
  * the cut-over switch `live_at_root`, read by qa/qa_manifest.py, scripts/v4_build_sitemap.py and
    tests/test_site_nav_reach_ratchet.py so the repo's description of `/` follows one committed bit.

Usage:
  python3 deploy/www_owned_paths.py --exclude-args [--under assets]   # "--exclude a --exclude b …"
  python3 deploy/www_owned_paths.py --check-dist www/dist              # exit 1 on a collision
  python3 deploy/www_owned_paths.py --live-at-root                     # exit 0 live · 1 not yet
  python3 deploy/www_owned_paths.py --summary

No AWS, no network. aws-cli `--exclude` patterns are matched against the path relative to the sync's
SOURCE directory, so `--under assets` re-roots the patterns for the two `assets/` sub-syncs.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNED_PATHS_JSON = os.path.join(REPO, "www", "owned_paths.json")
SITE = os.path.join(REPO, "site")

#: The site/ pages the v9 build REPLACES at their own URL (plan §C: the four destinations keep the
#: addresses readers already have). Each is kept as a reference copy under site/reference/
#: (scripts/v9_reference_copies.py, owner ruling 2026-10-18). Any other collision between a v9 route
#: and a kept site/ page is a defect — `collisions()` names it and the root deploy refuses it.
REPLACED_ROUTES = frozenset({"/", "/story/", "/data/", "/privacy/"})
#: Loose files the build writes at the root that site/ also carries. The 404 body is a utility page
#: (no layout to keep); sitemap.xml changes writer at cut-over (scripts/v4_build_sitemap.py).
REPLACED_FILES = frozenset({"404.html", "sitemap.xml"})

#: The superseded pages → (reference slug, layout, canonical successor). The first four are the live
#: v8 kit pages the issue names; /start/ and /coaches/ have no v9 twin, so they stay served from
#: site/ (noindex, canonical to their successor) and are copied for the record like the others.
#: /data/ and /privacy/ are the two v5 pages the build also replaces at their URL.
SUPERSEDED = {
    "/": ("home", "v8", "/"),
    "/start/": ("start", "v8", "/"),
    "/story/": ("story", "v8", "/story/"),
    "/coaches/": ("coaches", "v8", "/system/"),
    "/data/": ("data", "v5", "/data/"),
    "/privacy/": ("privacy", "v5", "/privacy/"),
}
CUTOVER_DATE = "2026-11-01"


def load(path: str = OWNED_PATHS_JSON) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("routes", "files", "prefixes", "static_routes", "route_patterns"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"{path}: missing list {key!r} — rebuild with `npm run build` in www/")
    return data


def live_at_root(data: dict | None = None) -> bool:
    data = data if data is not None else load()
    return data.get("live_at_root") is True


def owned_relpaths(data: dict | None = None) -> list[str]:
    """Every exact site/-relative path the build owns (routes as `<dir>/index.html`, plus files)."""
    data = data if data is not None else load()
    out = set()
    for route in data["routes"]:
        rel = route.strip("/")
        out.add(f"{rel}/index.html" if rel else "index.html")
    out.update(data["files"])
    return sorted(out)


def exclude_patterns(data: dict | None = None, under: str = "") -> list[str]:
    """aws-cli `--exclude` patterns relative to the sync source `under` ("" = site/, "assets" …).

    Exact paths for pages and files; `<prefix>*` for the two asset prefixes. A pattern outside the
    sub-root is dropped (it cannot match there), and a pattern inside it is re-rooted.
    """
    data = data if data is not None else load()
    pats = list(owned_relpaths(data)) + [f"{p.rstrip('/')}/*" for p in data["prefixes"]]
    root = under.strip("/")
    if not root:
        return pats
    out = []
    for p in pats:
        if p.startswith(root + "/"):
            out.append(p[len(root) + 1 :])
    return out


def is_excluded(relpath: str, data: dict | None = None, under: str = "") -> bool:
    """Would `aws s3 sync` skip this source-relative path under the exclude set? (fnmatch, as the CLI)."""
    return any(fnmatch.fnmatchcase(relpath, pat) for pat in exclude_patterns(data, under))


def dist_routes(dist: str) -> tuple[set[str], set[str]]:
    """(directory routes, loose root files) a built dist/ would write under its prefix."""
    routes, files = set(), set()
    for dirpath, dirnames, filenames in os.walk(dist):
        rel_dir = os.path.relpath(dirpath, dist).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        top = rel_dir.split("/")[0]
        if top in ("_astro", "assets", ".prerender"):
            dirnames[:] = []
            continue
        for name in filenames:
            if name == "index.html":
                routes.add("/" + (rel_dir + "/" if rel_dir else ""))
            else:
                files.add((rel_dir + "/" if rel_dir else "") + name)
    return routes, files


def collisions(routes: set[str], files: set[str], site: str = SITE) -> list[str]:
    """v9 output that would land on a kept site/ page or file OUTSIDE the declared replaced set."""
    bad = []
    for route in sorted(routes):
        rel = route.strip("/")
        if os.path.isfile(os.path.join(site, rel, "index.html") if rel else os.path.join(site, "index.html")):
            if route not in REPLACED_ROUTES:
                bad.append(f"route {route} — site{route}index.html is a kept page (not in REPLACED_ROUTES)")
    for f in sorted(files):
        if os.path.isfile(os.path.join(site, f)) and f not in REPLACED_FILES:
            bad.append(f"file {f} — site/{f} is kept (not in REPLACED_FILES)")
    return bad


def check_dist(dist: str, site: str = SITE) -> list[str]:
    if not os.path.isfile(os.path.join(dist, "index.html")):
        return [f"{dist}: no index.html — not a built v9 tree"]
    routes, files = dist_routes(dist)
    return collisions(routes, files, site)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exclude-args", action="store_true", help="print `--exclude <p>` pairs for aws s3 sync")
    ap.add_argument("--under", default="", help="re-root the patterns for a sub-sync (e.g. assets)")
    ap.add_argument("--check-dist", metavar="DIST", help="refuse a built tree that collides with a kept site/ page")
    ap.add_argument("--live-at-root", action="store_true", help="exit 0 when the build owns `/`, 1 otherwise")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--json", default=OWNED_PATHS_JSON)
    args = ap.parse_args(argv)
    data = load(args.json)

    if args.exclude_args:
        print(" ".join(f"--exclude {p}" for p in exclude_patterns(data, args.under)))
        return 0
    if args.live_at_root:
        live = live_at_root(data)
        print(f"live_at_root={'true' if live else 'false'}" + ("" if live else "  (the v9 build is served at /next/v9/ only)"))
        return 0 if live else 1
    if args.check_dist:
        bad = check_dist(args.check_dist)
        if bad:
            print("www_owned_paths: the built tree would overwrite kept site/ content — refusing (#5534):", file=sys.stderr)
            for b in bad:
                print(f"  ✗ {b}", file=sys.stderr)
            return 1
        routes, files = dist_routes(args.check_dist)
        print(f"www_owned_paths: {len(routes)} routes + {len(files)} files collide only with the declared replaced set ✓")
        return 0
    rel = owned_relpaths(data)
    print(
        f"owned: {len(data['routes'])} routes · {len(data['files'])} files · prefixes {data['prefixes']} · live_at_root={live_at_root(data)}"
    )
    print(f"exclude set (site/): {len(exclude_patterns(data))} patterns; (assets/): {exclude_patterns(data, 'assets')}")
    print(f"static routes: {data['static_routes']}")
    print(f"first owned paths: {rel[:5]} …")
    return 0


if __name__ == "__main__":
    sys.exit(main())
