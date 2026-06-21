/*
  coach_popover.js — CC-04: progressive-disclosure coach-name popovers.
  ----------------------------------------------------------------------------
  Anywhere a coach is named in reader prose (chronicle · journal · AI lab notes),
  the FIRST mention per render becomes a chip → popover: persona, one-line voice,
  and a "full page →" link to /story/coaches/#<id>. Pure enhancement — if the
  roster can't load or no names appear, the text is untouched. The popover is
  appended to <body> (position:absolute), so there's no layout shift (no CLS).
  Keyboard-accessible: chips are real <button>s; Esc closes.
*/

// Shared genesis anchor — stamps "Day N · Week N since June 14 2026" into any
// [data-bind="genesisStamp"] element, so the Story + Coaching doors carry the same
// "it's week one, watch it happen" throughline as the Home hero (cross-site consistency).
export function stampGenesis(root = document) {
  const el = root.querySelector('[data-bind="genesisStamp"]');
  if (!el) return;
  const genesis = new Date("2026-06-14T00:00:00");
  const dayN = Math.floor((Date.now() - genesis.getTime()) / 86400000) + 1;
  if (dayN < 1) return;
  const weekN = Math.floor((dayN - 1) / 7) + 1;
  el.textContent = `Day ${dayN} · Week ${weekN}, since June 14 2026`;
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
function popEl() {
  if (_pop) return _pop;
  _pop = document.createElement("div");
  _pop.className = "coach-pop";
  _pop.setAttribute("role", "dialog");
  _pop.hidden = true;
  document.body.appendChild(_pop);
  document.addEventListener("click", (e) => {
    if (!_pop.hidden && !_pop.contains(e.target) && !e.target.classList.contains("coach-chip")) hide();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
  });
  window.addEventListener("resize", hide);
  return _pop;
}
function hide() {
  if (_pop) _pop.hidden = true;
}
function show(chip, c) {
  const p = popEl();
  p.innerHTML =
    `<p class="cp-name">${esc(c.emoji || "")} ${esc(c.name)}</p>` +
    `<p class="cp-role label">${esc(c.board_role || c.domain || "")}</p>` +
    (c.short_bio ? `<p class="cp-bio">${esc(c.short_bio)}</p>` : "") +
    `<a class="cp-link" href="/coaching/coaches/#${esc(c.persona_id)}">full page →</a>`;
  p.hidden = false;
  const r = chip.getBoundingClientRect();
  const top = window.scrollY + r.bottom + 6;
  const left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - p.offsetWidth - 12);
  p.style.top = `${top}px`;
  p.style.left = `${Math.max(8, left)}px`;
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
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      show(chip, map[hitName]);
    });
    frag.appendChild(chip);
    if (after) frag.appendChild(document.createTextNode(after));
    t.parentNode.replaceChild(frag, t);
  }
}
