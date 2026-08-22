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
  leak_scan      include in the leak-token grep (default True for every real
                 HTML page; False only for pure redirects) — driven by
                 restart_verify_rendered.py at reset time AND by the daily
                 tests/visual_qa.py sweep (#1448; both share tests/leak_token_sweep.py)
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
    python3 tests/qa_manifest.py --emit api_deps    # distinct union of every declared api_dep (#1586)
    python3 tests/qa_manifest.py --emit api_sweep   # router-derived long-tail rows 'route|fetch|status' (#2652)
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
        if "external" in flags:
            # #1392: a curated page that keeps its archive tile — it registers its own
            # _CURATED manifest entry (with its real js_modules/visual checks); deriving
            # an archive row here would both duplicate the path and lie about the page.
            continue
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
        # CLS paydown (#1474): the archive shell now paints its crumb/title/blurb +
        # a designed readout skeleton server-side and reserves the tabs + Day-N-stamp
        # lines, so the async fill no longer shifts layout. Measured before→after
        # (route-mocked, 1280px): /data topics 0.46→0.0 (returning) / 0.14 (first
        # visit — the one-time data-door intro card); /method,/protocols ~0.0. The
        # data door carries that first-visit intro card, so it keeps more headroom
        # than the intro-less method/protocols doors. These lock the gain; the global
        # CLS_BUDGET (0.75) still covers pages not yet reworked.
        "cls_budget": 0.30 if path.startswith("/data/") else 0.15,
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


# #1566: the "In my own words" essay permalink pages are GENERATED from
# site/journal/blog.json by scripts/v4_build_journal.py — so the QA registry
# derives one static entry per essay from that same manifest, exactly the way
# _archive_entries() derives from the evidence build registry. An essay now
# registers ONCE (its blog.json entry); smoke/visual/structural derive here.
# This kills the "new essay = hand-add a qa_manifest row" trap that shipped
# alongside the old hand-HTML step.
def _essay_rows():
    blog = os.path.join(_REPO, "site", "journal", "blog.json")
    try:
        with open(blog, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for p in data.get("posts", []):
        url = p.get("url")
        if not (url and p.get("title") and p.get("date")):
            continue
        out.append(
            {
                "path": url,
                "name": f"Essay · {p['title']}",
                "tier": 3,
                "content_class": "static",
                "api_deps": [],
                "js_modules": [],
                "visual": {"checks": [{"selector": "main, article, .post-body", "not_empty": True, "desc": "essay content"}]},
                # The generated permalink page always carries the essay title in an
                # <h1 class="post-header__title"> — the stable structural anchor.
                "structural": {"marker": 'class="post-header__title"'},
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
        # /api/journal_quotes (#1568): the weekly featured line — the beat is dormant
        # (hidden) without a featured quote, but the endpoint must stay healthy.
        "api_deps": ["/api/journey", "/api/character", "/api/journal_quotes"],
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
        "api_deps": ["/api/timeline", "/api/content_cadence"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "chronicle content"}]},
    },
    {
        "path": "/story/journal/",
        "ai_surface": True,  # #1441: reader-visible AI narrative — daily screenshot archived
        "name": "Story · journal",
        "tier": 2,
        "content_class": "narrative",
        # /api/journal_quotes (#1568): the consent-per-line pull-quote archive — the
        # page renders it dormant-empty, but the endpoint itself must stay healthy.
        "api_deps": ["/journal/posts.json", "/api/journal_quotes"],
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
        # #1586: was declared as "/api/agents" (a route that never existed — a
        # stale/typo'd dep the new endpoint-health smoke leg caught immediately).
        # agents.js actually fetches the single real endpoint below.
        "api_deps": ["/api/agent_activity"],
        "js_modules": ["agents.js"],
        "visual": {"checks": [{"selector": "[data-roster], .agent-card, [data-feed]", "not_empty": True, "desc": "agent roster + feed"}]},
    },
    {
        "path": "/story/build/",
        "name": "Story · build dispatches",
        "tier": 3,
        "content_class": "narrative",
        # #2541: NOT fetched by the page — these two are the fork-me front door's LINK
        # TARGETS, declared here so the smoke's JSON-health leg (#1586) guards them.
        # The manifest was published with nothing on the site linking it; a front door
        # whose target 404s is worse than no front door, and only this leg would catch
        # that (the page renders fine either way).
        "api_deps": ["/data/stack.json", "/data/stack.schema.json"],
        "js_modules": ["story.js"],
        "visual": {
            "checks": [
                {"selector": "main, [data-readout], article", "not_empty": True, "desc": "build dispatches content"},
                # #2541: the fork-me front door itself. Selector is the LINK, not its
                # container — a card that renders with the manifest anchor dropped must
                # red here, so this cannot pass against a page missing the link.
                {
                    "selector": '.dx-subscribe a[href="/data/stack.json"]',
                    "not_empty": True,
                    "min_count": 1,
                    "desc": "fork-me front door → the stack manifest (#2541)",
                },
            ]
        },
    },
    {
        # #1399: the Remediation Agent's public track record. Static build-time page —
        # scripts/v4_build_agent_review.py bakes the computed track record (from the
        # remediation-log audit trail via remediation/track_record.py) into the HTML,
        # so there is NO /api dep and no autodeploy race. Re-run the builder to refresh.
        "path": "/story/build/agent-review/",
        "name": "Story · agent performance review (#1399)",
        "tier": 3,
        "content_class": "static",
        "api_deps": [],
        "js_modules": [],
        "structural": {"marker": 'class="ar-main"'},
        "visual": {"checks": [{"selector": ".ar-stats, .ar-case, .ar-empty", "not_empty": True, "desc": "agent track record"}]},
    },
    {
        "path": "/story/panel/",
        "name": "Story · panelcast",
        "tier": 3,
        "content_class": "narrative",
        # (The podcast has no independent cron — its cadence line rides the chronicle's.)
        "api_deps": ["/panelcast/episodes.json", "/api/content_cadence"],
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
        # #1672 (The Social Membrane, epic #1668): the Broadcast feed — facade cards of
        # Matthew's cleared, origin:human posts, from the read-only /api/broadcast.
        "path": "/story/broadcast/",
        "name": "Story · broadcast",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/broadcast"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "broadcast content"}]},
    },
    {
        # #1679 (The Social Membrane, epic #1668, S11): the bidirectional membrane —
        # what I said (the BROADCAST_ORIGIN# ledger) → where it went → what came back
        # (the same membrane gate /api/broadcast reads). Provenance counts only; the
        # sensitivity gate's held set is never published. Unlisted from the story tab
        # bar (linked from the Broadcast section), same posture as /story/build/.
        "path": "/story/membrane/",
        "name": "Story · membrane",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/membrane"],
        "js_modules": ["story.js"],
        "visual": {"checks": [{"selector": "main, [data-readout], article", "not_empty": True, "desc": "membrane content"}]},
    },
    {
        # #1707 (epic #1686 S3): Horizons — the Mind coach's weekly media picks + their
        # grounded retrospectives, on the DATA door near the reading shelf. From the
        # read-only /api/horizons; degrades to an honest empty/"note coming" state at low n.
        "path": "/data/horizons/",
        "name": "Data · horizons",
        "tier": 2,
        "content_class": "live-data",
        "api_deps": ["/api/horizons"],
        "js_modules": ["horizons.js"],
        "visual": {
            "wait_for": "[data-horizons]",
            "checks": [{"selector": "[data-horizons]", "not_empty": True, "desc": "horizons feed rendered (picks or honest empty state)"}],
        },
    },
    {
        # #1381 (epic #1364): the Theme River — evolving journal-enrichment themes across
        # the attempt, rendered as monochrome small-multiples. GENERATED —
        # scripts/v4_build_theme_river.py bakes the HTML + reads a STATIC artifact
        # (/data/theme_river.json), NOT a site-api /api endpoint — so NO api_deps and NO
        # autodeploy race. Honest empty/warming-up at low n (currently n=0 at genesis+days).
        "path": "/story/theme-river/",
        "name": "Story · the theme river (#1381)",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": [],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [
                {"selector": "[data-readout]", "not_empty": True, "desc": "theme river readout rendered (empty/warming-up/flowing)"},
            ],
        },
    },
    {
        # #1846: the consent-gated diary shelf — one card per Video Diary / Solo
        # Recording entry Matthew explicitly cleared, carrying only the lines he
        # marked publishable. LIVE-DATA (/api/diary_shelf, site_api_diary.py), so
        # the #1704 order holds: site-api must be deployed BEFORE this page's
        # site/** merge lands or the api_deps smoke leg 404s and auto-rollback
        # fires. The mount always resolves to real content — cards, an honest
        # "nothing published yet" line, or the fetch-failed line — so the visual
        # check is not_empty regardless of how much (if anything) is consented.
        "path": "/story/diary/",
        "name": "Story · the diary shelf (#1846)",
        "tier": 3,
        "content_class": "live-data",
        "api_deps": ["/api/diary_shelf"],
        "js_modules": ["diary_shelf.js"],
        "visual": {
            "wait_for": "[data-diary-shelf]",
            "checks": [
                {
                    "selector": "[data-diary-shelf]",
                    "not_empty": True,
                    "desc": "diary shelf rendered (cards or the honest nothing-published line)",
                },
            ],
        },
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
    {
        # #1390: the tone dial — three coach registers + their prompts published verbatim
        # (GENERATED — scripts/v4_build_tone.py from lambdas/coach_register.py).
        "path": "/method/tone/",
        "name": "Method · the tone dial",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": [],
        "visual": {
            "checks": [
                {"selector": "main, article", "not_empty": True, "desc": "tone dial content"},
                {"selector": ".td-card", "min_count": 3, "desc": "three register cards rendered"},
            ]
        },
    },
    {
        # #1390: the eyeball-calibration reliability chart (GENERATED — scripts/v4_build_eyeball.py).
        # Reads a STATIC generated artifact (/data/eyeball_calibration.json), NOT a site-api /api
        # endpoint — so it has no api_deps and no autodeploy race. Honest zero-state at n=0.
        "path": "/method/eyeball/",
        "name": "Method · how wrong is the AI at eyeballing food",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": [],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [
                {"selector": "[data-readout]", "not_empty": True, "desc": "eyeball reliability readout rendered (empty/low-n/reported)"},
            ],
        },
    },
    {
        # #1396: "grade your own LLM coach" — the calibration engine as an open artifact
        # (GENERATED — scripts/v4_build_grade_your_coach.py). Paste predictions+outcomes,
        # get the same scorecard the platform's coaches get. Computation is ENTIRELY
        # client-side (grade_your_coach.js -> calibration-core.js, a vendored copy of
        # oss/calibration-core/), so there is no /api endpoint and no autodeploy race; the
        # demo ledgers are a STATIC generated artifact (/data/calibration_demo.json).
        "path": "/method/grade-your-coach/",
        "name": "Method · grade your own LLM coach",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": ["grade_your_coach.js", "calibration-core.js"],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [
                {"selector": "[data-readout]", "not_empty": True, "desc": "scorecard readout rendered (scored or honest empty state)"},
                {"selector": "#gyc-input", "min_count": 1, "desc": "the paste box is present"},
            ],
        },
    },
    {
        # #1392: "The Mirror" — a reader's Whoop export scored on the platform's own
        # instruments, overlaid on Matthew's published distributions (GENERATED —
        # scripts/v4_build_mirror.py). Computation is ENTIRELY client-side
        # (mirror.js -> mirror-core.js, parity-pinned to the deployed Python by
        # tests/test_mirror_parity.py + tests/js/mirror_core.test.mjs); the page reads
        # ONE static artifact (/data/mirror_distributions.json), so no api_deps and no
        # autodeploy race. The reader's file never leaves the browser — structurally
        # enforced (exactly one fetch, no upload mechanisms).
        "path": "/method/mirror/",
        "name": "Method · The Mirror — your export on my instruments",
        "tier": 3,
        "content_class": "generated",
        "api_deps": [],
        "js_modules": ["mirror.js", "mirror-core.js", "mirror_demo.js", "calibration-core.js"],
        "visual": {
            "wait_for": "[data-readout]",
            "checks": [
                {"selector": "[data-readout]", "not_empty": True, "desc": "mirror readout rendered (scored or honest empty state)"},
                {"selector": "#mirror-drop", "min_count": 1, "desc": "the drop zone is present"},
                {"selector": ".mr-banner", "min_count": 1, "desc": "the calibrated-on-me banner is permanent"},
            ],
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
        # #1386: the Read tab also renders the Dispute Docket band (graceful-empty
        # until the first docket opens).
        "api_deps": ["/api/coaches", "/api/coach_team", "/api/coach_docket"],
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
                "fragment": "#physical_coach",  # v2 roster: the merged Performance seat (training retired 2026-08-10)
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
        # #1586: was declared as "/api/coach_track_records" (a route that never
        # existed — a stale/typo'd dep the new endpoint-health smoke leg caught
        # immediately). coaching.js's scorecard tab actually fetches /api/predictions.
        "api_deps": ["/api/predictions"],
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
    # NB: the essay permalink pages (/journal/essays/<slug>/) are NOT hand-listed
    # here — they derive from site/journal/blog.json via _essay_rows(), spliced in
    # by _build() (#1566). Add an essay by adding a blog.json entry, not a row here.
    {
        "path": "/privacy/",
        "name": "Privacy",
        "tier": 3,
        "content_class": "static",
        # #2574: the page carries the Permanence Contract's public terms and
        # reads the archive's live size/date/checksum from the two published
        # documents. Declared here so the smoke's api_deps JSON-health sweep is
        # the /archive/* coverage — #1400 deliberately left it out because the
        # nightly had never run; it has now.
        "api_deps": ["/archive/manifest.json", "/archive/continuity.json"],
        "js_modules": [],
        "visual": {
            "checks": [
                {"selector": "main, article", "not_empty": True, "desc": "privacy policy content"},
                {"selector": ".perm-clause", "min_count": 8, "desc": "the eight permanence clauses render"},
                {"selector": "#perm-live .pl-grid dd", "not_empty": True, "desc": "the live archive panel resolved"},
            ]
        },
        "structural": {"marker": 'class="perm-clauses"'},
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
        # Exemption reviewed 2026-07-20 (#1586 qa_audit coverage-drift ratchet) —
        # still holds: an error page has no interactive/data-bound content for
        # Playwright to assert beyond what the structural marker below already covers.
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
        # Exemption reviewed 2026-07-20 (#1586 qa_audit coverage-drift ratchet) —
        # still holds: a meta-refresh stub has nothing for Playwright to assert
        # before the browser hops away.
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
    pages = list(_CURATED) + _archive_entries() + _essay_rows()
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
            # The page's API deps ride along so the sweep can tell an honest
            # data-absence (the API itself is empty — genesis week) from a
            # broken render (#2500 rollback loop, 2026-08-10).
            d["api_deps"] = list(p.get("api_deps") or [])
            out.append(d)
        for var in p.get("visual_variants", []) or []:
            d = dict(var)
            d["path"] = p["path"] + d.pop("fragment", "")
            d["tier"] = p["tier"]
            d.setdefault("api_deps", list(p.get("api_deps") or []))
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


def api_dep_endpoints():
    """deploy/smoke_test_site.sh — the DISTINCT union of every page's declared
    api_deps (#1586). Pages declare the endpoints they render from, but until
    #1586 nothing asserted those endpoints' health directly — a dead dependency
    surfaced only as a blank page section (or not at all). This is the ONE list
    the smoke JSON-health sweep and scripts/qa_audit.py's coverage ratchet both
    read — one check per endpoint, never per page, so N pages sharing an
    endpoint cost one check, not N."""
    return sorted({d for p in MANIFEST for d in (p.get("api_deps") or [])})


# ── #2652 box 3: the live-route sweep facet ──────────────────────────────────
# Every /api route the router registers that no page declares as an api_dep gets
# a GENERIC probe: status + JSON shape (scripts/api_sweep_check.py, run by the
# smoke) and the numeric impossible-value scan (tests/accuracy_audit.py widens
# its denominator to these rows). The route LIST derives from
# deploy/endpoint_registry — the same AST walk sync_doc_metadata publishes the
# endpoint count from — so a new router route auto-enters the sweep the commit
# it lands, and hand-typing 69 entries here (the grandfathering this issue is
# about, wearing a different hat) never happens.
#
# Overrides are PER-ROUTE DATA, only where the generic 200-JSON probe is wrong,
# and each carries its written reason (the #2652 rule: swept, or a reason — no
# third state). Two shapes:
#   fetch    probe a different URL (prefix routes have no bare page: a naked
#            GET on the prefix 404s, which is not coverage)
#   expect   the status a healthy bare GET returns. Param-gated routes 400 by
#            design — the validator's structured JSON error IS the alive
#            signal; probing with real params would couple the sweep to data
#            (a roster id, an experiment id, a subscriber token).
# All expectations below were MEASURED against live 2026-08-22 before this
# sweep was allowed to gate (the 2026-07-17 lesson: never arm an unmeasured
# widened gate).
_API_SWEEP_OVERRIDES = {
    "/api/coach/": {
        "fetch": "/api/coach/eli_marsh",
        "expect": "200",
        "reason": "prefix route — a bare GET on the prefix is a 404 by design; probed via the head coach's "
        "detail route, the same representative instance the smoke's #1112 hand check pins.",
    },
    "/api/board_ask": {
        "expect": "405",
        "reason": "POST-only AI door served by site_api_ai_lambda — a DIFFERENT Lambda this router's AST walk "
        "never parses, so the write-door derivation cannot see its methods. A GET must 405; a POST would spend "
        "Bedrock tokens and a per-IP rate-limit slot on every sweep. The 405 probe proves routing + the method guard.",
    },
    "/api/changes-since": {
        "expect": "400",
        "reason": "param-gated (?ts= required): the validator's structured 400 is the alive signal; "
        "a real timestamp would make the probe's response window data-dependent.",
    },
    "/api/coach_timeline": {
        "expect": "400",
        "reason": "param-gated (?coach_id= required): the validator's structured 400 is the alive signal; "
        "a real coach_id would couple the probe to the live roster.",
    },
    "/api/experiment_detail": {
        "expect": "400",
        "reason": "param-gated (?id= required): the validator's structured 400 is the alive signal; "
        "a real id would couple the probe to the experiment library's contents.",
    },
    "/api/ritual_log": {
        "expect": "400",
        "reason": "param-gated (?metric= from a fixed whitelist required): the validator's structured 400 "
        "is the alive signal for the read side of the #769 evening-ritual route.",
    },
    "/api/social_context": {
        "expect": "400",
        "reason": "param-gated (?route= in {mind, training} required): the validator's structured 400 is " "the alive signal.",
    },
    "/api/verify_subscriber": {
        "expect": "400",
        "reason": "param-gated (valid ?email= + token required): the validator's structured 400 is the "
        "alive signal; a real verification token is a secret and single-use.",
    },
}


def api_sweep_records():
    """[{route, fetch, expect, reason}] — the #2652 generic sweep tier, DERIVED.

    route universe = deploy/endpoint_registry's /api walk, minus the two classes
    already adjudicated elsewhere:
      - POST-only write doors (scripts/qa_audit.py's derived out-of-scope class:
        a GET is a 405 and a POST would mutate real data on every deploy sweep)
      - manifest-declared api_deps (already swept: JSON health by the #1586
        smoke section, numeric scan by accuracy_audit)

    Raises on a prefix route without a probe override, and on a stale override
    (its route left the router, became an api_dep, or became a write door) —
    the structural_rows() precedent: adjudication is forced, never silent.
    """
    deploy_dir = os.path.join(_REPO, "deploy")
    if deploy_dir not in sys.path:
        sys.path.insert(0, deploy_dir)
    import endpoint_registry  # noqa: E402

    records = endpoint_registry.discover_endpoint_records()
    deps = set(api_dep_endpoints())
    out, missing_probe = [], []
    for path in sorted(records):
        if not path.startswith("/api/"):
            continue
        r = records[path]
        if r.methods and set(r.methods) <= {"POST"}:
            continue  # derived write door — carries its reason in qa_audit.OUT_OF_SCOPE_ROUTES
        if path in deps:
            continue  # already swept as a declared page dependency
        ov = _API_SWEEP_OVERRIDES.get(path, {})
        if r.is_prefix and not ov.get("fetch"):
            missing_probe.append(path)
            continue
        out.append(
            {
                "route": path,
                "fetch": ov.get("fetch", path),
                "expect": ov.get("expect", "200"),
                "reason": ov.get("reason", ""),
            }
        )
    if missing_probe:
        raise AssertionError(
            f"prefix /api routes need a probe override in _API_SWEEP_OVERRIDES "
            f"(#2652 — a bare GET on a prefix path 404s, which is not coverage): {missing_probe}"
        )
    swept_routes = {rec["route"] for rec in out}
    stale = sorted(p for p in _API_SWEEP_OVERRIDES if p not in swept_routes)
    if stale:
        raise AssertionError(
            f"stale _API_SWEEP_OVERRIDES entries — the route left the router, became a declared "
            f"api_dep, or became a POST-only write door; remove the override (#2652): {stale}"
        )
    return out


def api_sweep_rows():
    """scripts/api_sweep_check.py — 'route|fetch_path|expected_status' per row."""
    return [f"{r['route']}|{r['fetch']}|{r['expect']}" for r in api_sweep_records()]


def api_sweep_routes():
    """scripts/qa_audit.py's coverage ledger — the ROUTE names this sweep covers."""
    return [r["route"] for r in api_sweep_records()]


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
            # #1566: body.html is an essay AUTHORING FRAGMENT (the .prose source that
            # scripts/v4_build_journal.py renders into index.html), never a standalone
            # page — don't count it toward the page registry.
            if f in ("body.html", "body.md") and "journal/essays/" in (rel.replace(os.sep, "/") + "/"):
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
    ap.add_argument(
        "--emit", choices=["paths", "smoke", "leak", "static_core", "structural", "coverage", "ai-screens", "api_deps", "api_sweep"]
    )
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
    elif args.emit == "api_deps":
        for d in api_dep_endpoints():
            print(d)
    elif args.emit == "api_sweep":
        for row in api_sweep_rows():
            print(row)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
