/*
  evidence.js — Door 3 behaviour (/evidence/<topic>/)
  ----------------------------------------------------------------------------
  Generic, honest "readout" renderer. Each topic page declares its config in
  window.__EVIDENCE_TOPIC__ (written by scripts/v4_build_evidence.py). Data-mode
  topics fetch their published endpoint and render the ACTUAL data — never
  fabricated. Correlative framing is applied to every read; thin data is flagged
  preliminary. Anything richer/interactive links to its preserved /legacy view.
*/

const T = window.__EVIDENCE_TOPIC__ || {};
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

function isScalar(v) { return v == null || ["string", "number", "boolean"].includes(typeof v); }
function fmt(v) {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}
function titleize(k) { return String(k).replace(/_/g, " "); }

// Confidence label from an observation count (Henning standard).
function confidenceLabel(n) {
  if (typeof n !== "number") return null;
  if (n < 12) return { cls: "conf-prelim", text: `preliminary pattern · ${n} obs` };
  if (n < 30) return { cls: "conf-low", text: `low confidence · n=${n}` };
  return { cls: "conf-ok", text: `n=${n}` };
}

function pickArray(obj) {
  for (const [k, v] of Object.entries(obj)) {
    if (Array.isArray(v) && v.length && typeof v[0] === "object") return [k, v];
  }
  return [null, null];
}

function renderScalars(obj) {
  const entries = Object.entries(obj).filter(([k, v]) => isScalar(v) && !k.startsWith("_"));
  if (!entries.length) return "";
  const figs = entries.slice(0, 4).map(([k, v]) =>
    `<div class="fig"><span class="fig-v num">${esc(fmt(v))}</span><span class="fig-k label">${esc(titleize(k))}</span></div>`);
  const rest = entries.slice(4).map(([k, v]) => `<dt>${esc(titleize(k))}</dt><dd>${esc(fmt(v))}</dd>`);
  return (figs.length ? `<div class="figs">${figs.join("")}</div>` : "") +
         (rest.length ? `<dl class="dl">${rest.join("")}</dl>` : "");
}

function renderTable(rowsArr) {
  const cols = [...new Set(rowsArr.flatMap((r) => Object.keys(r)))]
    .filter((c) => !c.startsWith("_")).slice(0, 6);
  const head = cols.map((c) => `<th>${esc(titleize(c))}</th>`).join("");
  const body = rowsArr.slice(0, 40).map((r) =>
    `<tr>${cols.map((c) => `<td>${esc(fmt(r[c]))}</td>`).join("")}</tr>`).join("");
  return `<table class="readout-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// Special-case: supplements with what / why / what's backed.
function renderSupplements(items) {
  return `<div class="supp">` + items.slice(0, 40).map((s) => {
    const backed = (s.evidence || s.backed || s.evidence_level || "").toString().toLowerCase();
    const cls = /strong|high|robust/.test(backed) ? "backed-strong"
      : /some|moderate|mixed/.test(backed) ? "backed-some" : "backed-thin";
    return `<div class="supp-item">` +
      `<div class="supp-name">${esc(s.name || s.supplement || s.title || "—")}</div>` +
      (s.dose || s.dosage ? `<div class="supp-row"><span class="label">dose</span><span>${esc(s.dose || s.dosage)}</span></div>` : "") +
      (s.why || s.reason || s.purpose ? `<div class="supp-row"><span class="label">why</span><span>${esc(s.why || s.reason || s.purpose)}</span></div>` : "") +
      (backed ? `<div class="supp-row"><span class="label">backed</span><span class="supp-backed ${cls}">${esc(backed)}</span></div>` : "") +
      `</div>`;
  }).join("") + `</div>`;
}

async function render() {
  const out = $("[data-readout]");
  if (!out) return;

  if (T.mode !== "data" || !T.endpoint) {
    // Archive/meta topic: honest intro + link to the preserved interactive view.
    out.innerHTML = `<p class="ev-note">${esc(T.archive_note || "The full interactive view is preserved below while this section is rebuilt into the new Evidence treatment.")}</p>`;
    return;
  }

  try {
    const data = await getJSON(T.endpoint);
    const root = (T.root && data[T.root]) ? data[T.root] : data;

    let html = "";
    if (T.slug === "supplements") {
      const [, arr] = pickArray(root);
      html += renderScalars(root);
      if (arr) html += renderSupplements(arr);
    } else {
      html += renderScalars(root);
      const [, arr] = pickArray(root);
      if (arr) html += renderTable(arr);
    }

    // Confidence flag if the payload exposes an observation count.
    const n = root.observations ?? root.n ?? root.sample_size ?? root.count;
    const conf = confidenceLabel(typeof n === "number" ? n : undefined);
    html += `<p class="correlative">Correlative read only — these figures describe what co-occurred, not what caused what. ` +
            (conf ? `<span class="confidence ${conf.cls}">${conf.text}</span>` : `<span class="confidence conf-low">N=1 experiment</span>`) +
            `</p>`;

    out.innerHTML = html || `<p class="ev-note">No data published for this section yet.</p>`;
  } catch (e) {
    out.innerHTML = `<p class="ev-note">This readout couldn't load its data just now. The full view is preserved below.</p>`;
  }
}

function wireTheme() {
  const btn = $(".theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "light" ? "dark" : "light";
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(() => { document.documentElement.dataset.theme = next; });
    } else { document.documentElement.dataset.theme = next; }
    try { localStorage.setItem("ajm-theme", next); } catch (e) {}
  });
}

wireTheme();
render();
