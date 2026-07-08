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

import { initTheme } from "/assets/js/theme.js";
import { sigil } from "/assets/js/sigils.js";
import { portrait } from "/assets/js/portraits.js"; // §8.7 — portrait(c) || sigil(c)
import { sparkline } from "/assets/js/charts.js";
import { domainIcon } from "/assets/js/icons.js";
import { explainMount } from "/assets/js/explain.js"; // #403 one-tap explainer
import { momentsIndex, shareMount } from "/assets/js/share.js"; // #404 moment permalinks

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

/* ── #591 presence helpers — honest marks + timestamps, no fake liveness ──── */

// A speaker's mark: a signed portrait when one exists, else the deterministic
// sigil (never null). Accepts {coach_id|persona_id|name}.
function coachMark(c, size = 22) {
  return portrait(c, { title: "", cls: "ck-mark", size }) || sigil(c, { title: "", cls: "ck-mark" });
}

const PT = "America/Los_Angeles";
const _dayPT = (d) => d.toLocaleDateString("en-CA", { timeZone: PT }); // YYYY-MM-DD

// The real authoring time, in Pacific (the site's tz). "this morning/afternoon/
// evening" ONLY when written today (PT); otherwise the date. Never a live cue.
function writtenStamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString("en-US", { timeZone: PT, hour: "numeric", minute: "2-digit" });
  if (_dayPT(d) === _dayPT(new Date())) {
    const h = +d.toLocaleString("en-US", { timeZone: PT, hour: "numeric", hour12: false });
    const part = h < 12 ? "this morning" : h < 18 ? "this afternoon" : "this evening";
    return `written ${time} ${part}`;
  }
  return `written ${d.toLocaleDateString("en-US", { timeZone: PT, month: "short", day: "numeric" })}`;
}

// #802 (R22-CONTENT-03): honest "as of / refresh paused" disclosure for a
// pillar's coach read. budget_guard (ADR-063/125) can pause a coach's
// narrative regeneration at tier >= 2 — when it does, a served read can be a
// HELD read from before the pause, not today's, and the cockpit must say so.
function pillarAsOf(iso, paused) {
  const d = iso ? new Date(iso) : null;
  const valid = d && !isNaN(d.getTime());
  const date = valid ? d.toLocaleDateString("en-US", { timeZone: PT, month: "short", day: "numeric" }) : "";
  if (paused) return date ? `as of ${date} — refresh paused (budget guard)` : "refresh paused (budget guard)";
  if (valid && (Date.now() - d.getTime()) / 36e5 > 48) return `as of ${date} — next refresh pending`;
  return "";
}

// Honest "held since {date}" — stance data is weekly (ADR-104/105), so this is a
// real date + a coarse "~N weeks", NEVER a fabricated day count.
function heldSince(iso) {
  if (!iso) return "";
  const d = new Date(String(iso).length <= 10 ? `${iso}T12:00:00-07:00` : iso);
  if (isNaN(d.getTime())) return "";
  const date = d.toLocaleDateString("en-US", { timeZone: PT, month: "short", day: "numeric" });
  const weeks = Math.floor((Date.now() - d.getTime()) / (7 * 864e5));
  return weeks >= 1 ? `held since ${date} · ~${weeks} wk${weeks > 1 ? "s" : ""}` : `held since ${date}`;
}

