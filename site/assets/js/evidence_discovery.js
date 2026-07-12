/*
  evidence_discovery.js — discoveries/hypotheses, the genome, challenges, protocols and
  experiments (the /protocols/ door). Split out of evidence.js (#581) — no behavior change.
*/
import { dumbbell, nDots } from "/assets/js/charts.js";
import { domainIcon, icon } from "/assets/js/icons.js";
import { esc, tryJSON, isBad, has, fmt, ttl, fig, figs, sec, empty, note, evClass, kvtable, postJSON, voteFollowRow, wireVoteButtons, wireFollowForms } from "/assets/js/evidence_shared.js";

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
  // #551 — each found correlation carries its sample size as DOTS (the confidence grammar):
  // the reader sees how much data stands behind the finding. REAL overlapping-day n only.
  const findingCard = (f) =>
    `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(f.title)}</h3></header>${f.body ? `<p class="rd-why">${esc(f.body)}</p>` : ""}${f.n ? `<p class="rd-meta label">evidence weight ${nDots(f.n, { unit: "overlapping days" })}</p>` : ""}</article>`;
  const fs = findings.length
    ? sec("Correlations found in the data", `<div class="rd-cards">${findings.map(findingCard).join("")}</div>`)
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
    // #1089: these library entries are standing supplement protocols — cross-phase
    // by design (ADR-077), deliberately carried across cycle resets and active since
    // Feb 2026. They are NOT discoveries or hypotheses of the current cycle, and
    // pre-start they must never read as findings of an experiment that hasn't
    // produced any (ADR-104). Label them as what they are: carried protocols.
    const noneYet = !fs && !is
      ? `<p class="rd-meta label">No discoveries from this cycle yet — correlations and graded findings appear here as the data accrues.</p>`
      : "";
    const protoIntro = `<p class="rd-meta label">Standing supplement protocols, deliberately carried across cycle resets — long-horizon levers under continuous measurement, not findings of the current cycle.</p>`;
    const protoCard = (h) => {
      const meta = [
        "carried across cycles",
        h.active_since && `active since ${String(h.active_since).slice(0, 10)}`,
        h.evidence_tier && `evidence ${h.evidence_tier}`,
      ].filter(Boolean).join("  ·  ");
      const body = h.hypothesis || h.description || "";
      return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(h.name)}</h3><span class="rd-badge">ongoing protocol</span></header>${body ? `<p class="rd-why">${esc(body)}</p>` : ""}<p class="rd-meta label">${esc(meta)}</p></article>`;
    };
    hs = hyp.length
      ? sec("Ongoing protocols — carried across cycles", noneYet + protoIntro + `<div class="rd-cards">${hyp.map(protoCard).join("")}</div>`)
      : "";
  }
  // Reader participation: submit a finding — a visitor-spotted correlation goes
  // to Matthew's moderation queue (POST /api/submit_finding, S3-backed) and may
  // get promoted to a Discovery above or seed a new Experiment.
  const findingSec = sec("Submit a finding", `<p class="rd-meta label">Spotted a pattern the data should chase? Two metrics + what you noticed.</p>` +
    `<form class="part-form" data-finding-form><label class="label" for="fd-a">Metric A</label><input id="fd-a" type="text" data-finding-a placeholder="e.g. Sleep hours" maxlength="100" required>` +
    `<label class="label" for="fd-b">Metric B</label><input id="fd-b" type="text" data-finding-b placeholder="e.g. Next-day HRV" maxlength="100" required>` +
    `<label class="label" for="fd-text">What did you notice?</label><textarea id="fd-text" data-finding-text placeholder="Describe the pattern" maxlength="500" required></textarea>` +
    `<label class="label" for="fd-email">Email (optional — get notified if promoted)</label><input id="fd-email" type="email" data-finding-email maxlength="254">` +
    `<button class="part-btn" type="submit">Submit finding</button><p class="part-msg" data-finding-msg></p></form>`);
  if (!fs && !is && !hs)
    return findingSec + empty("No discoveries yet — real correlations and findings surface here as the data accrues. This cycle is only days old, so it needs more data first.");
  return fs + is + hs + findingSec + note("Correlative leads, not conclusions — N=1, FDR-corrected where computed, and n is small this early in the cycle.");
}

// Wired after renderDiscoveries mounts: the submit-a-finding form.
export function wireDiscoveries(root = document) {
  const form = root.querySelector("[data-finding-form]");
  if (!form || form.__wired) return;
  form.__wired = 1;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const metric_a = form.querySelector("[data-finding-a]").value.trim();
    const metric_b = form.querySelector("[data-finding-b]").value.trim();
    const finding = form.querySelector("[data-finding-text]").value.trim();
    const email = form.querySelector("[data-finding-email]").value.trim();
    const msgEl = form.querySelector("[data-finding-msg]");
    const btn = form.querySelector("button[type=submit]");
    if (!metric_a || !metric_b) { msgEl.textContent = "Both metrics are required."; msgEl.classList.add("is-error"); return; }
    if (finding.length < 10) { msgEl.textContent = "Describe the pattern in at least 10 characters."; msgEl.classList.add("is-error"); return; }
    if (email && !email.includes("@")) { msgEl.textContent = "Enter a valid email or leave it blank."; msgEl.classList.add("is-error"); return; }
    btn.disabled = true;
    const { ok, status, data } = await postJSON("/api/submit_finding", { metric_a, metric_b, finding, email: email || undefined });
    btn.disabled = false;
    if (ok) {
      msgEl.textContent = (data && data.message) || "Finding submitted — Matthew will review it.";
      msgEl.classList.remove("is-error");
      form.reset();
    } else {
      const fallback = status === 429 ? "Rate limit reached — 3 submissions per hour." : "Couldn't submit that — try again.";
      msgEl.textContent = (data && data.error) || fallback;
      msgEl.classList.add("is-error");
    }
  });
}

export function renderGenome(d) { const g = d.genome || d; const rs = g.risk_summary || {}; const cats = g.categories || {}; const head = figs([g.total_snps != null && fig(fmt(g.total_snps), "SNPs analysed"), rs.unfavorable != null && fig(rs.unfavorable, "unfavorable"), rs.favorable != null && fig(rs.favorable, "favorable")]); const cs = Object.keys(cats).length ? sec("Risk by category", kvtable(cats)) : ""; if (!head.includes("fig-v") && !cs) return empty("Genome not yet published."); return head + cs + note("Genotype is predisposition, not destiny — context for the biomarkers."); }

export async function renderChallenges(d) {
  const [cur, catalog] = await Promise.all([tryJSON("/api/current_challenge"), tryJSON("/api/challenge_catalog")]);
  const cc = cur && cur.current_challenge;
  // Reader participation switch-on (2026-07): live vote counts merged from
  // /api/challenge_catalog (DDB-backed, not the /api/challenges snapshot).
  const voteMap = catalog && catalog.challenges
    ? Object.fromEntries(catalog.challenges.map((c) => [c.id, c.votes]))
    : null;
  const list = d.challenges || [];
  const sm = d.summary || {};
  const banner = cc && cc.challenge ? `<div class="rd-obs"><p class="rd-primary">${esc(cc.challenge)}</p>${cc.detail ? `<p class="rd-why">${esc(cc.detail)}</p>` : ""}<p class="rd-meta label">day ${esc(cc.days_complete ?? 0)} of ${esc(cc.days_total ?? "—")}</p></div>` : "";
  const live = list.filter((c) => c.origin === "live");
  const avail = list.filter((c) => c.origin === "catalog" && c.status === "available");
  const backlog = list.filter((c) => c.origin === "catalog" && c.status === "backlog");
  // #1118 — the loop-station completeness figure (the #1116 supplements pattern):
  // how many taken-on challenges state their full hypothesis contract. An honest
  // count, not a claim — unannotated (historical) entries simply render nothing.
  const withLoop = live.filter((c) => (c.source_detail && !isBad(c.source_detail)) || (c.hoped_outcome && !isBad(c.hoped_outcome)) || (c.verification_method && !isBad(c.verification_method))).length;
  const head = figs([fig(sm.active ?? live.length, "active"), live.length ? fig(`${withLoop}/${live.length}`, "with stated hypotheses") : null, fig(avail.length + backlog.length, "in the backlog")]);
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
  // Reader participation switch-on: a reader following along can log whether
  // they did today's rep too — POST /api/challenge_checkin (public, rate-limited
  // 1/IP/challenge/day). No fake counts: the button just confirms the tap landed.
  const checkinControl = (c) => `<div class="part-row" data-checkin data-challenge-id="${esc(c.challenge_id || c.id)}">` +
    `<button class="part-btn" type="button" data-checkin-btn="true">Doing this too? Log today — done</button>` +
    `<button class="part-btn" type="button" data-checkin-btn="false">Log today — missed</button>` +
    `</div><p class="part-msg" data-checkin-msg></p>`;
  // #1118 — the closed loop on the live card face (the protocols grammar shared
  // with supplements #1116/#1148 and experiments): why the challenge exists NOW
  // (source_detail — the data trigger that generated it), what should visibly
  // change if it works (hoped_outcome), and which instrument adjudicates it
  // (verification_method). Honest-empty per ADR-104: a historical challenge
  // without a field renders NOTHING for it — no placeholder prose, ever.
  const VERIFY_LABELS = { self_report: "self-report (daily check-ins)", metric_auto: "automatic metrics (wearable/log data)", hybrid: "self-report + automatic metrics" };
  const loopBlock = (c) => {
    const whyNow = c.source_detail && !isBad(c.source_detail) ? `<p class="rd-line supp-why-now"><span class="label">why now</span> ${esc(c.source_detail)}</p>` : "";
    const hope = c.hoped_outcome && !isBad(c.hoped_outcome) ? `<p class="rd-line supp-hope"><span class="label">hoped outcome</span> ${esc(c.hoped_outcome)}</p>` : "";
    const vm = c.verification_method && !isBad(c.verification_method) ? `<p class="rd-line supp-measure"><span class="label">measured by</span> ${esc(VERIFY_LABELS[c.verification_method] || c.verification_method)}</p>` : "";
    return whyNow || hope || vm ? `<div class="supp-loop">${whyNow}${hope}${vm}</div>` : "";
  };
  const liveCard = (c) => {
    const done = !!c.completed_at || c.status === "completed";
    const active = !done && (c.status === "active" || !!c.activated_at);
    const pr = c.progress || {};
    const progFigs = active && pr.duration_days
      ? `<p class="rd-meta label">${[pr.checkin_days != null && `${pr.checkin_days}/${pr.duration_days} days checked in`, pr.completion_pct != null && `${fmt(pr.completion_pct)}% complete`, pr.success_rate != null && `${fmt(pr.success_rate)}% success`].filter(Boolean).join("  ·  ")}</p>`
      : "";
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(c.name || ttl(c.challenge_id || "Challenge"))}</h3><span class="rd-badge ${active ? "rd-badge-live" : ""}">${done ? "completed" : active ? "active" : "candidate"}</span></header>${c.description && !isBad(c.description) ? `<p class="rd-why">${esc(c.description)}</p>` : ""}${loopBlock(c)}${checkinGrid(c)}${progFigs}<p class="rd-meta label">${[c.character_xp_awarded != null && c.character_xp_awarded + " XP", c.badge_earned && `${icon("milestone")} badge`].filter(Boolean).join("  ·  ")}</p>${active ? checkinControl(c) : ""}</article>`;
  };
  // P2.2 — catalog cards carry their evidence: the summary, the tier chip, and
  // the recommending board persona. The served `icon` field is emoji — never drawn (§8).
  // Reader participation: a vote (want this next) + a follow (email when it launches),
  // wired to the live challenge_vote/challenge_follow endpoints — real counts, no padding.
  const catCard = (c) => {
    const [tc, tl] = c.evidence_tier ? evClass(c.evidence_tier) : [null, null];
    const votes = voteMap ? voteMap[c.id] : null;
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${c.category ? `<span class="ch-ric">${domainIcon(c.category)}</span>` : ""}${esc(c.name)}</h3><span class="rd-badge">${esc(c.status)}</span></header>${c.one_liner ? `<p class="rd-why">${esc(c.one_liner)}</p>` : ""}${c.evidence_summary && !isBad(c.evidence_summary) ? `<p class="rd-line">${esc(c.evidence_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${[c.category, c.difficulty, c.duration_days && c.duration_days + "d", c.board_recommender && "recommended by " + c.board_recommender].filter(Boolean).map(esc).join("  ·  ")}</p>${voteFollowRow("challenge", "catalog_id", c.id, votes)}</article>`;
  };
  const liveSec = sec("Taken on", live.length ? `<div class="rd-cards">${live.map(liveCard).join("")}</div>` : empty("None taken on yet this cycle."));
  // "Available now" vs "Backlog" was a distinction without a difference — both are
  // catalog ideas not yet taken on. One backlog.
  const candidates = avail.concat(backlog);
  const backSec = candidates.length ? sec(`Backlog (${candidates.length})`, `<div class="rd-cards">${candidates.slice(0, 80).map(catCard).join("")}</div>`) : "";
  return banner + head + liveSec + backSec + note("An N=1 instrument — vote for what's next, or log along on the active one.");
}

