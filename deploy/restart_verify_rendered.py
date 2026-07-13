#!/usr/bin/env python3
"""
restart_verify_rendered.py — Public-URL fetch + token-grep verification.

Different from restart_verify.py (which checks backend state — constants,
configs, DDB, API). This one fetches the actual rendered HTML/JSON the public
gets, and greps for forbidden tokens that signal pre-genesis leakage.

The institutional memory for ADR-058: the launch-eve audit showed that
clean constants + clean DDB + clean API can still produce a stale-looking
site if any of (a) hardcoded client JS, (b) cached S3 JSON, (c) missed DDB
partitions leaks through. This script catches that class of bug.

Exit code 0 if all checks pass; 1 otherwise.

Usage:
    python3 deploy/restart_verify_rendered.py [--old-genesis YYYY-MM-DD]
"""
import argparse
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

BASE = "https://averagejoematt.com"

# Pages to fetch and inspect — the v4 "Measured Life" surface (ADR-071), aligned
# with tests/visual_qa.py PAGES + scripts/v4_build_sitemap.py. The previous list
# here was the PRE-v4 page map (all of it 301s now), so the token grep ran
# against redirect targets it didn't intend (2026-07-10 clean-sweep audit).
PAGES = [
    "/",
    "/cockpit/",
    "/story/",
    "/story/chronicle/",
    "/story/journal/",
    "/story/about/",
    "/story/agents/",
    "/data/",
    # /data/ Evidence topics (tests/visual_qa.py EVIDENCE_TOPICS)
    "/data/vitals/",
    "/data/physical/",
    "/data/labs/",
    "/data/glucose/",
    "/data/sleep/",
    "/data/training/",
    "/data/nutrition/",
    "/data/habits/",
    "/data/character/",
    # /method/ door (visual_qa METHOD_TOPICS + the character explainer)
    "/method/character/",
    "/method/board/",
    "/method/pipeline/",
    "/method/intelligence/",
    "/method/predictions/",
    "/method/scenarios/",
    "/method/benchmarks/",
    # /protocols/ door
    "/protocols/",
    "/protocols/experiments/",
    "/protocols/challenges/",
    "/protocols/supplements/",
    # /coaching/ door
    "/coaching/",
    "/coaching/by-coach/",
    "/coaching/scorecard/",
    "/coaching/team/",
    "/coaching/lab-notes/",
]

# JSON endpoints to fetch and inspect for stale fields. cycle_compare must show
# the NEW cycle; the two feed indexes must not carry prior-cycle entries.
JSON_ENDPOINTS = [
    "/api/journey",
    "/api/vitals",
    "/api/character",
    "/api/timeline",
    "/api/cycle_compare",
    "/panelcast/episodes.json",
    "/journal/posts.json",
]

# Forbidden patterns. Each entry: (label, regex, allowed-on which path or '*').
# 'allowed' means we SKIP the check for paths matching that prefix
# (e.g., the /chronicle/sample page is allowed to show "Day 1 · April 2026"
# as illustrative copy if needed).
FORBIDDEN_TOKENS = [
    # Day-N counters showing >30 — wrong on Day 1 of restart
    ("Day-30+ counter", re.compile(r"\bDay\s+(?:[3-9][0-9]|[1-9][0-9]{2,})\b"), []),
    # Old baseline weight
    ("Old baseline (307)", re.compile(r"\b307\s*(?:lbs?|pounds|→|to\s+\d{3})"), []),
    # Cycle-1 genesis literal (the original launch date; kept as a static token —
    # the OUTGOING genesis for the current reset is appended dynamically from
    # --old-genesis in main()). The cycle-compare + timeline APIs legitimately
    # list every past genesis (CYCLE_GENESES is their whole point).
    ("Cycle-1 genesis literal", re.compile(r"\b2026-04-01\b"), ["/api/cycle_compare", "/api/timeline"]),
    # Error sentinel value
    ("999.0 sentinel", re.compile(r"\b999\.0\b"), []),
    # Earned achievements / milestones (pre-genesis state leak)
    (
        "Earned milestone",
        re.compile(r"(Hot Streak|Lab Rat|First Experiment|First Week)" r"[^<>]{0,80}(earned|achieved|completed|unlocked)"),
        [],
    ),
    # Character level above 3 — only flag in CURRENT-state English prose
    # ("Character Level 25", "Level: 25", "is at Level 25"). Excludes:
    #   - structural copy: "Reached Level 5", "reaching Level 80 means something"
    #   - JSON/JS variable names: level:21, min_level:1, next_tier_level:21
    # Requires a word-boundary "Level" (capital L) followed by space+digit.
    ("Character level 4+", re.compile(r"(?:Character Level|Level:\s|is at Level\s|currently at Level\s)(?:[4-9]|[1-9][0-9]+)\b"), []),
    # Past-week recap headers. Only flag when "Week N" appears in a header/title
    # context (followed by " — " or " of <year>") indicating it's an actual
    # weekly entry header. Excludes chart labels like "Week 13+: Integration"
    # and descriptive copy.
    (
        "Past week recap (Week 10+)",
        re.compile(r"\bWeek\s+(?:[1-9][0-9]+)\s+(?:—|of\s+20\d\d|recap|in\s+review)\b"),
        [
            "/chronicle/",
        ],
    ),
    # Tombstone JSON leaking to the public (would mean a tombstoned record made it through)
    ("Tombstone leak", re.compile(r'"tombstone"\s*:\s*true'), []),
]


