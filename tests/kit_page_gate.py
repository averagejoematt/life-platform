#!/usr/bin/env python3
"""
kit_page_gate.py — the pre-merge gate for the kit pages of the living front page
(#4586, epic #4580; the look is docs/design/v8).

What it holds, per page in KIT_PAGES, rendered at a phone (390x844) from a local static
serve of site/ with the data routes mocked by committed fixtures
(tests/fixtures/kit_pages_4586/ — one live capture, scripts/capture_kit_page_fixtures.py, its
time in _capture.json; never fetched here):

  1. HEIGHT. A page taller than its phone-screen budget fails: six screens for the front
     page, four elsewhere. The owner approved "about three and a half phone screens, one
     idea per section"; a page that grows past its budget has stopped being that page.
  2. No horizontal overflow at 390 px.
  3. No JS error, and the page reaches its ready mark (`data-ck-ready`).
  4. axe: zero serious or critical violations, in light and in dark.
  5. Words that must never render: "Dr." on a persona, "undefined", "NaN", an ISO date.

It runs BEFORE merge only (v4-gate.yml, the render job). It is never a deploy rollback:
page height depends on the day's data, so a long chapter title on a Wednesday must not
revert a deploy. The fixtures pin the data, and the browser's clock is pinned to the
fixtures' capture instant (`_capture.json: captured_at`), so the verdict is about the page:
a page that lists what is "upcoming" or "today" against the Pacific wall clock
(ck_coach.js isUpcoming/todayPT) must not change height as the calendar moves past the
capture (the #4848 class — on 2026-10-17 the physical coach page crossed its budget by
17 px with no site change, the day after the fixture's last due date).

MUTATION CONTROL (always runs first): the same harness is pointed at an over-long edition
— the coach lines inflated to 40 — and MUST report the height failure. A gate
that cannot fail that page is blind, and the run exits 2 without grading anything.

Usage:
    python3 tests/kit_page_gate.py                # gate (self-test first)
    python3 tests/kit_page_gate.py --out DIR      # also save a full-page PNG per page
"""

import argparse
import copy
import datetime
import functools
import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIXTURES_DIR = os.path.join(HERE, "fixtures", "kit_pages_4586")


def captured_at() -> datetime.datetime:
    """The instant the fixtures were captured (`_capture.json`), as an aware datetime: the
    browser clock every page is rendered under, so a day-relative list cannot move the verdict."""
    with open(os.path.join(FIXTURES_DIR, "_capture.json"), encoding="utf-8") as fh:
        stamp = json.load(fh)["captured_at"]
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


VIEWPORT = {"width": 390, "height": 844}
AXE_JS_PATH = os.path.join(HERE, "vendor", "axe.min.js")  # the bundle tests/a11y_audit.py vendors
AXE_GATING_IMPACTS = ("critical", "serious")
_RUN_AXE_JS = """async () => {
    const r = await axe.run(document, {resultTypes: ['violations']});
    return r.violations.map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length,
        targets: v.nodes.slice(0, 2).map(n => (n.target || []).join(' '))}));
}"""

#: path -> phone-screen budget. Adding a kit page means adding it here.
KIT_PAGES = {
    # The four kit pages at their live paths (#4588). Their /next/v8/ originals and the kit's deep pages (week, day,
    # trend, sheet, built, coach, call, appendix) were retired with the /next/ preview in #6223, and their budgets
    # left this table with them: a page that is not in site/ cannot be rendered from it.
    "/": 6,
    "/start/": 4,
    "/story/": 4,
    # #4808/#4809 (ruling 2026-10-11): four screens stand — the bet's reasons are the front
    # card's, and this page's bet card carries a door to them instead of printing both.
    # #4839: 4.25. The live record block now serves #4617's `counted_text` (what the big count
    # counts: sealed, bets, commentary, conditional - one four-line sentence under the number),
    # which the fixtures lacked until the recapture. That is +0.17 screens (3.83 -> 4.0 locally,
    # 4.06 on the Linux CI renderer). The sentence is the point of #4617, so the budget gives
    # it a quarter screen rather than the sentence being cut.
    "/coaches/": 4.25,
}