function renderVerdict(priority) {
  // uplevel P3 — the verdict was an 11-line static wall of mono text. Same words,
  // staged: attributed to the coach who wrote it (name + title from the payload,
  // never invented) and split on sentence boundaries into ≤3 beats that reveal in
  // sequence (CSS gated on html.mo — reduced-motion reads it all at once).
  const v = bind("verdict");
  const text = priority && priority.weekly_priority;
  if (isBad(text)) {
    v.innerHTML = `<span class="mark">&rsaquo;</span> The board's weekly read isn't in yet — it posts after the next briefing.`;
    return;
  }
  const sentences = String(text).match(/[^.!?]+[.!?]+(?:\s|$)/g) || [String(text)];
  const beats = [];
  const per = Math.ceil(sentences.length / Math.min(3, sentences.length));
  for (let i = 0; i < sentences.length; i += per) beats.push(sentences.slice(i, i + per).join("").trim());
  // #591: the read is attributed AND time-stamped — a signed mark for the author
  // and the honest hour it was written. Presence without fake liveness.
  const stamp = writtenStamp(priority.generated_at);
  const who = priority.coach_name
    ? `<p class="vd-who label">` +
      `<span class="vd-mark" aria-hidden="true">${coachMark({ name: priority.coach_name, coach_id: priority.coach_id }, 22)}</span>` +
      `${escapeHTML(priority.coach_name)}${priority.coach_title ? ` · ${escapeHTML(priority.coach_title)}` : ""}` +
      `${stamp ? ` · <span class="vd-stamp">${escapeHTML(stamp)}</span>` : ""}</p>`
    : "";
  v.innerHTML = who + beats.map((b, i) =>
    `<span class="vd-beat" style="--vd-delay:${(i * 0.45).toFixed(2)}s">${i === 0 ? `<span class="mark">&rsaquo;</span> ` : ""}${escapeHTML(b)}</span>`
  ).join(" ");
}

/* ── #591: the board, made present — the argument underneath the verdict + where
   each coach stands. Both fed by /api/coach_team; both self-hide until real data
   exists. The threaded renderer handles 1..n turns, so it's ready for #540 to grow
   the exchange without a rewrite. ─────────────────────────────────────────────── */
const _TURN_ROLE = { position: "opens", reply: "replies", rejoinder: "counters" };

function renderThread(team) {
  const wrap = bind("thread");
  if (!wrap) return;
  const d = team && team.dispute;
  const turns = d && Array.isArray(d.turns) ? d.turns.filter((t) => t && t.line) : [];
  if (!turns.length) { wrap.hidden = true; wrap.innerHTML = ""; return; }
  const when = d.created_at ? ` · <span class="thread-when">${escapeHTML(writtenStamp(d.created_at))}</span>` : "";
  const head =
    `<p class="thread-cap label"><span class="mark">&rsaquo;</span> the argument underneath` +
    `${d.topic ? ` — ${escapeHTML(d.topic)}` : ""}${when}</p>`;
  const body = turns
    .map((t, i) => {
      const role = _TURN_ROLE[t.kind] || "";
      return (
        `<div class="turn turn-${escapeHTML(t.kind || "position")}" style="--vd-delay:${(i * 0.4).toFixed(2)}s">` +
        `<span class="turn-mark" aria-hidden="true">${coachMark({ coach_id: t.speaker, name: t.name }, 20)}</span>` +
        `<div class="turn-body"><p class="turn-who label">${escapeHTML(t.name || "")}` +
        `${role ? ` <span class="turn-role">${role}</span>` : ""}</p>` +
        `<p class="turn-line">${escapeHTML(t.line)}</p></div></div>`
      );
    })
    .join("");
  wrap.innerHTML = head + body;
  wrap.hidden = false;
}

function renderStances(team) {
  const wrap = bind("stances");
  if (!wrap) return;
  const huddle = team && Array.isArray(team.huddle) ? team.huddle : [];
  const chips = huddle
    .filter((h) => h && h.headline)
    .map((h) => {
      const held = heldSince(h.held_since);
      return (
        `<li class="stance-chip">` +
        `<span class="sc-mark" aria-hidden="true">${coachMark({ coach_id: h.persona_id, name: h.name }, 16)}</span>` +
        `<span class="sc-name label">${escapeHTML(h.name || "")}</span>` +
        `<span class="sc-stage">${escapeHTML(h.headline)}</span>` +
        `${held ? `<span class="sc-held label">${escapeHTML(held)}</span>` : ""}</li>`
      );
    })
    .join("");
  if (!chips) { wrap.hidden = true; wrap.innerHTML = ""; return; }
  wrap.innerHTML = `<p class="stance-cap label">where the team stands</p><ul class="stance-list">${chips}</ul>`;
  wrap.hidden = false;
}

async function renderBoard() {
  try {
    const team = await getJSON(`${API}/coach_team`);
    renderThread(team);
    renderStances(team);
  } catch (e) {
    /* both self-hide — the cockpit never blanks on a missing board */
  }
}

