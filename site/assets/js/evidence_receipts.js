/*
  evidence_receipts.js — the #1373 progression-receipt drill-down for
  /data/character/: which inputs moved, what rule fired, what the delta was —
  plus formula version, config hash, replay digest, and the server-side replay
  verdict, provenance-labeled. Split from evidence_character.js so the renderer
  is DOM-free and unit-testable (the evidence_router precedent — that module's
  import graph pulls share.js, which touches window at import time).

  Honest by construction: a date with no stored receipt says so (ADR-104 —
  nothing back-fabricated), a replay that no longer matches is SHOWN, and a
  config/engine change since the receipt reads as "rules changed since", never
  a silent re-render under today's rules.
*/
import { esc, tryJSON, fmt, ttl } from "/assets/js/evidence_shared.js";

/* Local XP-delta chip — same classes as evidence_character.js's chDelta (that
   module is not importable from here without dragging its DOM-side imports). */
const xpDelta = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return `<span class="ch-d ch-d0">0</span>`;
  return n > 0 ? `<span class="ch-d ch-dup">+${fmt(n)}</span>` : `<span class="ch-d ch-ddn">−${fmt(Math.abs(n))}</span>`;
};

/* The rule that fired, derived from the transition's outputs — display label
   only; the authoritative rule engine is server-side (character_engine). */
export function rcptRule(t) {
  const o = (t && t.outputs) || {}, i = (t && t.inputs) || {};
  const evs = (o.events || []).map((e) => String(e.type || ""));
  if (evs.length) return evs.map((x) => ttl(x)).join(" + ");
  if (o.coverage_hold) return "no-signal hold — coverage below the floor, levels frozen both ways";
  if (i.not_instrumented) return "not instrumented — no XP judgment either way";
  if (Number(o.streak_above) > 0) return `up-streak building (day ${Math.round(Number(o.streak_above))})`;
  if (Number(o.streak_below) > 0) return `down-streak building (day ${Math.round(Number(o.streak_below))})`;
  return "steady — XP only, no level pressure";
}

