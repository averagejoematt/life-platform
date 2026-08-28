/*
  evidence_autonomic.js — two computed-view readouts on the Data door (#414, RQA-06/07):
    renderAutonomic  → /data/autonomic/ from /api/autonomic_balance (the 4-quadrant
                       nervous-system model: Flow / Stress / Recovery / Burnout)
    renderZone2      → /data/zone2/     from /api/zone2 (weekly Zone-2 minutes vs the
                       150-min/week reference + the full 5-zone distribution)

  Both are DISTINCT from the vitals hero (which draws the raw strain-vs-recovery 2×2).
  Reuses existing charts.js primitives (targetSpine, barChart, sparkline) — never edits
  them. Honest empty states: below-threshold data renders an explicit "not enough yet",
  never a fabricated value, and captions frame patterns as observation, not cause.
*/
import { targetSpine, barChart, sparkline } from "/assets/js/charts.js";
import { esc, fmt, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";

// ── Autonomic balance (RQA-06) ────────────────────────────────────────────────

const _Q_ORDER = ["FLOW", "STRESS", "RECOVERY", "BURNOUT"];

// The 2×2 as plain HTML — energy axis (HRV Z, vertical) × valence axis (recovery
// signals, horizontal). The current cell is lit; every cell shows its 7-day count so
// the reader sees the spread, not just today. Deliberately NOT the strain/recovery SVG
// on the vitals page — this is the computed Z-scored view.
function _quadrantGrid(cur, dist, meta) {
  const cell = (q) => {
    const m = (meta && meta[q]) || {};
    const n = (dist && dist[q]) || 0;
    const on = cur && cur.quadrant === q;
    return `<div class="aqg-cell${on ? " is-current" : ""}">` +
      `<span class="aqg-name">${esc(m.label || q)}</span>` +
      `<span class="aqg-n label">${n} of last 7</span>` +
      (on ? `<span class="aqg-here label">where the body sat today</span>` : "") +
      `</div>`;
  };
  // Grid order: Recovery (low energy/good) · Flow (high energy/good) on top row;
  // Burnout (low/poor) · Stress (high/poor) below — energy rises left→right isn't
  // meaningful in a 2-col grid, so we simply label each cell.
  return `<div class="aqg" role="img" aria-label="Autonomic 2 by 2: Flow, Stress, Recovery, Burnout — the current state highlighted.">` +
    `${cell("RECOVERY")}${cell("FLOW")}${cell("BURNOUT")}${cell("STRESS")}</div>`;
}

export function renderAutonomic(d) {
  if (!d || d.available === false) {
    const reason = (d && d.reason) || "Not enough recovery data yet to place the nervous system on the quadrant.";
    return empty(reason);
  }
  const cur = d.current_state || {};
  const trend = d.seven_day_trend || {};
  const daily = Array.isArray(d.daily_states) ? d.daily_states : [];
  const meta = d.quadrants || {};
  const parts = [];

  // Altitude 1 — the current state, in words + the balance number.
  parts.push(sec("Where the nervous system is sitting",
    figs([
      fig(esc(cur.label || cur.quadrant || "—"), "state" + (cur.days_in_state > 1 ? ` · ${cur.days_in_state}d` : "")),
      fig(cur.balance_score != null ? cur.balance_score : "—", "balance · 0–100"),
    ]) +
    (cur.blurb ? `<p class="rd-prose">${esc(cur.blurb)}</p>` : "") +
    note("A read of where recovery and strain signals have left the autonomic system — an observation, not a diagnosis.")));

  // Altitude 2 — the 2×2 + the trailing-7-day distribution.
  const dist = trend.state_distribution || {};
  parts.push(sec("The last week, across the quadrant",
    _quadrantGrid(cur, dist, meta) +
    `<p class="rd-meta label">Each day of the trailing week placed in one of four states, Z-scored against your own baseline over the window. Dominant lately: <strong>${esc((meta[trend.dominant_state] || {}).label || trend.dominant_state || "—")}</strong>${trend.avg_balance_score != null ? `, average balance ${fmt(trend.avg_balance_score, 0)}` : ""}. A snapshot of the spread — no trajectory claimed at this n.</p>`));

  // Altitude 3 — the balance-score trace (sparkline reuse; refuses <2 points itself).
  const scores = daily.map((s) => Number(s.balance_score)).filter((v) => Number.isFinite(v));
  if (scores.length >= 2) {
    const lo = daily[0].date, hi = daily[daily.length - 1].date;
    parts.push(sec("Balance score over the window",
      `<div class="aq-spark">${sparkline(scores)}</div>` +
      `<p class="rd-meta label">The 0–100 balance score (50 = neutral; Flow lifts it, Burnout pulls it down) across ${daily.length} days, ${esc(String(lo).slice(5))} → ${esc(String(hi).slice(5))}. Read the shape, not any single morning.</p>`));
  }

  if (d.methodology) {
    parts.push(sec("How it's computed", `<p class="rd-meta label">${esc(d.methodology)}</p>`));
  }
  return parts.join("");
}

// ── Zone-2 breakdown (RQA-07) ──────────────────────────────────────────────────

const _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// #3286 — a Zone-2 tally with no date on it is what let a ten-day-old week render as
// "this week". Every week the panel draws now wears its range.
//
// Formatted from the STRING parts, never `new Date("2026-08-24")`: a bare YYYY-MM-DD is
// parsed as UTC midnight, and rendering that through a Pacific locale prints the PREVIOUS
// day. That is the same "a date pushed through a clock that isn't its own" defect this
// panel is being fixed for — it would be absurd to reintroduce it in the label.
export function weekRange(w) {
  const start = w && w.week_start ? String(w.week_start).slice(0, 10) : "";
  const end = w && w.week_end ? String(w.week_end).slice(0, 10) : "";
  const part = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return null;
    return { mon: _MONTHS[Number(m[2]) - 1] || m[2], day: String(Number(m[3])) };
  };
  const a = part(start), b = part(end);
  if (!a) return start || "—";
  if (!b) return `${a.mon} ${a.day}`;
  return a.mon === b.mon ? `${a.mon} ${a.day}–${b.day}` : `${a.mon} ${a.day} – ${b.mon} ${b.day}`;
}

