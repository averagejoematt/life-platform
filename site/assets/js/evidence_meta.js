/*
  evidence_meta.js — the board of coaches + the platform/cost/data/tools/inference/pipeline
  meta pages (the /method/ build-transparency family), plus Ask + Explorer + the generic
  fallback renderer. Split out of evidence.js (#581) — no behavior change.
*/
import { sigil } from "/assets/js/sigils.js";
import { portrait } from "/assets/js/portraits.js";
import { esc, tryJSON, isBad, fmt, ttl, fig, figs, sec, empty, note, kvtable } from "/assets/js/evidence_shared.js";
import { lineChart } from "/assets/js/charts.js";

// The board — pick an expert, read their actual per-domain take + track record.
// WQA-06 — surface the cross-coach DISAGREEMENTS (the moat), not eight parallel monologues.
// Reads /api/coach_team tensions: topic + the two coaches' positions head-to-head + the
// board lead's call. Interpretation, never alarm; ember on the verdict. The lead is named
// by the API from config/personas.json (#1986) — never spelled out in this file.
export function boardDisagreements(tensions) {
  const ts = (tensions || []).filter((t) => t && (t.position_a || t.position_b));
  if (!ts.length) return "";
  const pretty = (id) => ttl(String(id || "").replace(/_coach$/, "").replace(/_/g, " ")) || "Coach";
  const strip = (txt) => String(txt || "").replace(/^[A-Za-z'’ .]{1,40}:\s*/, "");
  const cards = ts.map((t) => {
    const [a, b] = t.coaches || [];
    return `<article class="dis-card"><h4 class="dis-topic">${esc(t.topic || "An open disagreement")}</h4>` +
      `<div class="dis-cols">` +
      `<div class="dis-pos"><span class="dis-who label">${esc(pretty(a))}</span><p class="dis-text">${esc(strip(t.position_a))}</p></div>` +
      `<div class="dis-vs" aria-hidden="true">vs</div>` +
      `<div class="dis-pos"><span class="dis-who label">${esc(pretty(b))}</span><p class="dis-text">${esc(strip(t.position_b))}</p></div>` +
      `</div>` +
      (t.resolution ? `<div class="dis-call"><span class="dis-call-k label">the integrator's call</span><p class="dis-text">${esc(t.resolution)}</p></div>` : "") +
      `</article>`;
  }).join("");
  return sec("Where the coaches disagree — the argument, not the consensus",
    `<div class="dis-grid">${cards}</div>` +
    `<p class="rd-meta label">The moat isn't eight assistants nodding along — it's that they don't, and the disagreement is surfaced instead of averaged away. Each is an AI persona arguing from its own discipline; the board lead adjudicates, but the tension is the point. Interpretation of the data, never an instruction.</p>`);
}

export async function renderBoard(d) {
  const coaches = d.coaches || []; const wp = d.weekly_priority || {};
  const team = await tryJSON("/api/coach_team");
  const disagreements = boardDisagreements(team && team.tensions);
  const chair = wp.text && !isBad(wp.text)
    ? `<div class="rd-obs"><p class="board-kicker label">the integrator's weekly read · ${esc(wp.coach_name || "")}</p><p class="rd-primary">${esc(wp.text)}</p></div>`
    : `<div class="rd-obs"><p class="rd-primary">The board's weekly read posts after the next briefing.</p></div>`;
  const roster = coaches.length
    ? `<div class="coach-grid">${coaches.map((c) => `<button class="coach coach-pick" data-coach="${esc(c.coach_id)}" data-name="${esc(c.name)}" data-title="${esc(c.title || "")}" style="--coach:${/^#|rgb/.test(c.color || "") ? c.color : "var(--ember)"}"><span class="coach-badge">${portrait(c, { title: "", size: 24 }) || sigil(c, { title: "" })}<span class="sr-only">${esc(c.initials || (c.name || "?").slice(0, 2))}</span></span><div><h3 class="coach-name">${esc(c.name)}</h3><p class="coach-title label">${esc(c.title || "")}</p></div></button>`).join("")}</div>`
    : empty("The expert board is being assembled.");
  return chair + disagreements + sec("The experts — pick one to read their take", roster) +
    `<div class="coach-read" data-board-read></div>` +
    note("A board of named AI characters who each read the data differently. Interpretation, not instruction.");
}

export function renderPlatform(d) { return figs([fig(d.data_sources, "data sources (incl. derived)"), fig(d.mcp_tools, "MCP tools"), fig(d.lambdas, "lambdas"), fig(d.cdk_stacks, "CDK stacks")]) + sec("By the numbers", kvtable({ adrs: d.adrs, review_grade: d.review_grade, site_pages: d.site_pages })) + note("Built with the wearables already on his body — not a million-dollar lab. The full architecture (alarms, tests, the deeper counts) lives in the build write-up; this page keeps the human-legible ones."); }

/* The ceiling is the platform's most-quoted number, and this function used to hand-type
   it three times — once in the figure and twice in the prose (base and surge). That is
   how the page went on quoting a retired ceiling for weeks after the base moved, and it
   was stale AGAIN on the day #2898 landed: the ADR-133 dated raise window had lifted the
   live base and this file had not heard about it. A number no reader can see going stale
   is a number that will.
   It now reads the governor's own envelope off /api/receipts (base_ceiling_usd /
   surge_ceiling_usd / ceiling_window — site_api_budget._ceiling_envelope), the same
   payload /method/receipts/ renders. ADR-104 omit-when-stale, exactly like renderReceipts
   below: when the governor's breakdown is missing or stale the dollar figures are LEFT OUT
   and the gap is stated, never frozen at a last-known value.
   tests/test_budget_ceiling_registry_2898.py fails if any current ceiling figure comes
   back as a literal anywhere under site/ — including here. The ADR-063 original stays,
   because it is dated history and no longer a figure the governor owns. */
export async function renderCost(d) {
  const r = await tryJSON("/api/receipts");
  const live = r && !r.stale && r.base_ceiling_usd != null ? r : null;
  const base = live ? `$${fmt(live.base_ceiling_usd)}` : null;
  const surge = live && live.surge_ceiling_usd != null ? `$${fmt(live.surge_ceiling_usd)}` : null;
  const w = (live && live.ceiling_window) || null;
  const windowClause = w && w.end_exclusive && w.reverts_to_base_ceiling != null
    ? ` That base is a dated raise; it reverts to $${fmt(w.reverts_to_base_ceiling)} on ${esc(String(w.end_exclusive))}, on its own.`
    : "";
  const provenance = "(ADR-063 set the original $75; ADR-133 owns the current number)";
  const ceilingProse = base
    ? `against a self-imposed hard ceiling — ${base} base${surge ? `, floating to ${surge} only in reader-traffic surge mode` : ""} ${provenance}.${windowClause}`
    : `against a self-imposed hard ceiling ${provenance}. The current figure is deliberately blank: the budget governor's last projection is unavailable or stale, and a cost page that quietly freezes a number is worse than one that admits the gap.`;
  // The run-rate is omitted rather than defaulted for the same ADR-104 reason: the old
  // `|| "$20"` fallback printed a figure nobody had measured whenever the feed was down.
  // It is also used VERBATIM: the served string already carries its own "$" and its own
  // approximation marker ("~$80"), and the old `"$" + …replace("$","")` round-trip
  // re-prefixed the marker instead of the digits — the live page reads "$~80" today.
  const spend = isBad(d.monthly_cost) ? "" : String(d.monthly_cost).trim();
  const spendPhrase = spend ? `runs for ${esc(spend)}/month` : "runs on a monthly cost the platform-stats feed isn't reporting right now —";
  return figs([spend && fig(spend, "per month"), base && fig(base, "hard ceiling (ADR-133)")]) +
    `<p class="rd-archive">The whole platform ${spendPhrase} ${ceilingProse} Radical accessibility is the point: an ordinary person did this with a model and consumer wearables, not a lab.</p>` +
    note("Cost is the receipt for 'you could do this too.'");
}

export function renderData(d) { const src = d.sources || []; if (!src.length) return empty("Data-source registry unavailable."); const by = {}; for (const s of src) (by[s.category || "other"] ||= []).push(s); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><tbody>${rows.map((s) => `<tr><td class="rd-name">${esc(s.name)}</td><td>${esc(s.metrics || "")}</td><td class="rd-range">${esc(s.method || "")}</td></tr>`).join("")}</tbody></table>`)).join(""); return figs([fig(src.length, "sources catalogued")]) + secs + note(`The full catalogue (live + manual + derived). The Pipeline page shows which are actively monitored right now${d._meta && d._meta.updated ? ` · updated ${esc(d._meta.updated)}` : ""}.`); }
/* ── PG-14 Tier-A: "the data figure" ──────────────────────────────────────────
   A faceless, monochrome body silhouette whose girth is a *direct function* of
   the real weight number (start → current → goal). No photo, no face, nothing
   generated or guessed — it moves only when the measured number moves. Honest
   (Henning standard), privacy-safe, on-brand. Productionised from spikes/pg14_ai_me
   (PG-14, ADR-078 Wedge-B). Fill = var(--ink) so it adapts to light/dark. */

export function renderTools(d) { return figs([fig(d.mcp_tools ?? "—", "MCP tools"), fig(d.data_sources ?? "—", "data sources")]) + `<p class="rd-archive">The tools Claude uses to read this data back — spanning sleep, training, nutrition, labs, CGM, the character sheet, the board, correlations and more. They're how a conversation with the data is possible at all.</p>` + note("The interface between the model and the measured life."); }

// The inference receipt — every AI call priced, the meter behind the budget ceiling (ADR-133 owns the number).
export function renderInference(d) {
  const head = figs([
    d.ai_month_to_date_usd != null && fig(`$${fmt(d.ai_month_to_date_usd)}`, "AI spend MTD"),
    fig(`$${fmt(d.budget_ceiling_usd)}`, "hard ceiling (all-in)"),
    d.budget_tier != null && fig(String(d.budget_tier), "budget tier (0–3)"),
  ]);
  const mrows = (d.models || []).map((m) =>
    `<tr><td class="rd-name">${esc(m.model)}</td><td class="num">${fmt(m.today.input_tokens)} / ${fmt(m.today.output_tokens)}</td><td class="num">$${fmt(m.today.est_cost_usd)}</td><td class="num">${fmt(m.month.input_tokens)} / ${fmt(m.month.output_tokens)}</td><td class="num">$${fmt(m.month.est_cost_usd)}</td></tr>`).join("");
  const models = mrows ? sec("By model", `<table class="rd-tbl"><thead><tr><th>model</th><th>today in/out</th><th>today $</th><th>month in/out</th><th>month $</th></tr></thead><tbody>${mrows}</tbody></table>`) : "";
  const frows = (d.features || []).slice(0, 14).map((f) =>
    `<tr><td class="rd-name">${esc(f.lambda)}</td><td class="num">${fmt(f.month_input_tokens)}</td><td class="num">${fmt(f.month_output_tokens)}</td></tr>`).join("");
  const features = frows ? sec("By feature (month-to-date tokens)", `<table class="rd-tbl"><thead><tr><th>lambda</th><th>input</th><th>output</th></tr></thead><tbody>${frows}</tbody></table>`) : "";
  return head + models + features + `<p class="correlative">${esc(d.note || "")}</p>`;
}

/* The Glass Engine (#1397) — the budget envelope as an instrument.
   /method/inference/ prices the AI calls; this page shows the ceiling around them,
   where the month is projected to land, and what the current tier has switched off.
   Honesty contract (ADR-104): when the governor's breakdown is missing or stale the
   dollar figures are OMITTED and the reason is stated — never frozen at a last-known
   value, because a silently stale cost page is worse than an absent one. */
const TIER_BANDS = ["0 · normal", "1 · caution", "2 · restrict", "3 · hard stop"];

export function renderReceipts(d) {
  if (!d || typeof d !== "object") return empty("Receipts unavailable.");

  // Tier + what it actually pauses reads from SSM independently of the dollar
  // figures, so it stays truthful even when the breakdown is stale.
  const tier = d.tier;
  const tierBlock = tier == null ? "" : sec("What is paused right now",
    `<div class="rcp-gauge" role="img" aria-label="Budget tier ${esc(String(tier))} of 3">` +
    TIER_BANDS.map((b, i) => `<span class="rcp-band${i === tier ? " is-on" : ""}${i < tier ? " is-past" : ""}">${esc(b)}</span>`).join("") +
    `</div><p class="rd-archive">${esc(d.tier_semantics || "")}</p>`);

  // The stale state needs this MORE than the healthy one, not less: "how stale?" is the
  // reader's first question, and computed_at is the only thing that answers it concretely.
  // When stale, the TIMESTAMP goes inside the emphasized span too — the date is the part
  // that answers the question, so leaving it faint would emphasise the wrong half.
  const provDate = d.computed_at ? ` · last run ${esc(String(d.computed_at).slice(0, 16).replace("T", " "))} UTC` : "";
  const prov = d.stale
    ? `<p class="provenance"><span class="pv-src pv-stale">computed every 8h by cost_governor${provDate}</span></p>`
    : `<p class="provenance"><span class="pv-src">computed every 8h by cost_governor</span>${provDate}</p>`;

  if (d.stale) {
    return figs([tier != null && fig(String(tier), "budget tier (0–3)")].filter(Boolean)) + tierBlock +
      empty(`The spend figures aren't current: ${esc(d.stale_reason || "the budget breakdown is unavailable")}. ` +
        "They're deliberately left blank rather than shown at their last-known value — a cost page that quietly freezes is worse than one that admits the gap.") +
      prov +
      note("The governor reprojects every 8 hours; this page fills in on its next run.");
  }

  const pct = d.projected_pct_of_ceiling;
  const head = figs([
    d.month_to_date_usd != null && fig(`$${fmt(d.month_to_date_usd)}`, "spent this month", d.mtd_pct_of_ceiling != null ? `${fmt(d.mtd_pct_of_ceiling)}% of ceiling` : null),
    d.projected_month_end_usd != null && fig(`$${fmt(d.projected_month_end_usd)}`, "projected month-end", pct != null ? `${fmt(pct)}% of ceiling` : null),
    d.ceiling_usd != null && fig(`$${fmt(d.ceiling_usd)}`, d.surge_active ? "ceiling (surge mode)" : "hard ceiling (all-in)"),
    tier != null && fig(String(tier), "budget tier (0–3)"),
  ].filter(Boolean));

  // #1618 — extend the curve past today with a dashed projection to month-end, anchored on
  // the governor's projected_month_end_usd (NOT re-extrapolated in JS — a second projection
  // that disagreed with the governor is the exact defect this avoids). When the projection is
  // absent (stale/null breakdown) `proj` is null and only the solid actual line renders.
  const proj = (d.projected_month_end_usd != null && d.month_end_date)
    ? { value: d.projected_month_end_usd, date: d.month_end_date, label: "projected" }
    : null;
  const curveChart = (d.history || []).length
    ? lineChart(d.history, { valueKey: "mtd_usd", dateKey: "date", unit: "", label: "month-to-date spend · UTC billing days", goal: d.ceiling_usd, projection: proj, emptyMsg: "The spend curve draws in as the month accrues." })
    : "";
  // ADR-105: the dashed line is a forecast, not a measurement — say so in prose, not just the
  // caption, so a reader can never mistake the projected continuation for recorded spend.
  const curveNote = (proj && curveChart)
    ? `<p class="rd-archive">The solid line is what has actually been spent this month; the dashed line is the governor's projection to month-end — $${fmt(d.projected_month_end_usd)}, an estimate it re-runs every 8 hours, not a measured value (ADR-105). AWS bills on UTC days, so late in a Pacific evening the curve can already show a point for a day that hasn't finished here.</p>`
    : "";
  const curve = curveChart
    ? sec(proj ? "The month so far — and where it's heading" : "The month so far", curveChart + curveNote)
    : "";

  // Hand-built rather than kvtable(): kvtable title-cases its keys via ttl(), which
  // renders `ai_per_day` as "Ai Per Day" — wrong for AI, and title case is off-register
  // for a site whose labels are lowercase throughout.
  const split = (d.ai_daily_usd != null || d.non_ai_daily_usd != null)
    ? sec("Daily run rate", `<table class="rd-tbl"><tbody>` +
      `<tr><td class="rd-name">AI, per day</td><td class="num">${d.ai_daily_usd != null ? `$${fmt(d.ai_daily_usd)}` : "—"}</td></tr>` +
      `<tr><td class="rd-name">infrastructure, per day</td><td class="num">${d.non_ai_daily_usd != null ? `$${fmt(d.non_ai_daily_usd)}` : "—"}</td></tr>` +
      `</tbody></table>`)
    : "";

  // A projection ABOVE the ceiling is the single most important thing this page can
  // say, and in the figure row it renders in the same faint `.rd-delta` as a benign
  // "74% of ceiling" — no cue that one of them is a breach. State it in prose.
  const breach = (pct != null && pct > 100)
    ? `<p class="rd-archive"><b>Projected to finish the month over the ceiling</b> — $${fmt(d.projected_month_end_usd)} against $${fmt(d.ceiling_usd)} (${fmt(pct)}%). ` +
      `The tier ladder above is the response: features switch off as the projection climbs, which is what pulls the real figure back under.</p>`
    : "";

  const surge = d.surge_active
    ? `<p class="rd-archive">Surge mode is active: the ceiling floats from $${fmt(d.base_ceiling_usd)} to $${fmt(d.ceiling_usd)} while reader traffic stays above ${esc(fmt(d.surge_threshold_uniques))} unique visitors over 7 days (currently ${esc(fmt(d.recent_uniques))}) — ADR-133.</p>`
    : "";

  // #1999 — a dated ceiling window used to render as an unexplained gap between the
  // base figure and the one in effect. The governor now names the window in the payload;
  // this states it. Entirely absent when no window is active (the normal case).
  const w = d.ceiling_window;
  const window_ = (w && w.start && w.end_exclusive && w.base_ceiling != null)
    ? `<p class="rd-archive">The base ceiling is temporarily $${fmt(w.base_ceiling)} rather than the usual $${fmt(w.reverts_to_base_ceiling)}, ` +
      `under a dated window running ${esc(String(w.start))} until ${esc(String(w.end_exclusive))}${w.reason ? ` — ${esc(String(w.reason))}` : "."}</p>`
    : "";

  const feat = d.per_feature_note
    ? `<p class="correlative">${esc(d.per_feature_note)} <a href="/method/inference/">See the per-model receipt →</a></p>`
    : "";

  return head + breach + tierBlock + surge + window_ + curve + split + feat + prov +
    `<p class="correlative">${esc(d.note || "")}</p>`;
}

export function renderGeneric(d, t) { const root = (t && t.root && d[t.root]) ? d[t.root] : d; const scal = Object.entries(root).filter(([k, v]) => !k.startsWith("_") && ["string", "number", "boolean"].includes(typeof v)); let arr = null, key = null; for (const [k, v] of Object.entries(root)) if (Array.isArray(v) && v.length && typeof v[0] === "object") { arr = v; key = k; break; } let tbl = ""; if (arr) { const cols = [...new Set(arr.flatMap((r) => Object.keys(r)))].filter((c) => !c.startsWith("_")).slice(0, 5); tbl = sec(key, `<table class="rd-tbl"><thead><tr>${cols.map((c) => `<th>${esc(ttl(c))}</th>`).join("")}</tr></thead><tbody>${arr.slice(0, 40).map((r) => `<tr>${cols.map((c) => `<td class="num">${esc(fmt(r[c]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`); } if (!scal.length && !tbl) return empty("No data published for this section yet — it fills from the live pipeline."); return figs(scal.slice(0, 4).map(([k, v]) => fig(fmt(v), ttl(k)))) + tbl + note("Correlative read only."); }

/* Interactive: Ask the data + Explorer (wired after insert) */

export const ASK_CHIPS = [
  "How's the sleep trending lately?",
  "What predicts good recovery days?",
  "Is the weight loss on track?",
  "What foods spike the glucose most?",
  "Any signs of overtraining?",
  "What changed in the data this week?",
];

export function renderAsk() {
  // The widget itself is the shared module (assets/js/ask.js) — mounted by WIRE.ask
  // so Home and this archive render the SAME experience. The container is all we emit.
  return `<div data-ask-mount></div>`;
}

export function renderExplorer(d) { const v = (d.vitals && d.vitals.vitals) || d.vitals || {}; const ch = (d.character && d.character.character) || {}; const j = (d.journey && d.journey.journey) || d.journey || {}; const rows = { weight_lbs: j.current_weight_lbs, character_level: ch.level, ...Object.fromEntries(Object.entries(v).filter(([k, x]) => ["string", "number"].includes(typeof x)).slice(0, 12)) }; return `<p class="rd-archive">Today's raw record, straight from the pipeline — the unfiltered daily snapshot the rest of the site is built from.</p>` + sec("Today", kvtable(rows)) + note("The unfiltered daily record."); }

/* #735 — /verify/: make "the data is real" independently checkable. Three parts:
   (1) cross-device agreement (the disagreement IS the credibility — synthetic
       numbers don't misbehave the way two real sensors do), (2) public device-
       profile cross-links (honest "not yet linked" states — never invent a URL),
       (3) a privacy-filtered raw-payload sample. Endpoint: /api/device_agreement
       (lambdas/web/site_api_data.py::handle_device_agreement). */
function verifyDeviceLinks() {
  // No confirmed public-profile URLs exist for these accounts yet — this section
  // states that honestly rather than guessing a username/URL. Whoever picks this
  // up next: drop the real public URL in the href below (and drop the "not yet
  // linked" wording) once Matthew confirms it; Whoop has no public-profile
  // feature at all, so its row explains the cross-check instead of a dead link.
  const rows = [
    ["Whoop", "No public profile pages exist on Whoop's platform — its HRV/RHR readings are instead cross-checked against Garmin's independent sensor above."],
    ["Strava", "Not yet linked publicly. <!-- TODO(#735): Matthew's public Strava athlete profile URL, if training is shared publicly -->"],
    ["Hevy", "Not yet linked publicly. <!-- TODO(#735): Matthew's public Hevy profile URL, if lifting sessions are shared publicly -->"],
    ["Garmin Connect", "Not yet linked publicly (ingestion has also been paused since 2026-06, ADR-074 — vendor anti-automation). <!-- TODO(#735): public Garmin Connect profile URL, if enabled -->"],
  ];
  return sec("Public device profiles", `<p class="rd-prose">The devices behind this data, and whether their own platforms let a stranger check them directly. No links are invented — a row says "not yet linked" until a real, confirmed public URL exists.</p>` +
    `<ul class="rd-tierlist">${rows.map(([name, text]) => `<li><strong>${esc(name)}</strong> — ${text}</li>`).join("")}</ul>`);
}

function verifyRawSample() {
  // One real day (2026-06-15), both sensors, straight from DynamoDB — partition/sort
  // keys (pk/sk, which carry the internal user-id shape) stripped; every remaining
  // field is exactly what the ingestion pipeline wrote, unedited.
  const whoop = { source: "whoop", date: "2026-06-15", phase: "experiment", ingested_at: "2026-06-15T23:00:41.814388+00:00", resting_heart_rate: 61, hrv: 42.34, recovery_score: 76, sleep_duration_hours: 10.4, sleep_efficiency_percentage: 96.74, respiratory_rate: 13.3, strain: 3.56 };
  const garmin = { source: "garmin", date: "2026-06-15", phase: "experiment", ingested_at: "2026-06-16T00:00:17.374875+00:00", resting_heart_rate: 56, training_readiness: 79, training_readiness_level: "HIGH", body_battery_end: 84, avg_stress: 17, steps: 298 };
  return sec("A raw payload, identifiers stripped", `<p class="rd-prose">One real night (June 15), as both devices actually reported it — the same night the table above compares. Partition/sort keys (the internal row-id shape) are removed; every other field is untouched.</p>` +
    `<pre class="rd-code">// Whoop — DATE#2026-06-15\n${esc(JSON.stringify(whoop, null, 2))}</pre>` +
    `<pre class="rd-code">// Garmin — DATE#2026-06-15\n${esc(JSON.stringify(garmin, null, 2))}</pre>` +
    `<p class="rd-meta label">The 61 vs 56 bpm resting-heart-rate reading above is row one of the comparison table — a real 5bpm sensor disagreement, not a rounding artifact.</p>`);
}

export function renderVerify(d) {
  const links = verifyDeviceLinks();
  const sample = verifyRawSample();
  const methodLink = `<p class="rd-archive">Every statistic this platform publishes — its exact formula, the window it runs over, what it can't tell you — is documented at <a href="/method/registry/">the Methods Registry</a>, generated straight from the code, not hand-written. The devices behind these readings — what each measures and where to get it — are on <a href="/gear/">the gear page</a> (kept separate from this page's honesty checks on purpose).</p>`;
  if (!d || d.status === "unavailable") {
    return sec("Cross-device agreement — the credibility signal", empty(d && d.reason ? d.reason : "No overlapping device data recorded yet.")) + links + sample + methodLink + note("Nothing here is fabricated to fill a gap — an empty section says so.");
  }
  const rhr = d.rhr_agreement;
  const headFigs = figs([
    d.period && fig(d.period.overlapping_days, "nights both devices recorded"),
    d.combined_agreement_rate_pct != null && fig(d.combined_agreement_rate_pct + "%", "agreement rate"),
    rhr && fig(rhr.flagged_days, "nights flagged (RHR diff >6bpm)"),
  ]);
  const rows = (d.daily || []).slice(0, 30).map((r) => {
    const flagged = r.rhr_agreement === "flag" || r.hrv_agreement === "flag";
    return `<tr class="${flagged ? "rd-flag" : ""}"><td class="rd-name">${esc(r.date)}</td><td class="num">${r.whoop_rhr_bpm != null ? fmt(r.whoop_rhr_bpm) : "—"}</td><td class="num">${r.garmin_rhr_bpm != null ? fmt(r.garmin_rhr_bpm) : "—"}</td><td class="num">${r.rhr_abs_diff_bpm != null ? fmt(r.rhr_abs_diff_bpm) : "—"}</td><td>${esc(r.rhr_agreement || "—")}</td></tr>`;
  }).join("");
  // #2957: the table's own caption now bounds the window it's actually showing —
  // whatever the pause note says, a bare "night by night" table with no dates in
  // its heading reads as live to a skimming reader. `archival` (the producer's own
  // site_api_phase_frame.archival_frame call, off the window's newest night) adds
  // the same "previous cycle" framing every other cross-phase surface uses.
  const period = d.period ? ` — ${esc(d.period.start)} to ${esc(d.period.end)}` : "";
  const table = rows ? sec(`Whoop vs Garmin, night by night (resting heart rate, bpm)${period}`, `<table class="rd-tbl"><thead><tr><th>date</th><th>Whoop</th><th>Garmin</th><th>diff</th><th>agreement</th></tr></thead><tbody>${rows}</tbody></table>`) : "";
  const pausedNote = d.garmin_paused ? `<p class="rd-meta label">Garmin ingestion has been paused since ${esc(d.garmin_last_date)} (vendor anti-automation, ADR-074) — the window above is real history through that date, not a live feed.</p>` : "";
  const archivalNote = d.archival && d.archival.pre_cycle
    ? `<p class="rd-meta label">${esc(d.archival.label)} — the comparison window itself, not only the Garmin pause.</p>`
    : "";
  const agreeDays = rhr ? rhr.agree_days : 0, minorDays = rhr ? rhr.minor_days : 0, flagDays = rhr ? rhr.flagged_days : 0;
  return sec("Cross-device agreement — the credibility signal", headFigs +
      `<p class="rd-prose">Whoop and Garmin are two independently-made sensors, worn the same nights, that were never designed to talk to each other. Across every overlapping night on record: ${esc(agreeDays)} agreed within 3bpm, ${esc(minorDays)} were within 6bpm, and ${esc(flagDays)} disagreed enough to flag. That specific, correlated-but-imperfect pattern is what two real pieces of hardware produce — synthetic or copy-pasted numbers don't misbehave this particular way.</p>` +
      pausedNote + archivalNote) +
    table + links + sample + methodLink +
    note(d.interpretation || "Cross-device HRV/RHR comparison, thresholded from real inter-device variance — not a claim either sensor is 'right.'");
}

export function renderPipeline(d) {
  const src = d.sources || [];
  if (!src.length) return empty("Pipeline status unavailable — check back shortly.");
  const sm = d.summary || {};
  const rank = { fresh: 0, "behavioral-stale": 1, stale: 2, unknown: 3, paused: 4 };
  const badge = { fresh: "● flowing", "behavioral-stale": "○ awaiting log", stale: "▲ stale", paused: "⏸ paused", unknown: "– unknown" };
  const flagCls = (s) => (s === "stale" || s === "unknown") ? "rd-flag" : "";
  // #589: the documented-but-until-now-unadopted .provenance kit (DESIGN_SYSTEM_V5 —
  // "every number says where it came from and how fresh") gets its first real use here.
  // The dot pulses ONLY while data-fresh-ts/-window (this source's OWN registry-derived
  // window, from /api/source_freshness) are inside range; non-fresh statuses fall
  // through to the existing motionless .pv-stale — never a decorative loop either way.
  const lastUpdateCell = (s) => {
    const freshAttrs = (s.last_update_ts && s.stale_hours != null)
      ? ` data-fresh-ts="${esc(s.last_update_ts)}" data-fresh-window="${Math.round(Number(s.stale_hours) * 3600)}"`
      : "";
    // #2798: state the FRAME where the date is shown. last_update is a stored DATE# day
    // key — a UTC calendar day for the near-real-time sources (TD-19 Phase 2) — and UTC
    // rolls over at 5pm Pacific, so between 5pm and midnight PT a source that has just
    // delivered reads one day ahead of this Pacific-framed page. The server proves the
    // frame per row and hands us the Pacific day; the client must NOT re-derive either
    // from the browser clock, which is not Pacific for most readers. An ahead-of-PT date
    // with no proven UTC frame is a real anomaly and is flagged, never explained away.
    const frame = s.last_update_frame === "utc" ? ` <span class="rd-unit">UTC</span>` : "";
    const ahead = (s.last_update_ahead_of_pt && s.last_update_frame !== "utc")
      ? ` <span class="rd-badge">ahead of today</span>` : "";
    return `<p class="provenance${s.status !== "fresh" ? " pv-stale" : ""}"><span class="fr-dot"${freshAttrs} aria-hidden="true"></span>` +
      `<span class="pv-src">${esc(s.last_update || "—")}</span>${frame}${ahead}${s.age_hours != null ? ` <span class="rd-unit">${Math.round(s.age_hours)}h</span>` : ""}</p>`;
  };
  // #746: honest degraded stamp for a manual source (HAE / Notion / MCP) gone
  // quiet past its threshold — "manual source dark N days", the same behavioral-
  // absence honesty (ADR-104) a device gap gets. Never fabricated: days_dark is a
  // real count from /api/source_freshness, only present on a stale manual source.
  const statusCell = (s) => {
    let txt = badge[s.status] || s.status;
    if (s.manual && s.days_dark != null && s.days_dark > 0) txt += ` · dark ${s.days_dark}d`;
    let html = esc(txt);
    // #1371/#2002: cross-cycle provenance — this source's newest record predates
    // the current genesis, so its age is carried history from an earlier attempt,
    // not a live-cycle outage. Numbered server-side from the record's date against
    // the cycle-genesis ledger (no stamp dependency); null = predates cycle 1.
    if (s.carried) {
      const from = s.carried_from_cycle != null ? `attempt ${esc(String(s.carried_from_cycle))}` : "a previous attempt";
      html += ` <span class="rd-badge wu-carried">carried from ${from}</span>`;
    }
    return html;
  };
  // #746: apple_health is one partition fed by many streams; a dark hand-captured
  // stream (CGM/BP/State of Mind/water) is surfaced explicitly so a "fresh"
  // partition can't hide it. Passive device streams (steps/workouts) are labelled
  // as such — the nudge can't fix those, and honesty says which is which.
  const feedsCell = (s) => {
    let html = esc(s.desc || "");
    const dark = s.dark_datatypes || [];
    if (dark.length) {
      // #2001: days_dark is now numeric even for months-long lapses (the checker
      // deep-scans past its window); days_dark_floor is the honest ">Nd" bound for
      // a stream with no record inside even the deep horizon (ADR-104).
      const darkTxt = (d) => (d.days_dark != null ? ` dark ${d.days_dark}d` : d.days_dark_floor != null ? ` dark >${d.days_dark_floor}d` : " dark");
      const parts = dark.map((d) => `${esc(d.label)}${darkTxt(d)}${d.manual ? "" : " (device)"}`);
      html += `<span class="rd-meta label" style="display:block">${parts.join(" · ")}</span>`;
    }
    return html;
  };
  const by = {};
  for (const s of src) (by[s.category || "Other"] ||= []).push(s);
  const secs = Object.entries(by).map(([cat, rows]) => sec(cat,
    `<table class="rd-tbl"><thead><tr><th>source</th><th>what it feeds</th><th>last update</th><th>status</th></tr></thead><tbody>${rows
      .slice().sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9))
      .map((s) => `<tr class="${flagCls(s.status)}"><td class="rd-name">${esc(s.label)}</td><td>${feedsCell(s)}</td><td class="num rd-range">${lastUpdateCell(s)}</td><td>${statusCell(s)}</td></tr>`).join("")}</tbody></table>`)).join("");
  const carriedNote = (d.experiment && src.some((s) => s.carried))
    ? ` carried = the newest record predates this cycle's genesis (${esc(d.experiment.genesis || "")}) — history from an earlier attempt, not a live outage.`
    : "";
  // #2798: the frame, explained in-page the moment it can be seen. Without this a reader
  // between 5pm and midnight Pacific sees a "last update" one day ahead of the date this
  // page says it is, with nothing on the page accounting for it — which is what the
  // reader-truth judge (correctly) read as a future date. Shown only when a row is
  // actually ahead, so the other 17 hours of the day carry no extra copy.
  const frameNote = src.some((s) => s.last_update_ahead_of_pt)
    ? ` Day keys are stored in UTC, which rolls over at 5pm Pacific — so between 5pm and midnight Pacific a source that has just delivered reads one UTC day ahead of this page's Pacific date${d.pacific_today ? ` (${esc(d.pacific_today)})` : ""}. The hours-since figure is a duration and is unaffected.`
    : "";
  return figs([fig(sm.fresh ?? "—", "flowing"), fig(sm.paused ?? "—", "paused"), fig(sm.total ?? src.length, "live-monitored")]) + secs +
    `<p class="correlative">Live pipeline status — fresh = flowing on schedule, paused = intentionally off, awaiting-log = a manual entry not yet made, dark Nd = a manual source quiet that many days.${carriedNote}${frameNote}</p>`;
}
