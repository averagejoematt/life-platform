#!/usr/bin/env python3
"""tests/web_preview_gate.py — the pre-merge render gate for the v9 build (#5530, epic #5529).

Serves ``www/dist`` the way the S3 website origin will (under its base path, directory
URLs) and renders EVERY built page at a phone (390×844) and a laptop (1280×900), holding:

  1. No horizontal overflow at 390 px (document wider than the viewport).
  2. No JavaScript error, no failed request to the page's own origin.
  3. axe-core: zero serious or critical violations (light theme; the build is light-only).
  4. Words that must never render: "undefined", "NaN", "[object Object]", a "Thirty-seven" (the age
     the owner struck), and the fixture sentinels for a held or private object (the privacy gate
     measured on the OUTPUT, not just the snapshot) — scanned INSIDE quotations too. An ISO date is
     held by scripts/www_verbatim.py: forbidden everywhere except inside a verbatim coach quotation
     (`<q|blockquote data-verbatim="coach">`, text and <time> only, never in a heading, and — given
     the snapshot — only words the snapshot carries; owner ruling 2026-11-02).
  5. Every <script> has a src (the CSP is `script-src 'self'`; an inline script is a defect).
  6. The front page's phone height stays under its budget (7.5 screens since the owner's 2026-11-01 brief; six before).
  7. Every chart answers (#5578, A01): each <svg data-points> has the inspect island mounted on it
     (data-inspect="mounted") once the page has loaded — a chart a reader cannot read point by point is a defect.
  8. SVG text floor (#5597, mirrors qa/visual_qa.py #1210): every `svg text` renders >= 11 px effective at 390
     and 360 — computed font-size x the live getScreenCTM scale (rendered width / viewBox width).

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
sys.path.insert(0, os.path.join(REPO, "scripts"))
import www_verbatim  # noqa: E402 — the quote-aware dates-in-words rule; one rule, two callers (check_www_build.scan)

SNAPSHOT = os.path.join(REPO, "www", "content", "snapshot")
AXE_JS_PATH = os.path.join(HERE, "vendor", "axe.min.js")  # the bundle tests/a11y_audit.py vendors
AXE_GATING_IMPACTS = ("critical", "serious")
PHONE = {"width": 390, "height": 844}
LAPTOP = {"width": 1280, "height": 900}
FRONT_PAGE_SCREENS = 7.5  # was 6.0 (the kit's); raised 2026-11-01 for the owner's Start-page brief — the six-dimensional portrait and the chapter feature are on the front page by his ruling, not padding
FORBIDDEN = (
    (re.compile(r"\[object Object\]"), "a leaked non-value"),
    (re.compile(r"\bThirty-seven\b"), "the age (never published)"),
    (re.compile(r"SENTINEL|POISON-HELD|DO-NOT-PUBLISH"), "a held/private fixture sentinel"),
)
SVG_TEXT_FLOOR_PX = 11.0  # qa/visual_qa.py SVG_TEXT_FLOOR_PX (#1210); same selector, scale (hypot of the screen CTM) and tolerance
SVG_TEXT_WIDTHS = (("phone", 390), ("phone360", 360))
_SVG_TEXT_AUDIT_JS = """(floor) => {
    const out = [];
    document.querySelectorAll('svg text').forEach(t => {
        const txt = (t.textContent || '').trim();
        if (!txt) return;
        let box; try { box = t.getBoundingClientRect(); } catch (e) { return; }
        if (!box || box.width < 1 || box.height < 1) return;
        const cs = getComputedStyle(t);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        const fs = parseFloat(cs.fontSize) || 0;
        let scale = 1;
        try { const m = t.getScreenCTM(); if (m) { const s = Math.hypot(m.a, m.b); if (s > 0) scale = s; } } catch (e) {}
        const eff = fs * scale;
        if (eff < floor - 0.05) out.push({txt: txt.slice(0, 24), eff: Math.round(eff * 100) / 100});
    });
    return out;
}"""
# Two labels on top of each other, or a label running out of its chart's frame (the Journey at 390 px on 2 November:
# the baseline-change label sat on the 320 milestone and the projected date was clipped at the right edge). Boxes are
# the rendered glyph boxes; a 1 px touch is not an overlap.
_SVG_TEXT_LAYOUT_JS = """() => {
    const out = [];
    document.querySelectorAll('svg').forEach(svg => {
        const frame = svg.getBoundingClientRect();
        if (frame.width < 1 || frame.height < 1) return;
        const ts = [...svg.querySelectorAll('text')].filter(t => (t.textContent || '').trim()).map(t => {
            let b; try { b = t.getBoundingClientRect(); } catch (e) { return null; }
            return b && b.width >= 1 ? {txt: t.textContent.trim().slice(0, 24), b} : null;
        }).filter(Boolean);
        for (const t of ts) {
            if (t.b.left < frame.left - 1 || t.b.right > frame.right + 1 || t.b.top < frame.top - 1 || t.b.bottom > frame.bottom + 1)
                out.push({kind: 'clipped', a: t.txt, b: ''});
        }
        for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) {
            const a = ts[i].b, b = ts[j].b;
            const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (w > 1 && h > 1) out.push({kind: 'overlap', a: ts[i].txt, b: ts[j].txt});
        }
    });
    return out;
}"""
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


def _static_checks(html: str, path: str, quotes: set[str] | None = None) -> list[str]:
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
    for rx, why in FORBIDDEN:  # quotations are NOT stripped here: a sentinel or the age inside a quote still fails
        m = rx.search(text)
        if m:
            issues.append(f"{path}: {why}: {m.group(0)!r}")
    # dates in words, except inside a verbatim coach quotation — structure, ISO and (with the snapshot) provenance
    issues.extend(www_verbatim.page_issues(html, path, quotes))
    return issues


def _layout_issues(page, path: str, where: str) -> list[str]:
    out = []
    for f in page.evaluate(_SVG_TEXT_LAYOUT_JS):
        if f["kind"] == "clipped":
            out.append(f"{path}@{where}: SVG text clipped by its chart frame: '{f['a']}'")
        else:
            out.append(f"{path}@{where}: SVG labels overlap: '{f['a']}' × '{f['b']}'")
    return out


def gate(dist: str, base: str, out_dir: str | None, verbose: bool = True, snapshot: str = SNAPSHOT) -> tuple[bool, list[dict]]:
    from playwright.sync_api import sync_playwright

    quotes = www_verbatim.verbatim_strings(snapshot) if os.path.isdir(snapshot) else None
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
            rec["issues"].extend(_static_checks(html, path, quotes))
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
                    for wlabel, w in SVG_TEXT_WIDTHS:
                        if w != vp["width"]:
                            page.set_viewport_size({"width": w, "height": vp["height"]})
                            page.wait_for_timeout(150)
                        for f in page.evaluate(_SVG_TEXT_AUDIT_JS, SVG_TEXT_FLOOR_PX):
                            rec["issues"].append(
                                f"{path}@{wlabel}: SVG text below {SVG_TEXT_FLOOR_PX:g}px floor: '{f['txt']}' = {f['eff']}px effective (#1210)"
                            )
                        rec["issues"].extend(_layout_issues(page, path, wlabel))
                    page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                if label == "laptop":
                    rec["issues"].extend(_layout_issues(page, path, label))
                    unmounted = page.evaluate(
                        "() => [...document.querySelectorAll('svg[data-points]')].filter(s => s.dataset.inspect !== 'mounted' && JSON.parse(s.dataset.points || '[]').length).length"
                    )
                    if unmounted:
                        rec["issues"].append(f"{path}@{label}: {unmounted} chart(s) with data-points but no inspect island mounted (#5578)")
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


def _dated_quote(snapshot: str) -> str | None:
    """A coach string from the snapshot that carries an ISO date — the positive control's quotation (the fixture
    ships one: tests/fixtures …/predictions.json `physical-20261016-weight02`). None = the control cannot run."""
    if not os.path.isdir(snapshot):
        return None
    return next((q for q in sorted(www_verbatim.verbatim_strings(snapshot)) if www_verbatim.ISO_DATE.search(q)), None)


def mutation_control(dist: str, base: str, snapshot: str = SNAPSHOT) -> bool:
    """Plant defects in a COPY of the build; the gate must report every class — and must NOT report the one
    sanctioned exception (an ISO date inside a verbatim coach quotation the snapshot carries)."""
    import html as _html

    said = _dated_quote(snapshot)
    if said is None:
        print("the snapshot carries no coach quotation with an ISO date — the quote exemption cannot be proven", file=sys.stderr)
        return False
    tmp = tempfile.mkdtemp(prefix="web-gate-control-")
    shutil.copytree(dist, tmp, dirs_exist_ok=True)
    # The positive control lives on its own page so the front page's planted ISO dates cannot mask it.
    sys_idx = os.path.join(tmp, "system", "index.html")
    sys_html = open(sys_idx, encoding="utf-8").read()
    sys_html = sys_html.replace("</main>", f'<p><q data-verbatim="coach">{_html.escape(said, quote=False)}</q></p></main>', 1)
    open(sys_idx, "w", encoding="utf-8").write(sys_html)
    # …and the other FORBIDDEN rules still scan INSIDE a quotation: a sentinel quoted on an otherwise clean page.
    priv_idx = os.path.join(tmp, "privacy", "index.html")
    priv_html = open(priv_idx, encoding="utf-8").read()
    open(priv_idx, "w", encoding="utf-8").write(
        priv_html.replace(
            "</main>",
            '<p><q data-verbatim="coach">POISON-HELD inside a quote</q></p>'
            # the unmounted chart lives on a page that loads no island: the front page now loads the inspector (The Line,
            # 2026-11-14), which mounts every chart on its page — a planted one included — so the defect could not show there
            '<svg viewBox="0 0 10 10" data-points="[{&quot;x&quot;:1,&quot;y&quot;:1,&quot;label&quot;:&quot;planted&quot;}]"></svg></main>',
            1,
        )
    )
    idx = os.path.join(tmp, "index.html")
    html = open(idx, encoding="utf-8").read()
    html = html.replace(
        "</body>",
        '<div style="width:2000px;height:2px"></div><script>var x=1</script><p>HELD-SENTINEL-DO-NOT-PUBLISH</p>'
        '<svg viewBox="0 0 1000 100" width="100%"><text x="10" y="50" font-size="20">PLANTED-SMALL</text></svg>'
        '<svg viewBox="0 0 300 60" width="300" height="60"><text x="10" y="30" font-size="14">PLANTED-A</text>'
        '<text x="14" y="32" font-size="14">PLANTED-B</text><text x="280" y="50" font-size="14">PLANTED-CLIP</text></svg>'
        # dates in words: authored copy, a correction, a quote in a heading, a borrowed exemption
        "<p>Planted authored copy dated 2031-01-02.</p>"
        '<p class="correction" role="note">Correction: planted on 2031-01-03.</p>'
        '<h2><q data-verbatim="coach">PLANTED heading quote</q></h2>'
        '<p><q data-verbatim="coach">Planted authored words borrowing the exemption on 2031-01-04.</q></p></body>',
    )
    open(idx, "w", encoding="utf-8").write(html)
    ok, results = gate(tmp, base, None, verbose=False, snapshot=snapshot)
    shutil.rmtree(tmp, ignore_errors=True)
    front = next(r for r in results if r["path"] == "/")
    text = "\n".join(front["issues"])
    system = "\n".join(next(r for r in results if r["path"] == "/system/")["issues"])
    privacy = "\n".join(next(r for r in results if r["path"] == "/privacy/")["issues"])
    found = (
        "horizontal overflow" in text,
        "inline <script>" in text,
        "sentinel" in text,
        "no inspect island" in privacy,
        "SVG text below 11px floor: 'PLANTED-SMALL'" in text,
        "SVG labels overlap: 'PLANTED-A' × 'PLANTED-B'" in text,
        "SVG text clipped by its chart frame: 'PLANTED-CLIP'" in text,
        "2031-01-02" in text,  # authored copy: still dates in words
        "2031-01-03" in text,  # a correction is authored copy
        "inside <h2>" in text,  # a heading is never a verbatim container
        "the snapshot never carried" in text,  # authored words cannot borrow the exemption (2031-01-04)
        "held/private fixture sentinel" in privacy,  # the other FORBIDDEN rules still scan inside quotations
        "ISO date" not in system and "verbatim" not in system,  # the sanctioned exception passes
    )
    return (not ok) and all(found)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render gate for the v9 static build.")
    ap.add_argument("--dist", default=os.path.join(REPO, "www", "dist"))
    ap.add_argument("--base", default=os.environ.get("WEB_BASE", "/next/v9/"))
    ap.add_argument("--out", default=None, help="save full-page PNGs per page and viewport")
    ap.add_argument("--skip-control", action="store_true", help="skip the mutation control (local iteration only)")
    ap.add_argument("--snapshot", default=SNAPSHOT, help="the snapshot the build was made from (verbatim provenance + the control's quote)")
    args = ap.parse_args()
    if not os.path.isdir(args.dist):
        print(f"dist not found: {args.dist} — run `npm run build:preview` in www/ first", file=sys.stderr)
        return 3
    if not os.path.exists(AXE_JS_PATH):
        print(f"axe bundle missing: {AXE_JS_PATH}", file=sys.stderr)
        return 3
    if not args.skip_control:
        print("mutation control …", end=" ", flush=True)
        if not mutation_control(args.dist, args.base, args.snapshot):
            print(
                "FAILED — the gate did not report a planted overflow + inline script + sentinel + unmounted chart + sub-floor SVG text"
                " + overlapping/clipped SVG labels + ISO dates outside a quotation, in a correction, a quote in a heading, a borrowed"
                " exemption, a sentinel inside a quote — or it DID report the sanctioned in-quote ISO date; refusing to grade"
            )
            return 2
        print("ok (the gate can fail)")
    print(f"web preview gate — {args.dist} at base {args.base}")
    ok, results = gate(args.dist, args.base, args.out, snapshot=args.snapshot)
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
