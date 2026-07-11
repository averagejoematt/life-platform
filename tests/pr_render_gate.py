#!/usr/bin/env python3
"""
pr_render_gate.py — shift render + accuracy QA LEFT onto site pull requests (#408).

Today the Playwright render sweep (tests/visual_qa.py) and the accuracy
impossible-number checks (tests/accuracy_audit.py --live) run only AFTER deploy,
against the LIVE site, and only when backend code ships — so a site-only PR (the
change most likely to break a page) gets just an HTML well-formedness check before
merge. This harness closes that gap: it runs the SAME render harness at PR time
against a LOCAL static serve of site/ with the API mocked, and fails on render
errors / layout overflow / leaked impossible numbers — before it reaches readers.

How it stays fast + non-flaky (per handovers/HANDOVER_LATEST.md render-QA notes +
reference_local_render_qa memory):
  • Serves site/ over http.server (absolute /assets ES-module paths need a real
    origin, not file://) on an ephemeral localhost port.
  • Chromium headless, ONE context, service_workers="block" (SW-handled fetches
    bypass page.route and would silently 404 against the static server).
  • Mocks **/api/** with a catch-all registered FIRST (Playwright matches routes in
    REVERSE registration order, so specific mocks registered AFTER win). The mock
    data is realistic-but-static, so no live deploy / real data is touched and the
    gate can't flake on daily data drift.
  • Pages that render a legitimately-empty state (honest empty data) PASS — only a
    genuine render failure, a JS error, a horizontal overflow, or a leaked
    NaN/undefined/[object Object] in the visitor-facing prose blocks the merge.

Mobile coverage (#1012): capture_page runs a mobile pass at 390×844 (+ the app-bar
chrome check at 360×800) on every gate page, so the pre-merge gate now renders mobile
in addition to 1440×900 desktop — and asserts the Epic-A failure classes there
(stuck reveals #1002, app-bar overflow #1003, missing viewport meta #1004; tap-target
audit #1010 is advisory). A PR that reintroduces one of those classes fails the gate
before merge instead of surfacing on the live site.

This SUPPLEMENTS the post-deploy live QA (ci-cd.yml visual-qa job) — it never
replaces it. The live sweep still runs against real prod data after deploy.

Usage:
    python3 tests/pr_render_gate.py                 # gate over site/ (representative pages)
    python3 tests/pr_render_gate.py --site-dir /tmp/broken-site   # gate a copy (demo)
    python3 tests/pr_render_gate.py --keep          # keep the screenshot/prose capture dir
Exit 0 = gate passed; exit 1 = a render or accuracy regression blocked the merge.
"""

import argparse
import functools
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ── Representative page set ───────────────────────────────────────────────────
# One page per door + a chart/data page + the cockpit (its pillar interaction is
# the richest client-side render on the site). Kept small so the gate stays fast;
# every path here is a COMMITTED file under site/ (so the static serve resolves it
# without a build step). Checks are deliberately STRUCTURAL/lenient — the shell
# (page-hero · loop-ribbon · footer) is present regardless of data, so an honest
# empty-data state passes; capture_page still enforces no-JS-error, no-overflow,
# no-blank-section, no-stale-text on every one.
GATE_PAGES = [
    {"path": "/", "name": "Home (constellation)", "wait_for": "body"},
    {
        "path": "/now/",
        "name": "Cockpit",
        "wait_for": "body",
        # Exercise the pillar disclosure when data mounted a row; if the mock
        # yielded no rows it's skipped as a warning, not failed (honest empty state).
        "interact": {"click": ".row", "expect": ".pillar-detail", "desc": "pillar disclosure opens"},
    },
    {"path": "/story/", "name": "Story hub", "wait_for": "body"},
    {"path": "/data/", "name": "Data hub", "wait_for": "body"},
    {"path": "/data/vitals/", "name": "Evidence · vitals", "wait_for": "body", "charts": ["[data-readout] svg"]},
    {"path": "/protocols/", "name": "Protocols hub", "wait_for": "body"},
    {"path": "/coaching/", "name": "Coaching hub", "wait_for": "body"},
    {"path": "/method/character/", "name": "Method · character", "wait_for": "body"},
]

# ── API mocks ─────────────────────────────────────────────────────────────────
# The site's fetch layer is heavily try/caught + defensively coded (optional
# chaining, `|| []`, `?? 0`), so an empty object is a safe universal default: a
# page that gets it renders its honest empty state instead of throwing. A clean,
# in-range public_stats lets the accuracy impossible-number check run the exact
# same rubric as the post-deploy --live gate against the local render.
DEFAULT_API_MOCK = {}

CLEAN_PUBLIC_STATS = {
    "training": {"ctl_fitness": 42.0, "atl_fatigue": 38.0, "ctl": 42.0, "atl": 38.0},
    "journey": {"progress_pct": 61.0, "adherence_pct": 88.0},
    "vitals": {"recovery_pct": 74.0},
}


