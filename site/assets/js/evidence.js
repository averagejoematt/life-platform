/*
  evidence.js — the archive ROUTER (#581 split). Registry dispatch, shared head/hero/tabs/
  sidebar chrome, theme toggle and the first-run orientation card for the three archive
  pillars (/data/, /protocols/, /method/). Every actual readout lives in a per-family
  renderer module (evidence_*.js) imported below — this file only wires them up.

  Registry + start slug are embedded by scripts/v4_build_evidence.py:
    window.__EVIDENCE_REGISTRY__ = [{slug,title,blurb,group,mode,endpoint,root,legacy,editorial}]
    window.__START_SLUG__ = "<slug>"
*/
import { initTheme } from "/assets/js/theme.js";
import { domainIcon } from "/assets/js/icons.js";
import { mountAsk } from "/assets/js/ask.js";
import { esc, getJSON, tryJSON, isBad, sec, empty, note } from "/assets/js/evidence_shared.js";
import { enhanceProvenance } from "/assets/js/provenance_popover.js";
import { renderSupplements, renderLabs, renderPhysical, renderTraining } from "/assets/js/evidence_body.js";
import { wireCharacter, renderCharacter } from "/assets/js/evidence_character.js";
import { wireDataFigure, moveTrendMarker } from "/assets/js/evidence_datafigure.js";
import { renderDiscoveries, renderGenome, renderChallenges, renderProtocols, renderExperiments } from "/assets/js/evidence_discovery.js";
import { renderHabits, renderLedger } from "/assets/js/evidence_habits.js";
import { renderResults, renderPostmortems, renderSurvival, renderMirror, renderScenarios, renderWrong, renderCycles, renderCorrelations, renderCalibration, renderPredictions, renderBenchmarks } from "/assets/js/evidence_intelligence.js";
import { renderBoard, renderPlatform, renderCost, renderData, renderTools, renderInference, renderPipeline, renderAsk, renderExplorer, renderVerify, renderGeneric, ASK_CHIPS } from "/assets/js/evidence_meta.js";
import { renderNutrition, renderGlucose } from "/assets/js/evidence_nutrition.js";
import { renderReading } from "/assets/js/evidence_reading.js";
import { renderSleep, renderMind, renderVices } from "/assets/js/evidence_sleep.js";
import { renderPulse } from "/assets/js/evidence_vitals.js";
import { renderAutonomic, renderZone2 } from "/assets/js/evidence_autonomic.js";

const REG = window.__EVIDENCE_REGISTRY__ || [];

const BYSLUG = Object.fromEntries(REG.map((t) => [t.slug, t]));

const GROUPS = [...new Set(REG.map((t) => t.group))];

// v5: one engine serves three archive pillars (/data/, /protocols/, /method/).
// The builder sets the route base + door label per page; defaults keep the
// legacy /data/ door working if a page omits them.
export const BASE = window.__ARCHIVE_BASE__ || "/data/";

const DOOR = window.__ARCHIVE_DOOR__ || "evidence";

// #802 (R22-CONTENT-03): honest "refresh paused" disclosure for a coach's
// analysis, disclosed only when it's noteworthy — budget_guard paused this
// coach's regeneration (tier >= 2), or the served read is >48h old.
function coachRefreshNote(generatedAt, paused) {
  const d = generatedAt ? new Date(generatedAt) : null;
  const valid = d && !isNaN(d.getTime());
  const date = valid ? d.toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric" }) : "";
  if (paused) return date ? `as of ${date} — refresh paused (budget guard)` : "refresh paused (budget guard)";
  if (valid && (Date.now() - d.getTime()) / 36e5 > 48) return `as of ${date} — next refresh pending`;
  return "";
}

const DOORTITLE = window.__ARCHIVE_TITLE__ || "Evidence";

const slugFromPath = () => { const seg = location.pathname.split("/").filter(Boolean); return seg.length ? seg[seg.length - 1] : ""; };

const RENDERERS = {
  vitals: renderPulse, autonomic: renderAutonomic, zone2: renderZone2, supplements: renderSupplements, labs: renderLabs, physical: renderPhysical, training: renderTraining, nutrition: renderNutrition, glucose: renderGlucose, sleep: renderSleep, mind: renderMind, reading: renderReading, vices: renderVices, ledger: renderLedger, discoveries: renderDiscoveries, biology: renderGenome, challenges: renderChallenges, protocols: renderProtocols, experiments: renderExperiments, habits: renderHabits, board: renderBoard, platform: renderPlatform, cost: renderCost, data: renderData, pipeline: renderPipeline, results: renderResults, tools: renderTools, ask: renderAsk, cycles: renderCycles, inference: renderInference, wrong: renderWrong, survival: renderSurvival, postmortems: renderPostmortems, mirror: renderMirror, explorer: renderExplorer, verify: renderVerify, intelligence: renderCorrelations, predictions: renderPredictions, calibration: renderCalibration, benchmarks: renderBenchmarks, character: renderCharacter, scenarios: renderScenarios };