#: route glob -> fixture file. Every route the kit pages' modules read.
ROUTES = {
    "**/api/edition": "edition.json",
    "**/journal/posts.json": "posts.json",
    "**/panelcast/episodes.json": "episodes.json",
    "**/api/coaches": "coaches.json",
    "**/api/coach_docket": "coach_docket_full.json",  # every field the coach page reads; the same four dates
    "**/api/coach/sleep_coach": "coach_sleep_coach.json",
    "**/api/coach/physical_coach": "coach_physical_coach.json",
    "**/api/coach/glucose_coach": "coach_glucose_coach.json",
    "**/api/coach/eli_marsh": "coach_eli_marsh.json",
    "**/api/predictions?coach_id=sleep&*": "predictions_sleep.json",
    "**/api/predictions?coach_id=physical&*": "predictions_physical.json",
    "**/api/predictions?coach_id=glucose&*": "predictions_glucose.json",
    "**/api/timeline": "timeline.json",
    "**/api/pulse_history": "pulse_history.json",
    "**/api/workouts": "workouts.json",
    "**/api/training_overview": "training_overview.json",
    "**/api/nutrition_overview": "nutrition_overview.json",
    "**/api/frequent_meals": "frequent_meals.json",
    "**/api/weekly_priority": "weekly_priority.json",
    "**/api/character": "character.json",
    "**/api/achievements": "achievements.json",
    "**/panelcast/wk4.transcript.json": "transcript_wk4.json",
    "**/api/platform_stats": "platform_stats.json",
    "**/api/receipts": "receipts.json",
    "**/api/predictions": "predictions.json",
    "**/api/calls": "calls.json",  # ck_call.js
}
#: ck_depth.js asks GET /api/coach_moves?date=<day> for the day it shows (#4648). One capture per
#: day the gate opens, written by scripts/capture_kit_page_fixtures.py; a day with no file gets
#: the catch-all {} (no lines).
ROUTES.update(
    {
        f"**/api/coach_moves?date={name[len('coach_moves_'):-len('.json')]}": name
        for name in sorted(os.listdir(FIXTURES_DIR))
        if name.startswith("coach_moves_") and name.endswith(".json")
    }
)

_FORBIDDEN = (
    (re.compile(r"\bDr\.\s"), "an honorific on a persona"),
    (re.compile(r"\bundefined\b|\bNaN\b|\[object Object\]"), "a leaked non-value"),
    (re.compile(r"\b20\d\d-\d\d-\d\d\b"), "an ISO date (dates are written in words)"),
)


def _fixtures():
    return {glob: json.load(open(os.path.join(FIXTURES_DIR, name), encoding="utf-8")) for glob, name in ROUTES.items()}


def _over_long(fixtures):
    """The mutation: an edition whose coach lines run far past any budget. Each line is made one the
    front page may quote (a plain-language `call` by a coach other than the mind coach — ck_front.js
    frontQuotable, red team 2026-10-17): a capture whose day's line is one the front page leaves out
    would otherwise make a control the page never prints, which is blind."""
    mutated = copy.deepcopy(fixtures)
    lines = mutated["**/api/edition"]["blocks"]["coach_lines"]["data"]["lines"]
    mutated["**/api/edition"]["blocks"]["coach_lines"]["data"]["lines"] = [
        dict(
            lines[i % len(lines)],
            move="call",
            coach_id="sleep_coach",
            domain="sleep",
            text=f"The control line number {i} is long enough to wrap twice on a phone screen.",
        )
        for i in range(40)
    ]
    return mutated


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_a):
        pass


