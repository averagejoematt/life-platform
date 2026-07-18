/*
  evidence_body.js — the body domain: supplements, bloodwork, physical (weight cockpit +
  composition arc) and training. Split out of evidence.js (#581) — no behavior change.
*/
import { lineChart, barChart, dualWeight, stackedBar, dualLineChart, sparkline, targetSpine, heatStrip, stackedDayColumns, landmarkBars, weightTrendChart, projectionCone, ciWhisker } from "/assets/js/charts.js";
import { esc, tryJSON, isBad, has, fmt, ttl, fmtShort, todayPT, dayBefore, fig, figs, sec, empty, note, evClass, kvtable } from "/assets/js/evidence_shared.js";
import { dataFigure } from "/assets/js/evidence_datafigure.js";
import { preStart } from "/assets/js/coach_popover.js"; // #978 — the shared pre-start / Day-N cycle signal

export function renderSupplements(d) {
  const g = d.groups || {};
  const allItems = Object.values(g).flatMap((x) => x.items || []);
  // #1116 — the loop station: how many entries state their hypothesis. An honest
  // completeness count, not a claim — unannotated entries simply render nothing.
  const withLoop = allItems.filter((s) => s.hoped_outcome || s.measured_by).length;
  const head = figs([fig(d.total_count ?? allItems.length, "compounds"), allItems.length ? fig(`${withLoop}/${allItems.length}`, "with stated hypotheses") : null, d.as_of_date && fig(d.as_of_date, "as of")]);
  // #978 — cycle-aware framing. Before genesis this catalog is the plan going in, not a
  // progress report; say so, keyed off the same pre-start signal every door uses. Once
  // the experiment starts, preStart() returns null and the frame drops away.
  const pre = preStart();
  const frame = pre
    ? `<p class="supp-frame">The stack Matthew starts ${esc(pre.startDow)} — the plan going in, not a progress report. Nothing's been logged yet; adherence and results fill in once the experiment begins.</p>`
    : "";
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
      // #1116 — the closed loop, first-class on the card face: what we expect
      // (hoped_outcome) and which instrument adjudicates it (measured_by).
      // Honest-empty per ADR-104: an entry without a stated hypothesis renders
      // NOTHING here — no placeholder prose, ever.
      const loop = (s.hoped_outcome && !isBad(s.hoped_outcome)) || (s.measured_by && !isBad(s.measured_by))
        ? `<div class="supp-loop">${s.hoped_outcome && !isBad(s.hoped_outcome) ? `<p class="rd-line supp-hope"><span class="label">hoped outcome</span> ${esc(s.hoped_outcome)}</p>` : ""}${s.measured_by && !isBad(s.measured_by) ? `<p class="rd-line supp-measure"><span class="label">measured by</span> ${esc(s.measured_by)}</p>` : ""}</div>`
        : "";
      return `<article class="supp${paused ? " supp--paused" : ""}"><header class="supp-top"><h3 class="supp-name">${esc(s.name)}</h3>${paused ? `<span class="supp-flag label">paused</span>` : s.timing ? `<span class="supp-timing label">${esc(s.timing)}</span>` : ""}${s.dose ? `<span class="supp-dose num">${esc(s.dose)}</span>` : ""}</header>${paused ? `<p class="supp-paused-note label">${esc(pausedNote)}</p>` : ""}${s.why ? `<p class="supp-why">${esc(s.why)}</p>` : ""}${loop}<div class="supp-ev"><span class="supp-evlabel ${c}">${l}</span><span class="supp-meter"><i class="${c}" style="width:${pct}%"></i></span><span class="supp-evpct num">${s.evPct != null ? s.evPct + "%" : ""}</span></div>${adherence}${more}${snpChips}<p class="supp-meta label">${[s.board && "src: " + esc(s.board), s.cost_monthly != null && "$" + esc(s.cost_monthly) + "/mo", (s.evidence_url || (srcs[0] || {}).url) && `<a class="supp-ev-link" href="${esc(s.evidence_url || (srcs[0] || {}).url)}" target="_blank" rel="noopener">evidence ↗</a>`].filter(Boolean).join("  ·  ")}</p></article>`;
    }).join("");
    return `<section class="rd-sec"><div class="rd-grouphead"><h2 class="rd-h">${esc(grp.name)}</h2>${grp.desc ? `<p class="rd-desc">${esc(grp.desc)}</p>` : ""}</div><div class="supp-grid">${cards}</div></section>`;
  }).join("");
  return head + frame + secs + note("Evidence strength is the published research consensus — not a claim about Matthew.");
}

