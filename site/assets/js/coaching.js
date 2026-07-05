/*
  coaching.js — Door 4 "The Coaching" (/coaching/)
  ----------------------------------------------------------------------------
  COMMENTARY-FIRST (2026-06-28 redesign, COACHING_SECTION_REVIEW): the section's
  one job is "hear what your AI board is saying about your data right now — and
  zoom into any domain." Re-cut from roster-first to read-first:

    The Read   (default) — the board's read on you: today / this week. The
                           integrator's call + tensions + each coach's live line.
    By Coach             — a coach's read rendered ON TOP of their domain data
                           (observatory_week + coach_analysis) — the owner's ask.
    The Team             — roster · personalities · how they're built (reference).
    AI lab notes         — the Third Wall (AI's weekly read ↔ Matthew's response).
    Ask the board        — a reader's question → answered in an upcoming lab note.

  Pure surfacing of existing endpoints (/api/coaching-dashboard, /api/coach_team,
  /api/coach/{id}, /api/coach_analysis?domain=, /api/observatory_week?domain=,
  /api/weekly_priority, /api/field_notes) — nothing invented; honest empty-states.
  Reuses dx- and coach- styles from story.css; one type system (coaches speak serif).
*/
import { enhanceCoachNames, stampGenesis } from "/assets/js/coach_popover.js";
import { sigil, instrumentMark } from "/assets/js/sigils.js";
import { portrait } from "/assets/js/portraits.js"; // §8.7 — portrait(c) || sigil(c)
import { momentsIndex, shareMount } from "/assets/js/share.js"; // #404 moment permalinks

const SECTIONS = [
  { key: "read", label: "The Read", kicker: "what your board is saying — now", kind: "read" },
  { key: "by-coach", label: "By Coach", kicker: "each coach's read on your data", kind: "bycoach", url: "/api/coaches" },
  // Scorecard — the board's falsifiable track record: every call graded by the
  // daily evaluator (confirmed/refuted/pending). Honest-empty until calls resolve.
  { key: "scorecard", label: "Scorecard", kicker: "the board's track record", kind: "scorecard", url: "/api/predictions" },
  { key: "team", label: "The Team", kicker: "who they are · how they're built", kind: "team", url: "/api/coaches" },
  { key: "lab-notes", label: "AI lab notes", kicker: "the AI's read ↔ how it felt", kind: "fieldnotes", url: "/api/field_notes" },
  // Reader Q&A — ask a question (form) AND read the ones the board has answered
  // (PG-ENG-2 static feed published by scripts/publish_board_answer.py; empty-but-honest).
  { key: "qa", label: "Ask the Board", kicker: "you asked — the board answered", kind: "qa", url: "/board_answers/answers.json" },
];
const BYKEY = Object.fromEntries(SECTIONS.map((s) => [s.key, s]));
// Coaches whose 7-day domain data is available via /api/observatory_week.
const OBS_DOMAINS = new Set(["sleep", "training", "nutrition", "mind", "physical", "glucose"]);
const READ_SCOPES = [
  { id: "today", title: "Today", date: "the board's read right now" },
  { id: "week", title: "This week", date: "the week in each domain" },
  { id: "experiment", title: "The experiment", date: "the arc so far" },
];

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }
const cache = {};
async function secFetch(s) { if (!s.url) return null; if (cache[s.key]) return cache[s.key]; const d = await tryJSON(s.url); cache[s.key] = d; return d; }
const domainOf = (pid) => String(pid || "").replace(/_coach$/, "");

