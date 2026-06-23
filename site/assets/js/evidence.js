/*
  evidence.js — Door 3 as a master-detail app (/evidence/)
  ----------------------------------------------------------------------------
  Horizontal GROUP tabs (top) · topic TILES (left) · readout loads in the CENTER
  dynamically — no page jumps. Repeat-user browse per the Brief (§5: archival
  index, structured, browsable) + the disclosure model (detail in place, lateral
  movement). Deep links (/evidence/<slug>/) and the old-URL redirects still work
  via the History API. Renderers are bespoke + data-bound to the real shapes;
  empty domains render an honest "ready, no data yet" state.

  Registry + start slug are embedded by scripts/v4_build_evidence.py:
    window.__EVIDENCE_REGISTRY__ = [{slug,title,blurb,group,mode,endpoint,root,legacy,editorial}]
    window.__START_SLUG__ = "<slug>"
*/

import { lineChart, barChart, dualWeight, stackedBar, correlationChip, intakeSpine, sufficiencyBars, stackedColumns, mealWindowRibbon, dualLineChart, sparkline, targetSpine, heatStrip, stackedDayColumns, landmarkBars } from "/assets/js/charts.js";

const REG = window.__EVIDENCE_REGISTRY__ || [];
const BYSLUG = Object.fromEntries(REG.map((t) => [t.slug, t]));
const GROUPS = [...new Set(REG.map((t) => t.group))];

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }
const isBad = (v) => { if (v == null) return true; const s = String(v).trim(); return s === "" || /^\[.*\]$/.test(s) || s.toUpperCase() === "N/A"; };
const has = (v) => v != null && v !== "" && !(Array.isArray(v) && !v.length);
function fmt(v, d) { if (v == null || v === "") return "—"; const n = Number(v); return Number.isFinite(n) && typeof v !== "boolean" ? (d != null ? n.toFixed(d) : (Number.isInteger(n) ? String(n) : n.toFixed(1))) : esc(v); }
const ttl = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
// Sleep/recovery are wake-date-keyed: a record dated D describes the night of D-1.
// Returns a short "Jun 16" label for the night a wake-date reading came from.
const _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtShort = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_MON[+m[2] - 1]} ${+m[3]}` : ""; };
// Sleep/recovery are wake-date-keyed: a record dated D describes the night of D-1.
// Returns a short "Jun 16" label for the night a wake-date reading came from.
function nightOf(wakeIso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(wakeIso || ""));
  if (!m) return "";
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  d.setUTCDate(d.getUTCDate() - 1);
  return `${_MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
}
// The night a sleep readout came from: the unified record already exposes night_of
// (the evening date); otherwise derive it from the sleep-detail wake date.
const lastNightDate = (s, uni) => (uni && uni.night_of) ? fmtShort(uni.night_of) : nightOf(s && s.as_of_date);
const fig = (v, k, extra) => `<div class="fig"><span class="fig-v num">${esc(v)}</span><span class="fig-k label">${esc(k)}</span>${extra ? `<span class="rd-delta">${esc(extra)}</span>` : ""}</div>`;
const figs = (a) => `<div class="figs">${a.filter(Boolean).join("")}</div>`;
const sec = (t, inner) => inner ? `<section class="rd-sec"><h2 class="rd-h">${esc(t)}</h2>${inner}</section>` : "";
const empty = (m) => `<p class="rd-archive">${esc(m)}</p>`;
const note = (t) => `<p class="correlative">${t} <span class="confidence conf-low">N=1</span></p>`;
function evClass(ev) { const s = String(ev || "").toLowerCase(); if (/strong|high|robust/.test(s)) return ["backed-strong", "well supported"]; if (/mod|some|emerg|mixed/.test(s)) return ["backed-some", "moderate support"]; return ["backed-thin", "preliminary"]; }
// Render one value for a kv row. Handles nested objects (compact "k v · k v" of their
// scalar children) + arrays (count) — previously these fell through to "—", which turned
// nutrition periodization / eating-window and the genome category tables into walls of dashes.
function kvval(v, f, k) {
  if (v == null) return "—";
  if (f && f[k]) return f[k](v);
  if (Array.isArray(v)) return v.length ? `${v.length} item${v.length > 1 ? "s" : ""}` : "—";
  if (typeof v === "object") {
    if (v.summary || v.label || v.value) return v.summary || v.label || v.value;
    const inner = Object.entries(v).filter(([ik, iv]) => !ik.startsWith("_") && iv != null && typeof iv !== "object").map(([ik, iv]) => `${ttl(ik)} ${fmt(iv)}`);
    return inner.length ? inner.join(" · ") : "—";
  }
  return fmt(v);
}
function kvtable(o, f) {
  // Drop rows whose value renders empty ("—") so nested-null objects don't leave dash rows.
  const r = Object.entries(o || {}).filter(([k, v]) => !k.startsWith("_") && v != null).map(([k, v]) => [k, kvval(v, f, k)]).filter(([, val]) => val !== "—").map(([k, val]) => `<tr><td class="rd-name">${esc(ttl(k))}</td><td class="num">${esc(val)}</td></tr>`).join("");
  return r ? `<table class="rd-tbl"><tbody>${r}</tbody></table>` : "";
}

