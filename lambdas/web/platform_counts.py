"""
lambdas/web/platform_counts.py — GENERATED. The one committed home of the
repo-derived platform counters, and nothing else (#3101).

DO NOT HAND-EDIT. DO NOT COMMIT THIS FILE ON A BRANCH.

  • The only writer is `python3 deploy/sync_doc_metadata.py --apply`, which
    re-derives every value below from the repo (AST/glob discovery) and rewrites
    the literals in place.
  • On `main` that writer is the reconcile bot (`ci-cd.yml` Job 0, #1173).
  • `deploy/agent_commit.sh` REFUSES to stage this path, and the pre-commit hook
    stages it only for the driver reconciling on main.

WHY THIS FILE EXISTS — the conflict surface, measured (#3101).
`test_count` moves on *every* PR that adds a test, i.e. on nearly every PR. It
used to live inside `PLATFORM_STATS` in `lambdas/web/site_api_common.py` — a hot
shared module 134 endpoints import and branches edit for real reasons — and
inside `docs/TESTING.md`, a doc branches edit for real reasons. So the counter
was a committed line *inside files a PR was legitimately carrying*, which made it
inseparable from that PR's own diff: every concurrent test-adding PR conflicted
with every other one and with each post-merge reconcile-bot commit. The
2026-08-23/24 merge train paid ~3–4h of serial reconcile rounds to it.

Moving the literals to a file that exists for no other purpose makes the counter
*separable* by construction: a branch never has a reason to touch this module, so
`agent_commit.sh` can refuse it outright and a PR's diff no longer carries a
global counter. Same guard, same discovery, no shared line.

The serving Lambda cannot re-derive `test_count` at request time — `tests/` is
not in the bundle (`deploy/build_bundle.py` stages `lambdas/` only) — so the
count has to arrive as build-time-stamped data. A plain Python module inside
`lambdas/web/` is the smallest form of that: it is already staged into every
bundle by construction, needs no loader, no packaging change, no deploy-trigger
change, and no runtime fallback that could serve a stale number.

GUARDS (all of which still red on a genuinely wrong count):
  • `deploy/sync_doc_metadata.py --check`  — Docs CI, reds on any drifted literal
  • `tests/test_platform_stats_truth.py`   — reds when the served dict drifts
  • `tests/test_doc_literal_conflict_surface_3101.py` — reds if a counter grows a
    second committed home, or if the single-writer plumbing comes undone
"""

# Every key here is rewritten by deploy/sync_doc_metadata.py::_sync_platform_counts.
# Adding a key means adding a discoverer there too — a hand-maintained judgment
# number does NOT belong in this file, it belongs in PLATFORM_STATS.
DISCOVERED_COUNTS = {
    "data_sources": 20,
    "mcp_tools": 76,
    "lambdas": 104,
    "alarms": 114,
    "adrs": 153,
    "test_count": 17048,
}