def _serve(directory):
    """A static server for `directory` on a free port -> (base_url, shutdown). Local to this
    file on purpose: importing the render gate's copy would pull its whole import graph
    (boto3, pillow) into a CI job that installs only playwright."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=directory))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.socket.getsockname()[1]}", httpd.shutdown


def run_axe(page):
    """axe's violations on `page`. The bundle goes in by page.evaluate, never a script tag
    (the site CSP blocks inline script). Stdlib-only on purpose: tests/a11y_audit.py's
    import graph reaches boto3, which this CI job does not install. Raises if axe did not
    load — a pass that did not run is not a pass."""
    with open(AXE_JS_PATH, encoding="utf-8") as fh:
        page.evaluate(fh.read())
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        raise RuntimeError("axe bundle evaluated but window.axe is undefined — the audit did not run")
    return page.evaluate(_RUN_AXE_JS)


def _serve_json(payload):
    body = json.dumps(payload)
    return lambda route: route.fulfill(status=200, content_type="application/json", body=body)


def measure(browser, base_url, fixtures, pages, out_dir=None, axe=True):
    """Render each page and return {path: {"height", "screens", "findings": [...]}}."""
    results = {}
    for theme in ("light", "dark") if axe else ("light",):
        context = browser.new_context(viewport=VIEWPORT, color_scheme=theme, service_workers="block")
        context.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body="{}"))
        for glob, payload in fixtures.items():
            context.route(glob, _serve_json(payload))
        context.route("**/*.mp3", lambda route: route.fulfill(status=200, content_type="audio/mpeg", body=b""))
        for path, budget in pages.items():
            res = results.setdefault(path, {"findings": []})
            page = context.new_page()
            page.clock.set_fixed_time(captured_at())  # the fixtures' instant, not the wall clock (#4848 class)
            errors = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
            page.goto(base_url + path, wait_until="networkidle")
            try:
                page.wait_for_function("document.body.dataset.ckReady === '1'", timeout=15000)
            except Exception:  # noqa: BLE001 — the finding is the report
                res["findings"].append(f"[{theme}] never reached its ready mark (data-ck-ready)")
            for err in errors:
                res["findings"].append(f"[{theme}] JS error: {err[:200]}")
            if theme == "light":
                height = page.evaluate("document.documentElement.scrollHeight")
                res["height"], res["screens"] = height, round(height / VIEWPORT["height"], 2)
                if height > budget * VIEWPORT["height"]:
                    res["findings"].append(
                        f"{res['screens']} phone screens tall — the budget is {budget} ({height}px > {budget * VIEWPORT['height']}px)"
                    )
                if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                    res["findings"].append("horizontal overflow at 390px")
                text = page.inner_text("body")
                for rx, what in _FORBIDDEN:
                    hit = rx.search(text)
                    if hit:
                        res["findings"].append(f"renders {what}: {text[max(0, hit.start() - 30):hit.end() + 30]!r}")
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    page.screenshot(
                        path=os.path.join(out_dir, (re.sub(r"[^A-Za-z0-9._-]+", "_", path).strip("_") or "root") + ".png"), full_page=True
                    )
            if axe:
                for v in run_axe(page):
                    if v["impact"] in AXE_GATING_IMPACTS:
                        res["findings"].append(f"[{theme}] axe {v['impact']}: {v['id']} ({v['nodes']} node(s)) {v['targets'][:2]}")
            page.close()
        context.close()
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default=os.path.join(REPO, "site"))
    ap.add_argument("--out", default=None, help="directory for full-page PNGs")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    base_url, shutdown = _serve(args.site)
    fixtures = _fixtures()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            control = measure(browser, base_url, _over_long(fixtures), {"/": KIT_PAGES["/"]}, axe=False)
            if not any("phone screens tall" in f for f in control["/"]["findings"]):
                print(f"kit_page_gate: BLIND — the over-long control page passed the height check ({control['/']})")
                return 2
            print(f"control: an over-long front page ({control['/']['screens']} screens) fails, as it must")
            results = measure(browser, base_url, fixtures, KIT_PAGES, out_dir=args.out)
            browser.close()
    finally:
        shutdown()

    failed = False
    for path, res in results.items():
        mark = "FAIL" if res["findings"] else "ok  "
        print(f"{mark} {path}  {res.get('screens')} of {KIT_PAGES[path]} screens")
        for finding in res["findings"]:
            failed = True
            print(f"       - {finding}")
    print("kit_page_gate: " + ("FAILED" if failed else "clean"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
