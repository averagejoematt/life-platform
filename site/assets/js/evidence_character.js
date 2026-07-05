/*
  evidence_character.js — the character sheet (/data/character/): the seven-pillar hero,
  stat block, mechanics layer, record and time-travel wiring. Split out of evidence.js
  (#581) — no behavior change.
*/
import { sparkline, ring, pillarRing, radarChart } from "/assets/js/charts.js";
import { badgeMark, tierEmblem } from "/assets/js/sigils.js";
import { domainIcon } from "/assets/js/icons.js";
import { esc, tryJSON, has, fmt, ttl, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";
import { dfBody } from "/assets/js/evidence_datafigure.js";

export const CH_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"];

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

// Shared context for wireCharacter's time-travel re-render (P1.3): the hero +
// stat block rebuild for a scrubbed date; the slow-moving sections stand.
export let _chCtx = null;

/* 1 · Hero — the figure, leveled. Silhouette girth = the real weight; ring
   segments = the seven pillar scores; the emblem = tier + level. If the
   journey isn't available the composite number holds the center instead.
   A builder (not inline) so time travel can redraw it for any date. */

export function chHeroHtml(ch, pillars, jj, wave) {
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

export function chWhy(p) {
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

export function chStatHtml(pillars, hist) {
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

export async function renderCharacter(d) {
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
