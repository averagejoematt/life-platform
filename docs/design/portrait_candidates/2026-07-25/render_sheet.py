#!/usr/bin/env python3
"""render_sheet.py — #1114 in-situ 96px option sheet (render half of the option round).

Renders every option through the REAL shipped renderer (site/assets/js/portraits.js
renderPortrait) inside the REAL 96px UI context — the `coach-head` / `coach-head--lead`
markup coaching.js builds (`site/assets/css/tokens.css` + `story.css`, `.portrait-lg`
= 96x115px), the exact surface the #1114 complaint was raised on — then screenshots
each option section in BOTH themes with Playwright (reduced-motion emulated, so the
static portrait is what's captured; that's also what a motion-averse reader gets).

Ink-weight treatments (recorded per candidate in `_meta.option.ink`) are applied as a
post-render stroke-width attribute transform — the same mapping the chosen direction
would ship as a portraits.js change after Matthew's ADR-106 gate. Frame geometry is
NOT transformed: it comes from each candidate's explicit `frame` layer, drawn by the
shipped renderer itself.

Outputs (committed with the round):
    sheet.html            — the sheet page (absolute /assets/ paths; serve site/ to view)
    renders/<shot>.png    — per-option in-situ sections, dark + light

Usage:
    python3 docs/design/portrait_candidates/2026-07-25/render_sheet.py
"""

import http.server
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
SITE = os.path.join(ROOT, "site")
RENDERS = os.path.join(HERE, "renders")
SHEET = os.path.join(HERE, "sheet.html")

sys.path.insert(0, HERE)
from make_options import OPTIONS, TRIO  # noqa: E402

# The exact coach-head chrome coaching.js renders at the 96px call sites.
COACHES = {
    "elena_voss": {"name": "Elena Voss", "color": "#94a3b8", "role": "Embedded Journalist", "lead": True},
    "lisa_park": {"name": "Dr. Lisa Park", "color": "#8b5cf6", "role": "Sleep & Circadian", "lead": False},
    "james_okafor": {"name": "Dr. James Okafor", "color": "#f59e0b", "role": "Longevity Medicine", "lead": False},
}


def load_candidates():
    cands = {}
    for pid in TRIO:
        for opt_id in OPTIONS:
            path = os.path.join(HERE, f"{pid}__{opt_id}.json")
            with open(path) as f:
                cands[f"{pid}__{opt_id}"] = json.load(f)
    return cands


def build_sheet():
    data = {
        "coaches": COACHES,
        "trio": list(TRIO),
        "options": {oid: {"name": o["name"], "ink": o["ink"], "claim": o["claim"]} for oid, o in OPTIONS.items()},
        "candidates": load_candidates(),
    }
    payload = json.dumps(data, ensure_ascii=True, sort_keys=True)
    html = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<title>#1114 portrait art-direction v2 — 96px in-situ option sheet</title>