function entriesFor(s, data) {
  if (s.kind === "read") return READ_SCOPES.slice();
  // Reader Q&A — the ask form first, then any questions the board has answered.
  if (s.kind === "qa")
    return [{ id: "ask", title: "Ask a question", date: "to the whole board" }].concat(
      (((data && data.answers) || []).slice().reverse()).map((a) => ({ id: String(a.id), title: a.question, date: a.answered_at || "" }))
    );
  if (!data) return [];
  if (s.kind === "bycoach" || s.kind === "team")
    return (data.coaches || []).map((c) => ({ id: c.persona_id, title: String(c.name || "").trim(), date: c.domain ? String(c.domain).replace(/_/g, " ") : "", sub: c._live }));
  if (s.kind === "fieldnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "" }));
  if (s.kind === "scorecard") {
    const o = (data && data.overall) || {};
    const out = [{ id: "all", title: "The whole board", date: o.decided ? `${o.decided} decided` : `${o.total || 0} calls` }];
    const byc = (data && data.by_coach) || {};
    const names = {};
    for (const p of (data && data.predictions) || []) names[p.coach_id] = p.coach_name;
    Object.keys(byc).sort((a, b) => (byc[b].decided || 0) - (byc[a].decided || 0)).forEach((cid) => {
      const c = byc[cid];
      if (!c.total) return;
      const rate = c.hit_rate_pct != null ? `${c.hit_rate_pct}%` : `${c.decided || 0} decided`;
      out.push({ id: cid, title: names[cid] || cid, date: rate });
    });
    return out;
  }
  return [];
}

// ── Coach page sub-renderers (one type system: coaches SPEAK serif; labels/data mono) ──
// The coach's evolving, evidence-derived read of Matthew (the coach-opinion
// engine's STANCE#latest). Consumes the normalized stance shape the API returns
// for BOTH the live stance and the weight-ladder fallback (graduation_gate is
// present only on the fallback).
function coachStanceHTML(st) {
  if (!st || (!st.headline_read && !(st.stage && st.stage.label))) return "";
  const list = (arr) => (Array.isArray(arr) ? arr.map(esc).join(" · ") : "");
  const stage = st.stage || {};
  let h = `<section class="coach-stance"><p class="dx-kicker label">where I think you are · what I'm focused on</p>`;
  if (stage.label) h += `<h3 class="cs-headline">${esc(stage.label)}</h3>`;
  if (st.headline_read) h += `<p class="dx-prose">${esc(st.headline_read)}</p>`;
  if ((st.focused_on_now || []).length) h += `<p class="cs-care"><span class="label">focused on right now</span> ${list(st.focused_on_now)}</p>`;
  if ((st.set_aside_for_now || []).length) h += `<p class="cs-careless"><span class="label">set aside for now</span> ${list(st.set_aside_for_now)}</p>`;
  if (st.how_my_read_changed) h += `<p class="cs-evolve"><span class="label">how my read has changed</span> ${esc(st.how_my_read_changed)}</p>`;
  if (st.confidence_note) h += `<p class="cs-conf label">${esc(st.confidence_note)}</p>`;
  if (st.graduation_gate) h += `<p class="cs-gate label">graduates when — ${esc(st.graduation_gate)}</p>`;
  return h + `</section>`;
}
function coachReportHTML(rc) {
  const tr = (rc && rc.track_record) || {};
  let h = `<section class="coach-report"><p class="dx-kicker label">report card</p>`;
  h += `<p class="cr-rate">${tr.hit_rate_pct == null ? `Score unlocks as predictions resolve <span class="label">— first calls land in the coming weeks</span>` : esc(tr.hit_rate_pct) + "% hit-rate" + ` <span class="label">${esc(tr.n_note || "")}</span>`}</p>`;
  if ((tr.recent || []).length) h += `<ul class="cr-calls">${tr.recent.map((r) => `<li class="cr-${esc(r.status)}"><span class="label">${esc(r.status)}</span> ${esc(r.metric || "")}${r.reason ? " — " + esc(r.reason) : ""}</li>`).join("")}</ul>`;
  else h += `<p class="dx-prose">No decided predictions yet — hits <em>and</em> misses will both show here as they resolve.</p>`;
  if (tr.caveat) h += `<p class="cr-caveat label">${esc(tr.caveat)}</p>`;
  return h + `</section>`;
}
function coachCharacterHTML(c) {
  if (!c || (!(c.principles || []).length && !c.signature_behavior && !c.relationship_to_matthew)) return "";
  let h = `<section class="coach-char"><p class="dx-kicker label">the character</p>`;
  if (c.relationship_to_matthew) h += `<p class="dx-prose">${esc(c.relationship_to_matthew)}</p>`;
  if (c.signature_behavior) h += `<p class="cc-sig"><span class="label">how they show up</span> ${esc(c.signature_behavior)}</p>`;
  if ((c.principles || []).length) h += `<ul class="cc-principles">${c.principles.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`;
  if ((c.tendencies || []).length) h += `<p class="cc-tend label">tendencies: ${c.tendencies.map(esc).join(" · ")}</p>`;
  if ((c.focus_areas || []).length) h += `<p class="cc-focus label">tracks: ${c.focus_areas.map(esc).join(" · ")}</p>`;
  const vt = c.voice && (c.voice.tone || c.voice.style) ? [c.voice.tone, c.voice.style].filter(Boolean).join(" — ") : "";
  if (vt) h += `<p class="cc-voice label">voice: ${esc(vt)}</p>`;
  if (c.voice && c.voice.catchphrase) h += `<p class="cc-catch">“${esc(c.voice.catchphrase)}”</p>`;
  if (c.arc) h += `<p class="cc-arc label">their arc: ${esc(c.arc)}</p>`;
  return h + `</section>`;
}
function coachHypothesesHTML(hyps) {
  if (!(hyps && hyps.length)) return "";
  return `<section class="coach-hyp"><p class="dx-kicker label">working hypotheses · live bets</p><ul class="ch-list">` +
    hyps.map((x) => `<li class="ch-${esc(x.kind || "thread")}"><span class="label">${esc(x.kind || "thread")}</span> ${esc(x.claim)}</li>`).join("") +
    `</ul></section>`;
}
function disclose(summary, innerHTML) {
  if (!innerHTML) return "";
  return `<details class="coach-more"><summary class="dx-kicker label">${esc(summary)}</summary>${innerHTML}</details>`;
}

// ── THE TENSIONS BAND — the board's disagreements (reused by The Read) ──
function tensionsHTML(d) {
  const _tt = (d.tensions || []).filter((t) => t && (t.position_a || t.position_b || t.summary));
  let h = `<section class="team-tension"><p class="dx-kicker label">where the board disagrees — the argument, not the headline</p>`;
  if (_tt.length) {
    const _pretty = (id) => String(id || "").replace(/_coach$/, "").replace(/_/g, " ") || "a coach";
    const _strip = (s) => String(s || "").replace(/^[A-Za-z'’ .]{1,40}:\s*/, "");
    h += `<ul class="tt-list">${_tt.map((t) => {
      const [a, b] = t.coaches || [];
      const call = t.resolution || t.summary || "";
      return `<li class="tt-card"><p class="tt-topic">${esc(t.topic || "An open disagreement")}</p>` +
        (t.position_a || t.position_b ? `<div class="tt-cols"><div class="tt-pos"><span class="tt-who label">${esc(_pretty(a))}</span><p class="tt-text">${esc(_strip(t.position_a))}</p></div><div class="tt-pos"><span class="tt-who label">${esc(_pretty(b))}</span><p class="tt-text">${esc(_strip(t.position_b))}</p></div></div>` : "") +
        (call ? `<p class="tt-call"><span class="tt-call-k label">the integrator's call</span> ${esc(call)}</p>` : "") +
        `</li>`;
    }).join("")}</ul>`;
  } else {
    h += `<p class="dx-prose">No live disagreements right now — the board's aligned (or it's early and the threads haven't formed). When they pull in different directions, the tradeoff shows here.</p>`;
  }
  // #540 — THE DISPUTE: a real exchange, not a summary. Coach B answered coach A's
  // specific recorded claim (gated turns); shown verbatim from the persisted thread.
  const dp = d.dispute;
  if (dp && Array.isArray(dp.turns) && dp.turns.length >= 2) {
    const kindLabel = { position: "the claim", reply: "the reply", rejoinder: "the rejoinder" };
    h += `<div class="tt-dispute"><p class="dx-kicker label">the dispute · an actual exchange${dp.week ? ` · ${esc(dp.week)}` : ""}</p>` +
      `<p class="tt-topic">${esc(dp.topic || "")}</p>` +
      dp.turns.map((t) =>
        `<div class="ttd-turn ttd-${esc(t.kind || "turn")}"><span class="ttd-who label">${esc(t.name || t.speaker || "")}` +
        `<span class="ttd-kind"> · ${esc(kindLabel[t.kind] || t.kind || "")}</span></span><p class="ttd-line">${esc(t.line || "")}</p></div>`).join("") +
      `<p class="ttd-note label">Generated in each coach's own voice from their recorded positions — grounded, no invented numbers. AI characters arguing over real data.</p></div>`;
  }
  return h + `</section>`;
}

