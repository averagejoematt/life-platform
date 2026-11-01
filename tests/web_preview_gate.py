#!/usr/bin/env python3
"""tests/web_preview_gate.py — the pre-merge render gate for the v9 build (#5530, epic #5529).

Serves ``www/dist`` the way the S3 website origin will (under its base path, directory
URLs) and renders EVERY built page at a phone (390×844) and a laptop (1280×900), holding:

  1. No horizontal overflow at 390 px (document wider than the viewport).
  2. No JavaScript error, no failed request to the page's own origin.
  3. axe-core: zero serious or critical violations (light theme; the build is light-only).
  4. Words that must never render: "undefined", "NaN", "[object Object]", an ISO date, a
     "Thirty-seven" (the age the owner struck), and the fixture sentinels for a held or
     private object (the privacy gate measured on the OUTPUT, not just the snapshot).
  5. Every <script> has a src (the CSP is `script-src 'self'`; an inline script is a defect).
  6. The front page's phone height stays under its budget (7.5 screens since the owner's 2026-11-01 brief; six before).

MUTATION CONTROL (always runs first): a copy of the build with one page widened past the
viewport, an inline <script>, and a sentinel word MUST fail — a gate that cannot fail is a
green light wired to nothing (CHARTER §paved roads). The run exits 2 if the control passes.

Usage:
    python3 tests/web_preview_gate.py                      # gate www/dist (self-test first)
    python3 tests/web_preview_gate.py --dist www/dist --base /next/v9/ --out DIR   # + PNGs
Exit: 0 pass · 1 fail · 2 the mutation control did not fail (blind gate) · 3 setup error.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AXE_JS_PATH = os.path.join(HERE, "vendor", "axe.min.js")  # the bundle tests/a11y_audit.py vendors
AXE_GATING_IMPACTS = ("critical", "serious")
PHONE = {"width": 390, "height": 844}
LAPTOP = {"width": 1280, "height": 900}
FRONT_PAGE_SCREENS = 7.5  # was 6.0 (the kit's); raised 2026-11-01 for the owner's Start-page brief — the six-dimensional portrait and the chapter feature are on the front page by his ruling, not padding
FORBIDDEN = (
    (re.compile(r"\[object Object\]"), "a leaked non-value"),
    (re.compile(r"\b20\d\d-\d\d-\d\d\b"), "an ISO date (dates are written in words)"),
    (re.compile(r"\bThirty-seven\b"), "the age (never published)"),
    (re.compile(r"SENTINEL|POISON-HELD|DO-NOT-PUBLISH"), "a held/private fixture sentinel"),
)
_RUN_AXE_JS = """async () => {
    const r = await axe.run(document, {resultTypes: ['violations']});
    return r.violations.map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length,
        targets: v.nodes.slice(0, 2).map(n => (n.target || []).join(' '))}));
}"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_a):  # noqa: D401
        pass


