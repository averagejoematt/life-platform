/*
  provenance_popover.js — #584 (epic #575, workstream C): "the model never does the
  math" (ADR-062), made verifiable by hovering.
  ----------------------------------------------------------------------------
  Any stat readout a renderer tags with `data-method="<registry-key>"` gets a small
  code-drawn provenance chip → popover: SOURCE (the actual module::function) → FORMULA
  → WINDOW → minimum n → limitations, with a "full method →" link to /method/registry/.

  Registry-fed by construction (ADR-104/105): every field is pulled from /api/methods,
  the SAME registry that renders /method/registry/ and is fingerprint-guarded against
  code drift (lambdas/methods_registry.py). This module hardcodes NO formula/window/n
  text — so the popover cannot drift from what the code actually computes. Honest
  fallback: a `data-method` key with no registry entry gets NO chip (we never invent
  provenance for a number we can't document).

  Pattern mirrors coach_popover.js: chips are real <button>s appended non-destructively;
  the single popover is appended to <body> (position:absolute, no CLS); Esc closes,
  focus is trapped while open and returned to the trigger on close; tap-out / resize
  dismiss. Pure enhancement — if /api/methods can't load, every readout is untouched.
*/

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

let _reg = null; // id -> registry entry (null until first load; {} if load failed)

async function registry() {
  if (_reg) return _reg;
  _reg = {};
  try {
    const r = await fetch("/api/methods", { headers: { accept: "application/json" } });
    if (r.ok) {
      const d = await r.json();
      for (const s of d.stats || []) if (s && s.id) _reg[s.id] = s;
    }
  } catch (e) {
    /* leave _reg empty — enhancement becomes a no-op, readouts untouched */
  }
  return _reg;
}

let _pop = null;
let _trigger = null; // the chip that opened the popover — focus returns here on close

// Everything natively focusable the popover could contain (kept generic; its innerHTML
// is rebuilt per stat, currently just the "full method →" link).
const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function popEl() {
  if (_pop) return _pop;
  _pop = document.createElement("div");
  _pop.className = "prov-pop";
  _pop.setAttribute("role", "dialog");
  _pop.setAttribute("aria-modal", "false"); // a lightweight disclosure, not a blocking modal
  _pop.setAttribute("aria-label", "How this number is computed");
  _pop.hidden = true;
  document.body.appendChild(_pop);
  document.addEventListener("click", (e) => {
    if (!_pop.hidden && !_pop.contains(e.target) && !e.target.closest(".prov-btn")) hide();
  });
  document.addEventListener("keydown", (e) => {
    if (_pop.hidden) return;
    if (e.key === "Escape") { hide(); return; }
    // Focus trap (#579): Tab / Shift+Tab cycle within the popover instead of escaping
    // into the rest of the page while it's open.
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
    _trigger.focus(); // return focus to the trigger (#579) — never strand it on a hidden panel
    _trigger = null;
  }
}

function row(label, value) {
  if (value == null || value === "") return "";
  return `<div class="pv-row"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
}

function show(btn, entry, asof) {
  if (_trigger && _trigger !== btn) _trigger.setAttribute("aria-expanded", "false");
  const p = popEl();
  const src = `${entry.module}.py::${entry.function}`;
  p.innerHTML =
    `<p class="pv-name">${esc(entry.name)}</p>` +
    (entry.formula ? `<p class="pv-formula">${esc(entry.formula)}</p>` : "") +
    "<dl class=\"pv-fields\">" +
    row("source", src) +
    row("window", entry.window) +
    (entry.min_n != null ? row("minimum n", entry.min_n) : "") +
    (asof ? row("last computed", asof) : "") +
    row("limitations", entry.limitations) +
    "</dl>" +
    `<a class="pv-link" href="/method/registry/#stat-${esc(entry.id)}">full method &rarr;</a>`;
  p.hidden = false;
  _trigger = btn;
  btn.setAttribute("aria-expanded", "true");
  const r = btn.getBoundingClientRect();
  const top = window.scrollY + r.bottom + 6;
  const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - p.offsetWidth - 12);
  p.style.top = `${top}px`;
  p.style.left = `${Math.max(8, left)}px`;
  // Move focus into the popover (dialog pattern) — the link is its one focusable element.
  const target = p.querySelector(FOCUSABLE);
  if (target) target.focus();
}

/**
 * Enhance every `[data-method]` readout in `root` with a provenance chip whose popover
 * is rendered from the live /api/methods registry. Idempotent (a wired node is marked
 * and skipped) and non-destructive. Keys with no registry entry get NO chip — honest,
 * we never invent provenance.
 * @param {HTMLElement} root - a rendered container (e.g. the evidence readout).
 */
export async function enhanceProvenance(root) {
  if (!root) return;
  const nodes = root.querySelectorAll("[data-method]:not([data-prov-wired])");
  if (!nodes.length) return;
  const reg = await registry();
  for (const el of nodes) {
    el.setAttribute("data-prov-wired", "1"); // mark regardless, so a missing entry isn't re-scanned
    const key = el.getAttribute("data-method");
    const entry = reg[key];
    if (!entry) continue; // honest fallback: no registry entry ⇒ no popover
    const asof = el.getAttribute("data-asof") || (el.closest("[data-asof]") && el.closest("[data-asof]").getAttribute("data-asof")) || "";
    const host = el.querySelector(".fig-k") || el; // sit on the label so layout doesn't shift
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "prov-btn";
    btn.innerHTML = '<span aria-hidden="true">&#9432;</span>';
    btn.setAttribute("aria-label", `How "${entry.name}" is computed`);
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (btn.getAttribute("aria-expanded") === "true") hide();
      else show(btn, entry, asof);
    });
    host.appendChild(btn);
  }
}
