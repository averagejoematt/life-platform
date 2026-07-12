/*
  evidence_vitals.js — the Cockpit/Vitals landing readout (/data/vitals/ — today's pulse,
  the component rings, the small-multiples grid). Split out of evidence.js (#581) — no
  behavior change.
*/
import { sparkline, ring, autonomicHero, autonomicQuadrant, arcTrend, ciWhisker, nDots } from "/assets/js/charts.js";
import { esc, tryJSON, isBad, has, fmt, fig, figs, sec, empty } from "/assets/js/evidence_shared.js";

// Live Pulse — current status narrative + daily vitals trends (the old /live).
// ── /data/vitals/ — the landing page, glance-first, three altitudes. "An instant, honest
// tell at the top; the full documentary as you scroll." `d` = /api/pulse.
// P0.1 — decompose the day into 4 component reads (recovery / HRV / RHR / sleep). Each becomes
// a ring whose fill is the metric's own value or its position in the recent range. tone: ember
// = good, muted = neutral/forming, alert = reserved RED STATE (run-down) — NEVER for direction
// (RHR-down / HRV-up read ember-positive even as the line falls).
export function _vitalsComponents(p, hist) {
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
export function vitalsStatusRead(comps, p, dayNum) {
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
  // #931 pre-start: "0 days in" would read broken — the stamp counts down to Day 1 instead.
  const stamp = (p && p.pre_start && p.days_until_start != null)
    ? `<span class="vs-stamp label">${Number(p.days_until_start)} day${Number(p.days_until_start) === 1 ? "" : "s"} to Day 1 — the baseline starts with the first weigh-in</span>`
    : thin ? `<span class="vs-stamp label">${dayNum} days in — baseline still forming</span>` : "";
  const rings = `<div class="vr-row">${comps.map((c) => ring({ value: c.value, sub: c.sub || "", label: c.label, fill: c.fill, tone: c.tone, thin })).join("")}</div>`;
  return sec("Today's read",
    `<div class="vs-band vs-${tone}"><div class="vs-word"><span class="vs-w">${esc(word)}</span><span class="vs-line">${esc(line)}</span></div>${stamp}</div>` +
    rings +
    `<p class="rd-meta label">The status is the sum of the rings below it — recovery, HRV, resting HR, sleep — not a black-box grade. Each is <strong>last night's</strong> read, setting up today. Ember = good, muted = neutral or still forming${thin && dayNum >= 1 ? "; on day " + dayNum + " of a fresh cut the baseline is thin, so the rings show their state without overclaiming." : "."}</p>`);
}

// P0.2 — now vs 7-day vs 30-day ladder under each ring: "am I above/below my own normal?"
// The 30-day baseline honestly reads "fills in" until 30 days exist. Aligns with the ring grid.
export function vitalsLadder(comps, hist) {
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
      // #1099 — a not-yet baseline renders the honest "—" mark, not a long string that
      // crowds the neighbouring cells; the caption below explains that 30d fills in.
      `<span class="vl-pair"><span class="vl-k label">30d</span><span class="vl-v mono vl-base">${has30 ? esc(fmtv(avg(arr.slice(-30)), c.key)) : "—"}</span></span></div>`;
  }).join("");
  return `<div class="vl-row">${cells}</div>` +
    `<p class="rd-meta label">Each ring read against your <em>own</em> normal — today vs the trailing 7-day average, with a 30-day baseline that fills in as the days accrue (${hist.length} so far). The baseline is the honest "is this a good day for me," not a population chart.</p>`;
}

