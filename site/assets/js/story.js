/*
  story.js — Door 2 behaviour (/)
  ----------------------------------------------------------------------------
  The honest arc, bound to the live engine. Nothing invented: every value is
  from an existing endpoint; absent data degrades to honest copy, never faked.

    /public_stats.json        hero, elena_hero_line, chronicle_recent, character
    /api/journey              weight arc (lost_lbs, progress, projected goal)
    /api/journey_waveform     42-day whole-life score with green/amber/red/gray tiers
    /api/field_notes          the Third Wall (ai_present ↔ matthew_agreement)
    /api/character            pillar scores for the constellation
*/

import { initTheme } from "/assets/js/theme.js";
import { lineChart } from "/assets/js/charts.js";
import { stampGenesis, genesisCount, preStart } from "/assets/js/coach_popover.js"; // P0.1 — the one genesis source of truth (+ #931 pre-start)
import { mountAsk } from "/assets/js/ask.js"; // uplevel P2 — the live inline ask on the home beat
import { mountSinceRibbon } from "/assets/js/since.js"; // uplevel P5 — returnability, reader-keyed
import { instrumentMark, fnv1a, mulberry32 } from "/assets/js/sigils.js"; // visual P2 + #590 seeded drift
import { domainIcon } from "/assets/js/icons.js"; // #590 — pillar icon for the hover door affordance

const $ = (s, r = document) => r.querySelector(s);
const bind = (n, r = document) => r.querySelector(`[data-bind="${n}"]`);
const SVGNS = "http://www.w3.org/2000/svg";

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
const trend = (d) => (d == null ? "flat" : d > 0.05 ? "up" : d < -0.05 ? "down" : "flat");

/* ── the relational constellation (v2, #590) ─────────────────────────────────
   Edges are NO LONGER a hand-drawn topological guess — they are the REAL
   trailing-window co-movement between pillars (/api/pillar_coupling: masked-day
   Pearson r + n). Positive coupling reads as "move together" (ember), negative
   as "trade off" (cool), width tracks |r|, and non-significant or thin pairs
   stay honestly faint; a pillar with no measured coupling (relationships is a
   flat placeholder today) simply has no edges — the absence is the honest signal.
   Nodes drift on a DETERMINISTIC seeded orbit (same seed → same motion, the
   sigils.js vocabulary) and open a door on hover. ADR-104/105: nothing invented. */
const NODES = {
  sleep:        { x: 180, y: 58,  label: "Sleep" },
  movement:     { x: 292, y: 118, label: "Move" },
  nutrition:    { x: 292, y: 250, label: "Fuel" },
  metabolic:    { x: 180, y: 312, label: "Metab" },
  mind:         { x: 68,  y: 250, label: "Mind" },
  relationships:{ x: 68,  y: 118, label: "People" },
  consistency:  { x: 180, y: 185, label: "Hold" },
};
// Each pillar links into its deeper Data page (the story → sub-pages).
const NODE_LINK = {
  sleep: "/data/sleep/", movement: "/data/training/", nutrition: "/data/nutrition/",
  metabolic: "/data/glucose/", mind: "/data/reading/", relationships: "/data/mind/",
  consistency: "/data/habits/",
};
// Icon key per pillar for the hover door affordance (domainIcon maps to icons.js).
const NODE_ICON = {
  sleep: "sleep", movement: "training", nutrition: "nutrition", metabolic: "glucose",
  mind: "mind", relationships: "people", consistency: "habits",
};

// Deterministic per-node drift: seed from the pillar name (fnv1a → mulberry32), so the
// motion is byte-stable across reloads/browsers — the same seed-not-random rule as sigils.
function driftVars(name) {
  const rnd = mulberry32(fnv1a("constellation:" + name));
  const dx = (rnd() * 2 - 1) * 3.2;          // ±3.2px lateral
  const dy = (rnd() * 2 - 1) * 3.2;          // ±3.2px vertical
  const dur = 6 + rnd() * 4;                 // 6–10s, per-node
  const delay = -rnd() * dur;                // desync the phase
  return `--dx:${dx.toFixed(2)}px;--dy:${dy.toFixed(2)}px;--dur:${dur.toFixed(2)}s;--ddelay:${delay.toFixed(2)}s`;
}

// Source pillars implied by an active cross-pillar effect's condition string (the
// condition names the source; targets name the sink). "_all"/all_pillars → global.
function effectSources(cond) {
  const c = String(cond || "").toLowerCase();
  if (c.includes("all_pillars")) return Object.keys(NODES);
  return Object.keys(NODES).filter((p) => c.includes(p));
}

// #1017 — the legibility floor. SVG text is sized in viewBox units, so its on-screen size
// scales with the rendered width: at a 390px viewport the svg draws ~354px wide (scale ≈ 0.98)
// and the 9px labels land at ~8.9px — below the 11px mobile type floor (DESIGN_SYSTEM_V5 §10.5).
// Re-derive the user-unit sizes from the live scale so every label meets its effective-px
// floor; on desktop (scale > 1) max(base, floor/scale) keeps today's sizes — no regression.
const CN_TYPE = [
  ["--cn-fs-label", 9, 11], // .nlabel — pillar names: 11px mono-label is the smallest register that ships
  ["--cn-fs-score", 11, 12], // .score — the numeral keeps its rank above the label
  ["--cn-fs-cue", 8, 11], // .door-cue — interactive affordance, floored at 11px everywhere
];
function sizeConstellation(svg) {
  const w = svg.getBoundingClientRect().width;
  if (!w) return; // hidden / not laid out yet → the stylesheet fallbacks stand
  const scale = w / 360; // viewBox is 0 0 360 360
  for (const [prop, base, floorPx] of CN_TYPE) {
    svg.style.setProperty(prop, `${Math.max(base, floorPx / scale).toFixed(2)}px`);
  }
  // Tap-target floor (§10.4): the transparent per-node hit circle (touch-only via CSS)
  // grows to whatever user-space radius yields a ≥44px effective diameter on screen.
  const hitR = 22 / scale;
  for (const hit of svg.querySelectorAll(".node .hit")) {
    // round UP — rounding down can shave the target to 43.9px effective
    hit.setAttribute("r", String(Math.ceil(Math.max(Number(hit.dataset.baseR) || 0, hitR) * 10) / 10));
  }
}

