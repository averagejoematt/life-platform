// grade_your_coach.js — the /method/grade-your-coach/ controller (#1396).
//
// Paste a prediction ledger, get the same scorecard this platform's own AI
// coaches get: Brier, reliability curve, skill vs. the base rate, and a verdict
// that refuses to flatter.
//
// EVERYTHING here runs in the reader's browser. There is no endpoint, no upload,
// no telemetry — the pasted text never leaves the page. That is a promise the
// page makes in its own copy, so it has to be structurally true: this module
// imports the scorer and calls it locally, and there is no fetch() of anything
// but the two static demo ledgers that ship with the site.
//
// The math itself lives in calibration-core.js — a byte-identical vendored copy
// of oss/calibration-core/js/calibration-core.js, held to the same test vectors
// as the deployed Python grader (tests/js/calibration_core.test.mjs). The
// numbers on this page are not "like" the platform's; they are the platform's.
import { parseLedgerText, scorePairs } from "/assets/js/calibration-core.js";

const DEMO_URL = "/data/calibration_demo.json";

const VERDICT_COPY = {
  "over-confident": "Stated confidence runs ahead of what actually happened. The classic advice-engine failure: it sounds certain more often than it is right.",
  "under-confident": "Stated confidence runs behind reality — this forecaster is better than it says it is, and is hedging.",
  "well-calibrated": "Stated confidence tracks observed rates, and the forecasts beat the base rate. Both halves are required for this verdict.",
  not_yet_skillful:
    "The stated confidences line up reasonably, but the forecasts do not beat simply guessing the base rate every time. Reliability without skill is not calibration — so this reads as not yet skillful, with its n and skill shown beside it.",
  insufficient_data: "Fewer than 5 resolved forecasts. There is not enough here to claim anything about calibration, so nothing is claimed.",
};

const LABEL_COPY = {
  nascent: "fewer than 3 resolved calls",
  not_yet_skillful: "skill at or below the base rate",
  developing: "resolved, but the Brier score is above 0.20",
  reliable: "Brier at or below 0.20",
  authoritative: "Brier at or below 0.15 across 12+ resolved calls",
};

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function el(html) {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d.firstElementChild;
}

function num(v, dp) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(dp);
}

/**
 * The reliability curve as inline SVG. Deliberately text-free: axis labels are
 * real HTML around the figure, so the chart never ships viewBox-scaled type that
 * would go sub-legible on a phone.
 */
function reliabilitySvg(bins) {
  const W = 320;
  const H = 320;
  const PAD = 8;
  const x = (p) => PAD + p * (W - 2 * PAD);
  const y = (p) => H - PAD - p * (H - 2 * PAD);
  const maxN = bins.reduce((m, b) => Math.max(m, b.n), 1);

  const pts = bins.map((b) => [x(b.mean_confidence), y(b.observed_rate), b]);
  const path = pts.length > 1 ? `<path class="gyc-curve" d="M${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L")}" fill="none"/>` : "";
  const dots = pts
    .map(([px, py, b]) => {
      const r = 3.5 + 5 * Math.sqrt(b.n / maxN);
      const title = `stated ${(b.mean_confidence * 100).toFixed(0)}% · happened ${(b.observed_rate * 100).toFixed(0)}% · n=${b.n}`;
      return `<circle class="gyc-dot" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${r.toFixed(1)}"><title>${esc(title)}</title></circle>`;
    })
    .join("");

  return (
    `<svg class="gyc-svg" viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid meet" ` +
    `aria-label="Reliability curve: stated confidence on the horizontal axis against how often those forecasts came true on the vertical axis. The diagonal is perfect calibration.">` +
    `<rect class="gyc-plot" x="${PAD}" y="${PAD}" width="${W - 2 * PAD}" height="${H - 2 * PAD}" rx="4"/>` +
    `<line class="gyc-ideal" x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}"/>` +
    path +
    dots +
    `</svg>`
  );
}

function binsTable(bins) {
  const rows = bins
    .map(
      (b) =>
        `<tr><td class="rd-name">${(b.lo * 100).toFixed(0)}–${(b.hi * 100).toFixed(0)}%</td>` +
        `<td class="num">${(b.mean_confidence * 100).toFixed(1)}%</td>` +
        `<td class="num">${(b.observed_rate * 100).toFixed(1)}%</td>` +
        `<td class="num">${b.n}</td></tr>`,
    )
    .join("");
  return (
    `<table class="rd-tbl gyc-tbl"><thead><tr><th>confidence band</th><th>said</th><th>happened</th><th>n</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`
  );
}

function statBlock(label, value, sub) {
  return `<div class="gyc-fig"><span class="gyc-fig-v">${esc(value)}</span><span class="gyc-fig-l label">${esc(label)}</span>${sub ? `<span class="gyc-fig-s">${esc(sub)}</span>` : ""}</div>`;
}