export function renderZone2(d) {
  if (!d || d.available === false) {
    const reason = (d && d.reason) || "No qualifying cardio activity yet — Zone-2 time fills in as sessions with heart-rate land.";
    return empty(reason);
  }
  const target = Number(d.weekly_target_min) || 150;
  const cur = d.current_week || null;
  const weeks = Array.isArray(d.weeks) ? d.weeks : [];
  const dist = Array.isArray(d.zone_distribution) ? d.zone_distribution : [];
  const sports = Array.isArray(d.sport_breakdown) ? d.sport_breakdown : [];
  const s = d.summary || {};
  const parts = [];

  // Altitude 1 — this week vs the 150-min reference (targetSpine reuse).
  //
  // #3286 — the panel used to render `current_week` as "this week" with NO date anywhere
  // on it, while the endpoint's `current_week` was `weeks[-1]`: the last week that had
  // activity. On 2026-08-27 that was the week of 08-17 — ten days old — published as
  // "this week" beside a sibling endpoint reporting trailing-7d Zone-2 of zero. The API
  // now serves the real calendar week (an explicit dated zero when nothing qualified);
  // this renders its RANGE unconditionally, so a tally can never again be read as a week
  // it does not belong to, and names the last active week rather than hiding it.
  if (cur) {
    const range = weekRange(cur);
    const zeroWeek = cur.no_activity_recorded === true;
    const last = d.latest_active_week || null;
    const gap = Number(cur.days_since_activity);
    const lastNote = (zeroWeek && last)
      ? ` The most recent week with a qualifying session was <strong>${esc(weekRange(last))}</strong> — ${fmt(last.zone_2_minutes, 0)} min.`
      : "";
    const darkNote = (zeroWeek && cur.source_last_activity)
      ? ` Nothing has qualified since <strong>${esc(cur.source_last_activity)}</strong>${Number.isFinite(gap) ? ` (${gap} day${gap === 1 ? "" : "s"})` : ""} — a measured zero, not a missing read.`
      : "";
    parts.push(sec(`This week (${range}) vs the 150-minute reference`,
      targetSpine(cur.zone_2_minutes, target, { valueLabel: range, targetLabel: "150 min", unit: " min", label: "Zone-2 aerobic minutes" }) +
      `<p class="rd-meta label">The week-so-far Zone-2 tally for the current calendar week, <strong>${esc(range)}</strong>, against the widely-cited 150 min/week aerobic reference (Attia · Huberman · WHO).${darkNote}${lastNote} Zone 2 is ${esc(s.zone_2_hr_range || "—")} for a max HR of ${fmt(s.max_hr_used, 0)}. A reference line, not a prescription.</p>`));
  }

  // Altitude 2 — weekly Zone-2 minutes (barChart reuse).
  if (weeks.length) {
    const items = weeks.map((w) => ({ label: String(w.week_start).slice(5), value: w.zone_2_minutes }));
    parts.push(sec("Zone-2 minutes by week",
      barChart(items, { valueKey: "value", labelKey: "label", label: "Zone-2 min / week" }) +
      // #3286: `weeks` holds only the weeks that HAD qualifying activity — a blank week is
      // absent from this chart, not a zero bar. Said out loud so the last bar is never read
      // as "the current week" the way `current_week` used to be.
      `<p class="rd-meta label">Weeks with at least one qualifying session (a blank week is absent, not a zero bar). ${s.weeks_meeting_target || 0} of ${s.weeks_analyzed || weeks.length} weeks hit the 150-min mark (${fmt(s.target_hit_rate_pct, 0)}%); the window averages ${fmt(s.avg_weekly_zone_2_min, 0)} min/week.${d.trend ? ` Direction is <strong>${esc(d.trend.direction)}</strong> (${fmt(d.trend.first_half_avg_min, 0)} → ${fmt(d.trend.second_half_avg_min, 0)} min).` : ""}</p>`));
  }

  // Altitude 3 — the full 5-zone distribution + Zone-2 sport mix, as honest tables.
  if (dist.some((z) => z.total_minutes > 0)) {
    const rows = dist.map((z) =>
      `<div class="zdist-row"><span class="zdist-l">${esc(z.label)}</span>` +
      `<span class="zdist-track"><span class="zdist-fill${z.zone === "zone_2" ? " is-z2" : ""}" style="width:${Math.max(0, Math.min(100, z.pct_of_training))}%"></span></span>` +
      `<span class="zdist-v mono">${fmt(z.total_minutes, 0)} min · ${fmt(z.pct_of_training, 0)}%</span></div>`).join("");
    parts.push(sec("Full zone distribution",
      `<div class="zdist">${rows}</div>` +
      `<p class="rd-meta label">Where the cardio time actually landed across all five HR zones over the window — total ${fmt(s.total_zone_2_min, 0)} min in Zone 2 across ${s.total_activities || 0} sessions. Most people undertrain Zone 2 relative to the higher zones.</p>`));
  }
  if (sports.length) {
    const rows = sports.map((sp) =>
      `<li><span class="label">${esc(sp.sport_type)}</span> <span class="mono">${fmt(sp.zone_2_minutes, 0)} min · ${sp.activity_count}×</span></li>`).join("");
    parts.push(sec("Zone-2 by sport", `<ul class="zsport">${rows}</ul>`));
  }
  return parts.join("");
}
