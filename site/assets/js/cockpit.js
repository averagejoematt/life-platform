/*
  cockpit.js — Door 1 behaviour (/now)
  ----------------------------------------------------------------------------
  Binds the Cockpit to the live engine. No data is invented: every value comes
  from an existing endpoint, and anything absent is shown honestly or omitted.

  Endpoints (all read-only, already published):
    /api/snapshot          vitals + journey + character in one call
    /api/weekly_priority    The Chair's cross-pillar synthesis (Dr. Kai Nakamura)
    /api/coach_analysis?domain=<pillar>   lazy per-pillar read on disclosure

  Two jobs (LOCKED): the glance answers "am I winning + the one thing"; a pillar
  view answers "why it's here, where it's heading, what to do". Detail opens in
  place (View Transitions) — never a navigation away.
*/

import { sparkline } from "/assets/js/charts.js";
import { domainIcon } from "/assets/js/icons.js";

const API = "/api";

// Pillar → domain grouping (LOCKED, Constitution §6). Consistency is the band.
const BODY = ["movement", "nutrition", "sleep", "metabolic"];
const MIND = ["mind", "relationships"];
const PILLAR_LABEL = {
  movement: "Movement", nutrition: "Nutrition", sleep: "Sleep",
  metabolic: "Metabolic", mind: "Mind", relationships: "Relationships",
  consistency: "Consistency",
};

const $ = (sel, root = document) => root.querySelector(sel);
const bind = (name, root = document) => root.querySelector(`[data-bind="${name}"]`);
const rows = (name) => document.querySelector(`[data-rows="${name}"]`);

const state = { scope: "today", pillars: {}, coachCache: {} };

/* ── fetch helpers ───────────────────────────────────────────────────────── */
async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

/* ── trend helpers ───────────────────────────────────────────────────────── */
function trendOf(delta) {
  if (delta == null) return "flat";
  if (delta > 0.05) return "up";
  if (delta < -0.05) return "down";
  return "flat";
}
const MARK = { up: "▲", down: "▼", flat: "›" };

/* ── render: the hub + honesty + dialogue ────────────────────────────────── */
function renderHub(character) {
  const lvl = Math.round(character.level ?? 1);
  bind("level").textContent = lvl;
  bind("tier").textContent = character.tier || "Foundation";

  // Spine carries the day index of the experiment.
  if (character.as_of_date && character.started_date) {
    const d0 = Date.parse(character.started_date);
    const d1 = Date.parse(character.as_of_date);
    if (!Number.isNaN(d0) && !Number.isNaN(d1)) {
      const day = Math.max(0, Math.round((d1 - d0) / 86400000));
      bind("day").textContent = String(day).padStart(3, "0");
    }
  }

  // composite_delta_1d is record-over-record (the morning sheet vs the prior
  // morning sheet), so the honest period label is "since yesterday morning",
  // not the ambiguous "today".
  const delta = character.composite_delta_1d;
  const mv = bind("movement");
  if (delta != null) {
    const dir = trendOf(delta);
    mv.dataset.dir = dir;
    mv.textContent = `${MARK[dir]} ${delta > 0 ? "+" : ""}${delta} since yesterday morning`;
    mv.hidden = false;
  }

  // Honesty: a down/flat composite is shown plainly, never hidden, never red.
  const honest = bind("honest");
  if (delta != null && delta < 0) {
    honest.textContent = `▼ ${delta} ${state.scope === "week" ? "this week" : "since yesterday morning"} — logged honestly, not hidden.`;
    honest.hidden = false;
  } else {
    honest.hidden = true;
  }
}

// True for missing/sentinel/error values so they never render raw to a visitor
// (e.g. "[AI_UNAVAILABLE]", "", "N/A", any "[...]" placeholder).
function isBad(v) {
  if (v == null) return true;
  const s = String(v).trim();
  return s === "" || s.toUpperCase() === "N/A" || /^\[.*\]$/.test(s);
}

function renderVerdict(priority) {
  const v = bind("verdict");
  const text = priority && priority.weekly_priority;
  if (!isBad(text)) {
    v.innerHTML = `<span class="mark">&rsaquo;</span> ${escapeHTML(text)}`;
  } else {
    v.innerHTML = `<span class="mark">&rsaquo;</span> The board's weekly read isn't in yet — it posts after the next briefing.`;
  }
}

/* ── render: the two domains + consistency band ──────────────────────────── */
function rollup(keys) {
  const vals = keys.map((k) => state.pillars[k]?.raw_score).filter((n) => typeof n === "number");
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}

