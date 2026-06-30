/* mind.js — the Mind pillar (reading) page.
 *
 * Reads /api/reading_shelf + /api/reading_overview and renders the shelf
 * (warm spines), the roundedness wheel, and the input-streak habit line.
 * Honest empty states everywhere (day one is beautiful, not broken). No red on
 * this surface — a stalled/set-down book is muted ink, never an alert. The
 * reader's own takeaways are the loudest type; private fields never arrive here
 * (the server projects them out).
 */

const API = "/api";
const $ = (sel, root = document) => root.querySelector(sel);
const bind = (name) => document.querySelector(`[data-bind="${name}"]`);
const rowsEl = (name) => document.querySelector(`[data-rows="${name}"]`);
const emptyEl = (name) => document.querySelector(`[data-empty="${name}"]`);

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function escapeHTML(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

function isBad(v) {
  if (v == null) return true;
  const s = String(v).trim();
  return s === "" || s.toUpperCase() === "N/A" || /^\[.*\]$/.test(s);
}

/* A book "spine" — cover if cached, else a designed text spine in the house palette. */
function spine(item) {
  const book = item.book || {};
  const state = item.state || {};
  const title = isBad(book.title) ? "Untitled" : book.title;
  const author = isBad(book.author) ? "" : book.author;
  const cover = book.coverS3Key ? `/${String(book.coverS3Key).replace(/^generated\//, "")}` : null;
  const status = escapeHTML(state.status || "");
  const rating = state.rating != null ? `<span class="sp-rating num" aria-label="rating">${escapeHTML(state.rating)}★</span>` : "";
  const inner = cover
    ? `<img class="sp-cover" src="${escapeHTML(cover)}" alt="${escapeHTML(title)} cover" loading="lazy">`
    : `<span class="sp-title">${escapeHTML(title)}</span>${author ? `<span class="sp-author">${escapeHTML(author)}</span>` : ""}`;
  return (
    `<figure class="sp sp-${status}" title="${escapeHTML(title)}${author ? " — " + escapeHTML(author) : ""}">` +
    `<span class="sp-face">${inner}</span>` +
    `<figcaption class="sp-cap label">${escapeHTML(title)}${rating}</figcaption>` +
    `</figure>`
  );
}

function renderShelfBlock(name, items) {
  const el = rowsEl(name);
  const empty = emptyEl(name);
  if (!el) return 0;
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    el.innerHTML = "";
    if (empty) empty.hidden = false;
    return 0;
  }
  if (empty) empty.hidden = true;
  el.innerHTML = list.map(spine).join("");
  return list.length;
}

async function renderShelf() {
  let d = null;
  try {
    d = await getJSON(`${API}/reading_shelf`);
  } catch (e) {
    d = { reading: [], queue: [], finished: [], set_down: [] };
  }
  renderShelfBlock("reading", d.reading);
  const fin = renderShelfBlock("finished", d.finished);
  renderShelfBlock("queue", d.queue);
  const setdown = renderShelfBlock("set_down", d.set_down);
  const fc = bind("count-finished");
  if (fc) fc.textContent = fin ? fin : "";
  // the 'set down' shelf only appears once there's something on it (dignified, not a scold)
  const sdBlock = document.querySelector('[data-block="set_down"]');
  if (sdBlock) sdBlock.hidden = setdown === 0;
}

/* The roundedness wheel: domain bars. Refuses to render below a meaningful count. */
function renderWheel(wheel) {
  const el = bind("wheel");
  const empty = emptyEl("wheel");
  if (!el) return;
  const dist = (wheel && wheel.distribution) || {};
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (total < 1 || entries.length < 1) {
    el.innerHTML = "";
    if (empty) empty.hidden = false;
    return;
  }
  if (empty) empty.hidden = true;
  const max = Math.max(...entries.map(([, n]) => n));
  el.innerHTML = entries
    .map(([tag, n]) => {
      const pct = Math.round((n / max) * 100);
      return (
        `<div class="wh-row"><span class="wh-label label">${escapeHTML(tag)}</span>` +
        `<span class="wh-bar"><i style="width:${pct}%"></i></span>` +
        `<span class="wh-n num">${n}</span></div>`
      );
    })
    .join("");
}

