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

function fateLine(c, collapseDef) {
  if (c.is_current) return `live — day ${n(c.window_days)}`;
  if (c.collapse_day) return `collapsed on day ${n(c.collapse_day)} — ${esc(collapseDef || "engagement went silent")}`;
  return "re-anchored while still engaged — an administrative reset, not a collapse";
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
    return `<text class="att-label" x="${PADL - 8}" y="${y + 4}" text-anchor="end">#${esc(String(c.cycle))} · ${esc(c.genesis)}</text>${bar}${end}`;
  }).join("");

  const legend =
    `<text class="att-tick" x="${PADL}" y="${PADT - 14}">every attempt, aligned at day 1 — × collapsed · ↺ re-anchored · ▶ live</text>`;

  return `<svg class="att-svg" viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid meet" ` +
    `aria-label="All attempts overlaid on the same day axis">${axis}${legend}${rows}</svg>`;
}

/* ── the expedition log ────────────────────────────────────────────────── */
function logCards(cycles, byN, collapseDef) {
  return cycles.slice().reverse().map((c) => {
    const m = byN[c.cycle] || {};
    const next = cycles.find((x) => x.cycle === c.cycle + 1);
    const changed = c.is_current ? "" : next
      ? ` What changed: restarted ${esc(next.genesis)} as attempt #${n(next.cycle)}.`
      : "";
    const stats = [
      m.weight_delta_lbs != null ? `weight ${m.weight_delta_lbs > 0 ? "+" : ""}${n(m.weight_delta_lbs)} lb in the window` : null,
      m.avg_recovery_pct != null ? `avg recovery ${n(m.avg_recovery_pct)}%` : null,
      m.avg_sleep_hours != null ? `avg sleep ${n(m.avg_sleep_hours)}h` : null,
    ].filter(Boolean).join(" · ");
    return `<li class="tt-card att-card${c.is_current ? " is-live" : ""}">` +
      `<p class="att-head"><span class="att-no num">Attempt #${n(c.cycle)}</span> ` +
      `<span class="label">${esc(c.genesis)} · showed up ${n(c.engaged_days)} of ${n(c.window_days)} day${c.window_days === 1 ? "" : "s"}</span></p>` +
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

  const closed = cycles.filter((c) => !c.is_current);
  const live = cycles.find((c) => c.is_current) || null;
  const maxCycle = Math.max(...cycles.map((c) => c.cycle));
  // The attempt number: the live cycle if the record has one, else the staged
  // next cycle from /api/cycle_compare (pre-start), else the last recorded.
  const attemptNo = live ? live.cycle : (cc && cc.current_cycle) || maxCycle;
  const prevBest = closed.length ? Math.max(...closed.map(aliveDays)) : null;
  const staged = !live && cc && cc.pre_start;

  const byN = {};
  for (const c of (cc && cc.cycles) || []) byN[c.cycle] = c;

  $("[data-att-figs]").innerHTML =
    `<div class="att-fig"><span class="att-fig-n num">${n(attemptNo)}</span><span class="label">attempt${staged ? ` · arms ${esc(cc.start_date || "")}` : live ? ` · day ${n(live.window_days)}` : ""}</span></div>` +
    `<div class="att-fig"><span class="att-fig-n num">${n(prevBest)}</span><span class="label">previous best, days</span></div>` +
    `<div class="att-fig"><span class="att-fig-n num">${sv.p_reach_30_pct != null ? n(sv.p_reach_30_pct) + "%" : "—"}</span><span class="label">odds of day ${n(sv.horizon_days || 30)} (model's own line)</span></div>`;

  $("[data-att-overlay]").innerHTML = overlaySVG(cycles);
  $("[data-att-log]").innerHTML = logCards(cycles, byN, sv.collapse_definition);
  const method = $("[data-att-method]");
  if (method) method.textContent = `${sv.method || ""} Collapse = ${sv.collapse_definition || ""}.`;
  mount.hidden = false;
}

boot();
