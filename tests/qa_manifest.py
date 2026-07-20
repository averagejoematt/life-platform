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
  ai_surface     #1441 (default False): True = the page renders AI-generated
                 narrative a reader sees (coach commentary, board answers,
                 chronicle, field notes, State of Matthew). The daily standalone
                 visual-qa run archives these pages' full-page screenshots to
                 s3://…/generated/qa_archive/screenshots/{date}/ (90d lifecycle)
                 — the screenshot leg of the generation-time AI archive
                 (lambdas/qa_archive.py is the text leg). Under-claiming loses
                 evidence; over-claiming only costs pennies of S3.
  structural     #1429 (static/utility pages only): {"marker": <fixed string the
                 live body must contain — an expected title/selector fragment>,
                 "fetch_path": <optional viewer-path override — the 404 page is
                 asserted via a nonexistent URL, where CloudFront serves the body
                 with status 404>}. REQUIRED on every static/utility 200 page
                 (structural_rows() raises otherwise) so a new static page can't
                 land outside the smoke's structural gate.

Archive-topic entries (the /data/ · /protocols/ · /method/ readout pages) are
GENERATED from scripts/v4_build_evidence.REGISTRY + PILLARS at import time so
they can never drift from the live build — same trick site_review_bindings
uses for its primary endpoints.

Emitters (for the bash smoke script and ad-hoc use):
    python3 tests/qa_manifest.py --emit paths       # every page path
    python3 tests/qa_manifest.py --emit smoke       # "path|name|expected_status"
    python3 tests/qa_manifest.py --emit leak        # leak-scan page paths
    python3 tests/qa_manifest.py --emit static_core # pages that must ship a static core
    python3 tests/qa_manifest.py --emit structural  # "fetch_path|name|marker" (#1429)
    python3 tests/qa_manifest.py --emit ai-screens  # screenshot slugs of ai_surface pages (#1441)
    python3 tests/qa_manifest.py --check            # internal consistency self-check

