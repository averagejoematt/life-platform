#!/usr/bin/env python3
"""
site_review_bindings.py — the page→endpoint binding map for the holistic site review.

Single source of truth for "which /api/* endpoints render the numbers on this page",
so the review (tests/site_review.py + the /site-review skill) can corroborate what a
page DISPLAYS against the data it's BUILT FROM, and cross-check the same metric across
pages that should agree.

Three sources are reconciled here (see the Plan-agent findings):
  • Evidence topic → PRIMARY endpoint is generated from scripts/v4_build_evidence.REGISTRY
    at import time, so it can never drift from the live build.
  • Evidence SECONDARY endpoints (a renderer pulls more than its primary) + the
    Cockpit/Story/Home bindings are hand-curated from the JS modules (cited inline).
  • `metrics` lists ONLY the JSON paths whose response shape has been VERIFIED live
    (journey / snapshot / character / pulse). The cross-page consistency check fires
    only for a canonical metric seen from ≥2 distinct endpoints, so under-claiming here
    is safe (no false positives); over-claiming an unverified path is not.

`metrics` entry shape: {"name": <canonical cross-page key>, "path": <dotted path in THIS
endpoint's JSON>}. The canonical name groups observations across endpoints; the path says
where to read it in each. NB: /api/snapshot double-nests (journey.journey.*,
character.character.*) — verified 2026-06-20.

No third-party deps. Importable by tests/site_review.py and (later) the Phase-2 Lambda.
Run directly for the drift self-check:  python3 tests/site_review_bindings.py
"""
from __future__ import annotations

import os
import re
import sys

# ── Per-metric agreement tolerance for the cross-page consistency check ───────
#   key = canonical metric name; value = max allowed abs delta between endpoints.
#   weight: same-day weigh-in rounding ≈ 0.1 lb. counts/levels: exact. ratios: 0.5pp.
METRIC_TOLERANCE = {
    "current_weight_lbs": 0.1,
    "weight_lbs": 0.1,
    "lost_lbs": 0.5,
    "progress_pct": 0.5,
    "level": 0.0,
    "day_number": 0.0,
}


