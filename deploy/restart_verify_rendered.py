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

Exit code 0 if all checks pass; 1 otherwise.

Usage:
    python3 deploy/restart_verify_rendered.py [--old-genesis YYYY-MM-DD]
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

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
    all_hits = []  # list of (url, [(label, samples)])

    for r in page_results:
        total_pages += 1
        path, url, status, hits = r["path"], r["url"], r["http_status"], r["hits"]
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
