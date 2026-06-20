#!/usr/bin/env python3
"""
restart_site_copy_sync.py — ADR-058: Regenerate site copy from current genesis
+ baseline. Reads from lambdas/constants.py.

Touches:
  1. site/assets/js/site_constants.js
       - journey.{start_weight, goal_weight, start_date, experiment_start, phase}
         are written from constants. build_date removed (per D decision).
       - Hero copy block (hero_tagline, hero_short, hero_copy, cta_sub) is
         rewritten to clean-slate framing — no restart/relapse/start-over
         language anywhere.
  2. site/data/content_manifest.json
       - The "Started at 307 lbs. Goal: 185." sidebar replaced.
  3. HTML files under site/ with hardcoded "Day 1 · 307 lbs" or "of 365"
     patterns get the literal weight number updated. (Day-of-365 phrasing
     stays — it's a 365-day horizon that's independent of date pivot.)
  4. site/builders/index.html — the platform-build "started February 22, 2026"
     reference is removed per D decision.
  5. CloudFront invalidation for the touched paths.

Date-agnostic. Idempotent — re-running with the same genesis is a no-op.
Re-running with a new genesis updates the JS / JSON / HTML to match.

Usage:
    python3 deploy/restart_site_copy_sync.py            # dry-run / show diffs
    python3 deploy/restart_site_copy_sync.py --apply    # write files + S3 sync + invalidation
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import (
    EXPERIMENT_BASELINE_WEIGHT_LBS,
    EXPERIMENT_GOAL_WEIGHT_LBS,
    EXPERIMENT_START_DATE,
)

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CLOUDFRONT_DIST = "E3S424OXQZ8NBE"

SITE_CONSTANTS_JS = REPO_ROOT / "site" / "assets" / "js" / "site_constants.js"
CONTENT_MANIFEST = REPO_ROOT / "site" / "data" / "content_manifest.json"
BUILDERS_HTML = REPO_ROOT / "site" / "builders" / "index.html"

# ADR-058 launch-eve audit (2026-05-24):
# S3 JSON artifacts that have NO Lambda writer in current code, or whose
# writer cron hasn't fired since pivot. Tombstone-overwrite each so the
# frontend gets a structured empty response and doesn't render stale data.
ORPHAN_S3_FILES = [
    "dashboard/data.json",  # 2026-03-08, no writer
    "dashboard/clinical.json",  # 2026-03-08, no writer
    "dashboard/data/character_stats.json",  # 2026-04-04, pre-pivot
    "dashboard/journal/posts.json",  # 2026-03-30, weekly refresh (legacy dashboard path)
    "dashboard/chronicle/posts.json",  # 2026-03-31, weekly refresh (legacy dashboard path)
    "site/data/data_sources.json",  # 15-day stale
    # v4 Story-door feeds (2026-06-20): the reset tombstoned only the legacy
    # dashboard/ paths above, leaving these v4-served keys stale across the
    # cycle-4 reset — the site served pre-genesis chronicle/journal posts whose
    # DDB records were already phase=pilot+tombstoned. Clear them too so a feed
    # only carries current-cycle posts (empty → honest "Nothing published yet").
    "site/chronicle/posts.json",  # /chronicle/posts.json — Story chronicle feed
    "generated/journal/posts.json",  # /journal/posts.json — Story journal feed
    "site/journal/posts.json",  # sibling journal index (same vintage)
]

# Lambdas to invoke after sync to regenerate the JSON files they own.
# These cover the generated/ prefix files that drive site rendering.
REGEN_LAMBDAS = [
    "life-platform-daily-brief",  # generated/public_stats.json + generated/pulse.json + dashboard/matthew/data.json
    "character-sheet-compute",  # generated/data/character_stats.json
    "site-stats-refresh",  # refreshes vitals in public_stats.json
    "og-image-generator",  # OG image PNGs for share cards
]


# Clean-slate hero copy. No restart / relapse / starting-over language.
# References EXPERIMENT_BASELINE_WEIGHT_LBS rounded to integer for display.
def journey_block(start_lbs_int: int) -> str:
    return (
        "  journey: {\n"
        f"    start_weight:  {start_lbs_int},\n"
        f"    goal_weight:   {EXPERIMENT_GOAL_WEIGHT_LBS},\n"
        f"    start_date:    '{EXPERIMENT_START_DATE}',\n"
        f"    experiment_start: '{EXPERIMENT_START_DATE}',  // Day 1 of the public experiment\n"
        "    phase:         'Foundation',\n"
        "    hero_tagline:  'Day 1.',\n"
        f"    hero_short:    '{start_lbs_int} → {EXPERIMENT_GOAL_WEIGHT_LBS}. 19 data sources. Every number public.',\n"
        "    hero_copy:     'A 12-month experiment in measured living. Body, sleep, training, nutrition — every metric tracked, every change documented. Begin here.',\n"
        f"    cta_sub:       '{start_lbs_int} lbs. The work begins.',\n"
        "  },"
    )


JOURNEY_BLOCK_RE = re.compile(r"  journey: \{\n.*?\n  \},", re.DOTALL)


def rewrite_site_constants(apply: bool) -> tuple[str, str]:
    """Returns (before, after) text for site_constants.js."""
    text = SITE_CONSTANTS_JS.read_text()
    start_int = int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))
    new_journey = journey_block(start_int)
    if not JOURNEY_BLOCK_RE.search(text):
        raise RuntimeError("Could not locate journey: block in site_constants.js")
    new_text = JOURNEY_BLOCK_RE.sub(new_journey, text, count=1)
    if apply and new_text != text:
        SITE_CONSTANTS_JS.write_text(new_text)
    return text, new_text


def rewrite_content_manifest(apply: bool) -> tuple[str, str]:
    """Replace the 307-lbs sidebar string in content_manifest.json."""
    data = json.loads(CONTENT_MANIFEST.read_text())
    before = json.dumps(data, indent=2)
    start_int = int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))
    changed = False
    target_phrase_re = re.compile(r"Started at \d+ lbs\. Goal: \d+\.?")
    new_phrase = f"Started at {start_int} lbs. Goal: {EXPERIMENT_GOAL_WEIGHT_LBS}."

    def visit(node):
        nonlocal changed
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if isinstance(v, str) and target_phrase_re.search(v):
                    node[k] = target_phrase_re.sub(new_phrase, v)
                    changed = True
                elif isinstance(v, (dict, list)):
                    visit(v)
        elif isinstance(node, list):
            for x in node:
                visit(x)

    visit(data)
    after = json.dumps(data, indent=2)
    if apply and changed:
        CONTENT_MANIFEST.write_text(after + "\n")
    return before, after


def rewrite_html_files(apply: bool) -> list[str]:
    """Sweep all site/ HTML for hardcoded baseline-weight references.

    Catches:
      - 'Day 1 · NNN lbs' chart anchors
      - 'Started at NNN lbs' sidebar / hero strings
      - 'NNN to 185 lbs' / 'NNN→185' in titles / meta / scaffolding
      - JS fallback literal `|| NNN` patterns next to start_weight
      - 'Day 1 · April 2026' badge text (removes the badge entirely)
    """
    touched = []
    start_int = int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))
    goal_int = int(round(EXPERIMENT_GOAL_WEIGHT_LBS))

    # Matches any "NNN lbs" / "NNN pounds" / "NNN to NNN" pattern where NNN is
    # plausibly a baseline-weight literal (200–350) NOT followed by phrases
    # like "page" or "items" (those would be unrelated to the baseline).
    patterns = [
        (re.compile(r"Day 1 · \d{3} lbs"), f"Day 1 · {start_int} lbs"),
        (re.compile(r"Started at \d{3} lbs"), f"Started at {start_int} lbs"),
        (re.compile(r"\b\d{3} to 185 lbs\b"), f"{start_int} to {goal_int} lbs"),
        (re.compile(r"\b\d{3}→185\b"), f"{start_int}→{goal_int}"),
        (re.compile(r"\b\d{3} → 185\b"), f"{start_int} → {goal_int}"),
        # JS fallback patterns next to start_weight references:
        (re.compile(r"(start_weight[^;\n]{0,60}\|\|\s*)\d{3}"), rf"\g<1>{start_int}"),
        # Pull-quote dated badge from prior attempt:
        (re.compile(r"Day 1 [&·]middot;[ ]?\s*April 2026"), f"Day 1 · {EXPERIMENT_START_DATE[:7]}"),
        # ADR-058 launch-eve: bare 307 in weight-context substrings (live + physical pages)
        (re.compile(r"From 307 lbs to goal"), f"From {start_int} lbs to goal"),
        (re.compile(r"down from 307"), f"down from {start_int}"),
        (re.compile(r"\(307 - cur\)"), f"({start_int} - cur)"),
        # Generic "307 →" chart anchor (used as Day-1 line on physical/live pages)
        (re.compile(r"\b307\s*→"), f"{start_int} →"),
        # JS fallback: || 307 in any var-assignment near weight
        (re.compile(r"(\|\|\s*)307\b"), rf"\g<1>{start_int}"),
    ]

    for html in (REPO_ROOT / "site").rglob("*.html"):
        if "/archive/" in str(html):
            continue
        original = html.read_text()
        new = original
        for pat, replacement in patterns:
            new = pat.sub(replacement, new)
        if new != original:
            touched.append(str(html.relative_to(REPO_ROOT)))
            if apply:
                html.write_text(new)
    return touched


def rewrite_js_files(apply: bool) -> list[str]:
    """Sweep all site/ JS files for hardcoded `'YYYY-MM-DD'` literals near
    start_date / journey / experiment / Date( and replace with a runtime
    expression that reads window.AMJ.journey.start_date with a fallback to
    the current EXPERIMENT_START_DATE.

    Idempotent: only rewrites bare-literal forms, not already-dynamic ones.
    """
    touched = []
    fallback = EXPERIMENT_START_DATE
    dynamic = "((window.AMJ && window.AMJ.journey && window.AMJ.journey.start_date) " f"|| '{fallback}')"

    # Two patterns:
    #   1. Bare quoted ISO date like '2026-04-01' or "2026-04-01"
    #   2. ISO date with time suffix like '2026-04-01T07:00:00-07:00'
    # We restrict to single 4-digit-year ISO strings to avoid touching IDs.
    bare_pat = re.compile(r"(['\"])(\d{4}-\d{2}-\d{2})\1")
    iso_time_pat = re.compile(r"(['\"])(\d{4}-\d{2}-\d{2})(T[^'\"]+)\1")

    # Skip site_constants.js — it's where the genesis value is DEFINED.
    # Rewriting it would create a circular dynamic-lookup of itself.
    SKIP_FILES = {"site_constants.js"}

    for f in (REPO_ROOT / "site").rglob("*.js"):
        if "/archive/" in str(f):
            continue
        if f.name in SKIP_FILES:
            continue
        text = f.read_text()

        # Pass 1: T-suffix variants — only rewrite the OLD genesis literal
        def repl_iso_time(m):
            q, date, suffix = m.group(1), m.group(2), m.group(3)
            if date != "2026-04-01":
                return m.group(0)  # preserve other dates as-is
            return f"{dynamic} + {q}{suffix}{q}"

        new = iso_time_pat.sub(repl_iso_time, text)

        # Pass 2: bare literals — only rewrite the OLD genesis literal
        def repl_bare(m):
            _q, date = m.group(1), m.group(2)
            if date != "2026-04-01":
                return m.group(0)
            return dynamic

        new = bare_pat.sub(repl_bare, new)

        if new != text:
            touched.append(str(f.relative_to(REPO_ROOT)))
            if apply:
                f.write_text(new)
    return touched


def tombstone_orphan_s3_files(apply: bool, now_iso: str) -> list[str]:
    """Tombstone-overwrite orphaned S3 JSON files that have no active writer."""
    tombstoned = []
    payload = json.dumps(
        {
            "tombstone": True,
            "tombstoned_at": now_iso,
            "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}",
            "_note": "This file has no active Lambda writer; was overwritten during the experiment restart to prevent stale-data leak.",
        }
    ).encode()
    for key in ORPHAN_S3_FILES:
        if apply:
            subprocess.run(
                [
                    "aws",
                    "s3api",
                    "put-object",
                    "--bucket",
                    S3_BUCKET,
                    "--key",
                    key,
                    "--body",
                    "-",
                    "--content-type",
                    "application/json",
                    "--region",
                    REGION,
                ],
                input=payload,
                check=False,
                capture_output=True,
            )
        tombstoned.append(key)
    return tombstoned


def invoke_regen_lambdas(apply: bool) -> list[tuple[str, str]]:
    """Invoke the Lambdas that own the cached JSON artifacts the site reads."""
    results = []
    for fn in REGEN_LAMBDAS:
        if apply:
            proc = subprocess.run(
                [
                    "aws",
                    "lambda",
                    "invoke",
                    "--function-name",
                    fn,
                    "--region",
                    REGION,
                    "--invocation-type",
                    "RequestResponse",
                    "--payload",
                    "e30=",  # base64-encoded '{}'
                    "--cli-binary-format",
                    "raw-in-base64-out",
                    "/tmp/_regen_" + fn.replace("-", "_") + ".json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            status = "ok" if proc.returncode == 0 else f"err({proc.returncode})"
        else:
            status = "would-invoke"
        results.append((fn, status))
    return results


def strip_builders_feb22(apply: bool) -> bool:
    """Remove the 'started February 22, 2026' reference from the builders page.
    Returns True if a change was needed.
    """
    if not BUILDERS_HTML.exists():
        return False
    text = BUILDERS_HTML.read_text()
    # The sentence in the discovery report:
    #   "He started this platform on February 22, 2026."
    # Strip that one sentence; leave the rest of the paragraph.
    pat = re.compile(r"He started this platform on February 22, 2026\. ?")
    new = pat.sub("", text)
    if new == text:
        return False
    if apply:
        BUILDERS_HTML.write_text(new)
    return True


def sync_to_s3(apply: bool, touched_html: list[str]):
    """Mirror local site/ → s3://matthew-life-platform/site/ for the touched files."""
    keys_to_sync = [
        "site/assets/js/site_constants.js",
        "site/data/content_manifest.json",
        "site/builders/index.html",
    ] + touched_html
    if apply:
        for rel in keys_to_sync:
            local = REPO_ROOT / rel
            if not local.exists():
                continue
            subprocess.run(["aws", "s3", "cp", str(local), f"s3://{S3_BUCKET}/{rel}", "--region", REGION], check=False, capture_output=True)
    return keys_to_sync


def _viewer_path(key: str) -> str:
    """Map an S3 key to its CloudFront VIEWER path. Both `site/` and `generated/`
    (ADR-046) are stripped at the edge, so an invalidation must target the public
    path, not the S3 key — busting `/generated/...` never clears `/...` (the
    CloudFront-path bug, 2026-06-18)."""
    for prefix in ("site/", "generated/"):
        if key.startswith(prefix):
            return "/" + key[len(prefix) :]
    return "/" + key


def invalidate_cloudfront(apply: bool, paths: list[str]):
    cf_paths = [_viewer_path(p) for p in paths]
    cf_paths.append("/")  # invalidate root for safety
    if apply:
        subprocess.run(
            ["aws", "cloudfront", "create-invalidation", "--distribution-id", CLOUDFRONT_DIST, "--paths", *cf_paths],
            check=False,
            capture_output=True,
        )
    return cf_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument("--skip-cloudfront", action="store_true", help="Skip CloudFront invalidation step")
    parser.add_argument(
        "--orphans-only",
        action="store_true",
        help="Run ONLY the orphan-S3 tombstone step (+ CloudFront invalidation) — for a targeted stale-feed cleanup outside a full reset",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] site copy sync. genesis={EXPERIMENT_START_DATE} baseline={EXPERIMENT_BASELINE_WEIGHT_LBS}")

    if args.orphans_only:
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        orphans = tombstone_orphan_s3_files(args.apply, now_iso)
        print(f"[orphans-only] Orphan S3 files tombstoned: {len(orphans)}")
        for o in orphans:
            print(f"    - s3://{S3_BUCKET}/{o}")
        if not args.skip_cloudfront:
            paths = invalidate_cloudfront(args.apply, orphans)
            print(f"               CloudFront invalidation: {len(paths)} path(s){' (would invalidate)' if not args.apply else ''}")
        return

    # 1. site_constants.js
    js_before, js_after = rewrite_site_constants(args.apply)
    js_changed = js_before != js_after
    print(f"\n[1/5] site_constants.js: {'CHANGED' if js_changed else 'unchanged'}")

    # 2. content_manifest.json
    cm_before, cm_after = rewrite_content_manifest(args.apply)
    cm_changed = cm_before != cm_after
    print(f"[2/5] content_manifest.json: {'CHANGED' if cm_changed else 'unchanged'}")

    # 3. HTML files
    touched_html = rewrite_html_files(args.apply)
    print(f"[3/8] HTML files updated: {len(touched_html)}")
    for h in touched_html:
        print(f"    - {h}")

    # 4. JS files (ADR-058 launch-eve: was missing)
    touched_js = rewrite_js_files(args.apply)
    print(f"[4/8] JS files updated: {len(touched_js)}")
    for j in touched_js:
        print(f"    - {j}")

    # 5. builders/ Feb-22 strip
    builders_changed = strip_builders_feb22(args.apply)
    print(f"[5/8] builders/index.html Feb-22 strip: {'CHANGED' if builders_changed else 'unchanged'}")

    # 6. Orphan S3 file tombstones
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    orphans = tombstone_orphan_s3_files(args.apply, now_iso)
    print(f"[6/8] Orphan S3 files tombstoned: {len(orphans)}")
    for o in orphans:
        print(f"    - s3://{S3_BUCKET}/{o}")

    # 7. S3 sync + CloudFront invalidate
    keys = sync_to_s3(args.apply, touched_html + touched_js)
    print(f"[7/8] S3 sync: {len(keys)} key(s){' (would sync)' if not args.apply else ''}")
    if not args.skip_cloudfront:
        paths = invalidate_cloudfront(args.apply, keys + orphans)
        print(f"       CloudFront invalidation: {len(paths)} path(s){' (would invalidate)' if not args.apply else ''}")
    else:
        print("       CloudFront invalidation: SKIPPED")

    # 8. Regenerate generated/ JSON by invoking the writer Lambdas
    regen_results = invoke_regen_lambdas(args.apply)
    print(f"[8/8] Regen Lambda invocations: {len(regen_results)}")
    for fn, status in regen_results:
        print(f"    - {fn}: {status}")

    # Report
    report_path = REPO_ROOT / "docs" / "restart" / "_site_copy_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"site copy sync report — mode={mode} — genesis={EXPERIMENT_START_DATE}\n"
        f"baseline_lbs={EXPERIMENT_BASELINE_WEIGHT_LBS} goal_lbs={EXPERIMENT_GOAL_WEIGHT_LBS}\n\n"
        f"site_constants_js_changed   = {js_changed}\n"
        f"content_manifest_changed    = {cm_changed}\n"
        f"html_files_touched          = {len(touched_html)}\n"
        f"js_files_touched            = {len(touched_js)}\n"
        f"builders_feb22_removed      = {builders_changed}\n"
        f"orphan_s3_tombstoned        = {len(orphans)}\n"
        f"regen_lambdas_invoked       = {len([r for r in regen_results if r[1] == 'ok'])}/{len(regen_results)}\n"
        f"keys_synced                 = {len(keys) if args.apply else 0}\n"
    )
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
