/*
  evidence_sleep.js — sleep, the Mind pillar, and vice streaks ("the layer the machine
  can't see"). Split out of evidence.js (#581) — no behavior change.
*/
import { lineChart, stackedBar, correlationChip, dualLineChart, sparkline, targetSpine, stackedDayColumns, dumbbell } from "/assets/js/charts.js";
import { explainMount } from "/assets/js/explain.js";
import { esc, tryJSON, isBad, has, fmt, ttl, fmtShort, lastNightDate, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";

// §0 Forecast hero (P0.1) — the circadian-compliance forecast, PROMOTED to lead. A 0→100
// "tonight's odds" gauge + the four anchors (each with the lever to pull now) + two-voice.
// At-risk reads MUTED ink, never red/alarm (HARD RULE 5). Binds /api/circadian.
export function circadianForecast(circ) {
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
export function sleepCorrelationBoard(cards) {
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

export async function renderSleep(d) {
  const s = d.sleep_detail || {};
  const [circ, nut, corr] = await Promise.all([tryJSON("/api/circadian"), tryJSON("/api/nutrition_overview"), tryJSON("/api/sleep_correlations")]);
  const parts = [];
  // §0 — the forecast LEADS (prospective, not retrospective).
  const fcHero = circadianForecast(circ);
  if (fcHero) parts.push(fcHero);
  // §1 — last night, demoted to EVIDENCE beneath the forecast. The "night of" date
  // is sourced from the LIVE sleep_detail wake date (#487 retired sleep_unified —
  // its date ran 1–2 nights stale, which mislabelled these fresher figures).
  const lastNightHdr = "Last night — the evidence" + (lastNightDate(s) ? ` · the night of ${lastNightDate(s)}` : "");
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
  // #487: the "Unified sleep — sources reconciled" section was RETIRED. sleep_unified's
  // per-field merge read fields that never existed (it was relabeled Whoop + one Eight Sleep
  // score) and ran 1–2 nights stale — a public mislabel with zero compute consumers. The live
  // /api/sleep_detail above carries the same figures, fresher. See ADR-113.
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
export function mindRestraint(vices, timeline) {
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
export function mindInvitingAbsence(m) {
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
export function mindPillarDecomposed(m) {
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
export async function mindThirdWall() {
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

export async function renderMind(d) {
  const m = d.mind || {};
  const vices = d.vice_streaks || [];
  const parts = [];
  parts.push(mindRestraint(vices, d.vice_timeline)); // P0.1 — unnamed, cumulative-first restraint
  parts.push(await mindThirdWall()); // P0.4 — Third Wall centrepiece (the last word, held)
  parts.push(mindInvitingAbsence(m)); // P0.2 — the inviting absence (not a hollow axis)
  parts.push(mindPillarDecomposed(m)); // P0.3 — Mind pillar decomposed to its inputs
  return parts.join("") || empty("The inner-life view fills in as restraint, mood, and reflection accrue.");
}

export function renderVices(d) {
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
