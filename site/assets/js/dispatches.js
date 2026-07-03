/*
  dispatches.js — Door 2's narrative/context sub-pages (/story/).
  ----------------------------------------------------------------------------
  The slower "overlay of what's going on" — distinct from the real-time data in
  Evidence/Cockpit. Master-detail: section nav (Chronicle · AI lab notes · In my
  own words · Timeline · About) → entry list → reader. Real sub-page URLs
  (/story/<section>/) + #<entry> deep links; back/forward via History API.
  Chronicle/journal indexes from posts.json (native excerpts); lab notes fully
  native from /api/field_notes; timeline from /api/journey_timeline.
*/
import { enhanceCoachNames, stampGenesis } from "/assets/js/coach_popover.js";
import { isNewSince, mountSinceRibbon } from "/assets/js/since.js"; // uplevel P5 — reader-keyed NEW badges
import { sigil } from "/assets/js/sigils.js";

// NB (2026-06-20): "The Coaches" + "AI lab notes" moved OUT to their own top-level
// door, /coaching/ (assets/js/coaching.js). The coach/fieldnotes renderer functions
// below are retained-but-unused here (they now live in coaching.js) — pending cleanup.
// Feed wiring (2026-06-21, PR D — untangle): the chronicle Lambda writes Elena's
// weekly installments to generated/journal/posts.json (served at /journal/posts.json,
// phase-filtered → current-cycle only). That IS the Chronicle feed — point Chronicle
// at it so cycle-4 issues appear and pre-genesis ones don't. "In my own words" is
// Matt's OWN blog: a separate, Matt-authored source (/journal/blog.json), honestly
// empty until he writes one — never the AI-written chronicle content.
const SECTIONS = [
  { key: "chronicle", label: "Chronicle", kicker: "written weekly by Elena Voss", kind: "posts", url: "/journal/posts.json" },
  { key: "panel", label: "Podcast", kicker: "Elena + a coach review the week", kind: "podcast", url: "/panelcast/episodes.json" },
  { key: "journal", label: "In my own words", kicker: "Matt's own blog", kind: "posts", url: "/journal/blog.json" },
  { key: "timeline", label: "Timeline", kicker: "level-ups & milestones", kind: "timeline", url: "/api/journey_timeline" },
  { key: "about", label: "About", kicker: "the experiment, in context", kind: "about" },
];
const BYKEY = Object.fromEntries(SECTIONS.map((s) => [s.key, s]));

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
let _podcastEpisodes = null;  // current-cycle feed; loaded once, fails silent
async function podcastEpisode(ent) {
  // The chronicle's "listen" join used to read the SEASON-1 feed (/podcast/
  // episodes.json — pre-reset episodes, weeks 5..-4, Feb–May dates) keyed by
  // bare week number. Week numbers repeat across experiment resets, so the
  // moment the current chronicle reached Week 5 it would have inherited a May
  // episode about a previous cycle. Now: the current-cycle feed (/panelcast/,
  // the same one the Podcast tab reads) + a date-window guard on the join.
  if (_podcastEpisodes === null) {
    try {
      const d = await getJSON("/panelcast/episodes.json");
      _podcastEpisodes = d.episodes || [];
    } catch (e) { _podcastEpisodes = []; }
  }
  if (!ent) return undefined;
  const w = ent.week ?? ent.id;
  return _podcastEpisodes.find((e) => {
    if (String(e.week) !== String(w)) return false;
    if (!ent.date || !e.date) return true; // nothing to compare — trust the week
    const gap = Math.abs(Date.parse(e.date) - Date.parse(ent.date)) / 86400000;
    return Number.isFinite(gap) ? gap <= 14 : true; // same-cycle window
  });
}

async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }

// Episode transcript reader — speaker-attributed turns + a "chapters" contents list
// built from the host's (Elena's) turns. Chapters jump within the transcript (there
// are no audio timestamps: the episode is synthesized in one pass). Fails quiet.
async function renderTranscript(url, mount) {
  if (!mount) return;
  const d = await tryJSON(url);
  const turns = (d && d.turns) || [];
  if (!turns.length) return;
  const slug = (i) => `t-${i}`;
  // Chapters: each Elena turn is a natural section start; label it with its opening words.
  const chapters = turns
    .map((t, i) => ({ t, i }))
    .filter(({ t }) => (t.speaker || "").toLowerCase().includes("elena"))
    .map(({ t, i }) => ({ i, label: esc(String(t.line).replace(/\s+/g, " ").trim().split(/(?<=[.?!])\s/)[0]).slice(0, 64) }))
    .slice(0, 8);
  const toc = chapters.length
    ? `<details class="tx-toc"><summary class="dx-kicker label">in this episode · ${chapters.length} moments</summary>` +
      `<ol class="tx-chapters">${chapters.map((c) => `<li><a href="#${slug(c.i)}">${c.label}…</a></li>`).join("")}</ol></details>`
    : "";
  const body = turns
    .map((t, i) => `<div class="tx-turn" id="${slug(i)}"><span class="tx-who label">${esc(t.name || t.speaker)}</span><p class="tx-line">${esc(t.line)}</p></div>`)
    .join("");
  mount.innerHTML = `<p class="dx-kicker label">transcript</p>${toc}<div class="tx-body">${body}</div>`;
  mount.hidden = false;
}
const cache = {};
async function secFetch(s) { if (!s.url) return null; if (cache[s.key]) return cache[s.key]; const d = await tryJSON(s.url); cache[s.key] = d; return d; }

