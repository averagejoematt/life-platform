/*
  evidence.js — Door 3 behaviour (/evidence/<topic>/)
  ----------------------------------------------------------------------------
  Bespoke, data-bound readouts per topic — the "archival index · library-meets-
  gallery · rigor performed visually · Readout precision" treatment (Design Brief
  §5, Design System §4). Bound to the REAL published shapes; correlative framing
  throughout. No generic JSON dumping.

  Topic config in window.__EVIDENCE_TOPIC__ (slug, endpoint, mode). A SLUG→renderer
  map dispatches; data-mode topics with no special renderer fall back to a tidy
  scalar/table view. Archive topics show a real editorial card + link to the
  preserved legacy view.
*/

const T = window.__EVIDENCE_TOPIC__ || {};
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}
function isBad(v) { if (v == null) return true; const s = String(v).trim(); return s === "" || /^\[.*\]$/.test(s) || s.toUpperCase() === "N/A"; }
function fmt(v, dec) { if (v == null || v === "") return "—"; const n = Number(v); return Number.isFinite(n) ? (dec != null ? n.toFixed(dec) : (Number.isInteger(n) ? String(n) : n.toFixed(1))) : esc(v); }
function fig(v, k) { return `<div class="fig"><span class="fig-v num">${esc(v)}</span><span class="fig-k label">${esc(k)}</span></div>`; }
function section(title, inner) { return `<section class="rd-sec"><h2 class="rd-h">${esc(title)}</h2>${inner}</section>`; }

// Evidence-strength → class + readable label.
function evClass(ev) {
  const s = String(ev || "").toLowerCase();
  if (/strong|high|robust/.test(s)) return ["backed-strong", "well supported"];
  if (/mod|some|emerg|mixed/.test(s)) return ["backed-some", "moderate support"];
  return ["backed-thin", "preliminary"];
}

/* ── Supplements — the what / why / what's-backed showcase ─────────────────── */
function renderSupplements(d) {
  const groups = d.groups || {};
  const figs = `<div class="figs">${fig(d.total_count ?? Object.values(groups).reduce((a, g) => a + (g.items || []).length, 0), "compounds")}` +
    (d.as_of_date ? fig(d.as_of_date, "as of") : "") + `</div>`;
  const secs = Object.values(groups).map((g) => {
    const cards = (g.items || []).map((s) => {
      const [cls, label] = evClass(s.ev);
      const pct = Math.max(4, Math.min(100, s.evPct ?? 0));
      return `<article class="supp">
        <header class="supp-top">
          <h3 class="supp-name">${esc(s.name)}</h3>
          ${s.dose ? `<span class="supp-dose num">${esc(s.dose)}</span>` : ""}
          ${s.timing ? `<span class="supp-timing label">${esc(s.timing)}</span>` : ""}
        </header>
        ${s.why ? `<p class="supp-why">${esc(s.why)}</p>` : ""}
        <div class="supp-ev">
          <span class="supp-evlabel ${cls}">${label}</span>
          <span class="supp-meter"><i class="${cls}" style="width:${pct}%"></i></span>
          <span class="supp-evpct num">${s.evPct != null ? s.evPct + "%" : ""}</span>
        </div>
        <p class="supp-meta label">${[s.board && "src: " + esc(s.board), s.cost_monthly != null && "$" + esc(s.cost_monthly) + "/mo", s.experiment && "exp: " + esc(s.experiment)].filter(Boolean).join("  ·  ")}</p>
      </article>`;
    }).join("");
    return `<section class="rd-sec"><div class="rd-grouphead"><h2 class="rd-h">${esc(g.name)}</h2>${g.desc ? `<p class="rd-desc">${esc(g.desc)}</p>` : ""}</div><div class="supp-grid">${cards}</div></section>`;
  }).join("");
  return figs + secs +
    `<p class="correlative">Evidence strength is the published research consensus for each compound — not a claim about Matthew specifically. <span class="confidence conf-low">N=1 use</span></p>`;
}