function drawConstellation(pillars, coupling, activeEffects) {
  const svg = $(".constellation svg");
  if (!svg) return;
  const edgeG = svg.querySelector("[data-edges]");
  const nodeG = svg.querySelector("[data-nodes]");
  edgeG.replaceChildren();
  nodeG.replaceChildren();
  const byName = {};
  for (const p of pillars) byName[p.name] = p;

  // ── EDGES = measured co-movement ──
  const edges = Array.isArray(coupling && coupling.edges) ? coupling.edges : [];
  const coupledPillars = new Set();
  // Which edges are lit RIGHT NOW by an active designed effect (source→target).
  const effectPairs = new Set();
  for (const e of activeEffects || []) {
    const srcs = effectSources(e.condition);
    for (const tgt of Object.keys(e.targets || {})) {
      const t = tgt === "_all" ? Object.keys(NODES) : [tgt];
      for (const s of srcs) for (const tt of t) if (s !== tt) effectPairs.add([s, tt].sort().join("~"));
    }
  }
  for (const e of edges) {
    const na = NODES[e.a], nb = NODES[e.b];
    if (!na || !nb) continue;
    coupledPillars.add(e.a); coupledPillars.add(e.b);
    const mag = Math.min(1, Math.abs(e.r));
    const line = document.createElementNS(SVGNS, "line");
    line.setAttribute("x1", na.x); line.setAttribute("y1", na.y);
    line.setAttribute("x2", nb.x); line.setAttribute("y2", nb.y);
    const sign = e.r >= 0 ? "pos" : "neg";
    const strength = e.significant ? "sig" : "faint";
    const active = effectPairs.has([e.a, e.b].sort().join("~"));
    line.setAttribute("class", `edge ${sign} ${strength}${active ? " effect" : ""}`);
    line.setAttribute("stroke-width", (0.8 + mag * 3.2).toFixed(2));
    line.style.setProperty("--emag", mag.toFixed(3));
    if (sign === "neg") line.setAttribute("stroke-dasharray", "5 4"); // trade-off reads dashed
    const rel = e.r >= 0 ? "move together" : "trade off";
    const t = document.createElementNS(SVGNS, "title");
    t.textContent = `${NODES[e.a].label} ↔ ${NODES[e.b].label}: r=${e.r > 0 ? "+" : ""}${e.r} over ${e.n} days` +
      `${e.significant ? "" : " (not significant)"} — they ${rel}`;
    line.appendChild(t);
    edgeG.appendChild(line);
  }

  // ── NODES = the pillars themselves ──
  for (const [name, pos] of Object.entries(NODES)) {
    const p = byName[name] || {};
    const score = Math.round(p.raw_score ?? 0);
    const r = 14 + Math.min(26, score / 4);   // size by where it stands
    const up = trend(p.xp_delta) === "up";
    const instrumented = coupledPillars.has(name);
    const g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "node" + (up ? " up" : "") + (instrumented ? "" : " quiet"));
    g.setAttribute("style", driftVars(name));
    // #1017 — invisible tap-target expander (§10.4 grammar: bigger hit area, no visual
    // redesign). Sized up to the 44px effective floor by sizeConstellation; touch-only in CSS.
    const hit = document.createElementNS(SVGNS, "circle");
    hit.setAttribute("class", "hit"); hit.setAttribute("cx", pos.x); hit.setAttribute("cy", pos.y);
    hit.setAttribute("r", r); hit.dataset.baseR = String(r);
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("cx", pos.x); c.setAttribute("cy", pos.y); c.setAttribute("r", r);
    const tScore = document.createElementNS(SVGNS, "text");
    tScore.setAttribute("class", "score"); tScore.setAttribute("x", pos.x); tScore.setAttribute("y", pos.y + 4);
    tScore.textContent = score || "";
    const tLab = document.createElementNS(SVGNS, "text");
    tLab.setAttribute("class", "nlabel"); tLab.setAttribute("x", pos.x); tLab.setAttribute("y", pos.y + r + 12);
    tLab.textContent = pos.label;
    // Hover/focus door affordance: pillar icon + "open →" cue, revealed on interaction.
    const door = document.createElementNS(SVGNS, "g");
    door.setAttribute("class", "door");
    const fo = document.createElementNS(SVGNS, "foreignObject");
    fo.setAttribute("x", pos.x - 9); fo.setAttribute("y", pos.y - r - 22); fo.setAttribute("width", 18); fo.setAttribute("height", 18);
    const ico = document.createElement("span");
    ico.className = "door-ico"; ico.innerHTML = domainIcon(NODE_ICON[name] || "vitals", { size: "16px" });
    fo.appendChild(ico);
    const cue = document.createElementNS(SVGNS, "text");
    cue.setAttribute("class", "door-cue"); cue.setAttribute("x", pos.x); cue.setAttribute("y", pos.y + r + 24);
    cue.textContent = "open →";
    door.append(fo, cue);
    g.append(hit, c, tScore, tLab, door);
    const href = NODE_LINK[name];
    if (href) {
      const a = document.createElementNS(SVGNS, "a");
      a.setAttribute("href", href);
      a.setAttribute("aria-label", `${pos.label} — score ${score} of 100, open its data`);
      a.appendChild(g);
      nodeG.appendChild(a);
    } else {
      nodeG.appendChild(g);
    }
  }

  // #1017 — size the type + tap targets for the current rendered width, and keep them
  // floored across rotations/resizes (one rAF-debounced listener, vars-only — no redraw).
  sizeConstellation(svg);
  if (!drawConstellation._resizeWired) {
    drawConstellation._resizeWired = true;
    let raf = 0;
    window.addEventListener("resize", () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => sizeConstellation(svg));
    });
  }
}