def fetch(url: str) -> tuple[int, str]:
    """Fetch a URL, return (status_code, body). Returns (0, '') on network error.

    Reads the body even on HTTPError — callers may need to inspect the error
    payload (e.g., '/api/character' returns 503 with a 'not yet computed' body
    that the verifier accepts as expected pre-compute state).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "restart-verify-rendered/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        print(f"  [fetch error] {url}: {e}")
        return 0, ""


def check_body(path: str, body: str) -> list[tuple[str, list[str]]]:
    """Return list of (token_label, matches) for any forbidden token that hit."""
    hits = []
    for label, regex, allowed_prefixes in FORBIDDEN_TOKENS:
        if any(path.startswith(p) for p in allowed_prefixes):
            continue
        matches = regex.findall(body)
        if matches:
            # Sample at most 3 matches per token for the report
            sample = [str(m)[:80] for m in matches[:3]]
            hits.append((label, sample))
    return hits


def _old_genesis_tokens(old_genesis: str) -> list:
    """Dynamic forbidden tokens for the OUTGOING genesis: the ISO literal plus its
    short prose forms ('June 14' / 'Jun 14') — the forms the JS sweep rewrites."""
    from datetime import date as _d

    if not old_genesis or old_genesis == EXPERIMENT_START_DATE:
        return []
    o = _d.fromisoformat(old_genesis)
    # cycle_compare / timeline legitimately list every past genesis (ISO only).
    iso_allowed = ["/api/cycle_compare", "/api/timeline"]
    tokens = [
        (f"Outgoing genesis prose ({o.strftime('%B')} {o.day})", re.compile(rf"\b{o.strftime('%B')}\s+{o.day}\b"), []),
        (f"Outgoing genesis prose ({o.strftime('%b')} {o.day})", re.compile(rf"\b{o.strftime('%b')}\s+{o.day}\b(?![a-zA-Z])"), []),
    ]
    # Future-genesis reset (#1188): when the NEW genesis is still ahead of us, the
    # OUTGOING genesis equals today's real date — so every legitimate freshness stamp
    # ('as of 2026-07-12', '"night_of": "2026-07-12"', ISO dates in /api/* payloads)
    # is that literal. The ISO token is then indistinguishable from live data, so we
    # waive it (logged) and rely on the prose forms to catch a genuine chronicle leak.
    if old_genesis == _d.today().isoformat():
        print(
            f"  ⚠ outgoing genesis {old_genesis} == today (future-genesis reset) — ISO-literal token WAIVED (collides with live freshness data)"
        )
        return tokens
    return [
        (f"Outgoing genesis literal ({old_genesis})", re.compile(rf"\b{re.escape(old_genesis)}\b"), iso_allowed),
        *tokens,
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-genesis",
        default=None,
        help="The OUTGOING genesis (YYYY-MM-DD) — its ISO + prose forms become forbidden tokens. Passed by restart_pipeline.",
    )
    args = parser.parse_args()
    FORBIDDEN_TOKENS.extend(_old_genesis_tokens(args.old_genesis))

    print(f"\nrestart_verify_rendered — checking public surfaces against genesis={EXPERIMENT_START_DATE}\n")
    if args.old_genesis:
        print(f"  (outgoing-genesis tokens active for {args.old_genesis})\n")

    total_pages = 0
    failed_pages = 0
    all_hits = []  # list of (url, [(label, samples)])

    # Endpoints that may legitimately return 503 before that day's compute
    # cycle has run (e.g., /api/character is empty until character-sheet-compute
    # runs at 11 AM PT). Allow 503 only if the body explains it.
    ALLOW_503_NOT_COMPUTED = {"/api/character"}

    for path in PAGES + JSON_ENDPOINTS:
        url = BASE + path
        total_pages += 1
        status, body = fetch(url)
        if status != 200:
            if status == 503 and path in ALLOW_503_NOT_COMPUTED and "not yet computed" in body:
                print(f"  ✓ {path} — 503 (expected: compute not yet run today)")
                continue
            print(f"  ✗ {path} — HTTP {status}")
            failed_pages += 1
            all_hits.append((url, [("HTTP error", [str(status)])]))
            continue
        hits = check_body(path, body)
        if hits:
            failed_pages += 1
            print(f"  ✗ {path}")
            for label, samples in hits:
                print(f"      [{label}] {' | '.join(samples)}")
            all_hits.append((url, hits))
        else:
            print(f"  ✓ {path}")

    print("\n══ summary ══")
    print(f"  {total_pages - failed_pages}/{total_pages} pages clean")

    # Persist report
    report = REPO_ROOT / "docs" / "restart" / "_verify_rendered_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"verify_rendered report — genesis={EXPERIMENT_START_DATE}", ""]
    lines.append(f"checked {total_pages} URLs, {failed_pages} with forbidden tokens")
    for url, hits in all_hits:
        lines.append(f"\n{url}")
        for label, samples in hits:
            lines.append(f"  [{label}] {' | '.join(samples)}")
    report.write_text("\n".join(lines))
    print(f"Report: {report.relative_to(REPO_ROOT)}")

    if failed_pages > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
