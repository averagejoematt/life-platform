/*
  evidence_character.js — the character sheet (/data/character/): the seven-pillar hero,
  stat block, mechanics layer, record and time-travel wiring. Split out of evidence.js
  (#581) — no behavior change.
*/
import { sparkline, ring, pillarRing, pillarRingCpts, radarChart } from "/assets/js/charts.js";
import { badgeMark, tierEmblem } from "/assets/js/sigils.js";
import { domainIcon } from "/assets/js/icons.js";
import { esc, tryJSON, has, fmt, ttl, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";
import { preStart } from "/assets/js/coach_popover.js"; // #931 — the pre-start countdown state
import { dfBody } from "/assets/js/evidence_datafigure.js";
// #420: one share affordance — the character sheet's own linkable moment travels.
import { shareMount } from "/assets/js/share.js";

export const CH_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"];

// #1126: one category vocabulary for every badge surface (the sheet's Unlocks
// wall + the dedicated /data/badges/ page) — shared so the two can't drift.
export const BADGE_CAT_TTL = { streak: "Streaks", level: "Level milestones", milestone: "Milestones", data: "Data consistency", challenge: "Challenges", science: "Science" };

export const CH_ABBR = { sleep: "SLP", movement: "MOV", nutrition: "NUT", metabolic: "MET", mind: "MIN", relationships: "REL", consistency: "CON" };

export const CH_FLAVOR = {
  Foundation: "Laying the base: the habits and the floor.",
  Momentum: "The base holds and starts compounding.",
  Discipline: "Consistency under load, not just on good weeks.",
  Mastery: "The system runs itself most days.",
  Elite: "The far end of what an N=1 can reach.",
};

export const chDelta = (v, unit = "") => {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return `<span class="ch-d ch-d0">0${unit}</span>`;
  return n > 0 ? `<span class="ch-d ch-dup">+${fmt(n)}${unit}</span>` : `<span class="ch-d ch-ddn">−${fmt(Math.abs(n))}${unit}</span>`;
};

/* #913 · the deterministic mood — engine-computed on the daily record
   (thriving/steady/fading/dormant). Records computed before v1.3.0 carry no
   mood, so /api/presence is the honest fallback: dark → dormant, any lull →
   fading. Never derived from prose, always from the presence instrument. */
export const CH_MOODS = ["thriving", "steady", "fading", "dormant"];
export const chMood = (ch, pres) => {
  const m = ch && ch.character_mood;
  if (CH_MOODS.includes(m)) return m;
  if (pres && pres.available) {
    if (pres.presence_class === "dark") return "dormant";
    if (pres.in_lull) return "fading";
  }
  return "steady";
};

// Shared context for wireCharacter's time-travel re-render (P1.3): the hero +
// stat block rebuild for a scrubbed date; the slow-moving sections stand.
export let _chCtx = null;

/* 1 · Hero — the figure, leveled. Silhouette girth = the real weight; ring
   segments = the seven pillar scores; the emblem = tier + level. If the
   journey isn't available the composite number holds the center instead.
   A builder (not inline) so time travel can redraw it for any date. */

export function chHeroHtml(ch, pillars, jj, wave, mood) {
  const tier = String(ch.tier || "Foundation");
  const level = Math.round(Number(ch.level) || 1);
  const composite = Number(ch.composite_score);
  const RING = 360;
  /* #913 · neglect states: the hero carries data-state, and during a lull the
     arcs of pillars that are decaying / whose behaviors aren't happening dim —
     the figure literally fades where the life went quiet. */
  const state = CH_MOODS.includes(mood) ? mood : (CH_MOODS.includes(ch.character_mood) ? ch.character_mood : "steady");
  const lull = state === "fading" || state === "dormant";
  const ringPillars = lull
    ? pillars.map((p) => (((p.neglect_decay && p.neglect_decay.applied) || (p.absent_behaviors || []).length) ? Object.assign({}, p, { dim: true }) : p))
    : pillars;
  let center;
  // #948: explicit null checks — Number(null) is 0 (finite), which would draw a
  // goal-weight silhouette while /api/journey suppresses the pre-start weight.
  if (jj && jj.start_weight_lbs != null && jj.current_weight_lbs != null && isFinite(Number(jj.start_weight_lbs)) && isFinite(Number(jj.current_weight_lbs)) && Number(jj.start_weight_lbs) !== Number(jj.goal_weight_lbs)) {
    const g = Math.max(0, Math.min(1, (Number(jj.current_weight_lbs) - Number(jj.goal_weight_lbs)) / (Number(jj.start_weight_lbs) - Number(jj.goal_weight_lbs))));
    center = `<svg x="118" y="76" width="124" height="208" viewBox="0 0 300 620" aria-hidden="true">` +
      `<circle class="ch-body" cx="150" cy="64" r="${(29 + 6 * g).toFixed(1)}"></circle>` +
      `<path class="ch-body" d="${dfBody(g)}"></path></svg>`;
  } else {
    center = `<text class="ch-center num" x="180" y="192" text-anchor="middle">${Number.isFinite(composite) ? Math.round(composite) : "—"}</text>`;
  }
  const legend = pillars.map((p) => `<span class="ch-leg"><i class="ch-dot" style="background:var(--pillar-${esc(p.name)},var(--ember))"></i>${esc(CH_ABBR[p.name] || p.name)}</span>`).join("");
  const tt = ch.time_travel ? `<span class="ch-ttflag">time travel</span> · ` : "";
  /* #913 · the state, said plainly under the class line — and no celebratory
     share copy while the sheet is in a lull (the level was earned earlier;
     framing it as a win next to a dark stretch would be a lie of emphasis). */
  const moodLine = state === "dormant"
    ? `<p class="ch-mood label">dormant — manual logging has gone dark; the levels below are decaying, not paused</p>`
    : state === "fading"
      ? `<p class="ch-mood label">fading — a quiet stretch is pulling the sheet down</p>`
      : "";
  const shareText = lull
    ? `Level ${level} ${tier} — the character sheet during a quiet stretch: absent behaviors score zero and the levels atrophy. Honest, not flattering`
    : `Level ${level} ${tier} — my life as an RPG character sheet, scored nightly from real data`;
  return `<section class="rd-sec ch-hero" data-tier="${esc(tier.toLowerCase())}" data-state="${esc(state)}">
    <div class="ch-stage">
      <div class="ch-figwrap">
        <svg class="ch-ringsvg" viewBox="0 0 ${RING} ${RING}" role="img" aria-label="The seven pillar ring around the body silhouette — each arc fills with its pillar's score" data-cpts="${esc(JSON.stringify(pillarRingCpts(ringPillars, { size: RING })))}" data-cpts-hit="xy">${pillarRing(ringPillars, { size: RING })}${center}</svg>
        <div class="ch-legend label">${legend}</div>
      </div>
      <div class="ch-id">
        <div class="ch-emblem">${tierEmblem(tier, level)}</div>
        <p class="ch-class label">${tt}${esc(tier)} · Level ${level} of 100${ch.as_of_date ? ` · as of ${esc(String(ch.as_of_date))}` : ""}</p>
        ${moodLine}
        <p class="ch-idnote">One character, seven pillars — scored nightly from the same data every other page reads. The silhouette is the real weight; the ring is today's pillar scores; the emblem evolves with the tier.</p>
        ${figs([
          Number.isFinite(composite) && fig(fmt(composite), "composite", ch.composite_delta_1d != null ? `${Number(ch.composite_delta_1d) >= 0 ? "+" : ""}${fmt(ch.composite_delta_1d)} d/d` : ""),
          ch.xp_total != null && fig(fmt(ch.xp_total), "xp"),
          Number(ch.xp_debt) > 0 && fig(`−${fmt(ch.xp_debt)}`, "xp debt"),
          // #931: day 0 is pre-start, not a day of the experiment — the fig waits for Day 1.
          !ch.time_travel && Number(wave && wave.day_n) >= 1 && fig(`day ${wave.day_n}`, "of the experiment"),
        ])}
        <p class="ch-share">${shareMount("/data/character/", shareText)}</p>
      </div>
    </div>
  </section>`;
}

/* 2 · The seven pillars — RPG stat block + radar. Also a builder (time travel). */
/* ADR-104: each pillar carries its own honest "why" — engine-computed provenance
   (coverage holds, behaviors that didn't happen, what's dragging), never narrated. */

export function chWhy(p) {
  const drv = p.drivers || {};
  const names = (a) => (a || []).map((n) => ttl(n)).join(", ");
  // #747: engine-computed and deterministic (ADR-105) — checked first because a
  // not-instrumented pillar is also, incidentally, coverage_hold (0% coverage
  // is below any leveling threshold). "Not yet instrumented" is the honest
  // reason; "levels frozen" would undersell it as a temporary data gap.
  if (p.not_instrumented) {
    return p.not_instrumented_note || "Not yet instrumented — no data source feeds this pillar yet.";
  }
  if (p.coverage_hold) {
    const cov = p.data_coverage != null ? `${Math.round(Number(p.data_coverage) * 100)}%` : "too little";
    return `Levels frozen — only ${cov} of this pillar's data exists right now. The engine won't judge on gaps: no data can't climb, and no data can't crash.`;
  }
  const bits = [];
  // #913: atrophy is a state, not a footnote — name it first, with the gap.
  if (p.neglect_decay && p.neglect_decay.applied) {
    const gap = Math.round(Number(p.neglect_decay.gap_days) || 0);
    bits.push(`atrophy: ${gap} dark days are decaying this level score — real detraining and evidence loss, floored at what today measured`);
  }
  if (drv.absent && drv.absent.length) bits.push(`not happening: ${names(drv.absent)} (scores 0 while absent)`);
  if (drv.dragging && drv.dragging.length) bits.push(`dragging: ${names(drv.dragging)}`);
  if (drv.top && drv.top.length) bits.push(`carried by: ${names(drv.top)}`);
  if (!bits.length) return "";
  return bits.join(" · ");
}

export function chStatHtml(pillars, hist) {
  const rows = pillars.map((p) => {
    const scoreVals = hist.map((w) => ({ v: (w.pillars && w.pillars[p.name]) || 0, d: w.week_end })).slice(-8);
    const spark = scoreVals.filter((s) => s.v > 0).length >= 2 ? sparkline(scoreVals, { height: 26 }) : "";
    const raw = Math.max(0, Math.min(Number(p.raw_score) || 0, 100));
    const why = chWhy(p);
    // #747: a pillar with zero real inputs renders a labeled state instead of
    // the placeholder neutral score — data-driven off the engine's own flag,
    // so this clears itself automatically the day a component gets real data.
    const notInstrumented = !!p.not_instrumented;
    // #913: the atrophy chip — same badge grammar as `held`, muted ember, so a
    // decaying pillar is visibly different from a frozen or healthy one.
    const atrophy = !notInstrumented && p.neglect_decay && p.neglect_decay.applied
      ? `<span class="ch-hold ch-atrophy" title="a sustained quiet stretch is decaying this pillar's level score — floored at what the day itself measured">atrophy</span>`
      : "";
    const lvBadge = (notInstrumented
      ? `<span class="ch-hold" title="not yet instrumented — no data source feeds this pillar">n/a</span>`
      : (p.coverage_hold ? `<span class="ch-hold" title="levels frozen — not enough data to judge">held</span>` : "")) + atrophy;
    const bar = notInstrumented
      ? `<i class="ch-rbar-none"></i>`
      : `<i style="width:${raw}%;background:var(--pillar-${esc(p.name)},var(--ember))"></i>`;
    const rawCell = notInstrumented
      ? `<span class="ch-rraw label" title="not yet instrumented">—</span>`
      : `<span class="ch-rraw num">${fmt(raw)}<small>/100</small></span>`;
    // #913: a pillar in debt shows the hole, not a mute 0 — the bleed is the point.
    const xpCell = notInstrumented
      ? `<span class="ch-d ch-d0">—</span>`
      : (Number(p.xp_debt) > 0
        ? `<span class="ch-d ch-ddn" title="XP owed below zero — good days pay this down before XP grows again">−${fmt(p.xp_debt)} owed</span>`
        : chDelta(p.xp_delta, " xp"));
    return `<div class="ch-row">
      <span class="ch-ric" style="color:var(--pillar-${esc(p.name)},var(--ember))">${domainIcon(p.name)}</span>
      <span class="ch-rname">${esc(ttl(p.name))}</span>
      <span class="ch-rlv label">Lv ${Math.round(Number(p.level) || 1)}${lvBadge}</span>
      <span class="ch-rbar">${bar}<b style="left:25%"></b><b style="left:50%"></b><b style="left:75%"></b></span>
      ${rawCell}
      ${xpCell}
      ${spark ? `<span class="ch-rspark">${spark}</span>` : ""}
    </div>${why ? `<p class="ch-rwhy">${esc(why)}</p>` : ""}`;
  }).join("");
  const radar = radarChart(pillars.map((p) => ({ key: p.name, label: CH_ABBR[p.name] || p.name, value: p.raw_score })));
  return sec("The seven pillars", `<div class="ch-statgrid"><div class="ch-rows">${rows}</div>${radar}</div>
    <p class="rd-why">Each pillar scores 0–100 nightly from its own real data (wearables, the food log, habits, labs), then an EMA smooths it and a streak gate decides level moves — one great day can't swing a level, and a level-up also needs the day itself to have been lived at that level. Behaviors that didn't happen score zero; a missing sensor reading doesn't. XP is the daily currency: strong days earn it, weak days bleed it.</p>`);
}

export async function renderCharacter(d) {
  const ch = (d && d.character) || {};
  const pillars = ((d && d.pillars) || []).slice().sort((a, b) => CH_ORDER.indexOf(a.name) - CH_ORDER.indexOf(b.name));
  if (!pillars.length) {
    // #931 pre-start: no sheet yet is the EXPECTED state — say when the record begins.
    const pre0 = preStart();
    return empty(pre0
      ? `A fresh cycle at Level 1 — the record begins Day 1, ${pre0.startLabel}. The first character sheet computes after the first night of data.`
      : "The character sheet computes nightly — it fills in as the first days of data land.");
  }
  const [stats, wave, j, cfgRaw, ach, pres, calib] = await Promise.all([
    tryJSON("/data/character_stats.json"), tryJSON("/api/journey_waveform"), tryJSON("/api/journey"),
    tryJSON("/api/character_config"), tryJSON("/api/achievements"), tryJSON("/api/presence"),
    tryJSON("/api/character_calibration"),
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

  /* #931 pre-start: launch eve reads as ANTICIPATION — never dormant/atrophy
     (that grammar is for a life gone quiet mid-cycle, not one that hasn't
     started). Payload-first off the journey block; client GENESIS fallback. */
  const pre = preStart(jj);

  /* #913 · the deterministic mood drives the hero's visual state, the share
     copy, and the celebration gating below. */
  const mood = pre ? "steady" : chMood(ch, pres);
  const lullNow = !pre && !!(pres && pres.available && pres.in_lull && Number(pres.gap_days) >= 2);

  const hero = chHeroHtml(ch, pillars, jj, wave, mood);
  /* ADR-104/#913: the quiet stretch as a structural state banner — same calm
     voice, muted ember (never alarm-red), but persistent and specific: the
     gap-day counter plus exactly which pillars are decaying right now.
     #931: pre-start the same slot carries the countdown instead — the record
     begins Day 1, and nothing below is dormant, just unwritten. */
  const decaying = pillars.filter((p) => (p.neglect_decay && p.neglect_decay.applied) || (p.absent_behaviors || []).length);
  const graceDays = Number(cfg && cfg.leveling && cfg.leveling.neglect_decay && cfg.leveling.neglect_decay.n_grace_days) || 3;
  const quiet = pre
    ? `<section class="rd-sec ch-state" data-mood="steady" aria-label="Pre-start state">
        <p class="ch-state-line"><strong class="num">${esc(String(pre.daysUntil))}</strong><span class="label"> day${pre.daysUntil === 1 ? "" : "s"} until Day 1 — the experiment begins ${esc(pre.startLabel)}</span></p>
        <p class="ch-state-detail">A fresh cycle at Level 1: nothing carried over, nothing pre-earned. Every level below gets earned from the first night of data, and the first baseline is that morning's weigh-in. The record begins Day 1.</p>
      </section>`
    : lullNow
      ? `<section class="rd-sec ch-state" data-mood="${esc(mood)}" aria-label="Quiet-stretch state">
        <p class="ch-state-line"><strong class="num">${esc(String(Math.round(Number(pres.gap_days))))}</strong><span class="label"> days since a manual log</span>${pres.passive_still_flowing ? `<span class="label"> · the wearables keep flowing</span>` : ""}</p>
        ${decaying.length ? `<p class="ch-state-detail">Decaying while the logging is dark: ${decaying.map((p) => `<strong style="color:var(--pillar-${esc(p.name)},var(--ember))">${esc(ttl(p.name))}</strong>`).join(", ")}.</p>` : ""}
        <p class="ch-state-detail">The sheet doesn't look away: behaviors that aren't happening score zero, XP bleeds into visible debt, and after ${esc(String(graceDays))} dark days the levels themselves atrophy — modeling real detraining and evidence loss, not punishment. The levels below are what the data actually earns.</p>
      </section>`
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

  /* 2b · Felt-reality calibration (#1409) — the sheet grades itself against how
     the week actually felt. Weekly Sunday probe (3 one-tap items) vs each probed
     pillar's 7-day mean level score: pearson r + Fisher CI on n_eff, computed
     deterministically server-side. Aggregates only; the confidence grammar is
     honest — below the arming floor there is NO r (uncalibrated, with the real
     trigger), between floors r is a point estimate with NO band (ADR-105). */
  let calCard = "";
  if (calib && Array.isArray(calib.pillars)) {
    const probed = calib.pillars.filter((c) => c.state !== "unprobed");
    const calibrated = probed.filter((c) => c.state === "calibrated");
    const minW = (probed[0] && probed[0].gates && probed[0].gates.min_weeks) || 5;
    const provLine = calibrated.length
      ? `Calibrated against felt reality: ` + calibrated.map((c) =>
          `<strong style="color:var(--pillar-${esc(c.pillar)},var(--ember))">${esc(ttl(c.pillar))}</strong> r=<strong class="num">${fmt(c.r)}</strong> (n_eff ${fmt(c.n_eff)})`).join(" · ")
      : `Uncalibrated — <strong class="num">${esc(String((probed[0] && probed[0].n_weeks) || 0))}</strong> of ${esc(String(minW))} probe weeks banked. The card earns its r honestly, one Sunday at a time.`;
    const rows = calib.pillars.map((c) => {
      const name = `<span class="ch-cal-p" style="color:var(--pillar-${esc(c.pillar)},var(--ember))">${esc(ttl(c.pillar))}</span>`;
      if (c.state === "unprobed") return `<div class="ch-cal-row is-unprobed">${name}<span class="label">unprobed — no felt-reality instrument maps here yet</span></div>`;
      if (c.state !== "calibrated") return `<div class="ch-cal-row is-uncal">${name}<span class="label">uncalibrated (n=${esc(String(c.n_weeks))}) — arms at ${esc(String((c.gates && c.gates.min_weeks) || minW))} probe weeks</span></div>`;
      const band = c.ci95 ? ` · 95% CI [${fmt(c.ci95[0])}, ${fmt(c.ci95[1])}]` : ` · point estimate (band arms at ${esc(String((c.gates && c.gates.ci_min_weeks) || 8))} weeks)`;
      return `<div class="ch-cal-row is-cal">${name}<span class="num">r=${fmt(c.r)}</span><span class="label"> · n_eff ${fmt(c.n_eff)} of ${esc(String(c.n_weeks))}${band}</span></div>`;
    }).join("");
    calCard = sec("Calibration — does it match how it feels?", `
      <p class="rd-prose" data-cal-prov>${provLine}</p>
      <div class="ch-cal" id="calibration">${rows}</div>
      <p class="rd-why">Every Sunday evening, three one-tap questions — how alive, how rested, how connected the week actually felt (0–4, ≤20 seconds). Each answer is paired with that pillar's mean level over the same seven days, and the correlation above is the sheet grading itself: a level that climbs while the felt scores don't will show up here as a falling r. Skipped Sundays are coverage gaps — n simply doesn't accrue; nothing is zero-filled (${esc(String(calib.probe_weeks_covered || 0))} probe week${(calib.probe_weeks_covered || 0) === 1 ? "" : "s"} banked so far).</p>
      <p class="rd-archive">${esc(calib.method || "")}</p>`);
  }

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
    /* #913 · the bleed, visible: pillars sitting below the 0-floor used to
       render an indistinguishable 0 — now the debt line names the hole. */
    const debtors = pillars.filter((p) => Number(p.xp_debt) > 0);
    const debtLine = (Number(ch.xp_debt) > 0 || debtors.length)
      ? `<p class="rd-why ch-xpdebt">XP debt: <strong class="num">−${fmt(Number(ch.xp_debt) || debtors.reduce((a, p) => a + Number(p.xp_debt), 0))}</strong>${debtors.length ? ` (${debtors.map((p) => `${esc(ttl(p.name))} −${fmt(p.xp_debt)}`).join(" · ")})` : ""} — weak days used to vanish silently at the 0-floor; now they dig a visible hole that good days must repay before XP grows again.</p>`
      : "";
    const economy = sec("The XP economy", `<div class="ch-bands">${bandRows}</div>
      <p class="rd-why">Each pillar's nightly score lands in a band and earns (or loses) that XP — today's pillars are placed where they scored. Against it runs the decay: <strong>−${fmt(lv.daily_xp_decay)} XP every day</strong>, no exceptions. The game is simple and honest: you can't bank a good week and coast.</p>${debtLine}`);

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

  /* 4 · The record — level events, the weekly heatmap, the daily waveform.
     #913: a level-DOWN renders distinctly (muted, marked), and during a lull
     no "up" entry gets celebratory framing — ups dated inside the dark window
     are recorded-not-celebrated (they're pre-fix artifacts or EMA momentum);
     ups from before it are labeled as earned back then. Never a tier-up party
     next to the quiet-stretch banner. */
  const tl = (stats && stats.timeline) || [];
  const lullStart = lullNow ? String(pres.last_log_date || "") : "";
  const tlHtml = tl.length
    ? `<ul class="ch-tl">${tl.slice(-14).reverse().map((e) => {
      const ty = String(e.type || "");
      const isDown = ty.includes("down") || / tier down/.test(String(e.event || ""));
      const isUp = !isDown && (ty.includes("up") || e.type == null);
      const d = String(e.date || "").slice(0, 10);
      let cls = isDown ? " ch-tl-down" : "";
      let annot = "";
      if (isUp && lullNow) {
        if (lullStart && d > lullStart) { cls += " ch-tl-muted"; annot = ` <span class="label">· during the quiet stretch — recorded, not celebrated</span>`; }
        else annot = ` <span class="label">· earned before the quiet stretch</span>`;
      }
      return `<li class="ch-tl-li${cls}"><span class="label">${esc(d)}</span><span class="ch-tl-ev">${isDown ? `<span class="ch-tl-dn label" aria-hidden="true">▾</span> ` : ""}${esc(e.event || "")}${annot}</span>${e.character_level != null ? `<span class="ch-tl-lv label">Lv ${esc(String(Math.round(e.character_level)))}</span>` : ""}</li>`;
    }).join("")}</ul>`
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
    const cats = [...new Set(achList.map((b) => b.category || "other"))];
    const groups = cats.map((c) => {
      const items = achList.filter((b) => (b.category || "other") === c);
      return `<div class="ch-bgroup"><p class="label">${esc(BADGE_CAT_TTL[c] || ttl(c))}</p><div class="ch-bgrid">` +
        items.map((b) => `<div class="ch-badge${b.earned ? " is-earned" : ""}" title="${esc(b.description || "")}">
          <span class="ch-badge-m">${badgeMark(b.id, { earned: !!b.earned })}</span>
          <span class="ch-badge-n">${esc(b.label || b.id)}</span>
          <span class="ch-badge-h label">${b.earned ? esc(String(b.earned_date || "").slice(0, 10)) : esc(b.unlock_hint || b.description || "")}</span>
        </div>`).join("") + `</div></div>`;
    }).join("");
    badges = sec("Unlocks — the map of what's ahead",
      figs([fig(String(earned.length), "earned"), fig(String(achList.length - earned.length), "still locked")]) +
      (earned.length === 0 ? `<p class="rd-archive">Nothing earned yet this cycle — every mark below is drawn the moment it's unlocked, and the engine checks nightly. The wall isn't empty; it's the route.</p>` : "") +
      groups +
      // #1126: the wall's dedicated, linkable home.
      `<p class="rd-archive"><a href="/data/badges/">The full badge page — every mark, and what unlocks each →</a></p>`);
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
    ? sec("The math", `<p class="rd-prose">Each pillar scores 0–100 nightly from weighted components (above). Components that measure a <strong>behavior</strong> — logging food, journaling, training — score zero when the behavior doesn't happen; components that measure a <strong>sensor</strong> simply go quiet, and the engine won't judge what it can't see${lvv.level_change_min_coverage != null ? ` (below ${esc(String(Math.round(Number(lvv.level_change_min_coverage) * 100)))}% data coverage, levels freeze in both directions)` : ""}. An exponential moving average (λ = ${esc(String(lvv.ema_lambda))} over ${esc(String(lvv.ema_window_days))} days) smooths the noise into a level score. A <strong>streak counter</strong> then gates every level change — the smoothed score has to hold above (or below) the line for the full gate, a level-up also requires the day itself to have scored at the new level, and crossing a tier boundary demands a longer streak still. Bigger honest gaps move in bigger steps, so pillars converge to what the data earns instead of marching in lockstep. XP runs alongside as resilience: ${esc(String(lvv.xp_per_level))} XP to a level, decaying ${fmt(lvv.daily_xp_decay)} a day, with the buffer under ${esc(String(lvv.xp_buffer_threshold))} XP the only state where a level-down can land. Neglect is modeled, not ignored: after ${esc(String((lvv.neglect_decay && lvv.neglect_decay.n_grace_days) || 3))} dark days of manual-logging silence, behavioral pillars <strong>atrophy</strong> — a small daily decay on the smoothed score, floored at what each day actually measured — and XP below zero shows as visible <strong>debt</strong> instead of a silent floor. The character level is the weighted average of the seven pillar levels, floored — so it understates, never flatters.</p>
      <p class="rd-archive">The full rulebook — every weight, target, streak gate, and honest-absence rule, generated from the engine's actual config — is <a href="/method/game/">The Game, Explained</a>; the plain-language version lives on <a href="/method/character/">the character explainer</a>. The engine itself runs nightly in the platform's compute layer, and every number in this section is read live from its config.</p>`)
    : `<p class="rd-archive">How the engine works — the pillar weights, the XP economy, the streak gates — is documented in full in <a href="/method/game/">The Game, Explained</a> (generated from the engine's actual config) and in plain language on <a href="/method/character/">the character explainer</a>; the algorithms run nightly in the platform's compute layer.</p>`;

  return hero + quiet + scrub + statblock + calCard + ladder + mechanics + record + badges + sub + math +
    note("A motivational lens on real data, not a medical score — every input is correlative and N=1.");
}

/* ── #1126: the dedicated badge wall (/data/badges/) ─────────────────────────
   Reads the SAME /api/achievements the cockpit's Journey lens and the sheet's
   Unlocks section read — one source of truth, now a linkable page. ADR-104 +
   the earned-glow rule: a mark lights ONLY when a real record earned it; the
   all-unearned genesis state is framed honestly as the route ahead, never
   dressed up. Every mark is generative (badgeMark, seeded by id) — no emoji,
   no stock art, and any future catalog addition draws itself. */
export function renderBadges(d) {
  const list = (d && (d.achievements || d.badges)) || [];
  if (!list.length) return empty("The badge catalog publishes from the engine's nightly pass — nothing to show yet, and nothing gets faked in the meantime.");
  const sm = (d && d.summary) || {};
  const earned = list.filter((b) => b.earned);
  const locked = list.length - earned.length;

  const lead = `<p class="rd-lede">${earned.length
    ? `${earned.length} of ${list.length} marks earned — each one lit by a real record, re-checked nightly against the live data.`
    : `The full catalog, none of it earned yet — every mark below lights the moment the data earns it, and not a day sooner.`}</p>`;

  const stats = figs([
    fig(String(earned.length), "earned"),
    fig(String(locked), "still locked"),
    Number.isFinite(Number(sm.current_streak)) ? fig(String(sm.current_streak), "day streak") : "",
    Number.isFinite(Number(sm.days_tracked)) ? fig(String(sm.days_tracked), "days tracked · 365d") : "",
  ]);

  const zero = earned.length === 0
    ? `<p class="rd-archive">Nothing earned yet this cycle — that's the honest read of a fresh start. The wall isn't empty; it's the route: streaks build a day at a time, the engine re-checks nightly, and the first marks land within weeks of consistent days.</p>`
    : "";

  const cats = [...new Set(list.map((b) => b.category || "other"))];
  const groups = cats.map((c) => {
    const items = list.filter((b) => (b.category || "other") === c);
    const won = items.filter((b) => b.earned).length;
    return `<div class="ch-bgroup"><p class="label">${esc(BADGE_CAT_TTL[c] || ttl(c))} · ${won}/${items.length}</p><div class="ch-bgrid">` +
      items.map((b) => `<div class="ch-badge${b.earned ? " is-earned" : ""}" title="${esc(b.description || "")}">
        <span class="ch-badge-m">${badgeMark(b.id, { earned: !!b.earned })}</span>
        <span class="ch-badge-n">${esc(b.label || b.id)}</span>
        <span class="ch-badge-h label">${b.earned ? esc(String(b.earned_date || "").slice(0, 10)) : esc(b.unlock_hint || b.description || "")}</span>
      </div>`).join("") + `</div></div>`;
  }).join("");

  const how = sec("How a mark is earned",
    `<p class="rd-prose">Every badge is computed from the same records the rest of the site reads — habit streaks, the character level, weigh-ins, completed experiments and challenges. There are no participation trophies: a mark either has a record behind it or it stays locked, with what unlocks it written underneath. The level and streak marks ride the <a href="/data/character/">character sheet</a>'s engine (<a href="/method/character/">how levels work</a>); the day-to-day view is the <a href="/cockpit/">cockpit</a>'s Journey lens.</p>`);

  return lead + stats + zero + sec("The wall", groups) + how +
    note("A motivational lens on real data, not a medical score — every input is correlative and N=1.");
}

// The sheet's entrance choreography — ring arcs sweep in (staggered via each
// segment's transition-delay), stat bars fill. Re-run after every time-travel
// redraw. Motion-gated; fail-open: without motion everything is simply drawn.
export function chAnimate(scope) {
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

export function wireCharacter() {
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