// ── THE READ (default) — Today / This week / The experiment ──
async function renderReadToday(read) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the board…</span></p>`;
  const d = await tryJSON("/api/coaching-dashboard");
  const team = await tryJSON("/api/coach_team"); // for the tensions band + disclosure
  if (!d) { read.innerHTML = `<p class="dx-prose">Couldn't load the board's read just now.</p>`; return; }
  const wp = d.weekly_priority || {};
  let h = `<p class="dx-kicker label">the board's read on you · right now</p><h2 class="dx-title">What the board is saying</h2>`;
  if (wp.text) {
    h += `<section class="read-priority"><p class="dx-kicker label">the one priority · ${esc(wp.coach_name || "the integrator")}</p>` +
      `<blockquote class="rp-text">${esc(wp.text)}</blockquote></section>`;
  }
  if (team) h += tensionsHTML(team);
  // The stacked all-coach digest — each coach's LIVE read (position_summary), domain-labeled, deep-linking into By Coach.
  const coaches = (d.coaches || []).filter((c) => String(c.position_summary || "").trim());
  if (coaches.length) {
    h += `<section class="read-digest"><p class="dx-kicker label">each coach's read · click to go deeper</p><ul class="rd-list">`;
    for (const c of coaches) {
      h += `<li class="rd-card" data-coach="${esc(c.coach_id + "_coach")}" style="--coach:${esc(c.color || "")}"><button type="button" class="rd-btn">` +
        `<span class="sigil-md">${sigil(c, { title: "" })}</span><span class="rd-body">` +
        `<span class="rd-top"><span class="rd-dom label">${esc(String(c.title || c.coach_id))}</span><span class="rd-name">${esc(c.name || "")}</span></span>` +
        `<span class="rd-say">${esc(c.position_summary)}</span></span></button></li>`;
    }
    h += `</ul></section>`;
  } else {
    // Honest empty — never a promising heading over dead air. The reads regenerate
    // with the daily sync; a transient gap is stated, not hidden.
    h += `<section class="read-digest"><p class="dx-kicker label">each coach's read</p>` +
      `<p class="dx-prose">The per-coach reads refresh with the next daily sync — the full roster and stances live under <button type="button" class="dx-readfull" data-goto="by-coach">By Coach →</button></p></section>`;
  }
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  read.innerHTML = h;
  read.querySelectorAll(".rd-card").forEach((li) => li.querySelector(".rd-btn").addEventListener("click", () => selectSection("by-coach", li.dataset.coach)));
  const goBtn = read.querySelector("[data-goto]");
  if (goBtn) goBtn.addEventListener("click", () => selectSection(goBtn.dataset.goto));
  enhanceCoachNames(read);
}
async function renderReadWeek(read) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the week…</span></p>`;
  const wp = await tryJSON("/api/weekly_priority");
  let h = `<p class="dx-kicker label">the week · what each domain showed</p><h2 class="dx-title">This week</h2>`;
  if (wp && wp.weekly_priority) {
    h += `<section class="read-priority"><p class="dx-kicker label">the week's call · ${esc(wp.coach_name || "the integrator")}</p><blockquote class="rp-text">${esc(wp.weekly_priority)}</blockquote></section>`;
  }
  const notes = (wp && wp.cross_domain_notes) || {};
  const keys = Object.keys(notes);
  if (keys.length) {
    h += `<section class="read-week"><p class="dx-kicker label">domain by domain</p><dl class="rw-list">`;
    for (const k of keys) {
      if (!notes[k]) continue;
      h += `<dt class="rw-dom label">${esc(k)}</dt><dd class="rw-note dx-prose">${esc(notes[k])}</dd>`;
    }
    h += `</dl></section>`;
  } else if (!(wp && wp.weekly_priority)) {
    h += `<p class="dx-prose">The week's domain read isn't in yet — it's written once a week from the integrator's synthesis.</p>`;
  }
  read.innerHTML = h;
  enhanceCoachNames(read);
}
async function renderReadExperiment(read) {
  // The arc, composed from the weekly lab notes the board has written across the run —
  // each week's tone is how the board landed that week; click to read it. Grows over time.
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the arc…</span></p>`;
  const [fn, syn] = await Promise.all([tryJSON("/api/field_notes"), tryJSON("/api/experiment_synthesis")]);
  const entries = (fn && fn.entries) || [];
  let h = `<p class="dx-kicker label">the experiment · the board's read, week by week</p><h2 class="dx-title">The experiment to date</h2>`;
  h += `<p class="dx-prose">How the board has read you across the whole run. Each week's lab note is the AI's read against how the week actually felt; the tone is how the board landed that week.</p>`;
  // The board's cross-week synthesis (C-1) — Nakamura's read of the whole trajectory,
  // written once >=2 weeks of lab notes exist. Sits above the week-by-week list.
  if (syn && syn.arc) {
    const chapMap = {};
    for (const c of syn.chapters || []) if (c && c.week_label) chapMap[c.week_label] = c.headline || "";
    h += `<section class="exp-synth"><p class="exp-synth-k label">Dr. Kai Nakamura · the arc${syn.week_count ? ` · ${esc(syn.week_count)} weeks` : ""}</p>`;
    if (syn.throughline) h += `<p class="exp-throughline">${esc(syn.throughline)}</p>`;
    for (const para of String(syn.arc).split(/\n\n+/).filter(Boolean)) h += `<p class="dx-prose">${esc(para)}</p>`;
    h += `</section>`;
    // hand the per-week headlines down to the list below
    renderReadExperiment._chapters = chapMap;
  } else {
    renderReadExperiment._chapters = {};
  }
  if (entries.length) {
    h += `<ol class="exp-arc">`;
    const chapters = renderReadExperiment._chapters || {};
    for (const e of entries) {
      const wk = e.week_label || `Week ${e.week || ""}`;
      const headline = chapters[wk] || chapters[e.week_label] || "";
      h += `<li class="exp-wk"><button type="button" class="exp-btn" data-week="${esc(e.week)}">` +
        `<span class="exp-top"><span class="exp-wkn">${esc(wk)}</span><span class="exp-tone label tone-${esc(e.ai_tone || "")}">${esc(e.ai_tone || "—")}</span></span>` +
        (headline ? `<span class="exp-headline">${esc(headline)}</span>` : "") +
        `<span class="exp-date label">${esc(String(e.ai_generated_at || "").slice(0, 10))}${e.has_matthew_response ? " · Matthew replied" : ""}</span></button></li>`;
    }
    h += `</ol>`;
    h += `<p class="bc-datalink label"><a href="/coaching/lab-notes/">read the full lab notes ↗</a> · <a href="/story/chronicle/">the chronicle ↗</a></p>`;
  } else {
    h += `<p class="dx-prose">The week-by-week arc fills in as the lab notes accrue. <a href="/story/chronicle/">The chronicle ↗</a> carries the narrative meanwhile.</p>`;
  }
  h += `<p class="hero-day label" data-bind="genesisStamp"></p>`;
  read.innerHTML = h;
  read.querySelectorAll(".exp-btn").forEach((btn) => btn.addEventListener("click", () => selectSection("lab-notes", btn.dataset.week)));
  stampGenesis();
}

