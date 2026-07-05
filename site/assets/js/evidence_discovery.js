/*
  evidence_discovery.js — discoveries/hypotheses, the genome, challenges, protocols and
  experiments (the /protocols/ door). Split out of evidence.js (#581) — no behavior change.
*/
import { dumbbell } from "/assets/js/charts.js";
import { domainIcon, icon } from "/assets/js/icons.js";
import { esc, tryJSON, isBad, has, fmt, ttl, fig, figs, sec, empty, note, evClass, kvtable } from "/assets/js/evidence_shared.js";

// One machine-bet card: domains + status badge in the header, the falsifiable
// statement as the body, the verdict trail once graded, the founding evidence
// collapsed behind a details toggle (it's long — 4-5 cited sentences).
// Status → badge: confirmed earns ember (a live confirmed signal); refuted stays
// muted ink (down is never red); pending/confirming are plain machine labels.
export function hypCard(h) {
  const status = String(h.status || "pending");
  const badgeCls = status === "confirmed" ? "rd-badge rd-badge-live" : "rd-badge";
  const domains = (h.domains || []).map(esc).join(" ↔ ") || "cross-domain";
  const checks = Math.round(Number(h.check_count) || 0);
  const formed = h.created_at ? String(h.created_at).slice(0, 10) : null;
  const preReg = h.pre_registered_at ? String(h.pre_registered_at).slice(0, 10) : formed;
  const checked = h.last_checked ? String(h.last_checked).slice(0, 10) : null;
  const decided = status === "confirmed" || status === "refuted";
  const meta = [
    h.confidence && `confidence ${h.confidence}`,
    checks === 0 ? "not yet checked" : `${checks} check${checks === 1 ? "" : "s"}`,
    // #530: pre-registration is the honesty claim — the criterion predates the grading data
    preReg && (h.test_spec ? `pre-registered ${preReg}` : `formed ${preReg}`),
    checked && `last checked ${checked}`,
  ].filter(Boolean).join("  ·  ");
  // #530 (engine v2): the frozen deterministic criterion + the measured effect.
  // Rendered from the spec fields only — nothing invented client-side.
  let spec = "";
  if (h.test_spec && h.test_spec.condition_metric) {
    const s = h.test_spec;
    const cond = s.condition_op === "median_split" ? `${s.condition_metric} above its median` : `${s.condition_metric} ${s.condition_op} ${s.condition_threshold}`;
    const lag = Math.round(Number(s.lag_days) || 0);
    spec = `<p class="rd-line"><span class="label">frozen test</span> ${esc(s.outcome_metric)} ${esc(s.direction || "")}${lag ? ` ${lag}d after` : " on"} ${esc(cond)} days</p>`;
  }
  let measured = "";
  if (h.effect_size != null && h.ci95_low != null) {
    measured = `<p class="rd-line"><span class="label">measured</span> effect ${h.effect_size > 0 ? "+" : ""}${esc(h.effect_size)} (95% CI ${esc(h.ci95_low)} to ${esc(h.ci95_high)}, n=${esc(h.n_condition ?? "—")}/${esc(h.n_comparison ?? "—")} days)</p>`;
  }
  const verdict = h.last_evidence
    ? `<p class="rd-why hyp-verdict"><span class="label">${decided ? "the verdict" : "latest check"} — </span>${esc(h.last_evidence)}</p>`
    : "";
  const founding = h.evidence && typeof h.evidence === "string"
    ? `<details class="hyp-ev"><summary class="label">the data behind it</summary><p class="rd-why">${esc(h.evidence)}</p></details>`
    : "";
  return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${domains}</h3><span class="${badgeCls}">${esc(status)}</span></header>` +
    `<p class="rd-why">${esc(h.hypothesis || "")}</p>${spec}${measured}${verdict}${founding}<p class="rd-meta label">${esc(meta)}</p></article>`;
}

export async function renderDiscoveries(d) {
  // Real discoveries first: ai_findings = FDR-significant correlations computed from
  // Matt's own data (the API computed these but the page never rendered them — it showed
  // only library hypothesis templates, which read as placeholder). Hypotheses now last,
  // reframed "under test". Empty state names the small-n reality honestly.
  const findings = d.ai_findings || [],
    inner = d.inner_life || [],
    hyp = d.active_hypotheses || [];
  const card = (t, b, badge) =>
    `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(t)}</h3>${badge ? `<span class="rd-badge">${esc(badge)}</span>` : ""}</header>${b ? `<p class="rd-why">${esc(b)}</p>` : ""}</article>`;
  const fs = findings.length
    ? sec("Correlations found in the data", `<div class="rd-cards">${findings.map((f) => card(f.title, f.body, f.n ? `n=${f.n}` : "")).join("")}</div>`)
    : "";
  const is = inner.length ? sec("Inner-life findings", `<div class="rd-cards">${inner.map((f) => card(f.title, f.body, f.confidence)).join("")}</div>`) : "";
  // What the machine suspects — the hypothesis engine's REAL live bets
  // (/api/hypotheses: formed from the data, re-checked every Sunday, graded
  // confirmed/refuted or expired). The static library templates remain the
  // fallback for the empty windows (30-day hard expiry / post-reset).
  const live = await tryJSON("/api/hypotheses");
  const all = (live && live.hypotheses) || [];
  const bets = all.filter((h) => h.status !== "archived");
  const expired = all.length - bets.length;
  const unchecked = bets.length > 0 && bets.every((h) => !Math.round(Number(h.check_count) || 0));
  let hs;
  if (bets.length) {
    const intro = `<p class="rd-meta label">Falsifiable bets the engine formed from the data — re-checked every Sunday. A bet gets confirmed, refuted, or expires undecided; all three are shown.${unchecked ? " None checked yet — the first weekly check is upcoming." : ""}</p>`;
    const expiredNote = expired ? `<p class="rd-meta label">${expired} earlier bet${expired === 1 ? "" : "s"} expired before the data could decide ${expired === 1 ? "it" : "them"} — shown as the honest cost of betting in public.</p>` : "";
    hs = sec("What the machine suspects", intro + `<div class="rd-cards">${bets.map(hypCard).join("")}</div>` + expiredNote);
  } else {
    hs = hyp.length
      ? sec("Hypotheses under test", `<div class="rd-cards">${hyp.map((h) => card(h.name, h.hypothesis || h.description, h.evidence_tier)).join("")}</div>`)
      : "";
  }
  if (!fs && !is && !hs)
    return empty("No discoveries yet — real correlations and findings surface here as the data accrues. This cycle is only days old, so it needs more data first.");
  return fs + is + hs + note("Correlative leads, not conclusions — N=1, FDR-corrected where computed, and n is small this early in the cycle.");
}

export function renderGenome(d) { const g = d.genome || d; const rs = g.risk_summary || {}; const cats = g.categories || {}; const head = figs([g.total_snps != null && fig(fmt(g.total_snps), "SNPs analysed"), rs.unfavorable != null && fig(rs.unfavorable, "unfavorable"), rs.favorable != null && fig(rs.favorable, "favorable")]); const cs = Object.keys(cats).length ? sec("Risk by category", kvtable(cats)) : ""; if (!head.includes("fig-v") && !cs) return empty("Genome not yet published."); return head + cs + note("Genotype is predisposition, not destiny — context for the biomarkers."); }

export async function renderChallenges(d) {
  const cur = await tryJSON("/api/current_challenge");
  const cc = cur && cur.current_challenge;
  const list = d.challenges || [];
  const sm = d.summary || {};
  const banner = cc && cc.challenge ? `<div class="rd-obs"><p class="rd-primary">${esc(cc.challenge)}</p>${cc.detail ? `<p class="rd-why">${esc(cc.detail)}</p>` : ""}<p class="rd-meta label">day ${esc(cc.days_complete ?? 0)} of ${esc(cc.days_total ?? "—")}</p></div>` : "";
  const live = list.filter((c) => c.origin === "live");
  const avail = list.filter((c) => c.origin === "catalog" && c.status === "available");
  const backlog = list.filter((c) => c.origin === "catalog" && c.status === "backlog");
  const head = figs([fig(sm.active ?? live.length, "active"), fig(avail.length + backlog.length, "in the backlog")]);
  // P2.2 — the live card draws its served-but-never-drawn record: the check-in
  // streak grid (one cell per day of the run: checked-in = ember, checked-but-
  // missed = faint, ahead = outline) + the progress figs. Real cells only —
  // the grid renders exactly what was logged, gaps stay gaps.
  const checkinGrid = (c) => {
    const dur = Number((c.progress || {}).duration_days || c.duration_days) || 0;
    const checks = c.daily_checkins;
    if (!dur || !checks || typeof checks !== "object") return "";
    const entries = Array.isArray(checks) ? checks : Object.entries(checks).map(([date, v]) => ({ date, completed: v === true || (v && v.completed) }));
    const byDate = new Map(entries.map((e) => [String(e.date).slice(0, 10), !!(e.completed ?? e.done ?? e.success ?? true)]));
    const start = c.activated_at || c.start_date;
    if (!start) return "";
    const t0 = Date.parse(String(start).slice(0, 10) + "T12:00:00");
    if (!Number.isFinite(t0)) return "";
    const cells = Array.from({ length: Math.min(dur, 60) }, (_, i) => {
      const dd = new Date(t0 + i * 86400000).toISOString().slice(0, 10);
      const v = byDate.get(dd);
      const cls = v === true ? "is-done" : v === false ? "is-miss" : "";
      return `<i class="cg-cell ${cls}" title="${esc(dd)}${v === true ? " · done" : v === false ? " · missed" : ""}"></i>`;
    }).join("");
    return `<div class="cg" role="img" aria-label="Daily check-ins, ${dur} days">${cells}</div>`;
  };
  const liveCard = (c) => {
    const done = !!c.completed_at || c.status === "completed";
    const active = !done && (c.status === "active" || !!c.activated_at);
    const pr = c.progress || {};
    const progFigs = active && pr.duration_days
      ? `<p class="rd-meta label">${[pr.checkin_days != null && `${pr.checkin_days}/${pr.duration_days} days checked in`, pr.completion_pct != null && `${fmt(pr.completion_pct)}% complete`, pr.success_rate != null && `${fmt(pr.success_rate)}% success`].filter(Boolean).join("  ·  ")}</p>`
      : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(c.name || ttl(c.challenge_id || "Challenge"))}</h3><span class="rd-badge ${active ? "rd-badge-live" : ""}">${done ? "completed" : active ? "active" : "candidate"}</span></header>${checkinGrid(c)}${progFigs}<p class="rd-meta label">${[c.character_xp_awarded != null && c.character_xp_awarded + " XP", c.badge_earned && `${icon("milestone")} badge`].filter(Boolean).join("  ·  ")}</p></article>`;
  };
  // P2.2 — catalog cards carry their evidence: the summary, the tier chip, and
  // the recommending board persona. The served `icon` field is emoji — never drawn (§8).
  const catCard = (c) => {
    const [tc, tl] = c.evidence_tier ? evClass(c.evidence_tier) : [null, null];
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${c.category ? `<span class="ch-ric">${domainIcon(c.category)}</span>` : ""}${esc(c.name)}</h3><span class="rd-badge">${esc(c.status)}</span></header>${c.one_liner ? `<p class="rd-why">${esc(c.one_liner)}</p>` : ""}${c.evidence_summary && !isBad(c.evidence_summary) ? `<p class="rd-line">${esc(c.evidence_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${[c.category, c.difficulty, c.duration_days && c.duration_days + "d", c.board_recommender && "recommended by " + c.board_recommender].filter(Boolean).map(esc).join("  ·  ")}</p></article>`;
  };
  const liveSec = sec("Taken on", live.length ? `<div class="rd-cards">${live.map(liveCard).join("")}</div>` : empty("None taken on yet this cycle."));
  // "Available now" vs "Backlog" was a distinction without a difference — both are
  // catalog ideas not yet taken on. One backlog.
  const candidates = avail.concat(backlog);
  const backSec = candidates.length ? sec(`Backlog (${candidates.length})`, `<div class="rd-cards">${candidates.slice(0, 80).map(catCard).join("")}</div>`) : "";
  return banner + head + liveSec + backSec + note("An N=1 instrument — reader participation is deferred.");
}