function pillarRow(key) {
  const p = state.pillars[key];
  const score = Math.round(p?.raw_score ?? 0);
  // score_delta is the day-over-day move (vs yesterday's sheet); prefer it for the
  // glance arrow so the trend means the same thing the detail spells out.
  const dir = trendOf(p?.score_delta ?? p?.xp_delta);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `row ${dir === "up" ? "up" : dir === "down" ? "dn" : ""}`;
  btn.dataset.pillar = key;
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML =
    `<span class="lab">${domainIcon(key, { cls: "dom-ico" })}${PILLAR_LABEL[key] || key}</span>` +
    `<span class="track"><i style="width:${Math.min(100, score)}%"></i></span>` +
    `<span class="val num">${score}</span>` +
    `<span class="tr">${MARK[dir]}</span>` +
    `<span class="chev" aria-hidden="true">›</span>`;
  btn.addEventListener("click", () => togglePillar(btn, key));
  return btn;
}

function renderDomains() {
  const bodyRoll = rollup(BODY), mindRoll = rollup(MIND);
  if (bodyRoll != null) bind("roll-body").textContent = bodyRoll;
  if (mindRoll != null) bind("roll-mind").textContent = mindRoll;

  const bodyRows = rows("body"), mindRows = rows("mind");
  bodyRows.replaceChildren(...BODY.filter((k) => state.pillars[k]).map(pillarRow));
  mindRows.replaceChildren(...MIND.filter((k) => state.pillars[k]).map(pillarRow));

  const c = state.pillars.consistency;
  if (c) {
    const score = Math.round(c.raw_score ?? 0);
    bind("consistency-fill").style.width = `${Math.min(100, score)}%`;
    bind("consistency-val").textContent = score;
  }
}

/* ── Band: last night → today (readiness from raw vitals) ──────────────────────
   Recovery / sleep / HRV / resting-HR are wake-date-keyed: they describe last
   night and set today up. Raw readings come straight from snapshot.vitals — no
   extra fetch. Present-tense (hidden in time-travel, where no raw vitals exist
   for a past sheet); honest when a reading is absent (the row is just omitted). */