// ── BY COACH — the coach's read ON TOP of their domain data (the owner's ask) ──
async function renderByCoach(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the coach…</span></p>`;
  const dom = domainOf(id);
  const wantsSession = dom === "training" || dom === "physical";
  const wantsTraining = dom === "training";
  const [coach, analysis, obs, sessions, training] = await Promise.all([
    tryJSON(`/api/coach/${encodeURIComponent(id)}`),
    tryJSON(`/api/coach_analysis?domain=${encodeURIComponent(dom)}`),
    OBS_DOMAINS.has(dom) ? tryJSON(`/api/observatory_week?domain=${encodeURIComponent(dom)}`) : Promise.resolve(null),
    wantsSession ? tryJSON("/api/workouts") : Promise.resolve(null),
    wantsTraining ? tryJSON("/api/training_overview") : Promise.resolve(null),
  ]);
  if (!coach) { read.innerHTML = `<p class="dx-prose">Couldn't load this coach just now.</p>`; return; }
  let h = `<div class="coach-head" style="--coach:${esc(coach.color || "")}">${portrait(coach, { title: "", cls: "portrait-lg", size: 96 }) || `<span class="sigil-lg">${sigil(coach, { title: "" })}</span>`}<div><p class="dx-kicker label">${esc(coach.board_role || coach.domain || "")}</p><h2 class="dx-title">${esc(coach.name || "")}</h2></div></div>`;

  // 0) THE STANCE — the coach's evolving, evidence-derived read of Matthew (the
  //    durable "where I think you are", above this week's domain detail).
  h += coachStanceHTML(coach.stance);

  // 1) THE READ — lead with the coach's actual verdict on the domain.
  if (analysis && (analysis.analysis || analysis.key_recommendation)) {
    h += `<section class="bc-read"><p class="dx-kicker label">their read on your ${esc(dom)} · this week</p>`;
    if (analysis.analysis) h += `<p class="bc-analysis dx-prose">${esc(analysis.analysis)}</p>`;
    if (analysis.key_recommendation) h += `<p class="bc-rec"><span class="label">the one thing</span> ${esc(analysis.key_recommendation)}</p>`;
    if (analysis.cross_domain_note) h += `<p class="bc-xnote label">cross-domain: ${esc(analysis.cross_domain_note)}</p>`;
    if (analysis.confidence_language) h += `<p class="bc-conf label">${esc(analysis.confidence_language)}</p>`;
    h += `</section>`;
  } else if (typeof coach.daily === "string" && coach.daily.trim()) {
    h += `<section class="bc-read"><p class="dx-kicker label">today's read</p><p class="bc-analysis dx-prose">${esc(coach.daily)}</p></section>`;
  }

  // 2) THE DATA — the numbers the read is about (the owner's "my cardio/lifts/volume this week").
  if (obs && obs.summary && obs.summary.primary) {
    const p = obs.summary.primary;
    const spark = Array.isArray(p.sparkline) ? p.sparkline : [];
    const dl = p.delta_label || (p.delta ? `${p.delta > 0 ? "+" : ""}${p.delta}` : "");
    h += `<section class="bc-data"><p class="dx-kicker label">the data · last 7 days${obs.period ? ` · ${esc(obs.period.start)} → ${esc(obs.period.end)}` : ""}</p>` +
      `<p class="bc-stat"><span class="bc-statn">${esc(p.value)}${p.unit ? " " + esc(p.unit) : ""}</span> <span class="label">${esc(p.label || "")}</span>${dl ? ` <span class="bc-delta label">${esc(dl)} ${esc(p.trend || "")}</span>` : ""}</p>` +
      (spark.length ? `<p class="bc-spark label">${spark.map((v) => esc(v)).join(" · ")}</p>` : "") +
      `<p class="bc-datalink label"><a href="/data/${esc(dom)}/">see the full ${esc(dom)} data ↗</a></p></section>`;
  } else if (OBS_DOMAINS.has(dom)) {
    h += `<section class="bc-data"><p class="dx-kicker label">the data</p><p class="dx-prose">The 7-day ${esc(dom)} numbers aren't in yet — the read above is what the coach has so far. <a href="/data/${esc(dom)}/">Full ${esc(dom)} data ↗</a></p></section>`;
  }

  // 2.5) MOST RECENT SESSION — the owner's "my most recent session, how does it compare".
  const w = sessions && sessions.workouts && sessions.workouts[0];
  if (w) {
    const top = (w.exercises || []).slice(0, 5).map((ex) => {
      const best = (ex.sets || []).filter((s) => s.weight_kg != null).sort((a, b) => (b.weight_kg || 0) - (a.weight_kg || 0))[0];
      const detail = best ? `${esc(best.reps != null ? best.reps : "")}×${esc(best.weight_kg)}kg` : ((ex.sets || []).length ? `${(ex.sets || []).length} sets` : "");
      return `<li><span class="ms-ex">${esc(ex.name || "")}</span>${detail ? ` <span class="label">${detail}</span>` : ""}</li>`;
    }).join("");
    const meta = [w.duration_min ? `${esc(w.duration_min)} min` : "", w.exercise_count != null ? `${esc(w.exercise_count)} exercises` : "", w.set_count != null ? `${esc(w.set_count)} sets` : "", w.total_volume_kg ? `${Math.round(w.total_volume_kg)} kg volume` : ""].filter(Boolean).join(" · ");
    h += `<section class="bc-session"><p class="dx-kicker label">most recent session · ${esc(w.date || "")}</p>` +
      `<p class="ms-title">${esc(w.title || "Workout")}${meta ? ` <span class="label">${meta}</span>` : ""}</p>` +
      (top ? `<ul class="ms-ex-list">${top}</ul>` : "") +
      `<p class="bc-datalink label"><a href="/data/training/">full training log ↗</a></p></section>`;
  }

  // 2.7) CARDIO vs STRENGTH + MUSCLE BALANCE — the owner's "my cardio, my lifts, my volume,
  // the exercises, how that compares" (all from /api/training_overview, already computed).
  if (training) {
    const mods = (training.modality_breakdown || []).filter((m) => (m.count_30d || 0) > 0);
    const isStrength = (t) => /weight|strength|lift/i.test(t || "");
    const cardio = mods.filter((m) => !isStrength(m.type)).sort((a, b) => (b.total_minutes_30d || 0) - (a.total_minutes_30d || 0));
    const strength = mods.filter((m) => isStrength(m.type));
    if (cardio.length || strength.length) {
      h += `<section class="bc-modality"><p class="dx-kicker label">cardio vs lifts · last 30 days</p>`;
      if (cardio.length) {
        h += `<p class="bc-mod-h label">cardio</p><ul class="bc-mod-list">`;
        for (const m of cardio) {
          const bits = [`${esc(m.count_30d)}×`, m.total_minutes_30d ? `${esc(m.total_minutes_30d)} min` : "", m.total_distance_mi ? `${esc(m.total_distance_mi)} mi` : "", m.z2_minutes ? `${esc(m.z2_minutes)} Z2 min` : ""].filter(Boolean).join(" · ");
          h += `<li><span class="bc-mod-t">${esc(m.type)}</span> <span class="label">${bits}</span></li>`;
        }
        h += `</ul>`;
      }
      if (strength.length) {
        const s = strength[0];
        h += `<p class="bc-mod-h label">lifts</p><ul class="bc-mod-list"><li><span class="bc-mod-t">${esc(s.type)}</span> <span class="label">${esc(s.count_30d)}× · ${esc(s.total_minutes_30d || 0)} min</span></li></ul>`;
      }
      h += `</section>`;
    }
    // Per-muscle balance — sets/week vs MEV/MAV/MRV, status-colored (the lifts detail).
    const mv = (training.muscle_volume || []).filter((m) => m.muscle);
    if (mv.length) {
      h += `<section class="bc-muscle"><p class="dx-kicker label">muscle balance · sets per week vs the optimal range</p><ul class="bc-musc-list">`;
      for (const m of mv) {
        h += `<li class="bc-musc musc-${esc(m.status || "")}"><span class="bc-musc-m">${esc(m.muscle)}</span>` +
          `<span class="bc-musc-n label">${esc(m.sets_per_week)}/wk</span>` +
          `<span class="bc-musc-s label">${esc(m.status || "")}${m.MAV_lo ? ` · optimal ${esc(m.MAV_lo)}–${esc(m.MAV_hi)}` : ""}</span></li>`;
      }
      h += `</ul><p class="bc-datalink label"><a href="/data/training/">full training breakdown ↗</a></p></section>`;
    }
  }

  // 3) LIVE BETS + a thin track strip (the accountability, not a whole section).
  h += coachHypothesesHTML(coach.working_hypotheses);
  const tr = (coach.report_card && coach.report_card.track_record) || {};
  if (tr.hit_rate_pct != null || (tr.recent || []).length) {
    h += `<p class="bc-track label">track record: ${tr.hit_rate_pct != null ? esc(tr.hit_rate_pct) + "% hit-rate " + esc(tr.n_note || "") : "accruing"}</p>`;
  }
  // 3.5) THE EVOLVING READ — prefer the dated STANCE# trail (how the coach's read of
  //      Matthew actually moved, week to week), falling back to recent dated commentary.
  const sh = (coach.stance_history || []).filter((s) => s && (s.how_my_read_changed || s.headline_read));
  if (sh.length) {
    h += disclose(`how this read has evolved · ${sh.length}`,
      `<ol class="ce-trail">${sh.slice(0, 8).map((s) => {
        const stage = (s.stage && s.stage.label) ? " · " + esc(s.stage.label) : "";
        const say = s.how_my_read_changed || s.headline_read || "";
        return `<li class="ce-item"><span class="ce-date label">${esc(String(s.as_of || "").slice(0, 10))}${stage}</span>` +
          (say ? `<p class="ce-say">${esc(say)}</p>` : "") + `</li>`;
      }).join("")}</ol>`);
  } else {
    const ro = (coach.recent_outputs || []).filter((o) => o && (o.summary || (o.themes || []).length));
    if (ro.length) {
      h += disclose(`how this read has evolved · ${ro.length} recent`,
        `<ol class="ce-trail">${ro.slice(0, 8).map((o) =>
          `<li class="ce-item"><span class="ce-date label">${esc(String(o.date || "").slice(0, 10))}</span>` +
          (o.summary ? `<p class="ce-say">${esc(o.summary)}</p>` : "") +
          ((o.themes || []).length ? `<p class="ce-themes label">${(o.themes || []).slice(0, 4).map(esc).join(" · ")}</p>` : "") +
          `</li>`).join("")}</ol>`);
    }
  }
  // 4) The bio is one disclosure click down — not the lead (the stance now leads).
  h += disclose("who this coach is · their voice", coachCharacterHTML(coach.character));
  read.innerHTML = h;
  enhanceCoachNames(read);
}

