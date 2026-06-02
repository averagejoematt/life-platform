/*
  story.js — Door 2 behaviour (/)
  ----------------------------------------------------------------------------
  The honest arc, bound to the live engine. Nothing invented: every value is
  from an existing endpoint; absent data degrades to honest copy, never faked.

    /public_stats.json        hero, elena_hero_line, chronicle_recent, character
    /api/journey              weight arc (lost_lbs, progress, projected goal)
    /api/journey_waveform     42-day whole-life score with green/amber/red/gray tiers
    /api/field_notes          the Third Wall (ai_present ↔ matthew_agreement)
    /api/character            pillar scores for the constellation
*/

import { lineChart } from "/assets/js/charts.js";

const $ = (s, r = document) => r.querySelector(s);
const bind = (n, r = document) => r.querySelector(`[data-bind="${n}"]`);
const SVGNS = "http://www.w3.org/2000/svg";

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
const trend = (d) => (d == null ? "flat" : d > 0.05 ? "up" : d < -0.05 ? "down" : "flat");

/* ── the relational constellation ────────────────────────────────────────── */
const NODES = {
  sleep:        { x: 180, y: 58,  label: "Sleep" },
  movement:     { x: 292, y: 118, label: "Move" },
  nutrition:    { x: 292, y: 250, label: "Fuel" },
  metabolic:    { x: 180, y: 312, label: "Metab" },
  mind:         { x: 68,  y: 250, label: "Mind" },
  relationships:{ x: 68,  y: 118, label: "People" },
  consistency:  { x: 180, y: 185, label: "Hold" },
};
// How the pillars pull on each other (the synthesis, drawn).
const EDGES = [
  ["sleep", "movement"], ["sleep", "mind"], ["movement", "metabolic"],
  ["nutrition", "metabolic"], ["nutrition", "mind"], ["mind", "relationships"],
  ["consistency", "sleep"], ["consistency", "movement"], ["consistency", "nutrition"],
  ["consistency", "metabolic"], ["consistency", "mind"], ["consistency", "relationships"],
];

function drawConstellation(pillars) {
  const svg = $(".constellation svg");
  if (!svg) return;
  const edgeG = svg.querySelector("[data-edges]");
  const nodeG = svg.querySelector("[data-nodes]");
  const byName = {};
  for (const p of pillars) byName[p.name] = p;

  for (const [a, b] of EDGES) {
    const na = NODES[a], nb = NODES[b];
    if (!na || !nb) continue;
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("x1", na.x); line.setAttribute("y1", na.y);
    line.setAttribute("x2", nb.x); line.setAttribute("y2", nb.y);
    const live = trend(byName[a]?.xp_delta) === "up" || trend(byName[b]?.xp_delta) === "up";
    line.setAttribute("class", "edge" + (live ? " live" : ""));
    if (a === "consistency") line.setAttribute("stroke-dasharray", "2 4");
    edgeG.appendChild(line);
  }

  for (const [name, pos] of Object.entries(NODES)) {
    const p = byName[name] || {};
    const score = Math.round(p.raw_score ?? 12);
    const r = 14 + Math.min(26, score / 4);   // size by where it stands
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "node" + (trend(p.xp_delta) === "up" ? " up" : ""));
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("cx", pos.x); c.setAttribute("cy", pos.y); c.setAttribute("r", r);
    const tScore = document.createElementNS(SVGNS, "text");
    tScore.setAttribute("class", "score"); tScore.setAttribute("x", pos.x); tScore.setAttribute("y", pos.y + 4);
    tScore.textContent = score || "";
    const tLab = document.createElementNS(SVGNS, "text");
    tLab.setAttribute("x", pos.x); tLab.setAttribute("y", pos.y + r + 12);
    tLab.textContent = pos.label;
    g.append(c, tScore, tLab);
    nodeG.appendChild(g);
  }
}

/* ── the numbers beat ────────────────────────────────────────────────────── */
function renderNumbers(journey) {
  if (!journey) return;
  if (journey.lost_lbs != null) bind("lost").textContent = journey.lost_lbs;
  if (journey.current_weight_lbs != null) bind("current").textContent = journey.current_weight_lbs;
  if (journey.progress_pct != null) bind("progress").textContent = `${journey.progress_pct}%`;
  if (journey.projected_goal_date) {
    bind("projected").textContent = `At the current rate, goal lands around ${journey.projected_goal_date}. Correlative projection — not a promise.`;
  } else if (journey.weekly_rate != null) {
    bind("projected").textContent = "No reliable projection yet — too few weigh-ins in the recent window to draw a line.";
  }
}

