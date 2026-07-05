#!/usr/bin/env python3
"""
pr_render_gate.py — PR-time LOCAL render + accuracy gate for the static site (#408).

Shifts render/accuracy QA LEFT. Today the Playwright visual sweep + the accuracy audit
run only POST-deploy, against the live site, and only when backend code ships — so a
site-only PR (the change most likely to break a page) gets just an HTML well-formedness
check before merge (see .github/workflows/v4-gate.yml). This gate reuses the SAME
harness (tests/visual_qa.py) but points it at site/ served from a LOCAL http.server, so
a broken layout or a leaked/impossible number is caught before merge — not after it is
already live. The post-deploy live jobs stay in place; this supplements, never replaces.

How it stays fast + non-flaky (the render-QA reflexes, per handovers/HANDOVER_LATEST.md
+ memory/reference_local_render_qa.md):
  * Serves site/ over http.server so absolute /assets paths + ES-module imports resolve
    (file:// can't load modules); binds an ephemeral port so a crashed prior run can't
    collide.
  * Route-mocks **/api/** with empty-but-valid JSON — the catch-all is registered FIRST
    (Playwright matches routes in REVERSE registration order) — and BLOCKS the service
    worker (SW-handled fetches bypass page.route entirely). Pages therefore render their
    honest empty states offline, with no live data and no network.
  * Serves the public_stats.json fixture (tests/fixtures/pr_gate/) so home renders and
    the impossible-number check has something to grade.

What FAILS the gate (render-class + accuracy HIGH only):
  * an uncaught JS error / pageerror on any representative page (front-end code bug),
  * horizontal overflow at 390px or 1440px (a real layout break — CSS-driven, so it
    shows with or without data),
  * stuck/placeholder copy that should never ship (Loading…., pre-launch, lorem, TODO),
  * a leaked sentinel (NaN / undefined / [object Object]) in the rendered prose,
  * an impossible number in public_stats (negative CTL/ATL, pct out of [0,100]).

What does NOT fail it (honest empty states pass — AC#5): the data-content checks
(min_count / not_empty / broken-API / missing-chart / empty-section / perf budget) are
all EXPECTED under the empty API mock and are reported as info only. Live data validation
stays in the post-deploy visual-qa + accuracy jobs.

Usage:
  python3 tests/pr_render_gate.py            # representative sweep (CI default)
  python3 tests/pr_render_gate.py -v         # also print the info (data-absent) notes
Requires: playwright + chromium (`python3 -m playwright install chromium`).
"""

import argparse
import functools
import http.server
import json
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITE_DIR = os.path.join(ROOT, "site")
FIXTURE = os.path.join(HERE, "fixtures", "pr_gate", "public_stats.json")

# One representative page per template / JS module — spans the whole front-end without
# sweeping all ~40 pages (fast). Home (story.js/constellation), Cockpit (cockpit.js),
# Data hub + a data topic (evidence.js, chart path), Protocols (evidence.js), Coaching
# (coaching.js), Story (dispatches), a Method explainer. These paths are looked up in
# visual_qa.PAGES so we reuse its exact per-page check + capture definitions.
REPRESENTATIVE_PATHS = [
    "/",
    "/now/",
    "/data/",
    "/data/vitals/",
    "/protocols/",
    "/coaching/",
    "/story/",
    "/method/character/",
]

