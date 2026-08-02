// mirror.js — the /method/mirror/ controller (#1392).
//
// Drop a Whoop CSV export; get scored by the SAME deterministic instruments that
// score Matthew every night, then see your numbers laid over his published
// distributions. EVERYTHING runs in this browser:
//
//   - the file is read with FileReader/file.text() and never leaves the page —
//     there is no upload endpoint on this site to send it to;
//   - the ONLY network request this module makes is a GET of the published
//     distributions artifact (his data, flowing to you — never yours, anywhere);
//   - persistence is localStorage under one key, with a visible clear control.
//
// Those are promises the page makes in its own copy, so they are enforced
// structurally: tests/test_mirror_parity.py pins this module to exactly one
// fetch() (DIST_URL) and zero XHR/beacon/WebSocket/EventSource.
//
// The math lives in mirror-core.js, pinned to the deployed Python by
// tests/vectors/mirror_vectors.json (see that file's header). This module is
// only DOM: read files, call the core, render.
import { extractWhoopExport, mergeExtracts, buildDays, percentileRank, percentile, MIN_N } from "/assets/js/mirror-core.js";
import { DEMO_CSV, DEMO_LABEL } from "/assets/js/mirror_demo.js";

const DIST_URL = "/data/mirror_distributions.json";
const STORE_KEY = "ajm-mirror-v1";

// metric key in the distributions artifact → how to read the same quantity off a
// scored day, plus display formatting. `value` reads from the day's normalized
// record so both sides of the overlay use identical field semantics.
const OVERLAY_METRICS = [
  { key: "recovery_score", label: "recovery", unit: "%", dp: 0, value: (d) => d.record.recovery_score ?? null },
  { key: "hrv", label: "HRV (RMSSD)", unit: "ms", dp: 1, value: (d) => d.record.hrv ?? null },
  { key: "resting_heart_rate", label: "resting HR", unit: "bpm", dp: 0, value: (d) => d.record.resting_heart_rate ?? null },
  { key: "sleep_duration_hours", label: "sleep duration", unit: "h", dp: 2, value: (d) => d.sleep_norm?.sleep_duration_hours ?? null },
  { key: "sleep_performance", label: "sleep performance", unit: "%", dp: 0, value: (d) => d.sleep_norm?.sleep_score ?? null },
  { key: "strain", label: "day strain", unit: "", dp: 1, value: (d) => d.record.strain ?? null },
];

const state = { records: null, files: [], synthetic: false, dist: null, distErr: false };

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function num(v, dp) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(dp);
}