function fmtNight(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${MON[+m[2] - 1]} ${+m[3]}`;
}

// RQA-04 — the STORED readiness score + component breakdown (computed by daily-metrics-compute,
// surfaced via snapshot.readiness), not a band re-derived from raw vitals. Band worded, never red.
const RD_BAND = { green: ["primed", "rd-band-high"], yellow: ["moderate", "rd-band-mid"], red: ["go easy", "rd-band-low"] };
function renderReadinessScore(readiness) {
  const wrap = $("[data-bind=readiness-score-wrap]"), comp = $("[data-bind=readiness-components]");
  if (!wrap || !comp) return;
  if (!readiness || readiness.score == null) { wrap.hidden = true; comp.innerHTML = ""; return; }
  const [word, cls] = RD_BAND[String(readiness.band || "").toLowerCase()] || ["", ""];
  bind("readiness-score").textContent = Math.round(readiness.score);
  const bandEl = $("[data-bind=readiness-band]");
  bandEl.textContent = word; bandEl.className = "rd-score-band label " + cls;
  comp.innerHTML = (readiness.components || []).map((c) => {
    const pct = Math.max(0, Math.min(100, Number(c.score) || 0));
    return `<li class="rd-comp-row"><span class="label">${escapeHTML(c.label)}</span>` +
      `<span class="rd-comp-track"><span class="rd-comp-fill" style="width:${pct}%"></span></span>` +
      `<span class="rd-comp-v num">${Math.round(pct)}</span></li>`;
  }).join("");
  wrap.hidden = false;
}
function renderReadiness(vitals) {
  const sec = $("[data-readiness]");
  if (!sec) return;
  // Keep the section if the stored readiness score is showing, even with no raw vitals.
  const scoreShown = () => { const w = $("[data-bind=readiness-score-wrap]"); return w && !w.hidden; };
  const rows = $("[data-bind=readinessrows]");
  if (!vitals) { if (rows) rows.innerHTML = ""; sec.hidden = !scoreShown(); return; }

  const night = fmtNight(vitals.night_of);
  bind("readiness-night").textContent = night ? ` · the night of ${night}` : "";

  const defs = [
    { key: "recovery_pct", label: "recovery", unit: "%", status: vitals.recovery_status },
    { key: "sleep_hours", label: "sleep", unit: "h" },
    { key: "hrv_ms", label: "HRV", unit: "ms" },
    { key: "rhr_bpm", label: "resting HR", unit: "bpm" },
  ];
  const html = defs
    .filter((d) => vitals[d.key] != null)
    .map((d) => {
      const cls = d.status ? ` is-${escapeHTML(String(d.status))}` : "";
      return `<li class="rd-row${cls}"><span class="label">${d.label}</span>` +
        `<span class="rd-val num">${escapeHTML(String(vitals[d.key]))}<small> ${d.unit}</small></span></li>`;
    })
    .join("");
  if (!html) { bind("readinessrows").innerHTML = ""; sec.hidden = !scoreShown(); return; }
  bind("readinessrows").innerHTML = html;
  sec.hidden = false;
}

/* ── in-place pillar disclosure (View Transitions) ───────────────────────── */
function withTransition(fn) {
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(fn);
  } else {
    fn();
  }
}

async function togglePillar(btn, key) {
  const open = btn.getAttribute("aria-expanded") === "true";
  // Lateral focus model: only one pillar open at a time.
  document.querySelectorAll('.row[aria-expanded="true"]').forEach((r) => {
    if (r !== btn) collapse(r);
  });
  if (open) { withTransition(() => collapse(btn)); return; }

  btn.setAttribute("aria-expanded", "true");
  const detail = document.createElement("div");
  detail.className = "pillar-detail";
  detail.setAttribute("aria-live", "polite");
  detail.innerHTML = `<p class="pd-read"><span class="pd-who">loading ${PILLAR_LABEL[key]}…</span></p>`;
  withTransition(() => btn.after(detail));

  const read = await loadPillarRead(key);
  const p = state.pillars[key] || {};
  const sd = p.score_delta;
  // Day-over-day move, with the period made explicit so the arrow isn't ambiguous.
  const sdTxt = (typeof sd === "number" && sd !== 0)
    ? ` · ${sd > 0 ? "▲ +" : "▼ −"}${Math.abs(sd)} since yesterday`
    : "";
  detail.innerHTML =
    `<p class="pd-read">${read.text}</p>` +
    (read.action ? `<p class="pd-action">→ ${escapeHTML(read.action)}</p>` : "") +
    `<p class="pd-meta">` +
      `<span class="pd-conf">score ${Math.round(p.raw_score ?? 0)}${sdTxt}</span>` +
      `<span class="pd-conf">${p.tier || ""}</span>` +
      `<span class="pd-conf">${read.confidence}</span>` +
    `</p>`;
}

function collapse(btn) {
  btn.setAttribute("aria-expanded", "false");
  const d = btn.nextElementSibling;
  if (d && d.classList.contains("pillar-detail")) d.remove();
}

// Lazy per-pillar read from the coach intelligence; honest correlative framing.
async function loadPillarRead(key) {
  if (state.coachCache[key]) return state.coachCache[key];
  let text = "", action = "", confidence = "";
  try {
    const data = await getJSON(`${API}/coach_analysis?domain=${encodeURIComponent(key)}`);
    const a = data.analysis || data.coach_analysis || data;
    text = a.summary || a.analysis || a.read || "";
    action = a.action || a.recommendation || a.one_thing || "";
    const n = a.observations ?? a.n ?? a.sample_size;
    if (typeof n === "number") {
      confidence = n < 12 ? "preliminary pattern" : n < 30 ? "low confidence (n<30)" : `n=${n}`;
    }
  } catch (e) { /* fall through to the deterministic read */ }

  if (!text) {
    const p = state.pillars[key] || {};
    const dir = trendOf(p.xp_delta);
    const moving = dir === "up" ? "climbing" : dir === "down" ? "slipping" : "holding";
    text = `${PILLAR_LABEL[key]} is at ${Math.round(p.raw_score ?? 0)} and ${moving} (${p.tier || "Foundation"}). ` +
           `Correlative read only — open the Data door for the components behind it.`;
  }
  const out = { text: escapeHTML(text).replace(/^&gt;\s*/, ""), action, confidence: confidence || "correlative" };
  state.coachCache[key] = out;
  return out;
}

/* ── board one-liner (the interpretation layer, made glanceable) ─────────── */
function renderBoardline(priority) {
  const notes = priority && priority.cross_domain_notes;
  const line = notes && (typeof notes === "string" ? notes : Object.values(notes).find(Boolean));
  if (line && !isBad(line)) {
    const who = (priority.coach_name || "The integrator");
    bind("boardline").textContent = `“${String(line).trim()}” — ${who}`;
    bind("boardline").hidden = false;
  }
}

/* ── Predict the week (PG-ENG-1) ─────────────────────────────────────────────
   A reader bets which way a leading SIGNAL moves this week — not the outcome.
   Honest small-n: the reader % only appears past a threshold, rounds to 5% while
   thin, and a wrong call is never red. No streaks, no nags. Hides itself when
   there's no active weekly challenge with predict_metrics. */
const PREDICT_DIRS = [
  { key: "up", glyph: "▲", label: "up" },
  { key: "flat", glyph: "›", label: "hold" },
  { key: "down", glyph: "▼", label: "down" },
];
function _predictKey(week, metric) { return `ajm-predict-${week}-${metric}`; }
function _predictPrior(week, metric) { try { return localStorage.getItem(_predictKey(week, metric)); } catch (e) { return null; } }
function _dirChip(key) { const d = PREDICT_DIRS.find((x) => x.key === key); return d ? `<span class="predict-pick">${d.glyph} ${d.label}</span>` : escapeHTML(String(key)); }
function _pctOf(n, total, round5) { const p = total ? (100 * n) / total : 0; return round5 ? Math.round(p / 5) * 5 : Math.round(p); }

async function renderPredict() {
  const sec = $("[data-predict]");
  if (!sec) return;
  let d;
  try { d = await getJSON(`${API}/predict_week`); } catch (e) { d = null; }
  if (!d || !d.active || !d.metrics || !Object.keys(d.metrics).length) { sec.hidden = true; return; }
  const week = d.week_id;
  const result = d.result || null;
  const body = bind("predict-body");
  body.innerHTML = "";
  for (const [metric, label] of Object.entries(d.metrics)) {
    const tallies = (d.tallies && d.tallies[metric]) || { up: 0, down: 0, flat: 0 };
    const item = document.createElement("div");
    item.className = "predict-item";
    _renderPredictItem(item, week, metric, label, tallies, result, _predictPrior(week, metric));
    body.appendChild(item);
  }
  sec.hidden = false;
}

function _predictTallyLine(tallies) {
  const total = (tallies.up || 0) + (tallies.down || 0) + (tallies.flat || 0);
  if (total < 8) return `<span class="predict-n label">early · ${total} ${total === 1 ? "vote" : "votes"}</span>`;
  const round5 = total < 20;
  return `<span class="predict-tally label">` +
    PREDICT_DIRS.map((dir) => `<span class="pt-seg pt-${dir.key}">${dir.glyph} ${_pctOf(tallies[dir.key] || 0, total, round5)}%</span>`).join(" · ") +
    `</span>`;
}

function _renderPredictItem(item, week, metric, label, tallies, result, prior) {
  // Week closed — the honest reveal (never red for a wrong call).
  if (result && result.metric === metric && result.direction) {
    const actual = PREDICT_DIRS.find((x) => x.key === result.direction);
    const youRight = prior && prior === result.direction;
    item.innerHTML =
      `<p class="predict-q">${escapeHTML(label)}</p>` +
      `<p class="predict-reveal">readers said ${_predictTallyLine(tallies)}` +
      (prior ? ` · you said ${_dirChip(prior)}${youRight ? ' <span class="predict-hit">✓</span>' : ""}` : "") +
      ` · <span class="predict-actual">actual: ${actual ? actual.glyph + " " + actual.label : escapeHTML(String(result.direction))}</span></p>`;
    return;
  }
  // Already predicted this week — your pick + the reader read.
  if (prior) {
    item.innerHTML =
      `<p class="predict-q">${escapeHTML(label)}</p>` +
      `<p class="predict-state">you said ${_dirChip(prior)} · ${_predictTallyLine(tallies)}</p>`;
    return;
  }
  // Not yet — the vote row.
  item.innerHTML =
    `<p class="predict-q">Will <strong>${escapeHTML(label)}</strong> go up, hold, or down this week?</p>` +
    `<div class="predict-vote" role="group" aria-label="Your prediction">` +
    PREDICT_DIRS.map((dir) => `<button class="predict-btn" type="button" data-choice="${dir.key}"><span class="pb-g" aria-hidden="true">${dir.glyph}</span><span>${dir.label}</span></button>`).join("") +
    `</div><p class="predict-tallyrow">${_predictTallyLine(tallies)}</p>`;
  item.querySelectorAll(".predict-btn").forEach((b) => b.addEventListener("click", () => _castPredict(item, week, metric, label, b.dataset.choice)));
}

async function _castPredict(item, week, metric, label, choice) {
  item.querySelectorAll(".predict-btn").forEach((b) => (b.disabled = true));
  try {
    const res = await fetch(`${API}/predict_week`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ week_id: week, metric, choice }),
    });
    if (res.ok) {
      try { localStorage.setItem(_predictKey(week, metric), choice); } catch (e) {}
      const data = await res.json().catch(() => ({}));
      _renderPredictItem(item, week, metric, label, (data && data.tallies) || {}, null, choice);
    } else if (res.status === 429) {
      // Already counted (other tab / cleared storage) — honor it, show the voted state.
      try { localStorage.setItem(_predictKey(week, metric), choice); } catch (e) {}
      _renderPredictItem(item, week, metric, label, {}, null, choice);
    } else {
      item.querySelectorAll(".predict-btn").forEach((b) => (b.disabled = false));
    }
  } catch (e) {
    item.querySelectorAll(".predict-btn").forEach((b) => (b.disabled = false));
  }
}

/* ── Tonight's forecast: circadian-compliance (predictive) ─────────────────── */
async function renderCircadian() {
  const sec = $("[data-circadian]");
  if (!sec) return;
  let d = null;
  try { d = await getJSON(`${API}/circadian`); } catch (e) { d = null; }
  if (!d || !d.available || d.score == null) { sec.hidden = true; return; }
  const score = Math.max(0, Math.min(100, Math.round(d.score)));
  const cat = String(d.category || "").trim();
  bind("circ-score").textContent = score;
  bind("circ-fill").style.width = score + "%";
  bind("circ-cat").textContent = cat ? ` · ${cat}` : "";
  sec.dataset.cat = cat.toLowerCase();
  bind("circ-rx").textContent = d.prescription || "";
  const weak = bind("circ-weak");
  if (d.weakest_component) {
    weak.textContent = `weakest anchor — ${String(d.weakest_component).replace(/_/g, " ")}`;
    weak.hidden = false;
  } else {
    weak.hidden = true;
  }
  sec.hidden = false;
}

/* ── Journey scope: level-up timeline + achievements (gamified layer) ──────── */
const DAILY_SEL = [".dialogue", "[data-readiness]", ".cap-today", ".domains", ".band", "[data-circadian]"];
function showJourney(on) {
  DAILY_SEL.forEach((s) => { const el = $(s); if (el) el.style.display = on ? "none" : ""; });
  if (on) bind("boardline").hidden = true;
  const jr = document.querySelector("[data-journey]"); if (jr) jr.hidden = !on;
}

async function renderJourney() {
  showJourney(true);
  const [tl, ach] = await Promise.all([
    getJSON(`${API}/journey_timeline`).catch(() => null),
    getJSON(`${API}/achievements`).catch(() => null),
  ]);
  const events = (tl && tl.events) || [];
  bind("timeline").innerHTML = events.length
    ? events.map((e) => `<li class="tl-item"><span class="tl-date label">${escapeHTML(String(e.date || "").slice(0, 10))}</span><div class="tl-body"><p class="tl-title">${escapeHTML(e.title || e.type || "")}</p>${e.body ? `<p class="tl-note">${escapeHTML(e.body)}</p>` : ""}</div></li>`).join("")
    : `<li class="tl-empty">No level-ups logged yet — the timeline fills as the score climbs. Day 1 starts the clock.</li>`;
  const list = (ach && ach.achievements) || [];
  const sm = (ach && ach.summary) || {};
  bind("ach-count").textContent = list.length ? `${sm.earned ?? list.filter((a) => a.earned).length}/${sm.total ?? list.length}` : "";
  bind("achievements").innerHTML = list.length
    ? list.map((a) => `<div class="ach ${a.earned ? "is-earned" : ""}" title="${escapeHTML(a.description || "")}"><span class="ach-dot" aria-hidden="true"></span><span class="ach-label">${escapeHTML(a.label || a.id)}</span>${a.earned && a.earned_date ? `<span class="ach-when label">${escapeHTML(String(a.earned_date).slice(0, 10))}</span>` : ""}</div>`).join("")
    : `<p class="tl-empty">Achievements are defined and ready — they unlock as you go.</p>`;
}

/* ── Week scope: six instruments, seven days (S-03) ─────────────────────────
   Real data only: each row is /api/observatory_week?domain=<d> — sparkline of
   the actual daily values, this week's primary number, delta vs the week
   before. A domain that errors or has no points is omitted (shown honestly
   in the verdict count), never faked. */
const WEEK_DOMAINS = ["sleep", "training", "nutrition", "glucose", "physical", "mind"];

function hideDaily() {
  document.querySelector("[data-journey]").hidden = true;
  ["[data-readiness]", ".cap-today", ".domains", ".band", "[data-circadian]"].forEach((s) => { const el = $(s); if (el) el.style.display = "none"; });
  const hr = $(".voice.human"); if (hr) hr.style.display = "none";
  bind("boardline").hidden = true; bind("honest").hidden = true; bind("movement").hidden = true;
}

async function renderWeek() {
  hideDaily();
  const wv = document.querySelector("[data-weekview]"); if (wv) wv.hidden = false;
  const wm = $(".voice.machine .who"); if (wm) wm.textContent = "Week";
  bind("verdict").textContent = "Reading the week…";

  const reads = await Promise.all(WEEK_DOMAINS.map((d) =>
    getJSON(`${API}/observatory_week?domain=${d}`).then((r) => ({ d, r })).catch(() => ({ d, r: null }))));

  const rows = reads
    .filter(({ r }) => r && r.summary && r.summary.primary && (r.summary.primary.sparkline || []).length >= 2)
    .map(({ d, r }) => {
      const p = r.summary.primary;
      const delta = typeof p.delta === "number" && p.delta !== 0
        ? `<span class="wk-delta ${p.trend === "up" ? "is-up" : "is-down"}">${p.trend === "up" ? "▲" : "▼"} ${escapeHTML(String(Math.abs(p.delta)))}</span>`
        : `<span class="wk-delta">—</span>`;
      return `<li class="wk-row"><span class="label">${escapeHTML(d)}</span>${sparkline(p.sparkline)}<span class="wk-val num">${escapeHTML(String(p.value))}<small> ${escapeHTML(p.unit || "")}</small></span>${delta}<span class="wk-note">${escapeHTML(p.delta_label || "")}</span></li>`;
    });

  bind("weekrows").innerHTML = rows.length
    ? rows.join("")
    : `<li class="tl-empty">No week data yet — instruments fill in as the record deepens.</li>`;
  bind("verdict").textContent = rows.length
    ? `Seven days, ${rows.length} of ${WEEK_DOMAINS.length} instruments reporting — deltas read against the week before.`
    : "The week view fills in as the record deepens.";
}

// Month scope (SS-08): "what changed" — real trailing-30d-vs-prior deltas + correlations
// newly FDR-significant in the last 30 days, so a flat day still shows monthly motion.
// honest_null → a calm "steady month" state, never fake motion.
async function renderMonth() {
  hideDaily();
  const mv = document.querySelector("[data-monthview]"); if (mv) mv.hidden = false;
  const wm = $(".voice.machine .who"); if (wm) wm.textContent = "Month";
  bind("verdict").textContent = "Reading the month…";

  const wc = await getJSON(`${API}/what_changed`).catch(() => null);
  const deltas = (wc && wc.deltas) || [];
  const unlocks = (wc && wc.newly_unlocked) || [];

  const drows = deltas.map((d) => {
    const up = d.direction === "improved";
    const arrow = d.delta > 0 ? "▲" : "▼";
    const pct = typeof d.pct === "number" ? ` (${d.pct > 0 ? "+" : ""}${escapeHTML(String(d.pct))}%)` : "";
    return `<li class="mo-row ${up ? "is-up" : "is-down"}"><span class="label">${escapeHTML(d.label)}</span>` +
      `<span class="mo-val num">${escapeHTML(String(d.this_month_avg))}<small> ${escapeHTML(d.unit || "")}</small></span>` +
      `<span class="mo-delta">${arrow} ${escapeHTML(String(Math.abs(d.delta)))}${pct}</span>` +
      `<span class="mo-note">vs ${escapeHTML(String(d.prior_month_avg))} prior 30d</span></li>`;
  });
  bind("month-deltas").innerHTML = drows.join("");

  const urows = unlocks.map((u) => {
    const r = typeof u.r === "number" ? ` <span class="mo-unlock-r">r=${escapeHTML(u.r.toFixed(2))}</span>` : "";
    const txt = u.interpretation || `${u.metric_a || ""} ↔ ${u.metric_b || ""}`;
    return `<div class="mo-unlock"><span class="mo-unlock-k label">newly unlocked</span> ${escapeHTML(txt)}${r}</div>`;
  });
  bind("month-unlocks").innerHTML = urows.join("");

  if (wc && wc.honest_null) {
    bind("verdict").textContent = "A steady month — no metric crossed its monthly threshold and no new correlation reached significance. Calm is data too.";
  } else if (drows.length || urows.length) {
    const bits = [];
    if (drows.length) bits.push(`${drows.length} metric${drows.length === 1 ? "" : "s"} moved`);
    if (urows.length) bits.push(`${urows.length} new correlation${urows.length === 1 ? "" : "s"} unlocked`);
    bind("verdict").textContent = `Past 30 days vs the 30 before — ${bits.join(", ")}.`;
  } else {
    bind("verdict").textContent = "The month view fills in as the record deepens.";
  }
}

/* ── scope + theme controls ──────────────────────────────────────────────── */
function wireScope() {
  document.querySelectorAll(".scope-btn").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.scope === state.scope) return;
      document.querySelectorAll(".scope-btn").forEach((x) => {
        const on = x === b;
        x.classList.toggle("is-active", on);
        x.setAttribute("aria-pressed", String(on));
      });
      state.scope = b.dataset.scope;
      bind("scopeLabel").textContent = b.textContent.toLowerCase();
      const wv = document.querySelector("[data-weekview]"); if (wv) wv.hidden = true;
      const mv = document.querySelector("[data-monthview]"); if (mv) mv.hidden = true;
      if (state.scope === "journey") renderJourney();
      else if (state.scope === "week") renderWeek();
      else if (state.scope === "month") renderMonth();
      else {
        // Today: restore what hideDaily() inline-hid (children of .dialogue —
        // restoring the parent alone leaves them display:none), then reload.
        const hr = $(".voice.human"); if (hr) hr.style.display = "";
        const wm = $(".voice.machine .who"); if (wm) wm.textContent = "The board";
        showJourney(false); load();
      }
    });
  });
}

function wireTheme() {
  const btn = $(".theme-toggle");
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "light" ? "dark" : "light";
    withTransition(() => { document.documentElement.dataset.theme = next; });
    try { localStorage.setItem("ajm-theme", next); } catch (e) {}
  });
}

/* ── First-run orientation (PG-02) ───────────────────────────────────────────
   A dismissible "what am I looking at" card for first-time visitors. Shown once
   (localStorage), non-modal, sits above the panel — never blocks the dense view
   the pilot uses daily. Confidence framing is preserved, not simplified away. */
const INTRO_KEY = "ajm-cockpit-intro-v1";
function wireFirstRun() {
  let seen;
  try { seen = localStorage.getItem(INTRO_KEY); } catch (e) { seen = "1"; } // private mode → don't nag
  if (seen) return;
  const main = $("#cockpit");
  if (!main) return;

  const intro = document.createElement("aside");
  intro.className = "cockpit-intro";
  intro.setAttribute("aria-label", "What you're looking at");
  intro.innerHTML = `
    <button class="cockpit-intro__x" type="button" aria-label="Dismiss orientation">&times;</button>
    <p class="cockpit-intro__k label">new here?</p>
    <h2 class="cockpit-intro__h">This is one life, measured — live.</h2>
    <ul class="cockpit-intro__list">
      <li><strong>The big number</strong> is today's whole-life score: seven pillars rolled into one, recomputed every morning.</li>
      <li><strong>&ldquo;The board&rdquo;</strong> is an AI panel reading the week. Labels like <em>preliminary &middot; n=9</em> mean early signal, not proof.</li>
      <li><strong>Today &middot; Week &middot; Month &middot; Journey</strong> (top right) change the time scope; tap any pillar to open its detail.</li>
    </ul>
    <button class="cockpit-intro__go" type="button">Got it &mdash; show me the cockpit</button>
    <p class="cockpit-intro__note label">Shown once. It won't interrupt again.</p>`;

  const onKey = (e) => { if (e.key === "Escape") dismiss(); };
  function dismiss() {
    try { localStorage.setItem(INTRO_KEY, "1"); } catch (e) {}
    document.removeEventListener("keydown", onKey);
    intro.remove();
  }
  intro.querySelector(".cockpit-intro__x").addEventListener("click", dismiss);
  intro.querySelector(".cockpit-intro__go").addEventListener("click", dismiss);
  document.addEventListener("keydown", onKey);
  main.insertBefore(intro, main.firstChild);
}