/* ── the numbers beat ────────────────────────────────────────────────────── */
// The throughline anchor: stamp "Day N · Week N since genesis" so the site's youth is the
// headline, not an inconsistency. Genesis = the current experiment start (2026-06-14).
// P0.1 — genesis math now lives in coach_popover.js (one source of truth). Home/Story keep
// their "watch it happen" suffix; the day/week numbers come from the shared util so no door
// can drift (the bug that had Home on Week 1 while Story/Coaching were on Week 2).
const STORY_GENESIS_SUFFIX = " — a transformation you can watch happen in real time.";
function renderNumbers(journey, pre) {
  // #931 pre-start: no baseline exists until Day 1's weigh-in, so the numbers beat
  // makes no delta/progress claims — launch-eve framing instead, quiet confidence.
  if (pre) {
    const hp = bind("hero-proof");
    if (hp) {
      hp.textContent = `Launch eve — the instruments are on. The record starts ${pre.startLabel}, with the first weigh-in.`;
      hp.hidden = false;
    }
    const lostEl = bind("lost");
    if (lostEl) {
      lostEl.textContent = "—";
      const figEl = lostEl.closest(".figure");
      const cap = figEl && figEl.querySelector(".figure-cap");
      if (cap) cap.textContent = "lbs — counts from Day 1";
    }
    const curEl = bind("current");
    if (curEl && journey && journey.current_weight_lbs != null) {
      curEl.textContent = journey.current_weight_lbs;
      const curFig = curEl.closest(".figure");
      const curCap = curFig && curFig.querySelector(".figure-cap");
      if (curCap) curCap.textContent = "lbs at the start line";
    }
    const prEl = bind("progress");
    if (prEl) prEl.textContent = "—";
    const pj = bind("projected");
    if (pj) pj.textContent = `No projections yet — the finish-line math begins with Day 1's weigh-in on ${pre.startLabel}. No fake finish line; watch it happen from the start.`;
    return;
  }
  if (!journey) return;
  if (journey.lost_lbs != null) {
    // lost_lbs > 0 = actually lost; < 0 = gained. Show it honestly (the site's whole point),
    // not a gain dressed up as a loss.
    const lost = Number(journey.lost_lbs);
    const up = lost < -0.05, even = Math.abs(lost) <= 0.05;
    const el = bind("lost");
    el.textContent = even ? "0" : String(Math.round(Math.abs(lost) * 10) / 10);
    if (window.__moCount) window.__moCount(el);  // count-up once the real value lands
    const figEl = el.closest(".figure");
    if (figEl) {
      figEl.classList.toggle("is-up", up);
      const cap = figEl.querySelector(".figure-cap");
      if (cap) cap.textContent = even ? "lbs · even" : (up ? "lbs up" : "lbs down");
    }
  }
  if (journey.current_weight_lbs != null) {
    const curEl = bind("current");
    curEl.textContent = journey.current_weight_lbs;
    // Staleness honesty (truth audit 2026-07-10): "lbs today" over a weigh-in that's
    // weeks old reads false. When the last weigh-in is >2 days back, the caption
    // carries the real as-of date instead of claiming "today".
    if (journey.last_weighin_date) {
      const lwd = new Date(`${journey.last_weighin_date}T12:00:00`);
      if (!isNaN(lwd.getTime()) && (Date.now() - lwd.getTime()) / 86400000 > 2) {
        const curFig = curEl.closest(".figure");
        const curCap = curFig && curFig.querySelector(".figure-cap");
        if (curCap) curCap.textContent = `lbs at last weigh-in (${lwd.toLocaleDateString("en-US", { month: "short", day: "numeric" }).toLowerCase()})`;
      }
    }
  }
  if (journey.progress_pct != null) bind("progress").textContent = `${journey.progress_pct}%`;
  // P2.1 — pair the live weight delta with the genesis timeframe up in the hero, so the claim
  // meets its proof on the opening screen (down-beat waveform leads just below).
  if (journey.lost_lbs != null) {
    const lost = Number(journey.lost_lbs);
    const { dayN } = genesisCount();
    const hp = bind("hero-proof");
    if (hp) {
      const dir = lost > 0.05 ? `down ${Math.round(Math.abs(lost) * 10) / 10} lb` : lost < -0.05 ? `up ${Math.round(Math.abs(lost) * 10) / 10} lb` : "even";
      // Honest as-of: the day counter ticks live while the weight only moves at weigh-ins —
      // during a quiet stretch the pairing reads false without the anchor date.
      let asof = "";
      if (journey.last_weighin_date) {
        const lw = new Date(`${journey.last_weighin_date}T12:00:00`);
        if ((Date.now() - lw.getTime()) / 86400000 > 1.5) asof = ` (last weigh-in ${lw.toLocaleDateString("en-US", { month: "short", day: "numeric" })})`;
      }
      hp.textContent = `${dir} in ${dayN} days${asof} — the shape of it, every day, just below.`;
      hp.hidden = false;
    }
  }
  // #535: the honest finish line is a range (earliest..latest), never a false-precision point.
  const _goalFmt = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
  };
  if (journey.projected_goal_date_earliest && journey.projected_goal_date_latest) {
    bind("projected").textContent =
      `At the current rate, goal lands between ${_goalFmt(journey.projected_goal_date_earliest)} and ${_goalFmt(journey.projected_goal_date_latest)}. ` +
      `An 80% range — the interval is the honest part, not a single promised date.`;
  } else if (journey.projected_goal_date) {
    bind("projected").textContent = `At the current rate, goal lands around ${_goalFmt(journey.projected_goal_date) || journey.projected_goal_date}. Correlative projection — not a promise.`;
  } else if (journey.rate_provisional) {
    // Lean into the truth instead of projecting off a thin weigh-in record — but derive
    // the copy from the actual week, not a hardcoded "week one" (it fired in week 3).
    const wk = Number(journey.week_n) || genesisCount().weekN || 1;
    const span = Number(journey.weighin_span_days) || 0;
    bind("projected").textContent = wk <= 1
      ? "Too early to project — this is week one, and an early cut's rate is mostly water weight that will slow. No fake finish line; watch it happen in real time."
      : `No projection yet — the weigh-in record spans only ${span || "a few"} days, too short to draw an honest line. No fake finish line; watch it happen in real time.`;
  } else if (journey.weekly_rate_lbs != null) {
    bind("projected").textContent = "No reliable projection yet — too few weigh-ins to draw a line.";
  }
}

/* ── "Is he okay this week?" — the friends/family surface (#789) ──────────────
   North Star's fourth audience asks "is he okay, is it working, what's the
   journey?" — and the doors route them to an opaque cockpit. This renders the
   answer in plain language, DETERMINISTICALLY, from data the page already
   fetched: the /api/character pillars (raw_score + xp_delta 7-day trend + the
   ADR-104 coverage provenance) and the /api/journey weight delta. Nothing is
   invented and nothing new is fetched. A pillar the engine says carried no
   signal this week reads honestly absent ("not measured this week"); the
   character sheet's own as_of_date stamps the read. No AI, no lambda write. */
const OKAY_LEGIBLE = [
  ["sleep", "Sleep"],
  ["movement", "Training"],
  ["nutrition", "Eating"],
  ["consistency", "Daily habits"],
  ["mind", "Headspace"],
];
// One pillar → one plain, warm status. Honest absent when the engine flags the
// week as no-signal (coverage_hold), coverage is thin (<25%), or the score is a
// flat zero with no movement — never a faked "steady".
function okayStatus(p) {
  if (!p) return { txt: "not measured this week", state: "absent" };
  const cov = p.data_coverage;
  const absent = p.coverage_hold === true || (typeof cov === "number" && cov < 0.25) || (Number(p.raw_score) === 0 && !Number(p.xp_delta));
  if (absent) return { txt: "not measured this week", state: "absent" };
  const t = trend(p.xp_delta);
  if (t === "up") return { txt: "on the up", state: "up" };
  if (t === "down") return { txt: "eased off a little", state: "down" };
  return { txt: "holding steady", state: "flat" };
}
// The manual-input pillars — the ones that only move when Matthew logs. During a
// verified logging stall (truth audit 2026-07-10) their scores decay slowly enough
// that a 100%→0% two-week collapse still read "eased off a little"; the presence
// contract is the honest override. Sleep stays wearable-backed and keeps its trend.
const OKAY_MANUAL = new Set(["movement", "nutrition", "consistency", "mind"]);