/* ── render: the two domains + consistency band ──────────────────────────── */
function rollup(keys) {
  // #747: a not-yet-instrumented pillar's placeholder neutral score must not
  // quietly drag the domain composite toward 50 — exclude it from the average,
  // the same way an absent reading is already excluded (typeof n === "number").
  const vals = keys
    .filter((k) => !state.pillars[k]?.not_instrumented)
    .map((k) => state.pillars[k]?.raw_score)
    .filter((n) => typeof n === "number");
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}

function pillarRow(key) {
  const p = state.pillars[key];
  // #747: a pillar with no data source feeding it renders a labeled state
  // instead of the engine's placeholder neutral score — data-driven off the
  // engine's own flag (state.pillars[key].not_instrumented), not hardcoded
  // per pillar name, so this clears itself the day real data starts flowing.
  const notInstrumented = !!p?.not_instrumented;
  const score = Math.round(p?.raw_score ?? 0);
  // score_delta is the day-over-day move (vs yesterday's sheet); prefer it for the
  // glance arrow so the trend means the same thing the detail spells out.
  const dir = notInstrumented ? "flat" : trendOf(p?.score_delta ?? p?.xp_delta);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `row ${dir === "up" ? "up" : dir === "down" ? "dn" : ""}${notInstrumented ? " not-instrumented" : ""}`;
  btn.dataset.pillar = key;
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML = notInstrumented
    ? `<span class="lab">${domainIcon(key, { cls: "dom-ico" })}${PILLAR_LABEL[key] || key}</span>` +
      `<span class="track track-none" aria-hidden="true"></span>` +
      `<span class="val label" title="not yet instrumented">n/a</span>` +
      `<span class="tr"></span>` +
      `<span class="chev" aria-hidden="true">›</span>`
    : `<span class="lab">${domainIcon(key, { cls: "dom-ico" })}${PILLAR_LABEL[key] || key}</span>` +
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
  // #492/M-4: these are now the score's ACTUAL inputs (recovery / sleep / HRV
  // trend / training balance, stored by daily-metrics-compute), not the
  // day-grade set. A 0 here is a real reading (e.g. deep fatigue), so zero
  // rows stay de-emphasized but the caption no longer blames a "quiet day".
  const comps = readiness.components || [];
  comp.innerHTML = comps.map((c) => {
    const pct = Math.max(0, Math.min(100, Number(c.score) || 0));
    return `<li class="rd-comp-row${pct === 0 ? " rd-comp-zero" : ""}"><span class="label">${escapeHTML(c.label)}</span>` +
      `<span class="rd-comp-track"><span class="rd-comp-fill" style="width:${pct}%"></span></span>` +
      `<span class="rd-comp-v num">${Math.round(pct)}</span></li>`;
  }).join("") + (comps.some((c) => !Number(c.score))
    ? `<li class="rd-comp-note label">a 0 is a real reading — counted, not hidden.</li>`
    : "");
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

  const pNow = state.pillars[key] || {};
  // #747: nothing to fetch from the coach for a pillar with no data — the
  // engine's own note is the honest read, so skip the lazy /api/coach_analysis
  // call entirely rather than asking a coach to comment on a placeholder score.
  if (pNow.not_instrumented) {
    detail.innerHTML =
      `<p class="pd-read">${escapeHTML(pNow.not_instrumented_note || "Not yet instrumented — no data source feeds this pillar yet.")}</p>` +
      `<p class="pd-meta"><span class="pd-conf">not yet instrumented</span></p>`;
    withTransition(() => btn.after(detail));
    return;
  }

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
      (read.asOf ? `<span class="pd-conf">${escapeHTML(read.asOf)}</span>` : "") +
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
  let text = "", action = "", confidence = "", asOf = "";
  try {
    const data = await getJSON(`${API}/coach_analysis?domain=${encodeURIComponent(key)}`);
    const a = data.analysis || data.coach_analysis || data;
    text = a.summary || a.analysis || a.read || "";
    action = a.action || a.recommendation || a.one_thing || "";
    const n = a.observations ?? a.n ?? a.sample_size;
    if (typeof n === "number") {
      confidence = n < 12 ? "preliminary pattern" : n < 30 ? "low confidence (n<30)" : `n=${n}`;
    }
    // #802: disclose only when it's noteworthy — the budget guard paused this
    // coach's regeneration, or the served read is >48h old (see pillarAsOf()).
    asOf = pillarAsOf(data.generated_at, !!data.regeneration_paused);
  } catch (e) { /* fall through to the deterministic read */ }

  if (!text) {
    const p = state.pillars[key] || {};
    const dir = trendOf(p.xp_delta);
    const moving = dir === "up" ? "climbing" : dir === "down" ? "slipping" : "holding";
    text = `${PILLAR_LABEL[key]} is at ${Math.round(p.raw_score ?? 0)} and ${moving} (${p.tier || "Foundation"}). ` +
           `Correlative read only — open the Data door for the components behind it.`;
    asOf = "";  // the deterministic fallback has no coach generation to date-stamp
  }
  const out = { text: escapeHTML(text).replace(/^&gt;\s*/, ""), action, confidence: confidence || "correlative", asOf };
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

// The model expects (#541): tomorrow's deterministic expectations with 80% ranges,
// plus yesterday's grade (expected vs actual) and the running coverage stat once
// forecasts have actually been graded. Correlative framing only — "the model
// expects", never a promise. Self-hides until the engine has a summary.
async function renderForecast() {
  const sec = $("[data-forecast]");
  if (!sec) return;
  let d = null;
  try { d = await getJSON(`${API}/forecast`); } catch (e) { d = null; }
  const fx = d && d.available && Array.isArray(d.forecasts) ? d.forecasts : [];
  const NAMES = { recovery_pct: "recovery", sleep_hours: "sleep", weight_lbs: "weight" };
  const h1 = fx.filter((f) => f.horizon_days === 1 && f.point != null && f.lo != null && f.hi != null);
  if (!h1.length) { sec.hidden = true; return; }
  const rows = h1.map((f) => {
    const unit = f.unit === "%" ? "%" : ` ${f.unit}`;
    return `<li class="fx-row"><span class="label">${escapeHTML(NAMES[f.metric] || String(f.metric))}</span>` +
      `<span class="fx-point num">${escapeHTML(String(f.point))}<small>${escapeHTML(unit)}</small></span>` +
      `<span class="fx-range label">${escapeHTML(String(f.frame || "tomorrow"))} · 80% range ${escapeHTML(String(f.lo))}–${escapeHTML(String(f.hi))}</span></li>`;
  });
  bind("fx-rows").innerHTML = rows.join("");
  const cov = d.coverage;
  bind("fx-cov").textContent = cov && cov.n_resolved
    ? ` · range held ${Math.round(cov.coverage_pct)}% of ${cov.n_resolved} graded`
    : " · ungraded until tomorrow";
  const res = (d.resolutions_today || []).filter((r) => r.horizon_days === 1 && r.actual != null && r.point != null);
  const rline = bind("fx-resolved");
  if (res.length) {
    rline.textContent = "graded today — " + res.map((r) =>
      `${NAMES[r.metric] || r.metric}: ${r.actual} actual vs ${r.point} expected${r.covered ? "" : " (outside range)"}`).join(" · ");
    rline.hidden = false;
  } else {
    rline.hidden = true;
  }
  sec.hidden = false;
}

// The weekday name for an ISO date ("2026-06-26" → "Friday"), for "since Friday".
function _weekdaySince(iso) {
  if (!iso) return "";
  try {
    const dt = new Date(iso + "T12:00:00");
    return ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][dt.getDay()] || "";
  } catch (e) { return ""; }
}