@contextlib.contextmanager
def _serve(root: str):
    handler = functools.partial(_QuietHandler, directory=root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


def _mount(dist: str, base: str) -> str:
    """A temp root with dist mounted at the base path, as CloudFront + S3 will serve it."""
    root = tempfile.mkdtemp(prefix="web-gate-")
    target = os.path.join(root, base.strip("/")) if base.strip("/") else root
    if target != root:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.symlink(os.path.abspath(dist), target)
    else:
        shutil.rmtree(root)
        os.symlink(os.path.abspath(dist), root)
    return root


def pages_of(dist: str) -> list[str]:
    out = []
    for dirpath, _dirs, files in os.walk(dist):
        if "index.html" in files:
            rel = os.path.relpath(dirpath, dist)
            out.append("/" if rel == "." else f"/{rel}/")
    return sorted(out)


# `undefined` / `NaN` are English words in the methods registry's own prose ("skill is undefined
# against a degenerate base rate"), so the leak rule is positional: the whole text of an element,
# or the token beside a number, a unit or a separator — the shapes a template binding produces.
_PUBLISHED_BODY = re.compile(r"<div data-published-body[^>]*>[\s\S]*?</div>\s*(?=</article>)", re.IGNORECASE)
_LEAK_TOKEN = r"(?:undefined|NaN|null)"
_LEAK_RULES = (
    re.compile(rf"^\s*{_LEAK_TOKEN}\s*$"),  # the element says nothing else
    re.compile(rf"\b{_LEAK_TOKEN}\s+(?:of|lb|g|%|ms|bpm|kcal|h|min|steps|right|checked)\b"),
    re.compile(rf"(?:\bof|·|:|—|\d)\s*{_LEAK_TOKEN}\b"),
    re.compile(rf"\b{_LEAK_TOKEN}\s+{_LEAK_TOKEN}\b"),
)


def _leaked_values(html: str) -> list[str]:
    hits = []
    for seg in re.split(r"<[^>]+>", html):
        t = seg.strip()
        if not t:
            continue
        for rx in _LEAK_RULES:
            m = rx.search(t)
            if m:
                hits.append(t[:60])
                break
    return hits


def _static_checks(html: str, path: str) -> list[str]:
    issues = []
    for tag in re.findall(r"<script\b[^>]*>", html, re.IGNORECASE):
        if "src=" not in tag.lower():
            issues.append(f"{path}: inline <script> (CSP script-src 'self')")
    # A published body (a chapter or an essay, rendered as published — owner decision 12) is the
    # author's text, not the template's: the forbidden-word scan covers everything around it.
    scanned = _PUBLISHED_BODY.sub(" ", html)
    for hit in _leaked_values(scanned)[:3]:
        issues.append(f"{path}: a leaked non-value: {hit!r}")
    text = re.sub(r"<[^>]+>", " ", scanned)
    for rx, why in FORBIDDEN:
        m = rx.search(text)
        if m:
            issues.append(f"{path}: {why}: {m.group(0)!r}")
    return issues


def gate(dist: str, base: str, out_dir: str | None, verbose: bool = True) -> tuple[bool, list[dict]]:
    from playwright.sync_api import sync_playwright

    pages = pages_of(dist)
    if not pages:
        raise SystemExit("no pages in dist")
    axe_js = open(AXE_JS_PATH, encoding="utf-8").read()
    root = _mount(dist, base)
    results = []
    ok = True
    with _serve(root) as origin, sync_playwright() as p:
        browser = p.chromium.launch()
        for path in pages:
            url = f"{origin}{base.rstrip('/')}{path}"
            rec = {"path": path, "issues": [], "phone_screens": None}
            html = open(
                os.path.join(dist, path.strip("/"), "index.html") if path != "/" else os.path.join(dist, "index.html"), encoding="utf-8"
            ).read()
            rec["issues"].extend(_static_checks(html, path))
            for label, vp in (("phone", PHONE), ("laptop", LAPTOP)):
                ctx = browser.new_context(viewport=vp, color_scheme="light", service_workers="block")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("requestfailed", lambda r: errors.append(f"requestfailed: {r.url}") if r.url.startswith(origin) else None)
                page.on(
                    "response", lambda r: errors.append(f"{r.status} {r.url}") if r.url.startswith(origin) and r.status >= 400 else None
                )
                resp = page.goto(url, wait_until="load")
                if resp is None or resp.status != 200:
                    rec["issues"].append(f"{path}@{label}: status {resp.status if resp else 'none'}")
                page.wait_for_timeout(150)
                width = page.evaluate("() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
                if width > vp["width"]:
                    rec["issues"].append(f"{path}@{label}: horizontal overflow {width}px > {vp['width']}px")
                if label == "phone":
                    height = page.evaluate("() => document.documentElement.scrollHeight")
                    rec["phone_screens"] = round(height / vp["height"], 2)
                    if path == "/" and rec["phone_screens"] > FRONT_PAGE_SCREENS:
                        rec["issues"].append(f"/: {rec['phone_screens']} phone screens > budget {FRONT_PAGE_SCREENS}")
                    page.add_script_tag(content=axe_js)
                    viol = [v for v in page.evaluate(_RUN_AXE_JS) if v["impact"] in AXE_GATING_IMPACTS]
                    for v in viol:
                        rec["issues"].append(f"{path}@phone axe {v['impact']} {v['id']} ×{v['nodes']} {v['targets']}")
                rec["issues"].extend(f"{path}@{label}: {e}" for e in errors)
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    slug = "home" if path == "/" else path.strip("/").replace("/", "_")
                    page.screenshot(path=os.path.join(out_dir, f"{slug}-{label}.png"), full_page=True)
                ctx.close()
            results.append(rec)
            ok = ok and not rec["issues"]
            if verbose:
                mark = "✓" if not rec["issues"] else "✗"
                print(f"  {mark} {path}  ({rec['phone_screens']} phone screens)")
                for i in rec["issues"]:
                    print(f"      - {i}")
        browser.close()
    shutil.rmtree(root, ignore_errors=True)
    return ok, results


def mutation_control(dist: str, base: str) -> bool:
    """Plant three defects in a COPY of the build; the gate must report all three classes."""
    tmp = tempfile.mkdtemp(prefix="web-gate-control-")
    shutil.copytree(dist, tmp, dirs_exist_ok=True)
    idx = os.path.join(tmp, "index.html")
    html = open(idx, encoding="utf-8").read()
    html = html.replace(
        "</body>", '<div style="width:2000px;height:2px"></div><script>var x=1</script><p>HELD-SENTINEL-DO-NOT-PUBLISH</p></body>'
    )
    open(idx, "w", encoding="utf-8").write(html)
    ok, results = gate(tmp, base, None, verbose=False)
    shutil.rmtree(tmp, ignore_errors=True)
    front = next(r for r in results if r["path"] == "/")
    text = "\n".join(front["issues"])
    found = ("horizontal overflow" in text, "inline <script>" in text, "sentinel" in text)
    return (not ok) and all(found)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render gate for the v9 static build.")
    ap.add_argument("--dist", default=os.path.join(REPO, "www", "dist"))
    ap.add_argument("--base", default=os.environ.get("WEB_BASE", "/next/v9/"))
    ap.add_argument("--out", default=None, help="save full-page PNGs per page and viewport")
    ap.add_argument("--skip-control", action="store_true", help="skip the mutation control (local iteration only)")
    args = ap.parse_args()
    if not os.path.isdir(args.dist):
        print(f"dist not found: {args.dist} — run `npm run build:preview` in www/ first", file=sys.stderr)
        return 3
    if not os.path.exists(AXE_JS_PATH):
        print(f"axe bundle missing: {AXE_JS_PATH}", file=sys.stderr)
        return 3
    if not args.skip_control:
        print("mutation control …", end=" ", flush=True)
        if not mutation_control(args.dist, args.base):
            print("FAILED — the gate did not report a planted overflow + inline script + sentinel; refusing to grade")
            return 2
        print("ok (the gate can fail)")
    print(f"web preview gate — {args.dist} at base {args.base}")
    ok, results = gate(args.dist, args.base, args.out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## v9 preview render gate — {'PASS' if ok else 'FAIL'} ({len(results)} pages)\n\n")
            for r in results:
                if r["issues"]:
                    fh.write(f"- ❌ `{r['path']}`\n" + "".join(f"  - {i}\n" for i in r["issues"]))
    if args.out:
        with open(os.path.join(args.out, "gate_report.json"), "w", encoding="utf-8") as fh:
            json.dump({"ok": ok, "pages": results}, fh, indent=1)
    print(f"\n{'✅ GATE PASSED' if ok else '❌ GATE FAILED'} — {len(results)} pages, {sum(1 for r in results if r['issues'])} with issues")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
