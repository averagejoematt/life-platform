/*
  cockpit.js — Door 1 behaviour (/now)
  ----------------------------------------------------------------------------
  Binds the Cockpit to the live engine. No data is invented: every value comes
  from an existing endpoint, and anything absent is shown honestly or omitted.

  Endpoints (all read-only, already published):
    /api/snapshot          vitals + journey + character in one call
    /api/weekly_priority    The Chair's cross-pillar synthesis (Dr. Kai Nakamura)
    /api/coach_analysis?domain=<pillar>   lazy per-pillar read on disclosure

  Two jobs (LOCKED): the glance answers "am I winning + the one thing"; a pillar
  view answers "why it's here, where it's heading, what to do". Detail opens in
  place (View Transitions) — never a navigation away.
*/

const API = "/api";

// Pillar → domain grouping (LOCKED, Constitution §6). Consistency is the band.
const BODY = ["movement", "nutrition", "sleep", "metabolic"];
const MIND = ["mind", "relationships"];
const PILLAR_LABEL = {
  movement: "Movement", nutrition: "Nutrition", sleep: "Sleep",
  metabolic: "Metabolic", mind: "Mind", relationships: "Relationships",
  consistency: "Consistency",
};

const $ = (sel, root = document) => root.querySelector(sel);
const bind = (name, root = document) => root.querySelector(`[data-bind="${name}"]`);
const rows = (name) => document.querySelector(`[data-rows="${name}"]`);

const state = { scope: "today", pillars: {}, coachCache: {} };

/* ── fetch helpers ───────────────────────────────────────────────────────── */
async function getJSON(path) {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

/* ── trend helpers ───────────────────────────────────────────────────────── */
function trendOf(delta) {
  if (delta == null) return "flat";
  if (delta > 0.05) return "up";
  if (delta < -0.05) return "down";
  return "flat";
}
const MARK = { up: "▲", down: "▼", flat: "›" };

/* ── render: the hub + honesty + dialogue ────────────────────────────────── */
function renderHub(character) {
  const lvl = Math.round(character.level ?? 1);
  bind("level").textContent = lvl;
  bind("tier").textContent = character.tier || "Foundation";

  // Spine carries the day index of the experiment.
  if (character.as_of_date && character.started_date) {
    const d0 = Date.parse(character.started_date);
    const d1 = Date.parse(character.as_of_date);
    if (!Number.isNaN(d0) && !Number.isNaN(d1)) {
      const day = Math.max(0, Math.round((d1 - d0) / 86400000));
      bind("day").textContent = String(day).padStart(3, "0");
    }
  }

  const delta = character.composite_delta_1d;
  const mv = bind("movement");
  if (delta != null) {
    const dir = trendOf(delta);
    mv.dataset.dir = dir;
    mv.textContent = `${MARK[dir]} ${delta > 0 ? "+" : ""}${delta} today`;
    mv.hidden = false;
  }

  // Honesty: a down/flat composite is shown plainly, never hidden, never red.
  const honest = bind("honest");
  if (delta != null && delta < 0) {
    honest.textContent = `▼ ${delta} ${state.scope === "week" ? "this week" : "today"} — logged honestly, not hidden.`;
    honest.hidden = false;
  } else {
    honest.hidden = true;
  }
}

// True for missing/sentinel/error values so they never render raw to a visitor
// (e.g. "[AI_UNAVAILABLE]", "", "N/A", any "[...]" placeholder).
function isBad(v) {
  if (v == null) return true;
  const s = String(v).trim();
  return s === "" || s.toUpperCase() === "N/A" || /^\[.*\]$/.test(s);
}

function renderVerdict(priority) {
  const v = bind("verdict");
  const text = priority && priority.weekly_priority;
  if (!isBad(text)) {
    v.innerHTML = `<span class="mark">&rsaquo;</span> ${escapeHTML(text)}`;
  } else {
    v.innerHTML = `<span class="mark">&rsaquo;</span> The board's weekly read isn't in yet — it posts after the next briefing.`;
  }
}

/* ── render: the two domains + consistency band ──────────────────────────── */
function rollup(keys) {
  const vals = keys.map((k) => state.pillars[k]?.raw_score).filter((n) => typeof n === "number");
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}

function pillarRow(key) {
  const p = state.pillars[key];
  const score = Math.round(p?.raw_score ?? 0);
  const dir = trendOf(p?.xp_delta);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `row ${dir === "up" ? "up" : dir === "down" ? "dn" : ""}`;
  btn.dataset.pillar = key;
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML =
    `<span class="lab">${PILLAR_LABEL[key] || key}</span>` +
    `<span class="track"><i style="width:${Math.min(100, score)}%"></i></span>` +
    `<span class="val num">${score}</span>` +
    `<span class="tr">${MARK[dir]}</span>` +
    `<span class="chev" aria-hidden="true">›</span>`;
  btn.addEventListener("click", () => togglePillar(btn, key));
  return btn;
}

function renderDomains() {
  const bodyRoll = rollup(BODY), mindRoll = rollup(MIND);
  if (bodyRoll != null) bind("roll-body").textContent = bodyRoll;
  if (mindRoll != null) bind("roll-mind").textContent = mindRoll;

  const bodyRows = rows("body"), mindRows = rows("mind");
  bodyRows.replaceChildren(...BODY.filter((k) => state.pillars[k]).map(pillarRow));
  mindRows.replaceChildren(...MIND.filter((k) => state.pillars[k]).map(pillarRow));

  const c = state.pillars.consistency;
  if (c) {
    const score = Math.round(c.raw_score ?? 0);
    bind("consistency-fill").style.width = `${Math.min(100, score)}%`;
    bind("consistency-val").textContent = score;
  }
}

/* ── in-place pillar disclosure (View Transitions) ───────────────────────── */
function withTransition(fn) {
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(fn);
  } else {
    fn();
  }
}