// NOTE (2026-06-20): personable rewrite drawn from Matt's prior /legacy/about copy,
// kept within the §11 editorial guardrails (no employer/industry/role specifics) and
// free of hard tool/lambda counts (those live in Evidence, to avoid drift). Pending
// Matt's review of the voice before deploy.
const ABOUT = `
  <p class="dx-kicker label">the experiment, in context</p>
  <h2 class="dx-title">An ordinary person, rebuilt in public — with AI.</h2>
  <p class="dx-prose">I've spent two decades making complicated systems reliable and getting people to actually use them. In early 2026 I turned that same thinking on myself — not a challenge, not a 30-day hack, but a proper system: the wearables already on my body, an AI that reads the numbers back to me every morning, and the discipline to publish the down weeks too.</p>
  <p class="dx-prose">This isn't Blueprint. No million-dollar lab, no team of doctors, no superhuman protocol — just consumer devices, Claude, and a commitment to keep it honest. Every number here is real; every failure is included. The bet is simple: <strong>numbers <em>and</em> meaning, kept personal.</strong> The anti-Blueprint.</p>
  <p class="dx-prose">A board of named AI experts argues about my data; Elena Voss writes the weekly chronicle; the Third Wall is where the machine's read meets how it actually felt. Everything here is correlative, never causal — patterns, flagged when thin, never dressed up as proof.</p>
  <p class="dx-prose">The throughline I keep coming back to: <strong>you could do this too</strong>. The cockpit and the data pages hold the live data; this is the why. If something here resonates — you're going through something similar, or just curious — I'd genuinely love to hear from you: <a href="mailto:matt@averagejoematt.com">matt@averagejoematt.com</a>.</p>`;

