/*
  evidence.js — Door 3 behaviour (/evidence/<topic>/)
  ----------------------------------------------------------------------------
  Bespoke, data-bound readouts per topic — the archival index / library-meets-
  gallery / Readout-precision treatment (Brief §5, Design System §4). Bound to
  the REAL published shapes; correlative framing; nothing invented. Renderers
  may be async (multi-endpoint). Empty domains render an honest "ready, no data
  yet" state so day-1 gaps look intentional and auto-fill as the pipeline runs.
*/

const T = window.__EVIDENCE_TOPIC__ || {};
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }
const isBad = (v) => { if (v == null) return true; const s = String(v).trim(); return s === "" || /^\[.*\]$/.test(s) || s.toUpperCase() === "N/A"; };
const has = (v) => v != null && v !== "" && !(Array.isArray(v) && !v.length);
function fmt(v, d) { if (v == null || v === "") return "—"; const n = Number(v); return Number.isFinite(n) && typeof v !== "boolean" ? (d != null ? n.toFixed(d) : (Number.isInteger(n) ? String(n) : n.toFixed(1))) : esc(v); }
const title = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const fig = (v, k, extra) => `<div class="fig"><span class="fig-v num">${esc(v)}</span><span class="fig-k label">${esc(k)}</span>${extra ? `<span class="rd-delta">${esc(extra)}</span>` : ""}</div>`;
const figs = (arr) => `<div class="figs">${arr.filter(Boolean).join("")}</div>`;
const sec = (t, inner) => inner ? `<section class="rd-sec"><h2 class="rd-h">${esc(t)}</h2>${inner}</section>` : "";
const empty = (msg) => `<p class="rd-archive">${esc(msg)}</p>`;
const note = (txt, conf) => `<p class="correlative">${txt} <span class="confidence ${conf === "ok" ? "conf-ok" : "conf-low"}">${conf === "ok" ? "" : "N=1"}</span></p>`;
function evClass(ev) { const s = String(ev || "").toLowerCase(); if (/strong|high|robust/.test(s)) return ["backed-strong", "well supported"]; if (/mod|some|emerg|mixed/.test(s)) return ["backed-some", "moderate support"]; return ["backed-thin", "preliminary"]; }
function kvtable(obj, fmtMap) { const rows = Object.entries(obj || {}).filter(([k]) => !k.startsWith("_")).map(([k, v]) => `<tr><td class="rd-name">${esc(title(k))}</td><td class="num">${esc(fmtMap && fmtMap[k] ? fmtMap[k](v) : (typeof v === "object" ? JSON.stringify(v) : fmt(v)))}</td></tr>`).join(""); return rows ? `<table class="rd-tbl"><tbody>${rows}</tbody></table>` : ""; }

/* ── Supplements — what / why / what's-backed ─────────────────────────────── */
function renderSupplements(d) {
  const g = d.groups || {};
  const head = figs([fig(d.total_count ?? Object.values(g).reduce((a, x) => a + (x.items || []).length, 0), "compounds"), d.as_of_date && fig(d.as_of_date, "as of")]);
  const secs = Object.values(g).map((grp) => {
    const cards = (grp.items || []).map((s) => { const [c, lbl] = evClass(s.ev); const pct = Math.max(4, Math.min(100, s.evPct ?? 0));
      return `<article class="supp"><header class="supp-top"><h3 class="supp-name">${esc(s.name)}</h3>${s.dose ? `<span class="supp-dose num">${esc(s.dose)}</span>` : ""}${s.timing ? `<span class="supp-timing label">${esc(s.timing)}</span>` : ""}</header>${s.why ? `<p class="supp-why">${esc(s.why)}</p>` : ""}<div class="supp-ev"><span class="supp-evlabel ${c}">${lbl}</span><span class="supp-meter"><i class="${c}" style="width:${pct}%"></i></span><span class="supp-evpct num">${s.evPct != null ? s.evPct + "%" : ""}</span></div><p class="supp-meta label">${[s.board && "src: " + esc(s.board), s.cost_monthly != null && "$" + esc(s.cost_monthly) + "/mo"].filter(Boolean).join("  ·  ")}</p></article>`; }).join("");
    return `<section class="rd-sec"><div class="rd-grouphead"><h2 class="rd-h">${esc(grp.name)}</h2>${grp.desc ? `<p class="rd-desc">${esc(grp.desc)}</p>` : ""}</div><div class="supp-grid">${cards}</div></section>`;
  }).join("");
  return head + secs + note("Evidence strength is the published research consensus — not a claim about Matthew.");
}