/* The habit line — input streak + finished count. Pleasure, never a nag. */
function renderHabit(stats) {
  const el = bind("habit");
  if (!el) return;
  const defs = [
    { key: "input_streak_days", label: "days in a row", unit: "" },
    { key: "finished_count", label: "books kept", unit: "" },
    { key: "sessions_90d", label: "sessions (90d)", unit: "" },
  ];
  const html = defs
    .filter((d) => stats && stats[d.key] != null)
    .map(
      (d) =>
        `<li class="hb-row"><span class="hb-val num">${escapeHTML(stats[d.key])}</span>` +
        `<span class="label">${d.label}</span></li>`
    )
    .join("");
  el.innerHTML =
    html ||
    `<li class="hb-empty label">The habit starts with one session — no streaks to break yet, just the first page.</li>`;
}

/* The Constellation. Honest single-point empty state until enough ideas are kept;
   then a quiet code-drawn graph (ember = recent, muted ink = settled). Never red. */
async function renderConstellation() {
  const fig = bind("constellation");
  if (!fig) return;
  let d = null;
  try {
    d = await getJSON(`${API}/constellation`);
  } catch (e) {
    d = null;
  }
  if (!d || !d.ready || !Array.isArray(d.nodes) || d.nodes.length < 4) {
    return; // keep the beautiful seed empty-state already in the HTML
  }
  const nodes = d.nodes.slice(0, 40);
  const edges = Array.isArray(d.edges) ? d.edges : [];
  const W = 360, H = 360, cx = W / 2, cy = H / 2, r = 140;
  const pos = {};
  nodes.forEach((n, i) => {
    const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
    pos[n.ideaId] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  });
  const edgeSvg = edges
    .filter((e) => pos[e.from] && pos[e.to])
    .map((e) => `<line class="cst-edge" x1="${pos[e.from].x.toFixed(1)}" y1="${pos[e.from].y.toFixed(1)}" x2="${pos[e.to].x.toFixed(1)}" y2="${pos[e.to].y.toFixed(1)}"/>`)
    .join("");
  const nodeSvg = nodes
    .map((n) => {
      const p = pos[n.ideaId];
      const recent = Number(n.recency || 0) > 0.6 ? " cst-recent" : "";
      return `<g class="cst-node${recent}"><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5"/>` +
        `<title>${escapeHTML(n.label || "")}</title></g>`;
    })
    .join("");
  fig.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="A graph of ${nodes.length} ideas kept and their connections">` +
    `<g class="cst-edges">${edgeSvg}</g><g class="cst-nodes">${nodeSvg}</g></svg>` +
    `<figcaption class="label">${nodes.length} ideas kept · ${edges.length} connections</figcaption>`;
}

async function renderOverview() {
  let d = null;
  try {
    d = await getJSON(`${API}/reading_overview`);
  } catch (e) {
    d = null;
  }
  renderWheel(d ? d.wheel : null);
  renderHabit(d ? d.stats : null);
  const asof = bind("asof");
  if (asof && d && d.as_of) asof.textContent = `as of ${d.as_of}`;
}

async function load() {
  const main = $("#mind");
  try {
    await Promise.all([renderShelf(), renderOverview(), renderConstellation()]);
    if (main) main.dataset.state = "ready";
  } catch (e) {
    if (main) main.dataset.state = "ready";
    const err = bind("error");
    if (err) {
      err.textContent = "The shelf hasn't loaded yet — it refreshes through the day. Check back shortly.";
      err.hidden = false;
    }
  }
}

/* Theme toggle (mirrors the cockpit's localStorage contract so light/dark persists). */
function wireTheme() {
  const btn = document.querySelector(".theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || "dark";
    const next = cur === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("ajm-theme", next);
    } catch (e) {}
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireTheme();
  load();
});