No third-party deps. Importable by tests/* (sibling) and deploy/* scripts
(insert REPO_ROOT/tests on sys.path).
"""
from __future__ import annotations

import argparse
import json
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


# ── Visual defs for the archive topics ────────────────────────────────────────
# Every archive/readout page (the /data/ · /protocols/ · /method/ topic pages
# generated from scripts/v4_build_evidence.REGISTRY) shares one template —
# evidence.js always mounts content into a `[data-readout]` element, for every
# mode (data/interactive/editorial) — verified by grep across the built site/
# (#1427). So _readout_visual applies uniformly to ALL archive rows now, not
# just the pre-#1426 hand-picked subset; flipping a page into the sweep is a
# one-line visual= change here, not a new list anywhere.
CHART_TOPICS = {"vitals", "physical", "glucose", "sleep", "training", "character"}


def _readout_visual(path: str, title: str) -> dict:
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    d = {
        "wait_for": "[data-readout]",
        "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": f"{slug} readout rendered"}],
    }
    if slug in CHART_TOPICS and path.startswith("/data/"):
        d["charts"] = ["[data-readout] svg"]
    return d


# #1441: generated archive pages that render reader-visible AI narrative (the
# board read). The curated entries carry ai_surface literally; these rows are
# built from the evidence registry, so the flag is keyed by path here.
_AI_ARCHIVE_PAGES = {"/method/board/"}


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
                "visual": _readout_visual(path, title),
                "leak_scan": True,
                "smoke": "200",
                "unlisted": "unlisted" in flags,
                "ai_surface": path in _AI_ARCHIVE_PAGES,  # #1441
            }
        )
    return out


# ── Curated entries — everything that is not an archive readout page ──────────
# visual defs here are moved VERBATIM from the pre-#1426 tests/visual_qa.py
# PAGES list (coverage identical; the sweep now reads them from this facet).
_CURATED = [
    {
        "path": "/",
        # #1469 (variant A "the loop, drawn live"): the fold is now the loop dial —
        # a code-drawn SVG with the four door stations + the live day counter at the
        # hub; the constellation moved below the fold but keeps its section (and these
        # constellation checks stay true of the page).
        "name": "Home (loop dial)",
        "static_core": True,  # #1395: ships a <noscript> static core (headline numbers + as-of)
        "tier": 1,
        "content_class": "live-data",
        "api_deps": ["/api/journey", "/api/character"],
        "js_modules": ["home.js"],
        "visual": {
            "wait_for": ".constellation svg",
            "checks": [
                {
                    "selector": ".loop-dial .st",
                    "min_count": 4,
                    "desc": "the 4 loop-dial stations drawn in the fold (#1469)",
                },
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
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
        "name": "Story · chronicle",
        "tier": 2,
        "content_class": "narrative",
        "api_deps": ["/api/timeline"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "chronicle content"}]},
    },
    {
        "path": "/story/journal/",
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
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
        "structural": {"marker": 'class="ph-title"'},
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
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "build dispatches content"}]},
    },
    {
        "path": "/story/panel/",
        "name": "Story · panelcast",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": ["/panelcast/episodes.json"],
        "js_modules": [],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "panelcast content"}]},
    },
    {
        "path": "/story/timeline/",
        "name": "Story · timeline",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/timeline"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "timeline content"}]},
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
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [{"selector": "[data-readout]", "not_empty": True, "desc": "method readout rendered"}],
        },
    },
    {
        "path": "/method/game/",
        "name": "Method · the game, explained (GENERATED — v4_build_game_explained.py)",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": [],
        "visual": {
            "checks": [
                {"selector": "main, article", "not_empty": True, "desc": "game explainer content"},
                {"selector": ".gx-pillar", "min_count": 7, "desc": "7 pillar cards rendered"},
            ]
        },
    },
    {
        "path": "/method/registry/",
        "name": "Method · methods registry",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": [],
        "visual": {
            "checks": [
                {"selector": "main, article", "not_empty": True, "desc": "methods registry content"},
                {"selector": ".mr-stat", "min_count": 1, "desc": "registry stat entries rendered"},
            ]
        },
    },
    # ── Coaching door (promoted 2026-06-20) ──────────────────────────────────
    {
        "path": "/coaching/",
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
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
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
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
        # #1441: the base (fragmentless) page needs its own visual def — the
        # ai_surface screenshot archive uploads qa-screenshots/{slug}.png, and
        # only pages with a `visual` def get a base-slug screenshot (the two
        # deep-link variants above save under fragment-suffixed names). The page
        # auto-selects the first roster coach when no fragment is given
        # (coaching.js selectSection: initId = entries[0].id), so the default
        # read renders without a hash.
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "by-coach default read rendered (first roster coach)"}],
        },
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
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
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
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "team roster/profile rendered (legacy slug)"}],
        },
    },
    {
        "path": "/coaching/qa/",
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
        "name": "Coaching · Reader Q&A",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "reader Q&A content rendered"}],
        },
    },
    {
        "path": "/coaching/read/",
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
        "name": "Coaching · The Read",
        "tier": 3,
        "content_class": "narrative",
        "api_deps": [],
        "js_modules": ["coaching.js"],
        "visual": {
            "wait_for": "[data-dx-read]",
            "checks": [{"selector": "[data-dx-read]", "not_empty": True, "desc": "the-read content rendered"}],
        },
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
        "visual": {
            "checks": [
                {"selector": "main, article", "not_empty": True, "desc": "gear content"},
                {"selector": ".gr-card", "min_count": 1, "desc": "gear cards rendered"},
            ]
        },
        "structural": {"marker": 'class="gr-card"'},
    },
    {
        "path": "/journal/essays/org-chart-of-one/",
        "name": "Essay · The Org Chart of One",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": {"checks": [{"selector": "main, article, .post-body", "not_empty": True, "desc": "essay content"}]},
        "structural": {"marker": 'class="post-header__title"'},
    },
    {
        "path": "/privacy/",
        "name": "Privacy",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": {"checks": [{"selector": "main, article", "not_empty": True, "desc": "privacy policy content"}]},
        "structural": {"marker": 'class="policy-title"'},
    },
    {
        "path": "/subscribe/",
        "name": "Subscribe",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "visual": {"checks": [{"selector": "main, article", "not_empty": True, "desc": "subscribe page content"}]},
        "structural": {"marker": 'class="sub-title"'},
    },
    {
        "path": "/subscribe/confirm/",
        "name": "Subscribe · confirm",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        # Real content (JS renders a confirmed/expired/check-your-inbox state from
        # the ?confirmed=/?error= query params — default state with no params is
        # "Check your inbox"), so it earns a check despite tier-4 (#1427).
        "visual": {"checks": [{"selector": "#cc-title, main", "not_empty": True, "desc": "confirm-state message rendered"}]},
        "structural": {"marker": 'id="cc-title"'},
    },
    {
        "path": "/404.html",
        "name": "404 page (direct object)",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        # Error page — status-only is the right coverage (smoke already verifies the
        # 200 on direct S3 fetch); no meaningful render behavior to check (#1427).
        "visual": None,
        # #1429: assert the body CloudFront actually serves on a missing path (it
        # arrives with HTTP status 404 — the structural check reads the body and
        # never requires a 200; the status itself is asserted by the existing
        # nonexistent-page check in smoke_test_site.sh).
        "structural": {"marker": '<h1 class="nf-h">404</h1>', "fetch_path": "/nonexistent-page-xyz/"},
    },
    {
        "path": "/subscribe.html",
        "name": "Legacy /subscribe.html (meta-refresh stub → /subscribe/)",
        "tier": 4,
        "content_class": "utility",
        "api_deps": [],
        "js_modules": [],
        "leak_scan": False,
        # Pure meta-refresh redirect stub — no content to check; the target page
        # (/subscribe/) is visually swept directly (#1427).
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
    """tests/visual_qa.py PAGES — order-stable, identical to pre-#1426 coverage.

    Each entry carries `tier` (from its parent manifest entry, #1428) so the
    sweep can restrict the AI-vision layer to a tier subset (deploy-time =
    tier 1 only) without touching which pages the deterministic Playwright
    checks cover — that stays the full set, unchanged.
    """
    out = []
    for p in MANIFEST:
        if p.get("visual"):
            d = dict(p["visual"])
            d["path"] = p["path"]
            d["name"] = p["name"]
            d["tier"] = p["tier"]
            out.append(d)
        for var in p.get("visual_variants", []) or []:
            d = dict(var)
            d["path"] = p["path"] + d.pop("fragment", "")
            d["tier"] = p["tier"]
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


def ai_screenshot_slugs():
    """#1441 — the visual_qa screenshot slugs of every ai_surface page. The
    standalone visual-qa workflow uploads qa-screenshots/{slug}.png for each to
    generated/qa_archive/screenshots/{date}/ (the screenshot leg of the AI
    archive). Slug rule mirrors tests/visual_qa.py capture_page exactly."""
    return [(p["path"].strip("/").replace("/", "-") or "home") for p in MANIFEST if p.get("ai_surface")]


# #1429: the static long-tail = every real 200 page of these classes. Redirect
# stubs (smoke != 200, or leak_scan=False meta-refresh shells) have no body of
# their own to assert.
STRUCTURAL_CLASSES = {"static", "utility"}


def _structural_eligible(p):
    return p["content_class"] in STRUCTURAL_CLASSES and p["smoke"] == "200" and p["leak_scan"]


def structural_rows():
    """deploy/smoke_test_site.sh — 'fetch_path|name|marker' for the static long-tail (#1429).

    The page LIST derives from content_class (never a hand list — the #1454
    surface-drift rule); the marker is per-page data declared in THE registry,
    like the visual defs. Every eligible page MUST declare one: a new static
    page landing without a structural marker raises here, which reds both the
    smoke's emit call and tests/test_smoke_structural.py — by design.
    """
    rows, missing = [], []
    for p in MANIFEST:
        if not _structural_eligible(p):
            continue
        s = p.get("structural") or {}
        if not s.get("marker"):
            missing.append(p["path"])
            continue
        rows.append(f"{s.get('fetch_path', p['path'])}|{p['name']}|{s['marker']}")
    if missing:
        raise AssertionError(f"static/utility pages missing a structural marker (#1429 — add structural= to the manifest entry): {missing}")
    return rows


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


def coverage_stats():
    """#1446: deterministic QA-coverage rollup for the Monday ops green report.

    Derived entirely from MANIFEST at call time — never a hand-maintained
    number (the acceptance criterion). Deliberately carries NO timestamp:
    deploy/build_bundle.py stages this payload into every Lambda bundle, and a
    timestamp would churn the CDK asset hash on every synth (forcing a
    spurious full-fleet update per deploy). Content changes only when the
    manifest itself changes.
    """
    by_tier: dict = {}
    for p in MANIFEST:
        k = f"tier{p['tier']}"
        by_tier[k] = by_tier.get(k, 0) + 1
    return {
        "source": "tests/qa_manifest.py (#1426)",
        "pages_total": len(MANIFEST),
        "pages_by_tier": dict(sorted(by_tier.items())),
        "visual_defs": len(visual_pages()),
        "pages_with_visual": sum(1 for p in MANIFEST if p.get("visual")),
        "static_core_pages": len(static_core_paths()),
        "leak_scan_pages": len(leak_scan_paths()),
        "smoke_pages": len(smoke_rows()),
        "api_endpoints_declared": len({d for p in MANIFEST for d in (p.get("api_deps") or [])}),
    }


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
    ap.add_argument("--emit", choices=["paths", "smoke", "leak", "static_core", "structural", "coverage", "ai-screens"])
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
    elif args.emit == "structural":
        for row in structural_rows():
            print(row)
    elif args.emit == "coverage":
        # sort_keys so the emitted bytes are deterministic (bundle-hash stability, #1446)
        print(json.dumps(coverage_stats(), indent=2, sort_keys=True))
    elif args.emit == "ai-screens":
        for s in ai_screenshot_slugs():
            print(s)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