function entriesFor(s, data) {
  if (!data) return [];
  if (s.kind === "coaches") return [{ id: "team", title: "My Team", date: "the team's read on you" }].concat((data.coaches || []).map((c) => ({ id: c.persona_id, title: String(c.name || "").trim(), date: c.headline_stat || c.domain || "" })));
  if (s.kind === "podcast") return (data.episodes || []).map((e) => ({ id: e.week, title: e.title || `Week ${e.week}`, date: e.date, url: e.url, bytes: e.bytes, duration_sec: e.duration_sec, byline: e.byline, guest_id: e.guest_id, guest_name: e.guest_name, excerpt: e.excerpt, image_url: e.image_url || "", image_credit: e.image_credit || "" }));
  if (s.kind === "fieldnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "" }));
  if (s.kind === "posts") {
    const ps = data.posts || data.entries || (Array.isArray(data) ? data : []);
    // Genesis-anchored labels (truth-audit Phase 4b): installments before the genesis
    // date are the Prologue (numbered by date); after it they're Week N counted from
    // genesis. The raw `week` field can repeat (two "Week 1" shipped), so it never
    // drives the displayed label.
    const GENESIS = "2026-06-14";
    const ROMAN = ["I", "II", "III", "IV", "V", "VI"];
    const pre = ps.filter((p) => p.date && p.date < GENESIS).sort((a, b) => (a.date < b.date ? -1 : 1));
    const partOf = new Map(pre.map((p, i) => [p, ROMAN[i] || String(i + 1)]));
    const labelOf = (p) => {
      if (!p.date) return p.week ? `Week ${p.week}` : "";
      if (p.date < GENESIS) return pre.length > 1 ? `Prologue · Part ${partOf.get(p)}` : "Prologue";
      return `Week ${Math.max(1, Math.floor((Date.parse(p.date) - Date.parse(GENESIS)) / 6048e5) + 1)}`;
    };
    // id = date (unique) for selection/routing; week kept separately for podcast lookup.
    // The raw `week` repeated (two "Week 1"), so using it as the id collided two posts.
    return ps.map((p) => ({ id: p.date || String(p.week), week: p.week, label: labelOf(p), title: p.title || labelOf(p), date: p.date, excerpt: p.excerpt, meta: p.stats_line, word_count: p.word_count, url: p.url, image_url: p.image_url || "", image_credit: p.image_credit || "" }));
  }
  return [];
}

// CC-01/02 — a coach's page: stance (lead) · how it's going · report card · voice · relationships.
// Pure surfacing of /api/coach/{id}; honest empty-states before the data accrues.
// The coach's evolving, evidence-derived read of Matthew (STANCE#latest), in the
// normalized shape the API returns for both the live stance and the ladder fallback.
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
  h += `<p class="cr-rate">${tr.hit_rate_pct == null ? "Track record accruing" : esc(tr.hit_rate_pct) + "% hit-rate"} <span class="label">${esc(tr.n_note || "")}</span></p>`;
  if ((tr.recent || []).length) h += `<ul class="cr-calls">${tr.recent.map((r) => `<li class="cr-${esc(r.status)}"><span class="label">${esc(r.status)}</span> ${esc(r.metric || "")}${r.reason ? " — " + esc(r.reason) : ""}</li>`).join("")}</ul>`;
  else h += `<p class="dx-prose">No decided predictions yet — hits <em>and</em> misses will both show here as they resolve.</p>`;
  if (tr.caveat) h += `<p class="cr-caveat label">${esc(tr.caveat)}</p>`;
  const tl = (rc && rc.tuning_log) || [];
  if (tl.length) h += `<details class="cr-tuning"><summary class="label">tuning changelog (${tl.length})</summary><ul>${tl.map((e) => `<li><span class="label">${esc(e.date || "")} · ${esc(e.change_type || "")}</span> ${esc(e.summary || "")}</li>`).join("")}</ul></details>`;
  return h + `</section>`;
}
// CC-10 — "My Team": the team's collective read on Matthew right now (lead of /story/coaches/).
async function renderTeamView(read) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the team…</span></p>`;
  let d;
  try { d = await getJSON("/api/coach_team"); }
  catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load the team just now.</p>`; return; }
  let h = `<p class="dx-kicker label">your team · the collective read on you right now</p><h2 class="dx-title">My Team</h2>`;
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  if (d.lead) {
    const L = d.lead;
    h += `<section class="team-lead"><p class="dx-kicker label">running the program</p>`;
    h += `<div class="tl-head" style="--coach:${esc(L.color || "")}"><span class="sigil-lg">${sigil(L, { title: "" })}</span><span class="tl-name">${esc(L.name || "")}</span><span class="tl-role label">${esc(L.role || "")}</span></div>`;
    if (L.short_bio) h += `<p class="dx-prose tl-bio">${esc(L.short_bio)}</p>`;
    if (L.philosophy) h += `<blockquote class="tl-philosophy">${esc(L.philosophy)}</blockquote>`;
    if ((L.staff_focus || []).length) h += `<p class="tl-focus label">what he's got the staff focused on: ${L.staff_focus.map(esc).join(" · ")}</p>`;
    h += `</section>`;
  }
  if ((d.team_focus || []).length) {
    h += `<section class="team-focus"><p class="dx-kicker label">what the team is focused on for you${d.current_stage ? ` · the ${esc(d.current_stage)} stage` : ""}</p>`;
    h += `<ul class="tf-list">${d.team_focus.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></section>`;
  }
  h += `<section class="team-tension"><p class="dx-kicker label">where the team disagrees</p>`;
  if ((d.tensions || []).length) {
    h += `<ul class="tt-list">${d.tensions.map((t) => `<li><span class="label">${esc((t.coaches || []).map((c) => String(c).replace("_coach", "")).join(" ↔ ") || t.topic || "")}</span> ${esc(t.summary || "")}</li>`).join("")}</ul>`;
  } else {
    h += `<p class="dx-prose">No live disagreements right now — the team's aligned (or it's early and the threads haven't formed yet). When they pull in different directions, you'll see the tradeoff here.</p>`;
  }
  h += `</section>`;
  h += `<section class="team-huddle"><p class="dx-kicker label">the huddle — each coach's current read</p><ul class="th-list">`;
  for (const c of d.huddle || []) {
    h += `<li class="th-item" data-coach="${esc(c.persona_id)}" style="--coach:${esc(c.color || "")}"><button type="button" class="th-btn"><span class="th-name"><span class="coach-mark">${sigil(c, { title: "" })}</span>${esc(c.name || "")}</span><span class="th-head">${esc(c.headline || "")}</span>${c.watch ? `<span class="th-watch label">watching: ${esc(c.watch)}</span>` : ""}</button></li>`;
  }
  h += `</ul></section>`;
  read.innerHTML = h;
  read.querySelectorAll(".th-item").forEach((li) => li.querySelector(".th-btn").addEventListener("click", () => selectEntry(BYKEY["coaches"], li.dataset.coach)));
}

// CC-07 — the daily journey: each coach's recent outputs as a reverse-chron
// timeline, grouped Today / This week / Earlier. Honest empty-state when thin.
function coachJourneyHTML(ro) {
  if (!(ro && ro.length)) return "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dayMs = 86400000;
  const bucket = (d) => {
    const t = new Date(String(d) + "T00:00:00");
    const diff = Math.round((today - t) / dayMs);
    if (diff <= 0) return "Today";
    if (diff <= 7) return "This week";
    return "Earlier";
  };
  const groups = {};
  for (const o of ro) {
    const b = o.date ? bucket(o.date) : "Earlier";
    (groups[b] = groups[b] || []).push(o);
  }
  let h = `<section class="coach-journey"><p class="dx-kicker label">the daily journey</p>`;
  for (const label of ["Today", "This week", "Earlier"]) {
    if (!groups[label]) continue;
    h += `<p class="cj-band label">${label}</p><ol class="cj-list">`;
    h += groups[label]
      .map(
        (o) =>
          `<li><span class="cj-date label">${esc(o.date || "")}</span><span class="cj-sum">${esc(o.summary || "")}</span>` +
          (o.themes && o.themes.length ? `<span class="cj-themes label">${o.themes.slice(0, 3).map(esc).join(" · ")}</span>` : "") +
          `</li>`
      )
      .join("");
    h += `</ol>`;
  }
  return h + `</section>`;
}