// ── THE TEAM — roster / personalities / config (demoted reference) ──
async function renderTeamCoach(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the profile…</span></p>`;
  const d = await tryJSON(`/api/coach/${encodeURIComponent(id)}`);
  if (!d) { read.innerHTML = `<p class="dx-prose">Couldn't load this profile just now.</p>`; return; }
  let h = `<div class="coach-head" style="--coach:${esc(d.color || "")}">${portrait(d, { title: "", cls: "portrait-lg", size: 96 }) || `<span class="sigil-lg">${sigil(d, { title: "" })}</span>`}<div><p class="dx-kicker label">${esc(d.board_role || d.domain || "")}</p><h2 class="dx-title">${esc(d.name || "")}</h2></div></div>`;
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  h += coachCharacterHTML(d.character);
  const v = d.voice || {};
  if (typeof v.few_shot_example === "string" && v.few_shot_example.trim())
    h += `<section class="coach-voice"><p class="dx-kicker label">voice signature</p><blockquote class="cv-example">${esc(v.few_shot_example)}</blockquote></section>`;
  const rel = d.relationships || {};
  const edge = (e) => `${esc(domainOf(e.coach))} (${esc(e.weight)})`;
  if ((rel.leans_on || []).length || (rel.leaned_on_by || []).length) {
    let rh = `<section class="coach-rel"><p class="dx-kicker label">on the team</p>`;
    if ((rel.leans_on || []).length) rh += `<p class="cr-edges"><span class="label">leans on</span> ${rel.leans_on.map(edge).join(" · ")}</p>`;
    if ((rel.leaned_on_by || []).length) rh += `<p class="cr-edges"><span class="label">leaned on by</span> ${rel.leaned_on_by.map(edge).join(" · ")}</p>`;
    h += rh + `</section>`;
  }
  h += disclose("their report card", coachReportHTML(d.report_card));
  h += `<p class="bc-datalink label"><a href="/coaching/by-coach/#${esc(id)}">→ what they're saying about your ${esc(domainOf(id))}</a></p>`;
  read.innerHTML = h;
  enhanceCoachNames(read);
}

// ── AI LAB NOTES (the Third Wall) ──
async function renderFieldNote(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
  try {
    const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`); const e = d.entry || {};
    const ai = [["The AI's read", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"]].filter((v) => v[1]);
    const mattText = e.matthew_notes || e.matthew_agreement;
    const mattVoice = mattText
      ? `<div class="voice human"><span class="who">Matthew</span><p class="what">${esc(mattText)}</p></div>`
      : `<div class="voice human voice-pending"><span class="who">Matthew</span>` +
        `<p class="what pending-lead">The other half of the wall — Matthew's reply — is held open for this week.</p>` +
        `<p class="pending-sub label">He answers the AI on his own time; an empty slot is honest, not a gap. When he writes back, it lands right here, beside the machine's read.</p></div>`;
    const hasAny = ai.length || mattText;
    read.innerHTML = `<p class="dx-kicker label">field note · week ${esc(id)} · the AI's read ↔ Matthew's response${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
      (hasAny ? ai.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("") + mattVoice
        : `<p class="dx-prose">No field note recorded for this week yet.</p>`);
  } catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this field note just now.</p>`; }
  enhanceCoachNames(read);
}

// ── CONVENE THE BOARD (uplevel P2) — the live 6-persona panel, made visible.
// /api/board_ask existed with ZERO front-end callers; this is the site's clearest
// "watch the AI think" moment. Three of the six answer by default (latency + cost —
// the server's 5/IP/hour rate limit and budget tiers bound the spend); a toggle
// convenes all six. Cards render in a "deliberating" shimmer the moment you ask,
// then reveal in sequence — interaction, not animation, so reduced-motion simply
// shows all answers at once. Every failure state is honest: rate-limited (429 +
// Retry-After), budget-paused ({paused:true}), and a per-persona unavailability.
// The moderated weekly Reader Q&A stays as the considered-answer fallback path.
// #373: ONE cast — the same eight coaches the rest of the site displays, so the
// sigils and names on the convene cards match the roster (the phantom second
// cast answered ungrounded and is retired; the API maps old cached ids).
const BOARD_PERSONAS = {
  training_coach: { name: "Dr. Sarah Chen", title: "Training & Movement" },
  nutrition_coach: { name: "Dr. Marcus Webb", title: "Evidence-Based Nutrition" },
  sleep_coach: { name: "Dr. Lisa Park", title: "Sleep & Recovery" },
  physical_coach: { name: "Dr. Victor Reyes", title: "Physical & Metabolic Health" },
  glucose_coach: { name: "Dr. Amara Patel", title: "Glucose & Metabolic Response" },
  mind_coach: { name: "Dr. Nathan Reeves", title: "Mind & Behaviour" },
  labs_coach: { name: "Dr. James Okafor", title: "Labs & Biomarkers" },
  explorer_coach: { name: "Dr. Henning Brandt", title: "Cross-Domain Patterns" },
};
const BOARD_TRIO = ["training_coach", "nutrition_coach", "sleep_coach"];

