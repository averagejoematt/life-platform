/*
  agents.js — /story/agents behaviour (#399)
  ----------------------------------------------------------------------------
  Renders the "meet the agents" roster and a dated weekly Agent Activity feed
  from a single read-only endpoint, /api/agent_activity. Every value comes from
  an artifact the platform already wrote (coherence log, AI-quality canary log,
  remediation audit log); nothing here is invented, and an empty week says so.
*/

const API = "/api";

const $ = (sel, root = document) => root.querySelector(sel);

async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

// Small code-drawn sigils per agent — no emoji, matches the inline-SVG language.
function sigil(id) {
  const svg = (inner) =>
    `<svg class="agent-sigil" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${inner}</svg>`;
  switch (id) {
    case "coherence_sentinel": // interlocking rings — do the parts still agree
      return svg(`<circle cx="9" cy="12" r="5.5"/><circle cx="15" cy="12" r="5.5"/>`);
    case "ai_quality_canary": // an eye — watching the served answers
      return svg(`<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="2.6"/>`);
    case "remediation_agent": // a wrench — triage and repair
      return svg(`<path d="M15.5 6.5a4 4 0 0 0-5.4 4.9L4 17.5 6.5 20l6.1-6.1a4 4 0 0 0 4.9-5.4l-2.4 2.4-2.1-.5-.5-2.1 2.5-2.3Z"/>`);
    case "automerge_gate": // a shield with a check — the provably-safe gate
      return svg(`<path d="M12 3l7 3v5c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3Z"/><path d="M9 12l2 2 4-4"/>`);
    default:
      return svg(`<circle cx="12" cy="12" r="8"/>`);
  }
}

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ISO = (d) => d.toISOString().slice(0, 10);
const mondayOf = (d) => {
  const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dow = (x.getUTCDay() + 6) % 7; // 0 = Monday
  x.setUTCDate(x.getUTCDate() - dow);
  return x;
};
const addDays = (iso, n) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return ISO(d);
};
function prettyRange(start, end) {
  const opt = { month: "short", day: "numeric", timeZone: "UTC" };
  const s = new Date(start + "T00:00:00Z").toLocaleDateString("en-US", opt);
  const e = new Date(end + "T00:00:00Z").toLocaleDateString("en-US", { ...opt, year: "numeric" });
  return `${s} – ${e}`;
}
function prettyDay(iso) {
  return new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function renderRoster(roster, summary) {
  const el = $("[data-roster]");
  if (!el) return;
  el.innerHTML = roster
    .map((a) => {
      const s = (summary && summary[a.id]) || { runs: 0, flags: 0 };
      const tally = s.runs
        ? `<strong>${s.runs}</strong> run${s.runs === 1 ? "" : "s"} · <strong>${s.flags}</strong> flagged`
        : "quiet this week";
      return `<article class="agent-card">
        <div class="ac-top">${sigil(a.id)}<h3>${esc(a.name)}</h3></div>
        <p class="ac-role">${esc(a.role)}</p>
        <p class="ac-detail">${esc(a.detail)}</p>
        <div class="ac-foot"><span class="ac-tally">${tally}</span><span class="ac-src">${esc(a.source)}</span></div>
      </article>`;
    })
    .join("");
}

function renderFeed(data) {
  const host = $("[data-feed]");
  if (!host) return;
  const events = data.events || [];
  if (!events.length) {
    host.innerHTML = `<p class="feed-empty">No agent activity recorded this week. The watchdogs ran; nothing needed reporting.</p>`;
    return;
  }
  // group by date (events already sorted newest-first)
  const byDay = [];
  const seen = new Map();
  for (const e of events) {
    if (!seen.has(e.date)) {
      const bucket = { date: e.date, items: [] };
      seen.set(e.date, bucket);
      byDay.push(bucket);
    }
    seen.get(e.date).items.push(e);
  }
  host.innerHTML = byDay
    .map((day) => {
      const rows = day.items
        .map((e) => {
          const details = (e.details || []).length
            ? `<ul class="ev-details">${e.details.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>`
            : "";
          return `<li class="event" data-status="${esc(e.status)}">
            <span class="dot" aria-hidden="true"></span>
            <div class="ev-body">
              <p class="ev-agent">${esc(e.agent)}</p>
              <p class="ev-head">${esc(e.headline)}</p>
              ${details}
            </div>
          </li>`;
        })
        .join("");
      return `<section class="feed-day"><p class="feed-day-label">${esc(prettyDay(day.date))}</p><ul class="feed">${rows}</ul></section>`;
    })
    .join("");
}

const state = { week: ISO(mondayOf(new Date())) };

/* ── Loading skeletons + a per-week session cache (#1019) ─────────────────────
   The feed endpoint can take seconds cold; a bare "Loading…" string reads as
   broken. Instead: (1) swap to a design-system skeleton synchronously on every
   week-nav tap, and (2) stale-while-revalidate through sessionStorage — a week
   already seen this session paints instantly from cache while the fetch
   refreshes it in the background. Weeks are dated, append-only records (past
   weeks immutable), so a stale-first paint stays honest. The skeleton markup
   mirrors the static shell in index.html — keep them in sync. */

const CACHE_PREFIX = "ajm-agents-week-v1:";
const cacheGet = (k) => { try { const raw = sessionStorage.getItem(k); return raw ? JSON.parse(raw) : null; } catch (e) { return null; } };
const cachePut = (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode / quota — cache is best-effort */ } };