// Wired after renderChallenges mounts (evidence.js WIRE.challenges): the generic
// vote/follow controls (shared with Experiments) + the checkin buttons on the
// live "Taken on" card.
export function wireChallenges(root = document) {
  wireVoteButtons(root);
  wireFollowForms(root);
  root.querySelectorAll("[data-checkin]").forEach((wrap) => {
    if (wrap.__wired) return;
    wrap.__wired = 1;
    const msgEl = wrap.parentElement.querySelector("[data-checkin-msg]");
    wrap.querySelectorAll("[data-checkin-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const buttons = [...wrap.querySelectorAll("[data-checkin-btn]")];
        buttons.forEach((b) => (b.disabled = true));
        const completed = btn.dataset.checkinBtn === "true";
        const { ok, status, data } = await postJSON("/api/challenge_checkin", { challenge_id: wrap.dataset.challengeId, completed });
        if (ok) {
          buttons.forEach((b) => b.classList.add("is-done"));
          if (msgEl) { msgEl.textContent = `Logged — ${completed ? "done" : "missed"} today. Thanks for checking in.`; msgEl.classList.remove("is-error"); }
        } else {
          buttons.forEach((b) => (b.disabled = false));
          const fallback = status === 429 ? "Already checked in for this challenge today." : "Couldn't log that — try again.";
          if (msgEl) { msgEl.textContent = (data && data.error) || fallback; msgEl.classList.add("is-error"); }
        }
      });
    });
  });
}