function renderOkay(charV, journeyV, presenceV, pre) {
  const wrap = $("[data-okay]");
  if (!wrap) return;
  // #931 pre-start: nothing has happened yet to read — a neutral awaiting state,
  // never chips computed off a wiped week.
  if (pre) {
    wrap.innerHTML =
      `<p class="okay-lead">Awaiting Day 1 — the experiment begins <strong>${esc(pre.startLabel)}</strong>. ` +
      `Baselines start with that morning's first weigh-in, and this panel fills in from the first week of data.</p>` +
      `<p class="okay-asof label">plain-language, from the live cockpit numbers</p>`;
    return;
  }
  // /api/presence is the shipped stall signal (in_lull + gap_days). A lull ≥7 days
  // with no planned pause means the manual pillars aren't "easing off" — nothing is
  // being logged at all, and the chips must say that plainly.
  const pres = presenceV || {};
  const lullDays = Math.round(Number(pres.gap_days) || 0);
  const inLull = !!pres.in_lull && !pres.planned_pause && lullDays >= 7;
  const character = (charV && (charV.character || charV)) || {};
  const pillars = (charV && (charV.pillars || (charV.character && charV.character.pillars))) || [];
  const asOf = character.as_of_date || "";
  const byName = {};
  for (const p of pillars) byName[p.name] = p;

  // The lead line answers the family's "is it working?" with the real weight move
  // — with an honest as-of when the last weigh-in is a couple of days stale (the
  // scale moves slower than the page's day counter).
  let lead = "";
  if (journeyV && journeyV.lost_lbs != null) {
    const lost = Number(journeyV.lost_lbs);
    const n1 = Math.round(Math.abs(lost) * 10) / 10;
    let asofW = "";
    if (journeyV.last_weighin_date) {
      const lw = new Date(`${journeyV.last_weighin_date}T12:00:00`);
      if ((Date.now() - lw.getTime()) / 86400000 > 1.5) asofW = ` (last weigh-in ${lw.toLocaleDateString("en-US", { month: "short", day: "numeric" })})`;
    }
    if (lost > 0.05) lead = `The short version: he's <strong>down ${n1} lb</strong> since the start${esc(asofW)}, and the day-to-day looks like this —`;
    else if (lost < -0.05) lead = `The short version: the scale is <strong>up ${n1} lb</strong> right now${esc(asofW)} — the down weeks get shown here too. Day-to-day, it looks like this —`;
    else lead = `The short version: weight is <strong>holding steady</strong>${esc(asofW)}, and the day-to-day looks like this —`;
  } else {
    lead = "The short version — how the week's actually going, in plain terms:";
  }

  const rows = OKAY_LEGIBLE.map(([name, label]) => ({
    label,
    s: inLull && OKAY_MANUAL.has(name)
      ? { txt: `nothing logged for ${lullDays} days`, state: "absent" }
      : okayStatus(byName[name]),
  }));
  const allAbsent = !inLull && rows.every((r) => r.s.state === "absent");
  const asofLine = asOf
    ? `<p class="okay-asof label">as of ${esc(asOf)} · plain-language, computed from the same numbers on <a href="/cockpit/">the cockpit</a></p>`
    : `<p class="okay-asof label">plain-language, from the live cockpit numbers</p>`;

  if (allAbsent) {
    // Fresh cycle / post-reset: refuse to read a week with no signal. Honest silence.
    wrap.innerHTML =
      `<p class="okay-lead">This week's numbers are still filling in — too early to read honestly yet. <a href="/cockpit/">The cockpit</a> shows whatever's landed so far.</p>` +
      asofLine;
    return;
  }
  const chips = rows
    .map((r) => `<li class="okay-chip okay-${r.s.state}"><span class="okay-lab">${esc(r.label)}</span><span class="okay-val">${esc(r.s.txt)}</span></li>`)
    .join("");
  wrap.innerHTML = `<p class="okay-lead">${lead}</p><ul class="okay-chips">${chips}</ul>${asofLine}`;
}

/* ── the quiet stretch (presence) ────────────────────────────────────────── */
// Home is where family lands first — when the manual logs go quiet, say so in one
// calm line (the shipped /api/presence contract; same tone as the Story timeline's
// quiet-stretch beat). No banner, no red, and never a cause — the cause isn't in
// the data. Hides itself entirely when logging is current or the pause is planned.
function renderQuiet(p, pre) {
  const el = bind("hero-quiet");
  // #931 pre-start: launch eve reads as anticipation, not a lull — the quiet line
  // stays hidden until the experiment is actually running.
  if (pre) return;
  if (!el || !p || !p.in_lull || p.planned_pause) return;
  const days = Math.round(Number(p.gap_days) || 0);
  const since = days >= 2 ? `${days} days since the last entry` : "the latest entry is a beat behind";
  const passive = p.passive_still_flowing === false ? "" : " — the wearables kept recording, so the record stays honest";
  el.textContent = `The manual logs have gone quiet (${since})${passive}.`;
  el.hidden = false;
}