const WIRE = {
  ask: () => {
    const mount = document.querySelector("[data-ask-mount]");
    if (!mount) return;
    mountAsk(mount, {
      chips: ASK_CHIPS,
      note: "Answers are AI-generated from the published data — correlative, never medical advice. Rate-limited (5/hour), and may be paused by the budget guard.",
    });
  },
  board: () => {
    const picks = [...document.querySelectorAll(".coach-pick")];
    if (!picks.length) return;
    const load = async (btn) => {
      picks.forEach((p) => p.classList.toggle("is-active", p === btn));
      const id = btn.dataset.coach, name = btn.dataset.name, title = btn.dataset.title;
      const out = document.querySelector("[data-board-read]");
      out.innerHTML = `<p class="rd-archive"><span class="shimmer">Reading ${esc(name)}…</span></p>`;
      const [an, tl] = await Promise.all([tryJSON(`/api/coach_analysis?domain=${encodeURIComponent(id)}`), tryJSON(`/api/coach_timeline?coach_id=${encodeURIComponent(id)}`)]);
      const analysis = an && an.analysis; const ms = (tl && tl.milestones) || [];
      const refreshNote = an ? coachRefreshNote(an.generated_at, !!an.regeneration_paused) : "";
      out.innerHTML = `<div class="coach-detail"><p class="dx-kicker label">${esc(title)} · ${esc(name)}</p>` +
        (analysis && !isBad(analysis) ? `<p class="rd-prose">${esc(analysis)}</p>` : `<p class="rd-archive">${esc(name)}'s read posts here as data in their domain accrues.</p>`) +
        (refreshNote ? `<p class="rd-meta label">${esc(refreshNote)}</p>` : "") +
        (ms.length ? sec("Track record", `<ul class="coach-tl">${ms.slice(0, 12).map((m) => `<li><span class="label">${esc(String(m.date || "").slice(0, 10))}</span> ${esc(m.title || m.text || m.note || "")}</li>`).join("")}</ul>`) : "") +
        `</div>`;
    };
    picks.forEach((b) => b.addEventListener("click", () => load(b)));
    const start = picks.find((p) => p.dataset.coach === "training") || picks[0]; // open the lifting coach first
    if (start) load(start);
  },
  results: () => wireDataFigure(),
  character: wireCharacter,
  physical: () => {
    // P0.2 — silhouette scrubs the trend marker in lockstep; P4 adds the inverse:
    // hovering the weight chart drives the silhouette to that day's weigh-in.
    // Fire-and-forget both ways — a failure in the link never breaks either.
    const dfRender = wireDataFigure(moveTrendMarker);
    if (dfRender) {
      document.addEventListener("chart:point", (e) => {
        try {
          if (!e.target.closest || !e.target.closest(".wt-chart")) return;
          const w = Number(e.detail && e.detail.v);
          if (Number.isFinite(w)) dfRender(w);
        } catch (err) { /* decorative link */ }
      });
    }
  },
};

const $ = (s) => document.querySelector(s);

let current = window.__START_SLUG__ || (REG[0] && REG[0].slug);

function buildTabs() {
  const g = BYSLUG[current] ? BYSLUG[current].group : GROUPS[0];
  $("[data-tabs]").innerHTML = GROUPS.map((grp) => `<button class="ev-tab ${grp === g ? "is-active" : ""}" data-group="${esc(grp)}">${esc(grp)}</button>`).join("");
  document.querySelectorAll(".ev-tab").forEach((b) => b.addEventListener("click", () => { const grp = b.dataset.group; const first = REG.find((t) => t.group === grp); if (first) select(first.slug); }));
}

function buildSide() {
  const g = BYSLUG[current] ? BYSLUG[current].group : GROUPS[0];
  $("[data-side]").innerHTML = REG.filter((t) => t.group === g).map((t) => `<button class="ev-tile ${t.slug === current ? "is-active" : ""}" data-slug="${esc(t.slug)}"><span class="ev-tile-t">${domainIcon(t.slug, { cls: "dom-ico" })}${esc(t.title)}</span><span class="ev-tile-b">${esc(t.blurb)}</span></button>`).join("");
  document.querySelectorAll(".ev-tile").forEach((b) => b.addEventListener("click", () => select(b.dataset.slug)));
}