function renderAskBoard(read) {
  read.innerHTML =
    `<p class="dx-kicker label">convene the board</p><h2 class="dx-title">Put a question to the AI board.</h2>` +
    `<p class="dx-prose">Ask, and the board answers live — each member from their own discipline, reading the same real data. Correlative, never medical advice.</p>` +
    `<form class="askboard-form" novalidate>` +
    `<textarea class="askboard-in" name="q" rows="3" maxlength="500" placeholder="e.g. Is the glucose spike the supplement, or just a bad night's sleep?" aria-label="Your question for the board"></textarea>` +
    `<div class="askboard-row">` +
    `<label class="cv-all label"><input type="checkbox" name="allsix"> convene the full board (8)</label>` +
    `<button class="askboard-btn" type="submit">Convene the board</button>` +
    `</div><p class="askboard-out label" role="status" aria-live="polite"></p></form>` +
    `<div class="cv-panel" data-cv-panel aria-live="polite"></div>` +
    `<p class="dx-disclosure label">Rate-limited (5/hour) and budget-guarded. Prefer a considered, human-reviewed answer? ` +
    `<button type="button" class="dx-readfull" data-cv-queue>Send it to the weekly Reader Q&amp;A →</button></p>` +
    `<p class="dx-prose" data-qa-feedstate></p>` +
    `<div class="imark-rail" aria-hidden="true">${instrumentMark()}</div>`;
  // #397: the honest state of the answered-questions feed — real count when the
  // loop has closed before, an honest "none yet" (never seeded fakes) when not.
  tryJSON("/board_answers/answers.json").then((d) => {
    const el = read.querySelector("[data-qa-feedstate]");
    if (!el) return;
    const n = ((d && d.answers) || []).length;
    el.textContent = n
      ? `${n} reader question${n === 1 ? "" : "s"} answered so far — they're in the list on the left, dated, next to the board's take.`
      : "No reader questions answered yet — ask one. Answered questions appear here publicly, dated, alongside the board's take.";
  });
  const form = read.querySelector(".askboard-form");
  const out = read.querySelector(".askboard-out");
  const panel = read.querySelector("[data-cv-panel]");
  // The moderated path stays first-class: the same question can go to the weekly
  // Reader Q&A queue (existing /api/board_question capture — no AI on submit).
  read.querySelector("[data-cv-queue]").addEventListener("click", async () => {
    const q = form.q.value.trim();
    if (q.length < 10) { out.textContent = "Type the question above first (at least 10 characters), then send it to the queue."; return; }
    out.textContent = "Sending to the queue…";
    try {
      const res = await fetch("/api/board_question", { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify({ question: q }) });
      if (res.ok) { out.textContent = "Queued — Matthew reviews these, and the board answers a selection in the weekly Reader Q&A."; form.q.value = ""; }
      else if (res.status === 429) { out.textContent = "You've queued a few already — give it an hour."; }
      else { out.textContent = "Couldn't queue that just now — try again shortly."; }
    } catch (e) { out.textContent = "Network hiccup — try again in a moment."; }
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    if (q.length < 10) { out.textContent = "A little more detail — at least 10 characters."; return; }
    const btn = form.querySelector(".askboard-btn");
    const personas = form.allsix.checked ? Object.keys(BOARD_PERSONAS) : BOARD_TRIO;
    btn.disabled = true; out.textContent = "";
    // The deliberation, visible: every convened member's card appears immediately,
    // thinking — then the answers land.
    panel.innerHTML = `<p class="cv-q"><span class="label">the question</span>${esc(q)}</p>` +
      personas.map((pid) => {
        const p = BOARD_PERSONAS[pid];
        return `<article class="cv-card" data-pid="${esc(pid)}">` +
          `<header class="cv-head"><span class="sigil-md">${portrait({ coach_id: pid, name: p.name }, { title: "", size: 24 }) || sigil({ coach_id: pid, name: p.name }, { title: "" })}</span>` +
          `<span class="cv-who"><span class="cv-name">${esc(p.name)}</span><span class="cv-title label">${esc(p.title)}</span></span></header>` +
          `<p class="cv-text is-thinking"><span class="shimmer">deliberating…</span></p></article>`;
      }).join("");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    try {
      const res = await fetch("/api/board_ask", { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify({ question: q, personas }) });
      const d = await res.json().catch(() => ({}));
      if (res.status === 429) {
        const mins = Math.max(1, Math.round(Number(res.headers.get("Retry-After") || 3600) / 60));
        panel.innerHTML = `<p class="cv-note">The board's hourly limit is reached — it reconvenes in about ${mins} min. Or leave the question for the weekly Reader Q&amp;A below.</p>`;
      } else if (d && d.paused) {
        panel.innerHTML = `<p class="cv-note">${esc(d.answer || "The board is paused for the rest of the month to stay within budget — it's back on the 1st.")}</p>`;
      } else if (d && d.responses && Object.keys(d.responses).length) {
        personas.forEach((pid, i) => {
          const card = panel.querySelector(`[data-pid="${pid}"]`);
          if (!card) return;
          const text = String(d.responses[pid] || "");
          const unavailable = !text || /^\[.*unavailable\]$/i.test(text.trim());
          const el = card.querySelector(".cv-text");
          el.classList.remove("is-thinking");
          el.style.setProperty("--cv-delay", `${i * 0.35}s`);
          if (unavailable) {
            el.classList.add("cv-unavailable");
            el.textContent = `${BOARD_PERSONAS[pid].name} couldn't join this one.`;
          } else {
            // Personas emit light markdown bold — escape first, then render **…**
            // as <strong> so emphasis reads as emphasis, not raw asterisks.
            el.innerHTML = esc(text).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
          }
          el.classList.add("is-answered");
        });
        out.textContent = "";
        form.q.value = "";
      } else {
        panel.innerHTML = `<p class="cv-note">The board couldn't convene just now — try again shortly, or leave it for the weekly Reader Q&amp;A.</p>`;
      }
    } catch (err) {
      panel.innerHTML = `<p class="cv-note">Couldn't reach the board just now — try again in a moment.</p>`;
    } finally {
      btn.disabled = false;
    }
  });
}

async function renderRead(s, id) {
  const read = $("[data-dx-read]");
  if (s.kind === "read") { if (id === "week") return renderReadWeek(read); if (id === "experiment") return renderReadExperiment(read); return renderReadToday(read); }
  if (s.kind === "bycoach") return renderByCoach(read, id);
  if (s.kind === "team") return renderTeamCoach(read, id);
  if (s.kind === "fieldnotes") return renderFieldNote(read, id);
  if (s.kind === "scorecard") return renderScorecard(read, id);
  if (s.kind === "qa") { if (String(id) === "ask") return renderAskBoard(read); return renderAnswer(read, id); }
}

