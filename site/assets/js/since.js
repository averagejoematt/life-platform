/*
  since.js — the shared "since your last visit" reader (uplevel P5).
  ----------------------------------------------------------------------------
  Returnability, keyed to the READER's own gap via localStorage (no accounts,
  privacy-clean). The cockpit's renderSinceLastVisit stays the sole WRITER of
  record for the `amj_last_visit` stamp — this module only READS it, so landing
  on Home or Story never eats the cockpit's richer since-view, and a Story visit
  never re-stamps a reader who hasn't seen the cockpit yet.

  Exposes:
    sinceStamp()          → epoch-ms of the last cockpit visit, or null
    sinceGapDays()        → whole days since the stamp (null if no usable stamp)
    isNewSince(isoDate)   → true when content dated after the reader's stamp
    mountSinceRibbon(el)  → one calm line + deltas from /api/changes-since;
                            self-hides on first visit / <12h gap / fetch failure
                            / nothing moved (honest silence, same as the cockpit)
*/

const _LV_KEY = "amj_last_visit";

export function sinceStamp() {
  try {
    const raw = localStorage.getItem(_LV_KEY);
    const ts = raw ? parseInt(raw, 10) : NaN;
    const now = Date.now();
    if (!Number.isFinite(ts) || ts <= 0 || ts > now || now - ts > 365 * 86400000) return null;
    return ts;
  } catch (e) { return null; }
}

export function sinceGapDays() {
  const ts = sinceStamp();
  if (ts == null) return null;
  return Math.max(0, Math.round((Date.now() - ts) / 86400000));
}

export function isNewSince(isoDate) {
  const ts = sinceStamp();
  if (ts == null || !isoDate) return false;
  const t = Date.parse(`${String(isoDate).slice(0, 10)}T12:00:00`);
  return Number.isFinite(t) && t > ts;
}

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export async function mountSinceRibbon(el) {
  if (!el) return;
  const ts = sinceStamp();
  if (ts == null) return;                    // first visit → nothing to say
  const gapH = (Date.now() - ts) / 3600000;
  if (gapH < 12) return;                     // same-day reload → silence
  let d = null;
  try {
    const r = await fetch(`/api/changes-since?ts=${Math.floor(ts / 1000)}`, { headers: { accept: "application/json" } });
    if (!r.ok) return;
    d = await r.json();
  } catch (e) { return; }
  const deltas = (d && d.deltas) || {};
  const METRICS = [
    { key: "weight", label: "weight", unit: " lb" },
    { key: "hrv", label: "HRV", unit: " ms" },
    { key: "sleep", label: "sleep", unit: " h" },
    { key: "character", label: "character", unit: " pts" },
  ];
  const bits = METRICS.filter((m) => deltas[m.key] && deltas[m.key].from != null && deltas[m.key].to != null).map((m) => {
    const x = deltas[m.key];
    const chg = Number(x.change);
    const chgTxt = Number.isFinite(chg) ? ` (${chg > 0 ? "+" : ""}${Math.round(chg * 10) / 10}${m.unit})` : "";
    return `<span class="sv-bit"><span class="label">${esc(m.label)}</span> ${esc(String(x.from))} → ${esc(String(x.to))}${esc(chgTxt)}</span>`;
  });
  if (!bits.length) return;                  // nothing moved → honest silence
  const days = Math.max(1, Math.round(gapH / 24));
  el.innerHTML =
    `<p class="sv-line"><span class="sv-k label">since your last visit · ${days === 1 ? "a day" : `${days} days`} away</span> ` +
    bits.join(" · ") + ` <a class="sv-more" href="/cockpit/">the cockpit has the full read →</a></p>`;
  el.hidden = false;
}