// The character: the fictional background + personality that shapes this coach's
// prompt — who they are, how they show up, what they believe. Config-sourced.
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
// Live working hypotheses — open threads + pending predictions the coach is betting on now.
function coachHypothesesHTML(hyps) {
  if (!(hyps && hyps.length)) return "";
  return (
    `<section class="coach-hyp"><p class="dx-kicker label">working hypotheses · live bets</p><ul class="ch-list">` +
    hyps
      .map((x) => `<li class="ch-${esc(x.kind || "thread")}"><span class="label">${esc(x.kind || "thread")}</span> ${esc(x.claim)}</li>`)
      .join("") +
    `</ul></section>`
  );
}

async function renderCoachPage(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the coach…</span></p>`;
  let d;
  try { d = await getJSON(`/api/coach/${encodeURIComponent(id)}`); }
  catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this coach just now.</p>`; return; }
  let h = `<div class="coach-head" style="--coach:${esc(d.color || "")}"><span class="sigil-lg">${sigil(d, { title: "" })}</span><div><p class="dx-kicker label">${esc(d.board_role || d.domain || "")}</p><h2 class="dx-title">${esc(d.name || "")}</h2></div></div>`;
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  h += coachCharacterHTML(d.character);
  if (typeof d.daily === "string" && d.daily.trim()) {
    h += `<section class="coach-daily"><p class="dx-kicker label">today's reflection</p><p class="cd-text">${esc(d.daily)}</p></section>`;  // CC-08
  }
  h += coachStanceHTML(d.stance);
  h += coachHypothesesHTML(d.working_hypotheses);
  const ro = d.recent_outputs || [];
  h += `<section class="coach-progress"><p class="dx-kicker label">how it's going</p>`;
  h += ro.length
    ? `<p class="coach-latest"><span class="label">${esc(ro[0].date || "")}</span> ${esc(ro[0].summary || "")}</p>`
    : `<p class="dx-prose">Tracking begins as data arrives — this coach narrates honest progress against its watches here, down-weeks included.</p>`;
  h += `</section>`;
  h += coachReportHTML(d.report_card);
  const v = d.voice || {};
  if (typeof v.few_shot_example === "string" && v.few_shot_example.trim()) {
    h += `<section class="coach-voice"><p class="dx-kicker label">voice signature</p><blockquote class="cv-example">${esc(v.few_shot_example)}</blockquote></section>`;
  }
  const rel = d.relationships || {};
  const edge = (e) => `${esc(String(e.coach || "").replace("_coach", ""))} (${esc(e.weight)})`;
  if ((rel.leans_on || []).length || (rel.leaned_on_by || []).length) {
    h += `<section class="coach-rel"><p class="dx-kicker label">on the team</p>`;
    if ((rel.leans_on || []).length) h += `<p class="cr-edges"><span class="label">leans on</span> ${rel.leans_on.map(edge).join(" · ")}</p>`;
    if ((rel.leaned_on_by || []).length) h += `<p class="cr-edges"><span class="label">leaned on by</span> ${rel.leaned_on_by.map(edge).join(" · ")}</p>`;
    h += `</section>`;
  }
  h += coachJourneyHTML(ro);  // CC-07: the daily-journey timeline (spec anatomy: last)
  read.innerHTML = h;
}