/* ── load + orchestrate ──────────────────────────────────────────────────── */
async function load(dateStr) {
  const main = $("#cockpit");
  try {
    // Time travel: a dated request renders that morning's sheet. The board's
    // verdict/boardline stay present-tense only, so they're replaced by an
    // honest note rather than faked for the past.
    if (dateStr) {
      // Phase 4 historical window: the cockpit AS OF that date — the character sheet,
      // the REAL vitals from that morning (no longer hidden — /api/vitals?date= serves
      // them), and a cross-link into the chronicle installment that narrates the week.
      const [charBody, vitBody, posts] = await Promise.all([
        getJSON(`${API}/character?date=${encodeURIComponent(dateStr)}`),
        getJSON(`${API}/vitals?date=${encodeURIComponent(dateStr)}`).catch(() => null),
        getJSON(`/journal/posts.json`).catch(() => null),
      ]);
      const character = charBody?.character;
      state.pillars = {};
      for (const p of charBody?.pillars || []) state.pillars[p.name] = p;
      if (!character || !Object.keys(state.pillars).length) throw new Error("no sheet for that date");
      renderHub(character);
      renderDomains();
      // Real readings from that date (renderReadiness self-hides if the date has none).
      renderReadiness(vitBody?.vitals || null);
      bind("boardline").hidden = true;
      const post = nearestPost(posts, dateStr);
      const xlink = post ? ` <a href="/story/chronicle/#${escapeHTML(post.date)}">Read ${escapeHTML(post.label || ("Week " + post.week))} &rarr;</a>` : "";
      bind("verdict").innerHTML =
        `<span class="mark">&rsaquo;</span> Time travel — the cockpit as of <strong>${escapeHTML(character.as_of_date || dateStr)}</strong>. ` +
        `The board speaks only in the present.${xlink} <a href="/now/">Back to today →</a>`;
      bind("asof").textContent = `as of ${character.as_of_date || dateStr} (history)`;
      main.dataset.state = "ready";
      $(".panel").setAttribute("aria-busy", "false");
      return;
    }

    const [snap, priority] = await Promise.allSettled([
      getJSON(`${API}/snapshot`),
      getJSON(`${API}/weekly_priority`),
    ]);

    const snapV = snap.status === "fulfilled" ? snap.value : null;
    const charBody = snapV?.character || null;   // handle_character body (or {error} on 503)
    const character = charBody?.character || (charBody && !charBody.error ? charBody : null);
    const pillarList = charBody?.pillars || character?.pillars || [];
    state.pillars = {};
    for (const p of pillarList) state.pillars[p.name] = p;

    // No real sheet today (uncomputed / pre-experiment / error) → calm empty state,
    // never misleading zeros.
    if (!character || charBody.error || !pillarList.length) throw new Error("character sheet unavailable");

    renderHub(character);
    renderReadinessScore(snapV?.readiness);  // RQA-04 — stored readiness score + components
    renderReadiness(snapV?.vitals?.vitals);  // last night → today; hides itself if no readings
    renderDomains();
    const pri = priority.status === "fulfilled" ? priority.value : null;
    renderVerdict(pri);
    renderBoardline(pri);
    renderCircadian();  // fire-and-forget; hides itself if no forecast available
    renderPredict();    // fire-and-forget; hides itself if no active weekly prediction

    if (character.as_of_date) bind("asof").textContent = `as of ${character.as_of_date}`;
    main.dataset.state = "ready";
    $(".panel").setAttribute("aria-busy", "false");
  } catch (e) {
    // Calm, honest empty state — no misleading zeros, no raw error tokens, no
    // stuck shimmer. Force display:none (the [hidden] attr is overridden by the
    // author display rules on .domains/.band/.voice). The score recomputes daily.
    main.dataset.state = "ready";
    const gone = (sel) => { const el = typeof sel === "string" ? $(sel) : sel; if (el) el.style.display = "none"; };
    bind("level").textContent = "—";
    bind("tier").textContent = "";
    bind("day").textContent = "";
    gone(bind("movement")); gone(bind("honest")); gone(bind("boardline"));
    gone("[data-readiness]"); gone(".cap-today");
    gone(".domains"); gone(".band"); gone(".voice.human"); gone("[data-circadian]"); gone("[data-predict]");
    bind("verdict").innerHTML = "Today's score hasn't computed yet — the numbers refresh each morning. Check back shortly.";
    $(".panel").setAttribute("aria-busy", "false");
  }
}