// THE SCORECARD — the board's falsifiable record. Every call the coaches make is
// graded by the daily evaluator (EWMA-trend directional / machine). Honest about
// the early state: most calls are still inside their 2–4 week resolution window.
const _STATUS_LABEL = { confirmed: "confirmed", refuted: "refuted", pending: "still open", inconclusive: "no signal", expired: "expired" };
async function renderScorecard(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Tallying the board's calls…</span></p>`;
  const data = (await tryJSON("/api/predictions")) || {};
  const momentUrl = _momentUrlFor(await momentsIndex()); // #404 share permalinks
  const o = data.overall || {};
  const byc = data.by_coach || {};
  const preds = data.predictions || [];
  const names = {};
  for (const p of preds) names[p.coach_id] = p.coach_name;
  const decided = o.decided || 0;

  if (String(id) === "all" || !id) {
    let h = `<p class="dx-kicker label">the scorecard · every call, graded</p><h2 class="dx-title">The board's track record</h2>`;
    h += `<p class="dx-prose">The coaches don't just talk — they make falsifiable calls, and a deterministic evaluator grades each one against the data once its window closes. This is the honest tally. <span class="label">Self-assessment of the board's own calls, not external validation.</span></p>`;
    // The headline tiles.
    h += `<div class="sc-tiles">` +
      `<div class="sc-tile"><span class="sc-n">${decided ? `${o.accuracy_pct}%` : "—"}</span><span class="sc-l label">hit rate${decided ? ` · ${decided} decided` : ""}</span></div>` +
      `<div class="sc-tile"><span class="sc-n">${o.confirmed || 0}</span><span class="sc-l label">confirmed</span></div>` +
      `<div class="sc-tile"><span class="sc-n">${o.refuted || 0}</span><span class="sc-l label">refuted</span></div>` +
      `<div class="sc-tile"><span class="sc-n">${o.pending || 0}</span><span class="sc-l label">still open</span></div>` +
      `</div>`;
    if (!decided) {
      const pending = preds.filter((p) => p.status === "pending" && p.date);
      pending.sort((a, b) => (a.date < b.date ? -1 : 1));
      const nearest = pending[0];
      const countdown = nearest ? ` First verdict expected around <strong>${esc(nearest.date)}</strong>.` : "";
      h += `<p class="dx-prose sc-note">The board has made <strong>${o.total || 0}</strong> calls so far; none have resolved yet — each one grades only after its 2–4 week window closes.${countdown}${o.inconclusive ? ` ${o.inconclusive} came back with no clear signal.` : ""} The record fills in as the experiment runs. Watch a coach's calls under their name at left.</p>`;
    }
    // Per-coach rows.
    const rows = Object.keys(byc).filter((c) => byc[c].total).sort((a, b) => (byc[b].decided || 0) - (byc[a].decided || 0));
    if (rows.length) {
      h += `<p class="dx-kicker label sc-sub">by coach</p><ul class="sc-coachlist">`;
      for (const cid of rows) {
        const c = byc[cid];
        const rate = c.hit_rate_pct != null ? `${c.hit_rate_pct}%` : "—";
        h += `<li class="sc-row"><button type="button" class="sc-coachbtn" data-coach="${esc(cid)}">` +
          `<span class="sc-coach">${esc(names[cid] || cid)}</span>` +
          `<span class="sc-rate label">${esc(rate)}</span>` +
          `<span class="sc-mix label">${c.confirmed || 0}✓ · ${c.refuted || 0}✗ · ${c.pending || 0} open</span></button></li>`;
      }
      h += `</ul>`;
    }
    // Recent decided calls (the real signal once they exist).
    const decidedCalls = preds.filter((p) => p.status === "confirmed" || p.status === "refuted").slice(0, 8);
    if (decidedCalls.length) {
      h += `<p class="dx-kicker label sc-sub">recently graded</p>` + decidedCalls.map((p) => _scCallHTML(p, momentUrl(p))).join("");
    }
    read.innerHTML = h;
    read.querySelectorAll(".sc-coachbtn").forEach((b) => b.addEventListener("click", () => selectEntry(BYKEY.scorecard, b.dataset.coach)));
    enhanceCoachNames(read);
    return;
  }

  // A single coach's record.
  const c = byc[id] || {};
  const name = names[id] || id;
  const mine = preds.filter((p) => p.coach_id === id);
  const decidedC = c.decided || 0;
  let h = `<p class="dx-kicker label">scorecard · one coach</p><h2 class="dx-title">${esc(name)}</h2>`;
  h += `<div class="sc-tiles">` +
    `<div class="sc-tile"><span class="sc-n">${decidedC ? `${c.hit_rate_pct}%` : "—"}</span><span class="sc-l label">hit rate${decidedC ? ` · ${decidedC} decided` : ""}</span></div>` +
    `<div class="sc-tile"><span class="sc-n">${c.confirmed || 0}</span><span class="sc-l label">confirmed</span></div>` +
    `<div class="sc-tile"><span class="sc-n">${c.refuted || 0}</span><span class="sc-l label">refuted</span></div>` +
    `<div class="sc-tile"><span class="sc-n">${c.pending || 0}</span><span class="sc-l label">still open</span></div>` +
    `</div>`;
  if (!decidedC) h += `<p class="dx-prose sc-note">${esc(name)} has ${c.total || 0} calls on the board; none have resolved yet. Each grades after its window closes.</p>`;
  const show = mine.slice(0, 14);
  if (show.length) h += `<p class="dx-kicker label sc-sub">the calls</p>` + show.map((p) => _scCallHTML(p, momentUrl(p))).join("");
  h += `<p class="bc-datalink label"><a href="/coaching/scorecard/#all">← the whole board</a></p>`;
  read.innerHTML = h;
  read.querySelectorAll("[data-coach]").forEach((b) => b.addEventListener("click", () => selectEntry(BYKEY.scorecard, b.dataset.coach)));
  enhanceCoachNames(read);
}
function _scCallHTML(p, shareUrl) {
  const st = p.status || "pending";
  return `<div class="sc-call sc-${esc(st)}"><div class="sc-call-top"><span class="sc-call-st label">${esc(_STATUS_LABEL[st] || st)}</span>` +
    `${p.metric ? `<span class="sc-call-m label">${esc(p.metric)}</span>` : ""}` +
    `${p.date ? `<span class="sc-call-d label">${esc(p.date)}</span>` : ""}</div>` +
    `<p class="sc-call-claim">${esc(p.text || "")}</p>` +
    `${p.outcome_notes ? `<p class="sc-call-why label">${esc(p.outcome_notes)}</p>` : ""}` +
    `${shareUrl ? shareMount(shareUrl, p.text || "a graded prediction") : ""}</div>`;
}
// #404: a graded call's permalink, from the moments index (built by the daily
// sweep). Key mirrors og_moments._prediction_key — plain composite, no hashing.
function _momentUrlFor(mi) {
  const map = {};
  for (const m of (mi && mi.predictions) || []) map[m.key] = m.url;
  return (p) => map[`${p.coach_id}|${p.date}|${String(p.text || "").slice(0, 60)}`];
}