def _install_routes(context, extra_stats=None):
    """Wire the API mocks onto the browser context.

    ORDER MATTERS: the catch-all is registered FIRST so the specific mocks
    registered after it take precedence (reverse-order matching).
    """
    stats = extra_stats if extra_stats is not None else CLEAN_PUBLIC_STATS

    # 1) catch-all — anything under /api/** (and any un-mocked JSON) → empty object.
    def _catch_all(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(DEFAULT_API_MOCK))

    context.route("**/api/**", _catch_all)

    # 2) specific mocks — registered after, so they win.
    def _make(payload):
        def _h(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        return _h

    context.route("**/public_stats.json", _make(stats))
    context.route("**/moments/**", _make({}))
    # Generated JSON that lives in the S3 `generated/` prefix, not committed under
    # site/ — mock it empty so the static serve doesn't log a spurious 404 warning.
    context.route("**/journal/**", _make({}))


# ── Local static server ───────────────────────────────────────────────────────
def _serve(directory):
    """Start a threaded static file server for `directory` on an ephemeral port.

    Returns (base_url, shutdown_fn). Silences the default request logging so the
    gate output stays readable.
    """

    class _QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_a):  # noqa: D401 - silence access log
            pass

    handler = functools.partial(_QuietHandler, directory=directory)
    # Bind :0 to grab a free port (avoids the "port left bound after a crashed run"
    # trap called out in the handover render-QA notes).
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.socket.getsockname()[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{port}", httpd.shutdown


def _wait_port(host, port, timeout=5.0):
    import time

    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False


# ── Gate ──────────────────────────────────────────────────────────────────────
def run_gate(site_dir, screenshot_dir, keep=False):
    """Serve site_dir, drive the representative pages, run render + accuracy checks.

    Returns (ok: bool, results: list, accuracy_findings: list).
    """
    base_url, shutdown = _serve(site_dir)
    host, port = base_url.replace("http://", "").split(":")
    if not _wait_port(host, int(port)):
        print(f"❌ local server never came up on {base_url}")
        return False, [], []

    # capture_page reads visual_qa.SITE_URL at call time — point it local. Set the
    # env override BEFORE importing so a fresh interpreter also picks it up.
    os.environ["QA_SITE_URL"] = base_url
    sys.path.insert(0, HERE)
    import visual_qa as VQ

    VQ.SITE_URL = base_url
    import accuracy_audit as AA

    os.makedirs(screenshot_dir, exist_ok=True)
    results = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # service_workers="block" — SW-handled fetches bypass page.route.
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="dark",
                service_workers="block",
            )
            _install_routes(context)

            for page_def in GATE_PAGES:
                # capture_prose=True writes <slug>.txt (the visitor-facing text) so
                # the accuracy sentinel scan reads exactly what rendered.
                res = VQ.capture_page(context, page_def, screenshot_dir, save_screenshots=True, capture_prose=True)
                results.append(res)
                icon = "✅" if not res["issues"] else "❌"
                print(f"  {icon} {res['page']} ({res['path']})")
                for x in res["issues"]:
                    print(f"      → {x}")
                for w in res["warnings"]:
                    print(f"      ⚠ {w}")
            browser.close()
    finally:
        shutdown()

    # ── accuracy: impossible-number rubric + leaked-sentinel scan over the render ──
    accuracy = []
    # (a) impossible values in the (locally-served) public_stats — same rubric as --live.
    accuracy += AA.impossible_values(CLEAN_PUBLIC_STATS)
    # (b) leaked NaN/undefined/[object Object] in the rendered visitor prose we just
    #     captured (a render bug that stringifies a bad value shows up HERE).
    accuracy += AA.sanity_scan(screenshot_dir)

    render_ok = all(not r["issues"] for r in results)
    acc_high = [f for f in accuracy if f.get("severity") == "high"]

    print(f"\n{'=' * 60}")
    passed = sum(1 for r in results if not r["issues"])
    print(f"Render: {passed}/{len(results)} pages clean")
    print(f"Accuracy: {len(acc_high)} impossible-number/leak finding(s)")
    for f in acc_high:
        print(
            f"  ❌ {f.get('check', 'leak')}: {f.get('field') or f.get('source') or ''} {f.get('note') or f.get('snippet') or ''}".rstrip()
        )

    if not keep:
        # Leave the report.json-style artifact only when asked (CI uploads it).
        pass

    ok = render_ok and not acc_high
    return ok, results, accuracy


def main():
    ap = argparse.ArgumentParser(description="PR-time render + accuracy gate for the static site (#408).")
    ap.add_argument("--site-dir", default=os.path.join(REPO, "site"), help="Static site dir to serve (default: site/)")
    ap.add_argument("--out", default=None, help="Screenshot/prose capture dir (default: a temp dir)")
    ap.add_argument("--keep", action="store_true", help="Keep the capture dir after the run")
    args = ap.parse_args()

    site_dir = os.path.abspath(args.site_dir)
    if not os.path.isdir(site_dir):
        sys.exit(f"site dir not found: {site_dir}")

    out = args.out or tempfile.mkdtemp(prefix="pr-render-gate-")
    print(f"PR render + accuracy gate — serving {site_dir}\n  capture → {out}\n{'=' * 60}")

    ok, results, accuracy = run_gate(site_dir, out, keep=args.keep)

    # CI job summary (same convention as visual_qa).
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            lines = [f"## PR render + accuracy gate — {'PASS' if ok else 'FAIL'}\n"]
            for r in results:
                if r["issues"]:
                    lines.append(f"- ❌ **{r['page']}** (`{r['path']}`)")
                    for i in r["issues"]:
                        lines.append(f"  - 🔴 {i}")
            for f in [x for x in accuracy if x.get("severity") == "high"]:
                lines.append(f"- ❌ accuracy: {f.get('check', 'leak')} {f.get('field') or f.get('source') or ''}")
            with open(summary_path, "a") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:  # noqa: BLE001
            pass

    with open(os.path.join(out, "gate_report.json"), "w") as fh:
        json.dump({"ok": ok, "results": results, "accuracy": accuracy}, fh, indent=2)

    print(f"\n{'✅ GATE PASSED' if ok else '❌ GATE FAILED — regression blocked before merge'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