function escapeHTML(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Phase 4: the chronicle installment that narrates a given date = the soonest week
// ending on/after it (mirrors the timeline's postFor). Null-safe; decorative.
function nearestPost(pj, date) {
  const arr = (pj && pj.posts) || [];
  let best = null;
  for (const p of arr) { if (!p.date) continue; if (p.date >= date && (!best || p.date < best.date)) best = p; }
  return best || arr[0] || null;
}

function wireScrub() {
  const inp = document.querySelector("[data-scrub]");
  if (!inp) return;
  const today = new Date().toISOString().slice(0, 10);
  inp.max = today;
  inp.min = "2026-04-01";  // cycle 1 genesis — the first morning with a sheet
  const fromUrl = new URLSearchParams(location.search).get("date");
  if (fromUrl) inp.value = fromUrl;
  inp.addEventListener("change", () => {
    const d = inp.value;
    const url = d && d < today ? `/now/?date=${d}` : "/now/";
    try { history.replaceState({}, "", url); } catch (e) {}
    if (d && d < today) load(d);
    else { inp.value = ""; load(); }
  });
}

wireScope();
wireTheme();
wireFirstRun();
wireScrub();
bind("scopeLabel").textContent = "today";
const _deepDate = new URLSearchParams(location.search).get("date");
load(_deepDate && /^\d{4}-\d{2}-\d{2}$/.test(_deepDate) ? _deepDate : undefined);

// Build stamp — muted deploy fingerprint in the footer (apples-to-apples in QA). Reads
// the <meta name="build"> the deploy script injects; no-op locally where it's absent.
(function () {
  try {
    const m = document.querySelector('meta[name="build"]');
    const foot = document.querySelector(".site-foot") || document.querySelector(".cockpit-foot");
    if (!m || !m.content || !foot) return;
    const s = document.createElement("span");
    s.className = "build-stamp label";
    s.textContent = "build " + m.content.split(" ")[0];
    s.title = m.content;
    foot.appendChild(s);
  } catch (e) {}
})();
