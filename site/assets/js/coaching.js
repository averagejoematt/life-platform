/*
  coaching.js — Door 4 "The Coaching" (/coaching/)
  ----------------------------------------------------------------------------
  Promoted out of the Story tabs into its own door (2026-06-20, Option A). The AI
  team that reads the data: "My Team" (the collective read) → each coach's page
  (master-detail) → the AI Lab Notes (the Third Wall: the AI's weekly read ↔
  Matthew's response). Reuses the dx- and coach- styles from story.css; pure
  surfacing of /api/coaches, /api/coach_team, /api/coach/{id}, /api/field_notes —
  nothing invented, honest empty-states before data accrues.

  The coach PAGE leads with the essentials (stance + report card) and discloses
  the rest (character, voice, relationships, journey) so it's no longer one long
  scroll — and one type system (coaches speak serif; labels/data mono).
*/
import { enhanceCoachNames, stampGenesis } from "/assets/js/coach_popover.js";

const SECTIONS = [
  { key: "coaches", label: "The Team", kicker: "the AI team reading your data", kind: "coaches", url: "/api/coaches" },
  { key: "lab-notes", label: "AI lab notes", kicker: "the AI's read ↔ how it felt", kind: "fieldnotes", url: "/api/field_notes" },
  // PG-ENG-2 — reader questions the board has answered (the payoff for "ask the board").
  // Static feed published by scripts/publish_board_answer.py; empty-but-honest until the
  // first answer lands (tryJSON → null → "nothing here yet").
  { key: "qa", label: "Reader Q&A", kicker: "the board answers your questions", kind: "qa", url: "/board_answers/answers.json" },
];
const BYKEY = Object.fromEntries(SECTIONS.map((s) => [s.key, s]));

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }
const cache = {};
async function secFetch(s) { if (!s.url) return null; if (cache[s.key]) return cache[s.key]; const d = await tryJSON(s.url); cache[s.key] = d; return d; }

