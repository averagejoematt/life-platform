/*
  story_attempts.js — The Serial Restarter's Ledger (#1375).

  /story/attempts/ renders every cycle as an expedition log — day-count and a
  cause-of-death line per ended attempt, plus what changed — derived LIVE from
  /api/survival (engagement record) + /api/cycle_compare (matched windows).
  Real data only, never authored lore: every number on this page comes from a
  payload, and an absent payload renders an honest empty state.

  The survival overlay lays every attempt on the same day-N axis (day 1 at the
  left edge), so "how far did each one get" is one glance. Down ≠ red: a dead
  attempt is ink, not alarm — the restarts are part of the experiment.
*/

import "/assets/js/svgtype.js";
import { seasonBand } from "/assets/js/texture.js"; // #1471 — a season banner per attempt
import { dayInWords } from "/assets/js/entry_age.js"; // #4182 — dates in words, never ISO

const $ = (sel) => document.querySelector(sel);

async function J(path) {
  try {
    const r = await fetch(path, { headers: { accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const n = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString("en-US"));

/* Days an attempt stayed alive: a collapsed attempt died ON collapse_day (it
   lived collapse_day − 1 full days); a censored attempt (re-anchored while
   engaged) or the live one has its whole window so far. */
function aliveDays(c) {
  if (c.collapse_day) return Math.max(0, c.collapse_day - 1);
  return c.window_days || 0;
}

/* #6224 (owner ruling 2026-09-26, ADR-157 (5)): no start/attempt COUNT on a reader surface — no "#17", no "attempt
   #N", no "16 attempts". Starts are named by their date. The live start's day is computed here, from its genesis and
   today's Pacific date, so it is live even when a served window lags (it read "day 70" on day 79). */
function ptToday() {
  try { return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date()); } catch { return null; }
}
function liveDay(c) {
  const t = ptToday();
  const d = t && c && c.genesis ? Math.round((Date.parse(t) - Date.parse(c.genesis)) / 864e5) + 1 : null;
  return d != null && d >= 1 ? d : null;
}
const startName = (c) => esc(dayInWords(c.genesis, { weekday: false }) || c.genesis);

function fateLine(c, collapseDef) {
  if (c.is_current) return liveDay(c) ? `live — day ${n(liveDay(c))}` : "live";
  if (c.collapse_day) return `collapsed on day ${n(c.collapse_day)} — ${esc(collapseDef || "engagement went silent")}`;
  return "re-anchored while still engaged — a fresh start, not a collapse";
}

/* ── the overlay: every attempt on the same day-N axis ─────────────────── */
function overlaySVG(cycles) {
  const W = 760, ROW = 26, PADL = 140, PADR = 16, PADT = 26, PADB = 30;
  const maxDay = Math.max(30, ...cycles.map((c) => c.window_days || 0));
  const H = PADT + cycles.length * ROW + PADB;
  const x = (d) => PADL + (d / maxDay) * (W - PADL - PADR);

  const ticks = [1, 7, 14, 30, 60].filter((t) => t <= maxDay);
  const axis = ticks.map((t) =>
    `<line class="att-grid" x1="${x(t)}" y1="${PADT - 8}" x2="${x(t)}" y2="${H - PADB + 4}"/>` +
    `<text class="att-tick" x="${x(t)}" y="${H - PADB + 16}" text-anchor="middle">day ${t}</text>`).join("");

  const rows = cycles.map((c, i) => {
    const y = PADT + i * ROW + ROW / 2;
    const alive = aliveDays(c);
    const cls = c.is_current ? "att-bar is-live" : "att-bar";
    const bar = alive > 0
      ? `<line class="${cls}" x1="${x(0)}" y1="${y}" x2="${x(alive)}" y2="${y}"/>`
      : "";
    const end = c.is_current
      ? `<text class="att-live-mark" x="${x(alive) + 4}" y="${y + 4}">▶</text>`
      : c.collapse_day
        ? `<text class="att-death" x="${x(c.collapse_day)}" y="${y + 4}" text-anchor="middle">×</text>`
        : `<text class="att-censor" x="${x(alive) + 4}" y="${y + 4}">↺</text>`;
    return `<text class="att-label" x="${PADL - 8}" y="${y + 4}" text-anchor="end">${startName(c)}</text>${bar}${end}`;
  }).join("");

  const legend =
    `<text class="att-tick" x="${PADL}" y="${PADT - 14}">every attempt, aligned at day 1 — × ended · ↺ restarted · ▶ running</text>`;

  return `<svg class="att-svg" viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid meet" ` +
    `aria-label="All attempts overlaid on the same day axis">${axis}${legend}${rows}</svg>`;
}

/* ── the expedition log ────────────────────────────────────────────────── */
function logCards(cycles, byN, collapseDef) {
  return cycles.slice().reverse().map((c) => {
    const m = byN[c.cycle] || {};
    const next = cycles.find((x) => x.cycle === c.cycle + 1);
    const changed = c.is_current ? "" : next
      ? ` What changed: restarted ${startName(next)}.`
      : "";
    const stats = [
      m.weight_delta_lbs != null ? `weight ${m.weight_delta_lbs > 0 ? "+" : ""}${n(m.weight_delta_lbs)} lb in the window` : null,
      m.avg_recovery_pct != null ? `avg recovery ${n(m.avg_recovery_pct)}%` : null,
      m.avg_sleep_hours != null ? `avg sleep ${n(m.avg_sleep_hours)}h` : null,
    ].filter(Boolean).join(" · ");
    return `<li class="tt-card att-card${c.is_current ? " is-live" : ""}">` +
      // #1471 — each attempt is a season: its banner's texture is seeded by the
      // attempt's own identity (cycle + genesis date → byte-identical forever)
      // #6224: no beads — they counted the attempt number (ADR-157 (5)); the texture keeps its seed.
      `<div class="art-band art-season" aria-hidden="true">${seasonBand(0, { seed: "attempt:" + c.cycle + ":" + (c.genesis || "") })}</div>` +
      `<p class="att-head"><span class="att-no num">${c.is_current ? "The current start" : "A start"}</span> ` +
      `<span class="label">${startName(c)} · showed up ${n(c.engaged_days)} of ${c.is_current && liveDay(c) && liveDay(c) !== c.window_days ? "the first " : ""}${n(c.window_days)} day${c.window_days === 1 ? "" : "s"}</span></p>` +
      `<p class="att-fate">${fateLine(c, collapseDef)}.${changed}</p>` +
      (stats ? `<p class="att-stats label">${stats}</p>` : "") +
      `<p class="att-strip" aria-label="Engagement, day by day">${esc(c.strip || "")}</p>` +
      `</li>`;
  }).join("");
}

async function boot() {
  const [sv, cc] = await Promise.all([J("/api/survival"), J("/api/cycle_compare")]);
  const mount = $("[data-att]");
  if (!mount) return;

  const cycles = (sv && sv.cycles) || [];
  if (!cycles.length) {
    mount.innerHTML = `<p class="dx-prose">The ledger begins with the first attempt's data — nothing to show yet.</p>`;
    return;
  }

  // The hero's one number, data-bound. A start count written into the shell goes
  // stale on the very next re-anchor (it read "Seven" at cycle 15), so the shell
  // ships a neutral, always-true fallback ("Every start, counted") and the live
  // count comes from the same /api/survival record the log below renders from —
  // every start that actually happened, including the live one once it exists.
  // #6224: no count of starts is printed (the shell's "Every start" stands).

  const closed = cycles.filter((c) => !c.is_current);
  const live = cycles.find((c) => c.is_current) || null;
  const prevBest = closed.length ? Math.max(...closed.map(aliveDays)) : null;
  const staged = !live && cc && cc.pre_start;

  const byN = {};
  for (const c of (cc && cc.cycles) || []) byN[c.cycle] = c;

  // #3549: the odds figure is served ONLY once a prior attempt has actually been
  // observed at the horizon. Until then the API serves null and the counts that
  // explain it — "none of 15 attempts reached day 30" is the honest hero, not a
  // percentage manufactured from attempts re-anchored on day 1. Every number in
  // the label is a payload field, so the figure and the log beneath it cannot
  // disagree.
  const horizon = n(sv.horizon_days || 30);
  const oddsFig = sv.p_reach_30_pct != null
    ? `<span class="att-fig-n num">${n(sv.p_reach_30_pct)}%</span>` +
      `<span class="label">odds of day ${horizon} (the forecast's own line · ${n(sv.reached_horizon_n)} of ${n(sv.n_prior_cycles)} attempts reached it` +
      `${Array.isArray(sv.p_reach_30_ci95_pct) ? ` · 95% CI ${n(sv.p_reach_30_ci95_pct[0])}–${n(sv.p_reach_30_ci95_pct[1])}%` : ""})</span>`
    : `<span class="att-fig-n num">—</span>` +
      `<span class="label">odds of day ${horizon} · ${sv.n_prior_cycles != null ? "no earlier start reached it — no odds served" : "not yet handicapped"}</span>`;

  $("[data-att-figs]").innerHTML =
    (live && liveDay(live)
      ? `<div class="att-fig"><span class="att-fig-n num">${n(liveDay(live))}</span><span class="label">day of the current start · since ${startName(live)}</span></div>`
      : staged ? `<div class="att-fig"><span class="att-fig-n num">—</span><span class="label">next start · ${esc(cc.start_date || "")}</span></div>` : "") +
    `<div class="att-fig"><span class="att-fig-n num">${n(prevBest)}</span><span class="label">previous best, days</span></div>` +
    `<div class="att-fig">${oddsFig}</div>`;

  $("[data-att-overlay]").innerHTML = overlaySVG(cycles);
  $("[data-att-log]").innerHTML = logCards(cycles, byN, sv.collapse_definition);
  // #4182 — the post-mortem one-liners live on this page now (the /method/ survival +
  // post-mortem pages left the reader's path): each card's fate line is its post-mortem,
  // and the live start's own served note says why it has none yet.
  const liveNote = $("[data-att-live]");
  // #6224: the served note names the cycle number; the page says the same thing without it.
  if (liveNote) liveNote.textContent = live ? `The current start is still running${liveDay(live) ? ` (day ${n(liveDay(live))})` : ""} — its post-mortem is written once it closes, not before.` : "";
  const method = $("[data-att-method]");
  // #3549: the method AND the confidence line (n, reached) ride together — the
  // method names how censored attempts are treated, the confidence line carries
  // the n the hero figure was computed from.
  // #6224: the served method and confidence lines state the number of earlier starts; only the collapse rule is printed.
  if (method) method.textContent = `Collapse = ${sv.collapse_definition || ""}.`;
  mount.hidden = false;
}

boot();