export function renderLabs(d) { const L = d.labs || d; const bm = L.biomarkers || []; if (!bm.length) return empty("No bloodwork drawn yet — panels appear here as they're added."); const by = {}; for (const b of bm) (by[b.category || "Other"] ||= []).push(b); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><thead><tr><th>biomarker</th><th>value</th><th>reference</th><th>flag</th></tr></thead><tbody>${rows.map((b) => { const f = b.flag && String(b.flag).toLowerCase() !== "null"; return `<tr class="${f ? "rd-flag" : ""}"><td class="rd-name">${esc(b.name)}</td><td class="num">${esc(b.value)}${b.unit ? ` <span class="rd-unit">${esc(b.unit)}</span>` : ""}</td><td class="num rd-range">${esc(b.range || "—")}</td><td>${f ? `<span class="rd-flagmark">${esc(b.flag)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table>`)).join(""); return figs([fig(L.total_draws ?? "—", "draws"), fig(bm.length, "biomarkers"), fig(L.flagged_count ?? 0, "flagged"), L.latest_draw_date && fig(L.latest_draw_date, "latest draw")]) + secs + note("Reference ranges are lab-provided; flags mark out-of-range."); }

// ── /data/physical/ — two tiers: the weight cockpit (daily) + the composition arc
// (episodic). "Weight is the metronome; composition is the arc." `d` = physical_overview.
export const PHYS_GENESIS = "2026-07-18";

// Staleness honesty (truth audit 2026-07-10): present-tense weight copy over a dead
// scale reads false. Mirrors the withings threshold in source_registry (7 days).
export const WEIGHIN_STALE_DAYS = 7;
export function weighinStaleness(j) {
  const lw = String((j && j.last_weighin_date) || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(lw)) return { lw: "", days: null, silent: false };
  const days = Math.round((Date.parse(todayPT()) - Date.parse(lw)) / 86400000);
  return { lw, days, silent: days > WEIGHIN_STALE_DAYS };
}

// P0.1 — trend-weight hero (dual-layer). Faint raw daily dots + a confident ember smoothed
// trend; goal is an annotation NOT an axis anchor (HARD RULE 4); genesis marked; two-voice.
export function physicalTrendHero(readings, j, goal) {
  const now = j.current_weight_lbs, start = j.start_weight_lbs, lost = j.lost_lbs, rate = j.weekly_rate_lbs, prov = j.rate_provisional;
  const chart = weightTrendChart(readings, { goal, genesis: PHYS_GENESIS, label: "Weight · daily scale vs smoothed trend" });
  const down = lost != null && lost > 0;
  // #535: the trend rate carries its 80% CI — the band is the honest part.
  const ciLo = j.weekly_rate_ci_low, ciHi = j.weekly_rate_ci_high;
  // Staleness gate: when the last weigh-in is older than the withings threshold,
  // "now X lb · The scale is moving." is a false present tense — everything reads
  // as-of the last weigh-in and the silence itself becomes the headline.
  const ws = weighinStaleness(j);
  const rateStr = (rate != null && rate !== 0)
    ? `trend ${fmt(rate)} lb/wk${ciLo != null && ciHi != null ? ` (${fmt(ciLo)}…${fmt(ciHi)})` : ""}${ws.silent ? " · from the last logged stretch" : prov ? " · early = water" : ""}`
    : "";
  const machine = [
    ws.silent && `as of ${_physShortDate(ws.lw)}`,
    now != null && (ws.silent ? `${fmt(now)} lb at last weigh-in` : `now ${fmt(now)} lb`),
    lost != null && `${down ? "down" : "up"} ${fmt(Math.abs(lost))} lb from ${fmt(start)}`,
    rateStr,
  ].filter(Boolean).join(" · ");
  const serif = ws.silent
    ? `The scale has been silent for ${ws.days} days — the last weigh-in was ${_physShortDate(ws.lw)}. Everything on this page reads as of that morning, not today; the trend picks back up at the next weigh-in, and the gap itself is part of the record.`
    : rate != null && rate < 0
      ? `The scale is moving. ${prov ? "Most of an early cut is water — this rate will slow, and the line knows it; trust the smoothed trend over any single morning's dot." : "The smoothed trend is the signal; the daily dots are scale noise — water, food, the time of the weigh-in."} Goal ${fmt(goal)} sits off the bottom of this axis on purpose: anchoring to it would flatten the slope you're actually walking.`
      : `Weight is the daily metronome — the thing that moves every morning. The faint dots are the raw scale; the line is the trend underneath the noise.`;
  // #551 — the rate as an honest FORECAST: the point slope with its real block-bootstrap
  // 80% CI drawn as a band. If the band crosses zero the loss isn't statistically nailed
  // down yet — the honest read the bare number hides. Honest fallback: no CI ⇒ point only.
  const rateForecast = (rate != null && rate !== 0)
    ? sec("How fast — the rate, with its honest interval",
        ciWhisker(rate, ciLo, ciHi, {
          unit: " lb/wk", label: "trend slope", confidence: j.projection_confidence ?? 0.8,
          caption: (ws.silent ? `As of ${_physShortDate(ws.lw)} — the scale has been silent ${ws.days} days, so this is the rate of the last logged stretch, not the current pace. ` : "") + ((ciLo != null && ciHi != null)
            ? `The band is the ${Math.round((Number(j.projection_confidence) || 0.8) * 100)}% CI on the trend slope${(Number(ciLo) < 0 && Number(ciHi) > 0) ? " — it crosses zero, so the loss isn't statistically established yet (direction, not verdict)" : ""}. The point is the best estimate; the band is the honesty.`
            : "No interval yet — the slope needs a longer run of weigh-ins before a band is honest. The point alone, for now."),
        }))
    : "";
  return sec("Weight — the daily metronome",
    chart + `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`) + rateForecast;
}

// P0.3 — HappyScale-style stat cluster: High / Latest / Low · Yesterday (day-over-day) ·
// % complete (314.5 → 185 denominator). These REPLACE the DEXA percentages as the page's
// top figures. Ember reads positive on a down day; never red.
export function physicalStatCluster(readings, j, goal) {
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
export const _PHYS_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function _physShortDate(iso) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${_PHYS_MON[+m[2] - 1]} ${+m[3]}` : ""; }

export function physicalMilestoneLadder(readings, j, goal) {
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
  // #949: the heading derives from the same start/goal the ladder body already uses —
  // a hand-coded "315 to 185" strands on the next reset's re-anchored baseline.
  return sec(`Milestone ladder — ${fmt(Math.round(start))} to ${fmt(goal)}, ten pounds at a time`,
    `<div class="ml-ladder">${rows}</div>` +
    `<p class="rd-meta label">Each rung is a 10-lb mark on the way down; it clicks ember the day the trend crosses it, stamped with how long that rung took. The gaps widen as the cut matures — that's the real pace, not a straight line to the goal.</p>`);
}

// P0.5 — rate tempo strip. The pace over 7d / 30d / 90d / since-genesis as ember-intensity
// slope-gauges (not four naked numbers): faster loss = longer, more-saturated ember bar.
// A GAIN window reads muted ink, never red. The 7-day carries the "early = water" flag.
export function _slopePerDay(pts) {
  if (pts.length < 3) return null;
  const t0 = Date.parse(pts[0].d);
  const x = pts.map((p) => (Date.parse(p.d) - t0) / 86400000), y = pts.map((p) => p.w);
  const n = x.length, sx = x.reduce((a, b) => a + b, 0), sy = y.reduce((a, b) => a + b, 0);
  const sxy = x.reduce((a, b, i) => a + b * y[i], 0), sxx = x.reduce((a, b) => a + b * b, 0);
  const denom = n * sxx - sx * sx;
  return denom ? (n * sxy - sx * sy) / denom : null;
}

export function physicalRateTempo(readings, j) {
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
  // Staleness honesty: every window here is anchored to the LAST weigh-in — when the
  // scale has been silent past the withings threshold, say so instead of reading as pace.
  const wst = weighinStaleness(j);
  const staleNote = wst.silent
    ? `<p class="rd-meta label">Weigh-ins ended <strong>${esc(_physShortDate(wst.lw))}</strong> — ${wst.days} days ago. Every window above is measured up to that date; this is the pace of the last logged stretch, not the current one.</p>`
    : "";
  return sec("Rate tempo — the pace across windows",
    `<div class="rt-strip">${rates.map(row).join("")}</div>` + staleNote +
    `<p class="rd-meta label">Each bar is a loss rate; the longer and more saturated, the faster. The 7-day runs hot early because a new cut sheds water — it isn't fat coming off that fast, and it will slow. A gain window would read muted ink, never an alarm.</p>`);
}

// P0.7 — BMI, deliberately de-emphasized. Included because HappyScale-literate readers
// expect it, but small, last in Tier 1, and captioned with its own limitation (near-
// meaningless on a heavy frame rebuilding lean mass). Height from the profile, never a hero.
export function physicalBMI(readings, j) {
  const hIn = Number(j.height_inches);
  // #948: Number(null) is 0 — a nulled pre-start weight must hide the BMI, not compute 0.0.
  const latest = readings.length ? Number(readings[readings.length - 1].weight_lbs) : (j.current_weight_lbs != null ? Number(j.current_weight_lbs) : NaN);
  if (!Number.isFinite(hIn) || hIn <= 0 || latest <= 0 || !Number.isFinite(latest)) return "";
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
export function physicalDexaCountdown(d) {
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
export function _physDexaAgeDays(scanDate) {
  const t = Date.parse(scanDate); if (!Number.isFinite(t)) return null;
  const today = new Date(); return Math.round((Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()) - t) / 86400000);
}

export function physicalDexaBaseline(d) {
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
export function physicalVisceralCallout(d) {
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
export function physicalLeanLongevity(d) {
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
export function physicalPhenoAge(pa) {
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
export function physicalCaptureBacklog(d, pa) {
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
export function physicalFullScanExpander(d) {
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

// #1119 — the two-tier structure made explicit: a labeled group-head for the fluid
// (daily) block and for the checkpoint (slow) block. The cadence chips render from the
// API's measurement metadata (physical_overview.cadences ← source_registry + the DEXA
// recheck interval), never hand-typed here.
export function physicalTierHead(title, desc, chips) {
  const chipHtml = (chips || []).filter(Boolean).map((c) => `<span class="tier-cad label">${esc(c)}</span>`).join("");
  return `<section class="rd-grouphead tier-head"><div class="tier-row"><h2 class="rd-h">${esc(title)}</h2>${chipHtml}</div>${desc ? `<p class="rd-desc">${esc(desc)}</p>` : ""}</section>`;
}

// #1119 — cadence labels from the payload's metadata. Fail-soft for an older cached
// payload without `cadences`: the DEXA interval is derived from the payload's own dates
// (still metadata, not a hand-typed number); anything underivable is simply omitted.
export function physicalCadences(d) {
  const c = (d && d.cadences) || {};
  const lbl = (k) => (c[k] && c[k].label) || null;
  const out = { weight: lbl("weight"), dexa: lbl("dexa"), phenoage: lbl("phenoage"), tape: lbl("tape") };
  if (!out.dexa && d && d.latest_dexa && d.latest_dexa.scan_date && d.next_dexa_recommended) {
    const days = Math.round((Date.parse(d.next_dexa_recommended) - Date.parse(d.latest_dexa.scan_date)) / 86400000);
    if (Number.isFinite(days) && days > 0) out.dexa = `DEXA — re-scanned ~every ${days} days`;
  }
  return out;
}

export async function renderPhysical(d) {
  const [wp, wj, pa] = await Promise.all([tryJSON("/api/weight_progress"), tryJSON("/api/journey"), tryJSON("/api/phenoage")]);
  const readings = (wp && wp.weight_progress) || [];
  const j = (wj && wj.journey) || {};
  const goal = j.goal_weight_lbs ?? 185;
  const cad = physicalCadences(d);
  const parts = [];
  // ── TIER 1 — the weight cockpit (daily) — the fluid block leads the page (#1119) ──
  parts.push(physicalTierHead("The daily signal",
    "The fluid layer — the numbers that move morning to morning. Sparse early in a cycle; it thickens with every weigh-in.",
    [cad.weight]));
  parts.push(physicalTrendHero(readings, j, goal)); // P0.1
  if (j.start_weight_lbs != null && j.current_weight_lbs != null) parts.push(dataFigure(j)); // P0.2 — silhouette scrubber (links to the trend marker)
  parts.push(physicalStatCluster(readings, j, goal)); // P0.3 — stat cluster (replaces DEXA % as top figures)
  parts.push(physicalMilestoneLadder(readings, j, goal)); // P0.4 — milestone ladder (the vertical measuring-rule signature)
  parts.push(physicalRateTempo(readings, j)); // P0.5 — rate tempo strip (ember-intensity slope-gauges)
  // P0.6 — projection cone (widening; rate from the readings, rungs date-marked; the bet, gradeable).
  // Staleness gate: a projection extended from a scale that's been silent past the
  // withings threshold is a forecast off dead data — pause it honestly instead.
  const _wStale = weighinStaleness(j);
  if (readings.length >= 3 && _wStale.silent) {
    parts.push(sec("Projection to 185 — paused",
      `<p class="rd-meta label">No live projection is drawn from a silent scale — the last weigh-in was <strong>${esc(_physShortDate(_wStale.lw))}</strong>, ${_wStale.days} days ago. The cone resumes at the next weigh-in; the pause is part of the honest record, not an error.</p>`));
  } else if (readings.length >= 3) {
    const ws6 = readings.map((r) => ({ d: r.date, w: Number(r.weight_lbs) })).filter((p) => Number.isFinite(p.w));
    const slope = _slopePerDay(ws6.slice(-30));
    const ratePerWeek = slope != null ? Math.round(slope * 7 * 100) / 100 : (j.weekly_rate_lbs ?? null);
    const last6 = ws6[ws6.length - 1];
    const rungList = []; for (let w = Math.floor((last6.w - 5) / 10) * 10; w > goal; w -= 10) rungList.push(w);
    parts.push(sec("Projection to 185 — the cone, not a line",
      projectionCone({ date: last6.d, w: last6.w }, goal, ratePerWeek, {
        provisional: !!j.rate_provisional, rungs: rungList, label: "Projected weight → 185",
        // #551 — the fan edges bind to the REAL block-bootstrap slope CI, and the dated bet
        // to the backend's OWN goal-date range. Honest fallback (no CI) draws the line only.
        rateCiLow: j.weekly_rate_ci_low, rateCiHigh: j.weekly_rate_ci_high,
        goalDateRange: { earliest: j.projected_goal_date_earliest, latest: j.projected_goal_date_latest },
        confidence: j.projection_confidence,
      }) +
      `<p class="rd-meta label">A forecast is a cone, never a line. The band is the real ${j.projection_confidence != null ? Math.round(Number(j.projection_confidence) * 100) + "% " : ""}confidence interval on the loss slope — wide because the rate is young, tightening as weigh-ins accrue. The dated bet is the backend's own goal-date range, held honestly and checked against what actually happens.</p>`));
  }
  parts.push(physicalBMI(readings, j)); // P0.7 — BMI (de-emphasized, last in Tier 1)
  // ── TIER 2 — the composition arc (episodic) — the checkpoint block, grouped and
  // labeled with its actual cadence (#1119) ──
  parts.push(physicalTierHead("The checkpoints",
    "The slow measurements, grouped and dated — they move on scans and blood draws, not mornings. Read them as chapters, not a feed.",
    [cad.dexa, cad.phenoage, cad.tape]));
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
export function liftIndex(benchmarks) {
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

export const _weekKey = (iso) => { const d = new Date(iso + "T00:00:00"); const off = (d.getDay() + 6) % 7; d.setDate(d.getDate() - off); return d.toISOString().slice(0, 10); };

// §0 hero — the session-volume ramp (P0.2): building, with the load watched. WoW % +
// honest "ACWR unlocks ~4 weeks" placeholder; two-voice load-management caution (signed off).
export function trainingVolumeRamp(workouts) {
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
  // Staleness honesty (truth audit 2026-07-10): a 30-day series with no session in
  // over a week isn't "BUILDING" — it's a layoff, and the connective-tissue caution
  // flips to apply to the RESTART, not the ramp.
  const lastDate = String(sess[sess.length - 1].date || "").slice(0, 10);
  const daysSince = /^\d{4}-\d{2}-\d{2}$/.test(lastDate) ? Math.round((Date.parse(todayPT()) - Date.parse(lastDate)) / 86400000) : null;
  const layoff = daysSince != null && daysSince > 7;
  if (layoff) {
    const machineL = [`${sess.length} sessions in the window`, `last session ${_physShortDate(lastDate)}`, `${daysSince} days since`].join(" · ");
    const serifL = `No sessions in ${daysSince} days — the ramp is paused, not building. The connective-tissue caution doesn't disappear on a layoff; it moves to the RESTART: tendons detrain slower than enthusiasm returns, so the first weeks back are the ones to ramp gently, not the chart above.`;
    return sec("The volume ramp — paused, not building",
      chart + `<p class="rd-meta label">Last session ${esc(_physShortDate(lastDate))} — the line above is the last active stretch, not the current week.</p>` +
      `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machineL)}</p><p class="tv-human">${esc(serifL)}</p></div>`);
  }
  const machine = [`${sess.length} sessions`, `${fmt(Math.round(first))} → ${fmt(Math.round(last))} kg`, ratio ? `×${rmult} so far` : null, wow != null ? `WoW ${wow >= 0 ? "+" : ""}${wow}%` : null, "ACWR needs ~4 wks"].filter(Boolean).join(" · ");
  const serif = `Session volume roughly ${rmult}×'d ${weeks.length <= 1 ? "this week" : "over the window"} — ${fmt(Math.round(first))} → ${fmt(Math.round(last))} kg. That's how a foundation gets built, but it's also the kind of jump where connective tissue — which adapts slower than muscle — starts writing cheques the joints have to cash. Nothing here says too much yet; only that the rate is worth watching. The acute:chronic load ratio that would flag it properly needs ~4 weeks of history — until then this is watched, not judged.`;
  const note2 = `<p class="rd-meta label">${weeks.length < 2 ? "Week-over-week fills in next week · " : ""}ACWR (acute:chronic load) unlocks at ~4 weeks.</p>`;
  return sec("The volume ramp — building, with the load watched",
    chart + note2 + `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}

// §0 hero (twin) — RHR decline (P0.3), promoted out of vitals. The inversion: RHR-DOWN is
// the WIN → reads ember-positive (the engine answering), with a multi-factorial caveat in
// mono. Refuses <4 points. Binds pulse_history rhr_bpm.
export function trainingRHRHero(hist) {
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
export function muscleBodyMap(mv) {
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
export function trainingRPE(workouts) {
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
export function trainingSRPE(workouts) {
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

export async function renderTraining(d) { const t = d.training || {}; const [str, wk, wo, ph] = await Promise.all([tryJSON("/api/strength_benchmarks"), tryJSON("/api/weekly_physical_summary"), tryJSON("/api/workouts"), tryJSON("/api/pulse_history")]); const ramp = trainingVolumeRamp((wo && wo.workouts) || []); const rhrHero = trainingRHRHero((ph && ph.pulse_history) || []); const head = figs([fig(t.workouts_30d ?? "—", "workouts · 30d"), fig(t.weekly_avg ?? "—", "weekly avg"), t.z2_pct != null && fig(t.z2_pct + "%", "zone-2 target"), t.strength_sessions_30d != null && fig(t.strength_sessions_30d, "strength · 30d"), d.walking && d.walking.avg_daily_steps != null && fig(fmt(d.walking.avg_daily_steps), "avg daily steps")]); const _cardioHR = (d.cardio_sessions || []).filter((c) => c.avg_hr != null && c.minutes); const hrSec = _cardioHR.length ? sec("HR of the engine — is the easy work staying easy?", barChart(_cardioHR.slice(0, 12).map((c) => ({ label: String(c.sport || "—").slice(0, 8), value: Math.round(Number(c.avg_hr)) })), { valueKey: "value", labelKey: "label", label: "Avg HR per cardio session (bpm)" }) + `<p class="rd-meta label">Easy aerobic work should sit low (≈ under 129 bpm, ~70% of max) — proof the base stays base. Lifting HR isn't shown: Whoop returns 0 HR-zone minutes for lifts, so that's an honest gap an HR strap would fill — never a 0 bar.</p>`) : ""; const z2v = t.z2_weekly_avg_min, z2t = t.z2_target_min || 150, z2cur = t.z2_trailing_7d_min; const z2CurLine = z2cur != null ? `<p class="rd-meta label">This week (trailing 7 days): <strong>${fmt(Math.round(z2cur))} min</strong> vs the ${fmt(z2t)}-min target${z2v != null && z2v >= z2t && z2cur < z2t * 0.5 ? " — the 30-day average above is history carrying a quiet current week, not the present pace" : ""}.</p>` : ""; const z2Sec = z2v != null ? sec("The engine — Zone-2 base", targetSpine(z2v, z2t, { valueLabel: "Z2/wk · 30d avg", targetLabel: "150 target", unit: " min", label: "Zone-2 minutes per week · 30-day average" }) + z2CurLine + `<p class="rd-meta label">Counts steady aerobic work across sources — Strava, Whoop zones, AND Hevy bike/elliptical. The easy work that builds the engine. The spine is a 30-day average — the current week is stated above it, honestly.</p>`) : ""; const lifts = (str && str.benchmarks) || []; const strSec = lifts.length ? sec("The Lift Index — load trend, not max-testing", liftIndex(lifts) + `<p class="rd-meta label">Estimated from working sets (Epley) — a direction, not a 1RM goal. Foundation block: building the engine, not chasing PRs.</p>`) : ""; const days = (wk && wk.days) || []; const wkSec = days.length ? sec("This week — daily movement", `<table class="rd-tbl"><thead><tr><th>day</th><th>steps</th><th>active min</th></tr></thead><tbody>${days.map((x) => `<tr><td class="rd-name">${esc(x.day_of_week || x.date)}</td><td class="num">${fmt(x.steps)}</td><td class="num">${fmt(x.total_active_minutes)}</td></tr>`).join("")}</tbody></table>`) : ""; const rpeSec = trainingRPE((wo && wo.workouts) || []); const srpeSec = trainingSRPE((wo && wo.workouts) || []); const hrStrapSec = sec("Lifting HR zones — coming online", `<div class="nut-coming"><p class="rd-archive">Whoop returns 0 HR-zone minutes for lifting, so the cardiovascular cost of the lifts is a gap. A chest HR strap worn during sessions would fill it — turning "how hard did the lift tax the engine" from blank into data. <span class="confidence conf-low">needs HR strap</span></p></div>`); const ruckSec = sec("Rucking load & incline — coming online", `<div class="nut-coming"><p class="rd-archive">Walking is the primary engine, but it's logged flat — no pack weight or grade. Capturing rucking load / incline would make the walk progressible (same minutes, more stimulus) instead of a fixed floor. <span class="confidence conf-low">needs capture</span></p></div>`); const acwrSec = sec("Load gauge (ACWR) — coming online", `<div class="nut-coming"><p class="rd-archive">The acute:chronic workload ratio — this week's load against the rolling 4-week baseline — is the standard read on whether the ramp is sustainable or tipping into the danger zone. It needs ~3–4 weeks of history before it means anything; computing it at week one would be noise dressed as a verdict. The inputs (session sRPE, volume) are already accruing. <span class="confidence conf-low">unlocks ~4 weeks</span></p></div>`); const _strainDays = ((ph && ph.pulse_history) || []).map((h) => ({ date: h.date, value: Number(h.strain) })).filter((x) => Number.isFinite(x.value) && x.value > 0); const strainSec = _strainDays.length ? sec("Absorbing the work — daily strain", barChart(_strainDays.map((x) => ({ label: fmtShort(x.date).split(" ")[1] || "", value: Math.round(x.value * 10) / 10 })), { valueKey: "value", labelKey: "label", label: "Whoop day strain (0–21)" }) + `<p class="rd-meta label">Day-by-day cardiovascular load, not a single average headline. The strain-vs-recovery overlay fills in (P2.1).</p>`) : ""; const _phRec = ((ph && ph.pulse_history) || []).map((h) => ({ date: h.date, rec: Number(h.recovery_pct), str: Number(h.strain) })); const _recS = _phRec.filter((x) => Number.isFinite(x.rec)).map((x) => ({ date: x.date, value: x.rec })); const _strS = _phRec.filter((x) => Number.isFinite(x.str)).map((x) => ({ date: x.date, value: Math.round(x.str * 100 / 21) })); const overlaySec = (_recS.length >= 4 && _strS.length >= 4) ? sec("Strain vs recovery", dualLineChart(_recS, _strS, { aLabel: "recovery %", bLabel: "strain ·scaled", label: "does the load cost next-day recovery?", showGap: false }) + `<p class="rd-meta label">Recovery % (ember) against day strain scaled to 100 (muted dashed). Observation only — n=1, no coefficient drawn (needs ≥2 weeks).</p>`) : ""; const _sessDates = ((wo && wo.workouts) || []).map((w) => String(w.date || "").slice(0, 10)).filter((x) => /^\d{4}-\d{2}-\d{2}$/.test(x)).sort(); const _lastSess = _sessDates[_sessDates.length - 1]; const _daysSinceSess = _lastSess ? Math.round((Date.parse(todayPT()) - Date.parse(_lastSess)) / 86400000) : null; const _layoffWks = _daysSinceSess != null && _daysSinceSess > 7 ? Math.max(1, Math.floor(_daysSinceSess / 7)) : 0; const _mvFreeze = _layoffWks ? `<p class="rd-meta label">Last trained <strong>${esc(_physShortDate(_lastSess))}</strong> — ${_daysSinceSess} days ago: the current rate is 0 sets/wk for every muscle, ${_layoffWks} week${_layoffWks > 1 ? "s" : ""} running. The bars show the last active window, frozen, not this week's work.</p>` : ""; const _mv = d.muscle_volume || []; const mvSec = _mv.length ? sec("Per-muscle volume vs landmarks", landmarkBars(_mv, { label: "MEV = minimum effective · MAV = optimal range · MRV = max recoverable." }) + _mvFreeze + `<p class="rd-meta label">Weekly working sets per muscle against the volume landmarks (Israetel). Ember = in the optimal MEV–MAV band; muted = under or over. Week-one sets/week are extrapolated from a short window.</p>`) : ""; const bodyMapSec = _mv.length ? muscleBodyMap(_mv) : ""; const _tbp = d.training_blueprint; const blueprintSec = (_tbp && _tbp.public) ? sec("Present vs the proven blueprint", `<p class="rd-meta label">Present training vs the proven loss-period blueprint${_tbp.confidence ? ` · ${esc(_tbp.confidence)} confidence` : ""}. <span class="confidence conf-low">private — blueprint</span></p>`) : ""; const _ppl = { Push: 0, Pull: 0, Legs: 0 }; for (const w of (wo && wo.workouts) || []) { const ti = String(w.title || "").toLowerCase(); const cat = ti.includes("push") ? "Push" : ti.includes("pull") ? "Pull" : (ti.includes("leg") || ti.includes("squat")) ? "Legs" : null; if (!cat) continue; let vol = w.total_volume_kg; if (vol == null) { vol = 0; for (const e of w.exercises || []) for (const s of e.sets || []) vol += (Number(s.reps) || 0) * (Number(s.weight_kg) || 0); } _ppl[cat] += Number(vol) || 0; } const _pplRows = Object.entries(_ppl).filter(([, v]) => v > 0).map(([k, v]) => ({ label: k, value: Math.round(v) })); const pplSec = _pplRows.length ? sec("Push / Pull / Legs balance", barChart(_pplRows, { valueKey: "value", labelKey: "label", label: "Working-set volume by split (kg)" }) + `<p class="rd-meta label">Is one pattern carrying the others? Working-set volume tagged from Hevy session titles.</p>`) : ""; const _mod = (d.daily_modality_minutes_30d || []).map((m) => ({ date: m.date, lift: m.strength_min || 0, cardio: (m.walking_min || 0) + (m.cycling_min || 0) + (m.hiking_min || 0) + (m.soccer_min || 0) + (m.other_min || 0), mob: (m.stretching_min || 0) + (m.breathwork_min || 0) })); const modSec = _mod.some((m) => m.lift + m.cardio + m.mob > 0) ? sec("Training time — where the minutes go", stackedDayColumns(_mod, [{ key: "lift", label: "lift", tone: "lift" }, { key: "cardio", label: "walk/cardio", tone: "cardio" }, { key: "mob", label: "mobility", tone: "mob" }], { label: "minutes by modality · per day" }) + `<p class="rd-meta label">Is the engine work happening, or getting crowded out? Mobility gets its own lane here instead of hiding in the cardio list.</p>`) : ""; const _stepsTrend = (d.walking && d.walking.daily_steps_trend) || []; const wlk = d.walking || {}; const walkSec = _stepsTrend.length ? sec("Walking — the primary engine", figs([wlk.avg_daily_steps != null && fig(fmt(wlk.avg_daily_steps), "avg daily steps"), wlk.total_miles_30d != null && fig(fmt(wlk.total_miles_30d) + " mi", "walked · 30d"), wlk.avg_pace_min_per_mi != null && fig(fmt(wlk.avg_pace_min_per_mi) + "/mi", "avg pace")]) + heatStrip(_stepsTrend, { valueKey: "steps", label: "Daily steps", unit: " steps" })) : ""; const _MOBRE = /stretch|yoga|mobility|foam|recovery|\brest\b/i; const cardio = (d.cardio_sessions || []).filter((w) => w.modality !== "mobility" && !_MOBRE.test(String(w.sport || ""))); const _km = (mi) => (mi != null ? (mi * 1.60934).toFixed(1) : null); const sessSec = cardio.length ? sec("Recent cardio", `<table class="rd-tbl"><thead><tr><th>date</th><th>activity</th><th>distance</th><th>min</th><th>avg HR</th></tr></thead><tbody>${cardio.slice(0, 20).map((w) => `<tr><td class="rd-name">${esc(String(w.date || "").slice(0, 10))}</td><td>${esc(ttl(w.sport || "—"))}</td><td class="num rd-range">${w.distance_mi != null ? `${fmt(w.distance_mi, 1)} mi · ${_km(w.distance_mi)} km` : "—"}</td><td class="num">${fmt(w.minutes)}</td><td class="num">${fmt(w.avg_hr)}</td></tr>`).join("")}</tbody></table>`) : ""; const log = (wo && wo.workouts) || []; const logSec = log.length ? sec("Strength log — per-exercise sets", log.slice(0, 12).map((w) => `<details class="wlog"><summary class="wlog-sum"><span class="wlog-t">${esc(w.title || w.date)}</span><span class="wlog-m label">${[w.date, w.exercise_count != null && Math.round(w.exercise_count) + " exercises", w.total_volume_kg != null && dualWeight(w.total_volume_kg, "kg")].filter(Boolean).map(esc).join("  ·  ")}</span></summary>${(w.exercises || []).map((e) => `<div class="wlog-ex"><p class="wlog-ex-n">${esc(e.name)}</p><table class="rd-tbl"><tbody>${(e.sets || []).map((s, i) => `<tr><td class="rd-name">${esc(s.type && s.type.toLowerCase() !== "normal" ? s.type : "set")} ${i + 1}</td><td class="num">${s.reps != null ? fmt(s.reps) + " reps" : "—"}</td><td class="num rd-range">${s.weight_kg != null ? dualWeight(s.weight_kg, "kg") : (s.distance_m != null ? fmt(s.distance_m) + " m" : "—")}</td></tr>`).join("")}</tbody></table></div>`).join("")}</details>`).join("")) : ""; if (!ramp && !rhrHero && !head.includes("fig-v") && !strSec && !wkSec && !sessSec && !logSec) return empty("No training logged yet — workouts, Zone-2, and strength benchmarks appear here as sessions accrue."); return ramp + rhrHero + head + z2Sec + hrSec + walkSec + strSec + pplSec + mvSec + bodyMapSec + blueprintSec + modSec + strainSec + overlaySec + rpeSec + srpeSec + acwrSec + hrStrapSec + ruckSec + logSec + sessSec + wkSec + note("Correlative — training load vs the body's response. Per-exercise sets from Hevy; per-session strain & zones from Whoop."); }