// A single board-answered reader question (PG-ENG-2 static feed).
async function renderAnswer(read, id) {
  const data = await tryJSON("/board_answers/answers.json");
  const a = ((data && data.answers) || []).find((x) => String(x.id) === String(id));
  if (!a) { read.innerHTML = `<p class="dx-prose">That question isn't here yet.</p>`; return; }
  const resp = (a.responses && a.responses.length)
    ? a.responses.map((r) => `<div class="voice machine"><span class="who">${esc(r.name || r.coach || "The board")}</span><p class="what">${esc(r.text)}</p></div>`).join("")
    : (a.answer ? `<div class="voice machine"><span class="who">The board</span><p class="what">${esc(a.answer)}</p></div>` : `<p class="dx-prose">An answer is on the way.</p>`);
  // #404: the answer's permalink (a static moment shell with its own share
  // card) — button appears only once the daily sweep has minted it.
  const mi = await momentsIndex();
  const momentUrl = ((mi && mi.qa) || {})[String(id)];
  read.innerHTML =
    `<p class="dx-kicker label">a reader asked${a.answered_at ? ` · ${esc(a.answered_at)}` : ""}</p>` +
    `<h2 class="dx-title">${esc(a.question)}</h2>` +
    (a.note ? `<p class="dx-prose">${esc(a.note)}</p>` : "") + resp +
    (momentUrl ? `<p class="qa-share">${shareMount(momentUrl, a.question)}</p>` : "");
  enhanceCoachNames(read);
}

// On the By-Coach / Team lists, enrich each card subtitle with the coach's live one-line read.
async function enrichCoachLive(data) {
  if (!data || data._enriched) return data;
  const dash = await tryJSON("/api/coaching-dashboard");
  const live = {};
  for (const c of (dash && dash.coaches) || []) live[c.coach_id + "_coach"] = c.position_summary;
  for (const c of data.coaches || []) c._live = live[c.persona_id] || "";
  data._enriched = true;
  return data;
}

function selectEntry(s, id, silent) {
  document.querySelectorAll(".dx-item").forEach((b) => b.classList.toggle("is-active", String(b.dataset.id) === String(id)));
  if (!silent) { try { history.replaceState({ sec: s.key, id }, "", `/coaching/${s.key}/#${id}`); } catch (e) {} }
  renderRead(s, id);
}
async function selectSection(key, preId, push = true) {
  const s = BYKEY[key]; if (!s) return;
  document.querySelectorAll(".dx-tab").forEach((t) => { const on = t.dataset.sec === key; t.classList.toggle("is-active", on); t.setAttribute("aria-pressed", String(on)); });
  if (push) { try { history.pushState({ sec: key }, "", `/coaching/${key}/`); } catch (e) {} }
  document.title = `${s.label} — The Coaching — averagejoematt`;
  const listEl = $("[data-dx-list]");
  listEl.innerHTML = `<li class="dx-empty"><span class="shimmer">Loading…</span></li>`;
  let data = await secFetch(s);
  if (s.kind === "bycoach" || s.kind === "team") data = await enrichCoachLive(data);
  const entries = entriesFor(s, data);
  if (!entries.length) { listEl.innerHTML = `<li class="dx-empty">Nothing here yet — it fills as the experiment runs.</li>`; $("[data-dx-read]").innerHTML = ""; return; }
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}</span><span class="dx-item-d label">${esc(e.date || "")}</span>${e.sub ? `<span class="dx-item-sub">${esc(String(e.sub).slice(0, 90))}</span>` : ""}</button></li>`).join("");
  listEl.querySelectorAll(".dx-item").forEach((b) => b.addEventListener("click", () => selectEntry(s, b.dataset.id)));
  const initId = preId && entries.some((e) => String(e.id) === String(preId)) ? preId : entries[0].id;
  selectEntry(s, initId, true);
}

function build() {
  const tabsEl = $("[data-dx-tabs]"); if (!tabsEl) return;
  tabsEl.innerHTML = SECTIONS.map((s) => `<button class="dx-tab" data-sec="${s.key}" aria-pressed="false">${esc(s.label)}</button>`).join("");
  tabsEl.querySelectorAll(".dx-tab").forEach((b) => b.addEventListener("click", () => selectSection(b.dataset.sec)));
  const start = (window.__COACHING_START__ && BYKEY[window.__COACHING_START__]) ? window.__COACHING_START__ : "read";
  const hashId = (location.hash || "").replace("#", "") || undefined;
  selectSection(start, hashId, false);
  wireMachineryRibbon(tabsEl);
}

// ── The machinery ribbon (uplevel P3) — the elite AI machinery (live tensions +
// the falsifiable track record) was one tab too deep; the landing view showed
// none of it. One quiet line above the tabs, from data already computed:
// a live disagreement when one exists, and the scorecard tally always (honest
// about "none decided yet" — the count itself is the credibility signal).
// Fail-quiet: no data → no ribbon.
async function wireMachineryRibbon(tabsEl) {
  try {
    const [team, preds] = await Promise.all([tryJSON("/api/coach_team"), tryJSON("/api/predictions")]);
    const bits = [];
    const tension = ((team && team.tensions) || []).find((t) => t && (t.topic || t.summary));
    if (tension) {
      bits.push(`<button type="button" class="cm-bit cm-tension" data-sec="read"><span class="cm-k label">the board disagrees</span> ${esc(tension.topic || tension.summary)} →</button>`);
    }
    const o = (preds && preds.overall) || {};
    if (o.total) {
      const tally = o.decided
        ? `${o.decided} decided · ${o.accuracy_pct != null ? o.accuracy_pct + "% held up" : ""}`
        : "none decided yet — graded daily as windows close";
      bits.push(`<button type="button" class="cm-bit" data-sec="scorecard"><span class="cm-k label">the record</span> ${esc(String(o.total))} falsifiable calls · ${esc(tally)} →</button>`);
    }
    if (!bits.length) return;
    const rib = document.createElement("div");
    rib.className = "cm-ribbon";
    rib.innerHTML = bits.join("");
    tabsEl.insertAdjacentElement("beforebegin", rib);
    rib.querySelectorAll("[data-sec]").forEach((b) => b.addEventListener("click", () => selectSection(b.dataset.sec)));
  } catch (e) { /* ribbon is an enhancement — never block the page */ }
}
window.addEventListener("popstate", (e) => { const sec = (e.state && e.state.sec) || (location.pathname.match(/\/coaching\/([^/]+)\//) || [])[1] || "read"; selectSection(sec, e.state && e.state.id, false); });

function wireTheme() {
  const b = $(".theme-toggle"); if (!b) return;
  b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} });
}
wireTheme();
build();
stampGenesis();  // cross-site Day-N/Week-N anchor (matches the Home hero)