# ── Evidence primary endpoints, generated from the live build registry ────────
def _evidence_primary():
    """slug -> primary endpoint, for data-mode evidence topics (from REGISTRY)."""
    here = os.path.dirname(os.path.abspath(__file__))
    scripts = os.path.join(here, "..", "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import v4_build_evidence as v  # noqa: E402

    out = {}
    for row in v.REGISTRY:
        slug, mode, endpoint = row[0], row[4], row[5]
        if mode == "data" and endpoint:
            out[slug] = endpoint
    return out


EVIDENCE_PRIMARY = _evidence_primary()

# Secondary endpoints an evidence renderer fetches BEYOND its primary
# (hand-curated from site/assets/js/evidence.js renderers; cite the renderer).
EVIDENCE_SECONDARY = {
    "physical": ["/api/weight_progress", "/api/journey"],  # evidence.js:renderPhysical
    "training": ["/api/strength_benchmarks", "/api/weekly_physical_summary", "/api/workouts"],  # renderTraining
    "sleep": ["/api/circadian", "/api/sleep_reconciliation"],  # renderSleep
    "glucose": ["/api/meal_glucose", "/api/meal_responses"],  # renderGlucose
    "nutrition": ["/api/frequent_meals", "/api/protein_sources"],  # renderNutrition
    "habits": ["/api/habit_registry"],  # renderHabits
}

# Story intent per evidence topic — "what is this topic FOR" (the discoverer/skeptic door).
_EVIDENCE_INTENT = {
    "vitals": "today's body at a glance — the honest pulse",
    "physical": "the composition the scale hides — fat vs lean, biological age",
    "labs": "the inside view wearables can't see — 153 biomarkers over time",
    "glucose": "what food actually does to him — CGM married to meals",
    "sleep": "the recovery the training is borrowing against",
    "training": "the work going in — volume, zone-2, strength",
    "nutrition": "the deficit, honestly — calories, protein, adherence",
    "habits": "the small daily behaviours that compound",
    "board": "the AI team's current read — priority, actions, predictions",
    "pipeline": "does the data even arrive — source freshness, nothing hidden",
    "intelligence": "what the machine has discovered — FDR-corrected correlations",
    "predictions": "calls on the record — falsifiable, scored later",
    "benchmarks": "him vs age-band and centenarian targets",
}

# ── The binding map ───────────────────────────────────────────────────────────
# Order = the narrative walk order the skill uses. door ∈ {home,cockpit,story,evidence}.
PAGE_BINDINGS = [
    {
        "path": "/",
        "name": "Home (constellation)",
        "door": "home",
        "narrative_order": 1,
        "story_intent": "the hook: an ordinary life, rebuilt with AI, measured in public",
        "endpoints": [  # site/assets/js/story.js header
            {
                "url": "/api/journey",
                "role": "primary",
                "metrics": [
                    {"name": "current_weight_lbs", "path": "journey.current_weight_lbs"},
                    {"name": "lost_lbs", "path": "journey.lost_lbs"},
                    {"name": "progress_pct", "path": "journey.progress_pct"},
                ],
            },
            {"url": "/api/character", "role": "primary", "metrics": [{"name": "level", "path": "character.level"}]},
            {"url": "/api/journey_waveform", "role": "secondary", "metrics": []},
            {"url": "/api/field_notes", "role": "secondary", "metrics": []},
            {"url": "/public_stats.json", "role": "secondary", "metrics": []},
        ],
    },
    {
        "path": "/now/",
        "name": "Cockpit",
        "door": "cockpit",
        "narrative_order": 2,
        "story_intent": "am I winning, and what is the one thing right now (the daily tool)",
        "endpoints": [  # site/assets/js/cockpit.js header + scope reads
            {
                "url": "/api/snapshot",
                "role": "primary",
                "metrics": [
                    {"name": "current_weight_lbs", "path": "journey.journey.current_weight_lbs"},
                    {"name": "lost_lbs", "path": "journey.journey.lost_lbs"},
                    {"name": "progress_pct", "path": "journey.journey.progress_pct"},
                    {"name": "level", "path": "character.character.level"},
                ],
            },
            {"url": "/api/weekly_priority", "role": "primary", "metrics": []},
            {"url": "/api/circadian", "role": "secondary", "metrics": []},
            {"url": "/api/journey_timeline", "role": "secondary", "metrics": []},
            {"url": "/api/achievements", "role": "secondary", "metrics": []},
            {"url": "/api/coach_analysis?domain=sleep", "role": "lazy", "metrics": []},  # disclosure
            {"url": "/api/observatory_week?domain=sleep", "role": "lazy", "metrics": []},  # week scope
            # Since-your-last-visit strip (2026-07-02): fetched only for a returning
            # visitor with a >=12h localStorage gap — conditional, so "lazy".
            {"url": "/api/changes-since", "role": "lazy", "metrics": []},
        ],
    },
    {
        "path": "/story/",
        "name": "Story hub",
        "door": "story",
        "narrative_order": 3,
        "story_intent": "the honest arc — chronicle, lab notes, coaches, panel, journal",
        "endpoints": [  # site/assets/js/dispatches.js SECTIONS
            {"url": "/chronicle/posts.json", "role": "primary", "metrics": []},
            {"url": "/api/field_notes", "role": "primary", "metrics": []},
            {"url": "/api/coaches", "role": "primary", "metrics": []},
            {"url": "/panelcast/episodes.json", "role": "secondary", "metrics": []},
            {"url": "/journal/posts.json", "role": "secondary", "metrics": []},
            {"url": "/api/journey_timeline", "role": "secondary", "metrics": []},
        ],
    },
    {
        "path": "/story/chronicle/",
        "name": "Story · chronicle",
        "door": "story",
        "narrative_order": 4,
        "story_intent": "the weekly essay — Elena Voss narrates the week",
        "endpoints": [{"url": "/chronicle/posts.json", "role": "primary", "metrics": []}],
    },
    {
        "path": "/story/journal/",
        "name": "Story · journal",
        "door": "story",
        "narrative_order": 5,
        "story_intent": "in his own words — the unmediated daily voice",
        "endpoints": [{"url": "/journal/posts.json", "role": "primary", "metrics": []}],
    },
    {
        "path": "/story/about/",
        "name": "Story · about",
        "door": "story",
        "narrative_order": 6,
        "story_intent": "who this is and why — the premise and the promise",
        "endpoints": [],  # editorial
    },
    # Door 4 "The Coaching" (/coaching/) — promoted out of Story (2026-06-20). narrative_order
    # keeps it story-adjacent (7.x via 71-73 to avoid renumbering the evidence block at 10-22).
    {
        "path": "/coaching/",
        "name": "Coaching · The Read (default)",
        "door": "coaching",
        "narrative_order": 71,
        "story_intent": "what the AI board is saying about you right now — the priority, the disagreements, each coach's live read",
        "endpoints": [
            {"url": "/api/coaching-dashboard", "role": "primary", "metrics": []},
            {"url": "/api/coach_team", "role": "primary", "metrics": []},
            {"url": "/api/weekly_priority", "role": "secondary", "metrics": []},
        ],
    },
    {
        "path": "/coaching/by-coach/#training_coach",
        "name": "Coaching · By Coach (read-on-data, deep-link)",
        "door": "coaching",
        "narrative_order": 72,
        "story_intent": "a coach's read sitting on top of the actual domain data — cardio/lifts/volume this week",
        "endpoints": [
            {"url": "/api/coach/training_coach", "role": "primary", "metrics": []},
            {"url": "/api/coach_analysis?domain=training", "role": "primary", "metrics": []},
            {"url": "/api/observatory_week?domain=training", "role": "secondary", "metrics": []},
        ],
    },
    {
        "path": "/coaching/scorecard/",
        "name": "Coaching · Scorecard (graded track record)",
        "door": "coaching",
        "narrative_order": 72.3,
        "story_intent": "the board's falsifiable record — every coach call graded confirmed/refuted/open by the evaluator",
        "endpoints": [{"url": "/api/predictions", "role": "primary", "metrics": []}],
    },
    {
        "path": "/coaching/team/",
        "name": "Coaching · The Team (roster/config)",
        "door": "coaching",
        "narrative_order": 72.5,
        "story_intent": "who the coaches are — personalities, voice, how each is built (reference)",
        "endpoints": [{"url": "/api/coaches", "role": "primary", "metrics": []}],
    },
    {
        "path": "/coaching/lab-notes/",
        "name": "Coaching · AI lab notes",
        "door": "coaching",
        "narrative_order": 73,
        "story_intent": "the Third Wall — the AI's weekly read against Matthew's response",
        "endpoints": [{"url": "/api/field_notes", "role": "primary", "metrics": []}],
    },
    {
        "path": "/data/",
        "name": "Evidence hub",
        "door": "evidence",
        "narrative_order": 9,
        "story_intent": "the browsable archive — does the data hold up, can you copy it",
        "endpoints": [],  # the hub itself is a shell; topics carry the data
    },
]


def _build_evidence_bindings():
    """Append a binding for each evidence topic the visual_qa sweep covers.

    Kept in lockstep with visual_qa.EVIDENCE_TOPICS so coverage matches the
    screenshots; primary endpoint comes from REGISTRY, secondary from the
    hand-curated map above.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import visual_qa  # noqa: E402

    order = 10
    for base, door, topics in (
        ("/data", "evidence", visual_qa.EVIDENCE_TOPICS),
        ("/method", "method", visual_qa.METHOD_TOPICS),
    ):
        for slug in topics:
            endpoints = []
            primary = EVIDENCE_PRIMARY.get(slug)
            if primary:
                endpoints.append({"url": primary, "role": "primary", "metrics": []})
            for sec in EVIDENCE_SECONDARY.get(slug, []):
                endpoints.append({"url": sec, "role": "secondary", "metrics": []})
            PAGE_BINDINGS.append(
                {
                    "path": f"{base}/{slug}/",
                    "name": f"{'Evidence' if door == 'evidence' else 'Method'} · {slug}",
                    "door": door,
                    "narrative_order": order,
                    "story_intent": _EVIDENCE_INTENT.get(slug, f"the {slug} evidence"),
                    "endpoints": endpoints,
                }
            )
            order += 1


# v5 pillars the visual_qa sweep covers beyond the /data/ topics: the Protocols hub
# and the Method character explainer (door-coverage for protocols + method).
PAGE_BINDINGS.append(
    {
        "path": "/protocols/",
        "name": "The Protocols",
        "door": "protocols",
        "narrative_order": 80,
        "story_intent": "the levers — what gets changed to move the data",
        "endpoints": [{"url": "/api/supplements", "role": "primary", "metrics": []}],
    }
)
PAGE_BINDINGS.append(
    {
        "path": "/method/character/",
        "name": "Method · the character",
        "door": "method",
        "narrative_order": 81,
        "story_intent": "what the character level means — 7 pillars, 100 levels, 5 tiers",
        "endpoints": [],
    }
)
# S2 protocols uplevel (2026-07): the three upleveled topic pages joined visual_qa.PAGES.
PAGE_BINDINGS.append(
    {
        "path": "/protocols/experiments/",
        "name": "Protocols · experiments",
        "door": "protocols",
        "narrative_order": 83,
        "story_intent": "the N=1 instrument — the program arc, running progress, effect-size receipts",
        "endpoints": [
            {"url": "/api/experiments", "role": "primary", "metrics": []},
            {"url": "/api/experiment_synthesis", "role": "secondary", "metrics": []},
        ],
    }
)
PAGE_BINDINGS.append(
    {
        "path": "/protocols/challenges/",
        "name": "Protocols · challenges",
        "door": "protocols",
        "narrative_order": 84,
        "story_intent": "time-boxed challenges — the check-in grid, evidence, XP earned",
        "endpoints": [{"url": "/api/challenges", "role": "primary", "metrics": []}],
    }
)
PAGE_BINDINGS.append(
    {
        "path": "/protocols/supplements/",
        "name": "Protocols · supplements",
        "door": "protocols",
        "narrative_order": 85,
        "story_intent": "what's taken vs what's swallowed — evidence, adherence, the dissent",
        "endpoints": [{"url": "/api/supplements", "role": "primary", "metrics": []}],
    }
)
PAGE_BINDINGS.append(
    {
        "path": "/mind/",
        "name": "Mind · the reading shelf (ADR-097)",
        "door": "mind",
        "narrative_order": 82,
        "story_intent": "becoming a reader, measured by what he kept — the shelf, the roundedness, the habit",
        "endpoints": [
            {"url": "/api/reading_shelf", "role": "primary", "metrics": []},
            {"url": "/api/reading_overview", "role": "primary", "metrics": []},
        ],
    }
)

_build_evidence_bindings()


# ── Helpers ───────────────────────────────────────────────────────────────────
def bindings_for(path):
    """Return the binding record for a page path, or None."""
    for b in PAGE_BINDINGS:
        if b["path"] == path:
            return b
    return None


def all_endpoints():
    """Deduped list of every bound endpoint URL across all pages (stable order)."""
    seen, out = set(), []
    for b in PAGE_BINDINGS:
        for ep in b["endpoints"]:
            if ep["url"] not in seen:
                seen.add(ep["url"])
                out.append(ep["url"])
    return out


def metric_observations():
    """Map canonical metric name -> list of (page_path, endpoint_url, json_path).

    The plan for the consistency check: load each endpoint's captured JSON, read
    each declared path, and compare values for any metric seen from ≥2 endpoints.
    """
    obs = {}
    for b in PAGE_BINDINGS:
        for ep in b["endpoints"]:
            for m in ep.get("metrics", []):
                obs.setdefault(m["name"], []).append((b["path"], ep["url"], m["path"]))
    return obs


# ── Coverage guard: new doors must not silently escape the review ────────────────
# First path segment of a public route → its door.
_SEGMENT_TO_DOOR = {"": "home", "now": "cockpit", "story": "story", "coaching": "coaching", "evidence": "evidence"}


def _sitemap_routes():
    """Public route paths from the generated sitemap — the authoritative indexable-page list."""
    here = os.path.dirname(os.path.abspath(__file__))
    sm = os.path.join(here, "..", "site", "sitemap.xml")
    if not os.path.exists(sm):
        return []
    with open(sm, encoding="utf-8") as f:
        txt = f.read()
    routes = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", txt):
        m = re.match(r"https?://[^/]+(/.*)?$", loc.strip())
        routes.append(m.group(1) if (m and m.group(1)) else "/")
    return routes


def coverage_gaps():
    """Top-level doors that have public pages in the sitemap but NO PAGE_BINDINGS coverage.

    The door-level safety net: catches a whole new section/door shipped without QA
    registration (the /coaching/ blind spot, 2026-06-20). Per-page gaps inside the
    curated Evidence-topic subset are intentional and NOT flagged here.
    """
    bound_doors = {b["door"] for b in PAGE_BINDINGS}
    seen = set()
    for r in _sitemap_routes():
        seg = r.strip("/").split("/")[0] if r.strip("/") else ""
        door = _SEGMENT_TO_DOOR.get(seg)
        if door:
            seen.add(door)
    return sorted(seen - bound_doors)


# ── Drift self-check ────────────────────────────────────────────────────────────
def selfcheck():
    """Assert the binding map stays in sync with visual_qa.PAGES and REGISTRY.

    Returns (ok: bool, problems: list[str]). Run in __main__ and in the test suite.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import visual_qa  # noqa: E402

    problems = []
    bound_paths = {b["path"] for b in PAGE_BINDINGS}
    for pg in visual_qa.PAGES:
        if pg["path"] not in bound_paths:
            problems.append(f"PAGES path {pg['path']!r} has no PAGE_BINDINGS entry")

    # every evidence primary must equal the live REGISTRY endpoint
    for b in PAGE_BINDINGS:
        if b["door"] != "evidence" or b["path"] == "/data/":
            continue
        slug = b["path"].strip("/").split("/")[-1]
        want = EVIDENCE_PRIMARY.get(slug)
        got = next((e["url"] for e in b["endpoints"] if e["role"] == "primary"), None)
        if want and got != want:
            problems.append(f"evidence/{slug}: primary {got!r} != REGISTRY {want!r}")

    # narrative_order must be unique
    orders = [b["narrative_order"] for b in PAGE_BINDINGS]
    if len(orders) != len(set(orders)):
        problems.append("narrative_order values are not unique")

    # coverage: a new top-level door in the sitemap with no bindings is a blind spot
    for door in coverage_gaps():
        problems.append(
            f"sitemap has '{door}'-door pages but no PAGE_BINDINGS cover that door — " f"register them in visual_qa.PAGES + PAGE_BINDINGS"
        )

    return (not problems, problems)


if __name__ == "__main__":
    ok, problems = selfcheck()
    print(f"site_review_bindings: {len(PAGE_BINDINGS)} pages, {len(all_endpoints())} unique endpoints")
    print(f"cross-page metrics tracked: {sorted(metric_observations())}")
    if ok:
        print("✅ selfcheck passed — bindings in sync with visual_qa.PAGES and REGISTRY")
    else:
        print("❌ selfcheck FAILED:")
        for p in problems:
            print(f"   - {p}")
        sys.exit(1)