async function renderRead(s, id) {
  const read = $("[data-dx-read]");
  if (s.kind === "about") { read.innerHTML = ABOUT; return; }
  if (s.kind === "coaches") { if (String(id) === "team") { await renderTeamView(read); } else { await renderCoachPage(read, id); } return; }
  if (s.kind === "podcast") {
    const data = await secFetch(s);
    const all = entriesFor(s, data);
    // The pipeline can skip a week (e.g. the chronicle isn't written yet); it records
    // a `pending` marker so we say WHY instead of going silent (matches the show's honesty).
    const pendingHTML = data && data.pending && data.pending.display
      ? `<aside class="panel-pending"><p class="dx-kicker label">next episode</p><p class="dx-prose">${esc(data.pending.display)}</p></aside>`
      : "";
    const ent = all.find((x) => String(x.id) === String(id)) || all[0];
    if (!ent) { read.innerHTML = pendingHTML + `<p class="dx-prose">No episodes yet — the first weekly review drops here once the chronicle's been running a week.</p>`; return; }
    const isWav = /\.wav$/i.test(ent.url || "");
    const secs = ent.duration_sec || Math.round((ent.bytes || 0) / (isWav ? 48000 : 2097));  // WAV=24kHz·16-bit·mono; else MP3 est
    const mins = Math.max(1, Math.round(secs / 60));
    // Throughline: when the episode names its guest coach, link the byline to that
    // coach's page (/story/coaches/#<id>) so the show ties back into the team.
    const byline = (ent.guest_id && ent.guest_name)
      ? `Elena + <a href="/coaching/coaches/#${esc(ent.guest_id)}">${esc(ent.guest_name)}</a>`
      : esc(ent.byline || "Elena + a coach");
    // The Panel ledger — the running scoreboard of coach bets + outcomes (proof-of-honesty).
    const lg = await tryJSON("/api/panel_ledger");
    let ledgerHTML = "";
    if (lg && (lg.ledger || []).length) {
      // One bet per week by design — a historical re-publish once appended a
      // paraphrased duplicate (the wk1 double). Keep the NEWEST entry per week;
      // the stored ledger is fixed too, this is the render-side belt-and-braces.
      const _seen = new Set();
      const ledger = [...lg.ledger].reverse().filter((b) => {
        const k = String(b.week);
        if (_seen.has(k)) return false;
        _seen.add(k);
        return true;
      }).reverse();
      const r = lg.record || {};
      ledgerHTML =
        `<section class="panel-ledger"><p class="dx-kicker label">the bets · ${r.won || 0} won · ${r.lost || 0} lost${r.open ? ` · ${r.open} open` : ""}</p>` +
        `<ul class="pl-list">${ledger.slice(0, 12).map((b) => `<li class="pl-${esc(b.outcome)}"><span class="pl-tag label">wk${esc(b.week)} · ${esc(b.outcome)}</span> ${esc(b.bet)}</li>`).join("")}</ul>` +
        (lg.disclosure ? `<p class="correlative">${esc(lg.disclosure)}</p>` : "") +
        `</section>`;
    }
    const cover = ent.image_url
      ? `<figure class="editorial-img editorial-cover"><img class="img-duotone" src="${esc(ent.image_url)}" alt="" loading="lazy">${ent.image_credit ? `<figcaption class="img-credit label">${esc(ent.image_credit)}</figcaption>` : ""}</figure>`
      : "";
    // Tie the episode back to the week it reviews — the missing podcast→chronicle backlink.
    // (the podcast entry carries the week as its id, not a `week` field.)
    const _wk = ent.week ?? ent.id;
    const _pj = _wk != null ? await tryJSON("/journal/posts.json") : null;
    const _wkPost = _pj && _pj.posts ? _pj.posts.find((p) => String(p.week) === String(_wk)) : null;
    const chronLink = _wkPost ? `<p class="dx-xlink"><a href="/story/chronicle/#${esc(_wkPost.date)}">Read Week ${esc(_wk)}'s chronicle →</a></p>` : "";
    read.innerHTML =
      pendingHTML +
      cover +
      `<p class="dx-kicker label">the podcast · weekly review · two AI voices</p>` +
      `<h2 class="dx-title">${esc(ent.title)}</h2>` +
      (ent.date ? `<p class="dx-stats label">${esc(ent.date)}</p>` : "") +
      `<div class="dx-listen"><audio controls preload="none" src="${esc(ent.url)}"></audio><span class="label">listen · ${byline} (~${mins} min)</span></div>` +
      (ent.excerpt ? `<p class="dx-prose">${esc(ent.excerpt)}</p>` : "") +
      chronLink +
      ledgerHTML +
      (ent.transcript_url ? `<section class="dx-transcript" data-transcript hidden></section>` : "");
    // Transcript + in-page chapters (the host's questions). No audio timestamps
    // exist (single-pass synthesis), so chapters jump within the read, not the audio.
    if (ent.transcript_url) renderTranscript(ent.transcript_url, read.querySelector("[data-transcript]"));
    return;
  }
  if (s.kind === "timeline") {
    read.innerHTML = `<p class="dx-kicker label">${esc(s.kicker)}</p><h2 class="dx-title">The journey so far</h2><p class="dx-loading shimmer">Loading the timeline…</p>`;
    // The serial spine: walk backwards through the arc, jump into the chronicle week each
    // moment was written. Reads the existing journey-timeline + journey + the chronicle manifest.
    const [d, jr, pj, rc, pres] = await Promise.all([secFetch(s), tryJSON("/api/journey"), tryJSON("/journal/posts.json"), tryJSON("/api/recap"), tryJSON("/api/presence")]);
    const events = (d && d.events ? d.events.slice() : []);
    const posts = (pj && pj.posts) || [];
    events.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));  // newest-first → "walk back"
    const GEN = "2026-06-14", day1 = Date.parse(GEN), now = Date.now();
    const dayN = Math.max(1, Math.floor((now - day1) / 864e5) + 1);
    const weekN = Math.max(1, Math.floor((now - day1) / 6048e5) + 1);
    const lost = jr && jr.lost_lbs != null ? Math.round(jr.lost_lbs * 10) / 10 : null;
    const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const moLabel = (mo) => { const m = /^(\d{4})-(\d{2})/.exec(mo || ""); return m ? `${MON[+m[2] - 1]} ${m[1]}` : mo; };
    // The chronicle installment that narrates a given date = the soonest week ending on/after it.
    const postFor = (date) => { let best = null; for (const p of posts) { if (!p.date) continue; if (p.date >= date && (!best || p.date < best.date)) best = p; } return best || posts[0] || null; };
    const TYPE = { weight: "wt", level_up: "lv", experiment: "ex", discovery: "dx", correlation: "co", milestone: "ms", life_event: "le" };
    // Stat line (always shown): Day/Week/lbs + the jump link.
    const statLine = `<p class="tl-recap-h">Day ${dayN} · Week ${weekN}${lost != null ? ` · <span class="tl-recap-em">${lost} lbs down</span>` : ""}</p>` +
      `<p class="tl-recap-s">${events.length} key moment${events.length === 1 ? "" : "s"}, newest first.${events.length ? ` <a href="#tl-genesis">Jump to Day 1 ↓</a>` : ""}</p>`;
    // Phase 3: prefer Elena's "previously on" cold-open when /api/recap has one; else
    // fall back to the front-end-derived stat aside (no regression pre-recap).
    const er = rc && rc.recap;
    let recap;
    if (er && er.story_so_far) {
      const beats = (er.recent_beats || []).slice(0, 4).map((b) => {
        const lbl = b.week != null ? `Week ${b.week}` : (b.date || "");
        const lk = b.date ? `<a href="/story/chronicle/#${esc(b.date)}">${esc(lbl)}</a>` : `<span>${esc(lbl)}</span>`;
        return `<li class="tl-recap-beat"><span class="tl-recap-beat-k label">${lk}</span> ${esc(b.beat || "")}</li>`;
      }).join("");
      recap = `<aside class="tl-recap tl-recap-elena">` +
        `<p class="tl-recap-k label">previously on · the measured life</p>` +
        `<p class="tl-recap-story">${esc(er.story_so_far)}</p>` +
        (beats ? `<ul class="tl-recap-beats">${beats}</ul>` : "") +
        (er.where_we_are_now ? `<p class="tl-recap-now">${esc(er.where_we_are_now)}</p>` : "") +
        statLine +
        `<p class="tl-recap-by label">— Elena Voss</p></aside>`;
    } else {
      recap = `<aside class="tl-recap"><p class="tl-recap-k label">the story so far</p>` + statLine + `</aside>`;
    }
    // The quiet stretch (2026-06-30): when the owner's own logging has gone quiet —
    // or he's just returned — the serial spine says so, honestly. Fed by the
    // fail-closed /api/presence. No red; the arc simply acknowledges the lull.
    let quiet = "";
    if (pres && (pres.in_lull || pres.returned)) {
      const WD = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      let since = "";
      if (pres.last_log_date) { const dt = new Date(pres.last_log_date + "T12:00:00"); since = WD[dt.getDay()] || ""; }
      let head, line;
      if (pres.returned) {
        head = "the return";
        const n = pres.resumed_after_days;
        line = `Back after ${n ? n + (n === 1 ? " day" : " days") : "a stretch"} away.`;
        const wd = pres.weight_delta_over_gap_lbs;
        if (wd != null && wd > 0) line += ` The scale came back up about ${Math.abs(wd)} lb over the gap — noted, not judged.`;
        else if (pres.passive_still_flowing) line += " The wearables kept the thread while the logs were dark.";
      } else {
        head = "the quiet stretch";
        const n = pres.gap_days;
        if (pres.planned_pause) {
          line = `The logs have been quiet${since ? ` since ${since}` : ""} — a planned break.`;
        } else {
          line = `The logs have gone quiet${since ? ` since ${since}` : ""} — ${n != null ? n : "several"} ${n === 1 ? "day" : "days"} without an entry.`;
          if (pres.passive_still_flowing) line += " The wearables kept recording; the coaches are watching for the return.";
        }
      }
      quiet = `<aside class="tl-quiet" data-cls="${esc(pres.returned ? "returned" : (pres.presence_class || ""))}">` +
        `<p class="tl-quiet-k label">${head}</p><p class="tl-quiet-line">${esc(line)}</p></aside>`;
    }
    let body;
    if (events.length) {
      let curMonth = "";
      body = `<ol class="tl">`;
      events.forEach((e, i) => {
        const dt = String(e.date || "").slice(0, 10), mo = dt.slice(0, 7), last = i === events.length - 1;
        if (mo !== curMonth) { curMonth = mo; body += `<li class="tl-month" aria-hidden="true"><span class="label">${esc(moLabel(mo))}</span></li>`; }
        const p = postFor(dt);
        const xlink = p ? `<a class="tl-x" href="/story/chronicle/#${esc(p.date)}">Read ${esc(p.label || ("Week " + p.week))} →</a>`
          : (e.link ? `<a class="tl-x" href="${esc(e.link)}">see more →</a>` : "");
        body += `<li class="tl-item tl-${esc(TYPE[e.type] || "ms")}"${last ? ' id="tl-genesis"' : ""}>` +
          `<span class="tl-dot" aria-hidden="true"></span>` +
          `<div class="tl-body"><span class="tl-date label">${esc(dt)}</span>` +
          `<p class="tl-title">${esc(e.title || e.type || "")}</p>` +
          (e.body ? `<p class="tl-note">${esc(e.body)}</p>` : "") + xlink + `</div></li>`;
      });
      body += `</ol>`;
    } else {
      body = `<p class="dx-prose">No milestones logged yet — the timeline fills as the score climbs. Day 1 starts the clock.</p>`;
    }
    read.innerHTML = `<p class="dx-kicker label">${esc(s.kicker)}</p><h2 class="dx-title">The journey so far</h2>` +
      `<p class="dx-prose">Walk back through the arc — milestones, life events, and <strong>character level-ups</strong> — and jump into the chronicle week each moment was written. <a href="/method/character/">What's a character level?</a></p>` +
      recap + quiet + body;
    return;
  }
  if (s.kind === "fieldnotes") {
    read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
    try {
      const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`); const e = d.entry || {};
      // The Third Wall, explicit: the AI's read (them) → Matthew's response (me).
      const ai = [["The AI's read", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"]].filter((v) => v[1]);
      const mattText = e.matthew_notes || e.matthew_agreement;
      const mattVoice = mattText
        ? `<div class="voice human"><span class="who">Matthew</span><p class="what">${esc(mattText)}</p></div>`
        : `<div class="voice human voice-pending"><span class="who">Matthew</span><p class="what">Pending Matthew's response — he hasn't weighed in on the AI's read of this week yet.</p></div>`;
      const hasAny = ai.length || mattText;
      read.innerHTML = `<p class="dx-kicker label">field note · week ${esc(id)} · the AI's read ↔ Matthew's response${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
        (hasAny
          ? ai.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("") + mattVoice
          : `<p class="dx-prose">No field note recorded for this week yet.</p>`);
    } catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this field note just now.</p>`; }
    enhanceCoachNames(read);  // CC-04: coach-name popovers in lab notes
    return;
  }
  // posts (chronicle / journal)
  const all = entriesFor(s, await secFetch(s));
  const ent = all.find((x) => String(x.id) === String(id));
  if (!ent) { read.innerHTML = `<p class="dx-prose">Pick an entry to read it here.</p>`; return; }
  // Honest read-time from the real word count (~220 wpm) — replaces nothing, adds truth.
  const readMins = ent.word_count ? Math.max(1, Math.round(Number(ent.word_count) / 220)) : null;
  const readmore = ent.url
    ? `<p class="dx-readmore"><button type="button" class="dx-readfull" data-url="${esc(ent.url)}">Read the full piece${ent.word_count ? ` (${esc(ent.word_count)} words · ~${readMins} min)` : ""} →</button></p><div class="dx-fulltext" data-fulltext hidden></div>`
    : (ent.word_count ? `<p class="dx-foot label">${esc(ent.word_count)} words · ~${readMins} min</p>` : "");
  const episode = s.key === "chronicle" ? await podcastEpisode(ent) : null;
  // Duration: trust the real duration_sec first; the byte estimate must be WAV-aware
  // (24kHz·16-bit·mono ≈ 48000 B/s) — the old MP3-only guess labeled a 12.9 MB WAV
  // "~102 min". Mirrors the correct logic at the podcast renderer above.
  const _epSecs = episode ? (episode.duration_sec || Math.round((episode.bytes || 0) / (/\.wav(\?|$)/i.test(episode.url || "") ? 48000 : 2097))) : 0;
  const listen = episode
    ? `<div class="dx-listen"><audio controls preload="none" src="${esc(episode.url)}"></audio><span class="label">listen · AI-voiced (~${Math.max(1, Math.round(_epSecs / 60))} min)</span></div>`
    : "";
  const art = ent.image_url
    ? `<figure class="editorial-img"><img class="img-duotone" src="${esc(ent.image_url)}" alt="" loading="lazy">${ent.image_credit ? `<figcaption class="img-credit label">${esc(ent.image_credit)}</figcaption>` : ""}</figure>`
    : "";
  // "Previously" — the two prior installments, so a reader landing mid-series can step
  // backwards through the arc (the serial scaffold). Chronicle only; needs ≥1 earlier entry.
  const priors = s.key === "chronicle" && ent.date
    ? all.filter((x) => x.date && x.date < ent.date).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 2)
    : [];
  const prevRail = priors.length
    ? `<aside class="dx-prev"><p class="dx-prev-k label">previously</p><ul class="dx-prev-list">${priors.map((x) => `<li><button type="button" class="dx-prevlink" data-id="${esc(x.id)}"><span class="dx-prev-lbl label">${esc(x.label || ("week " + x.id))}</span><span class="dx-prev-t">${esc(x.title || "")}</span></button></li>`).join("")}</ul></aside>`
    : "";
  read.innerHTML = art + `<p class="dx-kicker label">${s.key === "chronicle" ? "chronicle · Elena Voss" : "journal"}${ent.label ? ` · ${esc(ent.label)}` : ent.id ? ` · week ${esc(ent.id)}` : ""}${ent.date ? ` · ${esc(ent.date)}` : ""}</p>` +
    `<h2 class="dx-title">${esc(ent.title)}</h2>` + listen + (ent.meta ? `<p class="dx-stats label">${esc(ent.meta)}</p>` : "") +
    prevRail + `<p class="dx-prose dx-excerpt">${esc(ent.excerpt || "")}</p>` + readmore + dispatchFoot(s, ent, all);
  read.querySelectorAll(".dx-prevlink").forEach((b) => b.addEventListener("click", () => selectEntry(s, b.dataset.id)));
  const rf = read.querySelector(".dx-readfull");
  if (rf) rf.addEventListener("click", () => loadFull(rf, read.querySelector("[data-fulltext]"), read.querySelector(".dx-excerpt")));
  const sf = read.querySelector(".dx-startfirst");
  if (sf) sf.addEventListener("click", () => selectEntry(s, sf.dataset.startid));
  enhanceCoachNames(read);  // CC-04: coach-name popovers in chronicle/journal prose
}

