/*
  section_toc.js — the shared mobile section-TOC / anchor-nav primitive (#1015).

  A very deep page (the labs readout is ~19 screens at 390px) gets a sticky,
  collapsible "on this page" bar: one tap opens the section list, one tap jumps
  to a section — so every major section is reachable in <= 2 taps. Each section
  also gets a real id, so deep links (/data/labs/#metabolic) are shareable.

  Usage (see evidence.js for the SPA readouts, the /gear/ shell for static HTML):
      import { mountSectionToc } from "/assets/js/section_toc.js";
      mountSectionToc(scopeEl, { content: readoutEl, before: readoutEl });

  - scope: the ancestor the sticky bar lives in. It must span the sections and
    have no overflow/transform on the chain (position:sticky sticks within it) —
    .ev-main and .gr-wrap both qualify.
  - content: element scanned for headings (default: scope). Headings matching
    opts.headingSel (default ".rd-h") anchor their enclosing .rd-sec/.gr-cat-head.
  - before: element the nav is inserted before (default: content).
  - App-bar safety (#1007): the bar is TOP-sticky while the mobile app-bar is
    bottom-fixed (@layer chrome, tokens.css), and the open list is height-capped
    well short of the bar — the two can never collide. Desktop (>=821px) hides
    the affordance in CSS; the section ids remain for deep links.
  - Tap floor (#1010): toggle and every list link are min-height 44px.
  - Styles self-inject (/assets/css/section_toc.css) so the generated evidence
    shells need no rebuild (same spirit as the JS-injected ev-intro card). The
    nav stays hidden until the stylesheet lands — no unstyled flash, and a CSS
    fetch failure just means no affordance, never a broken page.
*/

let cssReady = null;

function ensureCss() {
  if (cssReady) return cssReady;
  cssReady = new Promise((resolve) => {
    if (document.querySelector("link[data-stoc]")) { resolve(true); return; }
    const l = document.createElement("link");
    l.rel = "stylesheet"; l.href = "/assets/css/section_toc.css"; l.dataset.stoc = "1";
    l.onload = () => resolve(true);
    l.onerror = () => resolve(false); // fail quiet — the bar simply never shows
    document.head.appendChild(l);
  });
  return cssReady;
}

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const slugify = (t) =>
  String(t || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "section";

export function mountSectionToc(scope, opts = {}) {
  if (!scope) return null;
  const stale = scope.querySelector(".stoc");
  if (stale) stale.remove();

  const content = opts.content || scope;
  const min = opts.min == null ? 3 : opts.min;
  const headingSel = opts.headingSel || ".rd-h";

  // ── Collect anchors: every heading claims its enclosing section once ──────
  const claimed = new Set();
  const items = [];
  content.querySelectorAll(headingSel).forEach((h) => {
    const text = (h.textContent || "").trim();
    if (!text) return;
    let target = h.closest(".rd-sec, .gr-cat-head") || h;
    if (claimed.has(target)) target = h; // second heading inside one section anchors itself
    if (claimed.has(target)) return;
    claimed.add(target);
    if (!target.id) {
      const base = slugify(text);
      let id = base, n = 2;
      while (document.getElementById(id)) id = `${base}-${n++}`;
      target.id = id;
    }
    target.classList.add("stoc-target"); // scroll-margin clears the stuck bar
    items.push({ id: target.id, text, target });
  });
  if (items.length < min) return null;

  // ── Build the nav ──────────────────────────────────────────────────────────
  const nav = document.createElement("nav");
  nav.className = "stoc";
  nav.setAttribute("aria-label", "On this page");
  nav.hidden = true; // revealed once the stylesheet is in
  const listId = `stoc-list-${slugify(items[0].id).slice(0, 12)}-${items.length}`;
  nav.innerHTML =
    `<button class="stoc-toggle" type="button" aria-expanded="false" aria-controls="${esc(listId)}">` +
    `<span class="stoc-k">on this page</span>` +
    `<span class="stoc-count">${items.length} sections</span>` +
    `<span class="stoc-caret" aria-hidden="true"></span></button>` +
    `<ol class="stoc-list" id="${esc(listId)}" hidden>` +
    items.map((it) => `<li><a href="#${esc(it.id)}">${esc(it.text)}</a></li>`).join("") +
    `</ol>`;

  const toggle = nav.querySelector(".stoc-toggle");
  const list = nav.querySelector(".stoc-list");

  const onOutside = (e) => { if (!nav.contains(e.target)) setOpen(false); };
  const onKey = (e) => { if (e.key === "Escape") { setOpen(false); toggle.focus(); } };
  function setOpen(open) {
    toggle.setAttribute("aria-expanded", String(open));
    list.hidden = !open;
    if (open) {
      // App-bar collision guard (#1007): clamp the open list to the space between
      // its own top edge and the fixed bottom app-bar, so the last link can never
      // be swallowed under the bar. Falls back to the viewport when there's no
      // fixed bar (tablet 601-820, desktop).
      const doors = document.querySelector(".doors");
      const barTop = doors && getComputedStyle(doors).position === "fixed" ? doors.getBoundingClientRect().top : window.innerHeight;
      const top = list.getBoundingClientRect().top;
      list.style.maxHeight = `${Math.max(160, Math.floor(barTop - top - 10))}px`;
      document.addEventListener("click", onOutside, true);
      document.addEventListener("keydown", onKey);
    } else {
      document.removeEventListener("click", onOutside, true);
      document.removeEventListener("keydown", onKey);
    }
  }
  toggle.addEventListener("click", () => setOpen(list.hidden));

  const jump = (target, smooth) => {
    // Smooth only for short hops: gliding 10,000+px (these pages run 13-16k tall
    // at 390px) is seconds of dizzy scroll — a long jump lands instantly, like a
    // native anchor. Reduced-motion is always instant.
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const near = Math.abs(target.getBoundingClientRect().top) < window.innerHeight * 3;
    target.scrollIntoView({ block: "start", behavior: smooth && near && !reduce ? "smooth" : "auto" });
  };

  list.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    // preventDefault: a raw hash navigation fires popstate, which the evidence
    // SPA router treats as a route change and re-fetches the whole readout.
    e.preventDefault();
    const href = a.getAttribute("href") || "";
    const it = items.find((x) => `#${x.id}` === href);
    if (!it) return;
    setOpen(false);
    history.replaceState(history.state, "", `${location.pathname}${href}`);
    jump(it.target, true);
  });

  (opts.before || content).insertAdjacentElement("beforebegin", nav);
  ensureCss().then((ok) => { if (ok) nav.hidden = false; });

  // ── Shareable deep link: honor a #hash that names one of our sections ─────
  if (location.hash) {
    let el = null;
    try { el = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { /* malformed hash */ }
    // rAF so the instant jump lands AFTER the evidence router's own mobile
    // scroll-to-readout (renderCenter calls scrollIntoView right after us).
    if (el && claimed.has(el)) requestAnimationFrame(() => jump(el, false));
  }

  return nav;
}