// Presence / quiet-stretch (2026-06-30): an honest line when the OWNER's own
// logging has gone quiet — or when he's just returned after a lull. No streaks,
// no shame, no red; the platform simply notices, the way a coach would. Reads the
// fail-closed /api/presence (no private per-channel detail). Self-hides when present.
async function renderPresence() {
  const sec = $("[data-presence]");
  if (!sec) return;
  let d = null;
  try { d = await getJSON(`${API}/presence`); } catch (e) { d = null; }
  if (!d || (!d.in_lull && !d.returned)) { sec.hidden = true; return; }
  let line = "", sub = "";
  if (d.returned) {
    const n = d.resumed_after_days;
    line = n ? `Back after ${n} ${n === 1 ? "day" : "days"} away.` : "Back at it.";
    const wd = d.weight_delta_over_gap_lbs;
    if (wd != null && wd > 0) sub = `The scale came back up about ${Math.abs(wd)} lb over the gap — data, not a verdict.`;
    else if (d.passive_still_flowing) sub = "The wearables kept the thread while the logs were dark.";
  } else {
    const n = d.gap_days;
    const since = _weekdaySince(d.last_log_date);
    if (d.planned_pause) {
      line = `Quiet on the logs${since ? ` since ${since}` : ""} — looks like a planned break.`;
    } else {
      line = `Off the grid${since ? ` since ${since}` : ""} — ${n != null ? n : "several"} ${n === 1 ? "day" : "days"} without a log.`;
      if (d.passive_still_flowing) sub = "The wearables are still reporting — the story picks back up when the logging does.";
    }
  }
  bind("presence-line").textContent = line;
  const subEl = bind("presence-sub");
  if (sub) { subEl.textContent = sub; subEl.hidden = false; } else { subEl.hidden = true; }
  sec.dataset.cls = d.returned ? "returned" : (d.presence_class || "");
  sec.hidden = false;
}

