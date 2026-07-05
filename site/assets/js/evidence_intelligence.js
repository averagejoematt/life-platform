/*
  evidence_intelligence.js — the self-grading suite: results, post-mortems, the survival
  curve, the visitor mirror, scenario exploration, the wrong-page, and the correlation/
  calibration/prediction/benchmark readouts. Split out of evidence.js (#581) — no behavior
  change.
*/
import { lineChart, dualWeight } from "/assets/js/charts.js";
import { esc, tryJSON, has, fmt, ttl, fmtShort, todayPT, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";
import { dataFigure } from "/assets/js/evidence_datafigure.js";

export async function renderResults(d) { const j = d.journey || d; const wp = await tryJSON("/api/weight_progress"); const chart = sec("Weight trajectory", lineChart((wp && wp.weight_progress) || [], { valueKey: "weight_lbs", goal: j.goal_weight_lbs, unit: " lb", label: "Weight · recent readings", emptyMsg: "Weight trajectory fills as weigh-ins accrue." })); const lost = j.lost_lbs != null ? Number(j.lost_lbs) : null; const wdir = lost == null ? "" : (lost < -0.05 ? "up" : (Math.abs(lost) <= 0.05 ? "even" : "down")); const _wCap = (!j.last_weighin_date || String(j.last_weighin_date).slice(0, 10) === todayPT()) ? "today" : `latest · ${fmtShort(j.last_weighin_date)}`; return dataFigure(j) + chart + figs([lost != null && fig(dualWeight(Math.abs(lost), "lb"), wdir), j.current_weight_lbs != null && fig(dualWeight(j.current_weight_lbs, "lb"), _wCap), j.progress_pct != null && fig(fmt(j.progress_pct) + "%", "to goal"), (j.projected_goal_date_earliest && j.projected_goal_date_latest) ? fig(`${fmtShort(j.projected_goal_date_earliest)}–${fmtShort(j.projected_goal_date_latest)}`, "projected goal (80% range)", null, "ewma_forecast") : (j.projected_goal_date && fig(j.projected_goal_date, "projected goal", null, "ewma_forecast"))]) + `<p class="rd-archive">The headline outcome is weight, but the real results live in the mechanisms — see Experiments for what's confirmed, Bloodwork for what changed inside, and the Story for the arc.</p>` + note("Correlative projection — a range, not a promise."); }

// Post-mortems — what each closed cycle taught, derived live from the record.
export async function renderPostmortems(d) {
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
export function renderSurvival(d) {
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
export function renderMirror(d) {
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

// Scenario explorer (#550) — pick a kind of day, see the distribution of what
// historically FOLLOWED similar days. The anti-causal framing is the feature:
// what followed, never what it causes. All math is precomputed nightly
// (stats_core matching + block-bootstrap CIs); thin cells never arrive — the
// compute's effective-n gate hides them at the source.
export let _scnState = { data: null, pick: null };

export function _scnRow(metric, c) {
  const lo = Math.min(c.p25, c.comparison_mean), hi = Math.max(c.p75, c.comparison_mean);
  const span = (hi - lo) || 1, min = lo - span * 0.3, max = hi + span * 0.3;
  const W = 220, x = (v) => Math.max(0, Math.min(W, ((v - min) / (max - min)) * W));
  const ci = c.diff_ci95
    ? ` · vs other days ${c.diff > 0 ? "+" : ""}${fmt(c.diff)} [95% CI ${fmt(c.diff_ci95[0])}, ${fmt(c.diff_ci95[1])}]${c.ci_excludes_zero ? "" : " — could be nothing"}`
    : "";
  return `<div class="scn-row"><div class="scn-rowhead"><span class="label">${esc(c.label || metric)}</span>` +
    `<span class="scn-med num">${fmt(c.median)}${esc(c.unit || "")}</span>` +
    `<span class="label">median next day · n = ${fmt(c.n)} similar days (effective ${fmt(c.n_eff)})</span></div>` +
    `<svg viewBox="0 0 ${W} 22" class="scn-band" role="img" aria-label="${esc(c.label || metric)}: middle half ${fmt(c.p25)} to ${fmt(c.p75)}">` +
    `<line x1="0" x2="${W}" y1="11" y2="11" class="scn-axis"/>` +
    `<rect x="${x(c.p25).toFixed(1)}" y="6" width="${Math.max(2, x(c.p75) - x(c.p25)).toFixed(1)}" height="10" rx="2" class="scn-iqr"/>` +
    `<line x1="${x(c.median).toFixed(1)}" x2="${x(c.median).toFixed(1)}" y1="3" y2="19" class="scn-medline"/>` +
    `<line x1="${x(c.comparison_mean).toFixed(1)}" x2="${x(c.comparison_mean).toFixed(1)}" y1="6" y2="16" class="scn-base"/>` +
    `</svg><p class="scn-meta label">box = middle half of similar days · thin mark = other days' average (${fmt(c.comparison_mean)}${esc(c.unit || "")})${ci}</p></div>`;
}

export function _scnBody(lever, d) {
  const cells = Object.entries((lever && lever.outcomes) || {});
  const head = figs([fig(lever.n_matched_days, "similar days"), fig(d.window_days || 180, "day window")]);
  if (!cells.length) {
    return head + empty(`Only ${fmt(lever.n_matched_days)} matching days in the window — not enough to show an honest distribution yet.`);
  }
  return head + `<div class="scn-rows">${cells.map(([m, c]) => _scnRow(m, c)).join("")}</div>`;
}

export function renderScenarios(d) {
  if (!d || !d.available || !Array.isArray(d.levers) || !d.levers.length) {
    return empty("The scenario engine hasn't published a run yet — check back tomorrow.");
  }
  _scnState.data = d;
  if (!_scnState.pick || !d.levers.some((l) => l.slug === _scnState.pick)) {
    _scnState.pick = (d.levers.find((l) => Object.keys(l.outcomes || {}).length) || d.levers[0]).slug;
  }
  const chips = d.levers.map((l) =>
    `<button class="scn-chip${l.slug === _scnState.pick ? " is-on" : ""}" data-scn="${esc(l.slug)}">${esc(l.label)}</button>`).join("");
  const lever = d.levers.find((l) => l.slug === _scnState.pick);
  setTimeout(() => {
    document.querySelectorAll(".scn-chip").forEach((btn) => btn.addEventListener("click", () => {
      _scnState.pick = btn.dataset.scn;
      const host = document.querySelector("[data-readout]");
      if (host) host.innerHTML = renderScenarios(_scnState.data);
    }));
  }, 0);
  return `<div class="rd-obs"><p class="dx-kicker label">what tends to follow</p>` +
    `<p class="rd-primary">Pick a kind of day. These are the distributions of what historically <em>followed</em> similar days — what followed, not what it causes.</p></div>` +
    `<div class="scn-chips">${chips}</div>${_scnBody(lever, d)}` +
    note(`Correlative only — “similar days” share one feature, not a life. Cells with an effective n under ${fmt(d.min_effective_n || 8)} are hidden, not padded${d.cells_hidden_thin ? ` (${fmt(d.cells_hidden_thin)} hidden today)` : ""}.`);
}

// The Wrong Page — the AI's misses, uncurated.
export function renderWrong(d) {
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

// Cycle vs cycle — matched first-K-days windows across experiment restarts.
export function renderCycles(d) {
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

// Intelligence — the weekly correlation matrix (Pearson r + BH-FDR), strongest first,
// headed by the engine's live tallies (/api/intelligence_summary: open bets + pairs).
export async function renderCorrelations(d) {
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
  const head = figs([fig(obj.count ?? pairs.length, "pairs", null, "pearson_r"), sig ? fig(sig, "FDR-significant", null, "bh_fdr") : "", hypCount ? fig(hypCount, "open bets") : "", obj.week && fig(obj.week, "week")]);
  const pTxt = (p) => (p.p === 0 ? "&lt;0.001" : p.p == null ? "—" : fmt(p.p, 3));
  const rows = tabled.slice(0, 30).map((p) => `<tr class="${p.fdr_significant ? "rd-flag" : ""}"><td class="rd-name">${esc(p.label_a || p.metric_a)} <span class="rd-unit">↔</span> ${esc(p.label_b || p.metric_b)}</td><td class="num">${fmt(p.r, 2)}</td><td class="num rd-range">${pTxt(p)}</td><td class="num">${fmt(p.n)}</td><td>${p.fdr_significant ? `<span class="rd-flagmark">FDR ✓</span>` : esc(p.strength || "")}</td></tr>`).join("");
  const floorNote = belowFloor ? `<p class="rd-desc">${belowFloor} more pair${belowFloor === 1 ? "" : "s"} had fewer than 5 overlapping days this week — below the floor for claiming a pattern, so they aren't tabled.</p>` : "";
  const tbl = sec("Correlation matrix — strongest first", `<table class="rd-tbl"><thead><tr><th>pair</th><th>r</th><th>p</th><th>n</th><th>significance</th></tr></thead><tbody>${rows}</tbody></table>${floorNote}`);
  return head + betsLine + tbl + (obj.methodology ? `<p class="rd-desc">${esc(obj.methodology)}</p>` : "") + note("Correlative only — Pearson r with Benjamini-Hochberg FDR control across all pairs. Never causal. p-values below 0.001 display as &lt;0.001.");
}

// Predictions — the coaches' forward calls, scored against measured outcomes.
// Calibration scoreboard (#538) — every forecast graded against reality. Platform +
// per-coach Brier, the reliability curve (stated confidence vs. what came true), and
// the hypothesis engine's own ledger. The honesty moat, made legible.
export function renderCalibration(d) {
  const p = (d && d.platform) || {};
  const coaches = (d && d.coaches) || [];
  const hyp = (d && d.hypotheses) || {};
  if (!(p.n > 0))
    return empty("No graded forecasts yet — the calibration ledger restarts at each genesis. Coaches log forward predictions with a stated confidence; a deterministic evaluator scores each against measured outcomes as its target date passes. Brier scores and the reliability curve fill in as the first calls come due — the platform grading its own predictions, in public.");
  const cal = String(p.calibration || "").replace(/_/g, " ");
  const head = figs([
    fig(p.n, "graded forecasts", null, "calibration_score_pairs"),
    p.brier != null && fig(fmt(p.brier), "platform Brier", null, "brier_score"),
    p.brier_skill != null && fig(fmt(p.brier_skill), "skill vs base-rate", null, "brier_skill_score"),
    p.accuracy_pct != null && fig(fmt(p.accuracy_pct) + "%", "hit rate", null, "calibration_score_pairs"),
    p.calibration && p.calibration !== "insufficient_data" && fig(ttl(cal), "calibration", null, "calibration_verdict"),
  ]);
  const bins = p.reliability_bins || [];
  const relRows = bins
    .map(
      (b) =>
        `<tr><td class="rd-name">${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%</td><td class="num">${b.n}</td><td class="num">${Math.round(b.mean_confidence * 100)}%</td><td class="num rd-range">${Math.round(b.observed_rate * 100)}%</td></tr>`,
    )
    .join("");
  const relTbl = bins.length
    ? sec(
        "Reliability curve — stated confidence vs. what actually happened",
        `<table class="rd-tbl"><thead><tr><th>confidence band</th><th>n</th><th>said</th><th>came true</th></tr></thead><tbody>${relRows}</tbody></table>`,
      )
    : "";
  const cRows = coaches
    .map(
      (c) =>
        `<tr><td class="rd-name">${esc(c.coach_name || c.coach_id)}</td><td class="num">${c.n}</td><td class="num">${c.brier != null ? fmt(c.brier) : "—"}</td><td class="num rd-range">${c.accuracy_pct != null ? fmt(c.accuracy_pct) + "%" : "—"}</td><td>${c.calibration && c.calibration !== "insufficient_data" ? esc(ttl(String(c.calibration).replace(/_/g, " "))) : "—"}</td></tr>`,
    )
    .join("");
  const board = sec(
    "The scoreboard — by coach",
    `<table class="rd-tbl"><thead><tr><th>coach</th><th>graded</th><th>Brier</th><th>hit rate</th><th>calibration</th></tr></thead><tbody>${cRows}</tbody></table>`,
  );
  const hypLine = hyp && hyp.n > 0 ? note(`Hypothesis engine: ${hyp.n} resolved, Brier ${fmt(hyp.brier)}${hyp.calibration && hyp.calibration !== "insufficient_data" ? " (" + ttl(String(hyp.calibration).replace(/_/g, " ")) + ")" : ""}.`) : "";
  return head + relTbl + board + hypLine + note(d.disclosure || "Self-graded against the platform's own data — Brier 0 is perfect, 0.25 is the always-say-50% baseline, lower is better.");
}

export function renderPredictions(d) {
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
export function renderBenchmarks(d) {
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
