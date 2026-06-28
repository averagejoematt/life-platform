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

const SECTIONS = [
  { key: "read", label: "The Read", kicker: "what your board is saying — now", kind: "read" },
  { key: "by-coach", label: "By Coach", kicker: "each coach's read on your data", kind: "bycoach", url: "/api/coaches" },
  { key: "team", label: "The Team", kicker: "who they are · how they're built", kind: "team", url: "/api/coaches" },
  { key: "lab-notes", label: "AI lab notes", kicker: "the AI's read ↔ how it felt", kind: "fieldnotes", url: "/api/field_notes" },
  // Reader Q&A — ask a question (form) AND read the ones the board has answered
  // (PG-ENG-2 static feed published by scripts/publish_board_answer.py; empty-but-honest).
  { key: "qa", label: "Reader Q&A", kicker: "ask · the board answers", kind: "qa", url: "/board_answers/answers.json" },
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
    return [{ id: "ask", title: "✍️ Ask a question", date: "to the whole board" }].concat(
      (((data && data.answers) || []).slice().reverse()).map((a) => ({ id: String(a.id), title: a.question, date: a.answered_at || "" }))
    );
  if (!data) return [];
  if (s.kind === "bycoach" || s.kind === "team")
    return (data.coaches || []).map((c) => ({ id: c.persona_id, title: `${c.emoji || ""} ${c.name}`.trim(), date: c.domain ? String(c.domain).replace(/_/g, " ") : "", sub: c._live }));
  if (s.kind === "fieldnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "" }));
  return [];
}

// ── Coach page sub-renderers (one type system: coaches SPEAK serif; labels/data mono) ──
function coachStanceHTML(st) {
  if (!st) return "";
  const list = (arr) => (Array.isArray(arr) ? arr.map(esc).join(" · ") : "");
  let h = `<section class="coach-stance"><p class="dx-kicker label">where I think you are · what I'm focused on</p>`;
  h += `<h3 class="cs-headline">${esc(st.headline || "")}</h3><p class="dx-prose">${esc(st.read_of_him || "")}</p>`;
  if ((st.cares_most || []).length) h += `<p class="cs-care"><span class="label">caring most about right now</span> ${list(st.cares_most)}</p>`;
  if ((st.cares_less_right_now || []).length) h += `<p class="cs-careless"><span class="label">deliberately ignoring for now</span> ${list(st.cares_less_right_now)}</p>`;
  if (st.plan) h += `<p class="dx-prose"><strong>The plan:</strong> ${esc(st.plan)}</p>`;
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
  const coaches = (d.coaches || []).filter((c) => c.position_summary);
  if (coaches.length) {
    h += `<section class="read-digest"><p class="dx-kicker label">each coach's read · click to go deeper</p><ul class="rd-list">`;
    for (const c of coaches) {
      h += `<li class="rd-card" data-coach="${esc(c.coach_id + "_coach")}"><button type="button" class="rd-btn">` +
        `<span class="rd-top"><span class="rd-dom label">${esc(String(c.title || c.coach_id))}</span><span class="rd-name">${esc(c.name || "")}</span></span>` +
        `<span class="rd-say">${esc(c.position_summary)}</span></button></li>`;
    }
    h += `</ul></section>`;
  }
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  read.innerHTML = h;
  read.querySelectorAll(".rd-card").forEach((li) => li.querySelector(".rd-btn").addEventListener("click", () => selectSection("by-coach", li.dataset.coach)));
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
  const [coach, analysis, obs, sessions] = await Promise.all([
    tryJSON(`/api/coach/${encodeURIComponent(id)}`),
    tryJSON(`/api/coach_analysis?domain=${encodeURIComponent(dom)}`),
    OBS_DOMAINS.has(dom) ? tryJSON(`/api/observatory_week?domain=${encodeURIComponent(dom)}`) : Promise.resolve(null),
    wantsSession ? tryJSON("/api/workouts") : Promise.resolve(null),
  ]);
  if (!coach) { read.innerHTML = `<p class="dx-prose">Couldn't load this coach just now.</p>`; return; }
  let h = `<p class="dx-kicker label">${esc(coach.emoji || "")} ${esc(coach.board_role || coach.domain || "")}</p><h2 class="dx-title">${esc(coach.name || "")}</h2>`;

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

  // 3) LIVE BETS + a thin track strip (the accountability, not a whole section).
  h += coachHypothesesHTML(coach.working_hypotheses);
  const tr = (coach.report_card && coach.report_card.track_record) || {};
  if (tr.hit_rate_pct != null || (tr.recent || []).length) {
    h += `<p class="bc-track label">track record: ${tr.hit_rate_pct != null ? esc(tr.hit_rate_pct) + "% hit-rate " + esc(tr.n_note || "") : "accruing"}</p>`;
  }
  // 4) The bio is one disclosure click down — not the lead.
  h += disclose("who this coach is · their voice", coachCharacterHTML(coach.character) + (coach.stance && coach.stance.rung ? coachStanceHTML(coach.stance.rung) : ""));
  read.innerHTML = h;
  enhanceCoachNames(read);
}

// ── THE TEAM — roster / personalities / config (demoted reference) ──
async function renderTeamCoach(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the profile…</span></p>`;
  const d = await tryJSON(`/api/coach/${encodeURIComponent(id)}`);
  if (!d) { read.innerHTML = `<p class="dx-prose">Couldn't load this profile just now.</p>`; return; }
  let h = `<p class="dx-kicker label">${esc(d.emoji || "")} ${esc(d.board_role || d.domain || "")}</p><h2 class="dx-title">${esc(d.name || "")}</h2>`;
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

// ── ASK THE BOARD (moved off the first screen into its own section) ──
function renderAskBoard(read) {
  read.innerHTML =
    `<p class="dx-kicker label">ask the board</p><h2 class="dx-title">Got a question for the AI team?</h2>` +
    `<p class="dx-prose">Submit it — Matthew picks one and the board answers it in an upcoming lab note. This stores your question; it doesn't run a live AI answer.</p>` +
    `<form class="askboard-form" novalidate>` +
    `<textarea class="askboard-in" name="q" rows="3" maxlength="500" placeholder="e.g. Is the glucose spike the supplement, or just a bad night's sleep?" aria-label="Your question for the board"></textarea>` +
    `<div class="askboard-row">` +
    `<input class="askboard-email" name="email" type="email" maxlength="254" placeholder="email (optional — for a reply)" aria-label="Email, optional" />` +
    `<button class="askboard-btn" type="submit">Ask the board</button>` +
    `</div><p class="askboard-out label" role="status" aria-live="polite"></p></form>`;
  const form = read.querySelector(".askboard-form");
  const out = read.querySelector(".askboard-out");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    const email = form.email.value.trim();
    if (q.length < 10) { out.textContent = "A little more detail — at least 10 characters."; return; }
    const btn = form.querySelector(".askboard-btn");
    btn.disabled = true; out.textContent = "Sending…";
    try {
      const res = await fetch("/api/board_question", { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(email ? { question: q, email } : { question: q }) });
      if (res.ok) { form.q.value = ""; form.email.value = ""; out.textContent = "Question received — Matthew reviews these, and the board answers a selection in the lab notes."; }
      else if (res.status === 429) { out.textContent = "You've sent a few already — give it an hour and try again."; }
      else { const d = await res.json().catch(() => ({})); out.textContent = (d && d.error) || "Couldn't send that just now — try again shortly."; }
    } catch (err) { out.textContent = "Network hiccup — try again in a moment."; }
    finally { btn.disabled = false; }
  });
}