export function renderProtocols(d) { const ps = (d.protocols || []).slice().sort((a, b) => (/(active|running|on)/i.test(a.status || "") ? 0 : 1) - (/(active|running|on)/i.test(b.status || "") ? 0 : 1)); if (!ps.length) return empty("No active protocols yet."); return figs([fig(ps.length, "active protocols")]) + `<div class="rd-cards">${ps.map((p) => `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(p.name)}</h3>${p.status ? `<span class="rd-badge">${esc(p.status)}</span>` : ""}</header>${p.why ? `<p class="rd-why">${esc(p.why)}</p>` : ""}${p.mechanism ? `<p class="rd-line"><span class="label">mechanism</span> ${esc(p.mechanism)}</p>` : ""}<p class="rd-meta label">${[p.domain, p.tier && "tier " + esc(p.tier)].filter(Boolean).map(esc).join("  ·  ")}</p></article>`).join("")}</div>` + note("Matthew's deliberate interventions, read-only. Not medical advice."); }

export async function renderExperiments(d) {
  const xs = d.experiments || [];
  if (!xs.length) return empty("No experiments yet — the library is loading.");
  // P2.1 — the arc header: what the whole experiment PROGRAM has learned so far
  // (the same synthesis the coaching page reads; it was never surfaced here).
  const syn = await tryJSON("/api/experiment_synthesis");
  // Reader participation switch-on: live vote tallies from /api/experiment_library
  // (DDB-backed; the /api/experiments library entries carry only a static seed
  // count). Flatten the pillar grouping to one id→votes map.
  const elib = await tryJSON("/api/experiment_library");
  const voteMap = elib && elib.pillars
    ? Object.fromEntries(elib.pillars.flatMap((p) => (p.experiments || []).map((e) => [e.id, e.votes])))
    : null;
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
      // #728: the public frozen artifact — the timestamped before-the-results proof.
      const proof = x.pre_registration_url ? ` · <a class="supp-ev-link" href="${esc(x.pre_registration_url)}" target="_blank" rel="noopener">frozen artifact ↗</a>` : "";
      design = `<p class="rd-line"><span class="label">pre-registered design</span> ${esc(c.metric)} ${esc(c.direction || "")} by ≥${esc(String(c.min_effect))} · baseline ${esc(String(x.design.baseline_days))}d${wash}${proof}</p>`;
      // #728: the declared stopping rule — an early stop is checkable against this.
      if (x.design.stopping_rule && !isBad(x.design.stopping_rule)) {
        design += `<p class="rd-line"><span class="label">stopping rule</span> ${esc(String(x.design.stopping_rule))}</p>`;
      }
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
    // Reader participation: vote for which pipeline experiment runs next + get
    // notified when it does — wired to experiment_vote/experiment_follow.
    const votes = voteMap ? voteMap[x.id] : (x.votes != null ? x.votes : null);
    return `<article class="rd-card"><header class="rd-cardhead"><h3 class="rd-cardname">${esc(x.name)}</h3><span class="rd-badge">${esc(x.status)}</span></header>${x.hypothesis ? `<p class="rd-why">${esc(x.hypothesis)}</p>` : x.result_summary ? `<p class="rd-why">${esc(x.result_summary)}</p>` : ""}<p class="rd-meta label">${tc ? `<span class="supp-evlabel ${tc}">${esc(tl)}</span>  ·  ` : ""}${meta}${link}</p>${x.id ? voteFollowRow("experiment", "library_id", x.id, votes) : ""}</article>`;
  };
  const runSec = sec("Running now", running.length ? `<div class="rd-cards">${running.map(runCard).join("")}</div>` : empty("Nothing running yet this cycle — the experiment just started."));
  const pipeline = [...avail, ...backlog];
  const pipeSec = pipeline.length ? sec(`In the pipeline (${pipeline.length})`, `<div class="rd-cards">${pipeline.slice(0, 60).map(libCard).join("")}</div>`) : "";
  // Reader participation: suggest the next experiment — a moderated idea queue
  // (POST /api/experiment_suggest), not auto-published.
  const suggestSec = sec("Suggest an experiment", `<p class="rd-meta label">What should the platform test next? Matthew reviews every idea before it enters the pipeline.</p>` +
    `<form class="part-form" data-suggest-form><label class="label" for="sg-idea">Your idea</label>` +
    `<textarea id="sg-idea" data-suggest-idea placeholder="e.g. cold shower before bed vs deep sleep %" maxlength="500" required></textarea>` +
    `<label class="label" for="sg-source">Name or site (optional)</label><input id="sg-source" type="text" data-suggest-source maxlength="100">` +
    `<button class="part-btn" type="submit">Send</button><p class="part-msg" data-suggest-msg></p></form>`);
  return arcBand + head + runSec + pipeSec + suggestSec + note("N=1 instrument. “Running now” are live on the ledger; the pipeline is the experiment library — candidates not yet run.");
}

