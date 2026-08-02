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

The token list + fetch/check core live in tests/leak_token_sweep.py (#1448)
so the SAME deterministic, AI-free sweep also runs inside the daily
tests/visual_qa.py pass, not only here at reset time — this script's own
behavior is unchanged (full FORBIDDEN_TOKENS list, same --old-genesis waiver
logic, same report).

Also asserts (#1952) that GET /api/predict_week is active:true once the genesis
week begins — pre-genesis (countdown) dark is correct; see
check_predict_week_live().

Exit code 0 if all checks pass; 1 otherwise.

Usage:
    python3 deploy/restart_verify_rendered.py [--old-genesis YYYY-MM-DD]
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.common.constants import EXPERIMENT_START_DATE

BASE = "https://averagejoematt.com"

# Pages to fetch and inspect — derived from THE page registry
# (tests/qa_manifest.py, #1426): every real HTML page whose manifest entry has
# leak_scan=True (pure redirect stubs excluded). The pre-#1426 hand list here
# covered 35 pages; the manifest facet covers the full live surface, so the
# token grep now sweeps every page the public can reach.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from leak_token_sweep import (  # noqa: E402
    ALLOW_503_NOT_COMPUTED,
    FORBIDDEN_TOKENS,
    JSON_ENDPOINTS,
    old_genesis_tokens as _old_genesis_tokens,
    sweep as _leak_sweep,
)
from qa_manifest import leak_scan_paths  # noqa: E402

PAGES = leak_scan_paths()


def check_predict_week_live() -> tuple:
    """#1952 — the predict-the-week hook, checked alongside the page sweep.

    Once the genesis week begins, GET /api/predict_week must return active:true:
    the cycle-11 seed carried the wall-clock (pre-genesis) week_id and the #1198
    fail-closed guard correctly hid the flagship engagement hook for the whole
    opening week — a state every prior reset verification blessed. Pre-genesis
    (the countdown, #931) dark is correct; after the genesis week, weekly
    re-seeding is outside the reset verifier. Returns (ok, detail).
    """
    sys.path.insert(0, str(REPO_ROOT / "deploy"))
    from build_genesis_predict_week import evaluate_predict_week_state

    try:
        with urllib.request.urlopen(f"{BASE}/api/predict_week?cb=verify", timeout=15) as r:
            active = bool(json.loads(r.read()).get("active"))
    except Exception:
        active = None
    today_pt = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    return evaluate_predict_week_state(EXPERIMENT_START_DATE, today_pt, active)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-genesis",
        default=None,
        help="The OUTGOING genesis (YYYY-MM-DD) — its ISO + prose forms become forbidden tokens. Passed by restart_pipeline.",
    )
    args = parser.parse_args()
    # A LOCAL list, not a mutation of the shared module's FORBIDDEN_TOKENS — keeps
    # this reset-time-only extension from leaking into any other importer of
    # tests/leak_token_sweep.py within the same process (e.g. a pytest run that
    # imports both this module and visual_qa.py).
    tokens = FORBIDDEN_TOKENS + _old_genesis_tokens(args.old_genesis)

    print(f"\nrestart_verify_rendered — checking public surfaces against genesis={EXPERIMENT_START_DATE}\n")
    if args.old_genesis:
        print(f"  (outgoing-genesis tokens active for {args.old_genesis})\n")

    page_results = _leak_sweep(BASE, PAGES, JSON_ENDPOINTS, tokens=tokens, allow_503_paths=ALLOW_503_NOT_COMPUTED)

    total_pages = 0
    failed_pages = 0
    unreachable_pages = 0
    all_hits = []  # list of (url, [(label, samples)])

    for r in page_results:
        total_pages += 1
        path, url, status, hits = r["path"], r["url"], r["http_status"], r["hits"]
        if r.get("unreachable"):
            # Transport failure after one retry (#1931): the page was never
            # read, so it is neither clean nor failed — count it separately so
            # partial coverage cannot read as full coverage.
            unreachable_pages += 1
            print(f"  ⚠ {path} — UNREACHABLE after retry (NOT checked)")
            continue
        if hits and hits[0][0] == "HTTP error":
            print(f"  ✗ {path} — HTTP {status}")
            failed_pages += 1
            all_hits.append((url, hits))
            continue
        if hits:
            failed_pages += 1
            print(f"  ✗ {path}")
            for label, samples in hits:
                print(f"      [{label}] {' | '.join(samples)}")
            all_hits.append((url, hits))
        else:
            if status == 503:
                print(f"  ✓ {path} — 503 (expected: compute not yet run today)")
            else:
                print(f"  ✓ {path}")

    # #1952 — predict-the-week liveness, alongside the page sweep.
    predict_ok, predict_detail = check_predict_week_live()
    print(f"\n  {'✓' if predict_ok else '✗'} /api/predict_week — {predict_detail}")

    print("\n══ summary ══")
    checked_pages = total_pages - unreachable_pages
    print(f"  {checked_pages - failed_pages}/{checked_pages} checked pages clean; {unreachable_pages} NOT checked (unreachable)")

    # Persist report
    report = REPO_ROOT / "docs" / "restart" / "_verify_rendered_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"verify_rendered report — genesis={EXPERIMENT_START_DATE}", ""]
    lines.append(
        f"checked {checked_pages} of {total_pages} URLs ({unreachable_pages} unreachable, NOT checked), {failed_pages} with forbidden tokens"
    )
    lines.append(f"predict_week (#1952): {'PASS' if predict_ok else 'FAIL'} — {predict_detail}")
    for url, hits in all_hits:
        lines.append(f"\n{url}")
        for label, samples in hits:
            lines.append(f"  [{label}] {' | '.join(samples)}")
    report.write_text("\n".join(lines))
    print(f"Report: {report.relative_to(REPO_ROOT)}")

    if failed_pages > 0 or not predict_ok:
        sys.exit(1)
    # Coverage-collapse guard (#1931): this is the reset-time verification —
    # if a quarter of the surface was never read, a clean tally is a verdict
    # the sweep did not earn. Fail rather than bless unverified pages.
    if total_pages and unreachable_pages * 4 >= total_pages:
        print(f"  ✗ coverage collapse: {unreachable_pages}/{total_pages} pages unreachable — verdict not earned")
        sys.exit(1)


if __name__ == "__main__":
    main()
