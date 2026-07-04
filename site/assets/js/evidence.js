/*
  evidence.js — Door 3 as a master-detail app (/data/)
  ----------------------------------------------------------------------------
  Horizontal GROUP tabs (top) · topic TILES (left) · readout loads in the CENTER
  dynamically — no page jumps. Repeat-user browse per the Brief (§5: archival
  index, structured, browsable) + the disclosure model (detail in place, lateral
  movement). Deep links (/data/<slug>/) and the old-URL redirects still work
  via the History API. Renderers are bespoke + data-bound to the real shapes;
  empty domains render an honest "ready, no data yet" state.

  Registry + start slug are embedded by scripts/v4_build_evidence.py:
    window.__EVIDENCE_REGISTRY__ = [{slug,title,blurb,group,mode,endpoint,root,legacy,editorial}]
    window.__START_SLUG__ = "<slug>"
*/

import { lineChart, barChart, dualWeight, stackedBar, correlationChip, intakeSpine, sufficiencyBars, stackedColumns, mealWindowRibbon, dualLineChart, sparkline, targetSpine, heatStrip, stackedDayColumns, landmarkBars, dumbbell, weightTrendChart, projectionCone, ring, autonomicHero, autonomicQuadrant, pillarRing, radarChart } from "/assets/js/charts.js";
import { badgeMark, sigil, tierEmblem } from "/assets/js/sigils.js";
import { domainIcon, icon } from "/assets/js/icons.js";
import { mountAsk } from "/assets/js/ask.js";
import { explainMount } from "/assets/js/explain.js"; // #403 one-tap explainer