async function renderRead(s, id) {
  const read = $("[data-dx-read]");
  if (s.kind === "read") { if (id === "week") return renderReadWeek(read); if (id === "experiment") return renderReadExperiment(read); return renderReadToday(read); }
  if (s.kind === "bycoach") return renderByCoach(read, id);
  if (s.kind === "team") return renderTeamCoach(read, id);
  if (s.kind === "fieldnotes") return renderFieldNote(read, id);
  if (s.kind === "qa") { if (String(id) === "ask") return renderAskBoard(read); return renderAnswer(read, id); }
}

// A single board-answered reader question (PG-ENG-2 static feed).
async function renderAnswer(read, id) {
  const data = await tryJSON("/board_answers/answers.json");
  const a = ((data && data.answers) || []).find((x) => String(x.id) === String(id));
  if (!a) { read.innerHTML = `<p class="dx-prose">That question isn't here yet.</p>`; return; }
  const resp = (a.responses && a.responses.length)
    ? a.responses.map((r) => `<div class="voice machine"><span class="who">${esc(r.name || r.coach || "The board")}</span><p class="what">${esc(r.text)}</p></div>`).join("")
    : (a.answer ? `<div class="voice machine"><span class="who">The board</span><p class="what">${esc(a.answer)}</p></div>` : `<p class="dx-prose">An answer is on the way.</p>`);
  read.innerHTML =
    `<p class="dx-kicker label">a reader asked${a.answered_at ? ` · ${esc(a.answered_at)}` : ""}</p>` +
    `<h2 class="dx-title">${esc(a.question)}</h2>` +
    (a.note ? `<p class="dx-prose">${esc(a.note)}</p>` : "") + resp;
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
}
window.addEventListener("popstate", (e) => { const sec = (e.state && e.state.sec) || (location.pathname.match(/\/coaching\/([^/]+)\//) || [])[1] || "read"; selectSection(sec, e.state && e.state.id, false); });

function wireTheme() {
  const b = $(".theme-toggle"); if (!b) return;
  b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} });
}
wireTheme();
build();
stampGenesis();  // cross-site Day-N/Week-N anchor (matches the Home hero)
