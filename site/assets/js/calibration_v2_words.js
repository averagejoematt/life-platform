// calibration_v2_words.js — calibration-v2's three answers, in the words the API serves them (owner ruling 2026-11-09).
//
// The calibration verdict on every page is calibration-v2 (`/api/calibration` → `assessment_v2`,
// docs/methods/CALIBRATION_V2.md). Three separate questions, never one label:
//   1. Can calibration across confidence levels be estimated?
//   2. Is there statistically supported over- or under-confidence at an observed confidence level?
//   3. Does the coach beat the same-call guess that nothing changes?
// Each answer's words are the server's (`wording`, and `short` for a dense cell) — nothing is computed, relabelled or
// softened here. The deprecated v1 fields (`calibration`, `label`, `score`) are never read by this module.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);

/** The three questions, in the order every surface asks them. */
export const QUESTIONS = [
  { key: "estimability", ask: "Can calibration be estimated across confidence levels?" },
  { key: "confidence_direction", ask: "Over- or under-confident at an observed confidence level?" },
  { key: "skill", ask: "Better than the same-call guess that nothing changes?" },
];

/** A coach's served assessment (short id, e.g. "sleep"), or null. */
export function v2Coach(d, cid) {
  const a = d && d.assessment_v2;
  return (a && a.coaches && a.coaches[cid]) || null;
}

/** A platform stratum's served assessment ("coaches", "hypotheses", "interval_forecasts", …), or null. */
export function v2Stratum(d, name) {
  const a = d && d.assessment_v2;
  return (a && a.strata && a.strata[name]) || null;
}

function answer(a, key) {
  const q = a && a[key];
  return q && typeof q === "object" ? q : null;
}

/** The three answers as a definition list, each in the server's full words. "" when no assessment was served. */
export function answersHTML(a, { cls = "cv2-answers" } = {}) {
  if (!a || typeof a !== "object") return "";
  const rows = QUESTIONS.map(({ key, ask }) => {
    const q = answer(a, key);
    const words = q && (q.wording || q.short);
    return words ? `<div class="cv2-row"><dt>${esc(ask)}</dt><dd>${esc(words)}</dd></div>` : "";
  }).join("");
  return rows ? `<dl class="${esc(cls)}">${rows}</dl>` : "";
}

/** The three answers in short form for a dense table cell, one per line. "—" when no assessment was served. */
export function shortHTML(a) {
  if (!a || typeof a !== "object") return "—";
  const parts = QUESTIONS.map(({ key }) => {
    const q = answer(a, key);
    const words = q && (q.short || q.wording);
    return words ? `<span class="cv2-short">${esc(words)}</span>` : "";
  }).filter(Boolean);
  return parts.length ? parts.join("<br>") : "—";
}

/** One sentence naming the method and its version — the adoption date and what it replaced. */
export function methodLine(d) {
  const a = (d && d.assessment_v2) || {};
  const m = (d && d.calibration_method) || {};
  const version = a.method_version || m.version;
  if (!version) return "";
  const adopted = a.adopted || m.adopted;
  return (
    `<p class="cs-fresh cv2-method">Calibration verdicts use ${esc(version)}${adopted ? `, adopted ${esc(adopted)}` : ""}: three separate questions, each with its own test and 95% interval, ` +
    "with over- and under-confidence tested level by level and corrected for multiple testing (Holm). Not detecting a problem is never read as proof of good calibration. " +
    `It replaced a single label per coach. <a href="https://github.com/averagejoematt/life-platform/blob/main/docs/methods/CALIBRATION_V2.md">The method note</a>.</p>`
  );
}
