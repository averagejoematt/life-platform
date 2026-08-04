/*
  evidence_character_provenance.js — #1982 (ADR-105): the "What feeds each
  pillar" component rows on /data/character/ render every scalar target field
  but the row-builder filters out anything with `typeof v !== "object"` — and
  `target_provenance` IS an object, so it silently fell through. The field is
  served (/api/character_config, personal_baselines.derive_component_target)
  on every derivable target: a personal-variance band (n-backed, p75 of the
  reader's own 365-day distribution) rendered identically to an authored
  commitment. This chip is the honest disclosure.

  Split from evidence_character.js so it's DOM-free and unit-testable (the
  evidence_receipts.js precedent — that module's import graph pulls share.js,
  which touches `window` at import time).
*/
import { esc } from "/assets/js/evidence_shared.js";

export function chProvenance(cv) {
  const prov = cv && typeof cv === "object" ? cv.target_provenance : null;
  if (!prov || typeof prov !== "object") return "";
  if (prov.source === "personal") {
    const method = String(prov.method || "").replace(/^percentile_band_/, "");
    const bits = [`personal · ${method || "band"}`];
    if (prov.window_days) bits.push(`${prov.window_days}d`);
    bits.push(`n=${prov.n ?? "?"}`);
    if (prov.clamped) bits.push("clamped to guardrail");
    return `<span class="ch-comp-prov is-personal" title="derived from your own historical distribution"><span class="pv-src">${esc(bits.join(" · "))}</span></span>`;
  }
  return `<span class="ch-comp-prov is-prior" title="authored default — not yet enough personal history to derive one">${esc(prov.label || "authored commitment")}</span>`;
}