// Since your last visit — the returning-visitor strip. Keyed to the visitor's own
// gap via localStorage (the legacy key, so v3-era returners keep their continuity;
// no accounts, privacy-clean). Self-hides on: first visit, gaps under 12h (same-day
// reloads aren't a "return"), corrupted/ancient timestamps, fetch failure, empty
// deltas. The stamp only advances after a successful read, so a failed fetch
// doesn't eat the gap. /api/changes-since wants EPOCH SECONDS.
const _LV_KEY = "amj_last_visit";
function _lvSpark(values) {
  const v = (values || []).map(Number).filter(Number.isFinite);
  if (v.length < 2) return "";
  const min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * 72},${16 - ((x - min) / span) * 12 + 2}`).join(" ");
  return `<svg class="lv-spark" viewBox="0 0 72 20" width="72" height="20" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
async function renderSinceLastVisit() {
  const sec = $("[data-lastvisit]");
  if (!sec) return;
  const now = Date.now();
  const raw = localStorage.getItem(_LV_KEY);
  const ts = raw ? parseInt(raw, 10) : NaN;
  if (!Number.isFinite(ts) || ts <= 0 || ts > now || now - ts > 365 * 86400000) {
    localStorage.setItem(_LV_KEY, String(now));  // first visit / corrupted / ancient → stamp + stay silent
    return;
  }
  const gapH = (now - ts) / 3600000;
  if (gapH < 12) { localStorage.setItem(_LV_KEY, String(now)); return; }
  let d = null;
  try { d = await getJSON(`${API}/changes-since?ts=${Math.floor(ts / 1000)}`); } catch (e) { return; }
  const deltas = (d && d.deltas) || {};
  const METRICS = [
    { key: "weight", label: "weight", unit: " lb" },
    { key: "hrv", label: "HRV", unit: " ms" },
    { key: "sleep", label: "sleep", unit: " h" },
    { key: "character", label: "character", unit: " pts" },
  ];
  const rows = METRICS.filter((m) => deltas[m.key] && deltas[m.key].from != null && deltas[m.key].to != null).map((m) => {
    const x = deltas[m.key];
    const chg = Number(x.change);
    const chgTxt = Number.isFinite(chg) ? `${chg > 0 ? "+" : ""}${Math.round(chg * 10) / 10}${m.unit}` : "";
    return `<li class="lv-row"><span class="label">${escapeHTML(m.label)}</span>` +
      `<span class="lv-delta num">${escapeHTML(String(x.from))} → ${escapeHTML(String(x.to))}</span>` +
      `<span class="lv-chg num">${escapeHTML(chgTxt)}${x.trend ? ` <span class="label">${escapeHTML(String(x.trend))}</span>` : ""}</span>` +
      `${_lvSpark(x.sparkline)}</li>`;
  });
  if (!rows.length) { localStorage.setItem(_LV_KEY, String(now)); return; }  // nothing moved → silent
  const days = Math.max(1, Math.round(gapH / 24));
  bind("lv-gap").textContent = ` · ${days === 1 ? "a day" : days + " days"} away`;
  bind("lv-rows").innerHTML = rows.join("");
  sec.hidden = false;
  localStorage.setItem(_LV_KEY, String(now));
}