async function togglePillar(btn, key) {
  const open = btn.getAttribute("aria-expanded") === "true";
  // Lateral focus model: only one pillar open at a time.
  document.querySelectorAll('.row[aria-expanded="true"]').forEach((r) => {
    if (r !== btn) collapse(r);
  });
  if (open) { withTransition(() => collapse(btn)); return; }

  btn.setAttribute("aria-expanded", "true");
  const detail = document.createElement("div");
  detail.className = "pillar-detail";
  detail.innerHTML = `<p class="pd-read"><span class="pd-who">loading ${PILLAR_LABEL[key]}…</span></p>`;
  withTransition(() => btn.after(detail));

  const read = await loadPillarRead(key);
  const p = state.pillars[key] || {};
  const dir = trendOf(p.xp_delta);
  detail.innerHTML =
    `<p class="pd-read">${read.text}</p>` +
    (read.action ? `<p class="pd-action">→ ${escapeHTML(read.action)}</p>` : "") +
    `<p class="pd-meta">` +
      `<span class="pd-conf">${read.confidence}</span>` +
      `<span class="pd-conf">trend ${MARK[dir]} ${p.tier || ""}</span>` +
    `</p>`;
}

function collapse(btn) {
  btn.setAttribute("aria-expanded", "false");
  const d = btn.nextElementSibling;
  if (d && d.classList.contains("pillar-detail")) d.remove();
}

// Lazy per-pillar read from the coach intelligence; honest correlative framing.
async function loadPillarRead(key) {
  if (state.coachCache[key]) return state.coachCache[key];
  let text = "", action = "", confidence = "";
  try {
    const data = await getJSON(`${API}/coach_analysis?domain=${encodeURIComponent(key)}`);
    const a = data.analysis || data.coach_analysis || data;
    text = a.summary || a.analysis || a.read || "";
    action = a.action || a.recommendation || a.one_thing || "";
    const n = a.observations ?? a.n ?? a.sample_size;
    if (typeof n === "number") {
      confidence = n < 12 ? "preliminary pattern" : n < 30 ? "low confidence (n<30)" : `n=${n}`;
    }
  } catch (e) { /* fall through to the deterministic read */ }

  if (!text) {
    const p = state.pillars[key] || {};
    const dir = trendOf(p.xp_delta);
    const moving = dir === "up" ? "climbing" : dir === "down" ? "slipping" : "holding";
    text = `${PILLAR_LABEL[key]} is at ${Math.round(p.raw_score ?? 0)} and ${moving} (${p.tier || "Foundation"}). ` +
           `Correlative read only — open the Evidence door for the components behind it.`;
  }
  const out = { text: escapeHTML(text).replace(/^&gt;\s*/, ""), action, confidence: confidence || "correlative" };
  state.coachCache[key] = out;
  return out;
}

