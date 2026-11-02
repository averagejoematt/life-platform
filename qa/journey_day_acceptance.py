#!/usr/bin/env python3
"""qa/journey_day_acceptance.py — the owner's acceptance item 6 for the v9 Day and Journey pages, in a real browser.

Runs Playwright (sync API, Chromium) against production (https://averagejoematt.com) or a local build served at the
site root, and proves — with the ACTUAL dates and values it saw written into every detail line — that:

   1 swap-parts       every date-dependent part of the Day ([data-day-part] head, tiles, session-night, food-engine,
                      coaches-calls, week, rail) after an in-place swap equals the target day's own page, fetched
                      independently; the h1, weight, session, sleep, food, engine, coaches, calls, week and rail values
                      are reported for each swap
   2 swap-head        URL, document.title, link[rel=canonical] and rel=prev/next match the target page; no reload
   3 rapid-switch     two swaps in flight, the first response held ~2.5 s and the second ~0.2 s: the second-clicked day
                      wins and the page never flips back when the late response lands (the late response is delivered
                      even though the island aborted it — the harder case: a response that lands anyway)
   4 boundaries       the first day has no previous control and reads day 1; the latest has no next; the scrubber at
                      both ends (Home/End on the slider) swaps to the first and the latest day
   5 missing          a day with no weigh-in shows the absent state ("—"), never a number, NaN or undefined
   6 direct           direct loads of named dates; 12 September is Week 1, 21 October Week 7; 29 and 30 October carry a
                      correction note beside a verbatim quote
   7 refresh          reload after a swap shows the same day and the same parts
   8 history          A→B→C by the controls; Back → B, Back → A, Forward → B, each with URL, h1 and parts checked
   9 load-failure     the next day's fetch answers 500 → the island falls back to a full navigation that renders it
  10 inspect          after two swaps every swapped chart is mounted; keyboard reading shows a date in words and the
                      readout stays inside the viewport (390 and 1280); the Journey chart and a heart chart too
  11 keyboard         Tab reaches prev/next and the strip; Enter on a strip day swaps and focus lands on its documented
                      target (the strip link that moved it)
  12 announce         the live region names the new day in words; the slider's aria-valuetext and every strip link's
                      accessible name carry a date in words
  13 focus-visible    tabbed-to toolbar buttons, a strip link and a chart are not under the sticky masthead (or the
                      phone tab bar) once the browser has scrolled them into view, and carry a visible focus indicator
  14 reflow           no horizontal overflow at 320 px (WCAG 1.4.10, 400 % of 1280) and at 1280 with 200 % root text
  15 axe              zero critical/serious axe-core violations on the Journey and one Day at 390 (axe is injected in
                      a bypass_csp context only: the production CSP is script-src 'self')
  16 journey-labels   no two svg <text> boxes in the Journey chart overlap (>1 px on both axes) and none leave the svg

Usage:
    python3 qa/journey_day_acceptance.py --base https://averagejoematt.com --out /tmp/acc [--cache-bust]
    python3 qa/journey_day_acceptance.py --base http://127.0.0.1:8765 --out /tmp/acc --only swap-parts,history
Writes <out>/journey_day_checks.json ([{id, viewport, ok, detail}]), prints PASS/FAIL per check and a summary.
Exit: 0 every check passed · 1 a check failed · 3 setup error (no Playwright, the site unreachable).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AXE_JS_PATH = os.path.join(REPO, "tests", "vendor", "axe.min.js")
PHONE = {"width": 390, "height": 844}
LAPTOP = {"width": 1280, "height": 900}
REFLOW = {"width": 320, "height": 800}
PARTS = ("head", "tiles", "session-night", "food-engine", "coaches-calls", "week", "rail")
DIRECT_DATES = ("2026-09-12", "2026-10-21", "2026-10-29", "2026-10-30")
WEEK_EXPECT = {"2026-09-12": "Week 1", "2026-10-21": "Week 7"}
CORRECTION_DATES = ("2026-10-29", "2026-10-30")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
WEEKDAYS = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
DATE_WORDS = re.compile(rf"\b(?:(?:{WEEKDAYS}) )?\d{{1,2}} (?:{MONTHS})\b")
BAD_VALUE = re.compile(r"\b(?:NaN|undefined|null)\b|\[object Object\]")
SWAP_TIMEOUT_MS = 15000

# ---------------------------------------------------------------------------------------------------------------------
# In-page JavaScript. Each reads either the live document or a fresh page's HTML parsed by DOMParser, so the live DOM and
# the independent fetch are normalised by exactly the same code.
# ---------------------------------------------------------------------------------------------------------------------
_DOC_JS = "(html) => html ? new DOMParser().parseFromString(html, 'text/html') : document"

_PARTS_TEXT_JS = f"""([html, parts]) => {{
    const doc = ({_DOC_JS})(html);
    const out = {{}};
    for (const p of parts) {{
        const el = doc.querySelector(`[data-day-root] [data-day-part="${{p}}"]`);
        if (!el) {{ out[p] = null; continue; }}
        const c = el.cloneNode(true);
        c.querySelectorAll('.tip, circle.focus').forEach(x => x.remove());  // the inspect island's own furniture
        out[p] = (c.textContent || '').replace(/\\s+/g, ' ').trim();
    }}
    return out;
}}"""

_VALUES_JS = f"""(html) => {{
    const doc = ({_DOC_JS})(html);
    const t = (el) => el ? (el.textContent || '').replace(/\\s+/g, ' ').trim() : null;
    const q = (s) => doc.querySelector(s);
    const part = (p) => q(`[data-day-root] [data-day-part="${{p}}"]`);
    const tiles = [...(part('tiles') || doc).querySelectorAll('.tile')];
    const tile = (re) => {{
        const x = tiles.find(el => re.test(t(el.querySelector('.label')) || ''));
        return x ? `${{t(x.querySelector('.v'))}} | ${{t(x.querySelector('.d'))}}` : null;
    }};
    const fe = part('food-engine');
    const engineH = fe ? [...fe.querySelectorAll('h2')].find(h => /engine/i.test(h.textContent)) : null;
    const engine = engineH ? t(engineH.parentElement.querySelector('p.small, .unavail')) : null;
    const foodH = fe ? fe.querySelector('h2') : null;
    const foodBlock = foodH ? t(foodH.parentElement.querySelector('.callout, .unavail, p.small')) : null;
    const cc = part('coaches-calls');
    const wk = part('week');
    const rail = part('rail');
    return {{
        id: (q('[data-day-root]') || {{dataset: {{}}}}).dataset.dayId || null,
        h1: t(q('[data-day-h1]')),
        kicker: t(q('[data-day-part="head"] .row .label')),
        weight: tile(/^Weight/),
        sleep_hours: tile(/^Sleep/),
        food_kcal: tile(/^Food/),
        food_text: foodBlock ? foodBlock.slice(0, 140) : null,
        session: t(q('[data-day-session]')),
        engine: engine ? engine.slice(0, 140) : null,
        coaches: cc ? [...cc.querySelectorAll('.voice .who')].map(t) : [],
        first_call: cc ? t(cc.querySelector('.callchip')) : null,
        week: wk ? t(wk.querySelector('.rows > span > span, .empty')) : null,
        rail_first: rail ? (t(rail.querySelector('.conn a')) || '').slice(0, 120) || null : null,
        title: doc.title,
        canonical: (q('link[rel="canonical"]') || {{}}).getAttribute ? q('link[rel="canonical"]').getAttribute('href') : null,
        prev: q('link[rel="prev"]') ? q('link[rel="prev"]').getAttribute('href') : null,
        next: q('link[rel="next"]') ? q('link[rel="next"]').getAttribute('href') : null,
    }};
}}"""

# Glyph boxes of the svg text in one chart: overlaps (>1 px both axes) and labels outside the svg frame.
_SVG_LABELS_JS = """(sel) => {
    const svg = document.querySelector(sel);
    if (!svg) return null;
    const frame = svg.getBoundingClientRect();
    const ts = [...svg.querySelectorAll('text')].filter(t => (t.textContent || '').trim()).map(t => {
        const b = t.getBoundingClientRect();
        return {txt: t.textContent.trim(), b: {l: b.left, r: b.right, t: b.top, btm: b.bottom, w: b.width}};
    }).filter(x => x.b.w >= 1);
    const out = {labels: ts.map(x => x.txt), overlaps: [], clipped: [], frame: [frame.left, frame.top, frame.width, frame.height].map(Math.round)};
    for (const x of ts) {
        if (x.b.l < frame.left - 1 || x.b.r > frame.right + 1 || x.b.t < frame.top - 1 || x.b.btm > frame.bottom + 1) out.clipped.push(x.txt);
    }
    for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) {
        const a = ts[i].b, b = ts[j].b;
        const w = Math.min(a.r, b.r) - Math.max(a.l, b.l);
        const h = Math.min(a.btm, b.btm) - Math.max(a.t, b.t);
        if (w > 1 && h > 1) out.overlaps.push(`${ts[i].txt} × ${ts[j].txt}`);
    }
    return out;
}"""

# The focused element against the sticky masthead (top) and, on a phone, the fixed tab bar (bottom).
_FOCUS_GEOMETRY_JS = """() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const mast = document.querySelector('.mast');
    const mr = mast ? mast.getBoundingClientRect() : null;
    const mcs = mast ? getComputedStyle(mast) : null;
    const covering = mast && (mcs.position === 'sticky' || mcs.position === 'fixed') && mr.top <= 0.5 ? mr.bottom : 0;
    const tab = document.querySelector('.tabbar');
    const tcs = tab ? getComputedStyle(tab) : null;
    const tabTop = tab && tcs.display !== 'none' && tcs.position === 'fixed' ? tab.getBoundingClientRect().top : window.innerHeight;
    const spt = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    const ow = parseFloat(cs.outlineWidth) || 0;
    const desc = el.tagName.toLowerCase() + (el.dataset.focus ? `[data-focus=${el.dataset.focus}]` : '')
        + (el.dataset.frame ? `[data-frame=${el.dataset.frame}]` : '') + (el.dataset.show ? `[data-show=${el.dataset.show}]` : '')
        + (el.dataset.range ? `[data-range=${el.dataset.range}]` : '');
    const probe = (y) => { const h = document.elementFromPoint(r.left + r.width / 2, y);
        return !h || el.contains(h) || h.contains(el) ? null : (h.closest('.mast') ? 'masthead' : h.closest('.tabbar') ? 'tab bar' : h.tagName.toLowerCase()); };
    const coveredBy = [probe(r.top + 2), probe(r.bottom - 2)].filter(Boolean);
    return {desc, coveredBy, top: Math.round(r.top * 10) / 10, bottom: Math.round(r.bottom * 10) / 10, navBottom: Math.round(covering * 10) / 10,
        tabTop: Math.round(tabTop * 10) / 10, scrollPaddingTop: spt, outline: `${cs.outlineStyle} ${cs.outlineWidth}`, boxShadow: cs.boxShadow,
        visibleRing: (cs.outlineStyle !== 'none' && ow > 0) || (cs.boxShadow && cs.boxShadow !== 'none'), scrollY: Math.round(window.scrollY)};
}"""

_ACTIVE_JS = """() => { const a = document.activeElement; if (!a) return null;
    return {tag: a.tagName.toLowerCase(), focus: a.dataset ? (a.dataset.focus || null) : null, name: a.getAttribute('aria-label') || (a.textContent || '').trim().slice(0, 40),
        frame: a.dataset ? (a.dataset.frame || null) : null, show: a.dataset ? (a.dataset.show || null) : null, h1: a.hasAttribute && a.hasAttribute('data-day-h1'),
        chart: a.tagName.toLowerCase() === 'svg' && a.hasAttribute('data-points'), journey: !!(a.closest && a.closest('[data-journey-chart]'))}; }"""

_OVERFLOW_JS = """() => {
    const vw = document.documentElement.clientWidth;
    const sw = document.documentElement.scrollWidth;
    const off = [];
    if (sw > vw) document.querySelectorAll('body *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > vw + 1 && off.length < 4) off.push(`${el.tagName.toLowerCase()}.${(el.className && el.className.baseVal === undefined ? el.className : '').toString().split(' ')[0]} right=${Math.round(r.right)}`);
    });
    return {vw, sw, offenders: off};
}"""

# Hold the day-page HTML fetches this test names: each fetch to /data/day/<id>/ takes the next delay off the queue. The
# held response is DELIVERED after its delay even if the caller aborted — the case where an abort loses the race.
_DELAY_INIT_JS = """(() => {
    const orig = window.fetch.bind(window);
    window.__accDelays = [];
    window.__accLog = [];
    window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (!/\\/data\\/day\\/\\d{4}-\\d{2}-\\d{2}\\/?$/.test(new URL(url, location.href).pathname) || !window.__accDelays.length)
            return orig(input, init);
        const ms = window.__accDelays.shift();
        const t0 = performance.now();
        const sansSignal = Object.assign({}, init || {});
        delete sansSignal.signal;
        return orig(input, sansSignal).then(r => new Promise(res => setTimeout(() => {
            window.__accLog.push({url, ms, landed: Math.round(performance.now() - t0), aborted: !!(init && init.signal && init.signal.aborted)});
            res(r);
        }, ms)));
    };
})();"""

_RUN_AXE_JS = """async () => {
    const r = await axe.run(document, {resultTypes: ['violations']});
    return r.violations.filter(v => v.impact === 'critical' || v.impact === 'serious').map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length,
        targets: v.nodes.slice(0, 2).map(n => (n.target || []).join(' '))}));
}"""


def in_words(iso: str, weekday: bool = True) -> str:
    """The site's own phrasing: 'Friday 30 October'."""
    d = dt.date.fromisoformat(iso)
    core = f"{d.day} {d.strftime('%B')}"
    return f"{d.strftime('%A')} {core}" if weekday else core