function entriesFor(s, data) {
  if (!data) return [];
  if (s.kind === "coaches") return [{ id: "team", title: "🧭 My Team", date: "the team's read on you" }].concat((data.coaches || []).map((c) => ({ id: c.persona_id, title: `${c.emoji || ""} ${c.name}`.trim(), date: c.headline_stat || c.domain || "" })));
  if (s.kind === "fieldnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "" }));
  if (s.kind === "qa") return (data.answers || []).slice().reverse().map((a) => ({ id: a.id, title: a.question, date: a.answered_at || "" }));
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
  // P2.4 — frame the empty track record as anticipation, not a placeholder: the score is a
  // clock the reader watches start, not a missing number.
  h += `<p class="cr-rate">${tr.hit_rate_pct == null ? `Score unlocks as predictions resolve <span class="label">— week one of N; first calls land in the coming weeks</span>` : esc(tr.hit_rate_pct) + "% hit-rate" + ` <span class="label">${esc(tr.n_note || "")}</span>`}</p>`;
  if ((tr.recent || []).length) h += `<ul class="cr-calls">${tr.recent.map((r) => `<li class="cr-${esc(r.status)}"><span class="label">${esc(r.status)}</span> ${esc(r.metric || "")}${r.reason ? " — " + esc(r.reason) : ""}</li>`).join("")}</ul>`;
  else h += `<p class="dx-prose">No decided predictions yet — hits <em>and</em> misses will both show here as they resolve.</p>`;
  if (tr.caveat) h += `<p class="cr-caveat label">${esc(tr.caveat)}</p>`;
  const tl = (rc && rc.tuning_log) || [];
  if (tl.length) h += `<details class="cr-tuning"><summary class="label">tuning changelog (${tl.length})</summary><ul>${tl.map((e) => `<li><span class="label">${esc(e.date || "")} · ${esc(e.change_type || "")}</span> ${esc(e.summary || "")}</li>`).join("")}</ul></details>`;
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
function coachJourneyHTML(ro) {
  if (!(ro && ro.length)) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dayMs = 86400000;
  const bucket = (d) => { const t = new Date(String(d) + "T00:00:00"); const diff = Math.round((today - t) / dayMs); if (diff <= 0) return "Today"; if (diff <= 7) return "This week"; return "Earlier"; };
  const groups = {};
  for (const o of ro) { const b = o.date ? bucket(o.date) : "Earlier"; (groups[b] = groups[b] || []).push(o); }
  let h = `<section class="coach-journey"><p class="dx-kicker label">the daily journey</p>`;
  for (const label of ["Today", "This week", "Earlier"]) {
    if (!groups[label]) continue;
    h += `<p class="cj-band label">${label}</p><ol class="cj-list">`;
    h += groups[label].map((o) => `<li><span class="cj-date label">${esc(o.date || "")}</span><span class="cj-sum">${esc(o.summary || "")}</span>` + (o.themes && o.themes.length ? `<span class="cj-themes label">${o.themes.slice(0, 3).map(esc).join(" · ")}</span>` : "") + `</li>`).join("");
    h += `</ol>`;
  }
  return h + `</section>`;
}
// A disclosed (collapsed) block, so the coach page leads with the essentials
// (stance + report) and the deeper context is one click away — not one long stack.
function disclose(summary, innerHTML) {
  if (!innerHTML) return "";
  return `<details class="coach-more"><summary class="dx-kicker label">${esc(summary)}</summary>${innerHTML}</details>`;
}

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
    h += `<div class="tl-head"><span class="tl-name">${esc(L.emoji || "")} ${esc(L.name || "")}</span><span class="tl-role label">${esc(L.role || "")}</span></div>`;
    if (L.short_bio) h += `<p class="dx-prose tl-bio">${esc(L.short_bio)}</p>`;
    if (L.philosophy) h += `<blockquote class="tl-philosophy">${esc(L.philosophy)}</blockquote>`;
    if ((L.staff_focus || []).length) h += `<p class="tl-focus label">what he's got the staff focused on: ${L.staff_focus.map(esc).join(" · ")}</p>`;
    h += `</section>`;
  }
  if ((d.team_focus || []).length) {
    h += `<section class="team-focus"><p class="dx-kicker label">what the team is focused on for you${d.current_stage ? ` · the ${esc(d.current_stage)} stage` : ""}</p>`;
    h += `<ul class="tf-list">${d.team_focus.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></section>`;
  }
  h += `<section class="team-tension"><p class="dx-kicker label">where the team disagrees — the argument, not just the headline</p>`;
  // P2.4 — expand the cryptic "Coach ↔ Coach" lines into readable arguments: the two positions
  // head-to-head + the integrator's call (the same fields WQA-06 surfaced on the board).
  const _tt = (d.tensions || []).filter((t) => t && (t.position_a || t.position_b || t.summary));
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
    h += `<p class="dx-prose">No live disagreements right now — the team's aligned (or it's early and the threads haven't formed yet). When they pull in different directions, you'll see the tradeoff here.</p>`;
  }
  h += `</section>`;
  h += `<section class="team-huddle"><p class="dx-kicker label">the huddle — each coach's current read</p><ul class="th-list">`;
  for (const c of d.huddle || []) {
    h += `<li class="th-item" data-coach="${esc(c.persona_id)}"><button type="button" class="th-btn"><span class="th-name">${esc(c.emoji || "")} ${esc(c.name || "")}</span><span class="th-head">${esc(c.headline || "")}</span>${c.watch ? `<span class="th-watch label">watching: ${esc(c.watch)}</span>` : ""}</button></li>`;
  }
  h += `</ul></section>`;
  read.innerHTML = h;
  read.querySelectorAll(".th-item").forEach((li) => li.querySelector(".th-btn").addEventListener("click", () => selectEntry(BYKEY["coaches"], li.dataset.coach)));
}