/* ── Labs — the biomarker Readout (instrument precision) ───────────────────── */
function renderLabs(d) {
  const L = d.labs || d;
  const bm = L.biomarkers || [];
  const figs = `<div class="figs">${fig(L.total_draws ?? "—", "draws")}${fig(bm.length, "biomarkers")}${fig(L.flagged_count ?? 0, "flagged")}${L.latest_draw_date ? fig(L.latest_draw_date, "latest draw") : ""}</div>`;
  const byCat = {};
  for (const b of bm) (byCat[b.category || "Other"] = byCat[b.category || "Other"] || []).push(b);
  const secs = Object.entries(byCat).map(([cat, rows]) => {
    const trs = rows.map((b) => {
      const flagged = b.flag && String(b.flag).toLowerCase() !== "null";
      return `<tr class="${flagged ? "rd-flag" : ""}">
        <td class="rd-name">${esc(b.name)}</td>
        <td class="num">${esc(b.value)}${b.unit ? ` <span class="rd-unit">${esc(b.unit)}</span>` : ""}</td>
        <td class="num rd-range">${esc(b.range || "—")}</td>
        <td class="rd-flagcell">${flagged ? `<span class="rd-flagmark">${esc(b.flag)}</span>` : ""}</td>
      </tr>`;
    }).join("");
    return section(cat, `<table class="rd-tbl"><thead><tr><th>biomarker</th><th>value</th><th>reference</th><th>flag</th></tr></thead><tbody>${trs}</tbody></table>`);
  }).join("");
  return figs + secs +
    `<p class="correlative">Reference ranges are lab-provided population ranges; flags mark out-of-range values. Correlative context only. ${L.lab_provider ? `<span class="confidence conf-ok">${esc(L.lab_provider)}</span>` : ""}</p>`;
}

/* ── Protocols ─────────────────────────────────────────────────────────────── */
function renderProtocols(d) {
  const ps = d.protocols || [];
  const cards = ps.map((p) => `<article class="rd-card">
    <header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>
    ${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}
    ${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}
    ${p.key_finding && !isBad(p.key_finding) ? `<p class="rd-line"><span class="label">finding</span> ${esc(p.key_finding)}</p>` : ""}
    <p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier), p.signal_status].filter(Boolean).map(esc).join("  ·  ")}</p>
  </article>`).join("");
  return `<div class="figs">${fig(ps.length, "active protocols")}</div><div class="rd-cards">${cards}</div>` +
    `<p class="correlative">Protocols are Matthew's deliberate interventions, exposed read-only. Correlative — not medical advice. <span class="confidence conf-low">N=1</span></p>`;
}

/* ── Experiments (read-only proof) ─────────────────────────────────────────── */
function renderExperiments(d) {
  const xs = d.experiments || [];
  const cards = xs.map((x) => {
    const done = /complete|done|ended|closed/i.test(x.status || "");
    const verdict = x.hypothesis_confirmed === true ? "confirmed" : x.hypothesis_confirmed === false ? "not confirmed" : (x.outcome || x.status || "running");
    return `<article class="rd-card">
      <header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge ${done ? "" : "rd-badge-live"}">${esc(x.status || "")}</span></header>
      ${x.hypothesis ? `<p class="rd-why"><span class="label">hypothesis</span> ${esc(x.hypothesis)}</p>` : ""}
      ${x.result_summary && !isBad(x.result_summary) ? `<p class="rd-line">${esc(x.result_summary)}</p>` : ""}
      <p class="rd-meta label">${[verdict, x.grade && "grade " + esc(x.grade), x.days_in != null && esc(x.days_in) + "d in", x.progress_pct != null && esc(x.progress_pct) + "%"].filter(Boolean).map(esc).join("  ·  ")}</p>
    </article>`;
  }).join("");
  return `<div class="figs">${fig(xs.length, "experiments")}</div><div class="rd-cards">${cards}</div>` +
    `<p class="correlative">An N=1 instrument exposed as proof — reader participation is deferred. <span class="confidence conf-low">single subject</span></p>`;
}

/* ── Habits ────────────────────────────────────────────────────────────────── */
function renderHabits(d) {
  const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const avgs = d.day_of_week_avgs || [];
  const max = Math.max(1, ...avgs);
  const bars = avgs.map((v, i) => `<div class="hb-col"><span class="hb-bar" style="height:${Math.max(4, (v / max) * 100)}%"></span><span class="hb-day label">${dows[i] || ""}</span></div>`).join("");
  return `<div class="figs">${fig(d.current_streak ?? 0, "day streak")}${fig(d.days_tracked ?? 0, "days tracked")}</div>` +
    (avgs.length ? section("Adherence by day of week", `<div class="hb-chart">${bars}</div>`) : "") +
    `<p class="correlative">Adherence across pillars — the discipline layer behind the Consistency score. <span class="confidence conf-low">N=1</span></p>`;
}

