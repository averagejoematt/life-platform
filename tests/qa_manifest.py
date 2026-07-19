#!/usr/bin/env python3
"""
qa_manifest.py — THE page registry every QA sweep derives from (#1426).

One entry per live page under site/ (legacy/ excluded by standing policy).
The four previously hand-maintained page lists — tests/visual_qa.py PAGES,
deploy/smoke_test_site.sh v4-page block, deploy/restart_verify_rendered.py
PAGES, and the site-review PAGE_BINDINGS keys — now all derive from or are
gated against this module, killing the "new page = FOUR registries" trap
(memory: reference_new_site_page_registries). Modeled on the
lambdas/source_registry.py facet pattern: each consumer reads its own facet,
nobody re-lists pages.

Entry fields
  path           viewer path with trailing slash ("/x/…/"), or a bare file
                 ("/404.html") for the non-directory pages
  name           human label (used by smoke + visual output)
  tier           1 flagship doors (deploy-gating visual + AI QA)
                 2 live-data topic pages (deploy visual sweep)
                 3 editorial/static (smoke + leak scan; visual pending #1427)
                 4 utility/redirect stubs (status-only)
  content_class  "live-data" | "narrative" | "static" | "utility" | "generated"
  api_deps       /api endpoints (or absolute JSON paths) the page renders from.
                 Under-claiming is safe; over-claiming is not (site-review rule).
  js_modules     main ES module(s) the page loads (informational facet, #1431)
  visual         Playwright def for tests/visual_qa.py (wait_for/checks/charts/
                 interact) or None = not yet in the sweep (#1427 extends).
  leak_scan      include in restart_verify_rendered token grep (default True
                 for every real HTML page; False only for pure redirects)
  smoke          expected HTTP status for the status sweep (default "200")

Archive-topic entries (the /data/ · /protocols/ · /method/ readout pages) are
GENERATED from scripts/v4_build_evidence.REGISTRY + PILLARS at import time so
they can never drift from the live build — same trick site_review_bindings
uses for its primary endpoints.

Emitters (for the bash smoke script and ad-hoc use):
    python3 tests/qa_manifest.py --emit paths   # every page path
    python3 tests/qa_manifest.py --emit smoke   # "path|name|expected_status"
    python3 tests/qa_manifest.py --emit leak    # leak-scan page paths
    python3 tests/qa_manifest.py --check        # internal consistency self-check

No third-party deps. Importable by tests/* (sibling) and deploy/* scripts
(insert REPO_ROOT/tests on sys.path).
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)


def _evidence_rows():
    """(path, title, group, mode, endpoint, flags) per archive topic, from the build registry."""
    scripts = os.path.join(_REPO, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import v4_build_evidence as v  # noqa: E402

    group_to_base = {}
    for pillar in v.PILLARS:
        for g in pillar["groups"]:
            group_to_base[g] = pillar["base"]
    rows = []
    for entry in v.REGISTRY:
        slug, title, _blurb, group, mode, endpoint = entry[:6]
        flags = set(entry[8:])
        base = group_to_base.get(group)
        if base is None:  # a group outside the three pillars would be a build bug
            raise AssertionError(f"REGISTRY group {group!r} not in any PILLARS entry")
        rows.append((f"{base}{slug}/", title, group, mode, endpoint, flags))
    return rows


# ── Visual defs for the archive topics already in the Playwright sweep ────────
# Exactly the pre-#1426 tests/visual_qa.py coverage (EVIDENCE_TOPICS +
# METHOD_TOPICS + the /method/character/ explainer + the three protocols topic
# pages). #1427 extends visual coverage to the rest — flipping a page in is a
# one-line visual= change here, not a new list anywhere.
CHART_TOPICS = {"vitals", "physical", "glucose", "sleep", "training", "character"}
_VISUAL_EVIDENCE = {
    "/data/vitals/",
    "/data/physical/",
    "/data/labs/",
    "/data/glucose/",
    "/data/sleep/",
    "/data/training/",
    "/data/nutrition/",
    "/data/habits/",
    "/data/character/",
    "/method/board/",
    "/method/pipeline/",
    "/method/intelligence/",
    "/method/predictions/",
    "/method/scenarios/",
    "/method/benchmarks/",
    "/method/character/",
    "/protocols/experiments/",
    "/protocols/challenges/",
    "/protocols/supplements/",
}


def _readout_visual(path: str, title: str) -> dict:
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    d = {
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": f"{slug} readout rendered"}],
    }
    if slug in CHART_TOPICS and path.startswith("/data/"):
        d["charts"] = ["[data-readout] svg"]
    return d


def _archive_entries():
    out = []
    for path, title, group, mode, endpoint, flags in _evidence_rows():
        live = mode == "data"
        out.append(
            {
                "path": path,
                "name": f"{path.split('/')[1].capitalize()} · {title}",
                "tier": 2 if live else 3,
                "content_class": "live-data" if live else "narrative",
                "api_deps": [endpoint] if (live and endpoint) else [],
                "js_modules": ["evidence.js"],
                "visual": _readout_visual(path, title) if path in _VISUAL_EVIDENCE else None,
                "leak_scan": True,
                "smoke": "200",
                "unlisted": "unlisted" in flags,
            }
        )
    return out


# ── Curated entries — everything that is not an archive readout page ──────────
# visual defs here are moved VERBATIM from the pre-#1426 tests/visual_qa.py
# PAGES list (coverage identical; the sweep now reads them from this facet).
_CURATED = [
    {
        "path": "/",
        "name": "Home (constellation)",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": ["/api/journey", "/api/character"],
        "js_modules": ["home.js"],
        "visual": {
            "wait_for": ".constellation svg",
            "checks": [
                {
                    "selector": ".constellation svg a, .constellation svg .node",
                    "min_count": 7,
                    "desc": "7 pillar nodes drawn in the constellation",
                },
                {
                    "selector": "a[href='/cockpit/'], a[href='/story/'], a[href='/data/']",
                    "min_count": 2,
                    "desc": "the three door links present",
                },
            ],
            "charts": [".constellation svg"],
        },
    },
    {
        "path": "/cockpit/",
        "name": "Cockpit",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": ["/api/character", "/api/pulse", "/api/journey"],
        "js_modules": ["cockpit.js"],
        "visual": {
            "wait_for": "[data-bind='level']",
            "checks": [
                {"selector": "[data-bind='level']", "not_empty": True, "desc": "character level rendered"},
                {"selector": ".row", "min_count": 1, "desc": "at least one pillar row"},
                {"selector": ".site-foot-cols .sf-col", "min_count": 4, "desc": "footer mega-menu (4 columns) present (CC-05)"},
            ],
            "interact": {"click": ".row", "expect": ".pillar-detail", "desc": "pillar disclosure opens with the Day-Grade Replay detail"},
        },
    },
    {
        "path": "/story/",
        "name": "Story hub",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "narrative",
        "api_deps": ["/journal/posts.json"],
        "js_modules": ["story.js"],
        "visual": {
            "wait_for": "[data-dx-tabs], [data-dx-read]",
            "checks": [
                {
                    "selector": "[data-dx-tabs], [data-dx-list]",
                    "min_count": 1,
                    "desc": "dispatches reader (chronicle/journal/lab-notes tabs) rendered",
                },
                {"selector": "a[href='/data/'], a[href='/cockpit/']", "min_count": 1, "desc": "door links present"},
            ],
        },
    },
    {
        "path": "/story/chronicle/",
        "name": "Story · chronicle",
        "tier": 2,
        "content_class": "narrative",
        "api_deps": ["/api/timeline"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "chronicle content"}]},
    },
    {
        "path": "/story/journal/",
        "name": "Story · journal",
        "tier": 2,
        "content_class": "narrative",
        "api_deps": ["/journal/posts.json"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "journal content"}]},
    },
    {
        "path": "/story/about/",
        "name": "Story · about",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": {"checks": [{"selector": "main, article", "not_empty": True, "desc": "about content"}]},
    },
    {
        "path": "/story/attempts/",
        "name": "Story · the attempts (#1375)",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/cycle_compare"],
        "js_modules": ["attempts.js"],
        "visual": {
            "checks": [
                {"selector": "[data-att-figs]", "not_empty": True, "desc": "attempt headline figures"},
                {"selector": "[data-att-log]", "not_empty": True, "desc": "expedition log cards"},
                {"selector": ".att-svg", "not_empty": False, "desc": "same-day-axis overlay SVG"},
            ]
        },
    },
    {
        "path": "/story/agents/",
        "name": "Story · the agents",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/agents"],
        "js_modules": ["agents.js"],
        "visual": {"checks": [{"selector": "[data-roster], .agent-card, [data-feed]", "not_empty": True, "desc": "agent roster + feed"}]},
    },
    {
        "path": "/story/build/",
        "name": "Story · build dispatches",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["story.js"],
        "visual": None,
    },
    {
        "path": "/story/panel/",
        "name": "Story · panelcast",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": ["/panelcast/episodes.json"],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/story/timeline/",
        "name": "Story · timeline",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/timeline"],
        "js_modules": ["story.js"],
        "visual": None,
    },
    {
        "path": "/data/",
        "name": "Data hub",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": [],
        "js_modules": ["evidence.js"],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "data readout rendered"}],
        },
    },
    {
        "path": "/protocols/",
        "name": "Protocols hub",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": [],
        "js_modules": ["evidence.js"],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "protocols readout rendered"}],
        },
    },
    {
        "path": "/method/",
        "name": "Method hub",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": [],
        "js_modules": ["evidence.js"],
        "visual": None,
    },
    {
        "path": "/method/game/",
        "name": "Method · the game, explained (GENERATED — v4_build_game_explained.py)",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/method/registry/",
        "name": "Method · methods registry",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    # ── Coaching door (promoted 2026-06-20) ──────────────────────────────────
    {
        "path": "/coaching/",
        "name": "Coaching hub (My Team)",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": ["/api/coaches", "/api/coach_team"],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-tabs]",
            "checks": [
                {"selector": "[data-dx-tabs], [data-dx-list]", "min_count": 1, "desc": "coaching tabs + roster rendered"},
                {"selector": "[data-dx-read]", "not_empty": True, "desc": "team/coach readout rendered"},
            ],
        },
    },
    {
        "path": "/coaching/by-coach/",
        "name": "Coaching · By Coach",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/coach_team", "/api/field_notes"],
        "js_modules": ["coaching.js"],
        # Two deep-link sweeps preserved verbatim from the pre-#1426 registry:
        "visual_variants": [
            {
                "fragment": "#training_coach",
                "name": "Coaching · By Coach (read-on-data, deep-link)",
                "wait_for": "[data-dx-read]",
                "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "coach read + domain data rendered"}],
            },
            {
                "fragment": "#eli_marsh",
                "name": "Coaching · By Coach (head coach, lead tier)",
                "wait_for": "[data-dx-read]",
                "checks": [
                    {"selector": ".coach-head--lead", "min_count": 1, "desc": "lead-tier header rendered for the head coach"},
                    {"selector": "[data-dx-read] .team-lead", "min_count": 1, "desc": "running-the-program block rendered"},
                ],
            },
        ],
        "visual": None,
    },
    {
        "path": "/coaching/scorecard/",
        "name": "Coaching · Scorecard (graded track record)",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/coach_track_records"],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "scorecard tiles + per-coach record rendered"}],
        },
    },
    {
        "path": "/coaching/team/",
        "name": "Coaching · The Team (roster/config)",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/coach_team"],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "team roster/profile rendered"}],
        },
    },
    {
        "path": "/coaching/lab-notes/",
        "name": "Coaching · AI lab notes",
        "tier": 2,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "lab-notes readout rendered"}],
        },
    },
    {
        "path": "/coaching/coaches/",
        "name": "Coaching · The Team (legacy slug)",
        "tier": 3,
        "content_class": "live-data",
        "api_deps": ["/api/coach_team"],
        "js_modules": ["coaching.js"],
        "visual": None,
    },
    {
        "path": "/coaching/qa/",
        "name": "Coaching · Reader Q&A",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["coaching.js"],
        "visual": None,
    },
    {
        "path": "/coaching/read/",
        "name": "Coaching · The Read",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["coaching.js"],
        "visual": None,
    },
    # ── Mind (redirect shell → /data/reading/) ───────────────────────────────
    {
        "path": "/mind/",
        "name": "Mind → /data/reading (redirect + readout)",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        "smoke": "301",  # 301s to /data/reading/ at the CloudFront edge (#313)
        "leak_scan": False,  # pure meta-refresh/JS hop; the target page is scanned
        "visual": {
            "wait_for": ".ev-app",
            "checks": [
                {"selector": ".ev-tile", "min_count": 3, "desc": "archive tiles render after the redirect"},
                {"selector": ".readout, .ev-main", "min_count": 1, "desc": "the reading readout mounts"},
            ],
        },
    },
    # ── Standalone / utility ─────────────────────────────────────────────────
    {
        "path": "/gear/",
        "name": "The Gear",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/journal/essays/org-chart-of-one/",
        "name": "Essay · The Org Chart of One",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/privacy/",
        "name": "Privacy",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/subscribe/",
        "name": "Subscribe",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/subscribe/confirm/",
        "name": "Subscribe · confirm",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/404.html",
        "name": "404 page (direct object)",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        "visual": None,
    },
    {
        "path": "/subscribe.html",
        "name": "Legacy /subscribe.html (meta-refresh stub → /subscribe/)",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        "leak_scan": False,
        "visual": None,
    },
]

# Files under site/ that are deliberately NOT pages (or excluded by policy).
# path-prefix match for directories, exact for files. Every exemption carries
# its reason — the completeness gate treats anything else as unregistered.
EXEMPT = {
    "/legacy/": "verbatim pre-v4 archive, private rollback surface — never QA-swept by policy (ADR-071)",
    "/index.html": "the '/' entry covers it (directory index)",
}


def _build():
    pages = list(_CURATED) + _archive_entries()
    for p in pages:
        p.setdefault("leak_scan", True)
        p.setdefault("smoke", "200")
        p.setdefault("unlisted", False)
        # #1395: does this page ship a build-time <noscript> static core (headline
        # numbers + "as of" provenance) so the no-JS / crawler / link-unfurl view is
        # real content, not a blank shell? True only for the growth-surface pages
        # (Home + the doors); deploy/smoke_test_site.sh asserts it per page.
        p.setdefault("static_core", False)
    seen = {}
    for p in pages:
        if p["path"] in seen:
            raise AssertionError(f"duplicate manifest path {p['path']}")
        seen[p["path"]] = p
    return pages


MANIFEST = _build()
PAGES_BY_PATH = {p["path"]: p for p in MANIFEST}


# ── Consumer facets ───────────────────────────────────────────────────────────
def visual_pages():
    """tests/visual_qa.py PAGES — order-stable, identical to pre-#1426 coverage."""
    out = []
    for p in MANIFEST:
        if p.get("visual"):
            d = dict(p["visual"])
            d["path"] = p["path"]
            d["name"] = p["name"]
            out.append(d)
        for var in p.get("visual_variants", []) or []:
            d = dict(var)
            d["path"] = p["path"] + d.pop("fragment", "")
            out.append(d)
    return out