/* ── board one-liner (the interpretation layer, made glanceable) ─────────── */
function renderBoardline(priority) {
  const notes = priority && priority.cross_domain_notes;
  const line = notes && (typeof notes === "string" ? notes : Object.values(notes).find(Boolean));
  if (line && !isBad(line)) {
    const who = (priority.coach_name || "The integrator");
    bind("boardline").textContent = `“${String(line).trim()}” — ${who}`;
    bind("boardline").hidden = false;
  }
}

/* ── scope + theme controls ──────────────────────────────────────────────── */
function wireScope() {
  document.querySelectorAll(".scope-btn").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.dataset.scope === state.scope) return;
      document.querySelectorAll(".scope-btn").forEach((x) => {
        const on = x === b;
        x.classList.toggle("is-active", on);
        x.setAttribute("aria-pressed", String(on));
      });
      state.scope = b.dataset.scope;
      bind("scopeLabel").textContent = b.textContent.toLowerCase();
      // Re-render honesty wording for the active scope; deeper scope data
      // (week/month/journey series) is layered in by the Story/Evidence doors.
      load();
    });
  });
}

function wireTheme() {
  const btn = $(".theme-toggle");
  btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme
      || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = cur === "light" ? "dark" : "light";
    withTransition(() => { document.documentElement.dataset.theme = next; });
    try { localStorage.setItem("ajm-theme", next); } catch (e) {}
  });
}

/* ── load + orchestrate ──────────────────────────────────────────────────── */
async function load() {
  const main = $("#cockpit");
  try {
    const [snap, priority] = await Promise.allSettled([
      getJSON(`${API}/snapshot`),
      getJSON(`${API}/weekly_priority`),
    ]);

    const snapV = snap.status === "fulfilled" ? snap.value : null;
    const charBody = snapV?.character || null;   // handle_character body (or {error} on 503)
    const character = charBody?.character || (charBody && !charBody.error ? charBody : null);
    const pillarList = charBody?.pillars || character?.pillars || [];
    state.pillars = {};
    for (const p of pillarList) state.pillars[p.name] = p;

    // No real sheet today (uncomputed / pre-experiment / error) → calm empty state,
    // never misleading zeros.
    if (!character || charBody.error || !pillarList.length) throw new Error("character sheet unavailable");

    renderHub(character);
    renderDomains();
    const pri = priority.status === "fulfilled" ? priority.value : null;
    renderVerdict(pri);
    renderBoardline(pri);

    if (character.as_of_date) bind("asof").textContent = `as of ${character.as_of_date}`;
    main.dataset.state = "ready";
    $(".panel").setAttribute("aria-busy", "false");
  } catch (e) {
    // Calm, honest empty state — no misleading zeros, no raw error tokens, no
    // stuck shimmer. Force display:none (the [hidden] attr is overridden by the
    // author display rules on .domains/.band/.voice). The score recomputes daily.
    main.dataset.state = "ready";
    const gone = (sel) => { const el = typeof sel === "string" ? $(sel) : sel; if (el) el.style.display = "none"; };
    bind("level").textContent = "—";
    bind("tier").textContent = "";
    bind("day").textContent = "";
    gone(bind("movement")); gone(bind("honest")); gone(bind("boardline"));
    gone(".domains"); gone(".band"); gone(".voice.human");
    bind("verdict").innerHTML = "Today's score hasn't computed yet — the numbers refresh each morning. Check back shortly.";
    $(".panel").setAttribute("aria-busy", "false");
  }
}

function escapeHTML(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

wireScope();
wireTheme();
bind("scopeLabel").textContent = "today";
load();