// Wired after renderExperiments mounts: the shared vote/follow controls on
// pipeline cards + the suggest-an-experiment form submit handler.
export function wireExperiments(root = document) {
  wireVoteButtons(root);
  wireFollowForms(root);
  const form = root.querySelector("[data-suggest-form]");
  if (form && !form.__wired) {
    form.__wired = 1;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const idea = form.querySelector("[data-suggest-idea]").value.trim();
      const source = form.querySelector("[data-suggest-source]").value.trim();
      const msgEl = form.querySelector("[data-suggest-msg]");
      const btn = form.querySelector("button[type=submit]");
      if (idea.length < 10) {
        msgEl.textContent = "A few more words — at least 10 characters.";
        msgEl.classList.add("is-error");
        return;
      }
      btn.disabled = true;
      const { ok, status, data } = await postJSON("/api/experiment_suggest", { idea, source });
      btn.disabled = false;
      if (ok) {
        msgEl.textContent = "Sent — thanks. Matthew reads every suggestion.";
        msgEl.classList.remove("is-error");
        form.reset();
      } else {
        const fallback = status === 429 ? "Too many suggestions from this connection — try again later." : "Couldn't send that — try again.";
        msgEl.textContent = (data && data.error) || fallback;
        msgEl.classList.add("is-error");
      }
    });
  }
}
