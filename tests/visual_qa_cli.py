#!/usr/bin/env python3
"""
visual_qa_cli.py — argparse/CLI entry point for tests/visual_qa.py's run_sweep.

Extracted from visual_qa.py's `if __name__ == "__main__":` block (#1991) purely
to hold visual_qa.py's line count inside the module-size headroom (visual_qa.py
was ~1165 lines, within 150 of the 1200-line ceiling, before the light-theme
plumbing this issue adds) — no behavior change. All sweep logic still lives in
visual_qa.run_sweep; this module owns only flag parsing and dispatch.

Invoke via `python3 tests/visual_qa.py [flags]` — visual_qa.py's own __main__
guard hands off to `main()` here, passing its own already-executed module
object (`sys.modules["__main__"]`) so `python3 tests/visual_qa.py` never
double-imports/re-executes the module under two different sys.modules keys.
"""

import argparse
import sys


def main(vqa=None, argv=None):
    """Parse CLI flags and run the sweep. `vqa` is the visual_qa module to drive
    (defaults to importing it fresh, e.g. when this file is run directly or
    called from a test); `argv` defaults to sys.argv[1:]. Returns an exit code.
    """
    if vqa is None:
        import visual_qa as vqa  # deliberate local import: avoid importing visual_qa until CLI use

    ap = argparse.ArgumentParser(description="v4 visual QA sweep for averagejoematt.com")
    ap.add_argument("--page", help="Test a single page path (e.g. /cockpit/)")
    ap.add_argument("--screenshot", action="store_true", help="Save full-page + chart-crop + mobile screenshots")
    ap.add_argument("--ai-qa", action="store_true", help="Run Claude (Bedrock) semantic QA over the screenshots")
    ap.add_argument(
        "--ai-qa-max-tier",
        type=int,
        default=None,
        help=(
            "Restrict --ai-qa to qa_manifest pages with tier <= N (#1428; deploy-time CI passes 1 to cover exactly "
            "the 6 flagship doors). Omit for the full-surface pass (the weekly scheduled run). Never affects the "
            "deterministic Playwright coverage, which always runs over every page in --page/PAGES."
        ),
    )
    ap.add_argument(
        "--reader-truth",
        action="store_true",
        help="Run the phase-aware reader-truth QA over each page's rendered prose (#1095; high severity gates like --ai-qa)",
    )
    ap.add_argument(
        "--browser",
        choices=["chromium", "webkit", "firefox"],
        default="chromium",
        help="Playwright engine to drive (#1434; the weekly advisory iOS-Safari-engine run passes webkit)",
    )
    ap.add_argument(
        "--mobile",
        action="store_true",
        help="Open the browser context at an iPhone-class mobile profile (390x844, dpr 3, touch) instead of 1440x900 desktop (#1434)",
    )
    ap.add_argument(
        "--no-a11y",
        action="store_true",
        help="Skip the axe-core accessibility audit (#1433). Debug escape hatch only — every CI run keeps the audit on.",
    )
    ap.add_argument(
        "--color-scheme",
        choices=["dark", "light"],
        default="dark",
        help=(
            "Playwright color-scheme both browser contexts render under (#1991). Defaults to 'dark' — every "
            "existing gating run is unchanged. 'light' opens the same sweep under a light OS theme, threading "
            "into the axe gate's sibling 'pages_light' baseline ledger instead of 'pages'."
        ),
    )
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Rewrite tests/a11y_baseline.json from this run's axe findings for the pages swept (#1433). DELIBERATE path: "
            "the run still reds on NEW serious/critical violations, and the committed baseline diff is the review surface "
            "(added entries = newly accepted debt, removed = fixes). See tests/a11y_audit.py."
        ),
    )
    ap.add_argument(
        "--update-truth-baseline",
        action="store_true",
        help=(
            "Rewrite tests/truth_baseline.json (the reader-truth debt ledger, #2956) from this run's high findings "
            "for the pages swept — a11y --update-baseline's sibling, same DELIBERATE contract: the run still reds on "
            "NEW findings, fresh entries land UNTRIAGED (which reds the unit suite until an issue is named), and the "
            "committed diff is the review surface. Requires --reader-truth."
        ),
    )
    ap.add_argument(
        "--max-tier",
        type=int,
        default=None,
        help=(
            "Restrict the DETERMINISTIC sweep to qa_manifest pages with tier <= N (#1434; the weekly WebKit run passes 2 "
            "for the flagship doors + live-data topic pages). Omit for full coverage — every existing gating run does."
        ),
    )
    ap.add_argument(
        "--no-leak-scan",
        action="store_true",
        help=(
            "Skip the deterministic leak-token sweep (#1448; tests/leak_token_sweep.py — the same checks "
            "deploy/restart_verify_rendered.py runs at reset time). Debug escape hatch only — every CI run keeps it on."
        ),
    )
    args = ap.parse_args(argv)

    pages = None
    if args.page:
        pages = [p for p in vqa.PAGES if p["path"] == args.page]
        if not pages:
            print(f"Unknown page: {args.page}\nAvailable: {', '.join(p['path'] for p in vqa.PAGES)}")
            return 1

    profile = (
        f" [{args.browser}{', mobile' if args.mobile else ''}"
        f"{f', tier<={args.max_tier}' if args.max_tier is not None else ''}"
        f"{', light' if args.color_scheme == 'light' else ''}]"
    )
    print(f"v4 Visual QA Sweep — {vqa.SITE_URL}{profile if profile != ' [chromium]' else ''}\n{'=' * 56}")
    ok = vqa.run_sweep(
        pages=pages,
        save_screenshots=args.screenshot,
        ai_qa=args.ai_qa,
        reader_truth=args.reader_truth,
        ai_qa_max_tier=args.ai_qa_max_tier,
        browser_name=args.browser,
        mobile=args.mobile,
        max_tier=args.max_tier,
        a11y=not args.no_a11y,
        update_a11y_baseline=args.update_baseline,
        update_truth_baseline=args.update_truth_baseline,
        leak_scan=not args.no_leak_scan,
        color_scheme=args.color_scheme,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
