/*
  evidence_nutrition.js — the nutrition + glucose renderers. Split out of evidence.js
  (#581) — no behavior change.
*/
import { lineChart, barChart, stackedBar, intakeSpine, sufficiencyBars, stackedColumns, mealWindowRibbon, dualLineChart, sparkline, ring } from "/assets/js/charts.js";
import { esc, tryJSON, has, fmt, ttl, fmtShort, fig, figs, sec, empty, note, kvtable } from "/assets/js/evidence_shared.js";
import { genesisCount } from "/assets/js/coach_popover.js"; // P0.1 — the one genesis source of truth

// The §0 verdict (P0.1): mono states the figures, serif judges the trade. Computed
// only from the protein pct + avg_deficit — no fabricated mechanism, just the honest
// read. Every "floor" word here grades the FLOOR pct (170), not the 190 stretch target.
export function nutritionVerdict(n) {
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
export function nutritionHero(n) {
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
export function nutritionProteinLead(n) {
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
export function nutritionLossRate(lr) {
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
export function nutritionProteinAnnotation(n) {
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
export function nutritionProteinFloor(lm, target) {
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
export function nutritionProjection(pj) {
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
export function nutritionReconciliation(rc) {
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
export function cgmEmptyState() {
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
export function nutritionDeficitSustainability(ds) {
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

export async function renderNutrition(d) {
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
  // Staleness honesty (truth audit 2026-07-10): "uploads after the day ends" normalized
  // a 16-day-dead log as routine lag. The API now emits lag_days + a stalled flag (lag
  // vs the macrofactor threshold in source_registry) — when stalled, say it plainly.
  if (n.as_of && n.stalled) {
    parts.push(`<p class="rd-meta label nut-asof nut-stalled">Nutrition logging <strong>stopped ${esc(fmtShort(n.as_of))}</strong> — ${fmt(n.lag_days)} days dark. Everything below reads from that last logged stretch, not the present.</p>`);
  } else if (n.as_of) {
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
    // "It's week one" must be gated on the EXPERIMENT's age, not logged-day count —
    // a stalled log kept this caption alive on day 27 (truth audit 2026-07-10).
    const _dayN = genesisCount().dayN || 0;
    const wk1 = (_dayN > 0 && _dayN <= 14)
      ? `<p class="tv-human nut-anno">It's early days — the early scale drop is mostly water, not fat: sodium and glycogen swings move the number by pounds. Sodium here is the honesty check on that, not a hydration vanity score.</p>`
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

export async function renderGlucose(d) { const [mg, mr] = await Promise.all([tryJSON("/api/meal_glucose"), tryJSON("/api/meal_responses")]); const cur = d && d.glucose; const rows = ((mr && mr.meals) || (mg && mg.meals) || []); const head = figs([cur && cur.avg != null && fig(fmt(cur.avg), "avg mg/dL"), cur && cur.tir != null && fig(cur.tir + "%", "time in range"), (mg && mg.has_cgm != null) && fig(mg.has_cgm ? "yes" : "no", "cgm active")]); const mealSec = rows.length ? sec("Meal glucose response", `<table class="rd-tbl"><thead><tr><th>meal</th><th>peak</th><th>Δ rise</th></tr></thead><tbody>${rows.slice(0, 25).map((m) => `<tr><td class="rd-name">${esc(m.name || m.meal)}</td><td class="num">${fmt(m.peak ?? m.peak_mgdl)}</td><td class="num">${fmt(m.delta ?? m.rise)}</td></tr>`).join("")}</tbody></table>`) : ""; const trendChart = sec("Glucose trend", lineChart(d.glucose_trend || [], { valueKey: "value", label: "Glucose", emptyMsg: "The glucose curve fills once a CGM sensor is active." })); if (!head.includes("fig-v") && !mealSec && !(d.glucose_trend || []).length) return trendChart + empty("No CGM data yet — once a sensor is active, this marries each meal to its glucose response (peak, rise, return-to-baseline)."); return head + trendChart + mealSec + note("Correlative — how specific meals moved glucose. Not diagnostic."); }