// P0.3 — earned glyphs: light ember ONLY on a real daily signal (gray-state glyphs render
// unlit — nothing is always-lit/decorative). Habits use "X of N today" (the honest fallback;
// no hourly "by-this-hour" baseline is fabricated) and cross-link to the Habits page.
export function vitalsGlyphs(p, habitsToday) {
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
export function vitalsReadinessDecomposed(comps) {
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
export function vitalsNarrative(p, comps) {
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

// #1091 — cross-phase provenance stamp. VO2max / walking HR / fitness age are raw_timeseries
// metrics (ADR-077): real multi-year records deliberately KEPT across experiment resets. Without
// a label they can read as this-cycle data (pre-start, data that "shouldn't exist yet"), so each
// panel carries a small data-driven stamp keyed off the payload's scope field. Honest context,
// not a warning — nothing is blanked or filtered.
export function scopeStamp(o, opts = {}) {
  if (!o || o.scope !== "multi_year") return "";
  const asOf = opts.asOf !== false && o.as_of ? ` · as of ${esc(o.as_of)}` : "";
  return `<div class="rd-meta label rd-scope" style="margin-bottom:.5rem">multi-year history · not reset with the experiment${asOf}</div>`;
}

// #421 (VIT-03) — VO2max arc. The longevity gold-standard fitness number, a slow-moving arc
// metric beside the daily vitals. Real recorded Garmin estimates only; the date-positioned trend
// shows gaps as gaps. Renders nothing (no placeholder) until real estimates exist.
export function vitalsVo2max(vo) {
  if (!vo || !vo.available) return "";
  const dirWord = vo.trend === "improving" ? "climbing" : vo.trend === "declining" ? "declining" : "holding";
  const deltaLbl = (vo.delta > 0 ? "+" : "") + fmt(vo.delta, 1);
  return sec("VO₂max — the aerobic arc",
    scopeStamp(vo) +
    figs([fig(fmt(vo.current, 1), "now · ml/kg/min"), fig(fmt(vo.peak, 1), "recorded peak"), fig(deltaLbl, "arc-to-date")]) +
    arcTrend(vo.series, { valueKey: "value", unit: " ml/kg/min", label: "VO₂max", height: 180, decimals: 1 }) +
    `<p class="rd-meta label">The estimated maximal oxygen uptake from ${esc(vo.source)} — the single best-studied fitness-longevity number. This is an <strong>arc metric</strong>, not a daily dial: ${vo.n} recorded estimates, ${dirWord} (${esc(deltaLbl)} ml/kg/min across the record). The line is positioned by real date, so the sparse recent cadence reads as honest gaps — a device estimate, not a lab CPET, so read the multi-month direction, not any one reading.</p>`);
}

// #421 (VIT-02, PHY-06) — walking heart rate. A genuine walking-HR capture source: the average
// HR of real Strava `Walk` activities. Not a continuous intraday curve (no such capture exists) —
// a per-walk average trend, honestly labelled. Renders nothing until real walks with HR exist.
export function vitalsWalkingHr(w) {
  if (!w || !w.available) return "";
  const total = w.n_total != null ? w.n_total : w.n;
  return sec("Walking heart rate — what the heart does at a stroll",
    scopeStamp(w) +
    figs([fig(fmt(w.current, 0), "latest walk · bpm"), fig(fmt(w.avg, 0), `${w.n}-walk avg`)]) +
    arcTrend(w.series, { valueKey: "value", unit: " bpm", label: "Walking HR", height: 150, decimals: 0 }) +
    `<p class="rd-meta label">The average heart rate of your ${esc(w.source)} — the daytime, at-a-stroll signal the overnight resting figure misses. Each dot is one walk (${w.n} in the last ${w.window_days} days, ${total} recorded all-time), positioned by real date so quiet stretches read as gaps. It's a per-walk <strong>average</strong>, not a continuous intraday curve — the platform has no continuous-HR capture, so we don't draw one.</p>`);
}

// #421 (VIT-04) — fitness age, a complementary bio-age lens MAPPED from VO2max. Follows the
// Option A privacy pattern (like /api/phenoage): chronological age is never an input or output,
// so no true age is served or derivable. Provider-scrape ages (Garmin/Withings) stay deferred.
export function vitalsFitnessAge(fa) {
  if (!fa || !fa.available) return "";
  return sec("Fitness age — a complementary age lens",
    ciWhisker(fa.estimate, fa.range_low, fa.range_high, { unit: " yrs", label: "Fitness age", caption: `≈ ${fa.estimate} (${fa.range_low}–${fa.range_high}), the age at which your VO₂max is the male-population median. The band is your own recent VO₂max spread — ${fa.n} reading${fa.n === 1 ? "" : "s"}, not a guessed interval.` }) +
    `<div class="rd-meta label" style="margin-top:.4rem">${nDots(fa.n, { unit: "VO₂max readings" })} · basis VO₂max ${fmt(fa.basis_vo2max, 1)} ml/kg/min · as of ${esc(fa.as_of)}${fa.scope === "multi_year" ? `<span class="rd-scope"> · from the multi-year VO₂max record — not reset with the experiment</span>` : ""}</div>` +
    `<p class="rd-meta label">${esc(fa.method)} It's a complementary lens beside PhenoAge, not a replacement — and like every age on this site it follows the privacy line: your <strong>real age is never used or shown</strong>, and no age-gap is derivable. ${esc(fa.citation)}. Vascular age stays deferred — no validated formula in-repo, and the provider-scrape figure is gated on sign-off.</p>`);
}

export async function renderPulse(d) {
  const p = d.pulse || d;
  const [ph, hb, vd] = await Promise.all([tryJSON("/api/pulse_history"), tryJSON("/api/habits"), tryJSON("/api/vitals_depth")]);
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
  // #421 — vitals DEPTH: the slow-moving arc reads (each renders only when its real data exists).
  parts.push(vitalsVo2max(vd && vd.vo2max)); // VIT-03 — VO2max arc
  parts.push(vitalsWalkingHr(vd && vd.walking_hr)); // VIT-02 / PHY-06 — walking heart rate
  parts.push(vitalsFitnessAge(vd && vd.fitness_age)); // VIT-04 — fitness age (Option A privacy)
  parts.push(vitalsBackgroundStrip(p)); // P2.3 — background vitals (honest empty until captured)
  parts.push(vitalsCaptureBacklog(p)); // P3.1–P3.6 — capture + relationships, honestly gated
  parts.push(vitalsHubLinks()); // P2.4 — hub links out to the domain pages
  return parts.join("");
}

// P3.1–P3.6 — new-capture + relationships, honestly gated. Each is a real capability awaiting
// data; none fabricate. P3.6 (cross-metric correlations) STAYS withheld until ≥2 weeks of
// overlap — no coefficient is computed at ~10 days; it'll reuse the sleep correlation-board.
export function vitalsCaptureBacklog(p) {
  const dayNum = p && p.day_number;
  const wks = dayNum != null ? Math.max(0, 14 - dayNum) : null;
  const cards = [
    `<div class="cap-card"><h4 class="cap-h">Blood pressure <span class="cap-tag">needs a cuff</span></h4><p class="rd-meta label">The most valuable missing daily vital for a heavy man mid-cut — and the one that should improve visibly. A morning cuff reading would add a BP trend here. Not captured yet.</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Hourly habit history <span class="cap-tag">upgrades the glyphs</span></h4><p class="rd-meta label">The glyph row shows "X of N today"; with hourly habit-completion history it would become "vs your average by this hour" — a real pace benchmark. Until that exists, the honest X-of-N stands (no faked hourly baseline).</p></div>`,
    `<div class="cap-card"><h4 class="cap-h">Continuous intraday HR <span class="cap-tag">needs capture</span></h4><p class="rd-meta label">Walking heart rate now ships above (per-walk averages from Strava). A <em>continuous</em> intraday curve — heart rate second-by-second through the day — still isn't in the feed; Garmin/Whoop store only summaries and zone-seconds, so we don't draw one.</p></div>`,
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
export function vitalsSmallMultiples(hist) {
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
export function vitalsBackgroundStrip(p) {
  return sec("Background vitals — the quiet anomaly detectors",
    `<div class="nut-coming"><p class="rd-archive">SpO₂, skin temperature, and respiratory rate are background vitals — they should sit silent and only speak up on a deviation (the one place a reserved red would be earned). They're not in the current data feed yet, so rather than draw a fake "all in range" strip, this waits on the capture. <span class="confidence conf-low">needs capture</span></p></div>`);
}

// P2.4 — hub links: the landing page is the front door; each domain links out to its page.
export function vitalsHubLinks() {
  const links = [
    ["recovery & sleep", "/data/sleep/"], ["strain & training", "/data/training/"],
    ["weight & composition", "/data/physical/"], ["nutrition & the deficit", "/data/nutrition/"],
    ["habits", "/data/habits/"], ["bloodwork", "/data/labs/"],
  ];
  return sec("From here — the full documentary",
    `<div class="vh-row">${links.map(([t, h]) => `<a class="vh-link" href="${h}">${esc(t)} →</a>`).join("")}</div>` +
    `<p class="rd-meta label">This is the front door. The glance lives here; each signal opens into its own page for the deep read.</p>`);
}