async function renderCoachPage(read, id) {
  read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the coach…</span></p>`;
  let d;
  try { d = await getJSON(`/api/coach/${encodeURIComponent(id)}`); }
  catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this coach just now.</p>`; return; }
  // Header
  let head = `<p class="dx-kicker label">${esc(d.emoji || "")} ${esc(d.board_role || d.domain || "")}</p>`;
  head += `<h2 class="dx-title">${esc(d.name || "")}</h2>`;
  if (d.disclosure) head += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  const ro = d.recent_outputs || [];

  // ── Tab 1: Current read — today's reflection, the stance, how it's going ──
  let cur = "";
  if (typeof d.daily === "string" && d.daily.trim()) {
    cur += `<section class="coach-daily"><p class="dx-kicker label">today's reflection</p><p class="cd-text">${esc(d.daily)}</p></section>`;
  }
  cur += coachStanceHTML(d.stance && d.stance.rung);
  cur += `<section class="coach-progress"><p class="dx-kicker label">how it's going</p>`;
  cur += ro.length
    ? `<p class="coach-latest"><span class="label">${esc(ro[0].date || "")}</span> ${esc(ro[0].summary || "")}</p>`
    : `<p class="dx-prose">Tracking begins as data arrives — this coach narrates honest progress against its watches here, down-weeks included.</p>`;
  cur += `</section>`;

  // ── Tab 2: Track record — report card, live bets, the daily journey ──
  let track = coachReportHTML(d.report_card) + coachHypothesesHTML(d.working_hypotheses) + coachJourneyHTML(ro);
  if (!track.trim()) track = `<p class="dx-prose">No track record yet — predictions and the daily journey land here as the experiment runs.</p>`;

  // ── Tab 3: Bio — who they are, their voice, where they sit on the team ──
  let bio = coachCharacterHTML(d.character);
  const v = d.voice || {};
  if (typeof v.few_shot_example === "string" && v.few_shot_example.trim()) {
    bio += `<section class="coach-voice"><p class="dx-kicker label">voice signature</p><blockquote class="cv-example">${esc(v.few_shot_example)}</blockquote></section>`;
  }
  const rel = d.relationships || {};
  const edge = (e) => `${esc(String(e.coach || "").replace("_coach", ""))} (${esc(e.weight)})`;
  if ((rel.leans_on || []).length || (rel.leaned_on_by || []).length) {
    let rh = `<section class="coach-rel"><p class="dx-kicker label">on the team</p>`;
    if ((rel.leans_on || []).length) rh += `<p class="cr-edges"><span class="label">leans on</span> ${rel.leans_on.map(edge).join(" · ")}</p>`;
    if ((rel.leaned_on_by || []).length) rh += `<p class="cr-edges"><span class="label">leaned on by</span> ${rel.leaned_on_by.map(edge).join(" · ")}</p>`;
    bio += rh + `</section>`;
  }
  if (!bio.trim()) bio = `<p class="dx-prose">Bio fills in from this coach's profile.</p>`;

  // ── Assemble the tabset (the review's ask: Bio / track record / current feedback) ──
  const tabs = [
    { key: "current", label: "Current read", html: cur },
    { key: "track", label: "Track record", html: track },
    { key: "bio", label: "Bio", html: bio },
  ];
  let h = head;
  h += `<div class="tabset" role="tablist" aria-label="Coach views">` +
    tabs.map((t, i) => `<button class="tab" role="tab" type="button" data-coachtab="${t.key}" aria-selected="${i === 0 ? "true" : "false"}">${esc(t.label)}</button>`).join("") +
    `</div>`;
  h += tabs.map((t, i) => `<div class="tabpanel" role="tabpanel" data-coachpanel="${t.key}"${i === 0 ? "" : " hidden"}>${t.html}</div>`).join("");
  read.innerHTML = h;
  read.querySelectorAll("[data-coachtab]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.coachtab;
    read.querySelectorAll("[data-coachtab]").forEach((x) => x.setAttribute("aria-selected", x === b ? "true" : "false"));
    read.querySelectorAll("[data-coachpanel]").forEach((p) => { p.hidden = p.dataset.coachpanel !== k; });
  }));
  enhanceCoachNames(read);
}

