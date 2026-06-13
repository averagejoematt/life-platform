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
const SECTIONS = [
  { key: "chronicle", label: "Chronicle", kicker: "written weekly by Elena Voss", kind: "posts", url: "/chronicle/posts.json" },
  { key: "lab-notes", label: "AI lab notes", kicker: "what the AI saw ↔ how it felt", kind: "fieldnotes", url: "/api/field_notes" },
  { key: "journal", label: "In my own words", kicker: "the daily journal", kind: "posts", url: "/journal/posts.json" },
  { key: "timeline", label: "Timeline", kicker: "level-ups & milestones", kind: "timeline", url: "/api/journey_timeline" },
  { key: "about", label: "About", kicker: "the experiment, in context", kind: "about" },
];
const BYKEY = Object.fromEntries(SECTIONS.map((s) => [s.key, s]));

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
let _podcastEpisodes = null;  // week → {url, bytes}; loaded once, fails silent
async function podcastEpisode(week) {
  if (_podcastEpisodes === null) {
    try {
      const d = await getJSON("/podcast/episodes.json");
      _podcastEpisodes = {};
      for (const e of d.episodes || []) _podcastEpisodes[String(e.week)] = e;
    } catch (e) { _podcastEpisodes = {}; }
  }
  return _podcastEpisodes[String(week)];
}

async function getJSON(p) { const r = await fetch(p, { headers: { accept: "application/json" } }); if (!r.ok) throw new Error(p + " " + r.status); return r.json(); }
async function tryJSON(p) { try { return await getJSON(p); } catch (e) { return null; } }
const cache = {};
async function secFetch(s) { if (!s.url) return null; if (cache[s.key]) return cache[s.key]; const d = await tryJSON(s.url); cache[s.key] = d; return d; }

const ABOUT = `
  <p class="dx-kicker label">the experiment, in context</p>
  <h3 class="dx-title">An honest documentary of an ordinary life, rebuilt with AI.</h3>
  <p class="dx-prose">No million-dollar lab and no guru — just the wearables already on the body, a model that reads the numbers back every morning, and the willingness to publish the down weeks too. The bet is simple: numbers <em>and</em> meaning, kept honest and personal. The anti-Blueprint.</p>
  <p class="dx-prose">Everything here is correlative, never causal — patterns, flagged when thin, never dressed up as proof. The board of named AI experts argues about the data; Elena writes the weekly chronicle; the Third Wall is where the machine's read meets how it actually felt. This is the overlay — the story on top of the instrument.</p>
  <p class="dx-prose">The throughline: <strong>you could do this too</strong>. The cockpit and the evidence hold the live data; these dispatches hold the why.</p>`;

function entriesFor(s, data) {
  if (!data) return [];
  if (s.kind === "fieldnotes") return (data.entries || []).map((e) => ({ id: e.week, title: `Week ${e.week} field note`, date: e.ai_generated_at ? String(e.ai_generated_at).slice(0, 10) : "" }));
  if (s.kind === "posts") { const ps = data.posts || data.entries || (Array.isArray(data) ? data : []); return ps.map((p) => ({ id: p.week, title: p.title || `Week ${p.week}`, date: p.date, excerpt: p.excerpt, meta: p.stats_line, word_count: p.word_count, url: p.url })); }
  return [];
}

