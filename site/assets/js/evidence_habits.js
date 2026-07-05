/*
  evidence_habits.js — the habits registry readout + the accountability ledger. Split out
  of evidence.js (#581) — no behavior change.
*/
import { lineChart, correlationChip, sparkline, heatStrip } from "/assets/js/charts.js";
import { esc, tryJSON, has, fmt, ttl, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";

export function renderLedger(d) {
  const t = d.totals || {};
  const bc = d.by_cause || {};
  const head = figs([fig("$" + fmt(t.total_donated_usd), "donated"), fig("$" + fmt(t.total_bounties_usd), "bounties earned"), fig("$" + fmt(t.total_punishments_usd), "punishments"), fig(fmt(t.bounty_count), "bounties")]);
  // Surface the causes the money is routed to — present even at $0 so the page has the
  // human rules + personality (incl. the snake-rescue joke) instead of four bare zeros.
  const causeCard = (c, why) => `<div class="cause-card"><a class="cause-name" href="${esc(c.url || "#")}" target="_blank" rel="noopener">${esc(c.name)}</a>${c.short_description ? `<span class="cause-desc label">${esc(c.short_description)}</span>` : ""}${why && c[why] ? `<p class="cause-why">${esc(c[why])}</p>` : ""}<span class="cause-amt mono">$${fmt(c.total_usd || 0)} · ${fmt(c.count || 0)}×</span></div>`;
  const earned = (bc.earned_causes || []).filter((c) => c && c.name);
  const reluctant = (bc.reluctant_causes || []).filter((c) => c && c.name);
  const earnedSec = earned.length ? sec("Where winnings go", `<div class="cause-grid">${earned.map((c) => causeCard(c, "why_i_care")).join("")}</div>`) : "";
  const reluctantSec = reluctant.length ? sec("Where forfeits go (the ones that sting)", `<div class="cause-grid">${reluctant.map((c) => causeCard(c, "joke_note")).join("")}</div>`) : "";
  return head + earnedSec + reluctantSec + note("Money moved by the accountability rules — skin in the game. Causes shown whether or not money has moved yet.");
}

// §0 keystone hero (P0.1) — THE honesty fix. The old panel showed a bare Pearson (r=0.88,
// n=7) as if proven. Rebuild: lead with the group + direction + STRENGTH word; n is the
// loudest element, stamped "early signal, not proven"; coefficient/chip WITHHELD until >=2
// weeks overlap. Two-voice. Binds keystone_correlations.
export function habitsKeystone(corrs) {
  if (!corrs || !corrs.length) return "";
  const k = corrs[0]; // strongest by |r|
  const n = k.n_days;
  const ready = n >= 14;
  const dir = k.correlation_r >= 0 ? "moves up with" : "moves against";
  const strength = Math.abs(k.correlation_r) >= 0.6 ? "strong" : Math.abs(k.correlation_r) >= 0.3 ? "moderate" : "faint";
  const machine = `${ttl(k.group)} ${dir} the day grade · ${strength} direction · n=${fmt(n)} days — early signal, not proven${ready ? "" : " · coefficient withheld until 2 weeks"}`;
  const serif = `Of everything tracked, ${ttl(k.group)} is the group most pulling the day up so far. On ~${fmt(n)} days that's a lead, not a law — the number to trust here is n, not a coefficient. ${ready ? "It now has the overlap to carry a real correlation, below." : "It earns a real coefficient once there are two weeks of overlap."}`;
  // P2.1 — keystone calibration, honesty-gated. Below 2 weeks of overlap: direction only,
  // no Pearson, no chip (P0.1). At n>=14 the coefficient surfaces inside the sleep board's
  // own confidence-card DNA — n + overlap weeks + a confidence tier + a "likely noise" guard
  // when |r| is small even with the overlap — so the magnitude never reads louder than its n.
  let card = "";
  if (ready) {
    const absr = Math.abs(k.correlation_r);
    const confidence = absr >= 0.6 ? "suggestive · strong" : absr >= 0.3 ? "suggestive · moderate" : "weak — treat as noise";
    const noise = absr < 0.3 ? `<span class="cb-noise">⚠ likely noise at this n — direction only</span>` : "";
    const read = absr < 0.3
      ? `<p class="cb-dir">${esc(dir)} the day grade — direction only, coefficient too weak to trust</p>`
      : `<p class="cb-dir mono">r = ${(Math.round(k.correlation_r * 100) / 100).toFixed(2)}</p>` + correlationChip([{ label: k.group, r: k.correlation_r, n }], { outcome: "the day grade" });
    card = `<div class="cb-grid"><article class="cb-card"><header class="cb-head"><h3 class="cb-pair">${esc(ttl(k.group))} <span class="cb-arrow">→</span> the day grade</h3><span class="cb-tag">${esc(confidence)}</span></header><div class="cb-read">${read}${noise}</div><p class="cb-meta label">n=${fmt(n)} · ${fmt(Math.round((n / 7) * 10) / 10)} wk overlap · N=1, correlative</p></article></div>`;
  }
  return sec("The keystone — one early signal, not a law",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>` + card +
    `<p class="rd-meta label">What would sharpen this: more overlapping days. At ~1 week it's direction-only; the magnitude is withheld until the n is honest. Even past two weeks it stays N=1 and correlative — a card that flags itself as noise when the coefficient is thin.</p>`);
}

// §4 habit state taxonomy (P0.5) — every habit tagged by STATE on ONE ember+ink ramp +
// position/marker (NOT a rainbow). Backlog/never-started SHOWN (most apps hide it). No red.
// P1.1 — auto-derived per-habit context (time-of-day + do/avoid/maintain), rendered as
// small mono tags. Heuristic, name-only inference → always shown under an "auto-derived"
// label, never as fact. "anytime"/"do" are the silent defaults (no tag = no false signal).
export function habitTaxonomyChips(tax) {
  if (!tax) return "";
  const out = [];
  if (tax.time_of_day && tax.time_of_day !== "anytime") out.push(`<span class="hb-tax hb-tax-time">${esc(tax.time_of_day)}</span>`);
  if (tax.type && tax.type !== "do") out.push(`<span class="hb-tax hb-tax-type">${esc(tax.type)}</span>`);
  return out.length ? `<span class="hb-tax-row">${out.join("")}</span>` : "";
}

// P1.2 — friction/difficulty, read from the REAL adherence rate (not inferred): a habit
// you keep ~always is automatic; one you keep rarely is high-friction. Neutral, never red,
// never "you failed" — descriptive. null adherence (backlog/never started) gets no tag.
export function habitFrictionChip(pct) {
  if (pct == null) return "";
  const t = pct >= 85 ? ["automatic", "fr-auto"] : pct >= 60 ? ["takes effort", "fr-mid"] : ["high friction", "fr-hard"];
  return `<span class="hb-fr ${t[1]}">${t[0]}</span>`;
}

// P1.3 — the three drivers behind a habit: trigger → friction → reward. Only friction is
// measured today (it's the inverse of adherence, P1.2). Trigger and reward need a capture
// step that doesn't exist yet — so they're shown as honestly empty, with the mechanism named,
// not faked. An honest empty state IS the build here; a fabricated drivers table would not be.
export function habitsDrivers(perHabit) {
  const ranked = (perHabit || []).filter((h) => h.adherence_pct != null).sort((a, b) => (a.adherence_pct || 0) - (b.adherence_pct || 0)).slice(0, 5);
  const rows = ranked.length
    ? `<table class="rd-tbl rd-drv"><thead><tr><th>habit</th><th>trigger</th><th>friction</th><th>reward</th></tr></thead><tbody>${ranked.map((h) => `<tr><td class="rd-name">${esc(ttl(h.name))}</td><td class="drv-empty">— not captured</td><td>${habitFrictionChip(h.adherence_pct) || "—"}</td><td class="drv-empty">— not captured</td></tr>`).join("")}</tbody></table>`
    : empty("Drivers populate once habits have adherence history.");
  return sec("Drivers — trigger · friction · reward",
    rows + `<p class="rd-meta label">Friction is real — it's the inverse of how often the habit actually gets kept. Trigger (what cues it) and reward (what it pays back) aren't logged yet; they need a per-habit capture step, so they're shown honestly empty rather than guessed. The lowest-adherence habits are listed first — those are where a trigger or reward would move the needle most.</p>`);
}

// P1.4 — misses become narrative. The miss COUNT is real (scheduled − completed); the WHY
// isn't captured, so each miss reason reads honestly empty. Surfacing the count without the
// reason is the honest half-step — it shows where the narrative would attach once a reason
// prompt exists, instead of inventing causes.
export function habitsWhyMissed(perHabit) {
  const missed = (perHabit || [])
    .map((h) => ({ name: h.name, n: Math.max(0, (h.scheduled_days || 0) - (h.completed_days || 0)) }))
    .filter((h) => h.n > 0)
    .sort((a, b) => b.n - a.n)
    .slice(0, 6);
  if (!missed.length) return "";
  const rows = missed.map((h) => `<div class="wm-row"><span class="wm-name">${esc(ttl(h.name))}</span><span class="wm-n mono">${h.n} missed</span><span class="wm-why drv-empty">reason not captured</span></div>`).join("");
  return sec("When a habit slips — the misses, honestly",
    `<div class="wm-list">${rows}</div><p class="rd-meta label">The miss count is real. The <em>reason</em> isn't logged yet — a one-tap "why" on a missed day would turn these counts into narrative (travel, illness, low day). Until that capture exists, the why stays blank rather than guessed. No red, no streak-shaming.</p>`);
}

export function habitStateTaxonomy(perHabit, registryHabits) {
  const byName = {}; for (const h of perHabit || []) byName[h.name] = h;
  const all = (perHabit || []).slice();
  for (const r of registryHabits || []) { if (!byName[r.name]) all.push({ name: r.name, group: r.group || "Other", adherence_pct: null, state: "backlog" }); }
  if (!all.length) return "";
  const STATES = [
    { key: "automatic", label: "Automatic", desc: "high & stable", tone: "st-auto" },
    { key: "holding", label: "Holding", desc: "consistent, lower", tone: "st-hold" },
    { key: "needs_attention", label: "Needs attention", desc: "slipping", tone: "st-need" },
    { key: "backlog", label: "Backlog / never started", desc: "shown, not hidden", tone: "st-backlog" },
  ];
  const lanes = STATES.map((s) => {
    const hs = all.filter((h) => h.state === s.key);
    if (!hs.length) return "";
    const chips = hs.map((h) => `<span class="st-chip ${s.tone}">${esc(ttl(h.name))}${h.adherence_pct != null ? ` <span class="st-pct">${fmt(h.adherence_pct)}%</span>` : ""}</span>`).join("");
    return `<div class="st-lane"><div class="st-lanehead"><span class="st-marker ${s.tone}"></span><span class="st-name">${esc(s.label)}</span><span class="st-desc label">${esc(s.desc)} · ${hs.length}</span></div><div class="st-chips">${chips}</div></div>`;
  }).join("");
  return sec("Habit states — every habit tagged (backlog shown, not hidden)",
    lanes + `<p class="rd-meta label">State is encoded by ember intensity + position, not a rainbow: Automatic = full ember · Holding = ember tint · Needs-attention = muted + marker · Backlog/never-started = outline, honestly empty (most apps hide these). No red, no shame.</p>`);
}

// §5 effort map (P0.6) — ranked dot-strip: dot size = habits the group carries, ember
// saturation = adherence. ONE ember scale + size, NOT a radar (misleading geometry) or rainbow.
export function habitsEffortMap(groupAvgs, registryHabits) {
  const counts = {}; for (const h of registryHabits || []) { const g = h.group || "Other"; counts[g] = (counts[g] || 0) + 1; }
  const items = Object.keys(counts).map((g) => ({ group: g, count: counts[g], pct: groupAvgs[g] != null ? groupAvgs[g] : null }));
  if (!items.length) return "";
  items.sort((a, b) => b.count - a.count);
  const maxCount = Math.max(...items.map((i) => i.count));
  const rows = items.map((i) => {
    const sat = i.pct != null ? Math.max(0.12, i.pct / 100) : 0.12;
    const sz = (12 + (i.count / maxCount) * 24).toFixed(0);
    return `<div class="em-row"><span class="em-dot" style="width:${sz}px;height:${sz}px;--heat:${sat.toFixed(2)}"></span>` +
      `<span class="em-l">${esc(ttl(i.group))}</span><span class="em-meta label">${i.count} habit${i.count > 1 ? "s" : ""}${i.pct != null ? ` · ${fmt(i.pct)}%` : ""}</span></div>`;
  }).join("");
  return sec("Where the effort is",
    `<div class="em-strip">${rows}</div>` +
    `<p class="rd-meta label">Each group: dot size = how many habits it carries, ember intensity = how reliably they're held. One ember scale + size — deliberately a ranked strip, not a radar (misleading geometry) and not a rainbow.</p>`);
}

// §6 per-group trend small-multiples (P0.7) — each group's adherence sparkline. The floor
// groups (Recovery ~14%) render muted (sparkline + label), never red — a not-yet, not a fail.
export function habitsGroupTrends(history, groupAvgs) {
  const series = {};
  for (const day of history || []) {
    for (const [g, p] of Object.entries(day.groups || {})) { if (Number.isFinite(Number(p))) (series[g] = series[g] || []).push(Number(p)); }
  }
  const groups = Object.keys(series).sort((a, b) => (groupAvgs[b] || 0) - (groupAvgs[a] || 0));
  if (!groups.length) return "";
  const cards = groups.map((g) => {
    const vals = series[g], avg = groupAvgs[g];
    const low = avg != null && avg < 40;
    return `<div class="gt-card${low ? " gt-low" : ""}"><div class="gt-head"><span class="gt-name">${esc(ttl(g))}</span><span class="gt-pct mono">${fmt(avg)}%</span></div>${vals.length >= 2 ? sparkline(vals) : `<span class="gt-thin label">fills in</span>`}</div>`;
  }).join("");
  return sec("Per-group trends — the floor and the load-bearing",
    `<div class="gt-grid">${cards}</div>` +
    `<p class="rd-meta label">Each group's adherence over the window. The low ones (Recovery — the floor not yet built) read muted, never red — a not-yet, not a failure.</p>`);
}

// §7 goal linkage (P0.8) — each habit group links UP to the goal/pillar it serves + a
// cross-link to the Evidence page that measures it. Copy-driven.
export const _HABIT_GOAL_LINKS = {
  recovery: { goal: "hold the cut without breaking", link: "/data/sleep/", label: "Sleep" },
  nutrition: { goal: "a deficit you can hold", link: "/data/nutrition/", label: "Nutrition" },
  movement: { goal: "build the engine", link: "/data/training/", label: "Training" },
  fitness: { goal: "build the engine", link: "/data/training/", label: "Training" },
  training: { goal: "build the engine", link: "/data/training/", label: "Training" },
  discipline: { goal: "the consistency pillar — skin in the game", link: "/data/vices/", label: "Vice streaks" },
  mind: { goal: "the inner-life pillar", link: "/data/mind/", label: "Mind" },
  hydration: { goal: "a deficit you can hold", link: "/data/nutrition/", label: "Nutrition" },
  sleep: { goal: "the recovery that protects the cut", link: "/data/sleep/", label: "Sleep" },
};

export function habitsGoalLinkage(groupAvgs) {
  const groups = Object.keys(groupAvgs || {});
  if (!groups.length) return "";
  const rows = groups.map((g) => {
    const m = _HABIT_GOAL_LINKS[g.toLowerCase()];
    return `<tr><td class="rd-name">${esc(ttl(g))}</td><td>${m ? esc(m.goal) : "—"}</td><td>${m ? `<a href="${m.link}">${esc(m.label)} →</a>` : ""}</td></tr>`;
  }).join("");
  return sec("What it's all for — groups → goals",
    `<table class="rd-tbl"><thead><tr><th>habit group</th><th>the goal it serves</th><th>see</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<p class="rd-meta label">P1.5 — each group links out to the page that proves it. The reverse feed (a Nutrition/Sleep/Training day's <em>own</em> completion folding back into this group's score) isn't wired yet — those pages don't expose a single daily-completion signal, so the group rate here stays sourced purely from Habitify rather than double-counting. The cross-link is live; the completion-feed is honestly pending.</p>`);
}

// §8 identity / compliance reflection (P0.9) — atomic-habits framing PINNED to real data
// (the most-automatic habit + its rate), never a mantra. Two-voice.
export function habitsIdentity(perHabit, rate, daysTracked) {
  const auto = (perHabit || []).filter((h) => h.adherence_pct != null).sort((a, b) => b.adherence_pct - a.adherence_pct)[0];
  if (!auto && rate == null) return "";
  const machine = [daysTracked != null && `${fmt(daysTracked)} days tracked`, rate != null && `consistency ${fmt(rate)}%`, auto && `top: ${ttl(auto.name)} ${fmt(auto.adherence_pct)}%`].filter(Boolean).join(" · ");
  const serif = auto
    ? `${fmt(daysTracked)} days in, the most automatic habit is ${ttl(auto.name)} — firing ${fmt(auto.adherence_pct)}% of the days it's due. That one isn't willpower anymore; it's just who shows up. Identity is the set of habits that fire without a decision, and the data says which have crossed over.`
    : `${fmt(daysTracked)} days in at ${fmt(rate)}% consistency — the identity is whatever the heatmap keeps proving, not a slogan.`;
  return sec("Identity — who the data says you are",
    `<div class="two-voice"><p class="tv-machine"><span class="tv-mark">›</span> ${esc(machine)}</p><p class="tv-human">${esc(serif)}</p></div>`);
}

export async function renderHabits(d) {
  const dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const a = d.day_of_week_avgs || [];
  const mx = Math.max(1, ...a);
  const reg = await tryJSON("/api/habit_registry");
  const habits = (reg && reg.habits) || [];
  const groups = (reg && reg.groups) || [];
  // P0.2 — consistency RATE is the north-star; the fragile single streak demotes (honest at 0).
  const _histAll = d.history || [];
  const _held = _histAll.filter((h) => (h.tier0_pct || 0) >= 80).length;
  const _total = _histAll.length;
  const _rate = _total ? Math.round((_held / _total) * 100) : null;
  const head = figs([
    _rate != null && fig(_rate + "%", `consistency · held ${_held}/${_total} days`),
    fig(d.days_tracked ?? 0, "days tracked"),
    habits.length ? fig(habits.length, "habits tracked") : "",
    fig(d.current_streak ?? 0, "current streak"),
  ]) + `<p class="rd-meta label">Consistency rate — how often the non-negotiables get held — is the north-star. The single streak is fragile (one missed day zeroes it), so it's shown honestly but not led with.</p>`;
  const dow = a.length ? sec("Adherence by day of week", `<div class="hb-chart">${a.map((v, i) => `<div class="hb-col"><span class="hb-bar" style="height:${Math.max(4, (v / mx) * 100)}%"></span><span class="hb-day label">${dows[i] || ""}</span></div>`).join("")}</div>`) : "";
  let list = empty("Habit list loading from Habitify.");
  if (habits.length) {
    const order = groups.length ? groups : [...new Set(habits.map((h) => h.group || "Other"))];
    const _perBy = {}; for (const ph of d.per_habit || []) _perBy[ph.name] = ph;
    const body = order.map((g) => { const hs = habits.filter((h) => (h.group || "Other") === g); if (!hs.length) return ""; return `<h4 class="hb-group label">${esc(g)} <span class="rd-unit">${hs.length}</span></h4><table class="rd-tbl"><tbody>${hs.map((h) => `<tr><td class="rd-name">${esc(h.name)}${habitTaxonomyChips(h.taxonomy)}${habitFrictionChip((_perBy[h.name] || {}).adherence_pct)}</td><td class="num rd-range">${esc(h.frequency || "daily")}</td></tr>`).join("")}</tbody></table>`; }).join("");
    list = sec(`Habits I'm tracking (${habits.length})`, body + `<p class="rd-meta label">Time-of-day and do/avoid/maintain are <em>auto-derived</em> from the habit's name (heuristic, not fact). The friction tag is the opposite — read straight from the real adherence rate: kept ~always is automatic, kept rarely is high-friction. Descriptive, not a grade.</p>`);
  }
  // §2 — 90-day adherence heatmap (P0.3). GitHub-style calendar, ember-saturation = the day's
  // Tier-0 %, cut-start (Jun 14) ringed. Replaces the old green/amber/red 7-day grid (rainbow +
  // red, both off-brand) with the ONE-ember heat scale. Reuses heatStrip (compact mode).
  const grid = _histAll.length
    ? sec("90-day adherence heatmap", heatStrip(_histAll, { valueKey: "tier0_pct", unit: "%", max: 100, compact: true, cutDate: "2026-06-14", label: "Daily Tier-0 adherence", caption: "Each square is a day · ember intensity = the non-negotiables held · the ringed square is the cut starting Jun 14 · 90-day history predates the cut." }))
    : "";
  // Adherence trend (the long-run consistency story the 7-cell grid only hinted at).
  const trend = (d.history || []).length ? sec("Adherence trend", lineChart(d.history, { valueKey: "tier0_pct", unit: "%", label: "Daily Tier-0 adherence", spine: true, emptyMsg: "The adherence curve fills as days accrue." })) : "";
  // §0 — keystone hero, honesty-rebuilt (P0.1): leads the page, n-forward, coefficient withheld.
  const keystone = habitsKeystone(d.keystone_correlations);
  // §3 — group grades from adherence RATE (P0.4). Real completion rate → grade (never a
  // correlation). Ember = load-bearing/solid; the floor groups (e.g. Recovery) muted, not red.
  const _gradeOf = (p) => (p >= 90 ? "A" : p >= 80 ? "B" : p >= 70 ? "C" : p >= 50 ? "D" : "F");
  const ga = Object.entries(d.group_90d_avgs || {}).map(([g, p]) => ({ group: g, pct: p })).sort((x, y) => y.pct - x.pct);
  const groupBars = ga.length ? sec("Group grades — what's load-bearing (from adherence rate)",
    `<div class="suf-rows">${ga.map((x) => {
      const tone = x.pct >= 70 ? "suf-ember" : "suf-ink";
      return `<div class="suf-row"><span class="suf-l">${esc(ttl(x.group))}</span><span class="suf-track"><span class="suf-fill ${tone}" style="width:${Math.round(Math.max(0, Math.min(100, x.pct)))}%"></span></span><span class="suf-v mono">${fmt(x.pct)}% · ${_gradeOf(x.pct)}</span></div>`;
    }).join("")}</div>` +
    `<p class="rd-meta label">Each grade is the group's real adherence RATE over the window — never a correlation. Higher = load-bearing; the low ones (the floor, like Recovery) read muted, not as failure. Tier-0 non-negotiables drive the heatmap above.</p>`) : "";
  const states = habitStateTaxonomy(d.per_habit, habits);
  const effort = habitsEffortMap(d.group_90d_avgs || {}, habits);
  const drivers = habitsDrivers(d.per_habit);
  const whymiss = habitsWhyMissed(d.per_habit);
  const gtrends = habitsGroupTrends(d.history, d.group_90d_avgs || {});
  const goals = habitsGoalLinkage(d.group_90d_avgs || {});
  const identity = habitsIdentity(d.per_habit, _rate, d.days_tracked);
  return keystone + head + grid + identity + groupBars + states + effort + drivers + whymiss + gtrends + goals + trend + dow + list + note("Everything I'm trying to do — sourced from Habitify. Correlations are N=1, not cause. Private habits are never shown.");
}