/* ── Labs — biomarker Readout ─────────────────────────────────────────────── */
function renderLabs(d) {
  const L = d.labs || d; const bm = L.biomarkers || [];
  if (!bm.length) return empty("No bloodwork drawn yet — panels appear here as they're added.");
  const byCat = {}; for (const b of bm) (byCat[b.category || "Other"] ||= []).push(b);
  const secs = Object.entries(byCat).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><thead><tr><th>biomarker</th><th>value</th><th>reference</th><th>flag</th></tr></thead><tbody>${rows.map((b) => { const f = b.flag && String(b.flag).toLowerCase() !== "null"; return `<tr class="${f ? "rd-flag" : ""}"><td class="rd-name">${esc(b.name)}</td><td class="num">${esc(b.value)}${b.unit ? ` <span class="rd-unit">${esc(b.unit)}</span>` : ""}</td><td class="num rd-range">${esc(b.range || "—")}</td><td>${f ? `<span class="rd-flagmark">${esc(b.flag)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table>`)).join("");
  return figs([fig(L.total_draws ?? "—", "draws"), fig(bm.length, "biomarkers"), fig(L.flagged_count ?? 0, "flagged"), L.latest_draw_date && fig(L.latest_draw_date, "latest draw")]) + secs + note("Reference ranges are lab-provided; flags mark out-of-range.");
}

/* ── Physical — DEXA body composition ─────────────────────────────────────── */
function renderPhysical(d) {
  const x = d.latest_dexa;
  if (!x) return empty("No DEXA scan on file yet — body-composition detail appears here after your next scan.");
  const bc = x.body_composition || {}, s360 = x.score_360 || {}, idx = x.indices || {}, bone = x.bone || {}, sf = x.segmental_fat || {}, sl = x.segmental_lean || {};
  const head = figs([
    bc.body_fat_pct != null && fig(fmt(bc.body_fat_pct, 1) + "%", "body fat"),
    bc.lean_mass_lb != null && fig(fmt(bc.lean_mass_lb, 1), "lean mass lb"),
    bc.visceral_fat_lb != null && fig(fmt(bc.visceral_fat_lb, 2), "visceral fat lb"),
    s360.biological_age != null && fig(fmt(s360.biological_age, 1), "biological age", s360.biological_age_delta != null ? `${s360.biological_age_delta > 0 ? "+" : ""}${fmt(s360.biological_age_delta, 1)} vs actual` : ""),
  ]);
  return head +
    sec("Composition", kvtable(bc)) +
    sec("Indices (ALMI / FFMI / FMI)", kvtable(idx)) +
    sec("Bone density", kvtable(bone)) +
    (Object.keys(sf).length ? sec("Segmental fat %", kvtable(sf)) : "") +
    (Object.keys(sl).length ? sec("Segmental lean", kvtable(sl)) : "") +
    note(`DEXA scan${x.scan_date ? ` · ${esc(x.scan_date)}` : ""}. ${s360.percentile != null ? "Percentiles are age/sex population norms." : ""}`);
}

/* ── Training & workouts (multi-endpoint) ─────────────────────────────────── */
async function renderTraining(d) {
  const t = d.training || {};
  const [str, wk] = await Promise.all([tryJSON("/api/strength_benchmarks"), tryJSON("/api/weekly_physical_summary")]);
  const head = figs([
    fig(t.workouts_30d ?? "—", "workouts · 30d"), fig(t.weekly_avg ?? "—", "weekly avg"),
    t.z2_pct != null && fig(t.z2_pct + "%", "zone-2 target"), t.avg_strain != null && fig(fmt(t.avg_strain, 1), "avg strain"),
    t.strength_sessions_30d != null && fig(t.strength_sessions_30d, "strength · 30d"),
    d.walking && d.walking.avg_daily_steps != null && fig(fmt(d.walking.avg_daily_steps), "avg daily steps"),
  ]);
  const lifts = (str && str.benchmarks) || [];
  const strSec = lifts.length ? sec("Strength — estimated 1RM", `<table class="rd-tbl"><thead><tr><th>lift</th><th>current</th><th>target</th><th>progress</th></tr></thead><tbody>${lifts.map((l) => `<tr><td class="rd-name">${esc(title(l.lift))}</td><td class="num">${fmt(l.current_1rm)}</td><td class="num rd-range">${fmt(l.target)}</td><td class="num">${l.progress_pct != null ? fmt(l.progress_pct) + "%" : "—"}</td></tr>`).join("")}</tbody></table>`) : "";
  const days = (wk && wk.days) || [];
  const wkSec = days.length ? sec("This week — daily movement", `<table class="rd-tbl"><thead><tr><th>day</th><th>steps</th><th>active min</th><th>activities</th></tr></thead><tbody>${days.map((x) => `<tr><td class="rd-name">${esc(x.day_of_week || x.date)}</td><td class="num">${fmt(x.steps)}</td><td class="num">${fmt(x.total_active_minutes)}</td><td class="num rd-range">${Array.isArray(x.activities) ? x.activities.length : fmt(x.activities)}</td></tr>`).join("")}</tbody></table>`) : "";
  if (!head.includes("fig-v") && !strSec && !wkSec) return empty("No training logged yet — workouts, Zone-2, and strength benchmarks appear here as sessions accrue.");
  return head + strSec + wkSec + note("Correlative — training load vs the body's response.");
}

/* ── Nutrition (multi-endpoint) ───────────────────────────────────────────── */
async function renderNutrition(d) {
  const ov = d && !d.error ? d : null;
  const [fm, ps] = await Promise.all([tryJSON("/api/frequent_meals"), tryJSON("/api/protein_sources")]);
  const meals = (fm && fm.meals) || []; const prot = (ps && ps.sources) || (ps && ps.proteins) || [];
  const parts = [];
  if (ov) parts.push(figs(Object.entries(ov).filter(([k, v]) => ["string", "number"].includes(typeof v) && !k.startsWith("_")).slice(0, 4).map(([k, v]) => fig(fmt(v), title(k)))));
  if (meals.length) parts.push(sec("Most-logged meals", `<table class="rd-tbl"><tbody>${meals.slice(0, 20).map((m) => `<tr><td class="rd-name">${esc(m.name || m.meal || "—")}</td><td class="num">${fmt(m.count ?? m.times)}×</td></tr>`).join("")}</tbody></table>`));
  if (prot.length) parts.push(sec("Protein sources", `<table class="rd-tbl"><tbody>${prot.slice(0, 20).map((p) => `<tr><td class="rd-name">${esc(p.name || p.source)}</td><td class="num">${fmt(p.grams ?? p.g)}g</td></tr>`).join("")}</tbody></table>`));
  if (!parts.length) return empty("No nutrition logged yet — macros, frequent meals, and protein sources appear here once meals are tracked.");
  return parts.join("") + note("Correlative — intake vs the deficit.");
}

/* ── Glucose × meals (the CGM marriage, multi-endpoint) ───────────────────── */
async function renderGlucose(d) {
  const [mg, mr] = await Promise.all([tryJSON("/api/meal_glucose"), tryJSON("/api/meal_responses")]);
  const trend = (d && d.glucose_trend) || []; const cur = d && d.glucose;
  const mealsG = (mg && mg.meals) || []; const resp = (mr && mr.meals) || [];
  const head = figs([cur && cur.avg != null && fig(fmt(cur.avg), "avg mg/dL"), cur && cur.tir != null && fig(cur.tir + "%", "time in range"), (mg && mg.has_cgm != null) && fig(mg.has_cgm ? "yes" : "no", "cgm active")]);
  const rows = (resp.length ? resp : mealsG);
  const mealSec = rows.length ? sec("Meal glucose response", `<table class="rd-tbl"><thead><tr><th>meal</th><th>peak</th><th>Δ rise</th><th>return</th></tr></thead><tbody>${rows.slice(0, 25).map((m) => `<tr><td class="rd-name">${esc(m.name || m.meal || "—")}</td><td class="num">${fmt(m.peak ?? m.peak_mgdl)}</td><td class="num">${fmt(m.delta ?? m.rise)}</td><td class="num rd-range">${fmt(m.return_min ?? m.recovery_min)}${m.return_min != null ? "m" : ""}</td></tr>`).join("")}</tbody></table>`) : "";
  if (!head.includes("fig-v") && !mealSec && !trend.length) return empty("No CGM data yet — once a sensor is active, this marries each meal to its glucose response (peak, rise, return-to-baseline).");
  return head + mealSec + note("Correlative — how specific meals moved glucose. Not diagnostic.");
}

/* ── Sleep detail ─────────────────────────────────────────────────────────── */
function renderSleep(d) {
  const s = d.sleep_detail || {}; if (!Object.values(s).some(has)) return empty("No sleep data yet — score, stages, HRV and recovery appear here nightly.");
  return figs([
    s.sleep_score != null && fig(fmt(s.sleep_score), "sleep score"), s.total_sleep_hours != null && fig(fmt(s.total_sleep_hours, 1), "hours"),
    s.sleep_efficiency != null && fig(fmt(s.sleep_efficiency) + "%", "efficiency"), s.recovery_score != null && fig(fmt(s.recovery_score), "recovery"), s.hrv != null && fig(fmt(s.hrv), "hrv ms"),
  ]) + sec("Stages & physiology", kvtable({ deep_sleep_hours: s.deep_sleep_hours, rem_sleep_hours: s.rem_sleep_hours, whoop_quality: s.whoop_quality, bed_temp_f: s.bed_temp_f })) + note("Correlative — last night and the recent trend.");
}

/* ── Mind & inner life ────────────────────────────────────────────────────── */
function renderMind(d) {
  const m = d.mind || {}; const vices = d.vice_streaks || [];
  const head = figs([m.journal_entries_30d != null && fig(m.journal_entries_30d, "journal · 30d"), m.mood_entries_count != null && fig(m.mood_entries_count, "mood logs"), m.resist_rate_pct != null && fig(fmt(m.resist_rate_pct) + "%", "temptations resisted"), m.meaningful_pct != null && fig(m.meaningful_pct + "%", "meaningful talk")]);
  const viceSec = vices.length ? sec("Vice streaks (held)", `<table class="rd-tbl"><tbody>${vices.map((v) => `<tr><td class="rd-name">${esc(title(v.name))}</td><td class="num">${fmt(v.current_streak)}d ${v.holding ? "✓" : ""}</td></tr>`).join("")}</tbody></table>`) : "";
  if (!head.includes("fig-v") && !viceSec) return empty("No mood / journal / temptation data yet — the inner-life view fills in as you log.");
  return head + viceSec + note("Correlative — mood, reflection, and restraint. Categories kept private.");
}

/* ── Vice streaks ─────────────────────────────────────────────────────────── */
function renderVices(d) {
  const v = d.vices || []; if (!v.length) return empty("No vice tracking yet.");
  return figs([fig(d.total_held ?? 0, "held"), fig(d.total_tracked ?? v.length, "tracked")]) +
    sec("Streaks", `<table class="rd-tbl"><thead><tr><th>vice</th><th>current</th><th>best</th><th>relapses 90d</th></tr></thead><tbody>${v.map((x) => `<tr class="${x.holding ? "" : "rd-flag"}"><td class="rd-name">${esc(title(x.name))}</td><td class="num">${fmt(x.current_streak)}d</td><td class="num rd-range">${fmt(x.best_streak)}d</td><td class="num">${fmt(x.relapses_90d)}</td></tr>`).join("")}</tbody></table>`) +
    note("Shown honestly — held and broken both. Categories named privately.");
}

/* ── The ledger ───────────────────────────────────────────────────────────── */
function renderLedger(d) {
  const t = d.totals || {};
  return figs([fig("$" + fmt(t.total_donated_usd), "donated"), fig("$" + fmt(t.total_bounties_usd), "bounties earned"), fig("$" + fmt(t.total_punishments_usd), "punishments"), fig(fmt(t.bounty_count), "bounties")]) +
    note("Money moved by the accountability rules — skin in the game.");
}

/* ── Discoveries ──────────────────────────────────────────────────────────── */
function renderDiscoveries(d) {
  const hyp = d.active_hypotheses || [], inner = d.inner_life || [], ai = d.ai_findings || [];
  const hsec = hyp.length ? sec("Active hypotheses", `<div class="rd-cards">${hyp.map((h) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(h.name)}</h3>${h.evidence_tier ? `<span class="rd-badge">${esc(h.evidence_tier)}</span>` : ""}</header>${h.hypothesis ? `<p class="rd-why">${esc(h.hypothesis)}</p>` : (h.description ? `<p class="rd-why">${esc(h.description)}</p>` : "")}<p class="rd-meta label">${[h.pillar, h.protocol].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>`) : "";
  const isec = inner.length ? sec("Inner-life findings", `<div class="rd-cards">${inner.map((f) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(f.title)}</h3>${f.confidence ? `<span class="rd-badge">${esc(f.confidence)}</span>` : ""}</header>${f.body ? `<p class="rd-why">${esc(f.body)}</p>` : ""}<p class="rd-meta label">${[f.category, f.date].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>`) : "";
  if (!hsec && !isec && !ai.length) return empty("No discoveries logged yet — hypotheses and findings the engine surfaces appear here.");
  return hsec + isec + note("Correlative leads, not conclusions — each is a hypothesis under test.");
}

/* ── Genome / biology ─────────────────────────────────────────────────────── */
function renderGenome(d) {
  const g = d.genome || d; const rs = g.risk_summary || {}; const cats = g.categories || {};
  const head = figs([g.total_snps != null && fig(fmt(g.total_snps), "SNPs analysed"), rs.unfavorable != null && fig(rs.unfavorable, "unfavorable"), rs.favorable != null && fig(rs.favorable, "favorable")]);
  const catSec = Object.keys(cats).length ? sec("Risk by category", kvtable(cats, Object.fromEntries(Object.keys(cats).map((k) => [k, (v) => typeof v === "object" ? (v.summary || v.label || JSON.stringify(v)) : fmt(v)])))) : "";
  if (!head.includes("fig-v") && !catSec) return empty("Genome not yet published.");
  return head + catSec + note("Genotype is predisposition, not destiny — context for the biomarkers.");
}

/* ── Challenges (multi-endpoint) ──────────────────────────────────────────── */
async function renderChallenges(d) {
  const cur = await tryJSON("/api/current_challenge");
  const cc = cur && cur.current_challenge;
  const list = d.challenges || []; const sm = d.summary || {};
  const banner = cc && cc.challenge ? `<div class="rd-obs"><p class="rd-primary">${esc(cc.challenge)}</p>${cc.detail ? `<p class="rd-why">${esc(cc.detail)}</p>` : ""}<p class="rd-meta label">day ${esc(cc.days_complete ?? 0)} of ${esc(cc.days_total ?? "—")}</p></div>` : "";
  const head = figs([fig(sm.total ?? list.length, "total"), sm.active != null && fig(sm.active, "active"), sm.completed != null && fig(sm.completed, "completed")]);
  const cards = list.length ? `<div class="rd-cards">${list.slice(0, 40).map((c) => { const done = !!c.completed_at; const active = !done && !!c.activated_at; const status = done ? "completed" : active ? "active" : "candidate";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(title(c.challenge_id || "Challenge"))}</h3><span class="rd-badge ${active ? "rd-badge-live" : ""}">${status}</span></header><p class="rd-meta label">${[c.character_xp_awarded != null && c.character_xp_awarded + " XP", c.badge_earned && "🏅 badge", c.completed_at && esc(String(c.completed_at).slice(0, 10))].filter(Boolean).join("  ·  ")}</p></article>`; }).join("")}</div>` : empty("No challenges yet — they'll appear here as you take them on. Read-only by design.");
  return banner + head + cards + note("An N=1 instrument — reader participation is deferred.");
}

/* ── Protocols / Experiments / Habits (from earlier, kept) ────────────────── */
function renderProtocols(d) { const ps = d.protocols || []; if (!ps.length) return empty("No active protocols yet."); return figs([fig(ps.length, "active protocols")]) + `<div class="rd-cards">${ps.map((p) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}${p.key_finding && !isBad(p.key_finding) ? `<p class="rd-line"><span class="label">finding</span> ${esc(p.key_finding)}</p>` : ""}<p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>` + note("Matthew's deliberate interventions, read-only. Not medical advice."); }
function renderExperiments(d) { const xs = d.experiments || []; if (!xs.length) return empty("No experiments running yet."); return figs([fig(xs.length, "experiments")]) + `<div class="rd-cards">${xs.map((x) => { const done = /complete|done|ended|closed/i.test(x.status || ""); const verdict = x.hypothesis_confirmed === true ? "confirmed" : x.hypothesis_confirmed === false ? "not confirmed" : (x.outcome || x.status || "running"); return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge ${done ? "" : "rd-badge-live"}">${esc(x.status || "")}</span></header>${x.hypothesis ? `<p class="rd-why"><span class="label">hypothesis</span> ${esc(x.hypothesis)}</p>` : ""}${x.result_summary && !isBad(x.result_summary) ? `<p class="rd-line">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${[verdict, x.grade && "grade " + esc(x.grade), x.days_in != null && x.days_in + "d in"].filter(Boolean).map(esc).join("  ·  ")}</p></article>`; }).join("")}</div>` + note("N=1 instrument exposed as proof."); }
function renderHabits(d) { const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; const a = d.day_of_week_avgs || []; const mx = Math.max(1, ...a); return figs([fig(d.current_streak ?? 0, "day streak"), fig(d.days_tracked ?? 0, "days tracked")]) + (a.length ? sec("Adherence by day of week", `<div class="hb-chart">${a.map((v, i) => `<div class="hb-col"><span class="hb-bar" style="height:${Math.max(4, (v / mx) * 100)}%"></span><span class="hb-day label">${dows[i] || ""}</span></div>`).join("")}</div>`) : "") + note("The discipline layer behind Consistency."); }

/* ── The AI experts — the board (multi-endpoint) ──────────────────────────── */
async function renderBoard(d) {
  const coaches = d.coaches || []; const wp = d.weekly_priority || {};
  const chair = wp.text && !isBad(wp.text) ? `<div class="rd-obs"><p class="board-kicker label">the integrator's weekly read · ${esc(wp.coach_name || "")}</p><p class="rd-primary">${esc(wp.text)}</p></div>` : `<div class="rd-obs"><p class="rd-primary">The board's weekly read posts after the next briefing.</p></div>`;
  const roster = coaches.length ? `<div class="coach-grid">${coaches.map((c) => `<article class="coach" style="--coach:${/^#|rgb/.test(c.color || "") ? c.color : "var(--ember)"}"><span class="coach-badge">${esc(c.initials || (c.name || "?").slice(0, 2))}</span><div><h3 class="coach-name">${esc(c.name)}</h3><p class="coach-title label">${esc(c.title || "")}</p></div></article>`).join("")}</div>` : empty("The expert board is being assembled.");
  return chair + sec("The experts", roster) + note("A board of named AI characters who argue about the data. Interpretation, not instruction.");
}

/* ── Generic + fallbacks ──────────────────────────────────────────────────── */
function renderGeneric(d) {
  const root = (T.root && d[T.root]) ? d[T.root] : d;
  const scal = Object.entries(root).filter(([k, v]) => !k.startsWith("_") && ["string", "number", "boolean"].includes(typeof v));
  let arr = null, key = null; for (const [k, v] of Object.entries(root)) if (Array.isArray(v) && v.length && typeof v[0] === "object") { arr = v; key = k; break; }
  let tbl = ""; if (arr) { const cols = [...new Set(arr.flatMap((r) => Object.keys(r)))].filter((c) => !c.startsWith("_")).slice(0, 5); tbl = sec(key, `<table class="rd-tbl"><thead><tr>${cols.map((c) => `<th>${esc(title(c))}</th>`).join("")}</tr></thead><tbody>${arr.slice(0, 40).map((r) => `<tr>${cols.map((c) => `<td class="num">${esc(fmt(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`); }
  if (!scal.length && !tbl) return empty("No data published for this section yet — it fills from the live pipeline.");
  return figs(scal.slice(0, 4).map(([k, v]) => fig(fmt(v), title(k)))) + tbl + note("Correlative read only.");
}

const RENDERERS = {
  supplements: renderSupplements, labs: renderLabs, physical: renderPhysical, training: renderTraining,
  nutrition: renderNutrition, glucose: renderGlucose, sleep: renderSleep, mind: renderMind, vices: renderVices,
  ledger: renderLedger, discoveries: renderDiscoveries, biology: renderGenome, challenges: renderChallenges,
  protocols: renderProtocols, experiments: renderExperiments, habits: renderHabits, board: renderBoard,
};

async function render() {
  const out = document.querySelector("[data-readout]");
  if (!out) return;
  if (T.mode !== "data" || !T.endpoint) { out.innerHTML = `<p class="rd-archive">${esc(T.archive_note || "This section lives in the archive while it's rebuilt into the new Evidence treatment.")}</p>`; return; }
  try {
    const data = await getJSON(T.endpoint);
    const fn = RENDERERS[T.slug] || renderGeneric;
    const html = await fn(data, T);
    out.innerHTML = html && html.trim() ? html : empty("No data published for this section yet — it fills from the live pipeline.");
  } catch (e) { out.innerHTML = empty("This readout couldn't load its data just now. The preserved view is linked below."); }
}

function wireTheme() {
  const btn = document.querySelector(".theme-toggle"); if (!btn) return;
  btn.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} });
}
wireTheme();
render();