async function renderRead(s, id) {
  const read = $("[data-dx-read]");
  if (s.kind === "coaches") { if (String(id) === "team") { await renderTeamView(read); } else { await renderCoachPage(read, id); } return; }
  if (s.kind === "fieldnotes") {
    read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
    try {
      const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`); const e = d.entry || {};
      // The Third Wall, explicit: the AI's read (them) → Matthew's response (me).
      const ai = [["The AI's read", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"]].filter((v) => v[1]);
      const mattText = e.matthew_notes || e.matthew_agreement;
      // P3.1 — the reply SLOT is first-class even while empty: the wall is a dialogue, and
      // Matthew's half is HELD SPACE that's waiting, not absent. Inviting, never a nag; the
      // reply mechanic itself is intentionally not wired here (his words, his hand).
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
    return;
  }
  if (s.kind === "qa") {
    const data = await secFetch(s);
    const a = ((data && data.answers) || []).find((x) => String(x.id) === String(id));
    if (!a) { read.innerHTML = `<p class="dx-prose">That question isn't here.</p>`; return; }
    const resp = (a.responses && a.responses.length)
      ? a.responses.map((r) => `<div class="voice machine"><span class="who">${esc(r.name || r.coach || "The board")}</span><p class="what">${esc(r.text)}</p></div>`).join("")
      : (a.answer ? `<div class="voice machine"><span class="who">The board</span><p class="what">${esc(a.answer)}</p></div>` : `<p class="dx-prose">An answer is on the way.</p>`);
    read.innerHTML =
      `<p class="dx-kicker label">a reader asked${a.answered_at ? ` · ${esc(a.answered_at)}` : ""}</p>` +
      `<h2 class="dx-title">${esc(a.question)}</h2>` +
      (a.note ? `<p class="dx-prose">${esc(a.note)}</p>` : "") +
      resp;
    enhanceCoachNames(read);
    return;
  }
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
  const entries = entriesFor(s, await secFetch(s));
  if (!entries.length) {
    const emptyMsg = s.kind === "qa"
      ? "No reader questions answered yet — ask one above and yours could be next."
      : "Nothing here yet — it fills as the experiment runs.";
    listEl.innerHTML = `<li class="dx-empty">${emptyMsg}</li>`; $("[data-dx-read]").innerHTML = ""; return;
  }
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}</span><span class="dx-item-d label">${esc(e.date || "")}</span></button></li>`).join("");
  listEl.querySelectorAll(".dx-item").forEach((b) => b.addEventListener("click", () => selectEntry(s, b.dataset.id)));
  const initId = preId && entries.some((e) => String(e.id) === String(preId)) ? preId : entries[0].id;
  selectEntry(s, initId, true);
}

function build() {
  const tabsEl = $("[data-dx-tabs]"); if (!tabsEl) return;
  tabsEl.innerHTML = SECTIONS.map((s) => `<button class="dx-tab" data-sec="${s.key}" aria-pressed="false">${esc(s.label)}</button>`).join("");
  tabsEl.querySelectorAll(".dx-tab").forEach((b) => b.addEventListener("click", () => selectSection(b.dataset.sec)));
  const start = (window.__COACHING_START__ && BYKEY[window.__COACHING_START__]) ? window.__COACHING_START__ : "coaches";
  const hashId = (location.hash || "").replace("#", "") || undefined;
  selectSection(start, hashId, false);
}
window.addEventListener("popstate", (e) => { const sec = (e.state && e.state.sec) || (location.pathname.match(/\/coaching\/([^/]+)\//) || [])[1] || "coaches"; selectSection(sec, e.state && e.state.id, false); });

function wireTheme() {
  const b = $(".theme-toggle"); if (!b) return;
  b.addEventListener("click", () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); document.documentElement.dataset.theme = cur === "light" ? "dark" : "light"; try { localStorage.setItem("ajm-theme", document.documentElement.dataset.theme); } catch (e) {} });
}
/* ── Ask the board (PG-ENG-2) — capture, not a live answer. A reader's question is
   submitted to a moderation queue; Matthew picks one and the board answers it in an
   upcoming lab note. JS-injected after the header so the generated shell needs no
   rebuild. The /api/board_ask cost gate is never touched here — this only stores. */
function wireAskBoard() {
  const head = $(".dx-head");
  if (!head) return;
  const card = document.createElement("section");
  card.className = "askboard";
  card.setAttribute("aria-label", "Ask the board");
  card.innerHTML =
    `<p class="askboard-k label">ask the board</p>` +
    `<p class="askboard-lede">Got a question for the AI team? Submit it — Matthew picks one and the board answers it in an upcoming lab note.</p>` +
    `<form class="askboard-form" novalidate>` +
    `<textarea class="askboard-in" name="q" rows="2" maxlength="500" placeholder="e.g. Is the glucose spike the supplement, or just a bad night's sleep?" aria-label="Your question for the board"></textarea>` +
    `<div class="askboard-row">` +
    `<input class="askboard-email" name="email" type="email" maxlength="254" placeholder="email (optional — for a reply)" aria-label="Email, optional" />` +
    `<button class="askboard-btn" type="submit">Ask the board</button>` +
    `</div><p class="askboard-out label" role="status" aria-live="polite"></p></form>`;
  head.insertAdjacentElement("afterend", card);

  const form = card.querySelector(".askboard-form");
  const out = card.querySelector(".askboard-out");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    const email = form.email.value.trim();
    if (q.length < 10) { out.textContent = "A little more detail — at least 10 characters."; return; }
    const btn = form.querySelector(".askboard-btn");
    btn.disabled = true; out.textContent = "Sending…";
    try {
      const res = await fetch("/api/board_question", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(email ? { question: q, email } : { question: q }),
      });
      if (res.ok) {
        form.q.value = ""; form.email.value = "";
        out.textContent = "Question received — Matthew reviews these, and the board answers a selection in the lab notes.";
      } else if (res.status === 429) {
        out.textContent = "You've sent a few already — give it an hour and try again.";
      } else {
        const d = await res.json().catch(() => ({}));
        out.textContent = (d && d.error) || "Couldn't send that just now — try again shortly.";
      }
    } catch (err) {
      out.textContent = "Network hiccup — try again in a moment.";
    } finally {
      btn.disabled = false;
    }
  });
}

wireTheme();
build();
wireAskBoard();
stampGenesis();  // cross-site Day-N/Week-N anchor (matches the Home hero)
