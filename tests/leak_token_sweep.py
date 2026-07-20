#!/usr/bin/env python3
"""
leak_token_sweep.py — shared leak-token sweep core (#1448).

Extracted from deploy/restart_verify_rendered.py (ADR-058) so the SAME
deterministic, AI-free token-grep runs in two places:
  - deploy/restart_verify_rendered.py — the manual reset-time verification
    path. Behavior unchanged: same full token list, same --old-genesis
    waiver logic, same report — it just imports the checks from here now.
  - tests/visual_qa.py — the daily/standalone visual-qa run (#1448), so a
    template/leak-token regression (a hardcoded stale literal, a cached S3
    JSON blob, a missed DDB partition) is caught within a day instead of
    only at the next reset.

No secrets here, and none should ever be added: every pattern is a
structural signal (a retired public literal weight, a dead cycle-1 launch
date, an error sentinel value, a JSON tombstone flag, or a day/level/week
counter that only makes sense right after a fresh reset) — this module
lives in a PUBLIC repo. Keep new patterns generic; never encode a personal
term or a live secret shape here — if a future check needs something more
sensitive than that, it belongs in private config, not this file.

RESET_WINDOW_LABELS marks the FORBIDDEN_TOKENS entries that encode "the OLD
cycle's higher counters must not leak into a freshly-reset one" — those only
make sense while the CURRENT cycle is still young (or the site is in
pre-start countdown, #931/#939). Once a cycle has legitimately run past the
window, the exact same values (Day 45, Character Level 12, ...) are true
content, not a leak. tokens_for_daily_run() drops that subset once the
cycle has matured past the window so the continuous sweep doesn't red on
real progress; restart_verify_rendered.py runs at reset time
(days-since-genesis ~0), so it always uses the full FORBIDDEN_TOKENS list
unchanged.
"""
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE  # noqa: E402

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

# Endpoints that may legitimately return 503 before that day's compute cycle
# has run (e.g., /api/character is empty until character-sheet-compute runs at
# 11 AM PT). Allowed only when the body explains it ("not yet computed").
ALLOW_503_NOT_COMPUTED = {"/api/character"}

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
    # --old-genesis in restart_verify_rendered's main()). The cycle-compare + timeline
    # APIs legitimately list every past genesis (CYCLE_GENESES is their whole point).
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

# The subset of FORBIDDEN_TOKENS that only makes sense while the CURRENT cycle
# is still young (see module docstring). tokens_for_daily_run() drops these
# once the cycle has matured past RESET_WINDOW_DAYS.
RESET_WINDOW_LABELS = {
    "Day-30+ counter",
    "Earned milestone",
    "Character level 4+",
    "Past week recap (Week 10+)",
}
RESET_WINDOW_DAYS = 30  # matches the "Day-30+" ceiling these checks assume


def fetch(url: str, timeout: int = 15, user_agent: str = "leak-token-sweep/1.0") -> tuple[int, str]:
    """Fetch a URL, return (status_code, body). Returns (0, '') on network error.

    Reads the body even on HTTPError — callers may need to inspect the error
    payload (e.g., '/api/character' returns 503 with a 'not yet computed' body
    that the sweep accepts as expected pre-compute state).
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def check_body(path: str, body: str, tokens=None) -> list[tuple[str, list[str]]]:
    """Return list of (token_label, matches) for any forbidden token that hit.

    tokens defaults to the full FORBIDDEN_TOKENS list; callers may pass a
    restricted set (e.g. tokens_for_daily_run()).
    """
    tokens = FORBIDDEN_TOKENS if tokens is None else tokens
    hits = []
    for label, regex, allowed_prefixes in tokens:
        if any(path.startswith(p) for p in allowed_prefixes):
            continue
        matches = regex.findall(body)
        if matches:
            # Sample at most 3 matches per token for the report
            sample = [str(m)[:80] for m in matches[:3]]
            hits.append((label, sample))
    return hits


def old_genesis_tokens(old_genesis: str, today: str | None = None) -> list:
    """Dynamic forbidden tokens for the OUTGOING genesis: the ISO literal plus its
    short prose forms ('June 14' / 'Jun 14') — the forms the JS sweep rewrites.

    `today` (ISO) is injectable so the waiver branch is testable without wall-clock
    coupling; it defaults to the real today at call time. Reset-time-only (called
    by restart_verify_rendered's main() with the OUTGOING genesis from
    restart_pipeline) — the daily sweep has no outgoing genesis, so it never
    calls this.
    """
    if not old_genesis or old_genesis == EXPERIMENT_START_DATE:
        return []
    o = date.fromisoformat(old_genesis)
    today = today or date.today().isoformat()
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
    if old_genesis == today:
        print(
            f"  ⚠ outgoing genesis {old_genesis} == today (future-genesis reset) — ISO-literal token WAIVED (collides with live freshness data)"
        )
        return tokens
    return [
        (f"Outgoing genesis literal ({old_genesis})", re.compile(rf"\b{re.escape(old_genesis)}\b"), iso_allowed),
        *tokens,
    ]


def days_since_genesis(today: str | None = None) -> int | None:
    """Days between EXPERIMENT_START_DATE and `today` (default: real today).
    Negative when the site is in pre-start countdown (#931/#939). None if
    EXPERIMENT_START_DATE is unavailable."""
    if not EXPERIMENT_START_DATE:
        return None
    today = today or date.today().isoformat()
    return (date.fromisoformat(today) - date.fromisoformat(EXPERIMENT_START_DATE)).days


def tokens_for_daily_run(today: str | None = None) -> list:
    """FORBIDDEN_TOKENS subset safe for the CONTINUOUS daily sweep (#1448).

    See module docstring / RESET_WINDOW_LABELS: the reset-window entries assume
    the cycle is still young. days_since_genesis() <= RESET_WINDOW_DAYS (or a
    pre-start negative value, or an unreadable genesis) keeps the full list —
    once the current cycle has legitimately run longer than that, the
    reset-window entries are dropped so real progress doesn't red the sweep.
    """
    days = days_since_genesis(today)
    if days is None or days <= RESET_WINDOW_DAYS:
        return FORBIDDEN_TOKENS
    return [t for t in FORBIDDEN_TOKENS if t[0] not in RESET_WINDOW_LABELS]


def sweep(base_url: str, pages, json_endpoints=(), tokens=None, allow_503_paths=(), timeout: int = 15) -> list[dict]:
    """Fetch base_url+path for every path in pages+json_endpoints and check_body
    each against `tokens` (defaults to FORBIDDEN_TOKENS). Returns a list of dicts:
        {"path", "url", "http_status", "hits": [(label, [samples]), ...]}
    `hits` is empty for a clean page/endpoint whose fetch succeeded (or was an
    allowed 503). A non-200/non-allowed-503 fetch is reported as a single
    ("HTTP error", [str(status)]) hit so callers can treat it uniformly.
    """
    tokens = FORBIDDEN_TOKENS if tokens is None else tokens
    results = []
    for path in list(pages) + list(json_endpoints):
        url = base_url + path
        status, body = fetch(url, timeout=timeout)
        if status != 200:
            if status == 503 and path in allow_503_paths and "not yet computed" in body:
                results.append({"path": path, "url": url, "http_status": status, "hits": []})
                continue
            results.append({"path": path, "url": url, "http_status": status, "hits": [("HTTP error", [str(status)])]})
            continue
        hits = check_body(path, body, tokens=tokens)
        results.append({"path": path, "url": url, "http_status": status, "hits": hits})
    return results