export function rcptHtml(body, date) {
  if (!body || body.available === false || !body.receipt) {
    return `<p class="rd-archive">No receipt recorded for ${esc(String(date || "this change"))} — receipts began with the audit layer (#1373); earlier changes have no recorded inputs and nothing gets back-fabricated to look audited.</p>`;
  }
  const r = body.receipt, tr = r.transitions || {}, pillars = tr.pillars || {};
  const rep = body.replay || null;
  const repOk = rep && (rep.verified != null ? rep.verified : rep.digest_match);
  let verdict;
  if (repOk) verdict = `<p class="rd-archive"><strong>Replay verified</strong> — the stored inputs, run back through the live engine just now, reproduce this digest exactly.</p>`;
  else if (rep && (rep.config_drift || rep.engine_drift)) verdict = `<p class="rd-archive"><strong>Rules have changed since</strong> — this receipt was written under ${rep.engine_drift ? `engine v${esc(String(r.engine_version || "?"))} (now v${esc(String(rep.current_engine_version || "?"))})` : "an earlier config"}${rep.config_drift && rep.engine_drift ? " and an earlier config" : ""}. The record stands as written; it is not rewritten to match today's rules.</p>`;
  else if (rep && rep.available === false) verdict = `<p class="rd-archive">Replay unavailable right now — the receipt below is served as stored.</p>`;
  else if (rep) verdict = `<p class="rd-archive"><strong>Replay mismatch</strong> — same rules, different result. That should be impossible; it is flagged to the nightly QA alarm, not hidden.</p>`;
  else verdict = "";

  const moved = Object.entries(pillars).filter(([, t]) => ((t.outputs || {}).events || []).length || Number((t.outputs || {}).xp_delta) !== 0 || (t.outputs || {}).coverage_hold);
  const rows = (moved.length ? moved : Object.entries(pillars)).map(([name, t]) => {
    const i = t.inputs || {}, o = t.outputs || {};
    const prevLv = i.prev ? Number(i.prev.level) : 1;
    const lvBit = Number(o.level) !== prevLv ? `Lv <strong class="num">${esc(String(prevLv))} → ${esc(String(Math.round(Number(o.level))))}</strong>` : `Lv <span class="num">${esc(String(Math.round(Number(o.level))))}</span> (held)`;
    const xpBit = `XP ${xpDelta(o.xp_delta)}${Number(o.xp_debt) > 0 ? ` · debt <span class="num">${fmt(o.xp_debt)}</span>` : ""}`;
    const inBits = [
      i.raw_score != null ? `raw <span class="num">${fmt(i.raw_score)}</span>` : "raw —",
      i.level_score != null ? `smoothed <span class="num">${fmt(i.level_score)}</span>` : "",
      i.data_coverage != null ? `coverage <span class="num">${Math.round(Number(i.data_coverage) * 100)}%</span>` : "",
      Number(i.bonus_xp) ? `challenge <span class="num">+${fmt(i.bonus_xp)}</span> XP` : "",
      i.presence_dark ? `<span class="label">dark stretch</span>` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="ch-comp"><span class="ch-comp-n" style="color:var(--pillar-${esc(name)},var(--ember))">${esc(ttl(name))}</span><span class="ch-comp-t">${lvBit} · ${xpBit}<br><span class="label">rule: ${esc(rcptRule(t))}</span><br><span class="label">inputs: </span>${inBits}</span></div>`;
  }).join("");

  const inputRows = r.input_rows || [];
  const rowCount = inputRows.reduce((n, g) => n + ((g.sks && g.sks.length) || (g.values && g.values.length) || 0), 0);
  const provList = inputRows.map((g) => g.pk
    ? `<li class="label">${esc(g.pk)} — ${esc(String((g.sks || []).length))} row${(g.sks || []).length === 1 ? "" : "s"} (${esc((g.sks || []).slice(0, 3).join(", "))}${(g.sks || []).length > 3 ? ", …" : ""})</li>`
    : `<li class="label">derived · ${esc(String(g.derived || ""))}: ${esc((g.values || []).join(", "))}</li>`).join("");
  const prov = inputRows.length
    ? `<details class="ch-rcpt-prov"><summary class="label">${esc(String(rowCount))} contributing input rows (keys, not copies)</summary><ul class="ch-rcpt-rows">${provList}</ul></details>`
    : `<p class="rd-archive">No input-row keys on this receipt.</p>`;

  const hl = tr.headline || null;
  const hlBit = hl && hl.outputs ? `<p class="label">headline: Lv ${esc(String((hl.inputs || {}).prev_character_level != null ? hl.inputs.prev_character_level : "?"))} → ${esc(String(hl.outputs.character_level))} — the floored weighted mean of the pillar levels</p>` : "";

  return `${verdict}${hlBit}<div class="ch-comps">${rows}</div>${prov}
    <p class="label">engine v${esc(String(r.engine_version || "?"))} · config ${esc(String(r.config_hash || "").slice(0, 12))} · digest ${esc(String(r.digest || "").slice(0, 12))}${r.replay_verified === false ? " · self-verify FAILED at write time" : ""}</p>`;
}

/* Lazy-load wiring: each timeline entry carries <details data-rcpt="date">;
   the receipt is fetched (verify=1 — server-side replay) on first open. */
export function wireReceipts() {
  document.querySelectorAll("details[data-rcpt]").forEach((det) => {
    det.addEventListener("toggle", async () => {
      if (!det.open || det.dataset.rcptLoaded) return;
      det.dataset.rcptLoaded = "1";
      const body = det.querySelector("[data-rcpt-body]");
      if (!body) return;
      const payload = await tryJSON(`/api/character_receipt?date=${encodeURIComponent(det.dataset.rcpt)}&verify=1`);
      body.innerHTML = rcptHtml(payload, det.dataset.rcpt);
    });
  });
}