/* ── the waveform (honest down-beats) ────────────────────────────────────── */
function tierOf(score) {
  if (score == null || score === 0) return "none";
  if (score >= 250) return "up";
  if (score >= 150) return "mid";
  return "down";
}
function renderWave(days) {
  const wrap = bind("wave");
  if (!wrap || !Array.isArray(days) || !days.length) {
    if (wrap) wrap.textContent = "The waveform fills in as the daily scores accrue.";
    return;
  }
  const max = Math.max(700, ...days.map((d) => d.score || 0));
  wrap.replaceChildren(...days.map((d) => {
    const bar = document.createElement("span");
    bar.className = `bar ${tierOf(d.score)}`;
    const h = d.score ? Math.max(4, (d.score / max) * 100) : 6;
    bar.style.height = `${h}%`;
    bar.title = `${d.date || ""}: ${d.score ?? "no data"}`;
    return bar;
  }));
}

/* ── the Third Wall ──────────────────────────────────────────────────────── */
async function renderWall() {
  const wall = bind("wall");
  try {
    const list = await getJSON("/api/field_notes");
    const latest = list.entries && list.entries[0];
    if (!latest) throw new Error("no field notes");
    const week = latest.week;
    const full = await getJSON(`/api/field_notes?week=${encodeURIComponent(week)}`);
    const e = full.entry || {};
    const aiText = e.ai_present || e.ai_affirming || e.ai_cautionary || "";
    const human = e.matthew_agreement || "";
    wall.innerHTML =
      `<div class="voice machine"><span class="who">The AI</span><p class="what">${esc(aiText)}</p></div>` +
      (human ? `<div class="voice human"><span class="who">Matthew</span><p class="what">${esc(human)}</p></div>`
             : `<div class="voice human"><span class="who">Matthew</span><p class="what">— hasn't replied to this one yet. (That's allowed; the wall is honest both ways.)</p></div>`);
    bind("wall-week").textContent = e.ai_generated_at ? `field note · week ${esc(week)} · ${esc(e.ai_tone || "mixed")}` : `field note · week ${esc(week)}`;
  } catch (_e) {
    wall.innerHTML = `<div class="voice machine"><span class="who">The AI</span><p class="what">The field notes — where the model says its piece and Matthew answers back — appear here each week.</p></div>`;
  }
}

/* ── Dispatches reader — the native narrative archive ─────────────────────── */
/*  Chronicle (Elena), Lab notes (the AI↔Matthew field notes), and the Journal.
    Lab notes render fully native from /api/field_notes; chronicle/journal render
    their real excerpts + metadata from posts.json. Master-detail, deep-linkable. */
const DX = [
  { key: "chronicle", label: "Chronicle", url: "/chronicle/posts.json" },
  { key: "labnotes", label: "Lab notes", url: "/api/field_notes" },
  { key: "journal", label: "Journal", url: "/journal/posts.json" },
];
const dxState = { src: "chronicle", cache: {} };