const SK_EVENT = `<div class="sk-event" aria-hidden="true"><span class="sk-b sk-dot"></span><div class="sk-lines"><span class="sk-b sk-l1"></span><span class="sk-b sk-l2"></span></div></div>`;
const SK_DAY = `<span class="sk-b sk-day" aria-hidden="true"></span>`;
const skeletonFeed = () =>
  `<div class="sk sk-feed" role="status" aria-label="Loading the week's agent activity">${SK_DAY}${SK_EVENT.repeat(3)}${SK_DAY}${SK_EVENT.repeat(2)}</div>`;
const SK_CARD = `<div class="sk-card" aria-hidden="true"><div class="sk-t"><span class="sk-b sk-sigil"></span><span class="sk-b sk-h"></span></div><span class="sk-b sk-r"></span><span class="sk-b sk-d"></span><span class="sk-b sk-d"></span></div>`;
const skeletonRoster = () => SK_CARD.repeat(4);

function render(data) {
  state.week = data.week_start || state.week;
  const range = $("[data-week-range]");
  if (range) range.textContent = prettyRange(data.week_start, data.week_end);
  renderRoster(data.roster || [], data.summary || {});
  renderFeed(data);
  // Don't let readers page into the future.
  const next = $("[data-week-next]");
  if (next) next.disabled = addDays(state.week, 7) > ISO(mondayOf(new Date()));
}

let seq = 0; // rapid week-nav taps race their fetches — only the latest may paint
async function load() {
  const my = ++seq;
  const week = state.week;
  const host = $("[data-feed]");
  const roster = $("[data-roster]");
  const cached = cacheGet(CACHE_PREFIX + week);
  if (cached) {
    render(cached); // instant stale paint; the fetch below revalidates it
  } else {
    if (host) host.innerHTML = skeletonFeed();
    if (roster && !roster.querySelector(".agent-card")) roster.innerHTML = skeletonRoster();
  }
  try {
    const data = await getJSON(`${API}/agent_activity?week=${encodeURIComponent(week)}`);
    cachePut(CACHE_PREFIX + week, data);
    if (my !== seq) return;
    render(data);
  } catch (err) {
    if (my !== seq || cached) return; // keep the cached paint if we had one
    if (host) host.innerHTML = `<p class="feed-empty">The activity feed is unavailable right now. Please try again shortly.</p>`;
  }
}

function wire() {
  const prev = $("[data-week-prev]");
  const next = $("[data-week-next]");
  if (prev) prev.addEventListener("click", () => { state.week = addDays(state.week, -7); load(); });
  if (next) next.addEventListener("click", () => { state.week = addDays(state.week, 7); load(); });
}

wire();
load();