// PG-03 — the per-dispatch foot: a subscribe CTA (the chronicle is the only
// organic-share engine) + a "start from the beginning" link. The first dispatch
// is the chronologically-earliest by date (week labels run -4…N, non-linear).
function dispatchFoot(s, ent, all) {
  const sorted = (all || []).slice().sort((a, b) =>
    String(a.date || "").localeCompare(String(b.date || "")) || (Number(a.id) - Number(b.id)));
  const first = sorted[0];
  const startLink = (first && String(first.id) !== String(ent.id))
    ? `<button type="button" class="dx-startfirst" data-startid="${esc(first.id)}">↩ Start from the beginning — &ldquo;${esc(first.title)}&rdquo;</button>`
    : "";
  return `
    <aside class="dx-subscribe" aria-label="Follow the experiment">
      <p class="dx-sub-h">Follow the experiment as it's written.</p>
      <p class="dx-sub-p">New dispatches land here first — the down weeks included. No selling, unsubscribe anytime.</p>
      <p class="dx-sub-cta"><a class="dx-sub-btn" href="/subscribe/">Subscribe by email</a><a class="dx-sub-rss" href="/rss.xml">or follow via RSS</a></p>
      ${startLink}
    </aside>`;
}

// Expand the full chronicle/journal piece inline (same-origin, platform-authored content):
// fetch the post page, lift its <div class="prose">, strip old promo/footer blocks, render in v4.
async function loadFull(btn, target, excerptEl) {
  const url = btn.dataset.url;
  btn.textContent = "Loading the full piece…"; btn.disabled = true;
  try {
    const r = await fetch(url); if (!r.ok) throw new Error("HTTP " + r.status);
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    const prose = doc.querySelector(".prose") || doc.querySelector(".post-body");
    if (!prose) throw new Error("no prose");
    prose.querySelectorAll("script,style,iframe,link,noscript,.discord-community-card,.community-card-header,.community-card-body,.community-card-cta,.fp-cross-footer,.signature").forEach((e) => e.remove());
    target.innerHTML = prose.innerHTML;
    target.hidden = false;
    enhanceCoachNames(target);  // CC-04: popovers in the expanded full piece too
    if (excerptEl) excerptEl.remove();          // the excerpt is now redundant
    btn.closest(".dx-readmore").remove();
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    btn.textContent = "Open the full piece →"; btn.disabled = false;
    btn.onclick = () => { location.href = url; };   // graceful fallback to the page
  }
}