class Suite:
    def __init__(self, browser, base: str, cache_bust: bool, only: set[str] | None):
        self.browser = browser
        self.base = base.rstrip("/")
        self.cache_bust = cache_bust
        self.only = only
        self.results: list[dict] = []
        self.days: list[dict] = []
        self._bust_n = 0

    # -- plumbing ------------------------------------------------------------------------------------------------------
    def record(self, cid: str, viewport: str, ok: bool, detail: str) -> None:
        self.results.append({"id": cid, "viewport": viewport, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {cid:<26} {viewport:<9} {detail[:400]}", flush=True)

    def url(self, path: str) -> str:
        return f"{self.base}{path}"

    def day_path(self, iso: str) -> str:
        return f"/data/day/{iso}/"

    def context(self, vp: dict, **kw):
        return self.browser.new_context(viewport=vp, reduced_motion="reduce", **kw)

    def open(self, ctx, path: str, *, init_js: str | None = None):
        """A page on `path`, loaded and its islands mounted; the window marker proves later that no reload happened."""
        page = ctx.new_page()
        if init_js:
            page.add_init_script(init_js)
        target = self.url(path)
        if self.cache_bust:
            self._bust_n += 1
            target += f"{'&' if '?' in target else '?'}acc={int(time.time() * 1000)}-{self._bust_n}"
        page.goto(target, wait_until="load")
        if "/data/day/" in path:
            page.wait_for_selector("[data-day-root][data-mounted='true']", timeout=SWAP_TIMEOUT_MS, state="attached")
        if path.startswith("/data/journey"):
            page.wait_for_selector("[data-journey][data-mounted='true']", timeout=SWAP_TIMEOUT_MS, state="attached")
        page.evaluate("() => { window.__accMarker = 'no-reload'; }")
        return page

    def no_reload(self, page) -> bool:
        return page.evaluate("() => window.__accMarker === 'no-reload' && performance.getEntriesByType('navigation').length === 1")

    def day_id(self, page) -> str:
        return page.evaluate("() => document.querySelector('[data-day-root]').dataset.dayId")

    def swaps(self, page) -> int:
        return int(page.evaluate("() => Number(document.querySelector('[data-day-root]').dataset.swaps || 0)"))

    def wait_swap(self, page, before: int, expect_id: str | None = None) -> None:
        page.wait_for_function(
            "([n, id]) => { const r = document.querySelector('[data-day-root]'); return Number(r.dataset.swaps || 0) > n && (!id || r.dataset.dayId === id); }",
            arg=[before, expect_id],
            timeout=SWAP_TIMEOUT_MS,
        )

    def click_swap(self, page, selector: str) -> str:
        """Click a day control, wait for the swap; returns the target id the control named."""
        loc = page.locator(selector).first
        href = loc.get_attribute("href") or ""
        target = href.rstrip("/").split("/")[-1]
        n = self.swaps(page)
        loc.click()
        self.wait_swap(page, n, target)
        return target

    def fresh_html(self, page, iso: str) -> str:
        r = page.request.get(self.url(self.day_path(iso)), headers={"Accept": "text/html"})
        if r.status != 200:
            raise RuntimeError(f"fresh fetch of {iso} answered {r.status}")
        return r.text()

    def parts_of(self, page, html: str | None = None) -> dict:
        return page.evaluate(_PARTS_TEXT_JS, [html, list(PARTS)])

    def values_of(self, page, html: str | None = None) -> dict:
        return page.evaluate(_VALUES_JS, html)

    def compare_to_fresh(self, page, iso: str) -> tuple[bool, str, dict]:
        """Live parts + head vs the day's own page fetched independently. Returns ok, a detail line, the live values."""
        html = self.fresh_html(page, iso)
        live, fresh = self.parts_of(page), self.parts_of(page, html)
        bad = [p for p in PARTS if live.get(p) is None or live.get(p) != fresh.get(p)]
        lv, fv = self.values_of(page), self.values_of(page, html)
        path = page.evaluate("() => location.pathname")
        head_bad = [k for k in ("title", "canonical", "prev", "next") if lv.get(k) != fv.get(k)]
        if path.rstrip("/") != self.day_path(iso).rstrip("/"):
            head_bad.append(f"url={path}")
        diffs = []
        for p in bad:
            a, b = live.get(p) or "", fresh.get(p) or ""
            k = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            diffs.append(f"{p}: live[{k}:]={a[k:k + 60]!r} fresh[{k}:]={b[k:k + 60]!r}")
        ok = not bad and not head_bad and lv.get("id") == iso
        detail = f"target {iso}: parts {'all 7 equal' if not bad else 'DIFFER ' + '; '.join(diffs)}; head {'equal' if not head_bad else 'DIFFER ' + str(head_bad)}"
        return ok, detail, lv

    @staticmethod
    def brief(v: dict) -> str:
        keys = (
            "h1",
            "kicker",
            "weight",
            "session",
            "sleep_hours",
            "food_kcal",
            "food_text",
            "engine",
            "coaches",
            "first_call",
            "week",
            "rail_first",
        )
        return " · ".join(f"{k}={v.get(k)!r}" for k in keys)

    def middle_day(self) -> str:
        return self.days[len(self.days) // 2]["id"]

    def strip_other(self, page, exclude: set[str]) -> str:
        """The selector of a strip link to a day not in `exclude` (and not the current day)."""
        ids = page.evaluate(
            "() => [...document.querySelectorAll('.strip a[data-day-link]')].map(a => a.dataset.focus.replace('strip-', ''))"
        )
        cur = self.day_id(page)
        for iso in reversed(ids[:-1]):
            if iso not in exclude and iso != cur:
                return f".strip a[data-focus='strip-{iso}']"
        raise RuntimeError(f"no strip day outside {sorted(exclude)} on {cur}")

    def wants(self, cid: str) -> bool:
        return not self.only or cid in self.only

    def guarded(self, cid: str, viewport: str, fn) -> None:
        if not self.wants(cid):
            return
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a harness exception is a FAIL with its message, never a silent skip
            self.record(cid, viewport, False, f"harness exception: {type(e).__name__}: {str(e).splitlines()[0][:300]}")

    # -- the checks ----------------------------------------------------------------------------------------------------
    def check_swaps(self, vp_name: str, vp: dict) -> None:
        """1 + 2: three swaps (next, a strip day, prev) each compared with the target's own page; no reload."""
        ctx = self.context(vp)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            plan = [("next", "a[data-focus='next']"), ("strip", None), ("prev", "a[data-focus='prev']")]
            part_ok, head_ok, lines, heads = True, True, [], []
            for how, sel in plan:
                sel = sel or self.strip_other(page, {start})
                before = self.day_id(page)
                target = self.click_swap(page, sel)
                ok, detail, vals = self.compare_to_fresh(page, target)
                parts_equal = "parts all 7 equal" in detail
                part_ok &= parts_equal and vals.get("id") == target
                head_ok &= "head equal" in detail
                lines.append(f"[{how} {before}→{target}] {detail.split('; head')[0]} | {self.brief(vals)}")
                heads.append(
                    f"[{how} →{target}] url={page.evaluate('() => location.pathname')} title={vals['title']!r} "
                    f"canonical={vals['canonical']} prev={vals['prev']} next={vals['next']} ({detail.split('; head ')[1]})"
                )
            reload_free = self.no_reload(page)
            self.record("1.swap-parts", vp_name, part_ok, " || ".join(lines))
            self.record(
                "2.swap-head-no-reload",
                vp_name,
                head_ok and reload_free,
                f"start {start}; swaps={self.swaps(page)}; navigations=1 and marker kept: {reload_free} || " + " || ".join(heads),
            )
        finally:
            ctx.close()

    def check_rapid(self) -> None:
        """3: the first swap's response held 2.5 s, the second's 0.2 s; the second-clicked day must win and stay."""
        ctx = self.context(LAPTOP)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start), init_js=_DELAY_INIT_JS)
            nxt = page.locator("a[data-focus='next']").first.get_attribute("href").rstrip("/").split("/")[-1]
            strip_sel = self.strip_other(page, {start, nxt})
            second = strip_sel.split("strip-")[1].rstrip("']")
            page.evaluate("() => { window.__accDelays = [2500, 200]; }")
            n0 = self.swaps(page)
            page.locator("a[data-focus='next']").first.click()
            page.wait_for_timeout(250)
            page.locator(strip_sel).first.click()
            self.wait_swap(page, n0, second)
            t_first = (self.day_id(page), page.evaluate("() => location.pathname"), self.values_of(page)["h1"])
            page.wait_for_timeout(3500)  # the held 2.5 s response has landed by now
            log = page.evaluate("() => window.__accLog")
            vals = self.values_of(page)
            t_late = (self.day_id(page), page.evaluate("() => location.pathname"), vals["h1"])
            ok_parts, detail, _ = self.compare_to_fresh(page, second)
            first_landed = any(nxt in x["url"] and x["ms"] == 2500 for x in log)
            ok = (
                t_first[0] == second
                and t_late[0] == second
                and t_late[1].rstrip("/").endswith(second)
                and ok_parts
                and first_landed
                and self.swaps(page) == n0 + 1
                and self.no_reload(page)
            )
            self.record(
                "3.rapid-switch",
                "1280",
                ok,
                f"start {start}; clicked next→{nxt} (held 2500 ms) then strip→{second} (held 200 ms); after swap: id={t_first[0]} "
                f"path={t_first[1]} h1={t_first[2]!r}; 3.5 s later: id={t_late[0]} path={t_late[1]} h1={t_late[2]!r}; "
                f"swaps={self.swaps(page) - n0}; late responses={log}; {detail}",
            )
        finally:
            ctx.close()

    def check_boundaries(self) -> None:
        """4: the first and the latest day; the scrubber driven to both ends."""
        ctx = self.context(LAPTOP)
        try:
            first, last = self.days[0], self.days[-1]
            page = self.open(ctx, self.day_path(first["id"]))
            v = self.values_of(page)
            prev_links = page.locator("a[data-focus='prev']").count()
            start_text = page.locator("[data-day-part='head'] .daynav > span.dn").first.text_content() if prev_links == 0 else None
            sl = page.evaluate(
                "() => { const i = document.querySelector('[data-day-index]'); return [i.value, i.min, i.max, i.getAttribute('aria-valuetext')]; }"
            )
            ok1 = prev_links == 0 and "day 1 " in f"{v['kicker']} " and first["day_number"] == 1 and sl[0] == sl[1] and v["prev"] is None
            self.record(
                "4.boundary-first",
                "1280",
                ok1,
                f"{first['id']}: h1={v['h1']!r} kicker={v['kicker']!r}; prev links={prev_links} (stand-in text {start_text!r}); "
                f"rel=prev={v['prev']}; slider value={sl[0]} min={sl[1]} max={sl[2]} valuetext={sl[3]!r}",
            )
            page.close()
            page = self.open(ctx, self.day_path(last["id"]))
            v = self.values_of(page)
            next_links = page.locator("a[data-focus='next']").count()
            end_text = page.locator("[data-day-part='head'] .daynav > span.dn").last.text_content() if next_links == 0 else None
            sl = page.evaluate(
                "() => { const i = document.querySelector('[data-day-index]'); return [i.value, i.min, i.max, i.getAttribute('aria-valuetext')]; }"
            )
            ok2 = next_links == 0 and sl[0] == sl[2] and v["next"] is None and f"day {last['day_number']}" in (v["kicker"] or "")
            self.record(
                "4.boundary-latest",
                "1280",
                ok2,
                f"{last['id']}: h1={v['h1']!r} kicker={v['kicker']!r}; next links={next_links} (stand-in text {end_text!r}); "
                f"rel=next={v['next']}; slider value={sl[0]} min={sl[1]} max={sl[2]} valuetext={sl[3]!r}",
            )
            page.close()
            mid = self.middle_day()
            page = self.open(ctx, self.day_path(mid))
            page.wait_for_function("() => true")
            page.wait_for_timeout(400)  # days.json index loads
            slider = page.locator("[data-day-index]")
            n = self.swaps(page)
            slider.focus()
            page.keyboard.press("Home")
            self.wait_swap(page, n, first["id"])
            home = (
                self.day_id(page),
                page.evaluate("() => location.pathname"),
                self.values_of(page)["h1"],
                slider.get_attribute("aria-valuetext"),
            )
            focus_home = page.evaluate("() => document.activeElement && document.activeElement.hasAttribute('data-day-index')")
            n = self.swaps(page)
            page.keyboard.press("End")
            self.wait_swap(page, n, last["id"])
            end = (
                self.day_id(page),
                page.evaluate("() => location.pathname"),
                self.values_of(page)["h1"],
                slider.get_attribute("aria-valuetext"),
            )
            ok3 = home[0] == first["id"] and end[0] == last["id"] and focus_home and self.no_reload(page)
            self.record(
                "4.scrubber-ends",
                "1280",
                ok3,
                f"from {mid}: Home → id={home[0]} path={home[1]} h1={home[2]!r} valuetext={home[3]!r} (focus kept on slider: {focus_home}); "
                f"End → id={end[0]} path={end[1]} h1={end[2]!r} valuetext={end[3]!r}; no reload: {self.no_reload(page)}",
            )
        finally:
            ctx.close()

    def check_missing(self) -> None:
        """5: a day with no weigh-in, read from days.json, shows the absent state — never a number or a non-value."""
        ctx = self.context(LAPTOP)
        try:
            gaps = [d["id"] for d in self.days if not d.get("has_weighin")]
            if not gaps:
                self.record(
                    "5.missing-reading", "1280", False, "days.json lists no day without a weigh-in — nothing to prove the absent state on"
                )
                return
            for iso in gaps[:2]:
                page = self.open(ctx, self.day_path(iso))
                v = self.values_of(page)
                tile_v = page.evaluate(
                    "() => { const t = [...document.querySelectorAll('[data-day-part=tiles] .tile')].find(x => /^Weight/.test(x.querySelector('.label').textContent.trim()));"
                    " return t ? [t.querySelector('.v').textContent.trim(), t.querySelector('.d').textContent.trim()] : null; }"
                )
                strip = page.locator(f".strip a[data-focus='strip-{iso}']").get_attribute("aria-label")
                text = page.evaluate("() => document.querySelector('[data-day-root]').innerText")
                leaks = BAD_VALUE.findall(text)
                ok = bool(tile_v) and tile_v[0] == "—" and not re.search(r"\d", tile_v[0]) and not leaks and "no weigh-in" in (strip or "")
                self.record(
                    "5.missing-reading",
                    "1280",
                    ok,
                    f"{iso} (has_weighin=false in days.json): weight tile value={tile_v[0] if tile_v else None!r} line={tile_v[1] if tile_v else None!r}; "
                    f"strip name={strip!r}; food={v['food_kcal']!r}; non-values on page={leaks}",
                )
                page.close()
        finally:
            ctx.close()

    def check_direct(self) -> None:
        """6: direct loads of named dates, their week labels, and the corrections beside verbatim quotes."""
        ctx = self.context(LAPTOP)
        try:
            dates = list(DIRECT_DATES) + [self.days[0]["id"], self.days[-1]["id"]]
            for iso in dates:
                page = self.open(ctx, self.day_path(iso))
                v = self.values_of(page)
                ok = v["id"] == iso and v["h1"] == in_words(iso) and bool(v["kicker"])
                notes = []
                if iso in WEEK_EXPECT:
                    has = re.search(rf"\b{WEEK_EXPECT[iso]}\b", v["kicker"] or "") is not None
                    ok &= has
                    notes.append(f"expects {WEEK_EXPECT[iso]!r}: {has}")
                if iso in CORRECTION_DATES:
                    pairs = page.evaluate(
                        "() => [...document.querySelectorAll('.voice')].filter(f => f.querySelector('.correction')).map(f => ({"
                        "who: (f.querySelector('.who')||{}).textContent?.trim(), quote: (f.querySelector('blockquote')||{}).textContent?.trim().slice(0, 70),"
                        "correction: f.querySelector('.correction').textContent.trim().slice(0, 90)}))"
                    )
                    good = [p for p in pairs if p.get("quote")]
                    ok &= bool(good)
                    notes.append(f"correction beside a quote: {len(good)} — {good[:2]}")
                self.record(
                    "6.direct-link",
                    "1280",
                    ok,
                    f"{iso}: id={v['id']} h1={v['h1']!r} (expected {in_words(iso)!r}) kicker={v['kicker']!r} week={v['week']!r}; "
                    + "; ".join(notes),
                )
                page.close()
        finally:
            ctx.close()

    def check_refresh(self) -> None:
        """7: a reload after a swap shows the swapped-to day with the same parts."""
        ctx = self.context(LAPTOP)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            target = self.click_swap(page, "a[data-focus='next']")
            before, vb = self.parts_of(page), self.values_of(page)
            page.reload(wait_until="load")
            page.wait_for_selector("[data-day-root][data-mounted='true']", state="attached", timeout=SWAP_TIMEOUT_MS)
            after, va = self.parts_of(page), self.values_of(page)
            bad = [p for p in PARTS if before.get(p) != after.get(p)]
            ok = va["id"] == target and not bad and page.evaluate("() => location.pathname").rstrip("/").endswith(target)
            self.record(
                "7.refresh-after-swap",
                "1280",
                ok,
                f"{start} → {target}, reload → id={va['id']} h1={va['h1']!r} path={page.evaluate('() => location.pathname')}; "
                f"parts differing after reload: {bad or 'none'}; before h1={vb['h1']!r}",
            )
        finally:
            ctx.close()

    def check_history(self) -> None:
        """8: A→B→C by the controls; Back → B, Back → A, Forward → B — each against that day's own page."""
        ctx = self.context(LAPTOP)
        try:
            a = self.days[len(self.days) // 2 - 1]["id"]
            page = self.open(ctx, self.day_path(a))
            b = self.click_swap(page, "a[data-focus='next']")
            c = self.click_swap(page, "a[data-focus='next']")
            steps, ok = [], True
            for how, want in (("back", b), ("back", a), ("forward", b)):
                n = self.swaps(page)
                page.go_back(wait_until="commit") if how == "back" else page.go_forward(wait_until="commit")
                self.wait_swap(page, n, want)
                good, detail, v = self.compare_to_fresh(page, want)
                ok &= good
                steps.append(f"{how} → id={v['id']} h1={v['h1']!r} path={page.evaluate('() => location.pathname')} ({detail})")
            reload_free = self.no_reload(page)
            self.record(
                "8.back-forward", "1280", ok and reload_free, f"A={a} B={b} C={c}; " + " | ".join(steps) + f"; no reload: {reload_free}"
            )
        finally:
            ctx.close()

    def check_load_failure(self) -> None:
        """9: the next day's fetch answers 500 → an ordinary navigation renders that day."""
        ctx = self.context(LAPTOP)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            nxt = page.locator("a[data-focus='next']").first.get_attribute("href").rstrip("/").split("/")[-1]
            seen = []

            def handler(route, request):
                if request.resource_type == "fetch":
                    seen.append(f"fetch→500 {request.url}")
                    route.fulfill(status=500, body="acceptance: forced failure", content_type="text/plain")
                else:
                    seen.append(f"{request.resource_type}→through {request.url}")
                    route.continue_()

            page.route(re.compile(rf".*/data/day/{nxt}/?(\?.*)?$"), handler)
            with page.expect_navigation(wait_until="load", timeout=SWAP_TIMEOUT_MS):
                page.locator("a[data-focus='next']").first.click()
            page.wait_for_selector("[data-day-root][data-mounted='true']", state="attached", timeout=SWAP_TIMEOUT_MS)
            v = self.values_of(page)
            reloaded = page.evaluate("() => window.__accMarker === undefined")
            ok = reloaded and v["id"] == nxt and v["h1"] == in_words(nxt) and any("fetch→500" in s for s in seen)
            self.record(
                "9.load-failure-fallback",
                "1280",
                ok,
                f"{start} → next {nxt} with its fetch forced to 500: full navigation={reloaded}; rendered id={v['id']} h1={v['h1']!r} "
                f"path={page.evaluate('() => location.pathname')}; requests={seen}",
            )
        finally:
            ctx.close()

    def _inspect_svg(self, page, sel: str, keys: list[str]) -> dict:
        """Focus a chart, press keys, read the readout and its box against the viewport."""
        svg = page.locator(sel).first
        svg.scroll_into_view_if_needed()
        svg.evaluate("el => el.scrollIntoView({block: 'center'})")
        svg.focus()
        reads = []
        for k in keys:
            page.keyboard.press(k)
            reads.append(
                svg.evaluate(
                    "(el, k) => { const tip = el.parentElement.querySelector(':scope > .tip'); if (!tip) return {k, tip: null};"
                    " const r = tip.getBoundingClientRect();"
                    " return {k, hidden: tip.hidden, text: tip.textContent, box: [r.left, r.top, r.right, r.bottom].map(Math.round), vw: document.documentElement.clientWidth, vh: window.innerHeight}; }",
                    k,
                )
            )
        return {"mounted": svg.get_attribute("data-inspect"), "reads": reads}

    @staticmethod
    def _read_ok(r: dict) -> bool:
        if not r.get("text") or r.get("hidden"):
            return False
        x0, y0, x1, y1 = r["box"]
        return bool(DATE_WORDS.search(r["text"])) and x0 >= 0 and x1 <= r["vw"] and y0 >= 0 and y1 <= r["vh"]

    def check_inspect(self, vp_name: str, vp: dict) -> None:
        """10: after two swaps every swapped chart is mounted and answers the keyboard; Journey + a heart chart too."""
        ctx = self.context(vp)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            t1 = self.click_swap(page, "a[data-focus='next']")
            t2 = self.click_swap(page, "a[data-focus='next']")
            state = page.evaluate(
                "() => [...document.querySelectorAll('[data-day-root] [data-day-part] svg[data-points]')].map(s => s.dataset.inspect || 'unmounted')"
            )
            unmounted = [s for s in state if s != "mounted"]
            res = self._inspect_svg(page, "[data-day-part='tiles'] svg[data-inspect='mounted']", ["ArrowLeft", "ArrowRight", "End"])
            ok = bool(state) and not unmounted and all(self._read_ok(r) for r in res["reads"])
            self.record(
                "10.inspect-after-swaps",
                vp_name,
                ok,
                f"{start}→{t1}→{t2}: {len(state)} charts, not mounted={unmounted}; first tile chart keys→readouts: "
                + "; ".join(f"{r['k']}: {r.get('text')!r} box={r.get('box')} in {r.get('vw')}x{r.get('vh')}" for r in res["reads"]),
            )
            page.close()
            page = self.open(ctx, "/data/journey/")
            res = self._inspect_svg(page, "[data-journey-chart] svg[data-points]", ["End", "Home", "ArrowRight", "Escape"])
            reads = res["reads"]
            ok = res["mounted"] == "mounted" and all(self._read_ok(r) for r in reads[:3]) and reads[3].get("hidden") is True
            self.record(
                "10.inspect-journey",
                vp_name,
                ok,
                f"journey chart inspect={res['mounted']}; "
                + "; ".join(
                    f"{r['k']}: {r.get('text')!r} hidden={r.get('hidden')} box={r.get('box')} in {r.get('vw')}x{r.get('vh')}" for r in reads
                ),
            )
            hearts = page.locator("figure[data-heart] svg[data-points]").count()
            if not hearts:
                self.record("10.inspect-heart", vp_name, False, "no figure[data-heart] svg[data-points] on the Journey")
            else:
                res = self._inspect_svg(page, "figure[data-heart] svg[data-points]", ["Home", "End", "Escape"])
                reads = res["reads"]
                ok = res["mounted"] == "mounted" and all(self._read_ok(r) for r in reads[:2]) and reads[2].get("hidden") is True
                self.record(
                    "10.inspect-heart",
                    vp_name,
                    ok,
                    f"{hearts} heart charts; first inspect={res['mounted']}; "
                    + "; ".join(f"{r['k']}: {r.get('text')!r} hidden={r.get('hidden')} box={r.get('box')}" for r in reads),
                )
        finally:
            ctx.close()

    def _tab_until(self, page, pred, limit: int = 120, reverse: bool = False) -> tuple[dict | None, list[str]]:
        trail = []
        for _ in range(limit):
            page.keyboard.press("Shift+Tab" if reverse else "Tab")
            a = page.evaluate(_ACTIVE_JS)
            if a:
                trail.append(a.get("focus") or a.get("frame") or a.get("show") or a["tag"])
                if pred(a):
                    return a, trail
        return None, trail

    def check_keyboard(self) -> None:
        """11: Tab reaches prev, strip and next; Enter on a strip day swaps and keeps focus on that day's link."""
        ctx = self.context(LAPTOP)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            prev, t1 = self._tab_until(page, lambda a: a.get("focus") == "prev")
            strip, t2 = self._tab_until(page, lambda a: (a.get("focus") or "").startswith("strip-"), limit=5)
            nxt, t3 = self._tab_until(page, lambda a: a.get("focus") == "next", limit=20)
            reached = f"prev at tab {len(t1)}: {bool(prev)}; first strip link next: {strip and strip['focus']}; next after {len(t3)} more: {bool(nxt)}"
            # back onto a strip day that is not the current one, then Enter
            page.locator(self.strip_other(page, {start})).first.focus()
            want = page.evaluate("() => document.activeElement.dataset.focus.replace('strip-', '')")
            n = self.swaps(page)
            page.keyboard.press("Enter")
            self.wait_swap(page, n, want)
            after = page.evaluate(_ACTIVE_JS)
            v = self.values_of(page)
            ok_strip = after.get("focus") == f"strip-{want}"
            # Enter on next: focus on the new page's next control (or the h1 on the latest day)
            page.locator("a[data-focus='next']").first.focus()
            want2 = page.locator("a[data-focus='next']").first.get_attribute("href").rstrip("/").split("/")[-1]
            n = self.swaps(page)
            page.keyboard.press("Enter")
            self.wait_swap(page, n, want2)
            after2 = page.evaluate(_ACTIVE_JS)
            ok_next = after2.get("focus") == "next" or after2.get("h1")
            ok = bool(prev and strip and nxt) and ok_strip and ok_next and self.no_reload(page)
            self.record(
                "11.keyboard",
                "1280",
                ok,
                f"{start}: {reached}; Enter on strip-{want} → id={v['id']} h1={v['h1']!r}, focus={after}; "
                f"Enter on next → id={self.day_id(page)}, focus={after2}",
            )
        finally:
            ctx.close()

    def check_announce(self) -> None:
        """12: the live region names the target in words; the slider and the strip links carry dates in words."""
        ctx = self.context(LAPTOP)
        try:
            start = self.middle_day()
            page = self.open(ctx, self.day_path(start))
            target = self.click_swap(page, "a[data-focus='next']")
            page.wait_for_timeout(100)
            live = page.locator("[data-day-live]").text_content() or ""
            attrs = page.evaluate(
                "() => { const l = document.querySelector('[data-day-live]'); return [l.getAttribute('aria-live'), l.getAttribute('role')]; }"
            )
            vt = page.locator("[data-day-index]").get_attribute("aria-valuetext") or ""
            names = page.evaluate(
                "() => [...document.querySelectorAll('.strip a[data-day-link]')].map(a => a.getAttribute('aria-label') || a.textContent.trim())"
            )
            unnamed = [n for n in names if not DATE_WORDS.search(n or "")]
            words = in_words(target)
            ok = words in live and words in vt and attrs[0] == "polite" and names and not unnamed
            self.record(
                "12.announcements",
                "1280",
                ok,
                f"{start} → {target} (expects {words!r}): live region ({attrs[0]}, role={attrs[1]})={live[:160]!r}; slider aria-valuetext={vt!r}; "
                f"{len(names)} strip names, without a date in words: {unnamed}; first/last: {names[:1]} {names[-1:]}",
            )
        finally:
            ctx.close()

    def check_focus_visible(self, vp_name: str, vp: dict) -> None:
        """13: tabbed-to controls are not under the sticky masthead / phone tab bar, and show a focus indicator.

        Forward Tab from the top, and Shift+Tab back up from the footer — the second is the case where the browser scrolls
        the element to the TOP edge, under a sticky header, unless scroll-padding-top accounts for it."""
        ctx = self.context(vp)
        try:
            rows, ok = [], True

            def measure(page, label: str, pred, reverse: bool):
                nonlocal ok
                if reverse:
                    page.evaluate(
                        "() => { const f = [...document.querySelectorAll('footer a, .tabbar a')]; window.scrollTo(0, document.body.scrollHeight);"
                        " const el = [...document.querySelectorAll('footer a')].pop() || f.pop(); el && el.focus(); }"
                    )
                hit, trail = self._tab_until(page, pred, limit=200, reverse=reverse)
                if not hit:
                    ok = False
                    rows.append(f"{label}: never focused by {'Shift+Tab' if reverse else 'Tab'} ({len(trail)} presses)")
                    return
                page.wait_for_timeout(150)
                g = page.evaluate(_FOCUS_GEOMETRY_JS)
                good = g["top"] >= g["navBottom"] - 0.5 and g["bottom"] <= g["tabTop"] + 0.5 and g["visibleRing"]
                ok &= good
                rows.append(
                    f"{label} [{'Shift+Tab' if reverse else 'Tab'}] {g['desc']}: top={g['top']} bottom={g['bottom']} nav bottom={g['navBottom']} "
                    f"tab bar top={g['tabTop']} scroll-padding-top={g['scrollPaddingTop']} outline={g['outline']} box-shadow={g['boxShadow']} "
                    f"scrollY={g['scrollY']} covered at top/bottom edge by={g['coveredBy'] or 'nothing'} → {'ok' if good else 'OBSCURED or no ring'}"
                )

            page = self.open(ctx, "/data/journey/")
            for rev in (False, True):
                if not rev:
                    page.evaluate("() => window.scrollTo(0, 0)")
                measure(page, "journey frame button", lambda a: a.get("frame") == "readings", rev)
                measure(page, "journey show toggle", lambda a: a.get("show") == "chapters", rev)
                measure(page, "journey chart", lambda a: a.get("chart") and a.get("journey"), rev)
            page.close()
            page = self.open(ctx, self.day_path(self.middle_day()))
            for rev in (False, True):
                if not rev:
                    page.evaluate("() => window.scrollTo(0, 0)")
                measure(page, "day strip link", lambda a: (a.get("focus") or "").startswith("strip-"), rev)
                measure(page, "day tile chart", lambda a: a.get("chart"), rev)
            self.record("13.focus-visible", vp_name, ok, " || ".join(rows))
        finally:
            ctx.close()

    def check_reflow(self) -> None:
        """14: no horizontal overflow at 320 px, and at 1280 with 200 % root text."""
        pages = ["/data/journey/", self.day_path(self.middle_day()), self.day_path(self.days[-1]["id"])]
        for vp_name, vp, zoom in (("320", REFLOW, False), ("1280@200%", LAPTOP, True)):
            ctx = self.context(vp)
            try:
                rows, ok = [], True
                for path in pages:
                    page = self.open(ctx, path)
                    if zoom:
                        page.evaluate(
                            "() => { document.documentElement.style.fontSize = '200%'; window.dispatchEvent(new Event('resize')); }"
                        )
                    page.wait_for_timeout(400)
                    o = page.evaluate(_OVERFLOW_JS)
                    good = o["sw"] <= vp["width"]
                    ok &= good
                    rows.append(f"{path}: scrollWidth={o['sw']} clientWidth={o['vw']}{'' if good else ' OVERFLOW ' + str(o['offenders'])}")
                    page.close()
                self.record("14.reflow", vp_name, ok, " | ".join(rows))
            finally:
                ctx.close()

    def check_axe(self) -> None:
        """15: axe-core critical/serious, Journey and one Day at 390, in a bypass_csp context."""
        if not os.path.exists(AXE_JS_PATH):
            self.record("15.axe", "390", False, f"axe bundle missing at {AXE_JS_PATH}")
            return
        ctx = self.context(PHONE, bypass_csp=True)
        try:
            for path in ("/data/journey/", self.day_path(self.middle_day())):
                page = self.open(ctx, path)
                page.add_script_tag(path=AXE_JS_PATH)
                v = page.evaluate(_RUN_AXE_JS)
                self.record("15.axe", "390", not v, f"{path}: {len(v)} critical/serious violations {v}")
                page.close()
        finally:
            ctx.close()

    def check_journey_labels(self, vp_name: str, vp: dict) -> None:
        """16: no overlapping or clipped svg text in the Journey chart."""
        ctx = self.context(vp)
        try:
            page = self.open(ctx, "/data/journey/")
            page.wait_for_timeout(300)
            r = page.evaluate(_SVG_LABELS_JS, "[data-journey-chart] svg")
            if r is None:
                self.record("16.journey-labels", vp_name, False, "no [data-journey-chart] svg")
                return
            ok = not r["overlaps"] and not r["clipped"] and bool(r["labels"])
            self.record(
                "16.journey-labels",
                vp_name,
                ok,
                f"svg frame={r['frame']}; {len(r['labels'])} labels {r['labels']}; overlaps={r['overlaps']}; outside the svg={r['clipped']}",
            )
        finally:
            ctx.close()

    # -- the run -------------------------------------------------------------------------------------------------------
    def run(self) -> None:
        with urllib.request.urlopen(self.url("/data/days.json"), timeout=30) as r:  # noqa: S310 — the site under test
            self.days = sorted(json.loads(r.read()), key=lambda d: d["date"])
        print(f"days.json: {len(self.days)} days, {self.days[0]['id']} … {self.days[-1]['id']}; base {self.base}", flush=True)
        for vp_name, vp in (("1280", LAPTOP), ("390", PHONE)):
            self.guarded("swap-parts", vp_name, lambda vp_name=vp_name, vp=vp: self.check_swaps(vp_name, vp))
        self.guarded("rapid-switch", "1280", self.check_rapid)
        self.guarded("boundaries", "1280", self.check_boundaries)
        self.guarded("missing", "1280", self.check_missing)
        self.guarded("direct", "1280", self.check_direct)
        self.guarded("refresh", "1280", self.check_refresh)
        self.guarded("history", "1280", self.check_history)
        self.guarded("load-failure", "1280", self.check_load_failure)
        for vp_name, vp in (("390", PHONE), ("1280", LAPTOP)):
            self.guarded("inspect", vp_name, lambda vp_name=vp_name, vp=vp: self.check_inspect(vp_name, vp))
        self.guarded("keyboard", "1280", self.check_keyboard)
        self.guarded("announce", "1280", self.check_announce)
        for vp_name, vp in (("1280", LAPTOP), ("390", PHONE)):
            self.guarded("focus-visible", vp_name, lambda vp_name=vp_name, vp=vp: self.check_focus_visible(vp_name, vp))
        self.guarded("reflow", "320", self.check_reflow)
        self.guarded("axe", "390", self.check_axe)
        for vp_name, vp in (("390", PHONE), ("1280", LAPTOP)):
            self.guarded("journey-labels", vp_name, lambda vp_name=vp_name, vp=vp: self.check_journey_labels(vp_name, vp))


GROUPS = ("swap-parts", "rapid-switch", "boundaries", "missing", "direct", "refresh", "history", "load-failure", "inspect", "keyboard")
GROUPS += ("announce", "focus-visible", "reflow", "axe", "journey-labels")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="https://averagejoematt.com", help="site root, e.g. http://127.0.0.1:8765")
    ap.add_argument("--out", required=True, help="directory for journey_day_checks.json")
    ap.add_argument("--cache-bust", action="store_true", help="append a unique query to every direct document load")
    ap.add_argument("--only", default="", help=f"comma-separated check groups: {', '.join(GROUPS)}")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    only = {x.strip() for x in a.only.split(",") if x.strip()} or None
    if only and only - set(GROUPS):
        print(f"unknown check group(s): {sorted(only - set(GROUPS))}", file=sys.stderr)
        return 3
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed: pip install playwright && python3 -m playwright install chromium", file=sys.stderr)
        return 3
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not a.headed)
        suite = Suite(browser, a.base, a.cache_bust, only)
        try:
            suite.run()
        except Exception as e:  # noqa: BLE001
            print(f"setup error: {type(e).__name__}: {e}", file=sys.stderr)
            browser.close()
            return 3
        browser.close()
    out = os.path.join(a.out, "journey_day_checks.json")
    with open(out, "w") as f:
        json.dump(suite.results, f, indent=2)
    failed = [r for r in suite.results if not r["ok"]]
    print(f"\n{len(suite.results) - len(failed)}/{len(suite.results)} checks passed in {time.time() - t0:.0f}s against {a.base} → {out}")
    for r in failed:
        print(f"  FAIL {r['id']} @{r['viewport']}")
    return 0 if suite.results and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