/* ── the waveform (honest down-beats) ────────────────────────────────────── */
// Tier by RELATIVE position within the window, not a fixed 250/150 cut. The real
// daily scores cluster in a narrow band (~250–320), so an absolute threshold painted
// every day "up" (green) — a down day was structurally impossible, which silently broke
// the page's own "down weeks shown, not hidden" promise. Relative tiers make the shape
// of the week honest: the lower days read as holding/down, the best days as up.
function tierOfRel(pos) {
  if (pos == null) return "none";
  if (pos >= 0.62) return "up";
  if (pos >= 0.3) return "mid";
  return "down";
}
function renderWave(days) {
  const wrap = bind("wave");
  if (!wrap || !Array.isArray(days) || !days.length) {
    if (wrap) wrap.textContent = "The waveform fills in as the daily scores accrue.";
    return;
  }
  // Normalize bar HEIGHT and COLOR to the window's own range (14%-floor + 86%-span keeps
  // small days visible). When every day is ~equal (span≈0) nothing is faked as a dip.
  const scores = days.map((d) => d.score || 0).filter(Boolean);
  const lo = scores.length ? Math.min(...scores) : 0;
  const span = Math.max(1, (scores.length ? Math.max(...scores) : 1) - lo);
  const meaningfulSpread = scores.length >= 4 && (Math.max(...scores) - lo) >= 8;
  // Each scored day deep-links into its own cockpit sheet (/cockpit/?date= — the
  // time-travel view that already exists one URL away). The signature honesty
  // artifact stops being inert: tap a dip, read that morning. No-data days stay
  // plain spans — there's no sheet to open.
  const n = days.length;
  const cpts = [];  // #590 — the SHARED interaction contract (motion.js draws the focus dot + tip)
  const bars = days.map((d, i) => {
    const pos = d.score ? (d.score - lo) / span : null;
    const linkable = !!d.date && d.score != null;
    const bar = document.createElement(linkable ? "a" : "span");
    bar.className = `bar ${d.score == null ? "none" : meaningfulSpread ? tierOfRel(pos) : "up"}`;
    const h = d.score ? 14 + (pos || 0) * 86 : 6;
    bar.style.height = `${h}%`;
    bar.title = `${d.date || ""}: ${d.score ?? "no data"}`; // a11y / no-JS fallback
    cpts.push({
      x: n > 1 ? (i + 0.5) / n : 0.5,
      y: 1 - h / 100,  // the bar's top, in normalized figure coords
      l: `${d.date || ""} · ${d.score == null ? "no data" : "score " + d.score + " — tap to open that day"}`,
      v: d.score == null ? null : d.score,
    });
    if (linkable) {
      bar.href = `/cockpit/?date=${encodeURIComponent(d.date)}`;
      bar.setAttribute("aria-label", `${d.date} · score ${d.score} — open that day's cockpit`);
    } else {
      bar.setAttribute("aria-hidden", "true");
    }
    return bar;
  });
  // A FRESH inner node carries the data-cpts contract + the flex bar row; motion.js's
  // MutationObserver wires the shared focus dot + tooltip + keyboard exploration on it
  // (the bespoke cursor-tooltip is gone — one interaction system across the whole site, #590/#582).
  const inner = document.createElement("div");
  inner.className = "wave-cpts";
  inner.setAttribute("data-cpts", JSON.stringify(cpts));
  inner.append(...bars);
  wrap.replaceChildren(inner);
}

/* ── the Third Wall ──────────────────────────────────────────────────────── */
// P1.2 — the Third Wall's one home is Coaching. Home shows a TEASER: the latest field note's
// AI line (trimmed) + a clear pointer that the full exchange — the AI's notes and Matthew's
// replies — lives in Coaching. No full AI↔Matthew duplicate here.
async function renderWall() {
  const wall = bind("wall");
  try {
    const list = await getJSON("/api/field_notes");
    const latest = list.entries && list.entries[0];
    if (!latest) throw new Error("no field notes");
    const week = latest.week;
    const full = await getJSON(`/api/field_notes?week=${encodeURIComponent(week)}`);
    const e = full.entry || {};
    const aiText = e.ai_present || e.ai_affirming || e.ai_cautionary || "";
    const trimmed = aiText.length > 240 ? esc(aiText.slice(0, 240)) + "…" : esc(aiText);
    const replied = !!e.matthew_agreement;
    wall.innerHTML =
      `<div class="voice machine"><span class="who">The AI</span><p class="what">${trimmed}</p></div>` +
      `<p class="wall-teaser">${replied ? "Matthew answered this one back" : "Matthew hasn't replied to this one yet — and that's allowed; the wall is honest both ways"}. The full exchange — the AI's weekly notes and Matthew's replies — lives in <a href="/coaching/">Coaching</a>.</p>`;
    bind("wall-week").textContent = e.ai_generated_at ? `field note · week ${esc(week)} · ${esc(e.ai_tone || "mixed")}` : `field note · week ${esc(week)}`;
  } catch (_e) {
    wall.innerHTML = `<div class="voice machine"><span class="who">The AI</span><p class="what">The field notes — where the model says its piece and Matthew answers back — appear each week in <a href="/coaching/">Coaching</a>.</p></div>`;
  }
}

/* ── Dispatches reader — the native narrative archive ─────────────────────── */
/*  Chronicle (Elena), Lab notes (the AI↔Matthew field notes), and the Journal.
    Lab notes render fully native from /api/field_notes; chronicle/journal render
    their real excerpts + metadata from posts.json. Master-detail, deep-linkable. */
const DX = [
  // Chronicle reads the live genesis-anchored feed (/journal/posts.json) — the old
  // /chronicle/posts.json was a dead season-1 snapshot with Feb–May dates + wrong weeks (#1/#3).
  { key: "chronicle", label: "Chronicle", url: "/journal/posts.json" },
  { key: "labnotes", label: "Lab notes", url: "/api/field_notes" },
  { key: "journal", label: "Journal", url: "/journal/posts.json" },
];
const dxState = { src: "chronicle", cache: {} };