function ordinal(p) {
  if (p < 1) return "&lt;1st";
  if (p > 99) return "&gt;99th";
  const n = Math.round(p);
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${n}${suffix}`;
}

// ── persistence ───────────────────────────────────────────────────────────

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ records: state.records, files: state.files, synthetic: state.synthetic }));
  } catch (e) {
    /* storage full/blocked — the session still works, it just won't persist */
  }
}

function restore() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    if (!saved || typeof saved.records !== "object" || !saved.records) return false;
    state.records = saved.records;
    state.files = Array.isArray(saved.files) ? saved.files : [];
    state.synthetic = Boolean(saved.synthetic);
    return true;
  } catch (e) {
    return false;
  }
}

function clearAll() {
  try {
    localStorage.removeItem(STORE_KEY);
  } catch (e) {
    /* ignore */
  }
  state.records = null;
  state.files = [];
  state.synthetic = false;
  render();
}

// ── ingest ────────────────────────────────────────────────────────────────

async function ingestFiles(fileList) {
  const files = Array.from(fileList).filter((f) => /\.csv$/i.test(f.name));
  if (!files.length) {
    setProv("No .csv file found in that drop. Unzip the Whoop export and drop physiological_cycles.csv (and, optionally, sleeps.csv).");
    return;
  }
  const extracts = [];
  let skipped = 0;
  let unrecognised = 0;
  for (const f of files) {
    const ex = extractWhoopExport(await f.text());
    if (ex.meta.kind === "unrecognised") unrecognised++;
    else {
      extracts.push(ex);
      skipped += ex.meta.skipped;
    }
  }
  if (!extracts.length) {
    setProv("None of those files look like a Whoop export — no “Cycle start time” / “Sleep onset” column found. Nothing was read, and (as always) nothing left this page.");
    return;
  }
  state.records = mergeExtracts(extracts);
  state.files = files.map((f) => f.name);
  state.synthetic = false;
  save();
  render(skipped, unrecognised);
}

function loadDemo() {
  const ex = extractWhoopExport(DEMO_CSV);
  state.records = ex.records;
  state.files = ["synthetic worked example"];
  state.synthetic = true;
  save();
  render(ex.meta.skipped, 0);
}

// ── render ────────────────────────────────────────────────────────────────

function setProv(html) {
  document.getElementById("mirror-prov").innerHTML = html;
}

function colourChip(colour) {
  return `<span class="mr-chip mr-chip-${esc(colour)}">${esc(colour)}</span>`;
}

function bandSvg(sample, userVal) {
  const p5 = percentile(sample, 5);
  const p25 = percentile(sample, 25);
  const p50 = percentile(sample, 50);
  const p75 = percentile(sample, 75);
  const p95 = percentile(sample, 95);
  let lo = Math.min(sample[0], userVal);
  let hi = Math.max(sample[sample.length - 1], userVal);
  if (hi === lo) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.04;
  lo -= pad;
  hi += pad;
  const W = 320;
  const x = (v) => ((v - lo) / (hi - lo)) * W;
  // Text-free by design (the gyc precedent): numbers live in the HTML beside the
  // strip so the chart never ships viewBox-scaled type. Bands wear neutral
  // surface/rule tokens; the reader's marker is the single accent with a
  // 2px surface ring so it survives sitting on top of the inner band.
  return (
    `<svg class="mr-svg" viewBox="0 0 ${W} 44" role="img" aria-hidden="true" focusable="false">` +
    `<rect class="mr-band" x="${x(p5).toFixed(1)}" y="16" width="${(x(p95) - x(p5)).toFixed(1)}" height="12" rx="4"></rect>` +
    `<rect class="mr-band-inner" x="${x(p25).toFixed(1)}" y="16" width="${(x(p75) - x(p25)).toFixed(1)}" height="12" rx="4"></rect>` +
    `<line class="mr-median" x1="${x(p50).toFixed(1)}" y1="10" x2="${x(p50).toFixed(1)}" y2="34"></line>` +
    `<circle class="mr-you" cx="${x(userVal).toFixed(1)}" cy="22" r="5"></circle>` +
    `</svg>`
  );
}

function renderBands(days) {
  const host = document.getElementById("mirror-bands");
  if (!state.dist) {
    host.innerHTML = state.distErr
      ? '<p class="mr-note">His published distributions could not be fetched just now — your scores above are unaffected (they never depended on the network).</p>'
      : "";
    return;
  }
  const last30 = days.slice(-30);
  const windowMeta = state.dist.window || {};
  const rows = OVERLAY_METRICS.map((m) => {
    const dist = (state.dist.metrics || {})[m.key];
    const vals = last30.map(m.value).filter((v) => v !== null && v !== undefined);
    if (!dist || !dist.n) return "";
    if (!vals.length) {
      return (
        `<div class="mr-row"><div class="mr-row-h"><span class="mr-metric">${esc(m.label)}</span>` +
        `<span class="mr-row-note">not in your export</span></div></div>`
      );
    }
    const yours = percentile(vals, 50);
    const pct = percentileRank(dist.sample, yours);
    const his = percentile(dist.sample, 50);
    return (
      `<div class="mr-row">` +
      `<div class="mr-row-h"><span class="mr-metric">${esc(m.label)}</span>` +
      `<span class="mr-row-note">your 30-day median <strong>${num(yours, m.dp)}${esc(m.unit)}</strong> &middot; his ${ordinal(pct)} percentile</span></div>` +
      bandSvg(dist.sample, yours) +
      `<p class="mr-row-sub">his median ${num(his, m.dp)}${esc(m.unit)} &middot; band his p5&ndash;p95 &middot; inner band p25&ndash;p75 &middot; n=${dist.n} days</p>` +
      `</div>`
    );
  }).join("");
  host.innerHTML =
    `<div class="mr-legend"><span class="mr-you-dot" aria-hidden="true"></span> you &middot; ` +
    `<span class="mr-band-key" aria-hidden="true"></span> his p5&ndash;p95 &middot; ` +
    `<span class="mr-median-key" aria-hidden="true"></span> his median</div>` +
    rows +
    `<p class="mr-note">His side: one value per day over ${esc(windowMeta.start || "?")} &rarr; ${esc(windowMeta.end || "?")}, ` +
    `published in <a href="/data/mirror_distributions.json">the same artifact this page fetches</a>. ` +
    `Percentiles are exact midranks over that sample &mdash; computed here, not served.</p>`;
}

// The zero-friction rung (the old /method/mirror/ widget, upgraded): type one
// number off the watch face, see its exact midrank percentile in the published
// year. Reuses the old widget's .mi-* classes so no new CSS ships for it.
const QUICK_METRICS = [
  ["recovery_score", "Recovery this morning (%)", 1],
  ["hrv", "HRV (RMSSD, ms)", 0.1],
  ["resting_heart_rate", "Resting heart rate (bpm)", 1],
  ["sleep_duration_hours", "Sleep last night (hours)", 0.1],
];

function renderQuick() {
  const host = document.getElementById("mirror-quick");
  if (!host) return;
  if (!state.dist) {
    host.innerHTML = state.distErr ? '<p class="mr-note">Distributions unavailable just now — try a reload.</p>' : "";
    return;
  }
  const rows = QUICK_METRICS.map(([k, label, step]) => {
    const dist = (state.dist.metrics || {})[k];
    if (!dist || !dist.n) return "";
    return (
      `<div class="mi-row"><label class="label" for="mi-${esc(k)}">${esc(label)}</label>` +
      `<input id="mi-${esc(k)}" class="ask-in mi-in" type="number" step="${step}" data-mi="${esc(k)}">` +
      `<span class="mi-out" data-mi-out="${esc(k)}"></span></div>`
    );
  }).join("");
  host.innerHTML = `<div class="mi-grid">${rows}</div>`;
  host.querySelectorAll(".mi-in").forEach((inp) =>
    inp.addEventListener("input", () => {
      const k = inp.dataset.mi;
      const v = parseFloat(inp.value);
      const out = host.querySelector(`[data-mi-out="${k}"]`);
      const dist = (state.dist.metrics || {})[k];
      if (!out || !dist) return;
      if (!isFinite(v)) {
        out.textContent = "";
        return;
      }
      const pct = percentileRank(dist.sample, v);
      out.textContent = `his ${ordinal(pct).replace("&lt;", "<").replace("&gt;", ">")} percentile of ${dist.n} days`;
    })
  );
}

function render(skipped = 0, unrecognised = 0) {
  const readout = document.getElementById("mirror-readout");
  const bands = document.getElementById("mirror-bands");
  if (!state.records || !Object.keys(state.records).length) {
    readout.innerHTML =
      '<p class="mr-empty" data-readout>No export loaded yet. Drop your Whoop CSV on the left — or load the synthetic example to see what you’ll get. Nothing you drop here is uploaded, to anyone, ever.</p>';
    bands.innerHTML = "";
    setProv("");
    return;
  }
  const { days, baselines, band_n } = buildDays(state.records);
  const scored = days.filter((d) => d.readiness !== null);
  const latest = scored.length ? scored[scored.length - 1] : null;

  const provBits = [];
  provBits.push(state.synthetic ? `<strong>${esc(DEMO_LABEL)}</strong>` : `Read ${esc(state.files.join(", "))}.`);
  provBits.push(`${days.length} day${days.length === 1 ? "" : "s"} parsed${skipped ? `, ${skipped} row${skipped === 1 ? "" : "s"} skipped` : ""}${unrecognised ? `, ${unrecognised} file${unrecognised === 1 ? "" : "s"} unrecognised` : ""}.`);
  provBits.push("Stored only in this browser.");
  setProv(provBits.join(" "));

  if (!latest) {
    readout.innerHTML = '<p class="mr-empty" data-readout>Parsed, but no day carried a scoreable field (recovery, sleep or HRV). If this is a real Whoop export, that would be surprising — check it is physiological_cycles.csv.</p>';
    bands.innerHTML = "";
    return;
  }

  const personal = Boolean(baselines.readiness_hrv_ratio);
  const baselineLine = personal
    ? `Your HRV-trend thresholds derive from <strong>your own</strong> ratio distribution (n=${baselines.readiness_hrv_ratio.n} &ge; ${MIN_N}) &mdash; the same personal-variance machinery his run under (ADR-105).`
    : `Fewer than ${MIN_N} days of HRV history in this export (n=${band_n}), so the HRV-trend map stays on the population fallback &mdash; labelled, exactly as his platform behaves below the same floor.`;

  const breakdown = latest.readiness_breakdown
    .map((c) => `<div class="mr-fig"><span class="mr-fig-v">${num(c.score, 0)}</span><span class="mr-fig-l">${esc(c.key.replace("_", " "))} &times; ${c.weight}</span></div>`)
    .join("");
  const absent = ["training load (TSB)"];
  if (!latest.readiness_breakdown.some((c) => c.key === "sleep")) absent.unshift("sleep");

  readout.innerHTML =
    `<div data-readout>` +
    `<p class="mr-latest-h">latest scored day &middot; <strong>${esc(latest.date)}</strong></p>` +
    `<div class="mr-headline"><span class="mr-score">${num(latest.readiness, 0)}</span>${colourChip(latest.readiness_colour)}<span class="mr-headline-l">readiness, on his instrument</span></div>` +
    `<div class="mr-figs">${breakdown}</div>` +
    `<p class="mr-sub">Absent from your export, so absent from the weighting &mdash; not zeroed: ${esc(absent.join(", "))}. ` +
    `The score renormalises over what your data actually contains.</p>` +
    `<div class="mr-pillars">` +
    `<div class="mr-fig"><span class="mr-fig-v">${num(latest.sleep_pillar, 0)}</span><span class="mr-fig-l">sleep pillar</span></div>` +
    `<div class="mr-fig"><span class="mr-fig-v">${num(latest.recovery_pillar, 0)}</span><span class="mr-fig-l">recovery pillar</span></div>` +
    `<div class="mr-fig"><span class="mr-fig-v">${num(latest.hrv_7d, 1)}<span class="mr-fig-u">/${num(latest.hrv_30d, 1)}</span></span><span class="mr-fig-l">HRV 7d / 30d, ms</span></div>` +
    `<div class="mr-fig"><span class="mr-fig-v">${scored.length}</span><span class="mr-fig-l">days scored</span></div>` +
    `</div>` +
    `<p class="mr-sub">${baselineLine}</p>` +
    `</div>`;

  renderBands(days);
}

// ── init ──────────────────────────────────────────────────────────────────

function init() {
  const input = document.getElementById("mirror-file");
  const drop = document.getElementById("mirror-drop");
  input.addEventListener("change", () => input.files.length && ingestFiles(input.files));
  ["dragover", "dragenter"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("mr-drop-hot");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("mr-drop-hot");
    })
  );
  drop.addEventListener("drop", (e) => e.dataTransfer?.files?.length && ingestFiles(e.dataTransfer.files));
  document.getElementById("mirror-demo").addEventListener("click", loadDemo);
  document.getElementById("mirror-clear").addEventListener("click", clearAll);

  restore();
  render();
  // The page's ONLY network request: his published distributions. GET, static,
  // carries nothing of yours. Rendering never waits on it for your scores.
  fetch(DIST_URL)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((dist) => {
      state.dist = dist;
      renderQuick();
      if (state.records) render();
    })
    .catch(() => {
      state.distErr = true;
      renderQuick();
      if (state.records) render();
    });
}

init();