function selectEntry(s, id, silent) {
  document.querySelectorAll(".dx-item").forEach((b) => b.classList.toggle("is-active", String(b.dataset.id) === String(id)));
  if (!silent) { try { history.replaceState({ sec: s.key, id }, "", `/story/${s.key}/#${id}`); } catch (e) {} }
  renderRead(s, id);
}
async function selectSection(key, preId, push = true) {
  const s = BYKEY[key]; if (!s) return;
  document.querySelectorAll(".dx-tab").forEach((t) => { const on = t.dataset.sec === key; t.classList.toggle("is-active", on); t.setAttribute("aria-pressed", String(on)); });
  if (push) { try { history.pushState({ sec: key }, "", `/story/${key}/`); } catch (e) {} }
  document.title = `${s.label} — The Story — averagejoematt`;
  const listEl = $("[data-dx-list]");
  if (s.kind === "about" || s.kind === "timeline") { listEl.innerHTML = `<li class="dx-empty">${esc(s.kicker)}</li>`; renderRead(s, null); return; }
  listEl.innerHTML = `<li class="dx-empty"><span class="shimmer">Loading…</span></li>`;
  const entries = entriesFor(s, await secFetch(s));
  if (!entries.length) { listEl.innerHTML = `<li class="dx-empty">Nothing published here yet — it fills as the experiment runs.</li>`; $("[data-dx-read]").innerHTML = ""; return; }
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}${isNewSince(e.date) ? ` <span class="dx-new label">new</span>` : ""}</span><span class="dx-item-d label">${esc(e.date || "")}</span></button></li>`).join("");
  listEl.querySelectorAll(".dx-item").forEach((b) => b.addEventListener("click", () => selectEntry(s, b.dataset.id)));
  const initId = preId && entries.some((e) => String(e.id) === String(preId)) ? preId : entries[0].id;
  selectEntry(s, initId, true);
}

function build() {
  const tabsEl = $("[data-dx-tabs]"); if (!tabsEl) return;
  tabsEl.innerHTML = SECTIONS.map((s) => `<button class="dx-tab" data-sec="${s.key}" aria-pressed="false">${esc(s.label)}</button>`).join("");
  tabsEl.querySelectorAll(".dx-tab").forEach((b) => b.addEventListener("click", () => selectSection(b.dataset.sec)));
  const start = (window.__DISPATCH_START__ && BYKEY[window.__DISPATCH_START__]) ? window.__DISPATCH_START__ : "chronicle";
  const hashId = (location.hash || "").replace("#", "") || undefined;
  selectSection(start, hashId, false);
}
window.addEventListener("popstate", (e) => { const sec = (e.state && e.state.sec) || (location.pathname.match(/\/story\/([^/]+)\//) || [])[1] || "chronicle"; selectSection(sec, e.state && e.state.id, false); });

function wireTheme() {
  const b = $(".theme-toggle"); if (!b) return;
  b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} });
}
wireTheme();
build();
stampGenesis();  // cross-site Day-N/Week-N anchor (matches the Home hero)

// uplevel P5 — the same reader-keyed since-ribbon on the Story page (reads the
// cockpit's stamp, never writes it). Injected under the header; self-hides.
(function storySince() {
  try {
    const head = document.querySelector(".dx-head");
    if (!head) return;
    const rib = document.createElement("div");
    rib.className = "home-since dx-since";
    rib.hidden = true;
    head.insertAdjacentElement("afterend", rib);
    mountSinceRibbon(rib);
  } catch (e) { /* enhancement only */ }
})();
