/*
  evidence_meta.js — the board of coaches + the platform/cost/data/tools/inference/pipeline
  meta pages (the /method/ build-transparency family), plus Ask + Explorer + the generic
  fallback renderer. Split out of evidence.js (#581) — no behavior change.
*/
import { sigil } from "/assets/js/sigils.js";
import { portrait } from "/assets/js/portraits.js";
import { esc, tryJSON, isBad, fmt, ttl, fig, figs, sec, empty, note, kvtable } from "/assets/js/evidence_shared.js";

// The board — pick an expert, read their actual per-domain take + track record.
// WQA-06 — surface the cross-coach DISAGREEMENTS (the moat), not eight parallel monologues.
// Reads /api/coach_team tensions: topic + the two coaches' positions head-to-head + the
// integrator's (Coach Nakamura's) call. Interpretation, never alarm; ember on the verdict.
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
    `<p class="rd-meta label">The moat isn't eight assistants nodding along — it's that they don't, and the disagreement is surfaced instead of averaged away. Each is an AI persona arguing from its own discipline; the integrator (Coach Nakamura) adjudicates, but the tension is the point. Interpretation of the data, never an instruction.</p>`);
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

export function renderPlatform(d) { return figs([fig(d.data_sources, "data sources (incl. derived)"), fig(d.mcp_tools, "MCP tools"), fig(d.lambdas, "lambdas"), fig(d.cdk_stacks, "CDK stacks")]) + sec("By the numbers", kvtable({ adrs: d.adrs, review_grade: d.review_grade, site_pages: d.site_pages })) + note("Built with Claude + the wearables already on his body — not a million-dollar lab. The full architecture (alarms, tests, the deeper counts) lives in the build write-up; this page keeps the human-legible ones."); }

export function renderCost(d) { return figs([fig("$" + String(d.monthly_cost || "").replace("$", ""), "per month"), fig("$75", "hard ceiling")]) + `<p class="rd-archive">The whole platform runs for about ${esc(d.monthly_cost || "$20")}/month against a self-imposed $75 hard ceiling (ADR-063). Radical accessibility is the point: an ordinary person did this with a model and consumer wearables, not a lab.</p>` + note("Cost is the receipt for 'you could do this too.'"); }

export function renderData(d) { const src = d.sources || []; if (!src.length) return empty("Data-source registry unavailable."); const by = {}; for (const s of src) (by[s.category || "other"] ||= []).push(s); const secs = Object.entries(by).map(([cat, rows]) => sec(cat, `<table class="rd-tbl"><tbody>${rows.map((s) => `<tr><td class="rd-name">${esc(s.name)}</td><td>${esc(s.metrics || "")}</td><td class="rd-range">${esc(s.method || "")}</td></tr>`).join("")}</tbody></table>`)).join(""); return figs([fig(src.length, "sources catalogued")]) + secs + note(`The full catalogue (live + manual + derived). The Pipeline page shows which are actively monitored right now${d._meta && d._meta.updated ? ` · updated ${esc(d._meta.updated)}` : ""}.`); }
/* ── PG-14 Tier-A: "the data figure" ──────────────────────────────────────────
   A faceless, monochrome body silhouette whose girth is a *direct function* of
   the real weight number (start → current → goal). No photo, no face, nothing
   generated or guessed — it moves only when the measured number moves. Honest
   (Henning standard), privacy-safe, on-brand. Productionised from spikes/pg14_ai_me
   (PG-14, ADR-078 Wedge-B). Fill = var(--ink) so it adapts to light/dark. */

export function renderTools(d) { return figs([fig(d.mcp_tools ?? "—", "MCP tools"), fig(d.data_sources ?? "—", "data sources")]) + `<p class="rd-archive">The tools Claude uses to read this data back — spanning sleep, training, nutrition, labs, CGM, the character sheet, the board, correlations and more. They're how a conversation with the data is possible at all.</p>` + note("The interface between the model and the measured life."); }

// The inference receipt — every AI call priced, the meter behind the $75 cap.
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