export function renderProtocols(d) { const ps = (d.protocols || []).slice().sort((a, b) => (/(active|running|on)/i.test(a.status || "") ? 0 : 1) - (/(active|running|on)/i.test(b.status || "") ? 0 : 1)); if (!ps.length) return empty("No active protocols yet."); return figs([fig(ps.length, "active protocols")]) + `<div class="rd-cards">${ps.map((p) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}<p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>` + note("Matthew's deliberate interventions, read-only. Not medical advice."); }

export async function renderExperiments(d) {
  const xs = d.experiments || [];
  if (!xs.length) return empty("No experiments yet — the library is loading.");
  // P2.1 — the arc header: what the whole experiment PROGRAM has learned so far
  // (the same synthesis the coaching page reads; it was never surfaced here).
  const syn = await tryJSON("/api/experiment_synthesis");
  const arcBand = syn && syn.throughline && !isBad(syn.throughline)
    ? `<div class="rd-obs"><p class="dx-kicker label">what the program has learned${syn.week_count ? ` · week ${esc(String(syn.week_count))}` : ""}</p><p class="rd-primary">${esc(syn.throughline)}</p>${syn.arc && !isBad(syn.arc) ? `<p class="rd-why">${esc(String(syn.arc).slice(0, 420))}${String(syn.arc).length > 420 ? "…" : ""}</p>` : ""}</div>`
    : "";
  const running = xs.filter((x) => x.origin !== "library");
  const lib = xs.filter((x) => x.origin === "library");
  const avail = lib.filter((x) => x.status === "available");
  const backlog = lib.filter((x) => x.status === "backlog");
  const head = figs([fig(running.length, "running"), avail.length ? fig(avail.length, "ready to run") : "", fig(backlog.length, "in backlog")]);
  // P2.1 — running cards carry their served-but-never-drawn instrumentation:
  // the progress bar, the primary metric, the mechanism, compliance; completed
  // runs become "receipt" cards — baseline→result drawn (the effect size), the
  // key finding as the headline, the reflection as the second (human) voice.
  const runCard = (x) => {
    const done = /complete|done|ended|closed/i.test(x.status || "");
    const verdict = x.hypothesis_confirmed === true ? "confirmed" : x.hypothesis_confirmed === false ? "not confirmed" : (x.outcome || x.status || "running");
    const prog = !done && x.planned_duration_days && x.days_in != null
      ? `<div class="pr-row"><span class="pr-bar"><i style="width:${Math.max(2, Math.min(100, Number(x.progress_pct) || (Number(x.days_in) / Number(x.planned_duration_days)) * 100)).toFixed(0)}%"></i></span><span class="label">day ${esc(String(x.days_in))} of ${esc(String(x.planned_duration_days))}</span></div>`
      : "";
    const compliance = x.compliance_pct != null
      ? `<div class="pr-row"><span class="pr-bar pr-bar--ink"><i style="width:${Math.max(2, Math.min(100, Number(x.compliance_pct))).toFixed(0)}%"></i></span><span class="label">compliance ${fmt(x.compliance_pct)}%</span></div>`
      : "";
    const receipt = done && Number.isFinite(Number(x.baseline_value)) && Number.isFinite(Number(x.result_value))
      ? dumbbell([{ label: x.primary_metric || "primary metric", a: Number(x.baseline_value), b: Number(x.result_value) }], { aLabel: "baseline", bLabel: "result", unit: "" })
      : "";
    const finding = done && x.key_finding && !isBad(x.key_finding) ? `<p class="rd-line"><strong>${esc(x.key_finding)}</strong></p>` : "";
    const reflect = done && x.reflection && !isBad(x.reflection) ? `<p class="rd-reflect">“${esc(x.reflection)}”</p>` : "";
    // #539: the pre-registration stamp + the frozen criterion, rendered from the
    // design fields only — the honesty claim is that the criterion predates the data.
    let design = "";
    if (x.design && x.design.criterion && x.design.criterion.metric) {
      const c = x.design.criterion;
      const wash = Number(x.design.washout_days) ? ` · washout ${esc(String(x.design.washout_days))}d` : "";
      design = `<p class="rd-line"><span class="label">pre-registered design</span> ${esc(c.metric)} ${esc(c.direction || "")} by ≥${esc(String(c.min_effect))} · baseline ${esc(String(x.design.baseline_days))}d${wash}</p>`;
    }
    // #539: the deterministic close-path result — effect [CI, n/n] → verdict.
    let analysis = "";
    if (done && x.analysis && x.analysis.effect_size != null) {
      const a = x.analysis;
      const ci = a.ci95_low != null ? ` [95% CI ${esc(String(a.ci95_low))}, ${esc(String(a.ci95_high))}]` : "";
      analysis = `<p class="rd-line"><strong>effect ${a.effect_size > 0 ? "+" : ""}${esc(String(a.effect_size))}${ci} · n ${esc(String(a.n_window))}/${esc(String(a.n_baseline))} → ${esc(String(a.verdict || ""))}</strong></p>`;
    } else if (done && x.analysis && x.analysis.verdict) {
      analysis = `<p class="rd-line label">paired analysis: ${esc(String(x.analysis.verdict))} (n ${esc(String(x.analysis.n_window ?? "?"))}/${esc(String(x.analysis.n_baseline ?? "?"))})</p>`;
    }
    const preReg = x.pre_registered_at ? String(x.pre_registered_at).slice(0, 10) : null;
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge ${done ? "" : "rd-badge-live"}">${esc(x.status || "")}</span></header>${x.hypothesis ? `<p class="rd-why"><span class="label">hypothesis</span> ${esc(x.hypothesis)}</p>` : ""}${design}${x.mechanism && !isBad(x.mechanism) ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(x.mechanism)}</p>` : ""}${prog}${compliance}${analysis}${finding}${receipt}${reflect}${x.result_summary && !isBad(x.result_summary) && !finding ? `<p class="rd-line">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${[verdict, preReg && `pre-registered ${preReg}`, x.primary_metric && !done && "tracking " + esc(x.primary_metric), x.grade && "grade " + esc(x.grade)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`;
  };
  const libCard = (x) => {
    // P2.1 — evidence_tier gets the evClass chip treatment (strong/moderate/emerging).
    const [tc, tl] = x.evidence_tier ? evClass(x.evidence_tier) : [null, null];
    const meta = [x.pillar, x.difficulty, x.evidence_citation && "src: " + x.evidence_citation].filter(Boolean).map(esc).join("  ·  ");
    const link = x.source_url ? ` · <a class="supp-ev-link" href="${esc(x.source_url)}" target="_blank" rel="noopener">evidence ↗</a>` : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge">${esc(x.status)}</span></header>${x.hypothesis ? `<p class="rd-why">${esc(x.hypothesis)}</p>` : x.result_summary ? `<p class="rd-why">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${meta}${link}</p></article>`;
  };
  const runSec = sec("Running now", running.length ? `<div class="rd-cards">${running.map(runCard).join("")}</div>` : empty("Nothing running yet this cycle — the experiment just started."));
  const pipeline = [...avail, ...backlog];
  const pipeSec = pipeline.length ? sec(`In the pipeline (${pipeline.length})`, `<div class="rd-cards">${pipeline.slice(0, 60).map(libCard).join("")}</div>`) : "";
  return arcBand + head + runSec + pipeSec + note("N=1 instrument. “Running now” are live on the ledger; the pipeline is the experiment library — candidates not yet run.");
}
