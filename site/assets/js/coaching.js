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
import { enhanceCoachNames } from "/assets/js/coach_popover.js";

const SECTIONS = [
  { key: "coaches", label: "The Team", kicker: "the AI team reading your data", kind: "coaches", url: "/api/coaches" },
  { key: "lab-notes", label: "AI lab notes", kicker: "the AI's read ↔ how it felt", kind: "fieldnotes", url: "/api/field_notes" },
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
  return [];
}

// ── Coach page sub-renderers (one type system: coaches SPEAK serif; labels/data mono) ──
function coachStanceHTML(st) {
  if (!st) return "";
  const list = (arr) => (Array.isArray(arr) ? arr.map(esc).join(" · ") : "");
  let h = `<section class="coach-stance"><p class="dx-kicker label">where I think you are · what I'm focused on</p>`;
  h += `<h4 class="cs-headline">${esc(st.headline || "")}</h4><p class="dx-prose">${esc(st.read_of_him || "")}</p>`;
  if ((st.cares_most || []).length) h += `<p class="cs-care"><span class="label">caring most about right now</span> ${list(st.cares_most)}</p>`;
  if ((st.cares_less_right_now || []).length) h += `<p class="cs-careless"><span class="label">deliberately ignoring for now</span> ${list(st.cares_less_right_now)}</p>`;
  if (st.plan) h += `<p class="dx-prose"><strong>The plan:</strong> ${esc(st.plan)}</p>`;
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
  let h = `<p class="dx-kicker label">your team · the collective read on you right now</p><h3 class="dx-title">My Team</h3>`;
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
  h += `<section class="team-tension"><p class="dx-kicker label">where the team disagrees</p>`;
  if ((d.tensions || []).length) {
    h += `<ul class="tt-list">${d.tensions.map((t) => `<li><span class="label">${esc((t.coaches || []).map((c) => String(c).replace("_coach", "")).join(" ↔ ") || t.topic || "")}</span> ${esc(t.summary || "")}</li>`).join("")}</ul>`;
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
  let h = `<p class="dx-kicker label">${esc(d.emoji || "")} ${esc(d.board_role || d.domain || "")}</p>`;
  h += `<h3 class="dx-title">${esc(d.name || "")}</h3>`;
  if (d.disclosure) h += `<p class="dx-disclosure label">${esc(d.disclosure)}</p>`;
  // Lead with the two essentials: today's reflection (if any), the stance, the report card.
  if (typeof d.daily === "string" && d.daily.trim()) {
    h += `<section class="coach-daily"><p class="dx-kicker label">today's reflection</p><p class="cd-text">${esc(d.daily)}</p></section>`;
  }
  h += coachStanceHTML(d.stance && d.stance.rung);
  const ro = d.recent_outputs || [];
  h += `<section class="coach-progress"><p class="dx-kicker label">how it's going</p>`;
  h += ro.length
    ? `<p class="coach-latest"><span class="label">${esc(ro[0].date || "")}</span> ${esc(ro[0].summary || "")}</p>`
    : `<p class="dx-prose">Tracking begins as data arrives — this coach narrates honest progress against its watches here, down-weeks included.</p>`;
  h += `</section>`;
  h += coachReportHTML(d.report_card);
  // Disclose the deeper context so the page isn't one long scroll (F-06).
  h += disclose("the character — who they are, how they show up", coachCharacterHTML(d.character));
  h += disclose("working hypotheses · live bets", coachHypothesesHTML(d.working_hypotheses));
  const v = d.voice || {};
  if (typeof v.few_shot_example === "string" && v.few_shot_example.trim()) {
    h += disclose("voice signature", `<section class="coach-voice"><blockquote class="cv-example">${esc(v.few_shot_example)}</blockquote></section>`);
  }
  const rel = d.relationships || {};
  const edge = (e) => `${esc(String(e.coach || "").replace("_coach", ""))} (${esc(e.weight)})`;
  if ((rel.leans_on || []).length || (rel.leaned_on_by || []).length) {
    let rh = `<section class="coach-rel">`;
    if ((rel.leans_on || []).length) rh += `<p class="cr-edges"><span class="label">leans on</span> ${rel.leans_on.map(edge).join(" · ")}</p>`;
    if ((rel.leaned_on_by || []).length) rh += `<p class="cr-edges"><span class="label">leaned on by</span> ${rel.leaned_on_by.map(edge).join(" · ")}</p>`;
    h += disclose("on the team", rh + `</section>`);
  }
  h += disclose("the daily journey", coachJourneyHTML(ro));
  read.innerHTML = h;
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
      const mattVoice = mattText
        ? `<div class="voice human"><span class="who">Matthew</span><p class="what">${esc(mattText)}</p></div>`
        : `<div class="voice human voice-pending"><span class="who">Matthew</span><p class="what">Pending Matthew's response — he hasn't weighed in on the AI's read of this week yet.</p></div>`;
      const hasAny = ai.length || mattText;
      read.innerHTML = `<p class="dx-kicker label">field note · week ${esc(id)} · the AI's read ↔ Matthew's response${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
        (hasAny ? ai.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("") + mattVoice
          : `<p class="dx-prose">No field note recorded for this week yet.</p>`);
    } catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this field note just now.</p>`; }
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
  if (!entries.length) { listEl.innerHTML = `<li class="dx-empty">Nothing here yet — it fills as the experiment runs.</li>`; $("[data-dx-read]").innerHTML = ""; return; }
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
wireTheme();
build();