async function renderRead(s, id) {
  const read = $("[data-dx-read]");
  if (s.kind === "about") { read.innerHTML = ABOUT; return; }
  if (s.kind === "timeline") {
    read.innerHTML = `<p class="dx-kicker label">${esc(s.kicker)}</p><h3 class="dx-title">The journey so far</h3><p class="dx-loading shimmer">Loading the timeline…</p>`;
    const d = await secFetch(s); const events = (d && d.events) || [];
    read.innerHTML = `<p class="dx-kicker label">${esc(s.kicker)}</p><h3 class="dx-title">The journey so far</h3>` +
      (events.length ? `<ol class="dx-timeline">${events.map((e) => `<li class="dxt-item"><span class="dxt-date label">${esc(String(e.date || "").slice(0, 10))}</span><div><p class="dxt-title">${esc(e.title || e.type || "")}</p>${e.body ? `<p class="dxt-note">${esc(e.body)}</p>` : ""}</div></li>`).join("")}</ol>`
        : `<p class="dx-prose">No milestones logged yet — the timeline fills as the score climbs. Day 1 starts the clock.</p>`);
    return;
  }
  if (s.kind === "fieldnotes") {
    read.innerHTML = `<p class="dx-kicker label"><span class="shimmer">Reading the field note…</span></p>`;
    try {
      const d = await getJSON(`/api/field_notes?week=${encodeURIComponent(id)}`); const e = d.entry || {};
      const voices = [["The AI", e.ai_present, "machine"], ["Worth watching", e.ai_cautionary, "machine"], ["Worth celebrating", e.ai_affirming, "machine"], ["Matthew", e.matthew_agreement, "human"]].filter((v) => v[1]);
      read.innerHTML = `<p class="dx-kicker label">field note · week ${esc(id)}${e.ai_tone ? ` · ${esc(e.ai_tone)}` : ""}</p>` +
        (voices.length ? voices.map(([who, txt, cls]) => `<div class="voice ${cls}"><span class="who">${esc(who)}</span><p class="what">${esc(txt)}</p></div>`).join("") : `<p class="dx-prose">No field note recorded for this week yet.</p>`);
    } catch (e) { read.innerHTML = `<p class="dx-prose">Couldn't load this field note just now.</p>`; }
    return;
  }
  // posts (chronicle / journal)
  const all = entriesFor(s, await secFetch(s));
  const ent = all.find((x) => String(x.id) === String(id));
  if (!ent) { read.innerHTML = `<p class="dx-prose">Pick an entry to read it here.</p>`; return; }
  const readmore = ent.url
    ? `<p class="dx-readmore"><button type="button" class="dx-readfull" data-url="${esc(ent.url)}">Read the full piece${ent.word_count ? ` (${esc(ent.word_count)} words)` : ""} →</button></p><div class="dx-fulltext" data-fulltext hidden></div>`
    : (ent.word_count ? `<p class="dx-foot label">${esc(ent.word_count)} words</p>` : "");
  const episode = s.key === "chronicle" ? await podcastEpisode(ent.id) : null;
  const listen = episode
    ? `<div class="dx-listen"><audio controls preload="none" src="${esc(episode.url)}"></audio><span class="label">listen · AI-voiced (~${Math.max(1, Math.round((episode.bytes || 0) / 1024 / 1024 / 0.12))} min)</span></div>`
    : "";
  read.innerHTML = `<p class="dx-kicker label">${s.key === "chronicle" ? "chronicle · Elena Voss" : "journal"} · week ${esc(ent.id)}${ent.date ? ` · ${esc(ent.date)}` : ""}</p>` +
    `<h3 class="dx-title">${esc(ent.title)}</h3>` + listen + (ent.meta ? `<p class="dx-stats label">${esc(ent.meta)}</p>` : "") +
    `<p class="dx-prose dx-excerpt">${esc(ent.excerpt || "")}</p>` + readmore + dispatchFoot(s, ent, all);
  const rf = read.querySelector(".dx-readfull");
  if (rf) rf.addEventListener("click", () => loadFull(rf, read.querySelector("[data-fulltext]"), read.querySelector(".dx-excerpt")));
  const sf = read.querySelector(".dx-startfirst");
  if (sf) sf.addEventListener("click", () => selectEntry(s, sf.dataset.startid));
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
  listEl.innerHTML = entries.map((e) => `<li><button class="dx-item" data-id="${esc(e.id)}"><span class="dx-item-t">${esc(e.title)}</span><span class="dx-item-d label">${esc(e.date || "")}</span></button></li>`).join("");
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