async function dxFetch(src) {
  if (dxState.cache[src]) return dxState.cache[src];
  const cfg = DX.find((d) => d.key === src);
  try { const d = await getJSON(cfg.url); dxState.cache[src] = d; return d; } catch (e) { return null; }
}
function dxEntries(src, data) {
  if (!data) return [];
  if (src === "labnotes") return (data.entries || []).map((e) => { const lbl = e.week_label || `Week ${e.week}`; return ({ id: e.week, label: lbl, title: `${lbl} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "", meta: e.ai_tone }); });
  const posts = data.posts || data.entries || (Array.isArray(data) ? data : []);
  return posts.map((p) => { const lbl = p.label || `Week ${p.week}`; return ({ id: p.week, label: lbl, title: p.title || lbl, date: p.date, meta: p.stats_line, excerpt: p.excerpt, word_count: p.word_count, image_url: p.image_url || "", image_credit: p.image_credit || "" }); });
}

async function dxRenderRead(src, id) {
  const read = document.querySelector("[data-dx-read]");
  if (src === "labnotes") {
    read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
    try {
      const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`);
      const e = d.entry || {};
      const voices = [["The AI", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"], ["Matthew", e.matthew_agreement, "human"]].filter((v) => v[1]);
      read.innerHTML = `<p class="dx-kicker label">field note · ${esc(e.week_label || `week ${id}`)}${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
        (voices.length ? voices.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("")
          : `<p class="beat-note">No field note recorded for this week yet.</p>`);
    } catch (e) { read.innerHTML = `<p class="beat-note">Couldn't load this field note just now.</p>`; }
    return;
  }
  const data = await dxFetch(src);
  const ent = dxEntries(src, data).find((x) => String(x.id) === String(id));
  if (!ent) { read.innerHTML = `<p class="beat-note">Pick an entry to read it here.</p>`; return; }
  read.innerHTML =
    `<p class="dx-kicker label">${src === "chronicle" ? "chronicle · Elena Voss" : "journal"} · ${esc(ent.label || `week ${ent.id}`)}${ent.date ? ` · ${esc(ent.date)}` : ""}</p>` +
    `<h3 class="dx-title">${esc(ent.title)}</h3>` +
    (ent.meta ? `<p class="dx-stats label">${esc(ent.meta)}</p>` : "") +
    `<p class="dx-prose">${esc(ent.excerpt || "")}</p>` +
    (ent.word_count ? `<p class="dx-foot label">${esc(ent.word_count)} words · full dispatch publishes here as the chronicle fills in</p>` : "");
}

function dxSelectEntry(src, id, silent) {
  document.querySelectorAll(".dx-item").forEach((b) => b.classList.toggle("is-active", String(b.dataset.id) === String(id)));
  if (!silent) { try { history.replaceState(null, "", `#dispatches/${src}/${id}`); } catch (e) {} }
  dxRenderRead(src, id);
}
async function dxSelectSrc(src, preId) {
  dxState.src = src;
  document.querySelectorAll(".dx-tab").forEach((t) => { const on = t.dataset.src === src; t.classList.toggle("is-active", on); t.setAttribute("aria-pressed", String(on)); });
  const listEl = document.querySelector("[data-dx-list]");
  listEl.innerHTML = `<li class="dx-empty"><span class="shimmer">Loading…</span></li>`;
  const entries = dxEntries(src, await dxFetch(src));
  if (!entries.length) { listEl.innerHTML = `<li class="dx-empty">Nothing published here yet — it fills as the experiment runs.</li>`; document.querySelector("[data-dx-read]").innerHTML = ""; return; }
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}</span><span class="dx-item-d label">${esc(e.date || "")}</span></button></li>`).join("");
  listEl.querySelectorAll(".dx-item").forEach((b) => b.addEventListener("click", () => dxSelectEntry(src, b.dataset.id)));
  const initId = preId && entries.some((e) => String(e.id) === String(preId)) ? preId : entries[0].id;
  dxSelectEntry(src, initId, true);
}
// P1.1 + P1.3 — Home no longer hosts the full master-detail dispatches reader (that lives in
// Story now, one canonical home). Home shows a one-line TEASER of the latest chronicle entry +
// the existing "read the full story in Story" link. The reader machinery (dxSelectSrc etc.)
// stays in this file but is only used by the teaser fetch — no duplicate reader is built.
async function dxTeaser() {
  const tabsEl = document.querySelector("[data-dx-tabs]");
  const layout = document.querySelector(".beat-dispatches .dx-layout");
  if (tabsEl) tabsEl.hidden = true;
  if (layout) layout.hidden = true;
  const read = document.querySelector("[data-dx-read]");
  if (!read) return;
  read.hidden = false;
  read.classList.add("dx-teaser");
  try {
    const data = await dxFetch("chronicle");
    const latest = dxEntries("chronicle", data)[0];
    if (latest) {
      // Freshness stated plainly: "latest" from a weekly serial can honestly be
      // days old — say how many, so a stale beat never masquerades as today's.
      let ago = "";
      if (latest.date) {
        const days = Math.max(0, Math.round((Date.now() - Date.parse(latest.date)) / 86400000));
        ago = days >= 2 ? ` · ${days} days ago` : days === 1 ? " · yesterday" : " · today";
      }
      // Editorial cover (visual uplevel P3): the same duotone treatment the Story
      // reader uses — fills the teaser's empty left column when a cover exists.
      const cover = latest.image_url
        ? `<figure class="editorial-img editorial-cover"><img class="img-duotone" src="${esc(latest.image_url)}" alt="" loading="lazy">${latest.image_credit ? `<figcaption class="img-credit label">${esc(latest.image_credit)}</figcaption>` : ""}</figure>`
        : "";
      read.innerHTML =
        `<p class="dx-kicker label">latest from the chronicle · Elena Voss${latest.date ? ` · ${esc(latest.date)}${ago}` : ""}</p>` +
        cover +
        `<h3 class="dx-title">${esc(latest.title || latest.label || "")}</h3>` +
        (latest.excerpt ? `<p class="dx-prose">${esc(String(latest.excerpt).slice(0, 240))}…</p>` : "") +
        `<p class="dx-foot label">The chronicle, journal &amp; podcast read in full in <a href="/story/">Story</a>; the AI lab notes live in <a href="/coaching/">Coaching</a>. This is just the latest beat.</p>`;
      return;
    }
  } catch (e) { /* fall through to the quiet placeholder */ }
  read.innerHTML = `<p class="beat-note">The chronicle fills in as the experiment runs — read it in <a href="/story/">Story</a>.</p>`;
}

/* ── load ────────────────────────────────────────────────────────────────── */
async function load() {
  initTheme();
  renderWall();

  const [stats, journey, wave, character, weight, presence, coupling] = await Promise.allSettled([
    getJSON("/public_stats.json"),
    getJSON("/api/journey"),
    getJSON("/api/journey_waveform"),
    getJSON("/api/character"),
    getJSON("/api/weight_progress"),
    getJSON("/api/presence"),
    getJSON("/api/pillar_coupling"),  // #590 — measured pillar co-movement for the constellation edges
  ]);

  const journeyV = journey.status === "fulfilled" ? (journey.value.journey || journey.value) : null;
  // #931 pre-start: payload-first (journey carries pre_start/days_until_start/
  // start_date), client GENESIS fallback. Truthy only in the staged-reset window.
  const pre = preStart(journeyV);

  const statsV = stats.status === "fulfilled" ? stats.value : null;
  if (statsV) {
    // Pre-start the stored hero line can narrate the WIPED cycle — the static
    // timeless line in the HTML stands instead.
    if (statsV.elena_hero_line && !pre) bind("elena").textContent = statsV.elena_hero_line;
    if (statsV._meta && statsV._meta.generated_at) bind("asof").textContent = `updated ${String(statsV._meta.generated_at).slice(0, 10)}`;
  }
  // #949 — the hero's "this attempt starts at …" claim binds to the LIVE baseline
  // (/api/journey start_weight_lbs), never a hand-coded literal that strands on the
  // next reset. Pre-start there is no baseline yet — the weigh-in is the honest copy.
  const hs = bind("hero-start");
  if (hs) {
    if (pre) hs.textContent = `${pre.startDow}'s first weigh-in`;
    else if (journeyV && journeyV.start_weight_lbs != null) hs.textContent = `${Math.round(Number(journeyV.start_weight_lbs))} lbs`;
  }
  stampGenesis(document, STORY_GENESIS_SUFFIX);  // P0.1 — shared genesis source; per-door suffix (pre-start: the countdown line)
  // The review's "central number": a prominent day-of-experiment counter in the hero.
  // Pre-start (#931) it counts DOWN to Day 1 — calm, dated, no marketing timer.
  const { dayN, weekN } = genesisCount();
  const dn = bind("dayNum"), dc = bind("dayCap");
  if (pre && dn && dc) {
    // The hero daycount IS the countdown — the genesis stamp (which the client-only
    // stampGenesis may have written from a not-yet-rewritten GENESIS literal, or as
    // a duplicate countdown) stays hidden pre-start.
    const gs = bind("genesisStamp");
    if (gs) gs.hidden = true;
    if (pre.daysUntil >= 2) {
      dn.textContent = String(pre.daysUntil);
      dc.textContent = `days until the experiment begins — ${pre.startLabel}`;
    } else if (pre.daysUntil === 1) {
      dn.textContent = "1";
      dc.textContent = `day to go — the experiment begins tomorrow, ${pre.startLabel}`;
    } else {
      dn.textContent = "0";
      dc.textContent = "the experiment begins today, with the first weigh-in";
    }
    // #949 — the countdown moment gets its conversion hook: an inline follow CTA
    // right under the count, pre-start only (post-start the close beat owns it).
    const dcWrap = dn.closest(".hero-daycount");
    if (dcWrap && !$(".hero-cta-pre")) {
      const cta = document.createElement("p");
      cta.className = "hero-cta hero-cta-pre";
      cta.innerHTML = `<a href="/subscribe/" class="cta">Get Day 1 in your inbox →</a> <a href="/rss.xml" class="cta cta-quiet">or follow via RSS</a>`;
      dcWrap.insertAdjacentElement("afterend", cta);
    }
  } else if (dayN >= 1) {
    if (dn) { dn.textContent = String(dayN); if (window.__moCount) window.__moCount(dn); }
    if (dc) dc.textContent = dayN === 1 ? "day one of the experiment" : `days into the experiment · week ${weekN}`;
  }
  dxTeaser();  // P1.1/P1.3 — Home teases the latest chronicle; the full reader lives in Story

  renderNumbers(journeyV, pre);
  renderQuiet(presence.status === "fulfilled" ? presence.value : null, pre);

  const wp = weight.status === "fulfilled" ? (weight.value.weight_progress || weight.value) : [];
  const wc = bind("weightchart");
  // HARD RULE 4: the goal (185) must NOT anchor the y-axis — passing it flattened the real
  // slope into a sliver at the top (the "empty chart" bug). Axis comes from the weight data
  // alone; goal progress already lives in the numbers above. spine adds the min/max scale.
  if (wc) wc.innerHTML = lineChart(Array.isArray(wp) ? wp : [], { valueKey: "weight_lbs", unit: " lb", spine: true, label: "Weight · the actual line", emptyMsg: "The weight line fills in as weigh-ins accrue." });

  const waveResp = wave.status === "fulfilled" ? wave.value : null;
  const waveV = waveResp ? (waveResp.days || waveResp.waveform || waveResp) : null;
  renderWave(Array.isArray(waveV) ? waveV : (waveV && waveV.days) || []);
  // Dynamic wave label — the window now tracks the experiment (genesis→today), not a fixed 42.
  const ww = bind("wave-window");
  if (ww && waveResp && waveResp.day_n) ww.textContent = `${waveResp.day_n} day${waveResp.day_n === 1 ? "" : "s"} · the shape of it`;
  // Reader-truth (#1094 drill finding): the static claim promises "every day,
  // including the ones that dipped" — a lie over a 1-dot chart. Under ~2 weeks
  // the claim speaks in the young-window voice; the static line returns once
  // there's enough history for "the ones that dipped" to be literally true.
  const wclaim = bind("wave-claim");
  const waveDayN = waveResp && waveResp.day_n;
  if (wclaim && waveDayN != null && waveDayN < 14) {
    wclaim.textContent =
      waveDayN <= 1
        ? "The climb isn't a straight line — it starts as a single dot. Every day lands here, dips included, as they happen."
        : `The climb isn't a straight line. ${waveDayN} days in, every one is here — dips included, as they come.`;
  }

  const charV = character.status === "fulfilled" ? character.value : null;
  const pillars = (charV && (charV.pillars || (charV.character && charV.character.pillars))) || [];
  const activeEffects = (charV && charV.character && charV.character.active_effects) || [];
  const couplingV = coupling.status === "fulfilled" ? coupling.value : null;
  drawConstellation(
    pillars.length ? pillars : Object.keys(NODES).map((name) => ({ name, raw_score: 0, xp_delta: 0 })),
    couplingV,
    activeEffects,
  );
  const cw = bind("const-window");
  if (cw && couplingV && couplingV.window_days) cw.textContent = ` over the last ${couplingV.window_days} days`;

  // #789 — the friends/family "is he okay this week?" plain-language read, from the
  // pillars + weight already in hand (no extra fetch). The presence result (already
  // fetched for the quiet-stretch line) keeps the chips honest during a logging stall.
  renderOkay(charV, journeyV, presence.status === "fulfilled" ? presence.value : null, pre);
}

load();

// uplevel P2 — the home "Ask the data" beat is a REAL inline ask (it was a styled
// teaser that linked away). Same shared widget as the Data door; three chips tuned
// for a first-time visitor. Fail-quiet: no mount point → nothing breaks.
// uplevel P5 — the returnability strip: the since-ribbon (reader-keyed, cockpit owns
// the stamp) + anything the correlation engine newly unlocked this month (announced
// once, correlative framing). The wrap unhides only if a child has something to say.
(async function homePulse() {
  const wrap = document.querySelector("[data-home-since-wrap]");
  if (!wrap) return;
  const rib = wrap.querySelector("[data-home-since]");
  await mountSinceRibbon(rib);
  try {
    // #949 pre-start: /api/what_changed still carries the PRIOR cycle's unlocks
    // (its window predates Day 1) — announcing intelligence on a Day-0 site reads
    // incoherent under the countdown. The engine starts listening with Day 1.
    if (!preStart()) {
      const r = await fetch("/api/what_changed", { headers: { accept: "application/json" } });
      const d = r.ok ? await r.json() : null;
      const nu = ((d && d.newly_unlocked) || [])[0];
      const el = wrap.querySelector("[data-home-unlocked]");
      if (nu && el) {
        const pretty = String(nu.label || "").replace(/_vs_/g, " ↔ ").replace(/_/g, " ");
        // r to 2 decimals — 4-decimal display is false precision (ADR-105); the
        // strength label stays the engine's own n-gated call, never re-derived here.
        const rDisp = Number.isFinite(Number(nu.r)) ? Number(nu.r).toFixed(2) : nu.r;
        el.textContent = `newly unlocked this month: ${pretty} (r=${rDisp}, n=${Math.round(nu.n)}, ${nu.direction}${nu.interpretation ? " · " + nu.interpretation : ""}) — correlation, not cause; announced once.`;
        el.hidden = false;
      }
    }
  } catch (e) { /* honest silence */ }
  if ((rib && !rib.hidden) || !wrap.querySelector("[data-home-unlocked]").hidden) wrap.hidden = false;
})();

mountAsk(document.querySelector("[data-home-ask]"), {
  chips: ["Is my sleep actually improving?", "What moves the glucose most?", "Is the weight loss on track?"],
  note: "AI-generated from the published data — correlative, never medical advice. Rate-limited (5/hour); may pause under the budget guard.",
});

// visual P2 — the faint marginal instrument mark on the loop beat (one of exactly
// three on the whole site; the OG card's own device, so on- and off-site share
// one vocabulary). aria-hidden, decorative-but-branded, draw-in via tokens §13.
document.querySelectorAll("[data-imark]").forEach((el) => { el.innerHTML = instrumentMark(); });

/* ── #413 "where would you land" — the client-only mirror ───────────────────
   The reader types ONE number; it is compared against Matthew's already-public
   band and NEVER leaves the page: submit is preventDefault-ed, there is no
   fetch/beacon/storage in this flow (the only network reads happen at render,
   before any input exists). N=1 framing and no-advice copy live in the HTML. */
async function wireMirror() {
  const form = $("[data-mirror]");
  const out = $("[data-mirror-out]");
  if (!form || !out) return;
  // Matthew's public numbers only — fetched read-only at render time.
  const [stats, wk] = await Promise.all([
    getJSON("/public_stats.json").catch(() => null),
    getJSON("/api/observatory_week?domain=sleep").catch(() => null),
  ]);
  const v = (stats && stats.vitals) || {};
  const j = (stats && stats.journey) || {};
  const spark = ((((wk || {}).summary || {}).primary || {}).sparkline || []).filter((n) => typeof n === "number" && n > 0);

  const metrics = {};
  if (spark.length >= 3) {
    metrics.sleep = {
      label: "sleep last night (hours)", unit: "h", max: 16,
      markers: () => {
        const lo = Math.min(...spark), hi = Math.max(...spark);
        const avg = spark.reduce((a, b) => a + b, 0) / spark.length;
        return { lo, hi, points: [{ v: lo, l: "his low" }, { v: avg, l: "his avg" }, { v: hi, l: "his high" }],
          read: (x) => `Matthew's last ${spark.length} nights ran ${lo.toFixed(1)}–${hi.toFixed(1)}h (avg ${avg.toFixed(1)}). Your ${x.toFixed(1)}h sits ${x < lo ? "below" : x > hi ? "above" : "inside"} that band.` };
      },
    };
  }
  if (typeof v.rhr_bpm === "number") {
    metrics.rhr = {
      label: "resting heart rate (bpm)", unit: "bpm", max: 220,
      markers: () => ({ lo: Math.min(v.rhr_bpm, 40), hi: Math.max(v.rhr_bpm, 90), points: [{ v: v.rhr_bpm, l: "Matthew now" }],
        read: (x) => `Matthew's current resting HR is ${Math.round(v.rhr_bpm)} bpm. Yours is ${Math.round(x)} — ${Math.abs(Math.round(x - v.rhr_bpm))} bpm ${x < v.rhr_bpm ? "lower" : x > v.rhr_bpm ? "higher" : "— the same"}. One body's number, not a target.` }),
    };
  }
  // #949 pre-start: the stored journey block can narrate the WIPED cycle ("started
  // at X, is at Y today") — the weight mirror stays honestly absent until Day 1's
  // baseline exists. Payload-first (the regenerated file carries pre_start), client
  // GENESIS fallback so a stale cached file can't leak prior-cycle numbers as "today".
  const preMirror = preStart(j);
  if (!preMirror && typeof j.start_weight_lbs === "number" && typeof j.current_weight_lbs === "number" && typeof j.goal_weight_lbs === "number") {
    metrics.weight = {
      label: "weight (lbs)", unit: "lbs", max: 1000,
      markers: () => ({ lo: Math.min(j.goal_weight_lbs, j.current_weight_lbs) - 20, hi: j.start_weight_lbs + 20,
        points: [{ v: j.start_weight_lbs, l: "his start" }, { v: j.current_weight_lbs, l: "him today" }, { v: j.goal_weight_lbs, l: "his goal" }],
        read: (x) => `Matthew started at ${j.start_weight_lbs} lbs, is at ${j.current_weight_lbs} today, aiming for ${j.goal_weight_lbs}. Your ${Math.round(x)} sits ${x > j.start_weight_lbs ? "above his start" : x > j.current_weight_lbs ? "between his start and today" : x > j.goal_weight_lbs ? "between him today and his goal" : "past his goal"}.` }),
    };
  }
  const keys = Object.keys(metrics);
  if (!keys.length) return; // no public numbers to mirror — the beat stays honestly hidden

  const sel = form.querySelector(".mirror-metric");
  sel.innerHTML = keys.map((k) => `<option value="${k}">${esc(metrics[k].label)}</option>`).join("");
  form.hidden = false;

  form.addEventListener("submit", (e) => {
    e.preventDefault(); // the number stays HERE — no request is ever made
    const m = metrics[sel.value];
    const x = parseFloat(form.value.value);
    if (!m || !Number.isFinite(x) || x <= 0 || x > m.max) {
      out.innerHTML = `<p class="mirror-read label">That doesn't look like a plausible ${esc(m ? m.label : "number")} — try again.</p>`;
      return;
    }
    const { lo, hi, points, read } = m.markers();
    const span = Math.max(hi - lo, 1e-6);
    const clamp = (n) => Math.max(2, Math.min(98, ((n - lo) / span) * 96 + 2));
    out.innerHTML =
      `<div class="mirror-strip" role="img" aria-label="${esc(read(x))}">` +
      points.map((p) => `<span class="ms-mark" style="left:${clamp(p.v)}%"><i></i><span class="label">${esc(p.l)}</span></span>`).join("") +
      `<span class="ms-mark ms-you" style="left:${clamp(x)}%"><i></i><span class="label">you</span></span></div>` +
      `<p class="mirror-read">${esc(read(x))}</p>` +
      `<p class="mirror-note label">single-subject comparison (n=1) — context, not a verdict. your number was not sent or saved.</p>`;
  });
}
wireMirror();