// Reading line (Mind pillar, ADR-097): current book + read-today tick + streak.
// Recall prompts/retention are owner-private — never fetched on the public cockpit.
async function renderReading() {
  const sec = $("[data-reading]");
  if (!sec) return;
  let d = null;
  try { d = await getJSON(`${API}/reading_overview`); } catch (e) { d = null; }
  const line = d && d.cockpit_line;
  const current = line && line.current;
  const streak = line && line.input_streak_days != null ? line.input_streak_days : 0;
  if (!current && !streak) { sec.hidden = true; return; }  // nothing to show yet
  const tick = bind("reading-tick");
  if (tick) tick.textContent = line && line.read_today ? " · read today ✓" : "";
  const now = bind("reading-now");
  if (now) {
    const b = (current && current.book) || {};
    const title = isBad(b.title) ? "" : b.title;
    const author = isBad(b.author) ? "" : b.author;
    now.innerHTML = title
      ? `<span class="rl-title">${escapeHTML(title)}</span>${author ? `<span class="rl-author"> · ${escapeHTML(author)}</span>` : ""}`
      : `<span class="rl-title">the shelf →</span>`;
  }
  const st = bind("reading-streak");
  if (st) st.textContent = streak ? `${streak} day${streak === 1 ? "" : "s"} in a row` : "";
  sec.hidden = false;
}

/* ── Journey scope: level-up timeline + achievements (gamified layer) ──────── */
const DAILY_SEL = [".dialogue", ".board-thread", ".stance-strip", "[data-readiness]", ".cap-today", ".domains", ".band", "[data-circadian]"];
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

  // #404: the week's recap permalink (minted daily by the moments sweep).
  const wk = ((await momentsIndex()) || {}).week;
  bind("weekrows").innerHTML = (rows.length
    ? rows.join("")
    : `<li class="tl-empty">No week data yet — instruments fill in as the record deepens.</li>`)
    + `<li class="wk-explain">${explainMount("observatory_week")}${wk && wk.current ? shareMount(wk.current, "The week so far — one measured life") : ""}</li>`;
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
  bind("month-unlocks").innerHTML = urows.join("") + explainMount("what_changed");

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

/* ── #807: first-visit context for the bare level number ─────────────────────
   The hub opens with "character level · today" and a bare number — a first-time
   visitor doesn't know if 12 is good. One muted inline sentence (markup lives in
   the HTML, hidden by default) shown until dismissed (localStorage); a returning
   visitor never sees it. Private mode → never shown, mirroring wireFirstRun(). */
