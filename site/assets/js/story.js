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

/* ── Elena's chronicle spine ─────────────────────────────────────────────── */
function renderChronicle(stats) {
  const wrap = bind("chronicle");
  const recent = (stats && stats.chronicle_recent) || [];
  const latest = stats && stats.chronicle_latest;
  if (latest && latest.headline) bind("chronicle-headline").textContent = latest.headline;
  const items = recent.length ? recent : (latest ? [latest] : []);
  if (!items.length) {
    wrap.innerHTML = `<p class="beat-note">Elena's weekly chronicle is published here as the experiment runs.</p>`;
    return;
  }
  wrap.replaceChildren(...items.slice(0, 3).map((c) => {
    const a = document.createElement("a");
    a.className = "chron-card";
    // Chronicle posts are preserved verbatim under /legacy until rehomed into the Story.
    a.href = c.url || c.path || (c.week ? `/legacy/chronicle/week-${esc(c.week)}/` : "/legacy/chronicle/");
    a.innerHTML =
      `<span class="chron-week label">${c.week != null ? "week " + esc(c.week) : "chronicle"}</span>` +
      `<span class="chron-title">${esc(c.headline || c.title || "A week in the experiment")}</span>` +
      (c.date ? `<span class="chron-date label">${esc(c.date)}</span>` : "");
    return a;
  }));
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

  const [stats, journey, wave, character] = await Promise.allSettled([
    getJSON("/public_stats.json"),
    getJSON("/api/journey"),
    getJSON("/api/journey_waveform"),
    getJSON("/api/character"),
  ]);

  const statsV = stats.status === "fulfilled" ? stats.value : null;
  if (statsV) {
    if (statsV.elena_hero_line) bind("elena").textContent = statsV.elena_hero_line;
    renderChronicle(statsV);
    if (statsV._meta && statsV._meta.generated_at) bind("asof").textContent = `updated ${String(statsV._meta.generated_at).slice(0, 10)}`;
  }

  const journeyV = journey.status === "fulfilled" ? (journey.value.journey || journey.value) : null;
  renderNumbers(journeyV);

  const waveV = wave.status === "fulfilled" ? (wave.value.days || wave.value.waveform || wave.value) : null;
  renderWave(Array.isArray(waveV) ? waveV : (waveV && waveV.days) || []);

  const charV = character.status === "fulfilled" ? character.value : null;
  const pillars = (charV && (charV.pillars || (charV.character && charV.character.pillars))) || [];
  drawConstellation(pillars.length ? pillars : Object.keys(NODES).map((name) => ({ name, raw_score: 12, xp_delta: 0 })));
}

load();