const REG = window.__EVIDENCE_REGISTRY__ || [];
const BYSLUG = Object.fromEntries(REG.map((t) => [t.slug, t]));
const GROUPS = [...new Set(REG.map((t) => t.group))];
// v5: one engine serves three archive pillars (/data/, /protocols/, /method/).
// The builder sets the route base + door label per page; defaults keep the
// legacy /data/ door working if a page omits them.
const BASE = window.__ARCHIVE_BASE__ || "/data/";
const DOOR = window.__ARCHIVE_DOOR__ || "evidence";
const DOORTITLE = window.__ARCHIVE_TITLE__ || "Evidence";
const slugFromPath = () => { const seg = location.pathname.split("/").filter(Boolean); return seg.length ? seg[seg.length - 1] : ""; };

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
// #491/M-5: today/yesterday in the experiment's timezone (PT) — used to
// date-condition recency labels so an 8-day-old weigh-in is never "today".
const todayPT = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
const dayBefore = (iso) => { const t = Date.parse(String(iso || "").slice(0, 10)); return Number.isFinite(t) ? new Date(t - 86400000).toISOString().slice(0, 10) : ""; };
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
function renderSupplements(d) {
  const g = d.groups || {};
  const head = figs([fig(d.total_count ?? Object.values(g).reduce((a, x) => a + (x.items || []).length, 0), "compounds"), d.as_of_date && fig(d.as_of_date, "as of")]);
  const secs = Object.values(g).map((grp) => {
    const cards = (grp.items || []).map((s) => {
      const [c, l] = evClass(s.ev);
      const pct = Math.max(4, Math.min(100, s.evPct ?? 0));
      const paused = !!s.paused;
      const pausedNote = paused && (s.pausedReason || "Paused — not currently taken");
      // P2.3 — the honesty layer: what the stack CLAIMS (evidence meter) vs what's
      // actually swallowed (adherence_pct, merged server-side from the real log —
      // served since Sprint 9, never drawn until now).
      const adherence = s.adherence_pct != null
        ? `<div class="supp-ev supp-adh"><span class="supp-evlabel">taken</span><span class="supp-meter"><i class="supp-adh-i" style="width:${Math.max(2, Math.min(100, Number(s.adherence_pct))).toFixed(0)}%"></i></span><span class="supp-evpct num">${fmt(s.adherence_pct)}% of days</span></div>`
        : "";
      // P2.3 — the disclosure: the science bullets, the SPLIT sources (the dissent
      // listed first — a stack that only cites support isn't showing its work),
      // rationale/synergy/watching, genome flags.
      const srcs = (s.sources || []).filter((x) => x && x.url);
      const against = srcs.filter((x) => /challeng|against|counter|skeptic/i.test(String(x.stance || "")));
      const forSrcs = srcs.filter((x) => !against.includes(x));
      const srcList = (list, cls, lbl) => list.length
        ? `<p class="supp-srchead label ${cls}">${lbl}</p><ul class="supp-srcs">${list.map((x) => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || x.url)}</a></li>`).join("")}</ul>`
        : "";
      const lines = [["rationale", s.rationale], ["synergy", s.synergy], ["watching", s.watching]]
        .filter(([, v]) => v && !isBad(v))
        .map(([k, v]) => `<p class="rd-line"><span class="label">${k}</span> ${esc(v)}</p>`).join("");
      const sci = (s.science || []).length ? `<ul class="supp-sci">${s.science.slice(0, 6).map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
      const hasMore = sci || lines || srcs.length > 1 || against.length;
      const more = hasMore
        ? `<details class="supp-more"><summary class="label">the work — science, sources${against.length ? " (incl. the dissent)" : ""}, rationale</summary>${sci}${lines}${srcList(against, "supp-src-against", "challenges it")}${srcList(forSrcs, "supp-src-for", "supports it")}</details>`
        : "";
      // Containment, not equality: the registry names are richer than the SNP's
      // supplement key ("Vitamin D3 + K2" vs "Vitamin D3") — verified 1:1 on the
      // live registry; a non-match simply means no chip (fail-soft).
      const snps = (d.genome_snps || []).filter((x) => x && x.supp && String(s.name || "").toLowerCase().includes(String(x.supp).toLowerCase()));
      const snpChips = snps.length ? snps.map((x) => `<p class="supp-snp label" title="${esc(x.note || "")}">genome · ${esc(x.id || "")}${x.note ? ` — ${esc(String(x.note).split("—")[0].trim())}` : ""}</p>`).join("") : "";
      return `<article class="supp${paused ? " supp--paused" : ""}"><header class="supp-top"><h3 class="supp-name">${esc(s.name)}</h3>${paused ? `<span class="supp-flag label">paused</span>` : s.timing ? `<span class="supp-timing label">${esc(s.timing)}</span>` : ""}${s.dose ? `<span class="supp-dose num">${esc(s.dose)}</span>` : ""}</header>${paused ? `<p class="supp-paused-note label">${esc(pausedNote)}</p>` : ""}${s.why ? `<p class="supp-why">${esc(s.why)}</p>` : ""}<div class="supp-ev"><span class="supp-evlabel ${c}">${l}</span><span class="supp-meter"><i class="${c}" style="width:${pct}%"></i></span><span class="supp-evpct num">${s.evPct != null ? s.evPct + "%" : ""}</span></div>${adherence}${more}${snpChips}<p class="supp-meta label">${[s.board && "src: " + esc(s.board), s.cost_monthly != null && "$" + esc(s.cost_monthly) + "/mo", (s.evidence_url || (srcs[0] || {}).url) && `<a class="supp-ev-link" href="${esc(s.evidence_url || (srcs[0] || {}).url)}" target="_blank" rel="noopener">evidence ↗</a>`].filter(Boolean).join("  ·  ")}</p></article>`;
    }).join("");
    return `<section class="rd-sec"><div class="rd-grouphead"><h2 class="rd-h">${esc(grp.name)}</h2>${grp.desc ? `<p class="rd-desc">${esc(grp.desc)}</p>` : ""}</div><div class="supp-grid">${cards}</div></section>`;
  }).join("");
  return head + secs + note("Evidence strength is the published research consensus — not a claim about Matthew.");
}
function renderLabs(d) { const L = d.labs || d; const bm = L.biomarkers || []; if (!bm.length) return empty("No bloodwork drawn yet — panels appear here as they're added."); const by = {}; for (const b of bm) (by[b.category || "Other"] ||= []).push(b); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><thead><tr><th>biomarker</th><th>value</th><th>reference</th><th>flag</th></tr></thead><tbody>${rows.map((b) => { const f = b.flag && String(b.flag).toLowerCase() !== "null"; return `<tr class="${f ? "rd-flag" : ""}"><td class="rd-name">${esc(b.name)}</td><td class="num">${esc(b.value)}${b.unit ? ` <span class="rd-unit">${esc(b.unit)}</span>` : ""}</td><td class="num rd-range">${esc(b.range || "—")}</td><td>${f ? `<span class="rd-flagmark">${esc(b.flag)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table>`)).join(""); return figs([fig(L.total_draws ?? "—", "draws"), fig(bm.length, "biomarkers"), fig(L.flagged_count ?? 0, "flagged"), L.latest_draw_date && fig(L.latest_draw_date, "latest draw")]) + secs + note("Reference ranges are lab-provided; flags mark out-of-range."); }
// ── /data/physical/ — two tiers: the weight cockpit (daily) + the composition arc
// (episodic). "Weight is the metronome; composition is the arc." `d` = physical_overview.
const PHYS_GENESIS = "2026-06-14";
// P0.1 — trend-weight hero (dual-layer). Faint raw daily dots + a confident ember smoothed
// trend; goal is an annotation NOT an axis anchor (HARD RULE 4); genesis marked; two-voice.
function physicalTrendHero(readings, j, goal) {
  const now = j.current_weight_lbs, start = j.start_weight_lbs, lost = j.lost_lbs, rate = j.weekly_rate_lbs, prov = j.rate_provisional;
  const chart = weightTrendChart(readings, { goal, genesis: PHYS_GENESIS, label: "Weight · daily scale vs smoothed trend" });
  const down = lost != null && lost > 0;
  const machine = [
    now != null && `now ${fmt(now)} lb`,
    lost != null && `${down ? "down" : "up"} ${fmt(Math.abs(lost))} lb from ${fmt(start)}`,
    (rate != null && rate !== 0) ? `trend ${fmt(rate)} lb/wk${prov ? " · early = water" : ""}` : "",
  ].filter(Boolean).join(" · ");
  const serif = rate != null && rate < 0
    ? `The scale is moving. ${prov ? "Most of an early cut is water — this rate will slow, and the line knows it; trust the smoothed trend over any single morning's dot." : "The smoothed trend is the signal; the daily dots are scale noise — water, food, the time of the weigh-in."} Goal ${fmt(goal)} sits off the bottom of this axis on purpose: anchoring to it would flatten the slope you're actually walking.`
    : `Weight is the daily metronome — the thing that moves every morning. The faint dots are the raw scale; the line is the trend underneath the noise.`;
  return sec("Weight — the daily metronome",
    chart + `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
// P0.3 — HappyScale-style stat cluster: High / Latest / Low · Yesterday (day-over-day) ·
// % complete (314.5 → 185 denominator). These REPLACE the DEXA percentages as the page's
// top figures. Ember reads positive on a down day; never red.
function physicalStatCluster(readings, j, goal) {
  const ws = readings.map((r) => Number(r.weight_lbs)).filter(Number.isFinite);
  if (ws.length < 1) return "";
  // Latest comes from the SAME raw series as high/low so they reconcile (journey's
  // current_weight is pre-rounded, which can read below the raw min — confusing).
  const latest = ws[ws.length - 1];
  const high = Math.max(...ws), low = Math.min(...ws);
  const prev = ws.length >= 2 ? ws[ws.length - 2] : null;
  const dayDelta = prev != null ? Math.round((ws[ws.length - 1] - prev) * 10) / 10 : null;
  // #491/M-5: label the readings by their actual dates — "yesterday" only when the
  // previous reading truly is yesterday's; a gap shows "Jun 26", never a fake day-delta.
  const withDates = readings.filter((r) => Number.isFinite(Number(r.weight_lbs)));
  const latestD = String((withDates[withDates.length - 1] || {}).date || "").slice(0, 10);
  const prevD = withDates.length >= 2 ? String(withDates[withDates.length - 2].date || "").slice(0, 10) : "";
  const latestCap = latestD && latestD !== todayPT() ? `latest · ${_physShortDate(latestD)}` : "latest";
  const prevWord = prevD && prevD === dayBefore(todayPT()) && latestD === todayPT() ? "yesterday" : (_physShortDate(prevD) || "previous");
  const ydayCap = dayDelta == null ? prevWord : `${prevWord} · ${dayDelta > 0 ? "+" : ""}${fmt(dayDelta)} lb`;
  const pct = j.progress_pct != null ? j.progress_pct : Math.round((j.start_weight_lbs - latest) / (j.start_weight_lbs - goal) * 1000) / 10;
  return figs([
    fig(fmt(high) + " lb", "high"),
    fig(fmt(latest) + " lb", latestCap),
    fig(fmt(low) + " lb", "low"),
    prev != null && fig(fmt(prev) + " lb", ydayCap),
    pct != null && fig(fmt(pct) + "%", `to goal · ${fmt(j.start_weight_lbs ?? 314.5)}→${fmt(goal)}`),
  ]) + `<p class="rd-meta label">The weight figures lead the page now — the body-composition percentages move to the dated scan arc below. % complete is against the full ${fmt(j.start_weight_lbs ?? 314.5)} → ${fmt(goal)} lb span.</p>`;
}
// P0.4 — the milestone ladder: the measuring-rule tick-spine made vertical, 315 → 185 in
// 10-lb rungs. Each crossed rung clicks ember + stamps the day it fell and the days since the
// previous rung (widening gaps = the honest pace arc). The current weight marks the live edge.
const _PHYS_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function _physShortDate(iso) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_PHYS_MON[+m[2] - 1]} ${+m[3]}` : ""; }
function physicalMilestoneLadder(readings, j, goal) {
  const ws = readings.map((r) => ({ d: r.date, w: Number(r.weight_lbs) })).filter((p) => Number.isFinite(p.w));
  if (ws.length < 2) return "";
  const start = j.start_weight_lbs != null ? Number(j.start_weight_lbs) : 314.5;
  const latest = ws[ws.length - 1].w;
  const top = Math.floor(start / 10) * 10;
  const rungs = [{ w: start, cap: "start" }];
  for (let w = top; w > goal + 0.5; w -= 10) if (w < start - 0.5) rungs.push({ w });
  rungs.push({ w: goal, cap: "goal" });
  const crossDate = (rung) => { for (const p of ws) if (p.w <= rung + 1e-9) return p.d; return null; };
  let prevDate = null, nowPlaced = false;
  const rows = rungs.map((r) => {
    const crossed = latest <= r.w + 1e-9;
    const date = crossed ? crossDate(r.w) : null;
    let days = "";
    if (crossed && date && prevDate) { const dd = Math.round((Date.parse(date) - Date.parse(prevDate)) / 86400000); if (dd > 0) days = ` · ${dd}d`; }
    if (crossed && date) prevDate = date;
    // The "now" edge: the first uncrossed rung gets the live marker.
    let nowMark = "";
    if (!crossed && !nowPlaced) { nowPlaced = true; nowMark = `<span class="ml-now">now ${fmt(latest)} lb · ${fmt(Math.round((latest - goal) * 10) / 10)} to goal</span>`; }
    const cls = crossed ? "ml-crossed" : (nowMark ? "ml-next" : "ml-future");
    const cap = r.cap ? `<span class="ml-cap label">${esc(r.cap)}</span>` : "";
    const meta = crossed && date ? `<span class="ml-meta label">crossed ${esc(_physShortDate(date))}${esc(days)}</span>` : "";
    return `<div class="ml-rung ${cls}"><span class="ml-tick"></span><span class="ml-w mono">${fmt(r.w)}</span>${cap}${meta}${nowMark}</div>`;
  }).join("");
  return sec("Milestone ladder — 315 to 185, ten pounds at a time",
    `<div class="ml-ladder">${rows}</div>` +
    `<p class="rd-meta label">Each rung is a 10-lb mark on the way down; it clicks ember the day the trend crosses it, stamped with how long that rung took. The gaps widen as the cut matures — that's the real pace, not a straight line to the goal.</p>`);
}
// P0.5 — rate tempo strip. The pace over 7d / 30d / 90d / since-genesis as ember-intensity
// slope-gauges (not four naked numbers): faster loss = longer, more-saturated ember bar.
// A GAIN window reads muted ink, never red. The 7-day carries the "early = water" flag.
function _slopePerDay(pts) {
  if (pts.length < 3) return null;
  const t0 = Date.parse(pts[0].d);
  const x = pts.map((p) => (Date.parse(p.d) - t0) / 86400000), y = pts.map((p) => p.w);
  const n = x.length, sx = x.reduce((a, b) => a + b, 0), sy = y.reduce((a, b) => a + b, 0);
  const sxy = x.reduce((a, b, i) => a + b * y[i], 0), sxx = x.reduce((a, b) => a + b * b, 0);
  const denom = n * sxx - sx * sx;
  return denom ? (n * sxy - sx * sy) / denom : null;
}
function physicalRateTempo(readings, j) {
  const ws = readings.map((r) => ({ d: r.date, w: Number(r.weight_lbs) })).filter((p) => Number.isFinite(p.w) && /^\d{4}/.test(p.d));
  if (ws.length < 3) return "";
  const today = ws[ws.length - 1].d;
  const since = (days) => { const cut = new Date(Date.parse(today) - days * 86400000).toISOString().slice(0, 10); return ws.filter((p) => p.d >= cut); };
  const genDays = Math.max(1, Math.round((Date.parse(today) - Date.parse(PHYS_GENESIS)) / 86400000));
  const spanOf = (pts) => (pts.length ? Math.max(1, Math.round((Date.parse(today) - Date.parse(pts[0].d)) / 86400000)) : 0);
  const windows = [
    { k: "7-day", days: 7, pts: since(7), flag: "early = water" },
    { k: "30-day", days: 30, pts: since(30) },
    { k: "90-day", days: 90, pts: since(90) },
    { k: "since genesis", pts: ws.filter((p) => p.d >= PHYS_GENESIS), sub: `${genDays}d` },
  ];
  // Honest windows (truth-audit Phase 4b): with only ~13 days of data the 30/90-day
  // windows hold the SAME points and render identical bars. Label a window that doesn't
  // actually reach back its nominal length with the real span, and drop any window whose
  // point-set is identical to one already shown (no duplicate bars).
  const seen = new Set();
  const rates = [];
  for (const w of windows) {
    if (!w.pts.length) continue;
    const sig = w.pts.length + ":" + w.pts[0].d;
    const span = spanOf(w.pts);
    if (w.days && span < w.days - 1) {
      if (seen.has(sig)) continue; // identical to a shorter window — don't repeat the bar
      w.k = `${span}-day`; // be honest: it's a span-day window, not a full 30/90
    } else if (seen.has(sig)) {
      continue;
    }
    seen.add(sig);
    const s = _slopePerDay(w.pts);
    rates.push({ ...w, wk: s == null ? null : Math.round(s * 7 * 10) / 10 });
  }
  const maxMag = Math.max(0.5, ...rates.map((r) => (r.wk == null ? 0 : Math.abs(r.wk))));
  const row = (r) => {
    if (r.wk == null) return `<div class="rt-row"><span class="rt-label">${esc(r.k)}</span><span class="rt-gauge"></span><span class="rt-v mono rt-na">—  too few weigh-ins</span></div>`;
    const losing = r.wk < 0;
    const width = Math.min(100, (Math.abs(r.wk) / maxMag) * 100);
    const op = (0.4 + 0.6 * Math.min(1, Math.abs(r.wk) / maxMag)).toFixed(2);
    const tone = losing ? "rt-ember" : "rt-ink";
    return `<div class="rt-row"><span class="rt-label">${esc(r.k)}${r.sub ? ` <span class="rt-sub">${esc(r.sub)}</span>` : ""}</span>` +
      `<span class="rt-gauge"><span class="rt-fill ${tone}" style="width:${width.toFixed(0)}%;opacity:${op}"></span></span>` +
      `<span class="rt-v mono">${r.wk > 0 ? "+" : ""}${fmt(r.wk)} lb/wk</span>${r.flag ? `<span class="rt-flag label">${esc(r.flag)}</span>` : ""}</div>`;
  };
  return sec("Rate tempo — the pace across windows",
    `<div class="rt-strip">${rates.map(row).join("")}</div>` +
    `<p class="rd-meta label">Each bar is a loss rate; the longer and more saturated, the faster. The 7-day runs hot early because a new cut sheds water — it isn't fat coming off that fast, and it will slow. A gain window would read muted ink, never an alarm.</p>`);
}
// P0.7 — BMI, deliberately de-emphasized. Included because HappyScale-literate readers
// expect it, but small, last in Tier 1, and captioned with its own limitation (near-
// meaningless on a heavy frame rebuilding lean mass). Height from the profile, never a hero.
function physicalBMI(readings, j) {
  const hIn = Number(j.height_inches);
  const latest = readings.length ? Number(readings[readings.length - 1].weight_lbs) : Number(j.current_weight_lbs);
  if (!Number.isFinite(hIn) || hIn <= 0 || !Number.isFinite(latest)) return "";
  const bmi = Math.round((703 * latest / (hIn * hIn)) * 10) / 10;
  return sec("BMI — included, but kept in its place",
    `<p class="rd-bmi"><span class="rd-bmi-v mono">${fmt(bmi)}</span> <span class="label">BMI</span></p>` +
    `<p class="rd-meta label">BMI is here only because people look for it — it's near-meaningless on a heavy frame carrying real muscle. It can't tell fat from lean, so it reads "obese" for a lineman and a couch alike. The DEXA composition below is the honest version; this is the number to distrust.</p>`);
}
// P1.1 — next-DEXA countdown: the Tier-2 arc anchor. Turns a single scan from a stale tile
// into anticipation ("the next chapter lands in ~X days"). Cut-aware target: ~10 weeks past
// genesis, when fat-vs-lean change finally clears the DEXA error bar — NOT the API's generic
// last+90 cadence (which would fall 2 weeks into the cut, too soon to mean anything). Honest
// that it isn't booked — scheduling it is the P2.1 capture step this countdown waits on.
function physicalDexaCountdown(d) {
  const x = d.latest_dexa; if (!x || !x.scan_date) return "";
  const genesisMs = Date.parse(PHYS_GENESIS);
  const apiMs = x.next_dexa_recommended ? Date.parse(x.next_dexa_recommended) : 0;
  const targetMs = Math.max(genesisMs + 70 * 86400000, apiMs || 0);
  const today = new Date(); const todayMs = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const days = Math.round((targetMs - todayMs) / 86400000);
  const td = new Date(targetMs), tStr = `${_PHYS_MON[td.getUTCMonth()]} ${td.getUTCFullYear()}`;
  const sinceLast = Math.round((todayMs - Date.parse(x.scan_date)) / 86400000);
  return sec("The composition arc — scan two is the next chapter",
    `<div class="dx-count"><span class="dx-days mono">${days > 0 ? "~" + days : "due"}</span><span class="dx-unit label">${days > 0 ? "days to the recommended scan two" : "scan two is due"}</span></div>` +
    `<p class="rd-meta label">The last DEXA was ${sinceLast} days ago, <strong>pre-cut</strong>. A second scan around <strong>${tStr}</strong> — roughly ten weeks into the cut — is when fat-vs-lean change finally clears the scan's own error bar and composition <em>velocity</em> becomes real. It isn't booked yet; scheduling it is the next data-capture step, and it's what this countdown is waiting on. Everything below is that one pre-cut scan — a dated snapshot, not a trend.</p>`);
}
// P1.2 — DEXA baseline as ONE dated stacked bar (lean vs fat). A snapshot, never a trend:
// lean is ember (the asset the cut protects), fat muted ink. Dated + pre-cut-labeled, with
// the honest line that this is where the cut STARTED — the scale above shows where it is now.
function _physDexaAgeDays(scanDate) {
  const t = Date.parse(scanDate); if (!Number.isFinite(t)) return null;
  const today = new Date(); return Math.round((Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()) - t) / 86400000);
}
function physicalDexaBaseline(d) {
  const x = d.latest_dexa; if (!x) return "";
  const bc = x.body_composition || {};
  const lean = Number(bc.lean_mass_lb), fat = Number(bc.fat_mass_lb);
  if (!Number.isFinite(lean) || !Number.isFinite(fat)) return "";
  const age = _physDexaAgeDays(x.scan_date);
  const bfp = bc.body_fat_pct != null ? `${fmt(bc.body_fat_pct, 1)}% body fat` : "";
  const bar = stackedBar([{ label: "lean mass", value: lean, tone: "ember" }, { label: "fat mass", value: fat, tone: "ink" }], { label: `Lean vs fat · ${esc(x.scan_date)}`, unit: " lb" });
  return sec("DEXA baseline — lean vs fat (one scan, dated)",
    bar + `<p class="rd-meta label"><strong>${esc(x.scan_date)}${age != null ? ` · ~${age} days ago` : ""} · pre-cut baseline.</strong> A snapshot, not a trend${bfp ? ` — ${esc(bfp)}` : ""}. This is where the cut <em>started</em>; the weight cockpit above shows where it is now. Lean (ember) is the asset the cut is trying to keep while the fat comes off — proven only when scan two lands.</p>`);
}
// P1.3 — visceral fat callout (dated). The fat around the organs — a better predictor of
// metabolic risk than total body-fat %. One figure + a risk-band gauge where ember INTENSITY
// (never red) rises with risk; thresholds are DEXA-system-dependent, so the band is explicitly
// directional, not a diagnosis.
function physicalVisceralCallout(d) {
  const x = d.latest_dexa; if (!x) return "";
  const bc = x.body_composition || {};
  const vlb = Number(bc.visceral_fat_lb), vg = Number(bc.visceral_fat_g);
  if (!Number.isFinite(vlb) && !Number.isFinite(vg)) return "";
  const lb = Number.isFinite(vlb) ? vlb : vg / 453.592;
  const maxS = 3; // lb full-scale
  const pos = Math.max(0, Math.min(100, (lb / maxS) * 100));
  const band = lb < 1 ? "low" : lb < 2 ? "moderate" : "elevated";
  const age = _physDexaAgeDays(x.scan_date);
  const fig6 = `${fmt(Math.round(lb * 100) / 100)} lb${Number.isFinite(vg) ? ` · ${fmt(Math.round(vg))} g` : ""}`;
  return sec("Visceral fat — the number under the number",
    `<div class="vf-wrap"><div class="vf-fig"><span class="vf-v mono">${esc(fig6)}</span><span class="vf-band label vf-${band}">${esc(band)}</span></div>` +
    `<div class="vf-gauge" role="img" aria-label="Visceral fat ${esc(fig6)} — ${band} band on a directional 0–3 lb scale"><span class="vf-zone vf-z1"></span><span class="vf-zone vf-z2"></span><span class="vf-zone vf-z3"></span><span class="vf-mark" style="left:${pos.toFixed(1)}%"></span></div>` +
    `<div class="vf-scale label"><span>0</span><span>low · moderate · elevated</span><span>${maxS} lb</span></div></div>` +
    `<p class="rd-meta label">Visceral fat wraps the organs and drives metabolic risk more than total body-fat % does — it's the number to actually watch, and the one a cut moves early. Dated <strong>${esc(x.scan_date)}${age != null ? ` · ~${age} days ago` : ""}</strong>, pre-cut. The bands are directional only — DEXA systems disagree on exact cutoffs, so this reads the zone, never a diagnosis.</p>`);
}
// P1.4 — lean / ALMI longevity context, demoted. Appendicular lean mass index is the
// body-comp number that best predicts healthy aging (sarcopenia/frailty). Small: a few figs,
// a one-line reference floor, plain language — out of the raw index table. Dated.
function physicalLeanLongevity(d) {
  const x = d.latest_dexa; if (!x) return "";
  const idx = x.indices || {}, bc = x.body_composition || {};
  const almi = Number(idx.almi_kg_m2), pct = Number(idx.almi_percentile), lean = Number(bc.lean_mass_lb);
  if (!Number.isFinite(almi) && !Number.isFinite(lean)) return "";
  const FLOOR = 7.0; // commonly-cited male sarcopenia ALMI floor (kg/m²); cutoffs vary
  const clear = Number.isFinite(almi) ? Math.round((almi - FLOOR) * 10) / 10 : null;
  return sec("Lean mass & longevity — the aging number",
    figs([
      Number.isFinite(almi) && fig(fmt(almi, 1), "ALMI · kg/m²"),
      Number.isFinite(pct) && fig(fmt(pct) + "th", "percentile"),
      Number.isFinite(lean) && fig(dualWeight(lean, "lb"), "appendicular + trunk lean"),
    ]) +
    `<p class="rd-meta label">Appendicular lean mass — the muscle on the arms and legs — is the body-comp figure that best predicts how well you age: it's the buffer against sarcopenia and frailty. ${Number.isFinite(almi) ? `At ${fmt(almi, 1)} kg/m²${Number.isFinite(pct) ? `, ${fmt(pct)}th percentile,` : ""} that's ${clear != null && clear > 0 ? `~${fmt(clear)} clear of` : "near"} the ~${FLOOR} sarcopenia floor.` : ""} The cut's whole job is to keep this while the fat comes off — confirmed only when scan two lands. Dated <strong>${esc(x.scan_date)}</strong>, pre-cut.</p>`);
}
// P1.5 — PhenoAge (transparent), Option A privacy. Shows the phenotypic ("biological") age +
// the 9 markers driving it — NO chronological age, NO gap, so the page can't reveal real age.
// Replaces the DEXA black-box "biological age". Honest "needs marker X" if any input missing.
function physicalPhenoAge(pa) {
  if (!pa) return "";
  if (pa.phenoage == null) {
    const miss = (pa.missing || []).join(", ");
    return sec("Biological age — PhenoAge (transparent)",
      `<p class="rd-meta label">Phenotypic Age needs all 9 blood markers and is never approximated from partial data${miss ? ` — waiting on: <strong>${esc(miss)}</strong>` : ""}. It fills in at the next complete draw.</p>`);
  }
  const drivers = pa.drivers || [];
  const driverRows = drivers.map((dv) => {
    const tone = dv.direction === "younger" ? "pa-younger" : dv.direction === "older" ? "pa-older" : "pa-neutral";
    const val = dv.value != null ? `${fmt(dv.value)}${dv.unit ? " " + dv.unit : ""}` : "—";
    return `<div class="pa-driver ${tone}"><span class="pa-d-name">${esc(dv.name)}${dv.derived ? ` <span class="pa-derived">derived</span>` : ""}</span><span class="pa-d-val mono">${esc(val)}</span><span class="pa-d-dir label">${esc(dv.direction || "")}</span></div>`;
  }).join("");
  return sec("Biological age — PhenoAge (transparent, replaces the black box)",
    `<div class="pa-dial"><span class="pa-v mono">${esc(String(pa.phenoage))}</span><span class="pa-unit label">phenotypic age · years</span></div>` +
    `<p class="rd-meta label">Levine Phenotypic Age (2018), computed from 9 standard blood markers — the transparent replacement for the DEXA "biological age" black box; every input is shown below. ${pa.as_of ? `Recomputed per blood draw · <strong>${esc(pa.as_of)}</strong>.` : ""} <strong>Chronological age isn't shown, by design</strong> — this can't be used to back out a real age. <strong>Caveats:</strong> population-level, not a diagnosis; this is blood-based <em>Phenotypic</em> Age, NOT the DNAm epigenetic clock; it's volatile to single markers (a CRP spike from a cold can swing it). <a href="/data/labs/">See the full bloodwork →</a></p>` +
    `<details class="pa-details"><summary class="pa-sum label">The 9 markers driving it — show the inputs</summary><div class="pa-drivers">${driverRows}</div>` +
    `<p class="rd-meta label">Ember = the marker is pushing the number <em>younger</em> vs a healthy reference; muted = older; faint = neutral. Lymphocyte % is derived from absolute lymphocytes ÷ WBC.</p></details>`);
}
// P2.1–P2.5 — new-capture + velocity, honestly gated. Each is a real capability with an
// honest empty/pending state until the data exists; none fabricate or surface a gated metric.
// P2.4 (composition velocity) STAYS a placeholder until a SECOND valid DEXA exists and the
// delta clears least-significant-change — never built off one scan.
function physicalCaptureBacklog(d, pa) {
  const x = d.latest_dexa || {};
  const haveTape = d.tape_measurements && Object.keys(d.tape_measurements).length;
  const cards = [];
  // P2.1 — DEXA cadence / scan-two scheduling (drives the countdown; unlocks velocity).
  cards.push(`<div class="cap-card"><h4 class="cap-h">Scan two — scheduling <span class="cap-tag">unlocks velocity</span></h4><p class="rd-meta label">A second DEXA ~10 weeks into the cut turns every composition figure above from a dated snapshot into a real fat-vs-lean <em>trajectory</em>. Booking it is the single highest-value capture step — it's what the countdown at the top of the arc is waiting on. Not yet scheduled.</p></div>`);
  // P2.2 — tape measurements (between-DEXA proxy).
  cards.push(`<div class="cap-card"><h4 class="cap-h">Tape measurements <span class="cap-tag">${haveTape ? "flowing" : "needs capture"}</span></h4><p class="rd-meta label">${haveTape ? "Tape sessions are logging — a cheap, frequent proxy for the silhouette and segmental change between scans." : "Zero sessions yet. A monthly tape (waist, hips, limbs) is the cheap, frequent proxy that keeps the silhouette honest between the expensive scans. Awaiting the first measurement."}</p></div>`);
  // P2.3 — progress photos (PRIVATE by default; explicit opt-in before any public render).
  cards.push(`<div class="cap-card"><h4 class="cap-h">Progress photos <span class="cap-tag cap-private">private by default</span></h4><p class="rd-meta label">The most powerful change signal and the most sensitive — so they're private by default, never rendered here without an explicit opt-in. The faceless silhouette above is the public-safe stand-in. No photo is shown.</p></div>`);
  // P2.4 — composition velocity (GATED on scan two + LSC).
  cards.push(`<div class="cap-card"><h4 class="cap-h">Composition velocity <span class="cap-tag">awaits scan two</span></h4><p class="rd-meta label">Lean/fat/visceral change per week — the number everyone wants — stays blank on purpose. One DEXA is a point; velocity needs a second valid scan AND a delta that clears the scan's least-significant-change, or it's noise dressed as progress. Until then, weight is the only honest "change." Placeholder, not hidden.</p></div>`);
  // P2.5 — complementary ages (optional; PhenoAge stays the anchor; WHOOP Age NOT built).
  cards.push(`<div class="cap-card"><h4 class="cap-h">Complementary ages <span class="cap-tag">secondary lenses</span></h4><p class="rd-meta label">Vascular age (Withings pulse-wave velocity) and a VO₂max fitness age could sit beside PhenoAge as secondary lenses — PhenoAge stays the anchor. WHOOP's "age" isn't in their official API (only a fragile unofficial scrape), so it's deliberately not built. Awaiting the source wiring.</p></div>`);
  return sec("What unlocks the arc — the capture backlog",
    `<div class="cap-grid">${cards.join("")}</div>` +
    `<p class="rd-meta label">Each of these is a real capability waiting on data, not a stub — honest empty states, ranked by what would move the picture most. Composition velocity is gated hardest: it does not get built off a single scan.</p>`);
}
// P1.6 — full-scan expander (dated). The remaining indices / segmental / bone numbers tucked
// behind a "full scan" disclosure, all dated. The +3.9 bone T-score is SUPPRESSED as an
// artifact (a T-score that high is physiologically implausible — almost certainly a parse
// error), shown as a flag, never as fact. The DEXA "Body Score" is already gone (never
// surfaced in the redesign — replaced by transparent PhenoAge above).
function physicalFullScanExpander(d) {
  const x = d.latest_dexa; if (!x) return "";
  const idx = x.indices || {}, bone = x.bone || {}, sf = x.segmental_fat || {}, sl = x.segmental_lean || {};
  const tval = Number(bone.t_score);
  const tImplausible = Number.isFinite(tval) && tval >= 3;
  const boneBlock = `<h4 class="hb-group label">Bone density</h4>` + (
    tImplausible
      ? `<p class="rd-flag-note label">⚑ Bone T-score reported <strong>+${esc(fmt(tval, 1))}</strong> — suppressed as a likely scan artifact: a T-score that high is physiologically implausible (it would mean bone density ~4 SD above the young-adult peak). Treated as a parse/scan error pending a re-read, not shown as a result.</p>`
      : kvtable(bone)
  );
  const idxSlim = {};
  for (const k of ["ffmi_kg_m2", "fmi_kg_m2", "ffmi_rating", "fmi_rating"]) if (idx[k] != null) idxSlim[k] = idx[k];
  const inner =
    (Object.keys(idxSlim).length ? `<h4 class="hb-group label">Indices (FFMI / FMI)</h4>${kvtable(idxSlim)}` : "") +
    boneBlock +
    (Object.keys(sf).length ? `<h4 class="hb-group label">Segmental fat %</h4>${kvtable(sf)}` : "") +
    (Object.keys(sl).length ? `<h4 class="hb-group label">Segmental lean</h4>${kvtable(sl)}` : "");
  return sec("The full scan — everything else, dated",
    `<details class="fs-exp"><summary class="pa-sum label">Open the full ${esc(x.scan_date || "DEXA")} scan — indices, segmental, bone</summary><div class="fs-body">${inner}</div></details>` +
    note(`Every figure here is from the single ${esc(x.scan_date || "")} pre-cut scan — a dated snapshot, not a trend. Composition velocity unlocks at scan two.`));
}
async function renderPhysical(d) {
  const [wp, wj, pa] = await Promise.all([tryJSON("/api/weight_progress"), tryJSON("/api/journey"), tryJSON("/api/phenoage")]);
  const readings = (wp && wp.weight_progress) || [];
  const j = (wj && wj.journey) || {};
  const goal = j.goal_weight_lbs ?? 185;
  const parts = [];
  // ── TIER 1 — the weight cockpit (daily) ──
  parts.push(physicalTrendHero(readings, j, goal)); // P0.1
  if (j.start_weight_lbs != null && j.current_weight_lbs != null) parts.push(dataFigure(j)); // P0.2 — silhouette scrubber (links to the trend marker)
  parts.push(physicalStatCluster(readings, j, goal)); // P0.3 — stat cluster (replaces DEXA % as top figures)
  parts.push(physicalMilestoneLadder(readings, j, goal)); // P0.4 — milestone ladder (the vertical measuring-rule signature)
  parts.push(physicalRateTempo(readings, j)); // P0.5 — rate tempo strip (ember-intensity slope-gauges)
  // P0.6 — projection cone (widening; rate from the readings, rungs date-marked; the bet, gradeable).
  if (readings.length >= 3) {
    const ws6 = readings.map((r) => ({ d: r.date, w: Number(r.weight_lbs) })).filter((p) => Number.isFinite(p.w));
    const slope = _slopePerDay(ws6.slice(-30));
    const ratePerWeek = slope != null ? Math.round(slope * 7 * 100) / 100 : (j.weekly_rate_lbs ?? null);
    const last6 = ws6[ws6.length - 1];
    const rungList = []; for (let w = Math.floor((last6.w - 5) / 10) * 10; w > goal; w -= 10) rungList.push(w);
    parts.push(sec("Projection to 185 — the cone, not a line",
      projectionCone({ date: last6.d, w: last6.w }, goal, ratePerWeek, { provisional: !!j.rate_provisional, rungs: rungList, label: "Projected weight → 185" }) +
      `<p class="rd-meta label">A forecast is a cone, never a line. It's wide because the rate is young and water-heavy; it tightens as real weigh-ins accrue. The dated bet above is held honestly — and checked against what actually happens.</p>`));
  }
  parts.push(physicalBMI(readings, j)); // P0.7 — BMI (de-emphasized, last in Tier 1)
  // ── TIER 2 — the composition arc (episodic) — restructured across P1.x ──
  parts.push(physicalDexaCountdown(d)); // P1.1 — next-DEXA countdown (arc anchor)
  parts.push(physicalDexaBaseline(d)); // P1.2 — dated lean-vs-fat baseline (one scan, not a trend)
  parts.push(physicalVisceralCallout(d)); // P1.3 — visceral fat callout + risk band (dated)
  parts.push(physicalLeanLongevity(d)); // P1.4 — lean/ALMI longevity context (dated, demoted)
  parts.push(physicalPhenoAge(pa)); // P1.5 — transparent PhenoAge (Option A: no chronological/gap)
  parts.push(physicalFullScanExpander(d)); // P1.6 — full-scan expander, dated; +3.9 T-score suppressed
  parts.push(physicalCaptureBacklog(d, pa)); // P2.1–P2.5 — capture backlog, honestly gated
  return parts.join("");
}
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
// only from the protein pct + avg_deficit — no fabricated mechanism, just the honest
// read. Every "floor" word here grades the FLOOR pct (170), not the 190 stretch target.
function nutritionVerdict(n) {
  const hasDef = n.avg_deficit != null && Number.isFinite(Number(n.avg_deficit));
  const hasFloor = n.protein_floor_hit_pct != null && Number.isFinite(Number(n.protein_floor_hit_pct));
  const hasHit = hasFloor || (n.protein_hit_pct != null && Number.isFinite(Number(n.protein_hit_pct)));
  if (!hasDef && !hasHit) return null;
  const d = Number(n.avg_deficit), h = Number(hasFloor ? n.protein_floor_hit_pct : n.protein_hit_pct);
  const machine = [
    n.avg_calories != null ? `${fmt(n.avg_calories)} in` : null,
    n.tdee != null ? `${fmt(n.tdee)} maintenance` : null,
    hasDef ? `${d >= 0 ? "−" : "+"}${fmt(Math.abs(Math.round(d)))} kcal/day` : null,
    hasHit ? `protein ${hasFloor ? "floor" : "target"} ${fmt(h)}%` : null,
  ].filter(Boolean).join(" · ");
  const realDeficit = hasDef && d >= 250;
  const line = hasFloor ? "floor" : "target"; // which line h actually grades
  let human;
  if (!hasDef) {
    human = h === 0 ? `Protein's under the ${line} every logged day — it isn't being cleared yet.`
      : `Protein clears the ${line} about ${fmt(h)}% of days. An expenditure read is needed before the deficit half of the story lands.`;
  } else if (!realDeficit) {
    human = "No real deficit on the logged days — this reads closer to maintenance than a cut right now.";
  } else if (!hasHit || h === 0) {
    human = `The deficit's real. The protein's under the ${line} every logged day — that's the trade you're making.`;
  } else if (h < 50) {
    human = `The deficit's real, but the protein clears the ${line} on under half the days — some of the cut is coming out of muscle, not just fat.`;
  } else if (h < 100) {
    human = `The deficit's real and the protein mostly holds the ${line} — the days it slips are the ones to watch.`;
  } else {
    human = `The deficit's real and the protein clears the ${line} every day — the cut's coming off the right places.`;
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
// §2 lead (P0.2) — promote the protein signal to THE weighted headline. Graded against
// the FLOOR (the same 170 g the coaches grade against — one story on both doors), with
// the 190 g target shown as the stretch line. Ember-as-warning when the floor isn't
// cleared (never an ember "win" block, honouring HARD RULE 3). Falls back to the old
// target-graded read if the payload predates the floor fields.
function nutritionProteinLead(n) {
  const hasFloor = n.protein_floor_hit_pct != null && n.protein_floor_g != null;
  if (!hasFloor && n.protein_hit_pct == null) return "";
  const h = Number(hasFloor ? n.protein_floor_hit_pct : n.protein_hit_pct);
  const low = h < 100; // the floor is daily — anything under 100% is missed days
  const days = n.days_logged;
  const hitDays = hasFloor ? n.protein_floor_hit_days : n.protein_hit_days;
  const sub = [
    n.avg_protein_g != null ? `${fmt(n.avg_protein_g)} g avg` : null,
    hasFloor ? `floor ${fmt(n.protein_floor_g)} g` : null,
    n.protein_target_g != null ? `target ${fmt(n.protein_target_g)} g` : null,
    (days != null && hitDays != null)
      ? (hitDays === 0 ? `${hasFloor ? "floor" : "target"} missed every logged day · 0/${fmt(days)}` : `cleared ${fmt(hitDays)}/${fmt(days)} days`)
      : null,
  ].filter(Boolean).join(" · ");
  return `<section class="rd-sec nut-lead ${low ? "lead-warn" : "lead-ok"}">` +
    `<div class="lead-fig"><span class="lead-v mono">${fmt(h)}%</span>` +
    `<span class="lead-k label">protein ${hasFloor ? "floor" : "target"} hit${low ? " — under floor" : " — floor cleared"}</span></div>` +
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
    (lr.protein_floor_hit_pct ?? lr.protein_hit_pct) != null ? `protein floor ${fmt(lr.protein_floor_hit_pct ?? lr.protein_hit_pct)}%` : null,
  ].filter(Boolean).join(" → ");
  const flag = lr.deficit_label ? `<span class="nut-flag nut-flag-${esc(lr.deficit_label)}">${esc(lr.deficit_label)} cut</span>` : "";
  // "The floor" here means the real floor (170) the coaches grade against, not the
  // 190 stretch target — the pct must match the word.
  const fp = lr.protein_floor_hit_pct ?? lr.protein_hit_pct;
  let floorClause;
  if (fp === 0) floorClause = ", and that floor's being missed every logged day";
  else if (fp != null && fp < 100) floorClause = ", and right now that floor's missed most days";
  else if (fp != null && fp >= 100) floorClause = ", and right now that floor's holding";
  else floorClause = "";
  const serif = `Three pounds a week is an aggressive rate. The bench is split on it — defensible early at this size if it's monitored, but only while the protein floor holds${floorClause}. That's why the rate and the protein sit on the same line here.`;
  return `<div class="two-voice nut-lossrate"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(chain)} ${flag}</p><p class="tv-human">${esc(serif)}</p></div>`;
}
// §2 serif "what this means" annotation under the protein-vs-target chart (P0.8,
// SIGNATURE 2 human voice). Data-derived, correlative, no causal claim.
function nutritionProteinAnnotation(n) {
  const avg = n.avg_protein_g, tgt = n.protein_target_g, hit = n.protein_hit_pct;
  const floor = n.protein_floor_g, floorHit = n.protein_floor_hit_pct;
  if (avg == null || tgt == null) return "";
  const gap = Math.round(Number(tgt) - Number(avg));
  // Floor (170) and target (190) are distinct lines — "the floor" must never name
  // the 190 stretch target (the cross-door contradiction a skeptic caught).
  let txt;
  if (floor != null && floorHit === 0) {
    txt = `The ember line stays under the dotted ${fmt(tgt)} g target the whole way — and under the ${fmt(floor)} g floor too, every logged day, about ${fmt(gap)} g short of target on average. On a cut, the floor is the line that decides how much muscle the deficit costs.`;
  } else if (hit === 0) {
    txt = `The ember line stays the whole way under the dotted ${fmt(tgt)} g target${floor != null ? ` — though it clears the ${fmt(floor)} g floor on some days` : ""}, about ${fmt(gap)} g short on average.`;
  } else if (gap > 0) {
    txt = `The line sits mostly under the dotted ${fmt(tgt)} g target — about ${fmt(gap)} g short on average. The days it crosses the line are the ones holding muscle.`;
  } else {
    txt = `The line rides at or above the dotted ${fmt(tgt)} g target most days — the protein floor is holding through the cut.`;
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
    // A lean-mass-derived CROSS-CHECK on the profile floor, not a third goal —
    // labeled as an estimate so it can't read as yet another "floor" number.
    bits.push(`A lean-mass cross-check: ~${fmt(lm.floor_g_per_kg_lean)} g/kg lean puts the retention floor near ${fmt(lm.floor_protein_g)} g a day (Helms et al.).`);
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
// RQA-05 — "is the cut costing you?" the five-channel deficit-sustainability read (ported from
// the MCP get_deficit_sustainability). A degraded channel reads ember (the thing to look at),
// a holding one muted ink — never red. Honest empty state until ≥7 logged days.
function nutritionDeficitSustainability(ds) {
  if (!ds) return "";
  if (!ds.available) {
    return sec("Is the cut costing you? — the five-channel read",
      `<p class="rd-meta label">${esc(ds.reason || "The cut is too new to read its cost yet.")} It needs ~a week of logged days before the five recovery channels mean anything.</p>`);
  }
  const def = ds.deficit || {};
  const ARROW = { improving: "↑", declining: "↓", stable: "→", insufficient_data: "·" };
  const rows = (ds.channels || []).map((c) => {
    const degraded = c.status === "degraded";
    const insuf = c.direction === "insufficient_data";
    const tone = degraded ? "dsx-strain" : insuf ? "dsx-none" : "dsx-hold";
    const statusWord = degraded ? "strain" : insuf ? "too few days" : "holding";
    const delta = (!insuf && c.delta_pct) ? ` ${c.delta_pct > 0 ? "+" : ""}${fmt(c.delta_pct)}%` : "";
    return `<div class="dsx-row ${tone}"><span class="dsx-name">${esc(c.name)}</span>` +
      `<span class="dsx-dir mono">${esc(ARROW[c.direction] || "·")}${esc(delta)}</span>` +
      `<span class="dsx-status label">${esc(statusWord)}</span></div>`;
  }).join("");
  const sevTone = (ds.severity === "warning" || ds.severity === "critical") ? "dsx-sev-attn" : "dsx-sev-ok";
  const defLine = def.in_deficit
    ? `Running ~${fmt(def.avg_intake_kcal)} kcal against an estimated ${fmt(def.tdee)} TDEE — about a <strong>${fmt(def.deficit_kcal)} kcal/day (${fmt(def.deficit_pct)}%, ${esc(def.label)})</strong> deficit (TDEE is estimated, so read the % as a ballpark).`
    : "No active deficit in the window.";
  return sec("Is the cut costing you? — the five-channel read",
    `<div class="dsx-verdict ${sevTone}"><span class="dsx-count mono">${ds.degraded_count}/5</span><span class="dsx-vtext">${esc(ds.verdict || "")}</span></div>` +
    `<div class="dsx-rows">${rows}</div>` +
    `<p class="rd-meta label">${defLine} The five channels — HRV, sleep quality, recovery, habit adherence, training output — are watched together: a deficit that's working shows up as the weight falling while these <em>hold</em>; one that's costing too much shows up as three or more slipping at once. A single strained channel is noise, not a verdict. Correlative, n=1 — an early signal, never alarm.</p>`);
}
async function renderNutrition(d) {
  // The API nests macros under d.nutrition (was read flat → blank); meal/protein field
  // names are frequency/food/avg_daily_g (were count/name/grams → empty tables).
  const n = (d && d.nutrition) || (d && !d.error ? d : {});
  const [fm, ps, ds] = await Promise.all([tryJSON("/api/frequent_meals"), tryJSON("/api/protein_sources"), tryJSON("/api/deficit_sustainability")]);
  const meals = (fm && fm.meals) || [];
  const prot = (ps && (ps.protein_sources || ps.sources || ps.proteins)) || [];
  const parts = [];
  // ── §0 Hero — the verdict (P0.1). Folds calories/TDEE/deficit out of the tile row.
  const hero = nutritionHero(n);
  if (hero) parts.push(hero);
  // Nutrition is a manual end-of-day upload — always a day behind BY DESIGN. Frame the
  // latest COMPLETE day as the live state so the trailing gap reads as expected, never
  // as "hasn't logged today". Uses n.as_of / n.today_pending from the API.
  if (n.as_of) {
    parts.push(`<p class="rd-meta label nut-asof">Nutrition reflects complete days — through <strong>${esc(fmtShort(n.as_of))}</strong>${n.today_pending ? ". Today's intake uploads after the day ends." : "."}</p>`);
  }
  // ── §2 lead — the protein miss as THE weighted signal (P0.2).
  const lead = nutritionProteinLead(n);
  if (lead) parts.push(lead);
  // RQA-05 — the five-channel "is the cut costing you?" read.
  const dsx = nutritionDeficitSustainability(ds && ds.deficit_sustainability);
  if (dsx) parts.push(dsx);
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
// §8 cross-source signal board (Phase 2) — the self-policing correlation surface. Each card:
// pair + n + overlap-weeks + confidence; DIRECTION ONLY under 2 weeks (no coefficient/chip);
// Pearson + chip at >=2 weeks; "likely noise" flags; sleep-vs-weight coefficient withheld.
function sleepCorrelationBoard(cards) {
  if (!cards || !cards.length) return "";
  const card = (c) => {
    const meta = `n=${fmt(c.n)} · ${fmt(c.overlap_weeks)} wk overlap${c.lag_days ? ` · ${fmt(c.lag_days)}d lag` : ""}`;
    let read;
    if (c.withheld) {
      read = `<p class="cb-dir cb-withheld">coefficient withheld — too noisy to trust in the water-weight phase</p>`;
    } else if (c.coefficient != null) {
      read = `<p class="cb-dir mono">r = ${fmt(c.coefficient)}</p>` + correlationChip([{ label: c.predictor, r: c.coefficient, n: c.n }], { outcome: c.outcome });
    } else {
      read = `<p class="cb-dir">${c.direction === "insufficient" ? "too early to call a direction" : esc(c.direction) + " — direction only, no coefficient yet"}</p>`;
    }
    const noise = c.noise && !c.withheld ? `<span class="cb-noise">⚠ likely noise at this n</span>` : "";
    return `<article class="cb-card"><header class="cb-head"><h3 class="cb-pair">${esc(c.predictor)} <span class="cb-arrow">→</span> ${esc(c.outcome)}</h3>` +
      `<span class="cb-tag">${esc(c.confidence)}</span></header>${c.note ? `<p class="cb-note">${esc(c.note)}</p>` : ""}` +
      `<div class="cb-read">${read}${noise}</div><p class="cb-meta label">${esc(meta)}</p></article>`;
  };
  return sec("Cross-source signal board — the correlation that tells you when NOT to trust it",
    `<div class="cb-grid">${cards.map(card).join("")}</div>` +
    `<p class="rd-meta label">Every card shows its n, the overlapping weeks, and a confidence tag. Under 2 weeks of overlap it's <strong>direction only</strong> — no Pearson, no chip. Thin pairs are flagged likely-noise. The self-skepticism is the feature, not a bug.</p>` +
    explainMount("sleep_correlations"));
}
async function renderSleep(d) {
  const s = d.sleep_detail || {};
  const [circ, uni, nut, corr] = await Promise.all([tryJSON("/api/circadian"), tryJSON("/api/sleep_reconciliation"), tryJSON("/api/nutrition_overview"), tryJSON("/api/sleep_correlations")]);
  const parts = [];
  // §0 — the forecast LEADS (prospective, not retrospective).
  const fcHero = circadianForecast(circ);
  if (fcHero) parts.push(fcHero);
  // §1 — last night, demoted to EVIDENCE beneath the forecast.
  const lastNightHdr = "Last night — the evidence" + (lastNightDate(s, uni) ? ` · the night of ${lastNightDate(s, uni)}` : "");
  // #495/M-9: when the API substituted an older night's Whoop recovery (its own
  // night rides in recovery_night_of), caption the splice everywhere those
  // figures render — never night-A hours + night-B recovery under one header.
  const recNote = s.recovery_night_of
    ? `<p class="rd-meta label">Recovery, HRV and resting HR are from the night of ${fmtShort(s.recovery_night_of)} — the latest night with a Whoop reading; last night's isn't in yet.</p>`
    : "";
  if (Object.values(s).some(has)) {
    parts.push(sec(lastNightHdr, figs([s.total_sleep_hours != null && fig(fmt(s.total_sleep_hours, 1), "hours"), s.sleep_efficiency != null && fig(fmt(s.sleep_efficiency) + "%", "efficiency"), s.recovery_score != null && fig(fmt(s.recovery_score), "recovery"), s.hrv != null && fig(fmt(s.hrv), "hrv ms"), s.sleep_score != null && fig(fmt(s.sleep_score), "composite score")]) + recNote + `<p class="rd-meta label">One night is noise, not a verdict — it's evidence the forecast above gets graded against. The composite "score" is Eight Sleep's black box; the hours, efficiency and stages are what actually move it.</p>`));
    if (s.deep_sleep_hours != null && s.rem_sleep_hours != null) parts.push(sec("Last night's stages", stackedBar([{ label: "Deep", value: s.deep_sleep_hours, tone: "ember" }, { label: "REM", value: s.rem_sleep_hours, tone: "ink" }, { label: "Light", value: Math.max(0, (s.total_sleep_hours || 0) - (s.deep_sleep_hours || 0) - (s.rem_sleep_hours || 0)), tone: "faint" }], { label: "Hours by stage", unit: "h" })));
    // §2 — dual-device stage agreement (P0.3): Eight Sleep % vs Whoop % per stage.
    const _wh = s.whoop_hours; const _dev = [];
    if (_wh) {
      if (s.deep_pct != null && s.deep_sleep_hours != null) _dev.push({ label: "Deep", a: s.deep_pct, b: (s.deep_sleep_hours / _wh) * 100 });
      if (s.rem_pct != null && s.rem_sleep_hours != null) _dev.push({ label: "REM", a: s.rem_pct, b: (s.rem_sleep_hours / _wh) * 100 });
      if (s.light_pct != null && s.deep_sleep_hours != null && s.rem_sleep_hours != null) _dev.push({ label: "Light", a: s.light_pct, b: Math.max(0, 100 - (s.deep_sleep_hours / _wh) * 100 - (s.rem_sleep_hours / _wh) * 100) });
    }
    if (_dev.length) parts.push(sec("Two devices, one night — agreement, not truth", dumbbell(_dev, { label: "% of night per stage", aLabel: "Eight Sleep", bLabel: "Whoop", unit: "%" }) + `<p class="rd-meta label">Wearable staging is an estimate, not a sleep-lab PSG. The gap between two devices is the honest uncertainty — agreement, not truth.</p>`));
    // §3 — regularity / consistency + social jet-lag (P0.4). Empty state until a weekend.
    if (s.avg_bedtime || s.avg_waketime) {
      const _sjl = (s.social_jet_lag_hrs != null && s.avg_bedtime_weekday && s.avg_bedtime_weekend)
        ? `<p class="rd-meta label">Social jet-lag <strong>${fmt(s.social_jet_lag_hrs)}h</strong> — the drift between weekday (${esc(s.avg_bedtime_weekday)}) and weekend (${esc(s.avg_bedtime_weekend)}) bedtime. Regularity predicts more than any single night's architecture.</p>`
        : `<p class="rd-meta label">Social jet-lag — the weekday-vs-weekend bedtime drift — fills in once there's a weekend in the window. Regularity predicts more than single-night architecture.</p>`;
      parts.push(sec("Regularity — when, not just how long", figs([s.avg_bedtime && fig(s.avg_bedtime, "avg bedtime"), s.avg_waketime && fig(s.avg_waketime, "avg wake")]) + _sjl));
    }
    // §4 — stage composition over the week (P0.5): stacked hours/night, refuses <4.
    const _stageNights = (d.sleep_trend || []).map((n) => {
      if (n.deep_sleep_hours == null || n.rem_sleep_hours == null) return null;
      const light = n.hours != null ? Math.max(0, n.hours - n.deep_sleep_hours - n.rem_sleep_hours) : 0;
      return { date: n.date, deep: n.deep_sleep_hours, rem: n.rem_sleep_hours, light };
    }).filter(Boolean);
    if (_stageNights.length) parts.push(sec("Stage composition over the week", stackedDayColumns(_stageNights, [{ key: "deep", label: "deep", tone: "lift" }, { key: "rem", label: "REM", tone: "cardio" }, { key: "light", label: "light", tone: "mob" }], { label: "hours by stage · per night", legendUnit: "h", minPoints: 4, emptyMsg: "Stage composition draws in at 4+ nights." })));
    // §5 — environment: bed temp vs deep sleep (P0.6), observation-only (bed temp = a band).
    const _env = (d.sleep_trend || []).filter((n) => n.bed_temp_f != null && n.deep_sleep_hours != null);
    const _norm = (series) => { const vs = series.map((p) => p.value).filter(Number.isFinite); if (vs.length < 2) return series; const mn = Math.min(...vs), mx = Math.max(...vs); return series.map((p) => ({ date: p.date, value: mx > mn ? Math.round((p.value - mn) / (mx - mn) * 100) : 50 })); };
    if (_env.length >= 4) {
      const _t = _env.map((n) => ({ date: n.date, value: n.bed_temp_f })), _dp = _env.map((n) => ({ date: n.date, value: n.deep_sleep_hours }));
      parts.push(sec("Environment — bed temp vs deep sleep", dualLineChart(_norm(_t), _norm(_dp), { aLabel: "bed temp", bLabel: "deep sleep", showGap: false, label: "both normalized 0–100 — co-movement only" }) + figs([s["30d_avg_temp"] != null && fig(fmt(s["30d_avg_temp"]) + "°F", "avg bed temp"), s.optimal_temp_f != null && fig(fmt(s.optimal_temp_f) + "°F", "best-scoring temp")]) + `<p class="rd-meta label">Bed temperature against deep-sleep hours, both normalized so the shapes compare. Observation only — bed temp is an optimal band, not monotonic; no coefficient at this n.</p>`));
    } else if (_env.length) {
      parts.push(sec("Environment — bed temp vs deep sleep", empty("The temp-vs-deep overlay draws in at 4+ nights with both readings.")));
    }
    // §7 — autonomic downshift readout (P0.7): a STATE snapshot (HRV + RHR + recovery), honest
    // at n=1 because it's a state, not a claimed relationship. Low ≠ red — just muted framing.
    if (s.recovery_score != null || s.hrv != null || s.rhr != null) {
      const _rec = s.recovery_score;
      const state = _rec == null ? "not assessable" : (_rec >= 67 ? "downshifted — parasympathetic" : _rec >= 34 ? "partial downshift" : "stayed elevated — sympathetic");
      parts.push(sec("Autonomic downshift — did the body let go?",
        figs([_rec != null && fig(fmt(_rec), "recovery"), s.hrv != null && fig(fmt(s.hrv) + "ms", "HRV"), s.rhr != null && fig(fmt(s.rhr), "resting HR")]) + recNote +
        `<p class="rd-meta label">Tonight's autonomic state: <strong>${esc(state)}</strong>. HRV up + RHR down = the body downshifting into recovery. A one-night state snapshot — honest at n=1, not a claimed relationship.</p>`));
    }
    parts.push(sec("Sleep-score trend · latest = last night", lineChart(d.sleep_trend || [], { valueKey: "sleep_score", label: "Sleep score · nightly", spine: true, emptyMsg: "The sleep-score trend fills in nightly." })));
  }
  // §6 — recovery readout (P1.1): HRV / RHR / recovery framed as what sleep DEFENDS in a
  // deficit (cross-link to training). RHR-down = good (ember-positive); never red.
  if (s.recovery_score != null || s.hrv != null || s.rhr != null) {
    parts.push(sec("Recovery — what the sleep defends",
      figs([s.recovery_score != null && fig(fmt(s.recovery_score), "recovery"), s.hrv != null && fig(fmt(s.hrv) + "ms", "HRV"), s.rhr != null && fig(fmt(s.rhr), "resting HR"), s["30d_avg_recovery"] != null && fig(fmt(s["30d_avg_recovery"]), "30d avg recovery")]) + recNote +
      `<p class="rd-meta label">In a calorie deficit, sleep is what protects recovery, HRV and a low resting heart rate — the buffer that lets the training still land. RHR drifting down is the win here. See <a href="/data/training/">Training</a> for what it buys.</p>`));
  }
  // §6b — last-meal-time cross-link (P1.2): reuse the nutrition eating window, observation-only.
  const _ew = nut && nut.eating_window;
  if (_ew && _ew.avg_last_meal) {
    parts.push(sec("Last meal → sleep — the cross-link",
      figs([fig(esc(_ew.avg_last_meal), "avg last meal"), _ew.avg_hours != null && fig(fmt(_ew.avg_hours) + "h", "eating window")]) +
      `<p class="rd-meta label">Eating late can blunt deep sleep. Average last meal lands at ${esc(_ew.avg_last_meal)}, pulled from the <a href="/data/nutrition/">nutrition</a> log — observation only; the day-lagged version lives in the board below once the overlap is deep enough.</p>`));
  }
  // §8 — the cross-source signal board (P2.1+).
  const board = sleepCorrelationBoard(corr && corr.cards);
  if (board) parts.push(board);
  const _hasSleep = !!fcHero || Object.values(s).some(has);
  // P1.3 — subjective "how rested" 1–5 (not captured) → honest empty state.
  if (_hasSleep) parts.push(sec("How rested — coming online", `<div class="nut-coming"><p class="rd-archive">A morning 1–5 "how rested do you feel" check-in isn't captured yet. It's the ground truth the wearables miss — the night a tracker calls great that still felt like garbage. Once logged, it grades the forecast and the score against how the body actually felt. <span class="confidence conf-low">needs capture</span></p></div>`));
  // P1.4 — caffeine + alcohol timing (not captured; PRIVACY-tiered) → honest empty state.
  if (_hasSleep) parts.push(sec("Caffeine & alcohol timing — coming online", `<div class="nut-coming"><p class="rd-archive">The two biggest modifiable levers on sleep — caffeine and alcohol timing — aren't captured yet. Once logged they'd feed the forecast's wind-down and consistency anchors directly, and the board below. <strong>Privacy-tiered:</strong> these behavioural inputs stay private by default and won't render publicly without an explicit opt-in. <span class="confidence conf-low">needs capture · private</span></p></div>`));
  // P1.5 — light exposure AM/PM (not captured; screen-time proxy) → honest empty state.
  if (_hasSleep) parts.push(sec("Light exposure (AM/PM) — coming online", `<div class="nut-coming"><p class="rd-archive">Morning and evening light is the master circadian anchor, but it isn't measured directly. An evening screen-time proxy could stand in — flagged honestly as a proxy, not lux. Until then the forecast's wind-down anchor leans on behaviour, not measured light. <span class="confidence conf-low">needs capture · proxy</span></p></div>`));
  // §9 — forecast self-grading (P2.9): does the forecast earn its lead? Placeholder until ~2 weeks.
  if (_hasSleep) parts.push(sec("Forecast self-grading — coming online", `<div class="nut-coming"><p class="rd-archive">The forecast earns the top of the page only if it's right. Did the nights it called high-risk actually score lower? That check needs ~2 weeks of paired forecasts and outcomes before it means anything — until then the forecast leads on its mechanism, not yet its track record. A prediction you don't grade is a horoscope. <span class="confidence conf-low">grades in ~2 weeks</span></p></div>`));
  // Unified sleep — Whoop + Eight Sleep + Apple merged, best source per field.
  if (uni && uni.available) {
    const srcs = (uni.sources_present || []).map(ttl).join(", ");
    parts.push(sec("Unified sleep — sources reconciled" + (uni.night_of ? ` · the night of ${fmtShort(uni.night_of)}` : ""), figs([uni.total_duration_hours != null && fig(fmt(uni.total_duration_hours, 1), "hours · merged"), uni.recovery_score != null && fig(fmt(uni.recovery_score), "recovery"), uni.hrv_ms != null && fig(fmt(uni.hrv_ms), "hrv ms"), uni.sleep_efficiency_pct != null && fig(fmt(uni.sleep_efficiency_pct) + "%", "efficiency")]) + kvtable({ rem_pct: uni.rem_pct, deep_pct: uni.deep_pct, light_pct: uni.light_pct, awake_pct: uni.awake_pct, respiratory_rate: uni.respiratory_rate, room_temp_c: uni.room_temp_c, bed_temp_c: uni.bed_temp_c }) + (srcs ? `<p class="rd-meta label">merged from ${esc(srcs)} — best source per field</p>` : "")));
  }
  if (!parts.length) return empty("No sleep data yet — score, stages, HRV and recovery appear here nightly.");
  return parts.join("") + note("Correlative — tonight's forecast leads; last night and the trend are the evidence it earns its place against.");
}
// ── /data/mind/ — "the layer the machine can't see, awaiting its human." The MOST
// sensitive page: vices NEVER named (private unnamed streaks); a relapse is a muted RESET, never
// red, never shame (the site-wide reserved-red is EXCLUDED here); capture is invitation, never
// obligation. `d` = /api/mind_overview.
// P0.1 — vice restraint, reset-honest: lead with CUMULATIVE days held (resilience across resets,
// never erased) over a fragile streak. Streaks are UNNAMED (only counts + held/reset, never the
// name). Resets read muted, framed as a restart — no red, no alarm, no shame.
function mindRestraint(vices, timeline) {
  if (!vices.length) return "";
  const held = vices.filter((v) => v.holding);
  const reset = vices.filter((v) => !v.holding);
  const cumulative = (timeline || []).reduce((s, day) => s + (Number(day.held) || 0), 0);
  const longest = vices.reduce((mx, v) => Math.max(mx, Number(v.current_streak) || 0), 0);
  const RUNGS = [1, 3, 7, 14, 30, 60, 90];
  const ladder = RUNGS.map((r) => `<span class="mr-rung ${longest >= r ? "mr-crossed" : "mr-future"}">${r}d</span>`).join("");
  const heldChips = held.map((v) => `<span class="mr-chip">held ${fmt(v.current_streak)}d</span>`).join("");
  const resetLine = reset.length
    ? `<p class="mr-reset label">${reset.length} restarting now — a reset isn't a failure shown in red, it's a restart; the cumulative days above still count.</p>` : "";
  return sec("Restraint — held, and held before",
    `<div class="mr-cum"><span class="mr-cum-v num">${cumulative}</span><span class="mr-cum-k label">cumulative days of restraint held this cycle — a reset never erases them</span></div>` +
    `<p class="rd-meta label">Across ${vices.length} private commitments (kept unnamed, on purpose), <strong>${held.length} held right now</strong>${longest ? `, the longest running ${longest} day${longest === 1 ? "" : "s"}` : ""}.</p>` +
    (heldChips ? `<div class="mr-chips">${heldChips}</div>` : "") +
    `<div class="mr-ladder" aria-label="restraint milestones">${ladder}</div>` +
    resetLine +
    `<p class="rd-meta label">These are private restraints — kept off the record by name, by design. The point is resilience over a perfect streak: the days already held are real, whether or not today is one of them.</p>`);
}
// P0.2 — the inviting absence: at week one the subjective layer is empty (mood 0, journal 0).
// That emptiness is the POINT — the machine's blind spot — so it reads as a dignified invitation,
// never a hollow "no data" axis. A one-tap entry affordance is present (the mechanic itself is
// P1, gated). No nag, no guilt, no streak to keep.
function mindInvitingAbsence(m) {
  const moodN = Number(m.mood_entries_count) || 0;
  if (moodN >= 4) return ""; // once mood accrues, the sparkline (P1/P2) takes over
  return sec("How it felt — the layer the machine can't see",
    `<div class="mi-absence"><p class="mi-lead">This is where how-it-felt goes. The machine has every number about the body this week — recovery, sleep, strain, the scale — and <em>nothing</em> about what any of it actually felt like.</p>` +
    `<p class="mi-sub label">Nothing's logged this cycle yet, and that emptiness is the honest part of this page, not an error or a gap to scold. When there's a moment, one tap starts it — no streak to keep, no guilt for the days you don't.</p>` +
    `<div class="mi-entry"><button class="mi-cta" type="button" data-mind-entry>＋ note how today felt</button><span class="mi-entry-note label">the one-tap capture is being wired — this space is held for it</span></div></div>`);
}
// P0.3 — the Mind pillar, decomposed (anti-black-box): it's not a single handed-down score, it's
// the sum of reflection / mood / restraint / conversation depth. Most await input at week one, so
// the pillar reads as honestly FORMING — shown with its inputs, never hidden behind a number.
function mindPillarDecomposed(m) {
  const inputs = [
    { label: "reflection — journal entries", val: m.journal_entries_30d, has: (m.journal_entries_30d || 0) > 0 },
    { label: "mood — daily check-ins", val: m.mood_entries_count, has: (m.mood_entries_count || 0) > 0 },
    { label: "restraint — temptations resisted", val: m.resist_rate_pct != null ? m.resist_rate_pct + "%" : null, has: m.resist_rate_pct != null },
    { label: "depth — meaningful conversation", val: m.meaningful_pct ? m.meaningful_pct + "%" : null, has: (m.meaningful_pct || 0) > 0 },
  ];
  const rows = inputs.map((i) => `<div class="mp-row"><span class="mp-l">${esc(i.label)}</span><span class="mp-v mono ${i.has ? "" : "mp-await"}">${i.has ? esc(String(i.val)) : "awaiting input"}</span></div>`).join("");
  return sec("The Mind pillar — what it's built from",
    `<div class="mp-rows">${rows}</div>` +
    `<p class="rd-meta label">The Mind pillar isn't a single score handed down — it's the sum of reflection, mood, restraint, and the depth of the week's conversations. Most of those still await their human at week one, so the pillar is honestly <em>forming</em>, not hidden behind a number.</p>`);
}
// P0.4 — the Third Wall, centrepiece: the machine sees the body; it can't see the meaning. The
// AI's weekly read vs Matthew's response slot, invitingly EMPTY (held, not absent — the human
// gets the last word). Reuses the two-voice + held-space pattern. No reply mechanic (gated).
async function mindThirdWall() {
  let e = null;
  try {
    const list = await tryJSON("/api/field_notes");
    const wk = list && list.entries && list.entries[0] && list.entries[0].week;
    if (wk != null) { const full = await tryJSON(`/api/field_notes?week=${encodeURIComponent(wk)}`); e = full && full.entry; }
  } catch (_e) { /* honest placeholder below */ }
  const aiText = e && (e.ai_present || e.ai_affirming || e.ai_cautionary);
  const mattText = e && (e.matthew_notes || e.matthew_agreement);
  const aiBlock = `<p class="tv-machine"><span class="tv-mark">›</span> The AI's read of the week: ${esc(aiText || "the machine writes its weekly read here — what the body's numbers say the week was.")}</p>`;
  const mattBlock = mattText
    ? `<p class="tv-human">${esc(mattText)}</p>`
    : `<div class="mw-pending"><span class="mw-who label">Matthew — the last word</span><p class="mw-lead">Held for Matthew's reply.</p><p class="mw-sub label">The machine sees the body; it can't see what it meant. This space waits for his answer — invitation, not obligation. When he writes back, it lands right here, beside the read.</p></div>`;
  return sec("The Third Wall — the machine's read, and the last word",
    `<div class="two-voice mind-wall">${aiBlock}${mattText ? mattBlock : ""}</div>${mattText ? "" : mattBlock}` +
    `<p class="rd-meta label">Every other page is the machine watching — automatic, all week. This is the one place the human gets the final say over what the numbers actually meant.</p>`);
}
async function renderMind(d) {
  const m = d.mind || {};
  const vices = d.vice_streaks || [];
  const parts = [];
  parts.push(mindRestraint(vices, d.vice_timeline)); // P0.1 — unnamed, cumulative-first restraint
  parts.push(await mindThirdWall()); // P0.4 — Third Wall centrepiece (the last word, held)
  parts.push(mindInvitingAbsence(m)); // P0.2 — the inviting absence (not a hollow axis)
  parts.push(mindPillarDecomposed(m)); // P0.3 — Mind pillar decomposed to its inputs
  return parts.join("") || empty("The inner-life view fills in as restraint, mood, and reflection accrue.");
}
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
// One machine-bet card: domains + status badge in the header, the falsifiable
// statement as the body, the verdict trail once graded, the founding evidence
// collapsed behind a details toggle (it's long — 4-5 cited sentences).
// Status → badge: confirmed earns ember (a live confirmed signal); refuted stays
// muted ink (down is never red); pending/confirming are plain machine labels.
function hypCard(h) {
  const status = String(h.status || "pending");
  const badgeCls = status === "confirmed" ? "rd-badge rd-badge-live" : "rd-badge";
  const domains = (h.domains || []).map(esc).join(" ↔ ") || "cross-domain";
  const checks = Math.round(Number(h.check_count) || 0);
  const formed = h.created_at ? String(h.created_at).slice(0, 10) : null;
  const checked = h.last_checked ? String(h.last_checked).slice(0, 10) : null;
  const decided = status === "confirmed" || status === "refuted";
  const meta = [
    h.confidence && `confidence ${h.confidence}`,
    checks === 0 ? "not yet checked" : `${checks} check${checks === 1 ? "" : "s"}`,
    formed && `formed ${formed}`,
    checked && `last checked ${checked}`,
  ].filter(Boolean).join("  ·  ");
  const verdict = h.last_evidence
    ? `<p class="rd-why hyp-verdict"><span class="label">${decided ? "the verdict" : "latest check"} — </span>${esc(h.last_evidence)}</p>`
    : "";
  const founding = h.evidence && typeof h.evidence === "string"
    ? `<details class="hyp-ev"><summary class="label">the data behind it</summary><p class="rd-why">${esc(h.evidence)}</p></details>`
    : "";
  return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${domains}</h3><span class="${badgeCls}">${esc(status)}</span></header>` +
    `<p class="rd-why">${esc(h.hypothesis || "")}</p>${verdict}${founding}<p class="rd-meta label">${esc(meta)}</p></article>`;
}
async function renderDiscoveries(d) {
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
  // What the machine suspects — the hypothesis engine's REAL live bets
  // (/api/hypotheses: formed from the data, re-checked every Sunday, graded
  // confirmed/refuted or expired). The static library templates remain the
  // fallback for the empty windows (30-day hard expiry / post-reset).
  const live = await tryJSON("/api/hypotheses");
  const all = (live && live.hypotheses) || [];
  const bets = all.filter((h) => h.status !== "archived");
  const expired = all.length - bets.length;
  const unchecked = bets.length > 0 && bets.every((h) => !Math.round(Number(h.check_count) || 0));
  let hs;
  if (bets.length) {
    const intro = `<p class="rd-meta label">Falsifiable bets the engine formed from the data — re-checked every Sunday. A bet gets confirmed, refuted, or expires undecided; all three are shown.${unchecked ? " None checked yet — the first weekly check is upcoming." : ""}</p>`;
    const expiredNote = expired ? `<p class="rd-meta label">${expired} earlier bet${expired === 1 ? "" : "s"} expired before the data could decide ${expired === 1 ? "it" : "them"} — shown as the honest cost of betting in public.</p>` : "";
    hs = sec("What the machine suspects", intro + `<div class="rd-cards">${bets.map(hypCard).join("")}</div>` + expiredNote);
  } else {
    hs = hyp.length
      ? sec("Hypotheses under test", `<div class="rd-cards">${hyp.map((h) => card(h.name, h.hypothesis || h.description, h.evidence_tier)).join("")}</div>`)
      : "";
  }
  if (!fs && !is && !hs)
    return empty("No discoveries yet — real correlations and findings surface here as the data accrues. This cycle is only days old, so it needs more data first.");
  return fs + is + hs + note("Correlative leads, not conclusions — N=1, FDR-corrected where computed, and n is small this early in the cycle.");
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
  // P2.2 — the live card draws its served-but-never-drawn record: the check-in
  // streak grid (one cell per day of the run: checked-in = ember, checked-but-
  // missed = faint, ahead = outline) + the progress figs. Real cells only —
  // the grid renders exactly what was logged, gaps stay gaps.
  const checkinGrid = (c) => {
    const dur = Number((c.progress || {}).duration_days || c.duration_days) || 0;
    const checks = c.daily_checkins;
    if (!dur || !checks || typeof checks !== "object") return "";
    const entries = Array.isArray(checks) ? checks : Object.entries(checks).map(([date, v]) => ({ date, completed: v === true || (v && v.completed) }));
    const byDate = new Map(entries.map((e) => [String(e.date).slice(0, 10), !!(e.completed ?? e.done ?? e.success ?? true)]));
    const start = c.activated_at || c.start_date;
    if (!start) return "";
    const t0 = Date.parse(String(start).slice(0, 10) + "T12:00:00");
    if (!Number.isFinite(t0)) return "";
    const cells = Array.from({ length: Math.min(dur, 60) }, (_, i) => {
      const dd = new Date(t0 + i * 86400000).toISOString().slice(0, 10);
      const v = byDate.get(dd);
      const cls = v === true ? "is-done" : v === false ? "is-miss" : "";
      return `<i class="cg-cell ${cls}" title="${esc(dd)}${v === true ? " · done" : v === false ? " · missed" : ""}"></i>`;
    }).join("");
    return `<div class="cg" role="img" aria-label="Daily check-ins, ${dur} days">${cells}</div>`;
  };
  const liveCard = (c) => {
    const done = !!c.completed_at || c.status === "completed";
    const active = !done && (c.status === "active" || !!c.activated_at);
    const pr = c.progress || {};
    const progFigs = active && pr.duration_days
      ? `<p class="rd-meta label">${[pr.checkin_days != null && `${pr.checkin_days}/${pr.duration_days} days checked in`, pr.completion_pct != null && `${fmt(pr.completion_pct)}% complete`, pr.success_rate != null && `${fmt(pr.success_rate)}% success`].filter(Boolean).join("  ·  ")}</p>`
      : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(c.name || ttl(c.challenge_id || "Challenge"))}</h3><span class="rd-badge ${active ? "rd-badge-live" : ""}">${done ? "completed" : active ? "active" : "candidate"}</span></header>${checkinGrid(c)}${progFigs}<p class="rd-meta label">${[c.character_xp_awarded != null && c.character_xp_awarded + " XP", c.badge_earned && `${icon("milestone")} badge`].filter(Boolean).join("  ·  ")}</p></article>`;
  };
  // P2.2 — catalog cards carry their evidence: the summary, the tier chip, and
  // the recommending board persona. The served `icon` field is emoji — never drawn (§8).
  const catCard = (c) => {
    const [tc, tl] = c.evidence_tier ? evClass(c.evidence_tier) : [null, null];
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${c.category ? `<span class="ch-ric">${domainIcon(c.category)}</span>` : ""}${esc(c.name)}</h3><span class="rd-badge">${esc(c.status)}</span></header>${c.one_liner ? `<p class="rd-why">${esc(c.one_liner)}</p>` : ""}${c.evidence_summary && !isBad(c.evidence_summary) ? `<p class="rd-line">${esc(c.evidence_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${[c.category, c.difficulty, c.duration_days && c.duration_days + "d", c.board_recommender && "recommended by " + c.board_recommender].filter(Boolean).map(esc).join("  ·  ")}</p></article>`;
  };
  const liveSec = sec("Taken on", live.length ? `<div class="rd-cards">${live.map(liveCard).join("")}</div>` : empty("None taken on yet this cycle."));
  // "Available now" vs "Backlog" was a distinction without a difference — both are
  // catalog ideas not yet taken on. One backlog.
  const candidates = avail.concat(backlog);
  const backSec = candidates.length ? sec(`Backlog (${candidates.length})`, `<div class="rd-cards">${candidates.slice(0, 80).map(catCard).join("")}</div>`) : "";
  return banner + head + liveSec + backSec + note("An N=1 instrument — reader participation is deferred.");
}
function renderProtocols(d) { const ps = (d.protocols || []).slice().sort((a, b) => (/(active|running|on)/i.test(a.status || "") ? 0 : 1) - (/(active|running|on)/i.test(b.status || "") ? 0 : 1)); if (!ps.length) return empty("No active protocols yet."); return figs([fig(ps.length, "active protocols")]) + `<div class="rd-cards">${ps.map((p) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}<p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>` + note("Matthew's deliberate interventions, read-only. Not medical advice."); }
async function renderExperiments(d) {
  const xs = d.experiments || [];
  if (!xs.length) return empty("No experiments yet — the library is loading.");
  // P2.1 — the arc header: what the whole experiment PROGRAM has learned so far
  // (the same synthesis the coaching page reads; it was never surfaced here).
  const syn = await tryJSON("/api/experiment_synthesis");
  const arcBand = syn && syn.throughline && !isBad(syn.throughline)
    ? `<div class="rd-obs"><p class="dx-kicker label">what the program has learned${syn.week_count ? ` · week ${esc(String(syn.week_count))}` : ""}</p><p class="rd-primary">${esc(syn.throughline)}</p>${syn.arc && !isBad(syn.arc) ? `<p class="rd-why">${esc(String(syn.arc).slice(0, 420))}${String(syn.arc).length > 420 ? "…" : ""}</p>` : ""}</div>`
    : "";
  const running = xs.filter((x) => x.origin !== "library");
  const lib = xs.filter((x) => x.origin === "library");
  const avail = lib.filter((x) => x.status === "available");
  const backlog = lib.filter((x) => x.status === "backlog");
  const head = figs([fig(running.length, "running"), avail.length ? fig(avail.length, "ready to run") : "", fig(backlog.length, "in backlog")]);
  // P2.1 — running cards carry their served-but-never-drawn instrumentation:
  // the progress bar, the primary metric, the mechanism, compliance; completed
  // runs become "receipt" cards — baseline→result drawn (the effect size), the
  // key finding as the headline, the reflection as the second (human) voice.
  const runCard = (x) => {
    const done = /complete|done|ended|closed/i.test(x.status || "");
    const verdict = x.hypothesis_confirmed === true ? "confirmed" : x.hypothesis_confirmed === false ? "not confirmed" : (x.outcome || x.status || "running");
    const prog = !done && x.planned_duration_days && x.days_in != null
      ? `<div class="pr-row"><span class="pr-bar"><i style="width:${Math.max(2, Math.min(100, Number(x.progress_pct) || (Number(x.days_in) / Number(x.planned_duration_days)) * 100)).toFixed(0)}%"></i></span><span class="label">day ${esc(String(x.days_in))} of ${esc(String(x.planned_duration_days))}</span></div>`
      : "";
    const compliance = x.compliance_pct != null
      ? `<div class="pr-row"><span class="pr-bar pr-bar--ink"><i style="width:${Math.max(2, Math.min(100, Number(x.compliance_pct))).toFixed(0)}%"></i></span><span class="label">compliance ${fmt(x.compliance_pct)}%</span></div>`
      : "";
    const receipt = done && Number.isFinite(Number(x.baseline_value)) && Number.isFinite(Number(x.result_value))
      ? dumbbell([{ label: x.primary_metric || "primary metric", a: Number(x.baseline_value), b: Number(x.result_value) }], { aLabel: "baseline", bLabel: "result", unit: "" })
      : "";
    const finding = done && x.key_finding && !isBad(x.key_finding) ? `<p class="rd-line"><strong>${esc(x.key_finding)}</strong></p>` : "";
    const reflect = done && x.reflection && !isBad(x.reflection) ? `<p class="rd-reflect">“${esc(x.reflection)}”</p>` : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge ${done ? "" : "rd-badge-live"}">${esc(x.status || "")}</span></header>${x.hypothesis ? `<p class="rd-why"><span class="label">hypothesis</span> ${esc(x.hypothesis)}</p>` : ""}${x.mechanism && !isBad(x.mechanism) ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(x.mechanism)}</p>` : ""}${prog}${compliance}${finding}${receipt}${reflect}${x.result_summary && !isBad(x.result_summary) && !finding ? `<p class="rd-line">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${[verdict, x.primary_metric && !done && "tracking " + esc(x.primary_metric), x.grade && "grade " + esc(x.grade)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`;
  };
  const libCard = (x) => {
    // P2.1 — evidence_tier gets the evClass chip treatment (strong/moderate/emerging).
    const [tc, tl] = x.evidence_tier ? evClass(x.evidence_tier) : [null, null];
    const meta = [x.pillar, x.difficulty, x.evidence_citation && "src: " + x.evidence_citation].filter(Boolean).map(esc).join("  ·  ");
    const link = x.source_url ? ` · <a class="supp-ev-link" href="${esc(x.source_url)}" target="_blank" rel="noopener">evidence ↗</a>` : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge">${esc(x.status)}</span></header>${x.hypothesis ? `<p class="rd-why">${esc(x.hypothesis)}</p>` : x.result_summary ? `<p class="rd-why">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${meta}${link}</p></article>`;
  };
  const runSec = sec("Running now", running.length ? `<div class="rd-cards">${running.map(runCard).join("")}</div>` : empty("Nothing running yet this cycle — the experiment just started."));
  const pipeline = [...avail, ...backlog];
  const pipeSec = pipeline.length ? sec(`In the pipeline (${pipeline.length})`, `<div class="rd-cards">${pipeline.slice(0, 60).map(libCard).join("")}</div>`) : "";
  return arcBand + head + runSec + pipeSec + note("N=1 instrument. “Running now” are live on the ledger; the pipeline is the experiment library — candidates not yet run.");
}
// §0 keystone hero (P0.1) — THE honesty fix. The old panel showed a bare Pearson (r=0.88,
// n=7) as if proven. Rebuild: lead with the group + direction + STRENGTH word; n is the
// loudest element, stamped "early signal, not proven"; coefficient/chip WITHHELD until >=2
// weeks overlap. Two-voice. Binds keystone_correlations.
function habitsKeystone(corrs) {
  if (!corrs || !corrs.length) return "";
  const k = corrs[0]; // strongest by |r|
  const n = k.n_days;
  const ready = n >= 14;
  const dir = k.correlation_r >= 0 ? "moves up with" : "moves against";
  const strength = Math.abs(k.correlation_r) >= 0.6 ? "strong" : Math.abs(k.correlation_r) >= 0.3 ? "moderate" : "faint";
  const machine = `${ttl(k.group)} ${dir} the day grade · ${strength} direction · n=${fmt(n)} days — early signal, not proven${ready ? "" : " · coefficient withheld until 2 weeks"}`;
  const serif = `Of everything tracked, ${ttl(k.group)} is the group most pulling the day up so far. On ~${fmt(n)} days that's a lead, not a law — the number to trust here is n, not a coefficient. ${ready ? "It now has the overlap to carry a real correlation, below." : "It earns a real coefficient once there are two weeks of overlap."}`;
  // P2.1 — keystone calibration, honesty-gated. Below 2 weeks of overlap: direction only,
  // no Pearson, no chip (P0.1). At n>=14 the coefficient surfaces inside the sleep board's
  // own confidence-card DNA — n + overlap weeks + a confidence tier + a "likely noise" guard
  // when |r| is small even with the overlap — so the magnitude never reads louder than its n.
  let card = "";
  if (ready) {
    const absr = Math.abs(k.correlation_r);
    const confidence = absr >= 0.6 ? "suggestive · strong" : absr >= 0.3 ? "suggestive · moderate" : "weak — treat as noise";
    const noise = absr < 0.3 ? `<span class="cb-noise">⚠ likely noise at this n — direction only</span>` : "";
    const read = absr < 0.3
      ? `<p class="cb-dir">${esc(dir)} the day grade — direction only, coefficient too weak to trust</p>`
      : `<p class="cb-dir mono">r = ${(Math.round(k.correlation_r * 100) / 100).toFixed(2)}</p>` + correlationChip([{ label: k.group, r: k.correlation_r, n }], { outcome: "the day grade" });
    card = `<div class="cb-grid"><article class="cb-card"><header class="cb-head"><h3 class="cb-pair">${esc(ttl(k.group))} <span class="cb-arrow">→</span> the day grade</h3><span class="cb-tag">${esc(confidence)}</span></header><div class="cb-read">${read}${noise}</div><p class="cb-meta label">n=${fmt(n)} · ${fmt(Math.round((n / 7) * 10) / 10)} wk overlap · N=1, correlative</p></article></div>`;
  }
  return sec("The keystone — one early signal, not a law",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>` + card +
    `<p class="rd-meta label">What would sharpen this: more overlapping days. At ~1 week it's direction-only; the magnitude is withheld until the n is honest. Even past two weeks it stays N=1 and correlative — a card that flags itself as noise when the coefficient is thin.</p>`);
}
// §4 habit state taxonomy (P0.5) — every habit tagged by STATE on ONE ember+ink ramp +
// position/marker (NOT a rainbow). Backlog/never-started SHOWN (most apps hide it). No red.
// P1.1 — auto-derived per-habit context (time-of-day + do/avoid/maintain), rendered as
// small mono tags. Heuristic, name-only inference → always shown under an "auto-derived"
// label, never as fact. "anytime"/"do" are the silent defaults (no tag = no false signal).
function habitTaxonomyChips(tax) {
  if (!tax) return "";
  const out = [];
  if (tax.time_of_day && tax.time_of_day !== "anytime") out.push(`<span class="hb-tax hb-tax-time">${esc(tax.time_of_day)}</span>`);
  if (tax.type && tax.type !== "do") out.push(`<span class="hb-tax hb-tax-type">${esc(tax.type)}</span>`);
  return out.length ? `<span class="hb-tax-row">${out.join("")}</span>` : "";
}
// P1.2 — friction/difficulty, read from the REAL adherence rate (not inferred): a habit
// you keep ~always is automatic; one you keep rarely is high-friction. Neutral, never red,
// never "you failed" — descriptive. null adherence (backlog/never started) gets no tag.
function habitFrictionChip(pct) {
  if (pct == null) return "";
  const t = pct >= 85 ? ["automatic", "fr-auto"] : pct >= 60 ? ["takes effort", "fr-mid"] : ["high friction", "fr-hard"];
  return `<span class="hb-fr ${t[1]}">${t[0]}</span>`;
}
// P1.3 — the three drivers behind a habit: trigger → friction → reward. Only friction is
// measured today (it's the inverse of adherence, P1.2). Trigger and reward need a capture
// step that doesn't exist yet — so they're shown as honestly empty, with the mechanism named,
// not faked. An honest empty state IS the build here; a fabricated drivers table would not be.
function habitsDrivers(perHabit) {
  const ranked = (perHabit || []).filter((h) => h.adherence_pct != null).sort((a, b) => (a.adherence_pct || 0) - (b.adherence_pct || 0)).slice(0, 5);
  const rows = ranked.length
    ? `<table class="rd-tbl rd-drv"><thead><tr><th>habit</th><th>trigger</th><th>friction</th><th>reward</th></tr></thead><tbody>${ranked.map((h) => `<tr><td class="rd-name">${esc(ttl(h.name))}</td><td class="drv-empty">— not captured</td><td>${habitFrictionChip(h.adherence_pct) || "—"}</td><td class="drv-empty">— not captured</td></tr>`).join("")}</tbody></table>`
    : empty("Drivers populate once habits have adherence history.");
  return sec("Drivers — trigger · friction · reward",
    rows + `<p class="rd-meta label">Friction is real — it's the inverse of how often the habit actually gets kept. Trigger (what cues it) and reward (what it pays back) aren't logged yet; they need a per-habit capture step, so they're shown honestly empty rather than guessed. The lowest-adherence habits are listed first — those are where a trigger or reward would move the needle most.</p>`);
}
// P1.4 — misses become narrative. The miss COUNT is real (scheduled − completed); the WHY
// isn't captured, so each miss reason reads honestly empty. Surfacing the count without the
// reason is the honest half-step — it shows where the narrative would attach once a reason
// prompt exists, instead of inventing causes.
function habitsWhyMissed(perHabit) {
  const missed = (perHabit || [])
    .map((h) => ({ name: h.name, n: Math.max(0, (h.scheduled_days || 0) - (h.completed_days || 0)) }))
    .filter((h) => h.n > 0)
    .sort((a, b) => b.n - a.n)
    .slice(0, 6);
  if (!missed.length) return "";
  const rows = missed.map((h) => `<div class="wm-row"><span class="wm-name">${esc(ttl(h.name))}</span><span class="wm-n mono">${h.n} missed</span><span class="wm-why drv-empty">reason not captured</span></div>`).join("");
  return sec("When a habit slips — the misses, honestly",
    `<div class="wm-list">${rows}</div><p class="rd-meta label">The miss count is real. The <em>reason</em> isn't logged yet — a one-tap "why" on a missed day would turn these counts into narrative (travel, illness, low day). Until that capture exists, the why stays blank rather than guessed. No red, no streak-shaming.</p>`);
}
function habitStateTaxonomy(perHabit, registryHabits) {
  const byName = {}; for (const h of perHabit || []) byName[h.name] = h;
  const all = (perHabit || []).slice();
  for (const r of registryHabits || []) { if (!byName[r.name]) all.push({ name: r.name, group: r.group || "Other", adherence_pct: null, state: "backlog" }); }
  if (!all.length) return "";
  const STATES = [
    { key: "automatic", label: "Automatic", desc: "high & stable", tone: "st-auto" },
    { key: "holding", label: "Holding", desc: "consistent, lower", tone: "st-hold" },
    { key: "needs_attention", label: "Needs attention", desc: "slipping", tone: "st-need" },
    { key: "backlog", label: "Backlog / never started", desc: "shown, not hidden", tone: "st-backlog" },
  ];
  const lanes = STATES.map((s) => {
    const hs = all.filter((h) => h.state === s.key);
    if (!hs.length) return "";
    const chips = hs.map((h) => `<span class="st-chip ${s.tone}">${esc(ttl(h.name))}${h.adherence_pct != null ? ` <span class="st-pct">${fmt(h.adherence_pct)}%</span>` : ""}</span>`).join("");
    return `<div class="st-lane"><div class="st-lanehead"><span class="st-marker ${s.tone}"></span><span class="st-name">${esc(s.label)}</span><span class="st-desc label">${esc(s.desc)} · ${hs.length}</span></div><div class="st-chips">${chips}</div></div>`;
  }).join("");
  return sec("Habit states — every habit tagged (backlog shown, not hidden)",
    lanes + `<p class="rd-meta label">State is encoded by ember intensity + position, not a rainbow: Automatic = full ember · Holding = ember tint · Needs-attention = muted + marker · Backlog/never-started = outline, honestly empty (most apps hide these). No red, no shame.</p>`);
}
// §5 effort map (P0.6) — ranked dot-strip: dot size = habits the group carries, ember
// saturation = adherence. ONE ember scale + size, NOT a radar (misleading geometry) or rainbow.
function habitsEffortMap(groupAvgs, registryHabits) {
  const counts = {}; for (const h of registryHabits || []) { const g = h.group || "Other"; counts[g] = (counts[g] || 0) + 1; }
  const items = Object.keys(counts).map((g) => ({ group: g, count: counts[g], pct: groupAvgs[g] != null ? groupAvgs[g] : null }));
  if (!items.length) return "";
  items.sort((a, b) => b.count - a.count);
  const maxCount = Math.max(...items.map((i) => i.count));
  const rows = items.map((i) => {
    const sat = i.pct != null ? Math.max(0.12, i.pct / 100) : 0.12;
    const sz = (12 + (i.count / maxCount) * 24).toFixed(0);
    return `<div class="em-row"><span class="em-dot" style="width:${sz}px;height:${sz}px;--heat:${sat.toFixed(2)}"></span>` +
      `<span class="em-l">${esc(ttl(i.group))}</span><span class="em-meta label">${i.count} habit${i.count > 1 ? "s" : ""}${i.pct != null ? ` · ${fmt(i.pct)}%` : ""}</span></div>`;
  }).join("");
  return sec("Where the effort is",
    `<div class="em-strip">${rows}</div>` +
    `<p class="rd-meta label">Each group: dot size = how many habits it carries, ember intensity = how reliably they're held. One ember scale + size — deliberately a ranked strip, not a radar (misleading geometry) and not a rainbow.</p>`);
}
// §6 per-group trend small-multiples (P0.7) — each group's adherence sparkline. The floor
// groups (Recovery ~14%) render muted (sparkline + label), never red — a not-yet, not a fail.
function habitsGroupTrends(history, groupAvgs) {
  const series = {};
  for (const day of history || []) {
    for (const [g, p] of Object.entries(day.groups || {})) { if (Number.isFinite(Number(p))) (series[g] = series[g] || []).push(Number(p)); }
  }
  const groups = Object.keys(series).sort((a, b) => (groupAvgs[b] || 0) - (groupAvgs[a] || 0));
  if (!groups.length) return "";
  const cards = groups.map((g) => {
    const vals = series[g], avg = groupAvgs[g];
    const low = avg != null && avg < 40;
    return `<div class="gt-card${low ? " gt-low" : ""}"><div class="gt-head"><span class="gt-name">${esc(ttl(g))}</span><span class="gt-pct mono">${fmt(avg)}%</span></div>${vals.length >= 2 ? sparkline(vals) : `<span class="gt-thin label">fills in</span>`}</div>`;
  }).join("");
  return sec("Per-group trends — the floor and the load-bearing",
    `<div class="gt-grid">${cards}</div>` +
    `<p class="rd-meta label">Each group's adherence over the window. The low ones (Recovery — the floor not yet built) read muted, never red — a not-yet, not a failure.</p>`);
}
// §7 goal linkage (P0.8) — each habit group links UP to the goal/pillar it serves + a
// cross-link to the Evidence page that measures it. Copy-driven.
const _HABIT_GOAL_LINKS = {
  recovery: { goal: "hold the cut without breaking", link: "/data/sleep/", label: "Sleep" },
  nutrition: { goal: "a deficit you can hold", link: "/data/nutrition/", label: "Nutrition" },
  movement: { goal: "build the engine", link: "/data/training/", label: "Training" },
  fitness: { goal: "build the engine", link: "/data/training/", label: "Training" },
  training: { goal: "build the engine", link: "/data/training/", label: "Training" },
  discipline: { goal: "the consistency pillar — skin in the game", link: "/data/vices/", label: "Vice streaks" },
  mind: { goal: "the inner-life pillar", link: "/data/mind/", label: "Mind" },
  hydration: { goal: "a deficit you can hold", link: "/data/nutrition/", label: "Nutrition" },
  sleep: { goal: "the recovery that protects the cut", link: "/data/sleep/", label: "Sleep" },
};
function habitsGoalLinkage(groupAvgs) {
  const groups = Object.keys(groupAvgs || {});
  if (!groups.length) return "";
  const rows = groups.map((g) => {
    const m = _HABIT_GOAL_LINKS[g.toLowerCase()];
    return `<tr><td class="rd-name">${esc(ttl(g))}</td><td>${m ? esc(m.goal) : "—"}</td><td>${m ? `<a href="${m.link}">${esc(m.label)} →</a>` : ""}</td></tr>`;
  }).join("");
  return sec("What it's all for — groups → goals",
    `<table class="rd-tbl"><thead><tr><th>habit group</th><th>the goal it serves</th><th>see</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<p class="rd-meta label">P1.5 — each group links out to the page that proves it. The reverse feed (a Nutrition/Sleep/Training day's <em>own</em> completion folding back into this group's score) isn't wired yet — those pages don't expose a single daily-completion signal, so the group rate here stays sourced purely from Habitify rather than double-counting. The cross-link is live; the completion-feed is honestly pending.</p>`);
}
// §8 identity / compliance reflection (P0.9) — atomic-habits framing PINNED to real data
// (the most-automatic habit + its rate), never a mantra. Two-voice.
function habitsIdentity(perHabit, rate, daysTracked) {
  const auto = (perHabit || []).filter((h) => h.adherence_pct != null).sort((a, b) => b.adherence_pct - a.adherence_pct)[0];
  if (!auto && rate == null) return "";
  const machine = [daysTracked != null && `${fmt(daysTracked)} days tracked`, rate != null && `consistency ${fmt(rate)}%`, auto && `top: ${ttl(auto.name)} ${fmt(auto.adherence_pct)}%`].filter(Boolean).join(" · ");
  const serif = auto
    ? `${fmt(daysTracked)} days in, the most automatic habit is ${ttl(auto.name)} — firing ${fmt(auto.adherence_pct)}% of the days it's due. That one isn't willpower anymore; it's just who shows up. Identity is the set of habits that fire without a decision, and the data says which have crossed over.`
    : `${fmt(daysTracked)} days in at ${fmt(rate)}% consistency — the identity is whatever the heatmap keeps proving, not a slogan.`;
  return sec("Identity — who the data says you are",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
async function renderHabits(d) {
  const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const a = d.day_of_week_avgs || [];
  const mx = Math.max(1, ...a);
  const reg = await tryJSON("/api/habit_registry");
  const habits = (reg && reg.habits) || [];
  const groups = (reg && reg.groups) || [];
  // P0.2 — consistency RATE is the north-star; the fragile single streak demotes (honest at 0).
  const _histAll = d.history || [];
  const _held = _histAll.filter((h) => (h.tier0_pct || 0) >= 80).length;
  const _total = _histAll.length;
  const _rate = _total ? Math.round((_held / _total) * 100) : null;
  const head = figs([
    _rate != null && fig(_rate + "%", `consistency · held ${_held}/${_total} days`),
    fig(d.days_tracked ?? 0, "days tracked"),
    habits.length ? fig(habits.length, "habits tracked") : "",
    fig(d.current_streak ?? 0, "current streak"),
  ]) + `<p class="rd-meta label">Consistency rate — how often the non-negotiables get held — is the north-star. The single streak is fragile (one missed day zeroes it), so it's shown honestly but not led with.</p>`;
  const dow = a.length ? sec("Adherence by day of week", `<div class="hb-chart">${a.map((v, i) => `<div class="hb-col"><span class="hb-bar" style="height:${Math.max(4, (v / mx) * 100)}%"></span><span class="hb-day label">${dows[i] || ""}</span></div>`).join("")}</div>`) : "";
  let list = empty("Habit list loading from Habitify.");
  if (habits.length) {
    const order = groups.length ? groups : [...new Set(habits.map((h) => h.group || "Other"))];
    const _perBy = {}; for (const ph of d.per_habit || []) _perBy[ph.name] = ph;
    const body = order.map((g) => { const hs = habits.filter((h) => (h.group || "Other") === g); if (!hs.length) return ""; return `<h4 class="hb-group label">${esc(g)} <span class="rd-unit">${hs.length}</span></h4><table class="rd-tbl"><tbody>${hs.map((h) => `<tr><td class="rd-name">${esc(h.name)}${habitTaxonomyChips(h.taxonomy)}${habitFrictionChip((_perBy[h.name] || {}).adherence_pct)}</td><td class="num rd-range">${esc(h.frequency || "daily")}</td></tr>`).join("")}</tbody></table>`; }).join("");
    list = sec(`Habits I'm tracking (${habits.length})`, body + `<p class="rd-meta label">Time-of-day and do/avoid/maintain are <em>auto-derived</em> from the habit's name (heuristic, not fact). The friction tag is the opposite — read straight from the real adherence rate: kept ~always is automatic, kept rarely is high-friction. Descriptive, not a grade.</p>`);
  }
  // §2 — 90-day adherence heatmap (P0.3). GitHub-style calendar, ember-saturation = the day's
  // Tier-0 %, cut-start (Jun 14) ringed. Replaces the old green/amber/red 7-day grid (rainbow +
  // red, both off-brand) with the ONE-ember heat scale. Reuses heatStrip (compact mode).
  const grid = _histAll.length
    ? sec("90-day adherence heatmap", heatStrip(_histAll, { valueKey: "tier0_pct", unit: "%", max: 100, compact: true, cutDate: "2026-06-14", label: "Daily Tier-0 adherence", caption: "Each square is a day · ember intensity = the non-negotiables held · the ringed square is the cut starting Jun 14 · 90-day history predates the cut." }))
    : "";
  // Adherence trend (the long-run consistency story the 7-cell grid only hinted at).
  const trend = (d.history || []).length ? sec("Adherence trend", lineChart(d.history, { valueKey: "tier0_pct", unit: "%", label: "Daily Tier-0 adherence", spine: true, emptyMsg: "The adherence curve fills as days accrue." })) : "";
  // §0 — keystone hero, honesty-rebuilt (P0.1): leads the page, n-forward, coefficient withheld.
  const keystone = habitsKeystone(d.keystone_correlations);
  // §3 — group grades from adherence RATE (P0.4). Real completion rate → grade (never a
  // correlation). Ember = load-bearing/solid; the floor groups (e.g. Recovery) muted, not red.
  const _gradeOf = (p) => (p >= 90 ? "A" : p >= 80 ? "B" : p >= 70 ? "C" : p >= 50 ? "D" : "F");
  const ga = Object.entries(d.group_90d_avgs || {}).map(([g, p]) => ({ group: g, pct: p })).sort((x, y) => y.pct - x.pct);
  const groupBars = ga.length ? sec("Group grades — what's load-bearing (from adherence rate)",
    `<div class="suf-rows">${ga.map((x) => {
      const tone = x.pct >= 70 ? "suf-ember" : "suf-ink";
      return `<div class="suf-row"><span class="suf-l">${esc(ttl(x.group))}</span><span class="suf-track"><span class="suf-fill ${tone}" style="width:${Math.round(Math.max(0, Math.min(100, x.pct)))}%"></span></span><span class="suf-v mono">${fmt(x.pct)}% · ${_gradeOf(x.pct)}</span></div>`;
    }).join("")}</div>` +
    `<p class="rd-meta label">Each grade is the group's real adherence RATE over the window — never a correlation. Higher = load-bearing; the low ones (the floor, like Recovery) read muted, not as failure. Tier-0 non-negotiables drive the heatmap above.</p>`) : "";
  const states = habitStateTaxonomy(d.per_habit, habits);
  const effort = habitsEffortMap(d.group_90d_avgs || {}, habits);
  const drivers = habitsDrivers(d.per_habit);
  const whymiss = habitsWhyMissed(d.per_habit);
  const gtrends = habitsGroupTrends(d.history, d.group_90d_avgs || {});
  const goals = habitsGoalLinkage(d.group_90d_avgs || {});
  const identity = habitsIdentity(d.per_habit, _rate, d.days_tracked);
  return keystone + head + grid + identity + groupBars + states + effort + drivers + whymiss + gtrends + goals + trend + dow + list + note("Everything I'm trying to do — sourced from Habitify. Correlations are N=1, not cause. Private habits are never shown.");
}
// The board — pick an expert, read their actual per-domain take + track record.
// WQA-06 — surface the cross-coach DISAGREEMENTS (the moat), not eight parallel monologues.
// Reads /api/coach_team tensions: topic + the two coaches' positions head-to-head + the
// integrator's (Coach Nakamura's) call. Interpretation, never alarm; ember on the verdict.
function boardDisagreements(tensions) {
  const ts = (tensions || []).filter((t) => t && (t.position_a || t.position_b));
  if (!ts.length) return "";
  const pretty = (id) => ttl(String(id || "").replace(/_coach$/, "").replace(/_/g, " ")) || "Coach";
  const strip = (txt) => String(txt || "").replace(/^[A-Za-z'’ .]{1,40}:\s*/, "");
  const cards = ts.map((t) => {
    const [a, b] = t.coaches || [];
    return `<article class="dis-card"><h4 class="dis-topic">${esc(t.topic || "An open disagreement")}</h4>` +
      `<div class="dis-cols">` +
      `<div class="dis-pos"><span class="dis-who label">${esc(pretty(a))}</span><p class="dis-text">${esc(strip(t.position_a))}</p></div>` +
      `<div class="dis-vs" aria-hidden="true">vs</div>` +
      `<div class="dis-pos"><span class="dis-who label">${esc(pretty(b))}</span><p class="dis-text">${esc(strip(t.position_b))}</p></div>` +
      `</div>` +
      (t.resolution ? `<div class="dis-call"><span class="dis-call-k label">the integrator's call</span><p class="dis-text">${esc(t.resolution)}</p></div>` : "") +
      `</article>`;
  }).join("");
  return sec("Where the coaches disagree — the argument, not the consensus",
    `<div class="dis-grid">${cards}</div>` +
    `<p class="rd-meta label">The moat isn't eight assistants nodding along — it's that they don't, and the disagreement is surfaced instead of averaged away. Each is an AI persona arguing from its own discipline; the integrator (Coach Nakamura) adjudicates, but the tension is the point. Interpretation of the data, never an instruction.</p>`);
}
async function renderBoard(d) {
  const coaches = d.coaches || []; const wp = d.weekly_priority || {};
  const team = await tryJSON("/api/coach_team");
  const disagreements = boardDisagreements(team && team.tensions);
  const chair = wp.text && !isBad(wp.text)
    ? `<div class="rd-obs"><p class="board-kicker label">the integrator's weekly read · ${esc(wp.coach_name || "")}</p><p class="rd-primary">${esc(wp.text)}</p></div>`
    : `<div class="rd-obs"><p class="rd-primary">The board's weekly read posts after the next briefing.</p></div>`;
  const roster = coaches.length
    ? `<div class="coach-grid">${coaches.map((c) => `<button class="coach coach-pick" data-coach="${esc(c.coach_id)}" data-name="${esc(c.name)}" data-title="${esc(c.title || "")}" style="--coach:${/^#|rgb/.test(c.color || "") ? c.color : "var(--ember)"}"><span class="coach-badge">${sigil(c, { title: "" })}<span class="sr-only">${esc(c.initials || (c.name || "?").slice(0, 2))}</span></span><div><h3 class="coach-name">${esc(c.name)}</h3><p class="coach-title label">${esc(c.title || "")}</p></div></button>`).join("")}</div>`
    : empty("The expert board is being assembled.");
  return chair + disagreements + sec("The experts — pick one to read their take", roster) +
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
    <div class="df-buttons">${ms.map(([w, lbl]) => `<button class="df-btn" data-df-to="${w}">${lbl ? lbl + " · " : ""}${Math.round(w)}</button>`).join("")}<button class="df-btn df-play" data-df-play>${icon("play")} morph</button></div>
    <p class="rd-why df-note"><strong>A representative figure, not a photo.</strong> The silhouette's girth is a direct function of the real measured weight — heaviest at ${Math.round(start)}, leanest at ${Math.round(goal)} — with no face, no identity, and nothing generated or guessed. It moves only when the actual number moves${moved && moved !== "even" ? ` (currently ${moved} from the start)` : ""}.</p>
  </section>`;
}

async function renderResults(d) { const j = d.journey || d; const wp = await tryJSON("/api/weight_progress"); const chart = sec("Weight trajectory", lineChart((wp && wp.weight_progress) || [], { valueKey: "weight_lbs", goal: j.goal_weight_lbs, unit: " lb", label: "Weight · recent readings", emptyMsg: "Weight trajectory fills as weigh-ins accrue." })); const lost = j.lost_lbs != null ? Number(j.lost_lbs) : null; const wdir = lost == null ? "" : (lost < -0.05 ? "up" : (Math.abs(lost) <= 0.05 ? "even" : "down")); const _wCap = (!j.last_weighin_date || String(j.last_weighin_date).slice(0, 10) === todayPT()) ? "today" : `latest · ${fmtShort(j.last_weighin_date)}`; return dataFigure(j) + chart + figs([lost != null && fig(dualWeight(Math.abs(lost), "lb"), wdir), j.current_weight_lbs != null && fig(dualWeight(j.current_weight_lbs, "lb"), _wCap), j.progress_pct != null && fig(fmt(j.progress_pct) + "%", "to goal"), j.projected_goal_date && fig(j.projected_goal_date, "projected goal")]) + `<p class="rd-archive">The headline outcome is weight, but the real results live in the mechanisms — see Experiments for what's confirmed, Bloodwork for what changed inside, and the Story for the arc.</p>` + note("Correlative projection — not a promise."); }
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
  // The widget itself is the shared module (assets/js/ask.js) — mounted by WIRE.ask
  // so Home and this archive render the SAME experience. The container is all we emit.
  return `<div data-ask-mount></div>`;
}
function renderExplorer(d) { const v = (d.vitals && d.vitals.vitals) || d.vitals || {}; const ch = (d.character && d.character.character) || {}; const j = (d.journey && d.journey.journey) || d.journey || {}; const rows = { weight_lbs: j.current_weight_lbs, character_level: ch.level, ...Object.fromEntries(Object.entries(v).filter(([k, x]) => ["string", "number"].includes(typeof x)).slice(0, 12)) }; return `<p class="rd-archive">Today's raw record, straight from the pipeline. For the full historical day-by-day browser, open the preserved Explorer below.</p>` + sec("Today", kvtable(rows)) + note("The unfiltered daily record."); }

// Live Pulse — current status narrative + daily vitals trends (the old /live).
// ── /data/vitals/ — the landing page, glance-first, three altitudes. "An instant, honest
// tell at the top; the full documentary as you scroll." `d` = /api/pulse.
// P0.1 — decompose the day into 4 component reads (recovery / HRV / RHR / sleep). Each becomes
// a ring whose fill is the metric's own value or its position in the recent range. tone: ember
// = good, muted = neutral/forming, alert = reserved RED STATE (run-down) — NEVER for direction
// (RHR-down / HRV-up read ember-positive even as the line falls).
function _vitalsComponents(p, hist) {
  const g = (p && p.glyphs) || {};
  const last = hist.length ? hist[hist.length - 1] : {};
  const num = (x) => (Number.isFinite(Number(x)) ? Number(x) : null);
  const recPct = num((g.recovery || {}).recovery_pct) ?? num(last.recovery_pct);
  const hrv = num((g.recovery || {}).hrv_ms) ?? num(last.hrv_ms);
  const rhr = num((g.recovery || {}).rhr_bpm) ?? num(last.rhr_bpm);
  const sleep = num((g.sleep || {}).hours) ?? num(last.sleep_hours);
  const col = (k) => hist.map((h) => num(h[k])).filter((v) => v != null);
  const rangePos = (val, arr, invert) => {
    if (val == null || arr.length < 2) return 0.5;
    const lo = Math.min(...arr), hi = Math.max(...arr);
    if (hi === lo) return 0.5;
    const pos = (val - lo) / (hi - lo);
    return invert ? 1 - pos : pos;
  };
  const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
  const hrvA = avg(col("hrv_ms")), rhrA = avg(col("rhr_bpm"));
  return [
    { key: "recovery", label: "recovery", value: recPct != null ? recPct + "%" : "—", raw: recPct, fill: recPct != null ? recPct / 100 : 0,
      tone: recPct == null ? "muted" : recPct >= 67 ? "ember" : recPct >= 34 ? "muted" : "alert", frame: "last night" },
    { key: "hrv", label: "HRV", value: hrv != null ? Math.round(hrv) : "—", sub: "ms", raw: hrv, fill: rangePos(hrv, col("hrv_ms"), false),
      tone: hrv == null ? "muted" : (hrvA != null && hrv >= hrvA ? "ember" : "muted"), frame: "last night" },
    { key: "rhr", label: "resting HR", value: rhr != null ? Math.round(rhr) : "—", sub: "bpm", raw: rhr, fill: rangePos(rhr, col("rhr_bpm"), true),
      tone: rhr == null ? "muted" : (rhrA != null && rhr <= rhrA ? "ember" : "muted"), frame: "last night" },
    { key: "sleep", label: "sleep", value: sleep != null ? fmt(sleep, 1) : "—", sub: "h", raw: sleep, fill: sleep != null ? Math.min(1, sleep / 8) : 0,
      tone: sleep == null ? "muted" : sleep >= 7 ? "ember" : sleep >= 5.5 ? "muted" : "alert", frame: "last night" },
  ];
}
// P0.1 — the status WORD is synthesised from the component tones (anti-black-box: it's the sum
// of the visible rings, never a lone grade). RED only for a genuine run-down STATE.
function vitalsStatusRead(comps, p, dayNum) {
  const rated = comps.filter((c) => c.raw != null);
  const ember = rated.filter((c) => c.tone === "ember").length;
  const alert = rated.filter((c) => c.tone === "alert").length;
  const rec = comps.find((c) => c.key === "recovery");
  let word, line, tone;
  if (!rated.length) { word = "READING…"; line = "today's signals are still coming in."; tone = "muted"; }
  else if (alert >= 2 || (rec && rec.tone === "alert")) { word = "RUN DOWN"; line = "the body's asking for an easier day."; tone = "alert"; }
  else if (ember >= 3) { word = "RECOVERED"; line = "the body's ready — push if you've got it."; tone = "ember"; }
  else { word = "MIXED"; line = "a split signal — read the parts, not a single verdict."; tone = "muted"; }
  const thin = (dayNum != null && dayNum < 14);
  const stamp = thin ? `<span class="vs-stamp label">${dayNum} days in — baseline still forming</span>` : "";
  const rings = `<div class="vr-row">${comps.map((c) => ring({ value: c.value, sub: c.sub || "", label: c.label, fill: c.fill, tone: c.tone, thin })).join("")}</div>`;
  return sec("Today's read",
    `<div class="vs-band vs-${tone}"><div class="vs-word"><span class="vs-w">${esc(word)}</span><span class="vs-line">${esc(line)}</span></div>${stamp}</div>` +
    rings +
    `<p class="rd-meta label">The status is the sum of the rings below it — recovery, HRV, resting HR, sleep — not a black-box grade. Each is <strong>last night's</strong> read, setting up today. Ember = good, muted = neutral or still forming${thin ? "; on day " + dayNum + " of a fresh cut the baseline is thin, so the rings show their state without overclaiming." : "."}</p>`);
}
// P0.2 — now vs 7-day vs 30-day ladder under each ring: "am I above/below my own normal?"
// The 30-day baseline honestly reads "fills in" until 30 days exist. Aligns with the ring grid.
function vitalsLadder(comps, hist) {
  const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);
  const col = (k) => hist.map((h) => num(h[k])).filter((v) => v != null);
  const avg = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
  const map = { recovery: "recovery_pct", hrv: "hrv_ms", rhr: "rhr_bpm", sleep: "sleep_hours" };
  const fmtv = (v, key) => (v == null ? "—" : key === "sleep" ? fmt(v, 1) : String(Math.round(v)));
  const cells = comps.map((c) => {
    const arr = col(map[c.key]);
    const a7 = avg(arr.slice(-7));
    const has30 = arr.length >= 30;
    return `<div class="vl-cell"><span class="vl-pair"><span class="vl-k label">now</span><span class="vl-v mono">${esc(fmtv(c.raw, c.key))}</span></span>` +
      `<span class="vl-pair"><span class="vl-k label">7d</span><span class="vl-v mono vl-base">${esc(fmtv(a7, c.key))}</span></span>` +
      `<span class="vl-pair"><span class="vl-k label">30d</span><span class="vl-v mono vl-base">${has30 ? esc(fmtv(avg(arr.slice(-30)), c.key)) : "fills in"}</span></span></div>`;
  }).join("");
  return `<div class="vl-row">${cells}</div>` +
    `<p class="rd-meta label">Each ring read against your <em>own</em> normal — today vs the trailing 7-day average, with a 30-day baseline that fills in as the days accrue (${hist.length} so far). The baseline is the honest "is this a good day for me," not a population chart.</p>`;
}
// P0.3 — earned glyphs: light ember ONLY on a real daily signal (gray-state glyphs render
// unlit — nothing is always-lit/decorative). Habits use "X of N today" (the honest fallback;
// no hourly "by-this-hour" baseline is fabricated) and cross-link to the Habits page.
function vitalsGlyphs(p, habitsToday) {
  const g = (p && p.glyphs) || {};
  const ORDER = [["recovery", "recovered"], ["sleep", "slept"], ["scale", "weight"], ["movement", "moved"], ["lift", "lifted"], ["water", "hydration"], ["journal", "journal"], ["mind", "mind"]];
  const chips = ORDER.map(([k, word]) => {
    const gl = g[k]; if (!gl) return null;
    const lit = gl.state && gl.state !== "gray";
    const val = gl.label || gl.delta_label || "";
    return `<span class="vg ${lit ? "vg-lit" : "vg-off"}"><span class="vg-dot" aria-hidden="true"></span><span class="vg-word">${esc(word)}</span>${val ? `<span class="vg-val mono">${esc(val)}</span>` : ""}</span>`;
  }).filter(Boolean);
  if (habitsToday && habitsToday.total) {
    const lit = habitsToday.done > 0;
    chips.unshift(`<a class="vg ${lit ? "vg-lit" : "vg-off"}" href="/data/habits/"><span class="vg-dot" aria-hidden="true"></span><span class="vg-word">habits</span><span class="vg-val mono">${habitsToday.done} of ${habitsToday.total}</span></a>`);
  }
  if (!chips.length) return "";
  return sec("Today, so far — the signals that have fired",
    `<div class="vg-row">${chips.join("")}</div>` +
    `<p class="rd-meta label">A glyph lights only when its signal actually fires today — the unlit ones simply haven't yet (no decorative always-on tiles). Habits show <strong>${habitsToday ? habitsToday.done + " of " + habitsToday.total : "—"} done today</strong>; an "average by this hour" benchmark waits on hourly habit history rather than being faked.</p>`);
}
// P1.3 — readiness decomposed: the recovery number broken into its drivers (HRV, RHR, sleep) —
// the Altitude-1 rings expanded into bars. Each bar = where the driver sits in its recent range
// (RHR inverted: lower = fuller). Anti-black-box, same decomposition as the glance.
function vitalsReadinessDecomposed(comps) {
  const rec = comps.find((c) => c.key === "recovery");
  const drivers = comps.filter((c) => c.key !== "recovery");
  if (!rec || rec.raw == null) return "";
  const rows = drivers.map((c) => {
    const pct = Math.round((c.fill || 0) * 100);
    const tone = c.tone === "ember" ? "suf-ember" : c.tone === "alert" ? "vd-alert" : "suf-ink";
    return `<div class="suf-row"><span class="suf-l">${esc(c.label)}</span><span class="suf-track"><span class="suf-fill ${tone}" style="width:${pct}%"></span></span><span class="suf-v mono">${esc(c.value)}${c.sub ? " " + esc(c.sub) : ""}</span></div>`;
  }).join("");
  return sec("Readiness, decomposed — what's under the recovery number",
    figs([fig(rec.value, "recovery · last night")]) +
    `<div class="suf-rows">${rows}</div>` +
    `<p class="rd-meta label">Recovery isn't a single black-box score — it's mostly HRV, resting heart rate, and sleep. Each bar is where that driver sits in its own recent range (resting HR inverted: lower = fuller). It's the Altitude-1 rings, expanded — last night's read, setting up today.</p>`);
}
// P1.1 — today's pulse narrative, kept + elevated: two-voice (mono numbers, serif meaning),
// retied to the autonomic story (the system downshifting into recovery).
function vitalsNarrative(p, comps) {
  const get = (k) => (comps.find((c) => c.key === k) || {});
  const rec = get("recovery"), hrv = get("hrv"), rhr = get("rhr");
  const machine = (p.narrative && !isBad(p.narrative)) ? p.narrative
    : [p.date, p.status, p.signals_reporting != null && `${p.signals_reporting}/${p.signals_total} signals`].filter(Boolean).join(" · ");
  // Only tell the "downshifting into recovery" story when recovery is high AND HRV is
  // actually at/above its recent range and RHR isn't elevated — otherwise the caption
  // claims "HRV holding their ground" on a day HRV is down (truth-audit Phase 4b).
  const recovered = rec.tone === "ember" && hrv.tone === "ember" && rhr.tone !== "alert";
  const serif = recovered
    ? `The autonomic read is the story under the numbers: recovery sitting at ${rec.value}, with resting heart rate and HRV holding their ground. That's the parasympathetic side doing its job — the body downshifting into repair overnight, which is exactly what a cut leans on to keep the work absorbable.`
    : `The autonomic system is the story under the numbers — recovery at ${rec.value}, HRV ${hrv.value}${hrv.sub || ""}, resting HR ${rhr.value}${rhr.sub || ""}. Read the direction of the pair over the next days, not any single morning: recovery is the body's nightly accounting of how much it could repair.`;
  return sec("Today's pulse — the autonomic read",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}
async function renderPulse(d) {
  const p = d.pulse || d;
  const [ph, hb] = await Promise.all([tryJSON("/api/pulse_history"), tryJSON("/api/habits")]);
  const hist = (ph && ph.pulse_history) || [];
  const _hh = (hb && hb.history && hb.history.length) ? hb.history[hb.history.length - 1] : null;
  const habitsToday = _hh && _hh.t0_total ? { done: _hh.t0_done, total: _hh.t0_total } : null;
  const comps = _vitalsComponents(p, hist);
  const parts = [];
  parts.push(vitalsStatusRead(comps, p, p.day_number)); // P0.1 — Altitude 1: status word + component rings
  parts.push(vitalsLadder(comps, hist)); // P0.2 — now / 7d / 30d ladder under the rings
  parts.push(vitalsGlyphs(p, habitsToday)); // P0.3 — earned glyph row (light on real signal only)
  // ── ALTITUDE 2 — the synthesis ──
  parts.push(vitalsNarrative(p, comps)); // P1.1 — today's pulse, two-voice, tied to the autonomic story
  if (hist.length >= 4) parts.push(sec("Autonomic recovery — RHR + HRV, one frame", // P1.2 — autonomic hero
    autonomicHero(hist, { label: "Resting HR (inverted) + HRV" }) +
    `<p class="rd-meta label">Resting heart rate and HRV are the two halves of one autonomic signal. RHR's axis is <strong>inverted</strong> so a falling resting HR reads as a rising line — because down is good. Both climbing together = the parasympathetic "rest &amp; repair" side taking over: the body downshifting. Last night's read; n=1, early moves partly water/novelty.</p>`));
  parts.push(vitalsReadinessDecomposed(comps)); // P1.3 — recovery broken into its drivers
  // ── ALTITUDE 3 — the analysis ──
  const qpts = hist.slice(-8).map((h, i, a) => ({ strain: Number(h.strain), recovery: Number(h.recovery_pct), date: h.date, today: i === a.length - 1 }));
  parts.push(sec("Autonomic balance — where the body's sat lately", // P2.1 — 2x2 snapshot
    `<div class="aq-wrap">${autonomicQuadrant(qpts)}</div>` +
    `<p class="rd-meta label">Day strain against recovery, the last ${qpts.length} days — recovered <em>and</em> training hard is flow; depleted and still pushing is stress. A snapshot of the spread, not a trajectory; no arrow drawn at this n.</p>`));
  parts.push(vitalsSmallMultiples(hist)); // P2.2 — small-multiples grid (replaces the 8 equal charts) + P2.5 remove
  parts.push(vitalsBackgroundStrip(p)); // P2.3 — background vitals (honest empty until captured)
  parts.push(vitalsCaptureBacklog(p)); // P3.1–P3.6 — capture + relationships, honestly gated
  parts.push(vitalsHubLinks()); // P2.4 — hub links out to the domain pages
  return parts.join("");
}
// P3.1–P3.6 — new-capture + relationships, honestly gated. Each is a real capability awaiting
// data; none fabricate. P3.6 (cross-metric correlations) STAYS withheld until ≥2 weeks of
// overlap — no coefficient is computed at ~10 days; it'll reuse the sleep correlation-board.
function vitalsCaptureBacklog(p) {
  const dayNum = p && p.day_number;
  const wks = dayNum != null ? Math.max(0, 14 - dayNum) : null;
  const cards = [
    `<div class="cap-card"><h4 class="cap-h">Blood pressure <span class="cap-tag">needs a cuff</span></h4><p class="rd-meta label">The most valuable missing daily vital for a heavy man mid-cut — and the one that should improve visibly. A morning cuff reading would add a BP trend here. Not captured yet.</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Hourly habit history <span class="cap-tag">upgrades the glyphs</span></h4><p class="rd-meta label">The glyph row shows "X of N today"; with hourly habit-completion history it would become "vs your average by this hour" — a real pace benchmark. Until that exists, the honest X-of-N stands (no faked hourly baseline).</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Continuous / walking HR <span class="cap-tag">needs capture</span></h4><p class="rd-meta label">Feeds Zone-2 and the autonomic read with daytime heart rate, not just the overnight resting figure.</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">VO₂max trend <span class="cap-tag">arc cadence</span></h4><p class="rd-meta label">The longevity gold-standard fitness number — a slow-moving arc metric beside the daily vitals.</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Subjective energy / mood <span class="cap-tag">needs capture</span></h4><p class="rd-meta label">A morning 1–5 "how do you actually feel" check-in — the ground-truth overlay the wearables miss, graded against the readiness read.</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Cross-metric relationships <span class="cap-tag">unlocks ${wks != null && wks > 0 ? "in ~" + wks + " days" : "at 2 weeks"}</span></h4><p class="rd-meta label">Which vitals move together — sleep→recovery, strain→next-day HRV — stays <strong>withheld</strong> until ~2 weeks of overlapping days (day ${dayNum != null ? dayNum : "?"} now). At n≈10 it's noise, not signal; when it opens it reuses the self-policing correlation board from Sleep — direction-only first, a coefficient only once the window is honest. No chip is drawn early.</p></div>`,
  ];
  return sec("What sharpens the read — capture & relationships",
    `<div class="cap-grid">${cards.join("")}</div>` +
    `<p class="rd-meta label">Each is a real capability waiting on data or time, not a stub — ranked by what would move the daily read most. The correlations stay closed until the window earns them.</p>`);
}
// P2.2 — small-multiples grid: every signal as a labelled sparkline (latest value + trend +
// temporal frame), replacing the eight big equal charts. P2.5: this IS the removal of the old
// charts. Refuses a sparkline under 2 points (shows "fills in").
function vitalsSmallMultiples(hist) {
  const SM = [
    { k: "recovery_pct", lbl: "recovery", unit: "%", frame: "last night", dp: 0 },
    { k: "hrv_ms", lbl: "HRV", unit: " ms", frame: "last night", dp: 0 },
    { k: "rhr_bpm", lbl: "resting HR", unit: " bpm", frame: "last night", dp: 0 },
    { k: "strain", lbl: "day strain", unit: "", frame: "same-day", dp: 1 },
    { k: "weight_lbs", lbl: "weight", unit: " lb", frame: "same-day", dp: 1 },
    { k: "steps", lbl: "steps", unit: "", frame: "same-day", dp: 0 },
  ];
  const cells = SM.map((m) => {
    const vals = hist.map((h) => Number(h[m.k])).filter((v) => Number.isFinite(v));
    if (vals.length < 2) return `<div class="sm-cell"><div class="sm-head"><span class="sm-lbl">${esc(m.lbl)}</span><span class="sm-frame label">${esc(m.frame)}</span></div><p class="sm-empty label">fills in</p></div>`;
    const latest = vals[vals.length - 1], first = vals[0];
    const arrow = latest > first ? "↑" : latest < first ? "↓" : "→";
    return `<div class="sm-cell"><div class="sm-head"><span class="sm-lbl">${esc(m.lbl)}</span><span class="sm-frame label">${esc(m.frame)}</span></div>` +
      `${sparkline(vals)}<div class="sm-foot"><span class="sm-v mono">${esc(fmt(latest, m.dp))}${esc(m.unit)}</span><span class="sm-trend mono">${arrow}</span></div></div>`;
  }).join("");
  return sec("Every signal, small — the full grid",
    `<div class="sm-grid">${cells}</div>` +
    `<p class="rd-meta label">All eight trends, demoted from equal hero charts to a glanceable grid — each stamped with its temporal frame (last-night vs same-day) and trend direction. The autonomic pair has its own hero above; these are the supporting cast.</p>`);
}
// P2.3 — background vitals (SpO2 / skin temp / resp rate) — anomaly detectors, not daily dials.
// Not captured by the current wearables, so an honest empty state, never a fake "all in range".
function vitalsBackgroundStrip(p) {
  return sec("Background vitals — the quiet anomaly detectors",
    `<div class="nut-coming"><p class="rd-archive">SpO₂, skin temperature, and respiratory rate are background vitals — they should sit silent and only speak up on a deviation (the one place a reserved red would be earned). They're not in the current data feed yet, so rather than draw a fake "all in range" strip, this waits on the capture. <span class="confidence conf-low">needs capture</span></p></div>`);
}
// P2.4 — hub links: the landing page is the front door; each domain links out to its page.
function vitalsHubLinks() {
  const links = [
    ["recovery & sleep", "/data/sleep/"], ["strain & training", "/data/training/"],
    ["weight & composition", "/data/physical/"], ["nutrition & the deficit", "/data/nutrition/"],
    ["habits", "/data/habits/"], ["bloodwork", "/data/labs/"],
  ];
  return sec("From here — the full documentary",
    `<div class="vh-row">${links.map(([t, h]) => `<a class="vh-link" href="${h}">${esc(t)} →</a>`).join("")}</div>` +
    `<p class="rd-meta label">This is the front door. The glance lives here; each signal opens into its own page for the deep read.</p>`);
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

// Intelligence — the weekly correlation matrix (Pearson r + BH-FDR), strongest first,
// headed by the engine's live tallies (/api/intelligence_summary: open bets + pairs).
async function renderCorrelations(d) {
  const summary = await tryJSON("/api/intelligence_summary");
  const hypCount = summary && summary.hypotheses && summary.hypotheses.count;
  // The loop continues: the machine's bets live on the Protocols door.
  const betsLine = hypCount
    ? `<p class="rd-meta label">The engine also holds ${fmt(hypCount)} open bet${hypCount === 1 ? "" : "s"} on this data — graded weekly under <a href="/protocols/discoveries/">What the machine suspects</a>.</p>`
    : "";
  const c = d && d.correlations;
  const obj = (c && !Array.isArray(c)) ? c : {};
  const pairs = obj.pairs || [];
  if (!pairs.length) return betsLine + empty("No correlations yet — and that's the honest state, not a broken pipeline. The experiment is freshly anchored to its current genesis, and the weekly matrix only computes once there are ~2+ weeks of overlapping daily data. An empty matrix means the sample is still too small to claim a pattern; it fills in as the days accrue.");
  const sig = pairs.filter((p) => p.fdr_significant).length;
  // Pairs with fewer than 5 overlapping days can't claim anything — collapse them
  // into one honest line instead of tabling a wall of r=0.00 / n=2 rows.
  const tabled = pairs.filter((p) => (p.n ?? 0) >= 5);
  const belowFloor = pairs.length - tabled.length;
  const head = figs([fig(obj.count ?? pairs.length, "pairs"), sig ? fig(sig, "FDR-significant") : "", hypCount ? fig(hypCount, "open bets") : "", obj.week && fig(obj.week, "week")]);
  const pTxt = (p) => (p.p === 0 ? "&lt;0.001" : p.p == null ? "—" : fmt(p.p, 3));
  const rows = tabled.slice(0, 30).map((p) => `<tr class="${p.fdr_significant ? "rd-flag" : ""}"><td class="rd-name">${esc(p.label_a || p.metric_a)} <span class="rd-unit">↔</span> ${esc(p.label_b || p.metric_b)}</td><td class="num">${fmt(p.r, 2)}</td><td class="num rd-range">${pTxt(p)}</td><td class="num">${fmt(p.n)}</td><td>${p.fdr_significant ? `<span class="rd-flagmark">FDR ✓</span>` : esc(p.strength || "")}</td></tr>`).join("");
  const floorNote = belowFloor ? `<p class="rd-desc">${belowFloor} more pair${belowFloor === 1 ? "" : "s"} had fewer than 5 overlapping days this week — below the floor for claiming a pattern, so they aren't tabled.</p>` : "";
  const tbl = sec("Correlation matrix — strongest first", `<table class="rd-tbl"><thead><tr><th>pair</th><th>r</th><th>p</th><th>n</th><th>significance</th></tr></thead><tbody>${rows}</tbody></table>${floorNote}`);
  return head + betsLine + tbl + (obj.methodology ? `<p class="rd-desc">${esc(obj.methodology)}</p>` : "") + note("Correlative only — Pearson r with Benjamini-Hochberg FDR control across all pairs. Never causal. p-values below 0.001 display as &lt;0.001.");
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

// Reading — the full Mind-pillar readout, rendered INSIDE the Data door so it shares
// the site chrome (there is no separate /mind/ page — it 301s here). Pulls the shelf
// (/api/reading_shelf), the roundedness wheel + habit (/api/reading_overview), and the
// idea constellation (/api/constellation). Honest empty states everywhere; no red on
// this surface (a set-down book is muted ink, never an alert); the reader's own words
// are the loudest type. Private fields never arrive — the server projects them out.
// See AUDIT PROD-01. (Reflections + why/intention + per-book detail layer in next.)
const _readingCover = (b) =>
  b && b.coverS3Key ? "/" + String(b.coverS3Key).replace(/^generated\//, "") : b && b.bookId ? `/covers/${esc(b.bookId)}.jpg` : null;

// The reader's own words — intention (why this book / what sparked it / the goal),
// reflections, and the finished-book takeaway. The loudest type on the page (design
// brief); only PUBLIC notes ever reach here (the server drops the rest). Empty → "".
function readingNotes(notes) {
  const list = Array.isArray(notes) ? notes : [];
  if (!list.length) return "";
  const LABELS = { intention: "Why this book", synthesis: "The takeaway", reflection: "Reflections", highlight: "Highlights" };
  const ORDER = ["intention", "synthesis", "reflection", "highlight"];
  const byType = {};
  list.forEach((n) => {
    (byType[n.type] = byType[n.type] || []).push(n);
  });
  return ORDER.filter((t) => byType[t] && byType[t].length)
    .map((t) => {
      const body = byType[t].map((n) => `<p class="rdg-note-text">${esc(n.text)}</p>`).join("");
      return `<div class="rdg-notes"><p class="rdg-note-label label">${esc(LABELS[t] || t)}</p>${body}</div>`;
    })
    .join("");
}

// A book list where each row carries cover + facts + the reader/coach's own words
// (why this book · reflections · the finished takeaway). Used for the queue (so the
// recommendation reason shows per book — the point of the pillar: the why, not just the
// spine) and for finished. `fallbackNote` shows when a book has no public note yet.
function readingBookList(title, items, opts) {
  opts = opts || {};
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return opts.emptyMsg ? sec(title, empty(opts.emptyMsg)) : "";
  const rows = list
    .map((it) => {
      const b = it.book || {};
      const cover = _readingCover(b);
      const tags = (b.domainTags || []).map(esc).join(" · ");
      const notes = readingNotes(it.notes);
      return (
        `<article class="rdg-fin">` +
        `<div class="rdg-fin-head">` +
        (cover ? `<img class="rdg-fin-cover" src="${esc(cover)}" alt="" loading="lazy">` : "") +
        `<div><p class="rdg-fin-title">${esc(b.title || "Untitled")}</p>` +
        (b.author ? `<p class="rd-meta label">${esc(b.author)}${tags ? " · " + tags : ""}</p>` : "") +
        `</div></div>` +
        (notes || (opts.fallbackNote ? `<p class="rd-meta label">${esc(opts.fallbackNote)}</p>` : "")) +
        `</article>`
      );
    })
    .join("");
  return sec(title, `<div class="rdg-fin-list">${rows}</div>`);
}

function readingSpine(item) {
  const b = (item && item.book) || {};
  const s = (item && item.state) || {};
  const title = b.title || "Untitled";
  const author = b.author || "";
  const cover = _readingCover(b);
  const rating = s.rating != null ? `<span class="rdg-rating num">${esc(s.rating)}★</span>` : "";
  const inner = cover
    ? `<img class="rdg-cover" src="${esc(cover)}" alt="" loading="lazy">`
    : `<span class="rdg-spine-t">${esc(title)}</span>${author ? `<span class="rdg-spine-a">${esc(author)}</span>` : ""}`;
  return (
    `<figure class="rdg-spine rdg-${esc(s.status || "")}" title="${esc(title)}${author ? " — " + esc(author) : ""}">` +
    `<span class="rdg-face">${inner}</span>` +
    `<figcaption class="rdg-cap label">${esc(title)}${rating}</figcaption></figure>`
  );
}

function readingShelfBlock(title, items, emptyMsg) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return emptyMsg ? sec(title, empty(emptyMsg)) : "";
  return sec(title, `<div class="rdg-shelf">${list.map(readingSpine).join("")}</div>`);
}

function readingNow(cur) {
  const b = (cur && cur.book) || null;
  if (!b) return sec("Reading now", empty("Nothing on the nightstand right now — the next book is the whole point."));
  const cover = _readingCover(b);
  const tags = (b.domainTags || []).map(esc).join(" · ");
  const themes = (b.themes || []).slice(0, 4).map(esc).join(" · ");
  return sec(
    "Reading now",
    `<div class="rdg-now">` +
      (cover ? `<img class="rdg-now-cover" src="${esc(cover)}" alt="" loading="lazy">` : "") +
      `<div class="rdg-now-meta"><p class="rdg-now-title">${esc(b.title || "Untitled")}</p>` +
      (b.author ? `<p class="rd-meta label rdg-now-author">${esc(b.author)}</p>` : "") +
      (tags ? `<p class="rd-meta label">${tags}</p>` : "") +
      (themes ? `<p class="rd-meta label">themes — ${themes}</p>` : "") +
      `</div></div>` +
      readingNotes(cur && cur.notes)
  );
}

function readingWheel(wheel) {
  const dist = (wheel && wheel.distribution) || {};
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (total < 1)
    return sec(
      "Roundedness — earned on finishes",
      empty("The wheel fills as books are finished, not shelved — a domain lights up when its first book is kept. Honest and empty until then.")
    );
  const max = Math.max(...entries.map(([, n]) => n));
  const bars = entries
    .map(
      ([tag, n]) =>
        `<div class="wh-row"><span class="wh-label label">${esc(tag)}</span><span class="wh-bar"><i style="width:${Math.round(
          (n / max) * 100
        )}%"></i></span><span class="wh-n num">${esc(n)}</span></div>`
    )
    .join("");
  return sec("Roundedness — what's been kept", bars);
}

function readingConstellation(cst) {
  if (!cst || !cst.ready || !Array.isArray(cst.nodes) || cst.nodes.length < 4) {
    const seedNote = (cst && cst.note) || "the constellation begins with the first idea you keep";
    return sec(
      "The idea constellation",
      `<div class="rdg-seed"><span class="rdg-seed-dot" aria-hidden="true"></span><p class="rd-archive">${esc(seedNote)}</p></div>`
    );
  }
  const nodes = cst.nodes.slice(0, 40);
  const edges = Array.isArray(cst.edges) ? cst.edges : [];
  const W = 360,
    H = 360,
    cx = W / 2,
    cy = H / 2,
    r = 140,
    pos = {};
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
      return `<g class="cst-node${recent}"><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5"/><title>${esc(n.label || "")}</title></g>`;
    })
    .join("");
  return sec(
    "The idea constellation",
    `<figure class="rdg-cst"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="A graph of ${nodes.length} ideas kept and their connections"><g class="cst-edges">${edgeSvg}</g><g class="cst-nodes">${nodeSvg}</g></svg><figcaption class="label">${nodes.length} ideas kept · ${edges.length} connections</figcaption></figure>`
  );
}

async function renderReading(d) {
  d = d || {};
  const [shelf, cst] = await Promise.all([tryJSON("/api/reading_shelf"), tryJSON("/api/constellation")]);
  const st = d.stats || {};
  const counts = (shelf && shelf.counts) || {};
  const cur = (d.cockpit_line || {}).current || (shelf && (shelf.reading || [])[0]) || null;
  const head = figs([
    fig(st.finished_count ?? counts.finished ?? 0, "finished"),
    counts.queue != null ? fig(counts.queue, "in the queue") : null,
    st.input_streak_days ? fig(st.input_streak_days, "day streak") : null,
    st.sessions_90d != null ? fig(st.sessions_90d, "sessions · 90d") : null,
  ]);
  const body =
    readingNow(cur) +
    readingBookList("Up next", shelf && shelf.queue, {
      emptyMsg: "Nothing queued yet — the next book is the whole point.",
      fallbackNote: "",
    }) +
    readingBookList("Finished — and what stuck", shelf && shelf.finished, {
      emptyMsg: "No finishes yet this cycle — the shelf fills a book at a time.",
      fallbackNote: "Kept on the shelf — a debrief adds the takeaway here.",
    }) +
    readingShelfBlock("Set down", shelf && shelf.set_down, "") +
    readingWheel(d.wheel) +
    readingConstellation(cst);
  return head + body + note("The Mind pillar — measuring what's kept, not what's consumed. Private fields (retention, mood) never reach this page.");
}

/* ── The character sheet (/data/character/) — resurrected from the legacy RPG
   page at v5 quality. The hero composes the three proven primitives: the real
   weight-driven silhouette (dfBody) held inside the 7-segment pillar ring
   (arcs fill by raw_score), framed by the tier emblem. Everything below is a
   readout of the nightly character engine — nothing here computes a score.
   Data: /api/character (live, 900s) + character_stats.json (daily: timeline,
   tiers, weekly history) + /api/journey_waveform + /api/journey. Every section
   degrades independently; post-reset empties render honest "not yet" states.
   Emoji served by the APIs are IGNORED (§8) — pillars render domainIcon marks. */
const CH_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"];
const CH_ABBR = { sleep: "SLP", movement: "MOV", nutrition: "NUT", metabolic: "MET", mind: "MIN", relationships: "REL", consistency: "CON" };
const CH_FLAVOR = {
  Foundation: "Laying the base: the habits and the floor.",
  Momentum: "The base holds and starts compounding.",
  Discipline: "Consistency under load, not just on good weeks.",
  Mastery: "The system runs itself most days.",
  Elite: "The far end of what an N=1 can reach.",
};
const chDelta = (v, unit = "") => {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return `<span class="ch-d ch-d0">0${unit}</span>`;
  return n > 0 ? `<span class="ch-d ch-dup">+${fmt(n)}${unit}</span>` : `<span class="ch-d ch-ddn">−${fmt(Math.abs(n))}${unit}</span>`;
};

// Shared context for wireCharacter's time-travel re-render (P1.3): the hero +
// stat block rebuild for a scrubbed date; the slow-moving sections stand.
let _chCtx = null;

/* 1 · Hero — the figure, leveled. Silhouette girth = the real weight; ring
   segments = the seven pillar scores; the emblem = tier + level. If the
   journey isn't available the composite number holds the center instead.
   A builder (not inline) so time travel can redraw it for any date. */
function chHeroHtml(ch, pillars, jj, wave) {
  const tier = String(ch.tier || "Foundation");
  const level = Math.round(Number(ch.level) || 1);
  const composite = Number(ch.composite_score);
  const RING = 360;
  let center;
  if (jj && isFinite(Number(jj.start_weight_lbs)) && isFinite(Number(jj.current_weight_lbs)) && Number(jj.start_weight_lbs) !== Number(jj.goal_weight_lbs)) {
    const g = Math.max(0, Math.min(1, (Number(jj.current_weight_lbs) - Number(jj.goal_weight_lbs)) / (Number(jj.start_weight_lbs) - Number(jj.goal_weight_lbs))));
    center = `<svg x="118" y="76" width="124" height="208" viewBox="0 0 300 620" aria-hidden="true">` +
      `<circle class="ch-body" cx="150" cy="64" r="${(29 + 6 * g).toFixed(1)}"></circle>` +
      `<path class="ch-body" d="${dfBody(g)}"></path></svg>`;
  } else {
    center = `<text class="ch-center num" x="180" y="192" text-anchor="middle">${Number.isFinite(composite) ? Math.round(composite) : "—"}</text>`;
  }
  const legend = pillars.map((p) => `<span class="ch-leg"><i class="ch-dot" style="background:var(--pillar-${esc(p.name)},var(--ember))"></i>${esc(CH_ABBR[p.name] || p.name)}</span>`).join("");
  const tt = ch.time_travel ? `<span class="ch-ttflag">time travel</span> · ` : "";
  return `<section class="rd-sec ch-hero" data-tier="${esc(tier.toLowerCase())}">
    <div class="ch-stage">
      <div class="ch-figwrap">
        <svg class="ch-ringsvg" viewBox="0 0 ${RING} ${RING}" role="img" aria-label="The seven pillar ring around the body silhouette — each arc fills with its pillar's score">${pillarRing(pillars, { size: RING })}${center}</svg>
        <div class="ch-legend label">${legend}</div>
      </div>
      <div class="ch-id">
        <div class="ch-emblem">${tierEmblem(tier, level)}</div>
        <p class="ch-class label">${tt}${esc(tier)} · Level ${level} of 100${ch.as_of_date ? ` · as of ${esc(String(ch.as_of_date))}` : ""}</p>
        <p class="ch-idnote">One character, seven pillars — scored nightly from the same data every other page reads. The silhouette is the real weight; the ring is today's pillar scores; the emblem evolves with the tier.</p>
        ${figs([
          Number.isFinite(composite) && fig(fmt(composite), "composite", ch.composite_delta_1d != null ? `${Number(ch.composite_delta_1d) >= 0 ? "+" : ""}${fmt(ch.composite_delta_1d)} d/d` : ""),
          ch.xp_total != null && fig(fmt(ch.xp_total), "xp"),
          !ch.time_travel && (wave && wave.day_n) != null && fig(`day ${wave.day_n}`, "of the experiment"),
        ])}
      </div>
    </div>
  </section>`;
}

/* 2 · The seven pillars — RPG stat block + radar. Also a builder (time travel). */
/* ADR-104: each pillar carries its own honest "why" — engine-computed provenance
   (coverage holds, behaviors that didn't happen, what's dragging), never narrated. */
function chWhy(p) {
  const drv = p.drivers || {};
  const names = (a) => (a || []).map((n) => ttl(n)).join(", ");
  if (p.coverage_hold) {
    const cov = p.data_coverage != null ? `${Math.round(Number(p.data_coverage) * 100)}%` : "too little";
    return `Levels frozen — only ${cov} of this pillar's data exists right now. The engine won't judge on gaps: no data can't climb, and no data can't crash.`;
  }
  const bits = [];
  if (drv.absent && drv.absent.length) bits.push(`not happening: ${names(drv.absent)} (scores 0 while absent)`);
  if (drv.dragging && drv.dragging.length) bits.push(`dragging: ${names(drv.dragging)}`);
  if (drv.top && drv.top.length) bits.push(`carried by: ${names(drv.top)}`);
  if (!bits.length) return "";
  return bits.join(" · ");
}

function chStatHtml(pillars, hist) {
  const rows = pillars.map((p) => {
    const scoreVals = hist.map((w) => ({ v: (w.pillars && w.pillars[p.name]) || 0, d: w.week_end })).slice(-8);
    const spark = scoreVals.filter((s) => s.v > 0).length >= 2 ? sparkline(scoreVals, { height: 26 }) : "";
    const raw = Math.max(0, Math.min(Number(p.raw_score) || 0, 100));
    const why = chWhy(p);
    return `<div class="ch-row">
      <span class="ch-ric" style="color:var(--pillar-${esc(p.name)},var(--ember))">${domainIcon(p.name)}</span>
      <span class="ch-rname">${esc(ttl(p.name))}</span>
      <span class="ch-rlv label">Lv ${Math.round(Number(p.level) || 1)}${p.coverage_hold ? `<span class="ch-hold" title="levels frozen — not enough data to judge">held</span>` : ""}</span>
      <span class="ch-rbar"><i style="width:${raw}%;background:var(--pillar-${esc(p.name)},var(--ember))"></i><b style="left:25%"></b><b style="left:50%"></b><b style="left:75%"></b></span>
      <span class="ch-rraw num">${fmt(raw)}<small>/100</small></span>
      ${chDelta(p.xp_delta, " xp")}
      ${spark ? `<span class="ch-rspark">${spark}</span>` : ""}
    </div>${why ? `<p class="ch-rwhy">${esc(why)}</p>` : ""}`;
  }).join("");
  const radar = radarChart(pillars.map((p) => ({ key: p.name, label: CH_ABBR[p.name] || p.name, value: p.raw_score })));
  return sec("The seven pillars", `<div class="ch-statgrid"><div class="ch-rows">${rows}</div>${radar}</div>
    <p class="rd-why">Each pillar scores 0–100 nightly from its own real data (wearables, the food log, habits, labs), then an EMA smooths it and a streak gate decides level moves — one great day can't swing a level, and a level-up also needs the day itself to have been lived at that level. Behaviors that didn't happen score zero; a missing sensor reading doesn't. XP is the daily currency: strong days earn it, weak days bleed it.</p>`);
}

async function renderCharacter(d) {
  const ch = (d && d.character) || {};
  const pillars = ((d && d.pillars) || []).slice().sort((a, b) => CH_ORDER.indexOf(a.name) - CH_ORDER.indexOf(b.name));
  if (!pillars.length) return empty("The character sheet computes nightly — it fills in as the first days of data land.");
  const [stats, wave, j, cfgRaw, ach, pres] = await Promise.all([
    tryJSON("/data/character_stats.json"), tryJSON("/api/journey_waveform"), tryJSON("/api/journey"),
    tryJSON("/api/character_config"), tryJSON("/api/achievements"), tryJSON("/api/presence"),
  ]);
  // The mechanics contract (P1.2) — fail-soft: without it the mechanics panels
  // simply don't render and the sheet stands on P1.1 alone.
  const cfg = cfgRaw && cfgRaw.available ? cfgRaw : null;
  const sc = (stats && stats.character) || {};
  const tier = String(ch.tier || "Foundation");
  const composite = Number(ch.composite_score);
  const jj = (j && j.journey) || null;
  const hist = (stats && stats.pillar_history) || [];
  _chCtx = { jj, wave, hist, genesis: (wave && wave.genesis) || null };

  const hero = chHeroHtml(ch, pillars, jj, wave);
  /* ADR-104: the quiet stretch, said plainly — fail-closed /api/presence, same
     calm voice as the cockpit/story lines. No red banner; the sheet just tells
     the truth about why some pillars are falling or frozen right now. */
  const quiet = pres && pres.available && pres.in_lull && Number(pres.gap_days) >= 2
    ? `<p class="rd-archive ch-quiet">A quiet stretch — manual logging has been dark for ${esc(String(Math.round(Number(pres.gap_days))))} days${pres.passive_still_flowing ? " while the wearables keep flowing" : ""}. The sheet doesn't look away: behaviors that aren't happening score zero, thin pillars freeze instead of climbing, and the levels below are what the data actually earns.</p>`
    : "";
  const statblock = chStatHtml(pillars, hist);

  /* 12 · Time travel — scrub the sheet to any past day (the cockpit's own
     day-slider grammar). The hero + stat block redraw from /api/character?date=;
     everything below stays (it's the record, not the day). */
  const scrub = `<div class="ch-tt" data-ch-tt hidden>
    <label class="label" for="ch-scrub">time travel</label>
    <input id="ch-scrub" data-ch-scrub type="range" min="0" max="1" step="1" value="1" aria-label="Scrub the character sheet to a past date">
    <span class="label" data-ch-scrub-label>today</span>
  </div>`;

  /* 3 · The tier ladder. */
  const tiers = (stats && stats.tiers) || [];
  const ladder = tiers.length ? sec("The tier ladder", `<div class="ch-ladder">` + tiers.map((t) => {
    const cur = t.status === "current";
    return `<div class="ch-rung${cur ? " is-current" : ""}${t.status === "locked" ? " is-locked" : ""}" data-tier="${esc(String(t.name || "").toLowerCase())}">
      <span class="ch-rung-em">${tierEmblem(t.name, null)}</span>
      <span class="ch-rung-name">${esc(t.name)}</span>
      <span class="ch-rung-band label">Lv ${t.min_level}–${t.max_level}</span>
      <span class="ch-rung-fl">${esc(CH_FLAVOR[t.name] || "")}</span>
      ${cur ? `<span class="ch-rung-now label">now</span>` : ""}
    </div>`;
  }).join("") + `</div>` +
    (sc.next_tier ? `<p class="rd-archive">Next tier: <strong>${esc(sc.next_tier)}</strong> at level ${esc(String(sc.next_tier_level || ""))} — crossing a tier line takes a longer sustained streak than a normal level-up.</p>` : "")) : "";

  /* 6-9 · The mechanics layer (P1.2) — the gamification made legible, every
     number interpolated from the live engine config so it can never lie. */
  let mechanics = "";
  if (cfg) {
    const lv = cfg.leveling || {};
    const scores = Object.fromEntries(pillars.map((p) => [p.name, Number(p.raw_score) || 0]));
    const weights = Object.fromEntries(Object.entries(cfg.pillars || {}).map(([n, p]) => [n, Number(p.weight) || 0]));
    const wTotal = Object.values(weights).reduce((a, b) => a + b, 0) || 1;

    /* 6 · What it takes — the next level. */
    const perLvl = Number(lv.xp_per_level) || 100;
    const bufThr = Number(lv.xp_buffer_threshold) || 20;
    const xpNow = Math.max(0, Number(ch.xp_total) || 0) % perLvl;
    const gates = (lv.tier_streak_overrides || {})[tier] || { up: lv.level_up_streak_days, down: lv.level_down_streak_days };
    const tick = (n, cls) => `<span class="ch-ticks">${Array.from({ length: Math.max(0, Math.min(Number(n) || 0, 21)) }, () => `<i class="${cls}"></i>`).join("")}<b class="label">${esc(String(n))} days</b></span>`;
    const bottlenecks = pillars.slice().sort((a, b) => (a.raw_score || 0) - (b.raw_score || 0)).slice(0, 2);
    const nextlvl = sec("What it takes — the next level", `
      <div class="ch-xpbar" role="img" aria-label="XP buffer: ${fmt(xpNow)} of ${perLvl}, shield at ${bufThr}">
        <i style="width:${Math.min(100, (xpNow / perLvl) * 100).toFixed(1)}%"></i>
        <b style="left:${(bufThr / perLvl) * 100}%"></b>
      </div>
      <p class="rd-why">XP banked: <strong class="num">${fmt(xpNow)}</strong> of ${perLvl}. The mark at ${bufThr} is <strong>the shield</strong> — a pillar can't level DOWN while its buffer holds above it. Strong days earn XP, every day decays ${fmt(lv.daily_xp_decay)} — coasting bleeds the shield.</p>
      <div class="ch-gates">
        <div class="ch-gate"><span class="label">level up</span>${tick(gates.up, "up")}</div>
        <div class="ch-gate"><span class="label">level down</span>${tick(gates.down, "dn")}</div>
      </div>
      <p class="rd-why">In ${esc(tier)}, a level-up takes <strong>${esc(String(gates.up))} sustained days</strong> above the line — but a level-down takes ${esc(String(gates.down))}. The asymmetry is deliberate: an "up" is earned, a "down" needs real decline, and a single day can never swing either.</p>
      ${bottlenecks.length ? `<p class="rd-prose">The bottlenecks right now: ${bottlenecks.map((p) => `<strong>${esc(ttl(p.name))}</strong> (${fmt(p.raw_score)}/100 — a level here moves the character +${((weights[p.name] || 1 / 7) / wTotal).toFixed(2)} weighted)`).join(" and ")}. The fastest route to the next character level runs through the weakest pillar, not the strongest.</p>` : ""}`);

    /* 7 · The XP economy — the bands ladder, today's pillars placed on it. */
    const bands = (cfg.xp_bands || []).slice().sort((a, b) => (b.min_raw_score || 0) - (a.min_raw_score || 0));
    const bandRows = bands.map((b, i) => {
      const lo = Number(b.min_raw_score) || 0;
      const hi = i === 0 ? 100 : Number(bands[i - 1].min_raw_score);
      const here = pillars.filter((p) => (p.raw_score || 0) >= lo && (p.raw_score || 0) < (i === 0 ? 101 : hi));
      return `<div class="ch-band${here.length ? " has-p" : ""}">
        <span class="ch-band-r label">${lo}–${i === 0 ? 100 : hi - 1}</span>
        <span class="ch-band-xp num ${Number(b.xp) > 0 ? "ch-dup" : Number(b.xp) < 0 ? "ch-ddn" : "ch-d0"}">${Number(b.xp) > 0 ? "+" : ""}${esc(String(b.xp))} xp/day</span>
        <span class="ch-band-p">${here.map((p) => `<span class="ch-ric" style="color:var(--pillar-${esc(p.name)},var(--ember))" title="${esc(ttl(p.name))} · ${fmt(p.raw_score)}">${domainIcon(p.name)}</span>`).join("")}</span>
      </div>`;
    }).join("");
    const economy = sec("The XP economy", `<div class="ch-bands">${bandRows}</div>
      <p class="rd-why">Each pillar's nightly score lands in a band and earns (or loses) that XP — today's pillars are placed where they scored. Against it runs the decay: <strong>−${fmt(lv.daily_xp_decay)} XP every day</strong>, no exceptions. The game is simple and honest: you can't bank a good week and coast.</p>`);

    /* 8 · Cross-pillar effects — evaluated live against today's raw scores. */
    const evalCond = (cond) => {
      const parts = String(cond || "").split(/\s+AND\s+/i);
      let active = true;
      for (const part of parts) {
        const m = /^\s*(\w+)\s*(<=|>=|<|>|==?)\s*([\d.]+)\s*$/.exec(part);
        if (!m) return null;
        const num = Number(m[3]);
        const vals = m[1] === "all_pillars" ? Object.values(scores) : (m[1] in scores ? [scores[m[1]]] : null);
        if (!vals) return null;
        const ok = vals.every((v) => (m[2] === "<" ? v < num : m[2] === ">" ? v > num : m[2] === "<=" ? v <= num : m[2] === ">=" ? v >= num : v === num));
        if (!ok) active = false;
      }
      return active;
    };
    const fxChips = (cfg.cross_pillar_effects || []).map((e) => {
      const active = evalCond(e.condition);
      const targets = Object.entries(e.targets || {}).map(([t, v]) => {
        const pct = Math.round(Math.abs(Number((v || {}).value) || 0) * 100);
        const sign = (Number((v || {}).value) || 0) >= 0 ? "+" : "−";
        return `<span class="ch-fx-t"><span class="ch-ric" style="color:var(--pillar-${esc(t)},var(--ember))">${t === "_all" ? "" : domainIcon(t)}</span>${t === "_all" ? "all pillars" : ""} ${sign}${pct}%</span>`;
      }).join("");
      return `<div class="ch-fx${active === true ? " is-active" : ""}${active === null ? " is-inert" : ""}">
        <span class="ch-fx-name">${esc(e.name || "")}</span>
        <span class="ch-fx-cond label">${active === true ? "active — " : active === false ? "activates when " : ""}${esc(String(e.condition || "").replace(/_/g, " "))}</span>
        <span class="ch-fx-targets">${targets}</span>
      </div>`;
    }).join("");
    const effects = fxChips ? sec("Cross-pillar effects", `<div class="ch-fxgrid">${fxChips}</div>
      <p class="rd-why">The pillars aren't independent — the engine models the physiology: poor sleep drags training and mind; strong nutrition and movement compound into metabolic health; everything above the line at once earns an alignment bonus. Active effects are evaluated from today's real scores.</p>`) : "";

    /* 9 · What feeds each pillar — component weights + targets, disclosure per pillar. */
    const feeds = Object.keys(cfg.pillars || {}).length ? sec("What feeds each pillar", `<div class="ch-feeds">` +
      pillars.map((p) => {
        const pc = (cfg.pillars || {})[p.name] || {};
        const comps = Object.entries(pc.components || {});
        if (!comps.length) return "";
        const compRows = comps.map(([cn, cv]) => {
          const w = Math.round((Number(cv.weight) || 0) * 100);
          const targets = Object.entries(cv).filter(([k, v]) => k !== "weight" && typeof v !== "object").map(([k, v]) => `${ttl(k)} ${fmt(v)}`).join(" · ");
          return `<div class="ch-comp"><span class="ch-comp-n">${esc(ttl(cn))}</span><span class="ch-comp-bar"><i style="width:${w}%;background:var(--pillar-${esc(p.name)},var(--ember))"></i></span><span class="ch-comp-w num">${w}%</span>${targets ? `<span class="ch-comp-t label">${esc(targets)}</span>` : ""}</div>`;
        }).join("");
        return `<details class="ch-feed"><summary><span class="ch-ric" style="color:var(--pillar-${esc(p.name)},var(--ember))">${domainIcon(p.name)}</span>${esc(ttl(p.name))} <span class="label">· ${Math.round(((weights[p.name] || 0) / wTotal) * 100)}% of the character</span></summary><div class="ch-feed-body">${compRows}</div></details>`;
      }).join("") + `</div>
      <p class="rd-why">Every pillar is a weighted blend of measurable components with explicit targets — nothing subjective, nothing self-reported where a sensor exists. The weights are live from the engine's own config: change the config, and this page changes with it.</p>`) : "";

    mechanics = nextlvl + economy + effects + feeds;
  }

  /* 4 · The record — level events, the weekly heatmap, the daily waveform. */
  const tl = (stats && stats.timeline) || [];
  const tlHtml = tl.length
    ? `<ul class="ch-tl">${tl.slice(-14).reverse().map((e) => `<li><span class="label">${esc(String(e.date || "").slice(0, 10))}</span><span class="ch-tl-ev">${esc(e.event || "")}</span>${e.character_level != null ? `<span class="ch-tl-lv label">Lv ${esc(String(Math.round(e.character_level)))}</span>` : ""}</li>`).join("")}</ul>`
    : `<p class="rd-archive">No level events yet this cycle — a level only moves after a sustained multi-day streak, so the first entries here are earned, not noise.</p>`;
  let heat = "";
  if (hist.length) {
    const weeks = hist.slice(-12);
    heat = `<div class="ch-heat" role="img" aria-label="Weekly pillar scores, ${weeks.length} weeks">` +
      `<div class="ch-heat-row ch-heat-head"><span></span>${weeks.map((w) => `<span class="label">${esc(w.week_label || "")}</span>`).join("")}</div>` +
      pillars.map((p) => `<div class="ch-heat-row"><span class="ch-heat-lbl" style="color:var(--pillar-${esc(p.name)},var(--ember))">${domainIcon(p.name)}</span>` +
        weeks.map((w) => {
          const v = Math.max(0, Math.min(Number((w.pillars || {})[p.name]) || 0, 100));
          return `<span class="ch-cell" title="${esc(ttl(p.name))} · ${esc(w.week_label || "")} · ${fmt(v)}" style="background:color-mix(in oklch, var(--ember) ${Math.round(4 + v * 0.6)}%, var(--surface))"></span>`;
        }).join("") + `</div>`).join("") + `</div>`;
  }
  let waveHtml = "";
  const days = (wave && wave.days) || [];
  if (days.length >= 2) {
    const W = Math.max(120, days.length * 6), H = 44, MAX = Number(wave.max_score) || 700;
    const bars = days.map((dd, i) => {
      const v = Number(dd.score);
      if (!Number.isFinite(v) || dd.color === "gray") return `<rect x="${i * 6}" y="${H - 2}" width="4" height="2" class="ch-wv-na"/>`;
      const h = Math.max(2, (v / MAX) * (H - 4));
      return `<rect x="${i * 6}" y="${(H - h).toFixed(1)}" width="4" height="${h.toFixed(1)}" class="ch-wv" style="opacity:${(0.3 + 0.7 * (v / MAX)).toFixed(2)}"><title>${esc(dd.date || "")} · ${Math.round(v)}/${MAX}</title></rect>`;
    }).join("");
    waveHtml = `<figure class="chart ch-wave"><figcaption class="label">The waveform — whole-life score (0–${MAX}), one bar per day since genesis</figcaption><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="max-width:${days.length * 14}px" aria-label="Daily whole-life score since genesis">${bars}</svg></figure>`;
  }
  const record = sec("The record", tlHtml + heat + waveHtml);

  /* 11 · Unlocks — the badge wall. Every mark is generative (badgeMark, seeded
     by the badge id) so any future badge draws itself. All-unearned is framed
     as intent: the wall is the map of what's ahead, not an empty shelf. */
  let badges = "";
  const achList = (ach && (ach.achievements || ach.badges)) || [];
  if (achList.length) {
    const earned = achList.filter((b) => b.earned);
    const CAT_TTL = { streak: "Streaks", level: "Level milestones", milestone: "Milestones", data: "Data consistency", challenge: "Challenges", science: "Science" };
    const cats = [...new Set(achList.map((b) => b.category || "other"))];
    const groups = cats.map((c) => {
      const items = achList.filter((b) => (b.category || "other") === c);
      return `<div class="ch-bgroup"><p class="label">${esc(CAT_TTL[c] || ttl(c))}</p><div class="ch-bgrid">` +
        items.map((b) => `<div class="ch-badge${b.earned ? " is-earned" : ""}" title="${esc(b.description || "")}">
          <span class="ch-badge-m">${badgeMark(b.id, { earned: !!b.earned })}</span>
          <span class="ch-badge-n">${esc(b.label || b.id)}</span>
          <span class="ch-badge-h label">${b.earned ? esc(String(b.earned_date || "").slice(0, 10)) : esc(b.unlock_hint || b.description || "")}</span>
        </div>`).join("") + `</div></div>`;
    }).join("");
    badges = sec("Unlocks — the map of what's ahead",
      figs([fig(String(earned.length), "earned"), fig(String(achList.length - earned.length), "still locked")]) +
      (earned.length === 0 ? `<p class="rd-archive">Nothing earned yet this cycle — every mark below is drawn the moment it's unlocked, and the engine checks nightly. The wall isn't empty; it's the route.</p>` : "") +
      groups);
  }

  /* 5 · Follow the level-ups. */
  const sub = `<section class="rd-sec ch-sub">
    <h2 class="rd-h">Follow the level-ups</h2>
    <p class="rd-prose">One email when the character levels up — the only thing this page will ever send.</p>
    <form class="ask-row" data-lvlsub><input class="ask-in" type="email" required autocomplete="email" placeholder="you@example.com" aria-label="Email for level-up alerts"><button class="ask-btn" type="submit">notify me</button></form>
    <p class="rd-archive" data-lvlsub-status hidden></p>
  </section>`;

  /* 10 · The math — prose interpolated from the live config so it can never lie. */
  const lvv = (cfg && cfg.leveling) || null;
  const math = lvv
    ? sec("The math", `<p class="rd-prose">Each pillar scores 0–100 nightly from weighted components (above). Components that measure a <strong>behavior</strong> — logging food, journaling, training — score zero when the behavior doesn't happen; components that measure a <strong>sensor</strong> simply go quiet, and the engine won't judge what it can't see${lvv.level_change_min_coverage != null ? ` (below ${esc(String(Math.round(Number(lvv.level_change_min_coverage) * 100)))}% data coverage, levels freeze in both directions)` : ""}. An exponential moving average (λ = ${esc(String(lvv.ema_lambda))} over ${esc(String(lvv.ema_window_days))} days) smooths the noise into a level score. A <strong>streak counter</strong> then gates every level change — the smoothed score has to hold above (or below) the line for the full gate, a level-up also requires the day itself to have scored at the new level, and crossing a tier boundary demands a longer streak still. Bigger honest gaps move in bigger steps, so pillars converge to what the data earns instead of marching in lockstep. XP runs alongside as resilience: ${esc(String(lvv.xp_per_level))} XP to a level, decaying ${fmt(lvv.daily_xp_decay)} a day, with the buffer under ${esc(String(lvv.xp_buffer_threshold))} XP the only state where a level-down can land. The character level is the weighted average of the seven pillar levels, floored — so it understates, never flatters.</p>
      <p class="rd-archive">The plain-language version lives on <a href="/method/character/">the character explainer</a>; the engine itself runs nightly in the platform's compute layer, and every number in this section is read live from its config.</p>`)
    : `<p class="rd-archive">How the engine works — the pillar weights, the XP economy, the streak gates — is documented on <a href="/method/character/">the character explainer</a>; the algorithms run nightly in the platform's compute layer.</p>`;

  return hero + quiet + scrub + statblock + ladder + mechanics + record + badges + sub + math +
    note("A motivational lens on real data, not a medical score — every input is correlative and N=1.");
}

// The sheet's entrance choreography — ring arcs sweep in (staggered via each
// segment's transition-delay), stat bars fill. Re-run after every time-travel
// redraw. Motion-gated; fail-open: without motion everything is simply drawn.
function chAnimate(scope) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const root = scope || document;
  root.querySelectorAll(".pring-fill").forEach((el) => {
    const final = el.getAttribute("stroke-dashoffset") || "0";
    const circ = 2 * Math.PI * Number(el.getAttribute("r") || 0);
    el.style.strokeDashoffset = String(circ);
    requestAnimationFrame(() => requestAnimationFrame(() => { el.style.strokeDashoffset = final; }));
  });
  root.querySelectorAll(".ch-rbar i").forEach((el) => {
    const final = el.style.width;
    el.style.width = "0%";
    requestAnimationFrame(() => requestAnimationFrame(() => { el.style.width = final; }));
  });
}

function wireCharacter() {
  chAnimate();

  /* Time travel (P1.3) — the cockpit's day-slider grammar: drag from cycle-1
     genesis (Apr 1) to today; the hero + stat block redraw as of that date via
     /api/character?date= (immutable-past cached server-side, so scrubbing is
     cheap). Dates before this cycle's genesis show the PRIOR cycle — labeled.
     Deep-linkable via ?date=. */
  const tt = document.querySelector("[data-ch-tt]");
  const slider = document.querySelector("[data-ch-scrub]");
  const lab = document.querySelector("[data-ch-scrub-label]");
  if (tt && slider && lab) {
    const today = new Date().toISOString().slice(0, 10);
    const t0 = Date.parse("2026-04-01T12:00:00");
    const days = Math.max(1, Math.round((Date.parse(`${today}T12:00:00`) - t0) / 86400000));
    slider.max = String(days);
    slider.value = String(days);
    const dOf = (i) => new Date(t0 + i * 86400000).toISOString().slice(0, 10);
    const genesis = (_chCtx && _chCtx.genesis) || null;
    const labelFor = (dd) => (dd === today ? "today" : `${dd}${genesis && dd < genesis ? " · prior cycle" : ""}`);
    const redraw = async (dd) => {
      const heroEl = document.querySelector(".ch-hero");
      const rowsEl = document.querySelector(".ch-rows");
      const statEl = rowsEl ? rowsEl.closest(".rd-sec") : null;
      if (!heroEl) return;
      heroEl.style.opacity = "0.6";
      const body = await tryJSON(dd === today ? "/api/character" : `/api/character?date=${dd}`);
      heroEl.style.opacity = "";
      if (!body || !body.pillars || !body.pillars.length) return;
      const ps = body.pillars.slice().sort((a, b) => CH_ORDER.indexOf(a.name) - CH_ORDER.indexOf(b.name));
      const ctx = _chCtx || {};
      heroEl.outerHTML = chHeroHtml(body.character || {}, ps, ctx.jj, ctx.wave);
      if (statEl) statEl.outerHTML = chStatHtml(ps, ctx.hist || []);
      chAnimate();
      try { history.replaceState({}, "", dd === today ? location.pathname : `${location.pathname}?date=${dd}`); } catch (e) { /* non-fatal */ }
    };
    let deb = null;
    slider.addEventListener("input", () => {
      const dd = dOf(Number(slider.value));
      lab.textContent = labelFor(dd);
      clearTimeout(deb);
      deb = setTimeout(() => redraw(dd), 350);
    });
    tt.hidden = false;
    // Deep link: /data/character/?date=YYYY-MM-DD starts the sheet time-travelled.
    const deep = new URLSearchParams(location.search).get("date");
    if (deep && /^\d{4}-\d{2}-\d{2}$/.test(deep) && deep < today) {
      const idx = Math.max(0, Math.min(days, Math.round((Date.parse(`${deep}T12:00:00`) - t0) / 86400000)));
      slider.value = String(idx);
      lab.textContent = labelFor(deep);
      redraw(deep);
    }
  }
  // Level-up subscribe — same contract as /subscribe/ (double-opt-in), tagged
  // with its own source so the alert list is separable server-side.
  const form = document.querySelector("[data-lvlsub]");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector("input"), btn = form.querySelector("button"), status = document.querySelector("[data-lvlsub-status]");
      const email = (input.value || "").trim();
      if (!email || !email.includes("@")) { input.focus(); return; }
      btn.disabled = true;
      try {
        const r = await fetch("/api/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, source: "levelup_alert" }) });
        status.hidden = false;
        status.textContent = r.ok ? "Check your inbox to confirm — you'll hear from this page only when a level moves." : "That didn't go through — try again in a moment.";
        if (r.ok) form.hidden = true;
      } catch (err) { status.hidden = false; status.textContent = "Network hiccup — try again in a moment."; }
      btn.disabled = false;
    });
  }
}

const RENDERERS = {
  vitals: renderPulse, supplements: renderSupplements, labs: renderLabs, physical: renderPhysical, training: renderTraining, nutrition: renderNutrition, glucose: renderGlucose, sleep: renderSleep, mind: renderMind, reading: renderReading, vices: renderVices, ledger: renderLedger, discoveries: renderDiscoveries, biology: renderGenome, challenges: renderChallenges, protocols: renderProtocols, experiments: renderExperiments, habits: renderHabits, board: renderBoard, platform: renderPlatform, cost: renderCost, data: renderData, pipeline: renderPipeline, results: renderResults, tools: renderTools, ask: renderAsk, cycles: renderCycles, inference: renderInference, wrong: renderWrong, survival: renderSurvival, postmortems: renderPostmortems, mirror: renderMirror, explorer: renderExplorer, intelligence: renderCorrelations, predictions: renderPredictions, benchmarks: renderBenchmarks, character: renderCharacter };
const WIRE = {
  ask: () => {
    const mount = document.querySelector("[data-ask-mount]");
    if (!mount) return;
    mountAsk(mount, {
      chips: ASK_CHIPS,
      note: "Answers are AI-generated from the published data — correlative, never medical advice. Rate-limited (5/hour), and may be paused by the budget guard.",
    });
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
  results: () => wireDataFigure(),
  character: wireCharacter,
  physical: () => {
    // P0.2 — silhouette scrubs the trend marker in lockstep; P4 adds the inverse:
    // hovering the weight chart drives the silhouette to that day's weigh-in.
    // Fire-and-forget both ways — a failure in the link never breaks either.
    const dfRender = wireDataFigure(moveTrendMarker);
    if (dfRender) {
      document.addEventListener("chart:point", (e) => {
        try {
          if (!e.target.closest || !e.target.closest(".wt-chart")) return;
          const w = Number(e.detail && e.detail.v);
          if (Number.isFinite(w)) dfRender(w);
        } catch (err) { /* decorative link */ }
      });
    }
  },
};

// P0.2 — silhouette scrubber wiring, reusable. `onWeight(w)` fires on every render so a
// caller can link another element (the physical page passes the trend-chart marker).
function wireDataFigure(onWeight) {
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
    if (onWeight) try { onWeight(w); } catch (e) { /* link is decorative — never break the scrub */ }
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
      playing = !playing; e.target.innerHTML = playing ? `${icon("pause")} pause` : `${icon("play")} morph`;
      if (playing) {
        let dir = -1, w = START; cancelAnimationFrame(raf);
        (function loop() { w += dir * 1.4; if (w <= GOAL) { w = GOAL; dir = 1; } if (w >= START) { w = START; dir = -1; } render(w); if (playing) ploop = requestAnimationFrame(loop); })();
      } else { cancelAnimationFrame(ploop); }
    });
  }
  render(NOW);   // open on the honest current state
  return render; // uplevel P4 — lets the chart's hover cross-highlight drive the figure
}

// P0.2 — move the trend-chart's horizontal scrub marker to weight `w` (lockstep with the
// silhouette). Below the chart's data floor (toward goal) → pin to the axis bottom + flag.
function moveTrendMarker(w) {
  const fig = document.querySelector(".wt-chart");
  if (!fig) return;
  const m = fig.querySelector("[data-wt-marker]");
  if (!m) return;
  const min = parseFloat(fig.dataset.wtMin), max = parseFloat(fig.dataset.wtMax), H = parseFloat(fig.dataset.wtH), P = parseFloat(fig.dataset.wtP);
  if (![min, max, H, P].every(Number.isFinite) || max === min) return;
  const below = w < min;
  const y = below ? (H - P) : (P + (1 - (w - min) / (max - min)) * (H - 2 * P));
  m.setAttribute("y1", y.toFixed(1)); m.setAttribute("y2", y.toFixed(1));
  m.style.opacity = "1";
  m.classList.toggle("wt-marker-below", below);
}

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
  $("[data-side]").innerHTML = REG.filter((t) => t.group === g).map((t) => `<button class="ev-tile ${t.slug === current ? "is-active" : ""}" data-slug="${esc(t.slug)}"><span class="ev-tile-t">${domainIcon(t.slug, { cls: "dom-ico" })}${esc(t.title)}</span><span class="ev-tile-b">${esc(t.blurb)}</span></button>`).join("");
  document.querySelectorAll(".ev-tile").forEach((b) => b.addEventListener("click", () => select(b.dataset.slug)));
}
async function renderCenter() {
  const t = BYSLUG[current]; if (!t) return;
  const main = $("[data-main]");
  main.querySelector("[data-crumb]").innerHTML = `${esc(DOOR)} / ${esc(t.slug)}`;
  { const _ti = main.querySelector("[data-title]"); _ti.innerHTML = domainIcon(t.slug, { cls: "dom-ico dom-ico-lead" }) + esc(t.title); }
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
  if (push) history.pushState({ slug }, "", `${BASE}${slug}/`);
  document.title = `${BYSLUG[slug].title} — The ${DOORTITLE} — averagejoematt`;
  buildTabs(); buildSide(); renderCenter();
}
window.addEventListener("popstate", (e) => { const slug = (e.state && e.state.slug) || slugFromPath() || (REG[0] && REG[0].slug); current = BYSLUG[slug] ? slug : current; buildTabs(); buildSide(); renderCenter(); });

function wireTheme() { const b = $(".theme-toggle"); if (!b) return; b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} }); }

/* ── First-run orientation — mirrors the Cockpit's PG-02 card ─────────────────
   A dismissible "what am I looking at" card for first-time visitors to the Data
   archive. Shown once (localStorage), non-modal, sits above the instrument — never
   blocks the dense view a repeat reader uses. Injected from JS so the generated
   shells need no rebuild; scoped to the Data door for v1. Renders pre-fetch so it
   appears even when /api/* is unreachable (e.g. local QA). */
const INTRO_KEY = "ajm-data-intro-v1";
function wireFirstRun() {
  if (DOOR !== "data") return;
  let seen;
  try { seen = localStorage.getItem(INTRO_KEY); } catch (e) { seen = "1"; } // private mode → don't nag
  if (seen) return;
  const head = $(".ev-head");
  if (!head) return;

  const intro = document.createElement("aside");
  intro.className = "ev-intro";
  intro.setAttribute("aria-label", "What you're looking at");
  intro.innerHTML = `
    <button class="ev-intro__x" type="button" aria-label="Dismiss orientation">&times;</button>
    <p class="ev-intro__k label">new here?</p>
    <h2 class="ev-intro__h">Every source this one life is measured by.</h2>
    <ul class="ev-intro__list">
      <li><strong>Pick a topic</strong> on the left — grouped into <em>the body</em> and <em>mind &amp; accountability</em>. Its trend loads in the center; no page jumps.</li>
      <li>Labels like <em>N=1</em> or <em>preliminary</em> mean a correlation from a single life, not proof — and thin data is flagged, never faked.</li>
      <li><strong>Read-only.</strong> The numbers are the real ones; nothing here is medical advice.</li>
    </ul>
    <button class="ev-intro__go" type="button">Got it &mdash; show me the data</button>
    <p class="ev-intro__note label">Shown once. It won't interrupt again.</p>`;

  const onKey = (e) => { if (e.key === "Escape") dismiss(); };
  function dismiss() {
    try { localStorage.setItem(INTRO_KEY, "1"); } catch (e) {}
    document.removeEventListener("keydown", onKey);
    intro.remove();
  }
  intro.querySelector(".ev-intro__x").addEventListener("click", dismiss);
  intro.querySelector(".ev-intro__go").addEventListener("click", dismiss);
  document.addEventListener("keydown", onKey);
  head.insertAdjacentElement("afterend", intro);
}

wireTheme();
wireFirstRun();
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