const HINT_KEY = "ajm-level-hint-v1";
function wireLevelHint() {
  const hint = document.querySelector("[data-hub-hint]");
  if (!hint) return;
  let seen;
  try { seen = localStorage.getItem(HINT_KEY); } catch (e) { seen = "1"; } // private mode → don't nag
  if (seen) return;
  hint.hidden = false;
  const x = hint.querySelector(".hub-hint-x");
  if (x) {
    x.addEventListener("click", () => {
      try { localStorage.setItem(HINT_KEY, "1"); } catch (e) {}
      hint.hidden = true;
    });
  }
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
    renderBoard();      // #591 fire-and-forget; the inter-coach thread + team stances, self-hiding
    renderPresence();   // fire-and-forget; hides itself unless he's gone quiet / just returned
    renderSinceLastVisit(); // fire-and-forget; only speaks to a genuine returning visitor
    renderCircadian();  // fire-and-forget; hides itself if no forecast available
    renderForecast();   // fire-and-forget (#541); hides itself until the engine has a summary
    renderReading();    // fire-and-forget; hides itself if no book in hand
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
  const go = (d) => {
    const url = d && d < today ? `/now/?date=${d}` : "/now/";
    try { history.replaceState({}, "", url); } catch (e) {}
    if (d && d < today) load(d);
    else { inp.value = ""; load(); }
  };
  inp.addEventListener("change", () => go(inp.value));

  // uplevel P4: the raw date input was the least-elite element on the flagship
  // instrument. A day-slider over the experiment's real span (min = cycle-1
  // genesis) makes time-travel a drag, not a form fill. Debounced so scrubbing
  // doesn't hammer the API; the date input stays as the precise/accessible path.
  const slider = document.querySelector("[data-scrub-days]");
  const lab = document.querySelector("[data-scrub-label]");
  if (!slider || !lab) return;
  const t0 = Date.parse("2026-04-01T12:00:00");
  const days = Math.max(1, Math.round((Date.parse(`${today}T12:00:00`) - t0) / 86400000));
  slider.max = String(days);
  const dOf = (i) => new Date(t0 + i * 86400000).toISOString().slice(0, 10);
  const sync = () => {
    const cur = fromUrl && /^\d{4}-\d{2}-\d{2}$/.test(fromUrl) ? fromUrl : today;
    const idx = Math.max(0, Math.min(days, Math.round((Date.parse(`${cur}T12:00:00`) - t0) / 86400000)));
    slider.value = String(idx);
    lab.textContent = cur === today ? "today" : cur;
  };
  sync();
  slider.hidden = false; lab.hidden = false;
  let deb = null;
  slider.addEventListener("input", () => {
    const d = dOf(Number(slider.value));
    lab.textContent = d === today ? "today" : d;
    clearTimeout(deb);
    deb = setTimeout(() => { inp.value = d === today ? "" : d; go(d === today ? "" : d); }, 350);
  });
}

wireScope();
initTheme();
wireFirstRun();
wireLevelHint();
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

/* ── #406: the sync strip — "measured, live" made checkable ─────────────────
   REAL ingestion write times from /api/last_sync (ingested_at stamps, never
   the day-granular DATE key). The "ago" text ticks client-side every 30s;
   the data re-fetches every 5 minutes. The pulse dot glows ONLY when a pipe
   wrote within ITS OWN registry-derived freshness window (#589 — data-fresh-ts
   + data-fresh-window hand off to motion.js's shared wireFreshness() primitive,
   replacing the old flat 45-minute guess; nothing is animated to imply data
   that isn't there); stale states render truthfully ("9h ago"). */
let _sync = null;
let _syncSkewMs = 0;

function _agoText(iso) {
  const ms = Date.now() + _syncSkewMs - Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function renderSyncLine() {
  const el = bind("syncline");
  if (!el) return;
  const srcs = ((_sync && _sync.sources) || []).filter((s) => s.last_write);
  if (!srcs.length) { el.hidden = true; return; }
  const freshestId = _sync.freshest && _sync.freshest.id;
  el.innerHTML = srcs.map((s) => {
    const windowS = Number.isFinite(Number(s.stale_hours)) ? Math.round(Number(s.stale_hours) * 3600) : "";
    const star = s.id === freshestId ? ` <span class="sync-freshest">← freshest</span>` : "";
    return `<span class="sync-src"><span class="sync-dot fr-dot" data-fresh-ts="${escapeHTML(s.last_write)}" data-fresh-window="${windowS}" aria-hidden="true"></span>` +
      `${escapeHTML(s.label)} <span class="sync-ago num">${escapeHTML(_agoText(s.last_write))}</span>${star}</span>`;
  }).join(`<span class="sync-sep" aria-hidden="true">·</span>`);
  el.hidden = false;
}

async function loadSync() {
  try {
    const d = await getJSON(`${API}/last_sync`);
    _sync = d;
    _syncSkewMs = d && d.server_now ? Date.parse(d.server_now) - Date.now() : 0;
  } catch (e) { _sync = null; }
  renderSyncLine();
}
loadSync();
setInterval(renderSyncLine, 30_000); // the "ago" ticks
setInterval(loadSync, 300_000);      // the data re-checks