function renderScorecard(s, parsed) {
  const skillTxt = s.brier_skill === null ? "undefined" : num(s.brier_skill, 4);
  const skillSub =
    s.skilled === null
      ? "undefined — too few calls, or every outcome identical. Unknown, not unskilled."
      : s.skilled
        ? "beats guessing the base rate"
        : "WORSE than guessing the base rate";

  const figs =
    `<div class="gyc-figs">` +
    statBlock("resolved calls", String(s.n), `${s.confirmed} came true · ${s.refuted} did not`) +
    statBlock("Brier score", num(s.brier, 4), "0 perfect · 0.25 = always saying 50%") +
    statBlock("skill vs base rate", skillTxt, skillSub) +
    statBlock("hit rate", s.accuracy_pct === null ? "—" : `${num(s.accuracy_pct, 1)}%`, "the flattering number — read it last") +
    `</div>`;

  const verdictKey = s.calibration;
  const verdict =
    `<div class="gyc-verdict" data-verdict="${esc(verdictKey)}">` +
    `<p class="gyc-verdict-h">${esc(String(verdictKey).replace(/[-_]/g, " "))}</p>` +
    `<p class="gyc-verdict-b">${esc(VERDICT_COPY[verdictKey] || "")}</p>` +
    `<p class="gyc-label label">credibility: ${esc(String(s.label).replace(/_/g, " "))} (${s.score}/100) — ${esc(LABEL_COPY[s.label] || "")}</p>` +
    `</div>`;

  const curve = s.reliability_bins.length
    ? `<div class="gyc-chartwrap">` +
      `<div class="gyc-chart">${reliabilitySvg(s.reliability_bins)}` +
      `<p class="gyc-ax gyc-ax-x label">stated confidence &rarr;</p><p class="gyc-ax gyc-ax-y label">how often it happened &rarr;</p></div>` +
      binsTable(s.reliability_bins) +
      `</div>` +
      `<p class="gyc-axnote">Each dot is one confidence band; its size is how many calls landed there. On the diagonal means the stated confidence was honest. Above it means under-confident; below it means over-confident.</p>`
    : "";

  const bookkeeping = [];
  if (parsed.unresolved) bookkeeping.push(`${parsed.unresolved} row${parsed.unresolved === 1 ? "" : "s"} not yet resolved — counted, not guessed at, and excluded from every number above.`);
  if (parsed.notes.length) bookkeeping.push(`${parsed.notes.length} confidence value${parsed.notes.length === 1 ? "" : "s"} above 1 were read as percentages.`);
  if (parsed.rejected.length) {
    const list = parsed.rejected
      .slice(0, 8)
      .map((r) => `<li><code>line ${r.line}</code> — ${esc(r.reason)}: <code>${esc(r.raw.slice(0, 80))}</code></li>`)
      .join("");
    bookkeeping.push(
      `${parsed.rejected.length} row${parsed.rejected.length === 1 ? "" : "s"} could not be read and were left out rather than given a made-up confidence:<ul class="gyc-rejects">${list}</ul>`,
    );
  }
  const notes = bookkeeping.length ? `<div class="gyc-notes">${bookkeeping.map((b) => `<p>${b}</p>`).join("")}</div>` : "";

  return `<div class="gyc-card" data-readout data-state="scored">${figs}${verdict}${curve}${notes}</div>`;
}

function renderEmpty(parsed) {
  const why = parsed && parsed.unresolved
    ? `Every row you pasted is still unresolved (${parsed.unresolved} of them). A forecast whose outcome is not yet known cannot be graded, and guessing would be the exact dishonesty this tool exists to catch.`
    : "Nothing scorable was found. Each line needs a stated confidence and an outcome — for example <code>0.8, confirmed</code>.";
  const rejected =
    parsed && parsed.rejected && parsed.rejected.length
      ? `<ul class="gyc-rejects">${parsed.rejected.slice(0, 8).map((r) => `<li><code>line ${r.line}</code> — ${esc(r.reason)}: <code>${esc(r.raw.slice(0, 80))}</code></li>`).join("")}</ul>`
      : "";
  return `<div class="gyc-card gyc-empty" data-readout data-state="empty"><p><strong>Nothing to grade yet.</strong> ${why}</p>${rejected}</div>`;
}

function ledgerToText(ledger) {
  const lines = ["confidence,outcome"];
  for (const r of ledger.rows) lines.push(`${r.confidence},${r.outcome}`);
  return lines.join("\n");
}

export function grade(text) {
  const parsed = parseLedgerText(text);
  if (!parsed.pairs.length) return { parsed, html: renderEmpty(parsed) };
  return { parsed, html: renderScorecard(scorePairs(parsed.pairs), parsed) };
}

export function init() {
  const box = document.getElementById("gyc-input");
  const out = document.getElementById("gyc-readout");
  const prov = document.getElementById("gyc-prov");
  if (!box || !out) return;

  let demos = null;

  const run = () => {
    const { html } = grade(box.value);
    out.replaceChildren(el(html));
  };

  box.addEventListener("input", run);
  document.getElementById("gyc-grade")?.addEventListener("click", run);
  document.getElementById("gyc-clear")?.addEventListener("click", () => {
    box.value = "";
    if (prov) prov.textContent = "";
    run();
  });

  const loadDemo = (key) => {
    if (!demos || !demos[key]) return;
    const d = demos[key];
    box.value = ledgerToText(d);
    if (prov) prov.textContent = d.provenance_line || "";
    run();
  };
  document.getElementById("gyc-demo-matthew")?.addEventListener("click", () => loadDemo("matthew"));
  document.getElementById("gyc-demo-example")?.addEventListener("click", () => loadDemo("example"));

  fetch(DEMO_URL, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      demos = d;
      loadDemo("example"); // a first-time reader sees a filled-in scorecard
    })
    .catch(() => {
      run();
    });
}

if (typeof document !== "undefined" && document.getElementById("gyc-input")) init();
