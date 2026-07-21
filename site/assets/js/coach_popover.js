/*
  coach_popover.js — CC-04: progressive-disclosure coach-name popovers.
  ----------------------------------------------------------------------------
  Anywhere a coach is named in reader prose (chronicle · journal · AI lab notes),
  the FIRST mention per render becomes a chip → popover: persona, one-line voice,
  and a "full page →" link to /coaching/coaches/#<id>. Pure enhancement — if the
  roster can't load or no names appear, the text is untouched. The popover is
  appended to <body> (position:absolute), so there's no layout shift (no CLS).
  Keyboard-accessible: chips are real <button>s; Esc closes.
*/
import { sigil } from "/assets/js/sigils.js";
import { portrait } from "/assets/js/portraits.js"; // §8.7 — portrait(c) || sigil(c)

// THE single genesis source of truth (P0.1). Genesis = 2026-06-14; Day N = whole days since,
// +1 so genesis day is Day 1; Week N = floor((dayN-1)/7)+1 (Day 8 = Week 2). EVERY door's
// Day-N/Week stamp consumes this one function — no door re-implements the math (that drift was
// the original cross-door bug). `genesisCount()` is the pure calc; `stampGenesis()` writes it
// into any [data-bind="genesisStamp"] element, with an optional per-door suffix.
// Exported (#1088) so the cockpit's time-travel scrub floor shares THIS single
// client literal as its boot fallback (the API payload is the runtime truth).
// The reset sweep (deploy/restart_site_copy_sync.py rewrite_js_files) follows
// the quoted ISO form here — keep it a plain quoted literal.
export const GENESIS_ISO = "2026-07-22";
const GENESIS = new Date(`${GENESIS_ISO}T00:00:00`);
export function genesisCount() {
  const dayN = Math.floor((Date.now() - GENESIS.getTime()) / 86400000) + 1;
  const weekN = Math.floor((Math.max(1, dayN) - 1) / 7) + 1;
  return { dayN, weekN, base: `Day ${dayN} · Week ${weekN}, since July 22 2026` };
}

// Pre-start countdown (#931). A reset can stage a FUTURE genesis (constants + this
// file's GENESIS literal regenerate together the night before Day 1) — for that
// window every door counts down to Day 1 instead of rendering a broken Day 0.
// Payload-first: the API's journey/snapshot/pulse blocks carry
// {pre_start, days_until_start, start_date}; the client GENESIS is the fallback so
// the state can't be missed while a cached payload lags. Returns null once the
// experiment has started (dayN >= 1 and no pre_start payload) — the inert path.
function _preShape(daysUntil, d) {
  return {
    daysUntil,
    startLabel: d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }),
    startDow: d.toLocaleDateString("en-US", { weekday: "long" }),
  };
}
export function preStart(payload) {
  if (payload && payload.pre_start && payload.start_date) {
    const d = new Date(`${payload.start_date}T00:00:00`);
    const n = Number(payload.days_until_start);
    if (!isNaN(d.getTime()) && Number.isFinite(n) && n >= 1) return _preShape(n, d);
  }
  const { dayN } = genesisCount();
  if (dayN >= 1) return null;
  return _preShape(1 - dayN, GENESIS);
}

export function stampGenesis(root = document, suffix = "") {
  const el = root.querySelector('[data-bind="genesisStamp"]');
  if (!el) return;
  // Pre-start (#931): the stamp becomes the countdown — calm, dated, no urgency.
  const pre = preStart();
  if (pre) {
    el.textContent = pre.daysUntil === 1
      ? `The experiment begins tomorrow — ${pre.startLabel}`
      : `The experiment begins in ${pre.daysUntil} days — ${pre.startLabel}`;
    el.hidden = false;
    return;
  }
  const { dayN, base } = genesisCount();
  if (dayN < 1) return;
  el.textContent = base + (suffix || "");
  el.hidden = false;
}

let _map = null; // display name -> persona dict

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

async function coachMap() {
  if (_map) return _map;
  _map = {};
  try {
    const r = await fetch("/api/coaches", { headers: { accept: "application/json" } });
    if (r.ok) {
      const d = await r.json();
      for (const c of d.coaches || []) if (c.name) _map[c.name] = c;
    }
  } catch (e) {
    /* leave _map empty — enhancement is a no-op */
  }
  return _map;
}