def leak_scan_paths():
    """deploy/restart_verify_rendered.py PAGES — every real HTML page."""
    return [p["path"] for p in MANIFEST if p["leak_scan"] and not p["path"].endswith(".html")]


def smoke_rows():
    """deploy/smoke_test_site.sh — 'path|name|expected_status' per page."""
    return [f"{p['path']}|{p['name']}|{p['smoke']}" for p in MANIFEST]


def static_core_paths():
    """deploy/smoke_test_site.sh — pages that MUST ship a build-time static core (#1395)."""
    return [p["path"] for p in MANIFEST if p.get("static_core")]


def site_files():
    """Every page-shaped file under site/ (repo truth for the completeness gate)."""
    site = os.path.join(_REPO, "site")
    found = set()
    for root, dirs, files in os.walk(site):
        rel = os.path.relpath(root, site)
        if rel.split(os.sep)[0] == "legacy":
            dirs[:] = []
            continue
        for f in files:
            if not f.endswith(".html"):
                continue
            rp = "/" if rel == "." else f"/{rel.replace(os.sep, '/')}/"
            found.add(rp + f if f != "index.html" else rp)
    # normalize: "/x/index.html" recorded as "/x/", top-level files as "/name.html"
    return {p.replace("//", "/") for p in found}


def self_check():
    files = site_files()
    registered = set(PAGES_BY_PATH)
    exempt_prefixes = tuple(k for k in EXEMPT if k.endswith("/"))
    exempt_exact = {k for k in EXEMPT if not k.endswith("/")}
    unregistered = {f for f in files if f not in registered and f not in exempt_exact and not f.startswith(exempt_prefixes)}
    ghosts = {
        p
        for p in registered
        if p not in files
        and not os.path.exists(os.path.join(_REPO, "site", p.strip("/").replace("/", os.sep), "index.html"))
        and not os.path.exists(os.path.join(_REPO, "site", p.strip("/")))
    }
    return unregistered, ghosts


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--emit", choices=["paths", "smoke", "leak", "static_core"])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        unregistered, ghosts = self_check()
        if unregistered:
            print("UNREGISTERED pages (add a manifest entry or an EXEMPT reason):")
            for p in sorted(unregistered):
                print(f"  {p}")
        if ghosts:
            print("GHOST manifest entries (no file under site/):")
            for p in sorted(ghosts):
                print(f"  {p}")
        if unregistered or ghosts:
            sys.exit(1)
        print(f"OK — {len(MANIFEST)} pages registered, 0 unregistered, 0 ghosts")
        return
    if args.emit == "paths":
        for p in MANIFEST:
            print(p["path"])
    elif args.emit == "smoke":
        for row in smoke_rows():
            print(row)
    elif args.emit == "leak":
        for p in leak_scan_paths():
            print(p)
    elif args.emit == "static_core":
        for p in static_core_paths():
            print(p)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