export function renderExplorer(d) { const v = (d.vitals && d.vitals.vitals) || d.vitals || {}; const ch = (d.character && d.character.character) || {}; const j = (d.journey && d.journey.journey) || d.journey || {}; const rows = { weight_lbs: j.current_weight_lbs, character_level: ch.level, ...Object.fromEntries(Object.entries(v).filter(([k, x]) => ["string", "number"].includes(typeof x)).slice(0, 12)) }; return `<p class="rd-archive">Today's raw record, straight from the pipeline. For the full historical day-by-day browser, open the preserved Explorer below.</p>` + sec("Today", kvtable(rows)) + note("The unfiltered daily record."); }

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
  const methodLink = `<p class="rd-archive">Every statistic this platform publishes — its exact formula, the window it runs over, what it can't tell you — is documented at <a href="/method/registry/">the Methods Registry</a>, generated straight from the code, not hand-written.</p>`;
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
  const table = rows ? sec("Whoop vs Garmin, night by night (resting heart rate, bpm)", `<table class="rd-tbl"><thead><tr><th>date</th><th>Whoop</th><th>Garmin</th><th>diff</th><th>agreement</th></tr></thead><tbody>${rows}</tbody></table>`) : "";
  const pausedNote = d.garmin_paused ? `<p class="rd-meta label">Garmin ingestion has been paused since ${esc(d.garmin_last_date)} (vendor anti-automation, ADR-074) — the window above is real history through that date, not a live feed.</p>` : "";
  const agreeDays = rhr ? rhr.agree_days : 0, minorDays = rhr ? rhr.minor_days : 0, flagDays = rhr ? rhr.flagged_days : 0;
  return sec("Cross-device agreement — the credibility signal", headFigs +
      `<p class="rd-prose">Whoop and Garmin are two independently-made sensors, worn the same nights, that were never designed to talk to each other. Across every overlapping night on record: ${esc(agreeDays)} agreed within 3bpm, ${esc(minorDays)} were within 6bpm, and ${esc(flagDays)} disagreed enough to flag. That specific, correlated-but-imperfect pattern is what two real pieces of hardware produce — synthetic or copy-pasted numbers don't misbehave this particular way.</p>` +
      pausedNote) +
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
    return `<p class="provenance${s.status !== "fresh" ? " pv-stale" : ""}"><span class="fr-dot"${freshAttrs} aria-hidden="true"></span>` +
      `<span class="pv-src">${esc(s.last_update || "—")}</span>${s.age_hours != null ? ` <span class="rd-unit">${Math.round(s.age_hours)}h</span>` : ""}</p>`;
  };
  // #746: honest degraded stamp for a manual source (HAE / Notion / MCP) gone
  // quiet past its threshold — "manual source dark N days", the same behavioral-
  // absence honesty (ADR-104) a device gap gets. Never fabricated: days_dark is a
  // real count from /api/source_freshness, only present on a stale manual source.
  const statusCell = (s) => {
    let txt = badge[s.status] || s.status;
    if (s.manual && s.days_dark != null && s.days_dark > 0) txt += ` · dark ${s.days_dark}d`;
    return esc(txt);
  };
  // #746: apple_health is one partition fed by many streams; a dark hand-captured
  // stream (CGM/BP/State of Mind/water) is surfaced explicitly so a "fresh"
  // partition can't hide it. Passive device streams (steps/workouts) are labelled
  // as such — the nudge can't fix those, and honesty says which is which.
  const feedsCell = (s) => {
    let html = esc(s.desc || "");
    const dark = s.dark_datatypes || [];
    if (dark.length) {
      const parts = dark.map((d) => `${esc(d.label)}${d.days_dark != null ? ` dark ${d.days_dark}d` : " dark"}${d.manual ? "" : " (device)"}`);
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
  return figs([fig(sm.fresh ?? "—", "flowing"), fig(sm.paused ?? "—", "paused"), fig(sm.total ?? src.length, "live-monitored")]) + secs +
    `<p class="correlative">Live pipeline status — fresh = flowing on schedule, paused = intentionally off, awaiting-log = a manual entry not yet made, dark Nd = a manual source quiet that many days.</p>`;
}