let _pop = null;
let _trigger = null; // the chip that opened the popover — focus returns here on close

// All natively-focusable elements a popover could contain (kept generic since
// the popover's innerHTML is rebuilt per coach, currently just the "full page →" link).
const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function popEl() {
  if (_pop) return _pop;
  _pop = document.createElement("div");
  _pop.className = "coach-pop";
  _pop.setAttribute("role", "dialog");
  _pop.setAttribute("aria-modal", "false"); // a lightweight disclosure, not a blocking modal
  _pop.hidden = true;
  document.body.appendChild(_pop);
  document.addEventListener("click", (e) => {
    if (!_pop.hidden && !_pop.contains(e.target) && !e.target.classList.contains("coach-chip")) hide();
  });
  document.addEventListener("keydown", (e) => {
    if (_pop.hidden) return;
    if (e.key === "Escape") { hide(); return; }
    // Focus trap (#579): Tab/Shift+Tab cycles within the popover's focusable elements
    // instead of escaping into the rest of the page while it's open.
    if (e.key === "Tab") {
      const items = Array.from(_pop.querySelectorAll(FOCUSABLE));
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  window.addEventListener("resize", hide);
  return _pop;
}
function hide() {
  if (!_pop || _pop.hidden) return;
  _pop.hidden = true;
  if (_trigger) {
    _trigger.setAttribute("aria-expanded", "false");
    _trigger.focus(); // return focus to the trigger (#579) — never strand it on a removed panel
    _trigger = null;
  }
}
function show(chip, c) {
  if (_trigger && _trigger !== chip) _trigger.setAttribute("aria-expanded", "false");
  const p = popEl();
  p.innerHTML =
    `<p class="cp-name" style="--coach:${esc(c.color || "")}"><span class="coach-mark">${portrait(c, { title: "", size: 18 }) || sigil(c, { title: "" })}</span>${esc(c.name)}</p>` +
    `<p class="cp-role label">${esc(c.board_role || c.domain || "")}</p>` +
    (c.short_bio ? `<p class="cp-bio">${esc(c.short_bio)}</p>` : "") +
    `<a class="cp-link" href="/coaching/coaches/#${esc(c.persona_id)}">full page →</a>`;
  p.hidden = false;
  _trigger = chip;
  chip.setAttribute("aria-expanded", "true");
  const r = chip.getBoundingClientRect();
  const top = window.scrollY + r.bottom + 6;
  const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - p.offsetWidth - 12);
  p.style.top = `${top}px`;
  p.style.left = `${Math.max(8, left)}px`;
  // Move focus into the popover (dialog pattern) — the link is its one focusable element.
  const target = p.querySelector(FOCUSABLE);
  if (target) target.focus();
}

/**
 * Wrap the first mention of each known coach name within `root` in a chip.
 * @param {HTMLElement} root - the rendered reader element to enhance.
 */
export async function enhanceCoachNames(root) {
  if (!root) return;
  const map = await coachMap();
  const names = Object.keys(map).sort((a, b) => b.length - a.length); // longest first (avoid partials)
  if (!names.length) return;

  const seen = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.nodeValue && n.parentElement && !n.parentElement.closest(".coach-chip,a,button,script,style,code")
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT,
  });
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  for (const t of textNodes) {
    const txt = t.nodeValue;
    let hitName = null;
    let hitIdx = -1;
    for (const name of names) {
      if (seen.has(name)) continue;
      const idx = txt.indexOf(name);
      if (idx >= 0 && (hitIdx < 0 || idx < hitIdx)) {
        hitName = name;
        hitIdx = idx;
      }
    }
    if (!hitName) continue;
    seen.add(hitName);
    const before = txt.slice(0, hitIdx);
    const after = txt.slice(hitIdx + hitName.length);
    const frag = document.createDocumentFragment();
    if (before) frag.appendChild(document.createTextNode(before));
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "coach-chip";
    chip.textContent = hitName;
    chip.setAttribute("aria-label", `${hitName} — coach details`);
    chip.setAttribute("aria-haspopup", "dialog");
    chip.setAttribute("aria-expanded", "false");
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      if (chip.getAttribute("aria-expanded") === "true") hide();
      else show(chip, map[hitName]);
    });
    frag.appendChild(chip);
    if (after) frag.appendChild(document.createTextNode(after));
    t.parentNode.replaceChild(frag, t);
  }
}