/* ── Renderers (bound to real shapes) ─────────────────────────────────────── */
function renderSupplements(d) { const g = d.groups || {}; const head = figs([fig(d.total_count ?? Object.values(g).reduce((a, x) => a + (x.items || []).length, 0), "compounds"), d.as_of_date && fig(d.as_of_date, "as of")]); const secs = Object.values(g).map((grp) => { const cards = (grp.items || []).map((s) => { const [c, l] = evClass(s.ev); const pct = Math.max(4, Math.min(100, s.evPct ?? 0)); return `<article class="supp"><header class="supp-top"><h3 class="supp-name">${esc(s.name)}</h3>${s.dose ? `<span class="supp-dose num">${esc(s.dose)}</span>` : ""}${s.timing ? `<span class="supp-timing label">${esc(s.timing)}</span>` : ""}</header>${s.why ? `<p class="supp-why">${esc(s.why)}</p>` : ""}<div class="supp-ev"><span class="supp-evlabel ${c}">${l}</span><span class="supp-meter"><i class="${c}" style="width:${pct}%"></i></span><span class="supp-evpct num">${s.evPct != null ? s.evPct + "%" : ""}</span></div><p class="supp-meta label">${[s.board && "src: " + esc(s.board), s.cost_monthly != null && "$" + esc(s.cost_monthly) + "/mo", (s.evidence_url || ((s.sources || []).find((x) => x && x.url) || {}).url) && `<a class="supp-ev-link" href="${esc(s.evidence_url || (s.sources.find((x) => x && x.url) || {}).url)}" target="_blank" rel="noopener">evidence ↗</a>`].filter(Boolean).join("  ·  ")}</p></article>`; }).join(""); return `<section class="rd-sec"><div class="rd-grouphead"><h2 class="rd-h">${esc(grp.name)}</h2>${grp.desc ? `<p class="rd-desc">${esc(grp.desc)}</p>` : ""}</div><div class="supp-grid">${cards}</div></section>`; }).join(""); return head + secs + note("Evidence strength is the published research consensus — not a claim about Matthew."); }
function renderLabs(d) { const L = d.labs || d; const bm = L.biomarkers || []; if (!bm.length) return empty("No bloodwork drawn yet — panels appear here as they're added."); const by = {}; for (const b of bm) (by[b.category || "Other"] ||= []).push(b); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><thead><tr><th>biomarker</th><th>value</th><th>reference</th><th>flag</th></tr></thead><tbody>${rows.map((b) => { const f = b.flag && String(b.flag).toLowerCase() !== "null"; return `<tr class="${f ? "rd-flag" : ""}"><td class="rd-name">${esc(b.name)}</td><td class="num">${esc(b.value)}${b.unit ? ` <span class="rd-unit">${esc(b.unit)}</span>` : ""}</td><td class="num rd-range">${esc(b.range || "—")}</td><td>${f ? `<span class="rd-flagmark">${esc(b.flag)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table>`)).join(""); return figs([fig(L.total_draws ?? "—", "draws"), fig(bm.length, "biomarkers"), fig(L.flagged_count ?? 0, "flagged"), L.latest_draw_date && fig(L.latest_draw_date, "latest draw")]) + secs + note("Reference ranges are lab-provided; flags mark out-of-range."); }
async function renderPhysical(d) { const x = d.latest_dexa; if (!x) return empty("No DEXA scan on file yet — body-composition detail appears here after your next scan."); const bc = x.body_composition || {}, s = x.score_360 || {}, idx = x.indices || {}, bone = x.bone || {}, sf = x.segmental_fat || {}, sl = x.segmental_lean || {}; const wp = await tryJSON("/api/weight_progress"); const wj = await tryJSON("/api/journey"); const chart = sec("Weight trajectory", lineChart((wp && wp.weight_progress) || [], { valueKey: "weight_lbs", goal: wj && wj.journey && wj.journey.goal_weight_lbs, unit: " lb", label: "Weight · recent readings", emptyMsg: "Weight trajectory fills as weigh-ins accrue." })); return chart + figs([bc.body_fat_pct != null && fig(fmt(bc.body_fat_pct, 1) + "%", "body fat"), bc.lean_mass_lb != null && fig(dualWeight(bc.lean_mass_lb, "lb"), "lean mass"), bc.visceral_fat_lb != null && fig(dualWeight(bc.visceral_fat_lb, "lb"), "visceral fat"), s.biological_age != null && fig(fmt(s.biological_age, 1), "biological age")]) + sec("Composition", kvtable(bc)) + sec("Indices (ALMI / FFMI / FMI)", kvtable(idx)) + sec("Bone density", kvtable(bone)) + (Object.keys(sf).length ? sec("Segmental fat %", kvtable(sf)) : "") + (Object.keys(sl).length ? sec("Segmental lean", kvtable(sl)) : "") + note(`DEXA scan${x.scan_date ? ` · ${esc(x.scan_date)}` : ""}.`); }
// P0.1 — The Lift Index: per-lift estimated-1RM TREND (sparkline + ▲/▼/flat tag), never a
// 1RM target/"goal met". Frame = building the engine, not PRs. Ember = load up; down = muted
// ink (never red); honesty gate: no arrow/slope until ~3+ sessions of that lift.
function liftIndex(benchmarks) {
  const tiles = (benchmarks || []).map((l) => {
    const hist = (l.history || []).map((h) => h.e1rm).filter((v) => Number.isFinite(v));
    const sess = l.sessions != null ? l.sessions : hist.length;
    if (sess < 3) {
      return `<div class="li-tile li-thin"><span class="li-name">${esc(ttl(l.lift))}</span>` +
        `<span class="li-fill label">fills in — ${fmt(sess)} session${sess === 1 ? "" : "s"} logged</span></div>`;
    }
    const first = hist[0], last = hist[hist.length - 1], delta = last - first;
    const thr = Math.max(2, first * 0.02);
    const tag = delta > thr ? `<span class="li-tag li-up">▲ load up</span>`
      : delta < -thr ? `<span class="li-tag li-down">▼ load down</span>`
        : `<span class="li-tag li-flat">› holding</span>`;
    return `<div class="li-tile"><div class="li-top"><span class="li-name">${esc(ttl(l.lift))}</span>${tag}</div>` +
      sparkline(hist) +
      `<span class="li-meta label">est. ${dualWeight(last, "lb")} · ${fmt(sess)} sessions</span></div>`;
  }).join("");
  return `<div class="li-grid">${tiles}</div>`;
}
const _weekKey = (iso) => { const d = new Date(iso + "T00:00:00"); const off = (d.getDay() + 6) % 7; d.setDate(d.getDate() - off); return d.toISOString().slice(0, 10); };
// §0 hero — the session-volume ramp (P0.2): building, with the load watched. WoW % +
// honest "ACWR unlocks ~4 weeks" placeholder; two-voice load-management caution (signed off).
function trainingVolumeRamp(workouts) {
  const sess = (workouts || []).filter((w) => w.total_volume_kg != null && w.date).slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!sess.length) return "";
  const series = sess.map((w) => ({ date: w.date, value: w.total_volume_kg }));
  const first = sess[0].total_volume_kg, last = sess[sess.length - 1].total_volume_kg;
  const ratio = first > 0 ? last / first : null;
  const byWeek = {};
  for (const w of sess) { const k = _weekKey(w.date); byWeek[k] = (byWeek[k] || 0) + w.total_volume_kg; }
  const weeks = Object.keys(byWeek).sort();
  let wow = null;
  if (weeks.length >= 2) { const a = byWeek[weeks[weeks.length - 2]], b = byWeek[weeks[weeks.length - 1]]; if (a > 0) wow = Math.round((b / a - 1) * 100); }
  const chart = lineChart(series, { valueKey: "value", unit: " kg", label: "Per-session volume", spine: true, emptyMsg: "The volume ramp draws in as sessions accrue." });
  const rmult = ratio ? ratio.toFixed(1) : "—";
  const machine = [`${sess.length} sessions`, `${fmt(Math.round(first))} → ${fmt(Math.round(last))} kg`, ratio ? `×${rmult} so far` : null, wow != null ? `WoW ${wow >= 0 ? "+" : ""}${wow}%` : null, "ACWR needs ~4 wks"].filter(Boolean).join(" · ");
  const serif = `Session volume roughly ${rmult}×'d ${weeks.length <= 1 ? "this week" : "over the window"} — ${fmt(Math.round(first))} → ${fmt(Math.round(last))} kg. That's how a foundation gets built, but it's also the kind of jump where connective tissue — which adapts slower than muscle — starts writing cheques the joints have to cash. Nothing here says too much yet; only that the rate is worth watching. The acute:chronic load ratio that would flag it properly needs ~4 weeks of history — until then this is watched, not judged.`;
  const note2 = `<p class="rd-meta label">${weeks.length < 2 ? "Week-over-week fills in next week · " : ""}ACWR (acute:chronic load) unlocks at ~4 weeks.</p>`;
  return sec("The volume ramp — building, with the load watched",
    chart + note2 + `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
// §0 hero (twin) — RHR decline (P0.3), promoted out of vitals. The inversion: RHR-DOWN is
// the WIN → reads ember-positive (the engine answering), with a multi-factorial caveat in
// mono. Refuses <4 points. Binds pulse_history rhr_bpm.
function trainingRHRHero(hist) {
  const series = (hist || []).map((h) => ({ date: h.date, value: h.rhr_bpm })).filter((p) => Number.isFinite(Number(p.value)));
  if (series.length < 4) return "";
  const first = series[0].value, last = series[series.length - 1].value, delta = Math.round(last - first);
  const down = delta < 0;
  const chart = lineChart(series, { valueKey: "value", unit: " bpm", label: "Resting heart rate · nightly", spine: true });
  const machine = `RHR ${fmt(first)} → ${fmt(last)} bpm · ${delta <= 0 ? "−" : "+"}${fmt(Math.abs(delta))} since the cut began · multi-factorial (fluid · sleep · deload), not a VO2max claim`;
  const serif = down
    ? `The resting heart rate is drifting down — and down is the win here: the engine starting to answer the work. Early in a cut that's the body responding, not a fitness verdict yet, but it's the direction you want.`
    : `Resting heart rate is holding ${delta === 0 ? "flat" : "up"} so far — early-cut noise more than signal; the engine's read fills in as the weeks accrue.`;
  return sec("Resting heart rate — the engine answering",
    chart + `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
// P1.4 — Stylized anatomical body-map (front + back), each muscle zone shaded by ember
// intensity = weekly working sets vs its optimal band. ONE hue (intensity), never red.
// Signed off despite the app-cliché cost. Binds muscle_volume.
function muscleBodyMap(mv) {
  if (!mv || !mv.length) return "";
  const by = {}; for (const m of mv) by[m.muscle] = m;
  const op = (name) => { const m = by[name]; if (!m) return 0.1; return Math.max(0.12, Math.min(1, m.sets_per_week / (m.MAV_hi || 16))); };
  const z = (name, shape) => `<g class="bm-zone" style="--o:${op(name).toFixed(2)}"><title>${esc(by[name] ? `${name}: ${by[name].sets_per_week}/wk · ${by[name].status}` : `${name}: none logged`)}</title>${shape}</g>`;
  const head = (cx) => `<circle class="bm-head" cx="${cx}" cy="20" r="13"/>`;
  const S = 140;
  const front = head(64) +
    z("Shoulders", `<ellipse class="bm-m" cx="44" cy="46" rx="13" ry="9"/><ellipse class="bm-m" cx="84" cy="46" rx="13" ry="9"/>`) +
    z("Chest", `<rect class="bm-m" x="48" y="42" width="32" height="22" rx="6"/>`) +
    z("Biceps", `<ellipse class="bm-m" cx="30" cy="80" rx="8" ry="16"/><ellipse class="bm-m" cx="98" cy="80" rx="8" ry="16"/>`) +
    z("Core", `<rect class="bm-m" x="50" y="66" width="28" height="40" rx="5"/>`) +
    z("Quads", `<rect class="bm-m" x="46" y="112" width="15" height="46" rx="6"/><rect class="bm-m" x="67" y="112" width="15" height="46" rx="6"/>`) +
    z("Calves", `<rect class="bm-m" x="47" y="166" width="13" height="36" rx="5"/><rect class="bm-m" x="68" y="166" width="13" height="36" rx="5"/>`) +
    `<text class="bm-cap" x="64" y="220">front</text>`;
  const back = head(64 + S) +
    z("Shoulders", `<ellipse class="bm-m" cx="${44 + S}" cy="46" rx="13" ry="9"/><ellipse class="bm-m" cx="${84 + S}" cy="46" rx="13" ry="9"/>`) +
    z("Back", `<rect class="bm-m" x="${48 + S}" y="44" width="32" height="40" rx="6"/>`) +
    z("Triceps", `<ellipse class="bm-m" cx="${30 + S}" cy="80" rx="8" ry="16"/><ellipse class="bm-m" cx="${98 + S}" cy="80" rx="8" ry="16"/>`) +
    z("Glutes", `<rect class="bm-m" x="${50 + S}" y="88" width="28" height="20" rx="8"/>`) +
    z("Hamstrings", `<rect class="bm-m" x="${46 + S}" y="110" width="15" height="48" rx="6"/><rect class="bm-m" x="${67 + S}" y="110" width="15" height="48" rx="6"/>`) +
    z("Calves", `<rect class="bm-m" x="${47 + S}" y="166" width="13" height="36" rx="5"/><rect class="bm-m" x="${68 + S}" y="166" width="13" height="36" rx="5"/>`) +
    `<text class="bm-cap" x="${64 + S}" y="220">back</text>`;
  return sec("The body map — volume by muscle",
    `<figure class="chart bodymap"><svg viewBox="0 0 270 232" role="img" aria-label="Body map shaded by per-muscle weekly volume, front and back.">${front}${back}</svg>` +
    `<figcaption class="chart-cap label">Ember intensity = working sets vs the optimal band — brighter is more trained. Hover a muscle for its sets/week.</figcaption></figure>`);
}
// P1.1 — Effort / autoregulation: avg working-set RPE per session (Hevy logs RPE per set).
// Renders only when RPE is actually logged; the trend draws at 4+ sessions.
function trainingRPE(workouts) {
  const sess = [];
  for (const w of workouts || []) {
    const rpes = [];
    for (const e of w.exercises || []) for (const s of e.sets || []) { const r = Number(s.rpe); if (Number.isFinite(r) && r > 0) rpes.push(r); }
    if (rpes.length) sess.push({ date: w.date, avg: rpes.reduce((a, b) => a + b, 0) / rpes.length, n: rpes.length });
  }
  if (!sess.length) return "";
  sess.sort((a, b) => (a.date < b.date ? -1 : 1));
  const series = sess.map((s) => ({ date: s.date, value: Math.round(s.avg * 10) / 10 }));
  const last = series[series.length - 1].value;
  const chart = series.length >= 4
    ? lineChart(series, { valueKey: "value", unit: " RPE", label: "Avg working-set RPE per session", spine: true })
    : `<p class="rd-meta label">Latest session RPE ${last} · ${series.length} session${series.length === 1 ? "" : "s"} — the trend draws in at 4+.</p>`;
  return sec("Effort — RPE (autoregulation)",
    chart + `<p class="rd-meta label">Average working-set RPE per session — how hard the work actually felt. The autoregulation read; it feeds session sRPE → honest internal load.</p>`);
}
// P1.2 — Internal load: session sRPE = session RPE × duration (min). The honest input for ACWR.
function trainingSRPE(workouts) {
  const sess = [];
  for (const w of workouts || []) {
    const rpes = [];
    for (const e of w.exercises || []) for (const s of e.sets || []) { const r = Number(s.rpe); if (Number.isFinite(r) && r > 0) rpes.push(r); }
    const dur = Number(w.duration_min);
    if (rpes.length && Number.isFinite(dur) && dur > 0) {
      const avg = rpes.reduce((a, b) => a + b, 0) / rpes.length;
      sess.push({ date: w.date, srpe: Math.round(avg * dur) });
    }
  }
  if (!sess.length) return "";
  sess.sort((a, b) => (a.date < b.date ? -1 : 1));
  const rows = sess.map((s) => ({ label: fmtShort(s.date).split(" ")[1] || "", value: s.srpe }));
  return sec("Internal load — session sRPE",
    barChart(rows, { valueKey: "value", labelKey: "label", label: "sRPE (RPE × minutes) per session" }) +
    `<p class="rd-meta label">Internal training load = session RPE × duration. The honest input for ACWR — which unlocks at ~4 weeks (P2.2), not before.</p>`);
}
async function renderTraining(d) { const t = d.training || {}; const [str, wk, wo, ph] = await Promise.all([tryJSON("/api/strength_benchmarks"), tryJSON("/api/weekly_physical_summary"), tryJSON("/api/workouts"), tryJSON("/api/pulse_history")]); const ramp = trainingVolumeRamp((wo && wo.workouts) || []); const rhrHero = trainingRHRHero((ph && ph.pulse_history) || []); const head = figs([fig(t.workouts_30d ?? "—", "workouts · 30d"), fig(t.weekly_avg ?? "—", "weekly avg"), t.z2_pct != null && fig(t.z2_pct + "%", "zone-2 target"), t.strength_sessions_30d != null && fig(t.strength_sessions_30d, "strength · 30d"), d.walking && d.walking.avg_daily_steps != null && fig(fmt(d.walking.avg_daily_steps), "avg daily steps")]); const _cardioHR = (d.cardio_sessions || []).filter((c) => c.avg_hr != null && c.minutes); const hrSec = _cardioHR.length ? sec("HR of the engine — is the easy work staying easy?", barChart(_cardioHR.slice(0, 12).map((c) => ({ label: String(c.sport || "—").slice(0, 8), value: Math.round(Number(c.avg_hr)) })), { valueKey: "value", labelKey: "label", label: "Avg HR per cardio session (bpm)" }) + `<p class="rd-meta label">Easy aerobic work should sit low (≈ under 129 bpm, ~70% of max) — proof the base stays base. Lifting HR isn't shown: Whoop returns 0 HR-zone minutes for lifts, so that's an honest gap an HR strap would fill — never a 0 bar.</p>`) : ""; const z2v = t.z2_weekly_avg_min, z2t = t.z2_target_min || 150; const z2Sec = z2v != null ? sec("The engine — Zone-2 base", targetSpine(z2v, z2t, { valueLabel: "Z2/wk", targetLabel: "150 target", unit: " min", label: "Zone-2 minutes per week" }) + `<p class="rd-meta label">Counts steady aerobic work across sources — Strava, Whoop zones, AND Hevy bike/elliptical. The easy work that builds the engine.</p>`) : ""; const lifts = (str && str.benchmarks) || []; const strSec = lifts.length ? sec("The Lift Index — load trend, not max-testing", liftIndex(lifts) + `<p class="rd-meta label">Estimated from working sets (Epley) — a direction, not a 1RM goal. Foundation block: building the engine, not chasing PRs.</p>`) : ""; const days = (wk && wk.days) || []; const wkSec = days.length ? sec("This week — daily movement", `<table class="rd-tbl"><thead><tr><th>day</th><th>steps</th><th>active min</th></tr></thead><tbody>${days.map((x) => `<tr><td class="rd-name">${esc(x.day_of_week || x.date)}</td><td class="num">${fmt(x.steps)}</td><td class="num">${fmt(x.total_active_minutes)}</td></tr>`).join("")}</tbody></table>`) : ""; const rpeSec = trainingRPE((wo && wo.workouts) || []); const srpeSec = trainingSRPE((wo && wo.workouts) || []); const hrStrapSec = sec("Lifting HR zones — coming online", `<div class="nut-coming"><p class="rd-archive">Whoop returns 0 HR-zone minutes for lifting, so the cardiovascular cost of the lifts is a gap. A chest HR strap worn during sessions would fill it — turning "how hard did the lift tax the engine" from blank into data. <span class="confidence conf-low">needs HR strap</span></p></div>`); const ruckSec = sec("Rucking load & incline — coming online", `<div class="nut-coming"><p class="rd-archive">Walking is the primary engine, but it's logged flat — no pack weight or grade. Capturing rucking load / incline would make the walk progressible (same minutes, more stimulus) instead of a fixed floor. <span class="confidence conf-low">needs capture</span></p></div>`); const acwrSec = sec("Load gauge (ACWR) — coming online", `<div class="nut-coming"><p class="rd-archive">The acute:chronic workload ratio — this week's load against the rolling 4-week baseline — is the standard read on whether the ramp is sustainable or tipping into the danger zone. It needs ~3–4 weeks of history before it means anything; computing it at week one would be noise dressed as a verdict. The inputs (session sRPE, volume) are already accruing. <span class="confidence conf-low">unlocks ~4 weeks</span></p></div>`); const _strainDays = ((ph && ph.pulse_history) || []).map((h) => ({ date: h.date, value: Number(h.strain) })).filter((x) => Number.isFinite(x.value) && x.value > 0); const strainSec = _strainDays.length ? sec("Absorbing the work — daily strain", barChart(_strainDays.map((x) => ({ label: fmtShort(x.date).split(" ")[1] || "", value: Math.round(x.value * 10) / 10 })), { valueKey: "value", labelKey: "label", label: "Whoop day strain (0–21)" }) + `<p class="rd-meta label">Day-by-day cardiovascular load, not a single average headline. The strain-vs-recovery overlay fills in (P2.1).</p>`) : ""; const _phRec = ((ph && ph.pulse_history) || []).map((h) => ({ date: h.date, rec: Number(h.recovery_pct), str: Number(h.strain) })); const _recS = _phRec.filter((x) => Number.isFinite(x.rec)).map((x) => ({ date: x.date, value: x.rec })); const _strS = _phRec.filter((x) => Number.isFinite(x.str)).map((x) => ({ date: x.date, value: Math.round(x.str * 100 / 21) })); const overlaySec = (_recS.length >= 4 && _strS.length >= 4) ? sec("Strain vs recovery", dualLineChart(_recS, _strS, { aLabel: "recovery %", bLabel: "strain ·scaled", label: "does the load cost next-day recovery?", showGap: false }) + `<p class="rd-meta label">Recovery % (ember) against day strain scaled to 100 (muted dashed). Observation only — n=1, no coefficient drawn (needs ≥2 weeks).</p>`) : ""; const _mv = d.muscle_volume || []; const mvSec = _mv.length ? sec("Per-muscle volume vs landmarks", landmarkBars(_mv, { label: "MEV = minimum effective · MAV = optimal range · MRV = max recoverable." }) + `<p class="rd-meta label">Weekly working sets per muscle against the volume landmarks (Israetel). Ember = in the optimal MEV–MAV band; muted = under or over. Week-one sets/week are extrapolated from a short window.</p>`) : ""; const bodyMapSec = _mv.length ? muscleBodyMap(_mv) : ""; const _tbp = d.training_blueprint; const blueprintSec = (_tbp && _tbp.public) ? sec("Present vs the proven blueprint", `<p class="rd-meta label">Present training vs the proven loss-period blueprint${_tbp.confidence ? ` · ${esc(_tbp.confidence)} confidence` : ""}. <span class="confidence conf-low">private — blueprint</span></p>`) : ""; const _ppl = { Push: 0, Pull: 0, Legs: 0 }; for (const w of (wo && wo.workouts) || []) { const ti = String(w.title || "").toLowerCase(); const cat = ti.includes("push") ? "Push" : ti.includes("pull") ? "Pull" : (ti.includes("leg") || ti.includes("squat")) ? "Legs" : null; if (!cat) continue; let vol = w.total_volume_kg; if (vol == null) { vol = 0; for (const e of w.exercises || []) for (const s of e.sets || []) vol += (Number(s.reps) || 0) * (Number(s.weight_kg) || 0); } _ppl[cat] += Number(vol) || 0; } const _pplRows = Object.entries(_ppl).filter(([, v]) => v > 0).map(([k, v]) => ({ label: k, value: Math.round(v) })); const pplSec = _pplRows.length ? sec("Push / Pull / Legs balance", barChart(_pplRows, { valueKey: "value", labelKey: "label", label: "Working-set volume by split (kg)" }) + `<p class="rd-meta label">Is one pattern carrying the others? Working-set volume tagged from Hevy session titles.</p>`) : ""; const _mod = (d.daily_modality_minutes_30d || []).map((m) => ({ date: m.date, lift: m.strength_min || 0, cardio: (m.walking_min || 0) + (m.cycling_min || 0) + (m.hiking_min || 0) + (m.soccer_min || 0) + (m.other_min || 0), mob: (m.stretching_min || 0) + (m.breathwork_min || 0) })); const modSec = _mod.some((m) => m.lift + m.cardio + m.mob > 0) ? sec("Training time — where the minutes go", stackedDayColumns(_mod, [{ key: "lift", label: "lift", tone: "lift" }, { key: "cardio", label: "walk/cardio", tone: "cardio" }, { key: "mob", label: "mobility", tone: "mob" }], { label: "minutes by modality · per day" }) + `<p class="rd-meta label">Is the engine work happening, or getting crowded out? Mobility gets its own lane here instead of hiding in the cardio list.</p>`) : ""; const _stepsTrend = (d.walking && d.walking.daily_steps_trend) || []; const wlk = d.walking || {}; const walkSec = _stepsTrend.length ? sec("Walking — the primary engine", figs([wlk.avg_daily_steps != null && fig(fmt(wlk.avg_daily_steps), "avg daily steps"), wlk.total_miles_30d != null && fig(fmt(wlk.total_miles_30d) + " mi", "walked · 30d"), wlk.avg_pace_min_per_mi != null && fig(fmt(wlk.avg_pace_min_per_mi) + "/mi", "avg pace")]) + heatStrip(_stepsTrend, { valueKey: "steps", label: "Daily steps", unit: " steps" })) : ""; const _MOBRE = /stretch|yoga|mobility|foam|recovery|\brest\b/i; const cardio = (d.cardio_sessions || []).filter((w) => w.modality !== "mobility" && !_MOBRE.test(String(w.sport || ""))); const _km = (mi) => (mi != null ? (mi * 1.60934).toFixed(1) : null); const sessSec = cardio.length ? sec("Recent cardio", `<table class="rd-tbl"><thead><tr><th>date</th><th>activity</th><th>distance</th><th>min</th><th>avg HR</th></tr></thead><tbody>${cardio.slice(0, 20).map((w) => `<tr><td class="rd-name">${esc(String(w.date || "").slice(0, 10))}</td><td>${esc(ttl(w.sport || "—"))}</td><td class="num rd-range">${w.distance_mi != null ? `${fmt(w.distance_mi, 1)} mi · ${_km(w.distance_mi)} km` : "—"}</td><td class="num">${fmt(w.minutes)}</td><td class="num">${fmt(w.avg_hr)}</td></tr>`).join("")}</tbody></table>`) : ""; const log = (wo && wo.workouts) || []; const logSec = log.length ? sec("Strength log — per-exercise sets", log.slice(0, 12).map((w) => `<details class="wlog"><summary class="wlog-sum"><span class="wlog-t">${esc(w.title || w.date)}</span><span class="wlog-m label">${[w.date, w.exercise_count != null && Math.round(w.exercise_count) + " exercises", w.total_volume_kg != null && dualWeight(w.total_volume_kg, "kg")].filter(Boolean).map(esc).join("  ·  ")}</span></summary>${(w.exercises || []).map((e) => `<div class="wlog-ex"><p class="wlog-ex-n">${esc(e.name)}</p><table class="rd-tbl"><tbody>${(e.sets || []).map((s, i) => `<tr><td class="rd-name">${esc(s.type && s.type.toLowerCase() !== "normal" ? s.type : "set")} ${i + 1}</td><td class="num">${s.reps != null ? fmt(s.reps) + " reps" : "—"}</td><td class="num rd-range">${s.weight_kg != null ? dualWeight(s.weight_kg, "kg") : (s.distance_m != null ? fmt(s.distance_m) + " m" : "—")}</td></tr>`).join("")}</tbody></table></div>`).join("")}</details>`).join("")) : ""; if (!ramp && !rhrHero && !head.includes("fig-v") && !strSec && !wkSec && !sessSec && !logSec) return empty("No training logged yet — workouts, Zone-2, and strength benchmarks appear here as sessions accrue."); return ramp + rhrHero + head + z2Sec + hrSec + walkSec + strSec + pplSec + mvSec + bodyMapSec + blueprintSec + modSec + strainSec + overlaySec + rpeSec + srpeSec + acwrSec + hrStrapSec + ruckSec + logSec + sessSec + wkSec + note("Correlative — training load vs the body's response. Per-exercise sets from Hevy; per-session strain & zones from Whoop."); }
// The §0 verdict (P0.1): mono states the figures, serif judges the trade. Computed
// only from protein_hit_pct + avg_deficit — no fabricated mechanism, just the honest read.
function nutritionVerdict(n) {
  const hasDef = n.avg_deficit != null && Number.isFinite(Number(n.avg_deficit));
  const hasHit = n.protein_hit_pct != null && Number.isFinite(Number(n.protein_hit_pct));
  if (!hasDef && !hasHit) return null;
  const d = Number(n.avg_deficit), h = Number(n.protein_hit_pct);
  const machine = [
    n.avg_calories != null ? `${fmt(n.avg_calories)} in` : null,
    n.tdee != null ? `${fmt(n.tdee)} maintenance` : null,
    hasDef ? `${d >= 0 ? "−" : "+"}${fmt(Math.abs(Math.round(d)))} kcal/day` : null,
    hasHit ? `protein hit ${fmt(h)}%` : null,
  ].filter(Boolean).join(" · ");
  const realDeficit = hasDef && d >= 250;
  let human;
  if (!hasDef) {
    human = h === 0 ? "Protein's under target every logged day — the floor isn't being cleared yet."
      : `Protein clears the floor about ${fmt(h)}% of days. An expenditure read is needed before the deficit half of the story lands.`;
  } else if (!realDeficit) {
    human = "No real deficit on the logged days — this reads closer to maintenance than a cut right now.";
  } else if (!hasHit || h === 0) {
    human = "The deficit's real. The protein's missing every logged day — that's the trade you're making.";
  } else if (h < 50) {
    human = "The deficit's real, but the protein lands under target most days — some of the cut is coming out of muscle, not just fat.";
  } else if (h < 100) {
    human = "The deficit's real and the protein mostly holds — the days it slips are the ones to watch.";
  } else {
    human = "The deficit's real and the protein clears the floor every day — the cut's coming off the right places.";
  }
  return { machine, human };
}
// §0 Hero — one measuring-rule spine (0→maintenance, intake + maintenance ticks,
// deficit gap shaded) + the two-voice verdict. Replaces the old neutral big-number tiles;
// calories / TDEE / deficit fold in here.
function nutritionHero(n) {
  if (n.avg_calories == null && n.tdee == null && n.avg_deficit == null && n.protein_hit_pct == null) return "";
  const spine = (n.avg_calories != null && n.tdee != null)
    ? intakeSpine(n.avg_calories, n.tdee, { label: "30-day average intake vs estimated maintenance" })
    : "";
  const v = nutritionVerdict(n);
  const voice = v ? `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(v.machine)}</p><p class="tv-human">${esc(v.human)}</p></div>` : "";
  if (!spine && !voice) return "";
  return `<section class="rd-sec nut-hero">${spine}${voice}</section>`;
}
// §2 lead (P0.2) — promote protein_hit_pct to THE weighted signal. Ember-as-warning
// when the floor isn't cleared (giant figure + ▼ + "under floor" — never an ember "win"
// block, honouring HARD RULE 3). avg protein demotes into the subline.
function nutritionProteinLead(n) {
  if (n.protein_hit_pct == null) return "";
  const h = Number(n.protein_hit_pct);
  const low = h < 100; // target is a daily floor — anything under 100% missed days
  const days = n.days_logged, hitDays = n.protein_hit_days;
  const sub = [
    n.avg_protein_g != null ? `${fmt(n.avg_protein_g)} g avg` : null,
    n.protein_target_g != null ? `${fmt(n.protein_target_g)} g target` : null,
    (days != null && hitDays != null)
      ? (hitDays === 0 ? `missed every logged day · 0/${fmt(days)}` : `cleared ${fmt(hitDays)}/${fmt(days)} days`)
      : null,
  ].filter(Boolean).join(" · ");
  return `<section class="rd-sec nut-lead ${low ? "lead-warn" : "lead-ok"}">` +
    `<div class="lead-fig"><span class="lead-v mono">${fmt(h)}%</span>` +
    `<span class="lead-k label">protein target hit${low ? " — under floor" : " — floor cleared"}</span></div>` +
    `<p class="lead-sub mono">${esc(sub)}</p></section>`;
}
// §1 loss-rate readout (P0.9) — target rate → required deficit → actual deficit → gap,
// with the deficit-intensity flag, the rate and the protein status on ONE sightline.
// Two-voice: mono states the chain, serif surfaces the (contested) read honestly.
function nutritionLossRate(lr) {
  if (!lr || lr.target_rate_lb_wk == null) return "";
  const chain = [
    `target ${fmt(lr.target_rate_lb_wk)} lb/wk`,
    lr.required_deficit_kcal != null ? `needs −${fmt(lr.required_deficit_kcal)} kcal/day` : null,
    lr.actual_deficit_kcal != null ? `running ${lr.actual_deficit_kcal >= 0 ? "−" : "+"}${fmt(Math.abs(lr.actual_deficit_kcal))}` : "running — (needs an expenditure read)",
    lr.gap_kcal != null ? `gap ${lr.gap_kcal >= 0 ? "+" : "−"}${fmt(Math.abs(lr.gap_kcal))}` : null,
    lr.protein_hit_pct != null ? `protein ${fmt(lr.protein_hit_pct)}%` : null,
  ].filter(Boolean).join(" → ");
  const flag = lr.deficit_label ? `<span class="nut-flag nut-flag-${esc(lr.deficit_label)}">${esc(lr.deficit_label)} cut</span>` : "";
  let floorClause;
  if (lr.protein_hit_pct === 0) floorClause = ", and that floor's being missed every logged day";
  else if (lr.protein_hit_pct != null && lr.protein_hit_pct < 100) floorClause = ", and right now that floor's missed most days";
  else if (lr.protein_hit_pct != null && lr.protein_hit_pct >= 100) floorClause = ", and right now that floor's holding";
  else floorClause = "";
  const serif = `Three pounds a week is an aggressive rate. The bench is split on it — defensible early at this size if it's monitored, but only while the protein floor holds${floorClause}. That's why the rate and the protein sit on the same line here.`;
  return `<div class="two-voice nut-lossrate"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(chain)} ${flag}</p><p class="tv-human">${esc(serif)}</p></div>`;
}
// §2 serif "what this means" annotation under the protein-vs-target chart (P0.8,
// SIGNATURE 2 human voice). Data-derived, correlative, no causal claim.
function nutritionProteinAnnotation(n) {
  const avg = n.avg_protein_g, tgt = n.protein_target_g, hit = n.protein_hit_pct;
  if (avg == null || tgt == null) return "";
  const gap = Math.round(Number(tgt) - Number(avg));
  let txt;
  if (hit === 0) {
    txt = `The ember line stays the whole way under the dotted ${fmt(tgt)} g goal — every logged day landed below the floor, about ${fmt(gap)} g short on average. On a cut, that's the line that decides how much muscle the deficit costs.`;
  } else if (gap > 0) {
    txt = `The line sits mostly under the dotted ${fmt(tgt)} g goal — about ${fmt(gap)} g short on average. The days it crosses the line are the ones holding muscle.`;
  } else {
    txt = `The line rides at or above the dotted ${fmt(tgt)} g goal most days — the protein floor is holding through the cut.`;
  }
  return `<p class="tv-human nut-anno">${esc(txt)}</p>`;
}
// §2 lean-mass protein floor (P1.4) — grounds the abstract 190 g target in the real
// g/kg-lean muscle-retention floor (needs Withings lean mass for the exact value).
function nutritionProteinFloor(lm, target) {
  if (!lm || lm.lean_mass_lb == null) return "";
  const bits = [];
  if (lm.target_g_per_kg_lean != null && target != null) {
    bits.push(`The ${fmt(target)} g target is ${fmt(lm.target_g_per_kg_lean)} g per kg of ${fmt(lm.lean_mass_lb)} lb lean mass.`);
  }
  if (lm.floor_protein_g != null) {
    bits.push(`The muscle-retention floor on a cut is ~${fmt(lm.floor_g_per_kg_lean)} g/kg lean — about ${fmt(lm.floor_protein_g)} g a day (Helms et al.).`);
  }
  return bits.length ? `<p class="rd-meta label">${esc(bits.join(" "))}</p>` : "";
}
// §3.1 standing self-grading prediction (P2.1) — the bet + its confidence band + the
// verdict. A prediction you don't grade is a horoscope, so the resolution date + criteria
// are stated up front; the verdict reads pending until the date, then confirmed/refuted/drifted.
function nutritionProjection(pj) {
  if (!pj || pj.current_weight_lbs == null || pj.target_weight_lbs == null) return "";
  const vClass = pj.verdict === "confirmed" ? "pj-ok" : pj.verdict === "refuted" ? "pj-warn" : "pj-pending";
  const vLabel = pj.verdict === "pending" ? `pending — resolves ${esc(pj.resolves_on || pj.projected_date)}` : esc(pj.verdict);
  const band = (pj.band_earliest && pj.band_latest) ? ` (band ${esc(pj.band_earliest)} → ${esc(pj.band_latest)})` : "";
  const chain = `the platform bets ${fmt(pj.current_weight_lbs)} lb → ${fmt(pj.target_weight_lbs)} lb by ${esc(pj.projected_date)}${band} · at the implied ${fmt(pj.implied_rate_lb_wk)} lb/wk`;
  const serif = `This is the standing bet, stated in the open: where the current pace puts the scale, by when, with the honest spread. It grades itself when the date arrives — ${pj.verdict === "pending" ? "pending until then" : `called <strong>${esc(pj.verdict)}</strong>`}.`;
  return sec("The standing bet — self-grading",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(chain)} <span class="nut-flag ${vClass}">${vLabel}</span></p><p class="tv-human">${serif}</p></div>`);
}
// §3.2 reconciliation (P2.2) — projected loss from energy balance vs the actual scale.
// Gated on ≥2 weeks overlap (honesty rule); NO Pearson/correlation chip ever.
function nutritionReconciliation(rc) {
  if (!rc) return "";
  if (!rc.ready) {
    return sec("Scale vs the log — reconciliation",
      empty(`The scale-vs-log reconciliation draws in at ${rc.min_days || 14}+ overlapping days — ${rc.overlap_days || 0} so far. Under two weeks the gap is noise, not the logging-accuracy story, so it waits.`));
  }
  const days = rc.days || [];
  const projSeries = days.filter((r) => r.projected_loss_lbs != null).map((r) => ({ date: r.date, value: r.projected_loss_lbs }));
  const actSeries = days.filter((r) => r.actual_loss_lbs != null).map((r) => ({ date: r.date, value: r.actual_loss_lbs }));
  const gap = rc.gap_lbs;
  const gapTxt = gap == null ? "" : `<p class="tv-human nut-anno">Energy balance projected about ${fmt(rc.projected_loss_lbs)} lb off; the scale shows ${fmt(rc.actual_loss_lbs)} lb. The ${fmt(Math.abs(gap))} lb ${gap > 0 ? "shortfall" : "overshoot"} is the honest logging-accuracy / TDEE-drift gap — a reconciliation, not a verdict. Correlative, N=1 — no coefficient drawn here.</p>`;
  return sec("Scale vs the log — reconciliation",
    dualLineChart(projSeries, actSeries, { aLabel: "projected (energy balance)", bLabel: "actual (scale)", unit: " lb", label: "cumulative loss" }) + gapTxt);
}
// §8 CGM × meals — a designed empty state (no live binding): a ghosted glucose curve with
// meal markers + "sensor not active — fills in when you wear one." The glucose page owns
// the live view; this is the nutrition-page placeholder for the eventual overlay.
function cgmEmptyState() {
  const W = 600, H = 130;
  const curve = "M8 92 C 60 90, 95 48, 145 60 S 225 98, 272 72 C 320 52, 352 96, 402 86 S 505 56, 560 80";
  const meals = [72, 252, 432];
  const markers = meals.map((x) => `<line class="cgm-meal" x1="${x}" y1="16" x2="${x}" y2="120"/><circle class="cgm-meal-dot" cx="${x}" cy="16" r="3"/>`).join("");
  return sec("Glucose × meals — coming online",
    `<div class="nut-coming cgm-ghost"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="cgm-svg" aria-hidden="true">${markers}<path class="cgm-curve" d="${curve}" vector-effect="non-scaling-stroke"/></svg>` +
    `<p class="rd-archive">When a CGM sensor is active, this marries each meal to its glucose response — the peak, the rise, the return to baseline, with the meal markers above. <strong>Sensor not active — fills in when you wear one.</strong> <span class="confidence conf-low">no sensor yet</span></p></div>`);
}
async function renderNutrition(d) {
  // The API nests macros under d.nutrition (was read flat → blank); meal/protein field
  // names are frequency/food/avg_daily_g (were count/name/grams → empty tables).
  const n = (d && d.nutrition) || (d && !d.error ? d : {});
  const [fm, ps] = await Promise.all([tryJSON("/api/frequent_meals"), tryJSON("/api/protein_sources")]);
  const meals = (fm && fm.meals) || [];
  const prot = (ps && (ps.protein_sources || ps.sources || ps.proteins)) || [];
  const parts = [];
  // ── §0 Hero — the verdict (P0.1). Folds calories/TDEE/deficit out of the tile row.
  const hero = nutritionHero(n);
  if (hero) parts.push(hero);
  // ── §2 lead — the protein miss as THE weighted signal (P0.2).
  const lead = nutritionProteinLead(n);
  if (lead) parts.push(lead);
  // The one latest-day figure kept as "news".
  const news = figs([
    n.latest_calories != null && fig(fmt(n.latest_calories), `latest logged${n.latest_date ? " · " + fmtShort(n.latest_date) : ""}`),
    n.latest_protein_g != null && fig(fmt(n.latest_protein_g) + "g", "protein that day"),
  ]);
  if (news.includes("fig-v")) parts.push(news);
  // avg protein folds into the protein lead's subline; carbs/fat stay as light context.
  const head = figs([
    n.avg_carbs_g != null && fig(fmt(n.avg_carbs_g) + "g", "avg carbs"),
    n.avg_fat_g != null && fig(fmt(n.avg_fat_g) + "g", "avg fat"),
  ]);
  if (head.includes("fig-v")) parts.push(head);
  // Hero trends — the daily macro time series the API always returned but the page never
  // drew. P0.8 deploys SIGNATURE 1 (the measuring-rule tick spine) on both, and a serif
  // "what this means" annotation (SIGNATURE 2, the human voice) under the protein chart.
  const trend = (d && d.nutrition_trend) || [];
  if (trend.length) {
    parts.push(sec("Energy — the deficit story",
      lineChart(trend, { valueKey: "calories", goal: n.tdee || null, unit: " kcal", label: "Calories vs maintenance", spine: true, emptyMsg: "The calorie trend fills as days are logged." }) +
      nutritionLossRate(d && d.loss_rate)));
    parts.push(sec("Protein vs target",
      lineChart(trend, { valueKey: "protein_g", goal: n.protein_target_g || null, unit: "g", label: "Protein per day vs target", spine: true }) +
      nutritionProteinAnnotation(n) +
      nutritionProteinFloor(d && d.lean_mass, n.protein_target_g)));
  }
  // §3.1 — the standing self-grading bet (P2.1).
  const proj = nutritionProjection(d && d.projection);
  if (proj) parts.push(proj);
  // §3.2 — scale-vs-log reconciliation (P2.2), gated on ≥2 weeks overlap.
  const recon = nutritionReconciliation(d && d.reconciliation);
  if (recon) parts.push(recon);
  // §3.3 — food-delivery off-protocol tell (P2.3, PRIVATE-by-default). Only renders when the
  // server opts it in (env flag OFF by default → field absent → nothing shows publicly).
  const fd = d && d.food_delivery;
  if (fd && fd.public && (fd.delivery_days || fd.home_days)) {
    parts.push(sec("Home-cooked vs delivery — off-protocol tell",
      figs([
        fd.avg_deficit_home != null && fig(fmt(fd.avg_deficit_home), `home-cooked deficit · ${fmt(fd.home_days)}d`),
        fd.avg_deficit_delivery != null && fig(fmt(fd.avg_deficit_delivery), `delivery-day deficit · ${fmt(fd.delivery_days)}d`),
      ]) +
      `<p class="rd-meta label">Delivery days vs home-cooked days, by average deficit — data, not a verdict. <span class="confidence conf-low">private signal</span></p>`));
  }
  // §3.4 — present-vs-PROVEN_BLUEPRINT (P2.5, NEVER public). Only renders if the server opts
  // it in (blueprint flag stays OFF → field absent → never shows on the public page).
  const bp = d && d.blueprint_benchmark;
  if (bp && bp.public) {
    parts.push(sec("Present vs the proven blueprint",
      figs([bp.current_avg_protein_g != null && fig(fmt(bp.current_avg_protein_g) + "g", "protein now"), bp.protein_target_g != null && fig(fmt(bp.protein_target_g) + "g", "target")]) +
      `<p class="rd-meta label">Present protocol vs the proven loss-period blueprint. <span class="confidence conf-low">private — blueprint</span></p>`));
  }
  // Average macro split — by ENERGY (P0.5): protein·4 / carbs·4 / fat·9, not gram mass.
  // Gram-fraction badly understates fat (16% by mass ≈ 30% by calories).
  const _kcal = (g, mult) => (g != null ? Math.round(Number(g) * mult) : 0);
  const pK = _kcal(n.avg_protein_g, 4), cK = _kcal(n.avg_carbs_g, 4), fK = _kcal(n.avg_fat_g, 9);
  if (pK || cK || fK) {
    parts.push(sec("Average macro split — by energy", stackedBar([
      { label: `Protein ${fmt(n.avg_protein_g)}g`, value: pK, tone: "ember" },
      { label: `Carbs ${fmt(n.avg_carbs_g)}g`, value: cK, tone: "ink" },
      { label: `Fat ${fmt(n.avg_fat_g)}g`, value: fK, tone: "faint" },
    ], { label: "Share of calories (protein·4 / carbs·4 / fat·9)", unit: " kcal" })));
  }
  // §3 — per-day macro composition by ENERGY (P0.7): reveals whether the cut comes out of
  // carbs/fat while protein holds. Refuses < 4 points via the chart kit.
  const trendDays = (d && d.nutrition_trend) || [];
  if (trendDays.length) {
    parts.push(sec("Where the cut comes from — per-day macros by energy",
      stackedColumns(trendDays, { emptyMsg: `Per-day macro composition draws in at 4+ logged days — ${trendDays.length} so far.` })));
  }
  // P0.6 — suppress empty scaffold. These comparisons render honest "needs more days"
  // states instead of zero-rows (no "Rest Day — Count 0" / "Weekend — Days 0").
  const DAYS = Number(n.days_logged) || 0;
  const TWO_WEEKS = 14;
  // Calorie cycling — only when BOTH training and rest days have logged data.
  const pz = (d && d.periodization) || {};
  const tdN = (pz.training_day && pz.training_day.count) || 0;
  const rdN = (pz.rest_day && pz.rest_day.count) || 0;
  if (tdN > 0 && rdN > 0) {
    parts.push(sec("Training-day vs rest-day", kvtable({ training_day: pz.training_day, rest_day: pz.rest_day })));
  } else if (tdN > 0 || rdN > 0) {
    parts.push(sec("Training-day vs rest-day", empty("Calorie cycling fills in once there are both training days and rest days logged — only one kind has data so far.")));
  }
  // §4 Rhythm — fasting & meal timing (P1.1). Average window + real avg-protein/meal +
  // the (now legitimate) per-meal distribution score + the per-day eating-window ribbon +
  // meal-time-of-day distribution. All from food_log per-entry time + protein.
  const ew = (d && d.eating_window) || {};
  const mr = (d && d.meal_rhythm) || {};
  const hourLbl = (h) => { const ap = h < 12 ? "a" : "p"; const hh = h % 12 === 0 ? 12 : h % 12; return `${hh}${ap}`; };
  const tdist = (mr.time_distribution || []).map((t) => ({ label: hourLbl(t.hour), value: t.protein_g }));
  const rhythmFigs = figs([
    ew.avg_hours != null && fig(fmt(ew.avg_hours) + "h", `avg window${ew.avg_first_meal ? ` · ${ew.avg_first_meal}–${ew.avg_last_meal}` : ""}`),
    mr.avg_protein_per_meal != null && fig(fmt(mr.avg_protein_per_meal) + "g", "avg protein / meal"),
    mr.protein_distribution_score != null && fig(fmt(mr.protein_distribution_score) + "%", "meals ≥30g protein"),
  ]);
  const ribbon = (mr.per_day_window && mr.per_day_window.length) ? mealWindowRibbon(mr.per_day_window, { refHours: mr.reference_window_hrs || 8, label: "Eating window · per day vs 16:8" }) : "";
  const tdistChart = tdist.length ? sec("When protein lands across the day", barChart(tdist, { valueKey: "value", labelKey: "label", label: "Protein by time of day (g · 2h buckets)" })) : "";
  if (rhythmFigs.includes("fig-v") || ribbon || tdistChart) {
    parts.push(sec("Rhythm — fasting & meal timing", (rhythmFigs.includes("fig-v") ? rhythmFigs : "") + ribbon + tdistChart));
  }
  // Weekday vs weekend — a real split needs ~2 weeks; below that it's noise, not signal.
  const ww = (d && d.weekday_vs_weekend) || {};
  const wdN = (ww.weekday && ww.weekday.days) || 0;
  const weN = (ww.weekend && ww.weekend.days) || 0;
  if (DAYS >= TWO_WEEKS && wdN > 0 && weN > 0) {
    parts.push(sec("Weekday vs weekend", kvtable(ww)));
  } else if (wdN > 0 || weN > 0) {
    parts.push(sec("Weekday vs weekend", empty(`The weekday/weekend split fills in at 2+ weeks of logging — ${DAYS} day${DAYS === 1 ? "" : "s"} so far.`)));
  }
  // Micronutrient sufficiency + protein-distribution score — beyond macros, the part almost
  // no transformation site shows (reverse-QA: rich in the data, surfaced nowhere).
  const mn = (d && d.micronutrients) || {};
  const suf = mn.sufficiency || {};
  // P0.3 — the protein-"timing" score is killed: it's a distribution score with no
  // per-meal timestamps behind it, it can't fall, and a "100" sitting over a 0% protein
  // hit congratulated the spacing of a thing he isn't eating enough of. Relabel as not-yet-
  // measured (P1.1 revives a real one once per-meal timestamps land).
  if (Object.keys(suf).length || mn.avg_pct != null) {
    // P0.4 — horizontal sufficiency bars 0→100%, worst-first, value-labelled, ember
    // reserved for the worst offenders (a deficiency is what to look at, not a win).
    const items = Object.entries(suf).map(([k, v]) => {
      const m = /_(mg|mcg|ug|g)$/i.exec(k);
      return { label: ttl(k.replace(/_(mg|mcg|ug|g)$/i, "")), pct: v && v.pct, actual: v && v.actual, target: v && v.target, unit: m ? m[1] : "" };
    });
    parts.push(sec("Micronutrients — what the food is short on",
      figs([mn.avg_pct != null && fig(fmt(mn.avg_pct) + "%", "micronutrient avg")]) +
      (items.length ? sufficiencyBars(items, { label: "Sufficiency vs daily target" }) : "")));
  }
  // §5 — Hydration & electrolytes (P1.2): sodium + potassium framed as the water-weight
  // honesty check on a cut (NOT a bare hydration ring). Week-one "the drop is water" caveat.
  const el = (d && d.electrolytes) || {};
  if (el.avg_sodium_mg != null) {
    const sod = el.avg_sodium_mg;
    const sodNote = sod < el.sodium_ref_low
      ? "below the 1.5–2.3 g range — low sodium on a cut can worsen cramps and lightheadedness"
      : sod > el.sodium_ref_high
        ? "above the 1.5–2.3 g range — more water retention, a higher scale reading"
        : "inside the 1.5–2.3 g range";
    const wk1 = (el.days_logged != null && el.days_logged < 14)
      ? `<p class="tv-human nut-anno">It's week one — the early scale drop is mostly water, not fat: sodium and glycogen swings move the number by pounds. Sodium here is the honesty check on that, not a hydration vanity score.</p>`
      : "";
    parts.push(sec("Hydration & electrolytes — the water-weight honesty check",
      figs([fig(fmt(sod), "avg sodium mg"), el.potassium_pct != null && fig(fmt(el.potassium_pct) + "%", "potassium vs target")]) +
      `<p class="rd-meta label">Sodium ${esc(sodNote)}. Potassium sufficiency is in Micronutrients above.</p>` + wk1));
  }
  // §"Can I hold this?" (P1.3) — daily hunger/energy 1–5 is NOT captured anywhere yet.
  // Honest designed empty state + flag (never stubbed). Gated on real nutrition data so a
  // truly empty page still shows the clean top-level empty state, not this placeholder.
  if ((n.days_logged || 0) > 0) {
    parts.push(sec("Can I hold this? — hunger & energy",
      `<div class="nut-coming"><p class="rd-archive">A daily 1–5 hunger and energy check-in isn't being captured yet. Once it is, this becomes a sparkline of how holdable the deficit actually feels day to day — the subjective side of "sustainable" that HRV and recovery can't see. <span class="confidence conf-low">needs capture</span></p></div>`));
    // §8 CGM × meals — designed empty state (no live binding).
    parts.push(cgmEmptyState());
  }
  if (meals.length)
    parts.push(
      sec(
        "Most-logged meals",
        `<table class="rd-tbl"><tbody>${meals
          .slice(0, 20)
          .map((m) => `<tr><td class="rd-name">${esc(m.name || m.meal)}</td><td class="num">${fmt(m.frequency ?? m.count ?? m.times)}×</td></tr>`)
          .join("")}</tbody></table>`,
      ),
    );
  if (prot.length)
    parts.push(
      sec(
        "Top protein sources",
        `<table class="rd-tbl"><tbody>${prot
          .slice(0, 20)
          .map((p) => `<tr><td class="rd-name">${esc(p.food || p.name || p.source)}</td><td class="num">${fmt(p.avg_daily_g ?? p.grams ?? p.g)}g/day</td></tr>`)
          .join("")}</tbody></table>`,
      ),
    );
  if (!parts.length) return empty("No nutrition logged yet — macros, frequent meals, and protein sources appear here once meals are tracked.");
  return parts.join("") + note("Correlative — intake vs the deficit.");
}
async function renderGlucose(d) { const [mg, mr] = await Promise.all([tryJSON("/api/meal_glucose"), tryJSON("/api/meal_responses")]); const cur = d && d.glucose; const rows = ((mr && mr.meals) || (mg && mg.meals) || []); const head = figs([cur && cur.avg != null && fig(fmt(cur.avg), "avg mg/dL"), cur && cur.tir != null && fig(cur.tir + "%", "time in range"), (mg && mg.has_cgm != null) && fig(mg.has_cgm ? "yes" : "no", "cgm active")]); const mealSec = rows.length ? sec("Meal glucose response", `<table class="rd-tbl"><thead><tr><th>meal</th><th>peak</th><th>Δ rise</th></tr></thead><tbody>${rows.slice(0, 25).map((m) => `<tr><td class="rd-name">${esc(m.name || m.meal)}</td><td class="num">${fmt(m.peak ?? m.peak_mgdl)}</td><td class="num">${fmt(m.delta ?? m.rise)}</td></tr>`).join("")}</tbody></table>`) : ""; const trendChart = sec("Glucose trend", lineChart(d.glucose_trend || [], { valueKey: "value", label: "Glucose", emptyMsg: "The glucose curve fills once a CGM sensor is active." })); if (!head.includes("fig-v") && !mealSec && !(d.glucose_trend || []).length) return trendChart + empty("No CGM data yet — once a sensor is active, this marries each meal to its glucose response (peak, rise, return-to-baseline)."); return head + trendChart + mealSec + note("Correlative — how specific meals moved glucose. Not diagnostic."); }
// §0 Forecast hero (P0.1) — the circadian-compliance forecast, PROMOTED to lead. A 0→100
// "tonight's odds" gauge + the four anchors (each with the lever to pull now) + two-voice.
// At-risk reads MUTED ink, never red/alarm (HARD RULE 5). Binds /api/circadian.
function circadianForecast(circ) {
  if (!circ || !circ.available) return "";
  const comps = Object.entries(circ.components || {});
  const anchors = comps.map(([name, c]) => {
    const pct = c.max ? Math.max(0, Math.min(1, c.score / c.max)) : 0;
    const tone = pct >= 0.7 ? "suf-ember" : "suf-ink"; // ember on-track, muted at-risk — never red
    const weak = name === circ.weakest_component;
    return `<div class="suf-row${weak ? " fc-lever" : ""}"><span class="suf-l">${esc(ttl(name))}${weak ? " · lever" : ""}</span>` +
      `<span class="suf-track"><span class="suf-fill ${tone}" style="width:${Math.round(pct * 100)}%"></span></span>` +
      `<span class="suf-v mono">${fmt(c.score)}/${fmt(c.max)}</span></div>`;
  }).join("");
  const score = circ.score;
  const atRisk = score != null && score < 60;
  const machine = [score != null ? `tonight ${fmt(score)}/100` : null, circ.category && ttl(circ.category),
    circ.weakest_component && `lever: ${ttl(circ.weakest_component)}`].filter(Boolean).join(" · ");
  const serif = (circ.prescription && !isBad(circ.prescription)) ? circ.prescription
    : (atRisk ? "Tonight's set-up is soft — the lever above is the one to pull before bed." : "Today's behaviours have tonight pointed the right way. The night below is the evidence, not the verdict.");
  const gauge = (score != null) ? targetSpine(score, 100, { valueLabel: "tonight", targetLabel: "100", unit: "", label: "Circadian compliance — what today's behaviours set up for tonight" }) : "";
  return sec("Tonight's odds — the forecast",
    gauge + (anchors ? `<div class="suf-rows fc-anchors">${anchors}</div>` : "") +
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
async function renderSleep(d) {
  const s = d.sleep_detail || {};
  const [circ, uni] = await Promise.all([tryJSON("/api/circadian"), tryJSON("/api/sleep_reconciliation")]);
  const parts = [];
  // §0 — the forecast LEADS (prospective, not retrospective).
  const fcHero = circadianForecast(circ);
  if (fcHero) parts.push(fcHero);
  // §1 — last night, demoted to EVIDENCE beneath the forecast.
  const lastNightHdr = "Last night — the evidence" + (lastNightDate(s, uni) ? ` · the night of ${lastNightDate(s, uni)}` : "");
  if (Object.values(s).some(has)) {
    parts.push(sec(lastNightHdr, figs([s.total_sleep_hours != null && fig(fmt(s.total_sleep_hours, 1), "hours"), s.sleep_efficiency != null && fig(fmt(s.sleep_efficiency) + "%", "efficiency"), s.recovery_score != null && fig(fmt(s.recovery_score), "recovery"), s.hrv != null && fig(fmt(s.hrv), "hrv ms"), s.sleep_score != null && fig(fmt(s.sleep_score), "composite score")]) + `<p class="rd-meta label">One night is noise, not a verdict — it's evidence the forecast above gets graded against. The composite "score" is Eight Sleep's black box; the hours, efficiency and stages are what actually move it.</p>`));
    if (s.deep_sleep_hours != null && s.rem_sleep_hours != null) parts.push(sec("Last night's stages", stackedBar([{ label: "Deep", value: s.deep_sleep_hours, tone: "ember" }, { label: "REM", value: s.rem_sleep_hours, tone: "ink" }, { label: "Light", value: Math.max(0, (s.total_sleep_hours || 0) - (s.deep_sleep_hours || 0) - (s.rem_sleep_hours || 0)), tone: "faint" }], { label: "Hours by stage", unit: "h" })));
    parts.push(sec("Stages & physiology", kvtable({ whoop_quality: s.whoop_quality, bed_temp_f: s.bed_temp_f })));
    parts.push(sec("Sleep-score trend · latest = last night", lineChart(d.sleep_trend || [], { valueKey: "sleep_score", label: "Sleep score · nightly", emptyMsg: "The sleep-score trend fills in nightly." })));
  }
  // Unified sleep — Whoop + Eight Sleep + Apple merged, best source per field.
  if (uni && uni.available) {
    const srcs = (uni.sources_present || []).map(ttl).join(", ");
    parts.push(sec("Unified sleep — sources reconciled" + (uni.night_of ? ` · the night of ${fmtShort(uni.night_of)}` : ""), figs([uni.total_duration_hours != null && fig(fmt(uni.total_duration_hours, 1), "hours · merged"), uni.recovery_score != null && fig(fmt(uni.recovery_score), "recovery"), uni.hrv_ms != null && fig(fmt(uni.hrv_ms), "hrv ms"), uni.sleep_efficiency_pct != null && fig(fmt(uni.sleep_efficiency_pct) + "%", "efficiency")]) + kvtable({ rem_pct: uni.rem_pct, deep_pct: uni.deep_pct, light_pct: uni.light_pct, awake_pct: uni.awake_pct, respiratory_rate: uni.respiratory_rate, room_temp_c: uni.room_temp_c, bed_temp_c: uni.bed_temp_c }) + (srcs ? `<p class="rd-meta label">merged from ${esc(srcs)} — best source per field</p>` : "")));
  }
  if (!parts.length) return empty("No sleep data yet — score, stages, HRV and recovery appear here nightly.");
  return parts.join("") + note("Correlative — tonight's forecast leads; last night and the trend are the evidence it earns its place against.");
}
function renderMind(d) { const m = d.mind || {}; const mp = d.mind_pillar; const vices = d.vice_streaks || []; const head = figs([mp && mp.level != null && fig(`L${fmt(mp.level)} · ${esc(mp.tier || "")}`, "mind pillar"), m.journal_entries_30d != null && fig(m.journal_entries_30d, "journal · 30d"), m.mood_entries_count != null && fig(m.mood_entries_count, "mood logs"), m.resist_rate_pct != null && fig(fmt(m.resist_rate_pct) + "%", "temptations resisted"), m.meaningful_pct != null && fig(m.meaningful_pct + "%", "meaningful talk")]); const v = vices.length ? sec("Vice streaks (held)", `<table class="rd-tbl"><tbody>${vices.map((x) => `<tr><td class="rd-name">${esc(ttl(x.name))}</td><td class="num">${fmt(x.current_streak)}d ${x.holding ? "✓" : ""}</td></tr>`).join("")}</tbody></table>`) : ""; const noLog = (m.journal_entries_30d || 0) === 0 && (m.mood_entries_count || 0) === 0; const honest = noLog ? note("No journal or mood logged this cycle yet — that part of the inner-life view fills in as you write. Below is what's tracked so far.") : ""; if (!head.includes("fig-v") && !v) return empty("No mood / journal / temptation data yet — the inner-life view fills in as you log."); return head + honest + v + note("Correlative — mood, reflection, restraint. Categories kept private."); }
function renderVices(d) {
  const v = d.vices || [];
  if (!v.length) return empty("No vice tracking yet.");
  const MILES = [7, 30, 90, 180, 365];
  const card = (x) => {
    const cur = Number(x.current_streak) || 0;
    const next = MILES.find((m) => m > cur) || cur + 365;
    const prev = [...MILES].reverse().find((m) => m <= cur) || 0;
    const pct = Math.max(4, Math.min(100, Math.round(((cur - prev) / (next - prev)) * 100)));
    return (
      `<article class="vice-card ${x.holding ? "vice-hold" : "vice-broke"}">` +
      `<header class="vice-top"><span class="vice-name">${esc(ttl(x.name))}</span><span class="vice-flag label">${x.holding ? "holding" : "reset"}</span></header>` +
      `<div class="vice-streak"><span class="vice-days num">${cur}</span><span class="vice-unit label">day${cur === 1 ? "" : "s"} clean</span></div>` +
      `<div class="vice-bar"><i style="width:${pct}%"></i></div>` +
      `<p class="vice-meta label">${[`next ${next}d`, x.best_streak != null && `best ${fmt(x.best_streak)}d`, x.relapses_90d != null && `${fmt(x.relapses_90d)} resets·90d`].filter(Boolean).join("  ·  ")}</p>` +
      `</article>`
    );
  };
  return (
    figs([fig(d.total_held ?? 0, "holding"), fig(d.total_tracked ?? v.length, "tracked")]) +
    `<div class="vice-grid">${v.map(card).join("")}</div>` +
    note("Shown honestly — held and broken both. Named privately.")
  );
}
function renderLedger(d) {
  const t = d.totals || {};
  const bc = d.by_cause || {};
  const head = figs([fig("$" + fmt(t.total_donated_usd), "donated"), fig("$" + fmt(t.total_bounties_usd), "bounties earned"), fig("$" + fmt(t.total_punishments_usd), "punishments"), fig(fmt(t.bounty_count), "bounties")]);
  // Surface the causes the money is routed to — present even at $0 so the page has the
  // human rules + personality (incl. the snake-rescue joke) instead of four bare zeros.
  const causeCard = (c, why) => `<div class="cause-card"><a class="cause-name" href="${esc(c.url || "#")}" target="_blank" rel="noopener">${esc(c.name)}</a>${c.short_description ? `<span class="cause-desc label">${esc(c.short_description)}</span>` : ""}${why && c[why] ? `<p class="cause-why">${esc(c[why])}</p>` : ""}<span class="cause-amt mono">$${fmt(c.total_usd || 0)} · ${fmt(c.count || 0)}×</span></div>`;
  const earned = (bc.earned_causes || []).filter((c) => c && c.name);
  const reluctant = (bc.reluctant_causes || []).filter((c) => c && c.name);
  const earnedSec = earned.length ? sec("Where winnings go", `<div class="cause-grid">${earned.map((c) => causeCard(c, "why_i_care")).join("")}</div>`) : "";
  const reluctantSec = reluctant.length ? sec("Where forfeits go (the ones that sting)", `<div class="cause-grid">${reluctant.map((c) => causeCard(c, "joke_note")).join("")}</div>`) : "";
  return head + earnedSec + reluctantSec + note("Money moved by the accountability rules — skin in the game. Causes shown whether or not money has moved yet.");
}
function renderDiscoveries(d) {
  // Real discoveries first: ai_findings = FDR-significant correlations computed from
  // Matt's own data (the API computed these but the page never rendered them — it showed
  // only library hypothesis templates, which read as placeholder). Hypotheses now last,
  // reframed "under test". Empty state names the small-n reality honestly.
  const findings = d.ai_findings || [],
    inner = d.inner_life || [],
    hyp = d.active_hypotheses || [];
  const card = (t, b, badge) =>
    `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(t)}</h3>${badge ? `<span class="rd-badge">${esc(badge)}</span>` : ""}</header>${b ? `<p class="rd-why">${esc(b)}</p>` : ""}</article>`;
  const fs = findings.length
    ? sec("Correlations found in the data", `<div class="rd-cards">${findings.map((f) => card(f.title, f.body, f.n ? `n=${f.n}` : "")).join("")}</div>`)
    : "";
  const is = inner.length ? sec("Inner-life findings", `<div class="rd-cards">${inner.map((f) => card(f.title, f.body, f.confidence)).join("")}</div>`) : "";
  const hs = hyp.length
    ? sec("Hypotheses under test", `<div class="rd-cards">${hyp.map((h) => card(h.name, h.hypothesis || h.description, h.evidence_tier)).join("")}</div>`)
    : "";
  if (!fs && !is && !hs)
    return empty("No discoveries yet — real correlations and findings surface here as the data accrues. This cycle is only days old, so it needs more data first.");
  return fs + is + hs + note("Correlative leads, not conclusions — FDR-corrected, but n is small this early in the cycle.");
}
function renderGenome(d) { const g = d.genome || d; const rs = g.risk_summary || {}; const cats = g.categories || {}; const head = figs([g.total_snps != null && fig(fmt(g.total_snps), "SNPs analysed"), rs.unfavorable != null && fig(rs.unfavorable, "unfavorable"), rs.favorable != null && fig(rs.favorable, "favorable")]); const cs = Object.keys(cats).length ? sec("Risk by category", kvtable(cats)) : ""; if (!head.includes("fig-v") && !cs) return empty("Genome not yet published."); return head + cs + note("Genotype is predisposition, not destiny — context for the biomarkers."); }
async function renderChallenges(d) {
  const cur = await tryJSON("/api/current_challenge");
  const cc = cur && cur.current_challenge;
  const list = d.challenges || [];
  const sm = d.summary || {};
  const banner = cc && cc.challenge ? `<div class="rd-obs"><p class="rd-primary">${esc(cc.challenge)}</p>${cc.detail ? `<p class="rd-why">${esc(cc.detail)}</p>` : ""}<p class="rd-meta label">day ${esc(cc.days_complete ?? 0)} of ${esc(cc.days_total ?? "—")}</p></div>` : "";
  const live = list.filter((c) => c.origin === "live");
  const avail = list.filter((c) => c.origin === "catalog" && c.status === "available");
  const backlog = list.filter((c) => c.origin === "catalog" && c.status === "backlog");
  const head = figs([fig(sm.active ?? live.length, "active"), fig(avail.length + backlog.length, "in the backlog")]);
  const liveCard = (c) => { const done = !!c.completed_at || c.status === "completed"; const active = !done && (c.status === "active" || !!c.activated_at); return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(c.name || ttl(c.challenge_id || "Challenge"))}</h3><span class="rd-badge ${active ? "rd-badge-live" : ""}">${done ? "completed" : active ? "active" : "candidate"}</span></header><p class="rd-meta label">${[c.character_xp_awarded != null && c.character_xp_awarded + " XP", c.badge_earned && "🏅 badge"].filter(Boolean).join("  ·  ")}</p></article>`; };
  const catCard = (c) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(c.name)}</h3><span class="rd-badge">${esc(c.status)}</span></header>${c.one_liner ? `<p class="rd-why">${esc(c.one_liner)}</p>` : ""}<p class="rd-meta label">${[c.category, c.difficulty, c.duration_days && c.duration_days + "d"].filter(Boolean).map(esc).join("  ·  ")}</p></article>`;
  const liveSec = sec("Taken on", live.length ? `<div class="rd-cards">${live.map(liveCard).join("")}</div>` : empty("None taken on yet this cycle."));
  // "Available now" vs "Backlog" was a distinction without a difference — both are
  // catalog ideas not yet taken on. One backlog.
  const candidates = avail.concat(backlog);
  const backSec = candidates.length ? sec(`Backlog (${candidates.length})`, `<div class="rd-cards">${candidates.slice(0, 80).map(catCard).join("")}</div>`) : "";
  return banner + head + liveSec + backSec + note("An N=1 instrument — reader participation is deferred.");
}
function renderProtocols(d) { const ps = (d.protocols || []).slice().sort((a, b) => (/(active|running|on)/i.test(a.status || "") ? 0 : 1) - (/(active|running|on)/i.test(b.status || "") ? 0 : 1)); if (!ps.length) return empty("No active protocols yet."); return figs([fig(ps.length, "active protocols")]) + `<div class="rd-cards">${ps.map((p) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}<p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>` + note("Matthew's deliberate interventions, read-only. Not medical advice."); }
function renderExperiments(d) {
  const xs = d.experiments || [];
  if (!xs.length) return empty("No experiments yet — the library is loading.");
  const running = xs.filter((x) => x.origin !== "library");
  const lib = xs.filter((x) => x.origin === "library");
  const avail = lib.filter((x) => x.status === "available");
  const backlog = lib.filter((x) => x.status === "backlog");
  const head = figs([fig(running.length, "running"), avail.length ? fig(avail.length, "ready to run") : "", fig(backlog.length, "in backlog")]);
  const runCard = (x) => { const done = /complete|done|ended|closed/i.test(x.status || ""); const verdict = x.hypothesis_confirmed === true ? "confirmed" : x.hypothesis_confirmed === false ? "not confirmed" : (x.outcome || x.status || "running"); return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge ${done ? "" : "rd-badge-live"}">${esc(x.status || "")}</span></header>${x.hypothesis ? `<p class="rd-why"><span class="label">hypothesis</span> ${esc(x.hypothesis)}</p>` : ""}${x.result_summary && !isBad(x.result_summary) ? `<p class="rd-line">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${[verdict, x.grade && "grade " + esc(x.grade)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`; };
  const libCard = (x) => {
    const meta = [x.pillar, x.difficulty, x.evidence_tier && "tier " + x.evidence_tier, x.evidence_citation && "src: " + x.evidence_citation].filter(Boolean).map(esc).join("  ·  ");
    const link = x.source_url ? ` · <a class="supp-ev-link" href="${esc(x.source_url)}" target="_blank" rel="noopener">evidence ↗</a>` : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge">${esc(x.status)}</span></header>${x.hypothesis ? `<p class="rd-why">${esc(x.hypothesis)}</p>` : x.result_summary ? `<p class="rd-why">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${meta}${link}</p></article>`;
  };
  const runSec = sec("Running now", running.length ? `<div class="rd-cards">${running.map(runCard).join("")}</div>` : empty("Nothing running yet this cycle — the experiment just started."));
  const pipeline = [...avail, ...backlog];
  const pipeSec = pipeline.length ? sec(`In the pipeline (${pipeline.length})`, `<div class="rd-cards">${pipeline.slice(0, 60).map(libCard).join("")}</div>`) : "";
  return head + runSec + pipeSec + note("N=1 instrument. “Running now” are live on the ledger; the pipeline is the experiment library — candidates not yet run.");
}
async function renderHabits(d) {
  const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const a = d.day_of_week_avgs || [];
  const mx = Math.max(1, ...a);
  const reg = await tryJSON("/api/habit_registry");
  const habits = (reg && reg.habits) || [];
  const groups = (reg && reg.groups) || [];
  const head = figs([fig(d.current_streak ?? 0, "day streak"), fig(d.days_tracked ?? 0, "days tracked"), habits.length ? fig(habits.length, "habits tracked") : "", d.keystone_group ? fig(`${esc(d.keystone_group)} ${d.keystone_group_pct ?? ""}%`, "most-held group") : ""]);
  const dow = a.length ? sec("Adherence by day of week", `<div class="hb-chart">${a.map((v, i) => `<div class="hb-col"><span class="hb-bar" style="height:${Math.max(4, (v / mx) * 100)}%"></span><span class="hb-day label">${dows[i] || ""}</span></div>`).join("")}</div>`) : "";
  let list = empty("Habit list loading from Habitify.");
  if (habits.length) {
    const order = groups.length ? groups : [...new Set(habits.map((h) => h.group || "Other"))];
    const body = order.map((g) => { const hs = habits.filter((h) => (h.group || "Other") === g); if (!hs.length) return ""; return `<h4 class="hb-group label">${esc(g)} <span class="rd-unit">${hs.length}</span></h4><table class="rd-tbl"><tbody>${hs.map((h) => `<tr><td class="rd-name">${esc(h.name)}</td><td class="num rd-range">${esc(h.frequency || "daily")}</td></tr>`).join("")}</tbody></table>`; }).join("");
    list = sec(`Habits I'm tracking (${habits.length})`, body);
  }
  // Last 7 days as a day-of-week color grid: green = mostly hit, amber = partial, red = miss.
  const hist = (d.history || []).slice(-7);
  const _dl = (ds) => ["S", "M", "T", "W", "T", "F", "S"][new Date(ds + "T00:00:00").getDay()] || "";
  const _hc = (p) => (p >= 80 ? "hb7-good" : p >= 50 ? "hb7-mid" : "hb7-miss");
  const grid = hist.length
    ? sec(
        "Last 7 days",
        `<div class="hb7">${hist
          .map(
            (h) =>
              `<div class="hb7-cell ${_hc(h.tier0_pct || 0)}" title="${esc(h.date || "")} · ${fmt(h.tier0_pct)}%"><span class="hb7-dow label">${_dl(h.date || "")}</span><span class="hb7-pct num">${fmt(h.tier0_pct)}</span></div>`,
          )
          .join("")}</div>`,
      )
    : "";
  // Adherence trend (the long-run consistency story the 7-cell grid only hinted at).
  const trend = (d.history || []).length ? sec("Adherence trend", lineChart(d.history, { valueKey: "tier0_pct", unit: "%", label: "Daily Tier-0 adherence", emptyMsg: "The adherence curve fills as days accrue." })) : "";
  // The signature panel: which habit groups actually track with the day grade (correlative, N=1).
  const kc = (d.keystone_correlations || []).map((c) => ({ label: c.group, r: c.correlation_r, n: c.n_days }));
  const corr = kc.length ? sec("Which habits move the needle", correlationChip(kc, { label: "Habit group ↔ day grade", outcome: "the day grade" })) : "";
  // Completion by group (the per-group averages the page computed but never showed).
  const ga = Object.entries(d.group_90d_avgs || {}).map(([g, p]) => ({ label: g, value: p })).sort((x, y) => y.value - x.value);
  const groupBars = ga.length ? sec("Completion by group", barChart(ga, { valueKey: "value", labelKey: "label", label: "Avg completion %" })) : "";
  return head + corr + trend + grid + dow + groupBars + list + note("Everything I'm trying to do — sourced from Habitify. Correlations are N=1, not cause. Private habits are never shown.");
}
// The board — pick an expert, read their actual per-domain take + track record.
async function renderBoard(d) {
  const coaches = d.coaches || []; const wp = d.weekly_priority || {};
  const chair = wp.text && !isBad(wp.text)
    ? `<div class="rd-obs"><p class="board-kicker label">the integrator's weekly read · ${esc(wp.coach_name || "")}</p><p class="rd-primary">${esc(wp.text)}</p></div>`
    : `<div class="rd-obs"><p class="rd-primary">The board's weekly read posts after the next briefing.</p></div>`;
  const roster = coaches.length
    ? `<div class="coach-grid">${coaches.map((c) => `<button class="coach coach-pick" data-coach="${esc(c.coach_id)}" data-name="${esc(c.name)}" data-title="${esc(c.title || "")}" style="--coach:${/^#|rgb/.test(c.color || "") ? c.color : "var(--ember)"}"><span class="coach-badge">${esc(c.initials || (c.name || "?").slice(0, 2))}</span><div><h3 class="coach-name">${esc(c.name)}</h3><p class="coach-title label">${esc(c.title || "")}</p></div></button>`).join("")}</div>`
    : empty("The expert board is being assembled.");
  return chair + sec("The experts — pick one to read their take", roster) +
    `<div class="coach-read" data-board-read></div>` +
    note("A board of named AI characters who argue about the data. Interpretation, not instruction.");
}
function renderPlatform(d) { return figs([fig(d.data_sources, "data sources (incl. derived)"), fig(d.mcp_tools, "MCP tools"), fig(d.lambdas, "lambdas"), fig(d.cdk_stacks, "CDK stacks")]) + sec("By the numbers", kvtable({ adrs: d.adrs, review_grade: d.review_grade, site_pages: d.site_pages })) + note("Built with Claude + the wearables already on his body — not a million-dollar lab. The full architecture (alarms, tests, the deeper counts) lives in the build write-up; this page keeps the human-legible ones."); }
function renderCost(d) { return figs([fig("$" + String(d.monthly_cost || "").replace("$", ""), "per month"), fig("$75", "hard ceiling")]) + `<p class="rd-archive">The whole platform runs for about ${esc(d.monthly_cost || "$20")}/month against a self-imposed $75 hard ceiling (ADR-063). Radical accessibility is the point: an ordinary person did this with a model and consumer wearables, not a lab.</p>` + note("Cost is the receipt for 'you could do this too.'"); }
function renderData(d) { const src = d.sources || []; if (!src.length) return empty("Data-source registry unavailable."); const by = {}; for (const s of src) (by[s.category || "other"] ||= []).push(s); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><tbody>${rows.map((s) => `<tr><td class="rd-name">${esc(s.name)}</td><td>${esc(s.metrics || "")}</td><td class="rd-range">${esc(s.method || "")}</td></tr>`).join("")}</tbody></table>`)).join(""); return figs([fig(src.length, "sources catalogued")]) + secs + note(`The full catalogue (live + manual + derived). The Pipeline page shows which are actively monitored right now${d._meta && d._meta.updated ? ` · updated ${esc(d._meta.updated)}` : ""}.`); }
/* ── PG-14 Tier-A: "the data figure" ──────────────────────────────────────────
   A faceless, monochrome body silhouette whose girth is a *direct function* of
   the real weight number (start → current → goal). No photo, no face, nothing
   generated or guessed — it moves only when the measured number moves. Honest
   (Henning standard), privacy-safe, on-brand. Productionised from spikes/pg14_ai_me
   (PG-14, ADR-078 Wedge-B). Fill = var(--ink) so it adapts to light/dark. */
const DF_CX = 150, DF_CROTCH = 372, DF_FOOT = 606;
const DF_NECK = [[100, 16, 9], [135, 54, 14], [188, 47, 30], [250, 35, 64], [306, 52, 42], [350, 42, 26]];
const DF_LEG_OUT = [[470, 32, 12], [582, 23, 8]], DF_LEG_IN = [[582, 9, 5], [470, 15, 6]];
const DF_FOOT_OUT = [27, 8], DF_FOOT_IN = [11, 0];
const dfHalf = (lm, g) => lm[1] + lm[2] * g;
function dfSmooth(pts) {
  if (pts.length < 3) return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}
function dfBody(g) {
  const right = [[DF_CX + dfHalf(DF_NECK[0], g), DF_NECK[0][0]]];
  for (const lm of DF_NECK) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  for (const lm of DF_LEG_OUT) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  right.push([DF_CX + DF_FOOT_OUT[0] + DF_FOOT_OUT[1] * g, DF_FOOT]);
  right.push([DF_CX + DF_FOOT_IN[0] + DF_FOOT_IN[1] * g, DF_FOOT]);
  for (const lm of DF_LEG_IN) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  right.push([DF_CX, DF_CROTCH]);
  const left = right.slice(0, -1).reverse().map(([x, y]) => [2 * DF_CX - x, y]);
  return dfSmooth(right.concat(left)) + " Z";
}
function dataFigure(j) {
  const start = Number(j.start_weight_lbs), goal = Number(j.goal_weight_lbs), now = Number(j.current_weight_lbs);
  if (!isFinite(start) || !isFinite(goal) || !isFinite(now) || start === goal) return "";
  const lost = Number(j.lost_lbs);
  const moved = isFinite(lost) ? (lost > 0.05 ? `down ${fmt(Math.abs(lost))} lb` : (lost < -0.05 ? `up ${fmt(Math.abs(lost))} lb` : "even")) : "";
  const ms = [[start, "start"], [now, "now"], [Math.round((start + goal) / 2), ""], [goal, "goal"]]
    .filter(([w], i, a) => a.findIndex(([x]) => Math.round(x) === Math.round(w)) === i);
  return `<section class="rd-sec df-sec" data-df data-start="${start}" data-goal="${goal}" data-now="${now}">
    <h2 class="rd-h">The figure, drawn from the numbers</h2>
    <div class="df-stage">
      <svg class="df-svg" viewBox="0 0 300 620" role="img" aria-label="A stylised body silhouette that slims as the weight number falls from ${Math.round(start)} toward ${Math.round(goal)} lb">
        <circle class="df-fig" data-df-head cx="150" cy="64" r="32"></circle>
        <path class="df-fig" data-df-body d=""></path>
      </svg>
    </div>
    <div class="df-readout">
      <div class="df-weight"><span data-df-w class="num">${Math.round(now)}</span><small>lb</small></div>
      <div class="df-togoal"><span class="label">to goal</span><span data-df-tg class="num">—</span></div>
    </div>
    <input class="df-scrub" data-df-scrub type="range" min="0" max="1" step="0.001" value="0" aria-label="Scrub the figure between start and goal weight">
    <div class="df-axis"><span class="label">${Math.round(start)} start</span><span class="label">${Math.round(goal)} goal</span></div>
    <div class="df-buttons">${ms.map(([w, lbl]) => `<button class="df-btn" data-df-to="${w}">${lbl ? lbl + " · " : ""}${Math.round(w)}</button>`).join("")}<button class="df-btn df-play" data-df-play>▶ morph</button></div>
    <p class="rd-why df-note"><strong>A representative figure, not a photo.</strong> The silhouette's girth is a direct function of the real measured weight — heaviest at ${Math.round(start)}, leanest at ${Math.round(goal)} — with no face, no identity, and nothing generated or guessed. It moves only when the actual number moves${moved && moved !== "even" ? ` (currently ${moved} from the start)` : ""}.</p>
  </section>`;
}

async function renderResults(d) { const j = d.journey || d; const wp = await tryJSON("/api/weight_progress"); const chart = sec("Weight trajectory", lineChart((wp && wp.weight_progress) || [], { valueKey: "weight_lbs", goal: j.goal_weight_lbs, unit: " lb", label: "Weight · recent readings", emptyMsg: "Weight trajectory fills as weigh-ins accrue." })); const lost = j.lost_lbs != null ? Number(j.lost_lbs) : null; const wdir = lost == null ? "" : (lost < -0.05 ? "up" : (Math.abs(lost) <= 0.05 ? "even" : "down")); return dataFigure(j) + chart + figs([lost != null && fig(dualWeight(Math.abs(lost), "lb"), wdir), j.current_weight_lbs != null && fig(dualWeight(j.current_weight_lbs, "lb"), "today"), j.progress_pct != null && fig(fmt(j.progress_pct) + "%", "to goal"), j.projected_goal_date && fig(j.projected_goal_date, "projected goal")]) + `<p class="rd-archive">The headline outcome is weight, but the real results live in the mechanisms — see Experiments for what's confirmed, Bloodwork for what changed inside, and the Story for the arc.</p>` + note("Correlative projection — not a promise."); }
function renderTools(d) { return figs([fig(d.mcp_tools ?? "—", "MCP tools"), fig(d.data_sources ?? "—", "data sources")]) + `<p class="rd-archive">The tools Claude uses to read this data back — spanning sleep, training, nutrition, labs, CGM, the character sheet, the board, correlations and more. They're how a conversation with the data is possible at all.</p>` + note("The interface between the model and the measured life."); }
// Post-mortems — what each closed cycle taught, derived live from the record.
async function renderPostmortems(d) {
  const cc = await tryJSON("/api/cycle_compare");
  const byN = {};
  for (const c of (cc && cc.cycles) || []) byN[c.cycle] = c;
  const closed = (d.cycles || []).filter((c) => !c.is_current);
  if (!closed.length) return empty("No closed cycles yet — post-mortems write themselves at each reset.");
  const cards = closed.map((c) => {
    const m = byN[c.cycle] || {};
    const fate = c.collapse_day ? `Engagement collapsed on day ${fmt(c.collapse_day)} — ${esc(d.collapse_definition || "")}.`
      : "Re-anchored while still engaged (administrative reset, not a collapse).";
    const next = (d.cycles || []).find((x) => x.cycle === c.cycle + 1);
    const changed = next ? `Restarted ${esc(next.genesis)} as cycle ${fmt(next.cycle)}.` : "";
    return sec(`Cycle ${fmt(c.cycle)} — ${esc(c.genesis)}, ${fmt(c.window_days)} days`,
      `<p class="rd-prose">${fate} Showed up ${fmt(c.engaged_days)} of ${fmt(c.window_days)} days.` +
      (m.weight_delta_lbs != null ? ` First-window weight: ${m.weight_delta_lbs > 0 ? "+" : ""}${fmt(m.weight_delta_lbs)} lb from ${fmt(m.weight_start_lbs)} lb.` : "") +
      (m.avg_recovery_pct != null ? ` Avg recovery ${fmt(m.avg_recovery_pct)}%.` : "") +
      (m.avg_sleep_hours != null ? ` Avg sleep ${fmt(m.avg_sleep_hours)}h.` : "") +
      ` ${changed}</p>` +
      `<p class="rd-meta label">strip: <span class="sv-strip">${esc(c.strip)}</span></p>`);
  }).join("");
  return cards + `<p class="correlative">Derived live from the engagement and comparison records — nothing curated, nothing deleted. The restarts are part of the experiment, not failures of it.</p>`;
}


// The Survival Curve — engagement strips per cycle + loudly-caveated odds.
function renderSurvival(d) {
  const head = figs([
    fig(`${fmt(d.p_reach_30_pct)}%`, `odds of reaching day ${fmt(d.horizon_days)}`),
    fig(fmt(d.current_silent_days), "silent days right now"),
  ]);
  const rows = (d.cycles || []).map((c) => {
    const fate = c.is_current ? `day ${fmt(c.window_days)} · live`
      : c.collapse_day ? `collapsed day ${fmt(c.collapse_day)}`
      : c.censored ? "re-anchored while engaged" : "survived window";
    return `<tr class="${c.is_current ? "rd-flagmark" : c.collapse_day ? "rd-flag" : ""}"><td class="rd-name">cycle ${esc(String(c.cycle))}</td><td class="num">${esc(c.genesis)}</td><td class="sv-strip">${esc(c.strip)}</td><td class="num">${fmt(c.engaged_days)}/${fmt(c.window_days)}</td><td>${esc(fate)}</td></tr>`;
  }).join("");
  return head +
    sec("Engagement, day by day (█ showed up · — silent)", `<table class="rd-tbl"><thead><tr><th>cycle</th><th>genesis</th><th>the strip</th><th>engaged</th><th>fate</th></tr></thead><tbody>${rows}</tbody></table>`) +
    `<p class="rd-archive">Collapse = ${esc(d.collapse_definition || "")}. Method: ${esc(d.method || "")}</p>` +
    `<p class="correlative">${esc(d.note || "")} <span class="confidence conf-low">${esc(d.confidence || "")}</span></p>`;
}


// The mirror — visitor's numbers vs the experiment's distributions. Pure
// client-side: nothing is sent, stored, or logged.
function renderMirror(d) {
  const hist = (d && d.pulse_history) || [];
  const series = (k) => hist.map((h) => h[k]).filter((v) => typeof v === "number");
  const DIMS = [
    ["sleep_hours", "Sleep last night (hours)", "h", 0.1],
    ["steps", "Steps yesterday", "", 100],
    ["recovery_pct", "Recovery this morning (%)", "%", 1],
  ];
  const inputs = DIMS.map(([k, label, , step]) => {
    const s_ = series(k);
    return `<div class="mi-row"><label class="label" for="mi-${k}">${esc(label)}</label>` +
      `<input id="mi-${k}" class="ask-in mi-in" type="number" step="${step}" data-mi="${k}" ${s_.length ? "" : "disabled"}>` +
      `<span class="mi-out" data-mi-out="${k}">${s_.length ? "" : "no data yet"}</span></div>`;
  }).join("");
  setTimeout(() => {
    document.querySelectorAll(".mi-in").forEach((inp) => inp.addEventListener("input", () => {
      const k = inp.dataset.mi, v = parseFloat(inp.value);
      const out = document.querySelector(`[data-mi-out="${k}"]`);
      const s_ = series(k);
      if (!out || !s_.length || !isFinite(v)) { if (out) out.textContent = ""; return; }
      const pct = Math.round(s_.filter((x) => x < v).length / s_.length * 100);
      out.textContent = `beats ${pct}% of Matthew's last ${s_.length} days`;
    }));
  }, 0);
  return `<p class="rd-lede">Where would your day sit inside this experiment? Type a number — the comparison runs in your browser against the last ${fmt(hist.length)} days of the record. Nothing you type is sent, stored, or seen.</p>` +
    sec("Your numbers vs the record", `<div class="mi-grid">${inputs}</div>`) +
    `<p class="correlative">A mirror, not a benchmark — this is one person's distribution, N=1. For population reference ranges, see Benchmarks.</p>`;
}


// The Wrong Page — the AI's misses, uncurated.
function renderWrong(d) {
  const v = d.validator || {}, pr = d.predictions || {};
  const head = figs([
    fig(fmt(v.claims_checked), "claims audited"),
    fig(fmt(v.caught), "caught wrong"),
    fig(fmt((pr.refuted_recent || []).length), "predictions refuted"),
  ]);
  const cr = (v.recent || []).map((c) =>
    `<tr class="${c.severity === "error" ? "rd-flag" : ""}"><td class="rd-name">${esc(String(c.date || "").slice(0, 10))}</td><td>${esc(c.coach || "")}</td><td>${esc(c.what)}</td></tr>`).join("");
  const caught = cr
    ? sec("Caught by the validator — claims the data contradicted", `<table class="rd-tbl"><thead><tr><th>date</th><th>coach</th><th>what was wrong</th></tr></thead><tbody>${cr}</tbody></table>`)
    : sec("Caught by the validator", `<p class="rd-archive">No catches in the window — every audited claim matched the data it cited.</p>`);
  const lr = (pr.by_coach || []).map((c) =>
    `<tr><td class="rd-name">${esc(c.coach)}</td><td class="num">${fmt(c.confirmed)}</td><td class="num">${fmt(c.refuted)}</td><td class="num">${fmt(c.inconclusive)}</td><td class="num">${fmt(c.expired)}</td></tr>`).join("");
  const ledger = lr
    ? sec("The prediction ledger — every dated call, scored", `<table class="rd-tbl"><thead><tr><th>coach</th><th>confirmed</th><th>refuted</th><th>inconclusive</th><th>expired</th></tr></thead><tbody>${lr}</tbody></table>`)
    : "";
  const mr = (pr.refuted_recent || []).map((m) =>
    `<tr class="rd-flag"><td class="rd-name">${esc(String(m.date || "").slice(0, 10))}</td><td>${esc(m.coach)}</td><td>${esc(m.what)}</td></tr>`).join("");
  const misses = mr ? sec("Refuted predictions", `<table class="rd-tbl"><thead><tr><th>date</th><th>coach</th><th>the call</th></tr></thead><tbody>${mr}</tbody></table>`) : "";
  return head + caught + ledger + misses + `<p class="correlative">${esc(d.note || "")}</p>`;
}


// The inference receipt — every AI call priced, the meter behind the $75 cap.
function renderInference(d) {
  const head = figs([
    d.ai_month_to_date_usd != null && fig(`$${fmt(d.ai_month_to_date_usd)}`, "AI spend MTD"),
    fig(`$${fmt(d.budget_ceiling_usd)}`, "hard ceiling (all-in)"),
    d.budget_tier != null && fig(String(d.budget_tier), "budget tier (0–3)"),
  ]);
  const mrows = (d.models || []).map((m) =>
    `<tr><td class="rd-name">${esc(m.model)}</td><td class="num">${fmt(m.today.input_tokens)} / ${fmt(m.today.output_tokens)}</td><td class="num">$${fmt(m.today.est_cost_usd)}</td><td class="num">${fmt(m.month.input_tokens)} / ${fmt(m.month.output_tokens)}</td><td class="num">$${fmt(m.month.est_cost_usd)}</td></tr>`).join("");
  const models = mrows ? sec("By model", `<table class="rd-tbl"><thead><tr><th>model</th><th>today in/out</th><th>today $</th><th>month in/out</th><th>month $</th></tr></thead><tbody>${mrows}</tbody></table>`) : "";
  const frows = (d.features || []).slice(0, 14).map((f) =>
    `<tr><td class="rd-name">${esc(f.lambda)}</td><td class="num">${fmt(f.month_input_tokens)}</td><td class="num">${fmt(f.month_output_tokens)}</td></tr>`).join("");
  const features = frows ? sec("By feature (month-to-date tokens)", `<table class="rd-tbl"><thead><tr><th>lambda</th><th>input</th><th>output</th></tr></thead><tbody>${frows}</tbody></table>`) : "";
  return head + models + features + `<p class="correlative">${esc(d.note || "")}</p>`;
}


// Cycle vs cycle — matched first-K-days windows across experiment restarts.
function renderCycles(d) {
  const cs = d.cycles || [];
  if (!cs.length) return empty("Cycle comparison fills in once a restart has data to compare.");
  const K = d.window_days;
  const rows = [
    ["Genesis", (c) => c.genesis],
    ["Start weight", (c) => c.weight_start_lbs != null ? `${fmt(c.weight_start_lbs)} lb` : "—"],
    [`Weight change (first ${K}d)`, (c) => c.weight_delta_lbs != null ? `${c.weight_delta_lbs > 0 ? "+" : ""}${fmt(c.weight_delta_lbs)} lb` : "—"],
    ["Avg recovery", (c) => c.avg_recovery_pct != null ? `${fmt(c.avg_recovery_pct)}%` : "—"],
    ["Avg sleep", (c) => c.avg_sleep_hours != null ? `${fmt(c.avg_sleep_hours)} h` : "—"],
    ["Days with data", (c) => fmt(c.days_with_data)],
  ];
  const head = `<tr><th></th>${cs.map((c) => `<th>cycle ${esc(String(c.cycle))}${c.is_current ? " · now" : ""}</th>`).join("")}</tr>`;
  const body = rows.map(([lbl, f]) => `<tr><td class="rd-name">${esc(lbl)}</td>${cs.map((c) => `<td class="num${c.is_current ? " rd-flagmark" : ""}">${f(c)}</td>`).join("")}</tr>`).join("");
  return sec(`The same first ${K} days, every restart`, `<table class="rd-tbl"><thead>${head}</thead><tbody>${body}</tbody></table>`) +
    `<p class="correlative">${esc(d.note || "")}</p>`;
}


function renderGeneric(d, t) { const root = (t && t.root && d[t.root]) ? d[t.root] : d; const scal = Object.entries(root).filter(([k, v]) => !k.startsWith("_") && ["string", "number", "boolean"].includes(typeof v)); let arr = null, key = null; for (const [k, v] of Object.entries(root)) if (Array.isArray(v) && v.length && typeof v[0] === "object") { arr = v; key = k; break; } let tbl = ""; if (arr) { const cols = [...new Set(arr.flatMap((r) => Object.keys(r)))].filter((c) => !c.startsWith("_")).slice(0, 5); tbl = sec(key, `<table class="rd-tbl"><thead><tr>${cols.map((c) => `<th>${esc(ttl(c))}</th>`).join("")}</tr></thead><tbody>${arr.slice(0, 40).map((r) => `<tr>${cols.map((c) => `<td class="num">${esc(fmt(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`); } if (!scal.length && !tbl) return empty("No data published for this section yet — it fills from the live pipeline."); return figs(scal.slice(0, 4).map(([k, v]) => fig(fmt(v), ttl(k)))) + tbl + note("Correlative read only."); }

/* Interactive: Ask the data + Explorer (wired after insert) */
const ASK_CHIPS = [
  "How's the sleep trending lately?",
  "What predicts good recovery days?",
  "Is the weight loss on track?",
  "What foods spike the glucose most?",
  "Any signs of overtraining?",
  "What changed in the data this week?",
];
function renderAsk() {
  return `<form class="ask-form" data-ask>` +
    `<label class="label" for="askq">Ask a question of the experiment's data</label>` +
    `<div class="ask-row"><input id="askq" class="ask-in" type="text" placeholder="e.g. how does my sleep affect recovery?" autocomplete="off" maxlength="300"><button class="ask-btn" type="submit">Ask</button></div>` +
    `</form>` +
    `<div class="ask-chips" aria-label="Suggested questions">${ASK_CHIPS.map((q) => `<button type="button" class="ask-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` +
    `<div class="ask-out" data-ask-out aria-live="polite"></div>` +
    note("Answers are AI-generated from the published data — correlative, never medical advice. Rate-limited (5/hour), and may be paused by the budget guard.");
}
function renderExplorer(d) { const v = (d.vitals && d.vitals.vitals) || d.vitals || {}; const ch = (d.character && d.character.character) || {}; const j = (d.journey && d.journey.journey) || d.journey || {}; const rows = { weight_lbs: j.current_weight_lbs, character_level: ch.level, ...Object.fromEntries(Object.entries(v).filter(([k, x]) => ["string", "number"].includes(typeof x)).slice(0, 12)) }; return `<p class="rd-archive">Today's raw record, straight from the pipeline. For the full historical day-by-day browser, open the preserved Explorer below.</p>` + sec("Today", kvtable(rows)) + note("The unfiltered daily record."); }

// Live Pulse — current status narrative + daily vitals trends (the old /live).
async function renderPulse(d) {
  const p = d.pulse || d;
  const ph = await tryJSON("/api/pulse_history"); const hist = (ph && ph.pulse_history) || [];
  const head = `<div class="rd-obs">${p.narrative && !isBad(p.narrative) ? `<p class="rd-primary">${esc(p.narrative)}</p>` : `<p class="rd-primary">Today's pulse is being read.</p>`}<p class="rd-meta label">${[p.date, p.status, p.signals_reporting != null && `${p.signals_reporting}/${p.signals_total} signals reporting`].filter(Boolean).map(esc).join("  ·  ")}</p></div>`;
  const series = (k) => hist.map((h) => ({ date: h.date, value: h[k] })).filter((x) => x.value != null);
  const trendBlock = (defs) => defs
    .map(([k, lbl]) => sec(lbl, lineChart(series(k), { valueKey: "value", label: lbl, emptyMsg: `The ${lbl.toLowerCase()} trend fills in as days accrue.` }))).join("");
  // Group by temporal frame: recovery/sleep/HRV are about LAST NIGHT (they set
  // today up); weight & steps are same-day. Different frames, labelled so a reader
  // doesn't read last night's recovery as a "today" activity number.
  const lastNight = trendBlock([["recovery_pct", "Recovery %"], ["hrv_ms", "HRV ms"], ["rhr_bpm", "Resting HR"], ["sleep_hours", "Sleep hours"]]);
  const today = trendBlock([["weight_lbs", "Weight"], ["strain", "Day strain"], ["steps", "Steps"]]);
  const frame = (lbl, inner) => `<p class="rd-frame label">${esc(lbl)}</p>${inner}`;
  return head + frame("Last night → sets up today", lastNight) + frame("Today — measured same-day", today) +
    note("Your live vitals — recovery/sleep/HRV read last night; weight & steps are today.");
}

function renderPipeline(d) {
  const src = d.sources || [];
  if (!src.length) return empty("Pipeline status unavailable — check back shortly.");
  const sm = d.summary || {};
  const rank = { fresh: 0, "behavioral-stale": 1, stale: 2, unknown: 3, paused: 4 };
  const badge = { fresh: "● flowing", "behavioral-stale": "○ awaiting log", stale: "▲ stale", paused: "⏸ paused", unknown: "– unknown" };
  const flagCls = (s) => (s === "stale" || s === "unknown") ? "rd-flag" : "";
  const by = {};
  for (const s of src) (by[s.category || "Other"] ||= []).push(s);
  const secs = Object.entries(by).map(([cat, rows]) => sec(cat,
    `<table class="rd-tbl"><thead><tr><th>source</th><th>what it feeds</th><th>last update</th><th>status</th></tr></thead><tbody>${rows
      .slice().sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9))
      .map((s) => `<tr class="${flagCls(s.status)}"><td class="rd-name">${esc(s.label)}</td><td>${esc(s.desc || "")}</td><td class="num rd-range">${esc(s.last_update || "—")}${s.age_hours != null ? ` <span class="rd-unit">${Math.round(s.age_hours)}h</span>` : ""}</td><td>${esc(badge[s.status] || s.status)}</td></tr>`).join("")}</tbody></table>`)).join("");
  return figs([fig(sm.fresh ?? "—", "flowing"), fig(sm.paused ?? "—", "paused"), fig(sm.total ?? src.length, "live-monitored")]) + secs +
    `<p class="correlative">Live pipeline status — fresh = flowing on schedule, paused = intentionally off, awaiting-log = a manual entry not yet made.</p>`;
}

// Intelligence — the weekly correlation matrix (Pearson r + BH-FDR), strongest first.
function renderCorrelations(d) {
  const c = d && d.correlations;
  const obj = (c && !Array.isArray(c)) ? c : {};
  const pairs = obj.pairs || [];
  if (!pairs.length) return empty("No correlations yet — and that's the honest state, not a broken pipeline. The experiment is freshly anchored to its current genesis, and the weekly matrix only computes once there are ~2+ weeks of overlapping daily data. An empty matrix means the sample is still too small to claim a pattern; it fills in as the days accrue.");
  const sig = pairs.filter((p) => p.fdr_significant).length;
  const head = figs([fig(obj.count ?? pairs.length, "pairs"), sig ? fig(sig, "FDR-significant") : "", obj.week && fig(obj.week, "week")]);
  const rows = pairs.slice(0, 30).map((p) => `<tr class="${p.fdr_significant ? "rd-flag" : ""}"><td class="rd-name">${esc(p.label_a || p.metric_a)} <span class="rd-unit">↔</span> ${esc(p.label_b || p.metric_b)}</td><td class="num">${fmt(p.r, 2)}</td><td class="num rd-range">${fmt(p.p, 3)}</td><td class="num">${fmt(p.n)}</td><td>${p.fdr_significant ? `<span class="rd-flagmark">FDR ✓</span>` : esc(p.strength || "")}</td></tr>`).join("");
  const tbl = sec("Correlation matrix — strongest first", `<table class="rd-tbl"><thead><tr><th>pair</th><th>r</th><th>p</th><th>n</th><th>significance</th></tr></thead><tbody>${rows}</tbody></table>`);
  return head + tbl + (obj.methodology ? `<p class="rd-desc">${esc(obj.methodology)}</p>` : "") + note("Correlative only — Pearson r with Benjamini-Hochberg FDR control across all pairs. Never causal.");
}
// Predictions — the coaches' forward calls, scored against measured outcomes.
function renderPredictions(d) {
  const o = (d && d.overall) || {};
  const list = (d && d.predictions) || [];
  const resolved = (o.confirmed || 0) + (o.refuted || 0);
  if (!(o.total > 0) && !list.length) return empty("No scored predictions yet — the prediction ledger restarts with each genesis rather than carrying old scores forward. Coaches log forward calls that get auto-graded against measured outcomes as target dates pass, so the track record rebuilds honestly from day one. It fills in as the first calls come due.");
  const head = figs([fig(o.total ?? 0, "predictions"), o.confirmed != null && fig(o.confirmed, "confirmed"), o.refuted != null && fig(o.refuted, "refuted"), o.pending != null && fig(o.pending, "pending"), resolved > 0 && fig(fmt(o.accuracy_pct) + "%", "accuracy")]);
  const badge = (s) => s === "confirmed" ? "rd-badge-live" : "";
  const rows = list.slice(0, 40).map((p) => `<tr><td class="rd-name">${esc(p.coach_name || p.coach_id)}</td><td>${esc(p.text)}</td><td><span class="rd-badge ${badge(p.status)}">${esc(p.status)}</span></td><td class="num rd-range">${esc(p.date || "")}</td></tr>`).join("");
  const tbl = list.length ? sec("The prediction ledger", `<table class="rd-tbl"><thead><tr><th>coach</th><th>call</th><th>verdict</th><th>made</th></tr></thead><tbody>${rows}</tbody></table>`) : "";
  return head + tbl + note("Forward calls logged, then scored against reality — the coaches' track record, kept honest.");
}
// Benchmarks — where the numbers sit vs age-band + centenarian-decathlon targets.
function renderBenchmarks(d) {
  const trends = (d && d.trends) || (Array.isArray(d) ? d : []);
  if (!trends.length) return empty("No benchmark readouts yet — these place your current numbers against age-band and centenarian-decathlon targets, and they re-populate from the current genesis as each metric accrues enough post-reset readings to be worth showing. An empty board is the experiment starting fresh, not a gap in the data. Direction, not destiny.");
  const rows = trends.slice(0, 40).map((t) => {
    const name = t.metric || t.name || t.label || t.sk || "—";
    const cur = t.current ?? t.value ?? t.current_value;
    const tgt = t.target ?? t.target_value ?? t.centenarian_target;
    const band = t.age_band ?? t.band ?? t.percentile;
    return `<tr><td class="rd-name">${esc(ttl(String(name).replace(/^.*#/, "")))}</td><td class="num">${fmt(cur)}</td><td class="num rd-range">${fmt(tgt)}</td><td class="num">${band != null ? esc(band) : "—"}</td></tr>`;
  }).join("");
  return figs([fig(trends.length, "benchmarks")]) + sec("Where the numbers stand", `<table class="rd-tbl"><thead><tr><th>metric</th><th>current</th><th>target</th><th>age-band</th></tr></thead><tbody>${rows}</tbody></table>`) + note("Targets are age-band and centenarian-decathlon references — direction, not destiny.");
}

const RENDERERS = {
  vitals: renderPulse, supplements: renderSupplements, labs: renderLabs, physical: renderPhysical, training: renderTraining, nutrition: renderNutrition, glucose: renderGlucose, sleep: renderSleep, mind: renderMind, vices: renderVices, ledger: renderLedger, discoveries: renderDiscoveries, biology: renderGenome, challenges: renderChallenges, protocols: renderProtocols, experiments: renderExperiments, habits: renderHabits, board: renderBoard, platform: renderPlatform, cost: renderCost, data: renderData, pipeline: renderPipeline, results: renderResults, tools: renderTools, ask: renderAsk, cycles: renderCycles, inference: renderInference, wrong: renderWrong, survival: renderSurvival, postmortems: renderPostmortems, mirror: renderMirror, explorer: renderExplorer, intelligence: renderCorrelations, predictions: renderPredictions, benchmarks: renderBenchmarks };
const WIRE = {
  ask: () => {
    const f = document.querySelector("[data-ask]");
    if (!f) return;
    const input = f.querySelector(".ask-in");
    const btn = f.querySelector(".ask-btn");
    const out = document.querySelector("[data-ask-out]");
    const history = [];  // last 3 Q/A pairs → follow-ups have context server-side
    const submit = async () => {
      const q = input.value.trim();
      if (!q || btn.disabled) return;
      btn.disabled = true;
      input.value = "";
      // Thread, not replace: each exchange appends so a visitor can follow up.
      out.insertAdjacentHTML("beforeend",
        `<div class="ask-turn"><p class="ask-q"><span class="label">you</span>${esc(q)}</p><p class="ask-answer is-pending"><span class="shimmer">Reading the data…</span></p></div>`);
      const slot = out.lastElementChild.querySelector(".ask-answer");
      slot.scrollIntoView({ behavior: "smooth", block: "nearest" });
      try {
        const r = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q, history: history.slice(-3) }) });
        const d = await r.json().catch(() => ({}));
        const ans = d.answer || d.response || d.text || "";
        if (r.status === 429) {
          slot.outerHTML = `<p class="rd-archive">Hourly question limit reached — it resets within the hour. <a href="/subscribe/">Subscribers</a> get a higher limit.</p>`;
        } else if (ans && !isBad(ans)) {
          history.push({ q, a: ans });
          slot.outerHTML = `<p class="ask-answer"><span class="label">the platform</span>${esc(ans)}</p>`;
        } else {
          slot.outerHTML = `<p class="rd-archive">The data Q&amp;A is paused right now (budget guard) — try again later, or browse the Evidence directly.</p>`;
        }
      } catch (x) {
        slot.outerHTML = `<p class="rd-archive">Couldn't reach the Q&amp;A service just now.</p>`;
      }
      btn.disabled = false;
      input.focus();
    };
    f.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    document.querySelectorAll(".ask-chip").forEach((c) => c.addEventListener("click", () => { input.value = c.dataset.q; submit(); }));
  },
  board: () => {
    const picks = [...document.querySelectorAll(".coach-pick")];
    if (!picks.length) return;
    const load = async (btn) => {
      picks.forEach((p) => p.classList.toggle("is-active", p === btn));
      const id = btn.dataset.coach, name = btn.dataset.name, title = btn.dataset.title;
      const out = document.querySelector("[data-board-read]");
      out.innerHTML = `<p class="rd-archive"><span class="shimmer">Reading ${esc(name)}…</span></p>`;
      const [an, tl] = await Promise.all([tryJSON(`/api/coach_analysis?domain=${encodeURIComponent(id)}`), tryJSON(`/api/coach_timeline?coach_id=${encodeURIComponent(id)}`)]);
      const analysis = an && an.analysis; const ms = (tl && tl.milestones) || [];
      out.innerHTML = `<div class="coach-detail"><p class="dx-kicker label">${esc(title)} · ${esc(name)}</p>` +
        (analysis && !isBad(analysis) ? `<p class="rd-prose">${esc(analysis)}</p>` : `<p class="rd-archive">${esc(name)}'s read posts here as data in their domain accrues.</p>`) +
        (ms.length ? sec("Track record", `<ul class="coach-tl">${ms.slice(0, 12).map((m) => `<li><span class="label">${esc(String(m.date || "").slice(0, 10))}</span> ${esc(m.title || m.text || m.note || "")}</li>`).join("")}</ul>`) : "") +
        `</div>`;
    };
    picks.forEach((b) => b.addEventListener("click", () => load(b)));
    const start = picks.find((p) => p.dataset.coach === "training") || picks[0]; // open the lifting coach first
    if (start) load(start);
  },
  results: () => {
    const stage = document.querySelector("[data-df]");
    if (!stage) return;
    const START = parseFloat(stage.dataset.start), GOAL = parseFloat(stage.dataset.goal), NOW = parseFloat(stage.dataset.now);
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const bodyEl = stage.querySelector("[data-df-body]"), headEl = stage.querySelector("[data-df-head]");
    const wEl = stage.querySelector("[data-df-w]"), tgEl = stage.querySelector("[data-df-tg]"), scrub = stage.querySelector("[data-df-scrub]");
    const heaviness = (w) => Math.max(0, Math.min(1, (w - GOAL) / (START - GOAL)));
    function render(w) {
      const g = heaviness(w);
      bodyEl.setAttribute("d", dfBody(g));
      headEl.setAttribute("r", (29 + 6 * g).toFixed(1));
      wEl.textContent = Math.round(w);
      const toGo = Math.max(0, w - GOAL);
      tgEl.textContent = toGo <= 0 ? "reached" : "-" + Math.round(toGo) + " lb";
      scrub.value = (1 - g).toFixed(3);
    }
    scrub.addEventListener("input", () => render(START + (GOAL - START) * parseFloat(scrub.value)));
    let raf = null;
    function animateTo(target) {
      cancelAnimationFrame(raf);
      const from = START + (GOAL - START) * parseFloat(scrub.value);
      if (reduce) { render(target); return; }
      const t0 = performance.now(), dur = 900;
      (function step(t) {
        const k = Math.min(1, (t - t0) / dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        render(from + (target - from) * e);
        if (k < 1) raf = requestAnimationFrame(step);
      })(t0);
    }
    stage.querySelectorAll("[data-df-to]").forEach((b) => b.addEventListener("click", () => animateTo(parseFloat(b.dataset.to))));
    const playBtn = stage.querySelector("[data-df-play]");
    if (reduce) { playBtn.remove(); } else {
      let playing = false, ploop = null;
      playBtn.addEventListener("click", (e) => {
        playing = !playing; e.target.textContent = playing ? "❚❚ pause" : "▶ morph";
        if (playing) {
          let dir = -1, w = START; cancelAnimationFrame(raf);
          (function loop() { w += dir * 1.4; if (w <= GOAL) { w = GOAL; dir = 1; } if (w >= START) { w = START; dir = -1; } render(w); if (playing) ploop = requestAnimationFrame(loop); })();
        } else { cancelAnimationFrame(ploop); }
      });
    }
    render(NOW);   // open on the honest current state
  },
};

/* ── App shell: tabs + sidebar + center ───────────────────────────────────── */
const $ = (s) => document.querySelector(s);
let current = window.__START_SLUG__ || (REG[0] && REG[0].slug);

function buildTabs() {
  const g = BYSLUG[current] ? BYSLUG[current].group : GROUPS[0];
  $("[data-tabs]").innerHTML = GROUPS.map((grp) => `<button class="ev-tab ${grp === g ? "is-active" : ""}" data-group="${esc(grp)}">${esc(grp)}</button>`).join("");
  document.querySelectorAll(".ev-tab").forEach((b) => b.addEventListener("click", () => { const grp = b.dataset.group; const first = REG.find((t) => t.group === grp); if (first) select(first.slug); }));
}
function buildSide() {
  const g = BYSLUG[current] ? BYSLUG[current].group : GROUPS[0];
  $("[data-side]").innerHTML = REG.filter((t) => t.group === g).map((t) => `<button class="ev-tile ${t.slug === current ? "is-active" : ""}" data-slug="${esc(t.slug)}"><span class="ev-tile-t">${esc(t.title)}</span><span class="ev-tile-b">${esc(t.blurb)}</span></button>`).join("");
  document.querySelectorAll(".ev-tile").forEach((b) => b.addEventListener("click", () => select(b.dataset.slug)));
}
async function renderCenter() {
  const t = BYSLUG[current]; if (!t) return;
  const main = $("[data-main]");
  main.querySelector("[data-crumb]").innerHTML = `evidence / ${esc(t.slug)}`;
  main.querySelector("[data-title]").textContent = t.title;
  main.querySelector("[data-blurb]").textContent = t.blurb;
  const ro = main.querySelector("[data-readout]");
  const deeper = main.querySelector("[data-deeper]");
  deeper.innerHTML = "";   // no link-outs to /legacy — everything lives inline in v4 now
  if (t.mode === "editorial") { ro.innerHTML = t.editorial || empty("—"); return; }
  if (t.mode === "interactive") { ro.innerHTML = (RENDERERS[t.slug] || renderGeneric)({}, t); if (WIRE[t.slug]) WIRE[t.slug](); return; }
  if (t.mode !== "data" || !t.endpoint) { ro.innerHTML = empty(t.archive_note || "This section lives in the archive while it's rebuilt."); return; }
  ro.innerHTML = `<p class="rd-archive"><span class="shimmer">Loading ${esc(t.title)}…</span></p>`;
  try { const data = await getJSON(t.endpoint); const fn = RENDERERS[t.slug] || renderGeneric; const html = await fn(data, t); ro.innerHTML = html && html.trim() ? html : empty("No data published for this section yet."); if (WIRE[t.slug]) WIRE[t.slug](); }
  catch (e) { ro.innerHTML = empty("This readout couldn't load its data just now. The preserved view is linked below."); }
  // Only pull the viewport to the readout on MOBILE (the nav stacks above the
  // content there). On desktop the readout sits beside the sticky nav, so a smooth
  // scroll-to-top just fights the user's own scrolling — the "freezing / pulling
  // up" bug. Respect reduced-motion.
  if (matchMedia("(max-width: 819px)").matches) {
    const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    main.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
  }
}
function select(slug, push = true) {
  if (!BYSLUG[slug]) return;
  current = slug;
  if (push) history.pushState({ slug }, "", `/evidence/${slug}/`);
  document.title = `${BYSLUG[slug].title} — The Evidence — averagejoematt`;
  buildTabs(); buildSide(); renderCenter();
}
window.addEventListener("popstate", (e) => { const slug = (e.state && e.state.slug) || (location.pathname.match(/\/evidence\/([^/]+)\//) || [])[1] || (REG[0] && REG[0].slug); current = BYSLUG[slug] ? slug : current; buildTabs(); buildSide(); renderCenter(); });

function wireTheme() { const b = $(".theme-toggle"); if (!b) return; b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} }); }

wireTheme();
buildTabs();
buildSide();
renderCenter();

// Build stamp — muted deploy fingerprint in the footer (apples-to-apples in QA). Reads
// the <meta name="build"> the deploy script injects; no-op locally where it's absent.
(function () {
  try {
    const m = document.querySelector('meta[name="build"]');
    const foot = document.querySelector(".site-foot");
    if (!m || !m.content || !foot) return;
    const s = document.createElement("span");
    s.className = "build-stamp label";
    s.textContent = "build " + m.content.split(" ")[0];
    s.title = m.content;
    foot.appendChild(s);
  } catch (e) {}
})();