# Issue-string prefixes that are RENDER-class (fatal at PR time). Everything else that
# capture_page can emit is data-dependent and expected-empty under the API mock.
_FATAL_MARKERS = ("Horizontal overflow", "JS error", "Stale text", "Page load failed")


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Static file server rooted at site/, with one overlay: /public_stats.json is
    served from the committed fixture (it's a generated/ file, never in site/)."""

    def log_message(self, *args):  # silence per-request noise
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/public_stats.json":
            try:
                with open(FIXTURE, "rb") as f:
                    body = f.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def _serve():
    port = _free_port()
    handler = functools.partial(_Handler, directory=SITE_DIR)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def _classify(results):
    """Split capture_page issues into fatal (render-class) vs info (data-absent)."""
    fatal, info = [], []
    for r in results:
        for iss in r.get("issues", []):
            (fatal if iss.startswith(_FATAL_MARKERS) else info).append((r["path"], iss))
    return fatal, info


def run(verbose=False):
    # Point the shared harness at the local origin BEFORE importing it — visual_qa reads
    # QA_SITE_URL at import, and accuracy_audit inherits it via site_review.
    httpd, port = _serve()
    os.environ["QA_SITE_URL"] = f"http://127.0.0.1:{port}"
    sys.path.insert(0, HERE)
    import accuracy_audit as AA  # noqa: E402
    import visual_qa as VQ  # noqa: E402
    from playwright.sync_api import sync_playwright  # noqa: E402

    by_path = {p["path"]: p for p in VQ.PAGES}
    missing = [p for p in REPRESENTATIVE_PATHS if p not in by_path]
    if missing:
        print(f"::error::representative path(s) not in visual_qa.PAGES: {missing}")
        return 2
    page_defs = [by_path[p] for p in REPRESENTATIVE_PATHS]

    run_dir = os.path.join(ROOT, "qa-screenshots", "pr-gate")
    os.makedirs(run_dir, exist_ok=True)

    print(f"PR render gate — serving site/ at http://127.0.0.1:{port}")
    print(f"Representative pages: {len(page_defs)}\n{'=' * 56}")

    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            # service_workers='block' — SW-handled fetches bypass page.route (bit 2026-07-05).
            context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", service_workers="block")
            # Catch-all FIRST: **/api/** → empty-but-valid JSON so pages render honest
            # empty states with no live data (routes match in reverse-registration order).
            context.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
            for pdef in page_defs:
                res = VQ.capture_page(context, pdef, run_dir, save_screenshots=False, capture_prose=True)
                results.append(res)
                fat = [i for i in res["issues"] if i.startswith(_FATAL_MARKERS)]
                icon = "❌" if fat else "✅"
                print(f"  {icon} {res['page']} ({res['path']})")
                for i in res["issues"]:
                    tag = "→ FATAL" if i.startswith(_FATAL_MARKERS) else "· info "
                    if tag == "→ FATAL" or verbose:
                        print(f"      {tag} {i}")
            browser.close()
    finally:
        httpd.shutdown()

    fatal, info = _classify(results)

    # ── accuracy: leaked sentinels in rendered prose + impossible numbers in stats ──
    prose = [f for f in AA.sanity_scan(run_dir) if f.get("severity") == "high"]
    try:
        with open(FIXTURE) as f:
            stats = json.load(f)
        impossible = AA.impossible_values(stats)
    except Exception as e:  # noqa: BLE001
        impossible = [{"check": "impossible_value", "severity": "high", "note": f"fixture load failed: {e}"}]

    print(f"\n{'=' * 56}\nAccuracy — {len(prose)} prose leak(s), {len(impossible)} impossible number(s)")
    for f in prose:
        print(f"  ❌ leak in {f['source']}: {f['snippet']}")
    for f in impossible:
        print(f"  ❌ {f.get('field', '')} = {f.get('value', '')} — {f.get('note', '')}".rstrip())

    total_fatal = len(fatal) + len(prose) + len(impossible)
    print(f"\n{'=' * 56}")
    print(f"Render-class failures: {len(fatal)} · prose leaks: {len(prose)} · impossible numbers: {len(impossible)}")
    print(f"(info-only data-absent notes: {len(info)} — expected under the empty API mock)")
    if total_fatal:
        print("\n❌ PR render gate FAILED")
        for path, iss in fatal:
            print(f"  {path}: {iss}")
        return 1
    print("\n✅ PR render gate passed — no render-class or accuracy regressions")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PR-time local render + accuracy gate (#408)")
    ap.add_argument("-v", "--verbose", action="store_true", help="also print info (data-absent) notes")
    args = ap.parse_args()
    sys.exit(run(verbose=args.verbose))