<link rel="stylesheet" href="/assets/css/fonts.css">
<link rel="stylesheet" href="/assets/css/tokens.css">
<link rel="stylesheet" href="/assets/css/story.css">
<style>
  body { padding: 24px; max-width: 1120px; margin: 0 auto; }
  .sheet-sec { margin: 0 0 28px; padding: 16px; border: 1px dashed var(--line, #555); border-radius: 8px; }
  .sheet-sec h2 { margin: 0 0 4px; font-size: 1.05rem; }
  .sheet-sec .claim { margin: 0 0 14px; opacity: 0.75; font-size: 0.85rem; max-width: 72ch; }
  .sheet-row { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; }
  .sheet-row .coach-head { margin-bottom: 0; min-width: 300px; }
  .size-strip { display: flex; gap: 18px; align-items: flex-end; margin-top: 14px; }
  .size-strip figure { margin: 0; text-align: center; }
  .size-strip figcaption { font-size: 0.7rem; opacity: 0.6; margin-top: 4px; }
</style>
</head>
<body>
<h1 style="font-size:1.2rem">#1114 — coach portrait frame + engraved-ink options, rendered in the 96px coach-head context</h1>
<div id="sheet"></div>
<script type="module">
import { renderPortrait } from "/assets/js/portraits.js";
import { PORTRAITS } from "/assets/js/portrait_data.js";

const DATA = __PAYLOAD__;
const SIL = ["head", "hair", "bust"];
const FEAT = ["brow", "eyes-open", "eyes-closed", "glasses", "nose", "mouth-rest", "mouth-a", "mouth-b"];

// The post-render ink transform — the renderer change the chosen direction would ship.
function applyInk(svg, ink) {
  const setW = (sel, w) => svg.querySelectorAll(`${sel} [stroke-width]`).forEach((p) => p.setAttribute("stroke-width", w));
  const frame = svg.querySelector(".pt-frame");
  if (ink.frame == null && frame) frame.remove();           // option A: no frame at any size
  else if (frame) {
    setW(".pt-frame", ink.frame);
    if (ink.frame_opacity != null) frame.style.opacity = ink.frame_opacity;
  }
  for (const l of SIL) setW(`[data-l="${l}"]`, ink.sil);
  for (const l of FEAT) setW(`[data-l="${l}"]`, ink.feat);
}

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;"); }

function coachHead(pid, svgHtml) {
  const c = DATA.coaches[pid];
  const lead = c.lead ? " coach-head--lead" : "";
  const tier = c.lead ? `<p class="coach-head-tier label">the head coach · lead tier</p>` : "";
  return `<div class="coach-head${lead}" style="--coach:${esc(c.color)}">${svgHtml}<div><h2 class="coach-head-role">${esc(c.role)}</h2><p class="coach-head-name label">${esc(c.name)}</p>${tier}</div></div>`;
}

function render(recipe, pid, opts) {
  return renderPortrait(recipe, { name: DATA.coaches[pid].name }, opts);
}

function section(id, label, claim, tiles, strip) {
  return `<section class="sheet-sec" data-shot="${esc(id)}"><h2>${esc(label)}</h2><p class="claim">${esc(claim)}</p><div class="sheet-row">${tiles}</div>${strip}</section>`;
}

const host = document.getElementById("sheet");
let html = "";

// Baseline: the shipped bundle exactly as live today (seeded ring+ticks, uniform 1.7 ink).
html += section(
  "baseline", "BASELINE — as shipped today (the complaint)",
  "seeded ring + radial ticks at frame opacity 0.35; uniform 1.7px non-scaling ink",
  DATA.trio.map((pid) => coachHead(pid, render(PORTRAITS[pid], pid, { title: "", cls: "portrait-lg", size: 96 }))).join(""),
  "");

for (const [oid, opt] of Object.entries(DATA.options)) {
  const tiles = DATA.trio.map((pid) => coachHead(pid, render(DATA.candidates[`${pid}__${oid}`], pid, { title: "", cls: "portrait-lg", size: 96 }))).join("");
  const stripTiles = [["", 40, "40px"], ["portrait-md", 56, "56px"], ["portrait-lg", 96, "96px"]].map(([cls, size, cap]) =>
    `<figure style="--coach:${esc(DATA.coaches.elena_voss.color)}">${render(DATA.candidates[`elena_voss__${oid}`], "elena_voss", { title: "", cls, size })}<figcaption>${cap}</figcaption></figure>`).join("");
  html += section(oid, `OPTION ${oid.slice(-1)} — ${opt.name}`, opt.claim, tiles,
    `<div class="size-strip">${stripTiles}</div>`);
}

host.innerHTML = html;

// Apply each option's ink treatment to every portrait in its section.
for (const [oid, opt] of Object.entries(DATA.options)) {
  document.querySelectorAll(`[data-shot="${oid}"] svg.portrait`).forEach((svg) => applyInk(svg, opt.ink));
}

window.__sheetReady = true;
</script>
</body>
</html>
"""
    html = html.replace("__PAYLOAD__", payload)
    with open(SHEET, "w") as f:
        f.write(html)
    return html


def serve(sheet_html):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=SITE, **kw)

        def do_GET(self):
            if self.path.split("?")[0] == "/sheet_1114.html":
                body = sheet_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    from playwright.sync_api import sync_playwright

    sheet_html = build_sheet()
    srv = serve(sheet_html)
    port = srv.server_address[1]
    os.makedirs(RENDERS, exist_ok=True)
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1160, "height": 1400}, reduced_motion="reduce")
        page.goto(f"http://127.0.0.1:{port}/sheet_1114.html")
        page.wait_for_function("window.__sheetReady === true")
        for theme in ("dark", "light"):
            page.evaluate(f"document.documentElement.dataset.theme = '{theme}'")
            page.wait_for_timeout(250)  # let theme tokens settle
            for sec in page.query_selector_all("section[data-shot]"):
                shot = f"{sec.get_attribute('data-shot')}--{theme}.png"
                sec.screenshot(path=os.path.join(RENDERS, shot))
                shots.append(shot)
            page.screenshot(path=os.path.join(RENDERS, f"sheet-full--{theme}.png"), full_page=True)
            shots.append(f"sheet-full--{theme}.png")
        browser.close()
    srv.shutdown()
    print(f"✅ {len(shots)} render(s) → {os.path.relpath(RENDERS, ROOT)}")
    for s in shots:
        print(f"   {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