/* ── Observatory domains (nutrition / sleep / training / physical / mind) ────── */
function renderObservatory(d) {
  const s = d.summary || {};
  const period = Array.isArray(d.period) ? d.period.join(" → ") : "";
  const stat = (o) => `${o.value != null && o.value !== "" ? esc(o.value) : "—"}${o.unit ? ` <span class="rd-unit">${esc(o.unit)}</span>` : ""}`;
  const card = (o) => (o && o.label)
    ? `<div class="fig"><span class="fig-v num">${stat(o)}</span><span class="fig-k label">${esc(o.label)}</span>` +
      (o.delta_label ? `<span class="rd-delta ${o.trend === "up" ? "rd-up" : o.trend === "down" ? "rd-down" : ""}">${esc(o.delta_label)}</span>`
        : (o.detail ? `<span class="rd-delta">${esc(o.detail)}</span>` : "")) + `</div>`
    : "";
  return `<div class="figs rd-obsfigs">${card(s.primary)}${card(s.highlight)}${card(s.lowlight)}</div>` +
    (d.notable ? `<p class="rd-notable">${esc(d.notable)}</p>` : "") +
    `<p class="correlative">Weekly view${period ? ` · ${esc(period)}` : ""}. Correlative, this week only. <span class="confidence conf-low">7-day window</span></p>`;
}

/* ── Generic fallback (tidy, not a dump) ──────────────────────────────────── */
function renderGeneric(d) {
  const root = (T.root && d[T.root]) ? d[T.root] : d;
  const scal = Object.entries(root).filter(([k, v]) => !k.startsWith("_") && ["string", "number", "boolean"].includes(typeof v));
  const figs = scal.slice(0, 4).map(([k, v]) => fig(fmt(v), k.replace(/_/g, " "))).join("");
  let arr = null, key = null;
  for (const [k, v] of Object.entries(root)) if (Array.isArray(v) && v.length && typeof v[0] === "object") { arr = v; key = k; break; }
  let table = "";
  if (arr) {
    const cols = [...new Set(arr.flatMap((r) => Object.keys(r)))].filter((c) => !c.startsWith("_")).slice(0, 5);
    table = section(key, `<table class="rd-tbl"><thead><tr>${cols.map((c) => `<th>${esc(c.replace(/_/g, " "))}</th>`).join("")}</tr></thead><tbody>${arr.slice(0, 40).map((r) => `<tr>${cols.map((c) => `<td>${esc(fmt(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
  }
  return `<div class="figs">${figs}</div>${table}<p class="correlative">Correlative read only. <span class="confidence conf-low">N=1</span></p>`;
}

const RENDERERS = {
  supplements: renderSupplements, labs: renderLabs, protocols: renderProtocols,
  experiments: renderExperiments, challenges: renderExperiments, habits: renderHabits,
  nutrition: renderObservatory, sleep: renderObservatory, training: renderObservatory,
  physical: renderObservatory, mind: renderObservatory,
};

async function render() {
  const out = document.querySelector("[data-readout]");
  if (!out) return;
  if (T.mode !== "data" || !T.endpoint) {
    out.innerHTML = `<p class="rd-archive">${esc(T.archive_note || "This section lives in the archive while it's rebuilt into the new Evidence treatment.")}</p>`;
    return;
  }
  try {
    const data = await getJSON(T.endpoint);
    const fn = RENDERERS[T.slug] || renderGeneric;
    const html = fn(data);
    out.innerHTML = html && html.trim() ? html : `<p class="rd-archive">No data published for this section yet — it refreshes from the live pipeline.</p>`;
  } catch (e) {
    out.innerHTML = `<p class="rd-archive">This readout couldn't load its data just now. The preserved view is linked below.</p>`;
  }
}

function wireTheme() {
  const btn = document.querySelector(".theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("ajm-theme", next); } catch (e) {}
  });
}

wireTheme();
render();