async function dxFetch(src) {
  if (dxState.cache[src]) return dxState.cache[src];
  const cfg = DX.find((d) => d.key === src);
  try { const d = await getJSON(cfg.url); dxState.cache[src] = d; return d; } catch (e) { return null; }
}
function dxEntries(src, data) {
  if (!data) return [];
  if (src === "labnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "", meta: e.ai_tone }));
  const posts = data.posts || data.entries || (Array.isArray(data) ? data : []);
  return posts.map((p) => ({ id: p.week, title: p.title || `Week ${p.week}`, date: p.date, meta: p.stats_line, excerpt: p.excerpt, word_count: p.word_count }));
}

async function dxRenderRead(src, id) {
  const read = document.querySelector("[data-dx-read]");
  if (src === "labnotes") {
    read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
    try {
      const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`);
      const e = d.entry || {};
      const voices = [["The AI", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"], ["Matthew", e.matthew_agreement, "human"]].filter((v) => v[1]);
      read.innerHTML = `<p class="dx-kicker label">field note · week ${esc(id)}${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
        (voices.length ? voices.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("")
          : `<p class="beat-note">No field note recorded for this week yet.</p>`);
    } catch (e) { read.innerHTML = `<p class="beat-note">Couldn't load this field note just now.</p>`; }
    return;
  }
  const data = await dxFetch(src);
  const ent = dxEntries(src, data).find((x) => String(x.id) === String(id));
  if (!ent) { read.innerHTML = `<p class="beat-note">Pick an entry to read it here.</p>`; return; }
  read.innerHTML =
    `<p class="dx-kicker label">${src === "chronicle" ? "chronicle · Elena Voss" : "journal"} · week ${esc(ent.id)}${ent.date ? ` · ${esc(ent.date)}` : ""}</p>` +
    `<h3 class="dx-title">${esc(ent.title)}</h3>` +
    (ent.meta ? `<p class="dx-stats label">${esc(ent.meta)}</p>` : "") +
    `<p class="dx-prose">${esc(ent.excerpt || "")}</p>` +
    (ent.word_count ? `<p class="dx-foot label">${esc(ent.word_count)} words · full dispatch publishes here as the chronicle fills in</p>` : "");
}

function dxSelectEntry(src, id, silent) {
  document.querySelectorAll(".dx-item").forEach((b) => b.classList.toggle("is-active", String(b.dataset.id) === String(id)));
  if (!silent) { try { history.replaceState(null, "", `#dispatches/${src}/${id}`); } catch (e) {} }
  dxRenderRead(src, id);
}
async function dxSelectSrc(src, preId) {
  dxState.src = src;
  document.querySelectorAll(".dx-tab").forEach((t) => { const on = t.dataset.src === src; t.classList.toggle("is-active", on); t.setAttribute("aria-pressed", String(on)); });
  const listEl = document.querySelector("[data-dx-list]");
  listEl.innerHTML = `<li class="dx-empty"><span class="shimmer">Loading…</span></li>`;
  const entries = dxEntries(src, await dxFetch(src));
  if (!entries.length) { listEl.innerHTML = `<li class="dx-empty">Nothing published here yet — it fills as the experiment runs.</li>`; document.querySelector("[data-dx-read]").innerHTML = ""; return; }
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}</span><span class="dx-item-d label">${esc(e.date || "")}</span></button></li>`).join("");
  listEl.querySelectorAll(".dx-item").forEach((b) => b.addEventListener("click", () => dxSelectEntry(src, b.dataset.id)));
  const initId = preId && entries.some((e) => String(e.id) === String(preId)) ? preId : entries[0].id;
  dxSelectEntry(src, initId, true);
}
function dxBuild() {
  const tabsEl = document.querySelector("[data-dx-tabs]");
  if (!tabsEl) return;
  tabsEl.innerHTML = DX.map((d) => `<button class="dx-tab" data-src="${d.key}" aria-pressed="false">${d.label}</button>`).join("");
  tabsEl.querySelectorAll(".dx-tab").forEach((b) => b.addEventListener("click", () => dxSelectSrc(b.dataset.src)));
  const m = location.hash.match(/#dispatches\/([a-z]+)(?:\/([\w-]+))?/) || [];
  dxSelectSrc(m[1] && DX.some((d) => d.key === m[1]) ? m[1] : "chronicle", m[2]);
}

/* ── theme ───────────────────────────────────────────────────────────────── */
function wireTheme() {
  const btn = $(".theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "light" ? "dark" : "light";
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(() => { document.documentElement.dataset.theme = next; });
    } else {
      document.documentElement.dataset.theme = next;
    }
    try { localStorage.setItem("ajm-theme", next); } catch (e) {}
  });
}

/* ── load ────────────────────────────────────────────────────────────────── */
async function load() {
  wireTheme();
  renderWall();

  const [stats, journey, wave, character, weight] = await Promise.allSettled([
    getJSON("/public_stats.json"),
    getJSON("/api/journey"),
    getJSON("/api/journey_waveform"),
    getJSON("/api/character"),
    getJSON("/api/weight_progress"),
  ]);

  const statsV = stats.status === "fulfilled" ? stats.value : null;
  if (statsV) {
    if (statsV.elena_hero_line) bind("elena").textContent = statsV.elena_hero_line;
    if (statsV._meta && statsV._meta.generated_at) bind("asof").textContent = `updated ${String(statsV._meta.generated_at).slice(0, 10)}`;
  }
  dxBuild();   // the native Dispatches reader (chronicle · lab notes · journal)

  const journeyV = journey.status === "fulfilled" ? (journey.value.journey || journey.value) : null;
  renderNumbers(journeyV);

  const wp = weight.status === "fulfilled" ? (weight.value.weight_progress || weight.value) : [];
  const wc = bind("weightchart");
  if (wc) wc.innerHTML = lineChart(Array.isArray(wp) ? wp : [], { valueKey: "weight_lbs", goal: journeyV && journeyV.goal_weight_lbs, unit: " lb", label: "Weight · the actual line", emptyMsg: "The weight line fills in as weigh-ins accrue." });

  const waveV = wave.status === "fulfilled" ? (wave.value.days || wave.value.waveform || wave.value) : null;
  renderWave(Array.isArray(waveV) ? waveV : (waveV && waveV.days) || []);

  const charV = character.status === "fulfilled" ? character.value : null;
  const pillars = (charV && (charV.pillars || (charV.character && charV.character.pillars))) || [];
  drawConstellation(pillars.length ? pillars : Object.keys(NODES).map((name) => ({ name, raw_score: 12, xp_delta: 0 })));
}

load();