async function renderCenter() {
  const t = BYSLUG[current]; if (!t) return;
  const main = $("[data-main]");
  main.querySelector("[data-crumb]").innerHTML = `${esc(DOOR)} / ${esc(t.slug)}`;
  { const _ti = main.querySelector("[data-title]"); _ti.innerHTML = domainIcon(t.slug, { cls: "dom-ico dom-ico-lead" }) + esc(t.title); }
  main.querySelector("[data-blurb]").textContent = t.blurb;
  const ro = main.querySelector("[data-readout]");
  const deeper = main.querySelector("[data-deeper]");
  deeper.innerHTML = "";   // no link-outs to /legacy — everything lives inline in v4 now
  if (t.mode === "editorial") { ro.innerHTML = t.editorial || empty("—"); return; }
  if (t.mode === "interactive") { ro.innerHTML = (RENDERERS[t.slug] || renderGeneric)({}, t); if (WIRE[t.slug]) WIRE[t.slug](); enhanceProvenance(ro); return; }
  if (t.mode !== "data" || !t.endpoint) { ro.innerHTML = empty(t.archive_note || "This section lives in the archive while it's rebuilt."); return; }
  ro.innerHTML = `<p class="rd-archive"><span class="shimmer">Loading ${esc(t.title)}…</span></p>`;
  try { const data = await getJSON(t.endpoint); const fn = RENDERERS[t.slug] || renderGeneric; const html = await fn(data, t); ro.innerHTML = html && html.trim() ? html : empty("No data published for this section yet."); if (WIRE[t.slug]) WIRE[t.slug](); enhanceProvenance(ro); }
  catch (e) { ro.innerHTML = empty("This readout couldn't load its data just now. The preserved view is linked below."); }
  // Only pull the viewport to the readout on MOBILE (the nav stacks above the
  // content there). On desktop the readout sits beside the sticky nav, so a smooth
  // scroll-to-top just fights the user's own scrolling — the "freezing / pulling
  // up" bug. Respect reduced-motion.
  if (matchMedia("(max-width: 819px)").matches) {
    const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    main.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
  }
}

function select(slug, push = true) {
  if (!BYSLUG[slug]) return;
  current = slug;
  if (push) history.pushState({ slug }, "", `${BASE}${slug}/`);
  document.title = `${BYSLUG[slug].title} — The ${DOORTITLE} — averagejoematt`;
  buildTabs(); buildSide(); renderCenter();
}
window.addEventListener("popstate", (e) => { const slug = (e.state && e.state.slug) || slugFromPath() || (REG[0] && REG[0].slug); current = BYSLUG[slug] ? slug : current; buildTabs(); buildSide(); renderCenter(); });


/* ── First-run orientation — mirrors the Cockpit's PG-02 card ─────────────────
   A dismissible "what am I looking at" card for first-time visitors to the Data
   archive. Shown once (localStorage), non-modal, sits above the instrument — never
   blocks the dense view a repeat reader uses. Injected from JS so the generated
   shells need no rebuild; scoped to the Data door for v1. Renders pre-fetch so it
   appears even when /api/* is unreachable (e.g. local QA). */

const INTRO_KEY = "ajm-data-intro-v1";

function wireFirstRun() {
  if (DOOR !== "data") return;
  let seen;
  try { seen = localStorage.getItem(INTRO_KEY); } catch (e) { seen = "1"; } // private mode → don't nag
  if (seen) return;
  const head = $(".page-hero");
  if (!head) return;

  const intro = document.createElement("aside");
  intro.className = "ev-intro";
  intro.setAttribute("aria-label", "What you're looking at");
  intro.innerHTML = `
    <button class="ev-intro__x" type="button" aria-label="Dismiss orientation">&times;</button>
    <p class="ev-intro__k label">new here?</p>
    <h2 class="ev-intro__h">Every source this one life is measured by.</h2>
    <ul class="ev-intro__list">
      <li><strong>Pick a topic</strong> on the left — grouped into <em>the body</em> and <em>mind &amp; accountability</em>. Its trend loads in the center; no page jumps.</li>
      <li>Labels like <em>N=1</em> or <em>preliminary</em> mean a correlation from a single life, not proof — and thin data is flagged, never faked.</li>
      <li><strong>Read-only.</strong> The numbers are the real ones; nothing here is medical advice.</li>
    </ul>
    <button class="ev-intro__go" type="button">Got it &mdash; show me the data</button>
    <p class="ev-intro__note label">Shown once. It won't interrupt again.</p>`;

  const onKey = (e) => { if (e.key === "Escape") dismiss(); };
  function dismiss() {
    try { localStorage.setItem(INTRO_KEY, "1"); } catch (e) {}
    document.removeEventListener("keydown", onKey);
    intro.remove();
  }
  intro.querySelector(".ev-intro__x").addEventListener("click", dismiss);
  intro.querySelector(".ev-intro__go").addEventListener("click", dismiss);
  document.addEventListener("keydown", onKey);
  head.insertAdjacentElement("afterend", intro);
}

initTheme();
wireFirstRun();
buildTabs();
buildSide();
renderCenter();

// Build stamp — muted deploy fingerprint in the footer (apples-to-apples in QA). Reads
// the <meta name="build"> the deploy script injects; no-op locally where it's absent.
(function () {
  try {
    const m = document.querySelector('meta[name="build"]');
    const foot = document.querySelector(".site-foot");
    if (!m || !m.content || !foot) return;
    const s = document.createElement("span");
    s.className = "build-stamp label";
    s.textContent = "build " + m.content.split(" ")[0];
    s.title = m.content;
    foot.appendChild(s);
  } catch (e) {}
})();
