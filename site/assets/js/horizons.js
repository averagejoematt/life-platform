/* horizons.js — the public Horizons feed (#1707, epic #1686 S3).
 *
 * Renders the coach-curated media picks + their grounded retrospectives (reverse-chron)
 * into [data-horizons] on /data/horizons/, from the read-only /api/horizons endpoint.
 * The retrospective is the narrative pull; a pick still awaiting next week's retrospective
 * shows an honest "coach's note coming" line (never a fabricated one). Fail-soft: an API
 * error or an empty feed both render an honest state, never a blank shell or a thrown page.
 */
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

async function getJSON(p) {
  const r = await fetch(p, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(p + " " + r.status);
  return r.json();
}

function card(it) {
  const meta =
    `<p class="hz-meta">` +
    `<span class="hz-format label">${esc(it.format || "pick")}</span>` +
    (it.source ? `<span class="hz-source">${esc(it.source)}</span>` : "") +
    (it.week ? `<span class="hz-week">${esc(it.week)}</span>` : "") +
    `</p>`;
  const title = it.url
    ? `<h3 class="hz-title"><a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title || "Untitled pick")}</a></h3>`
    : `<h3 class="hz-title">${esc(it.title || "Untitled pick")}</h3>`;
  const pitch = it.pitch ? `<p class="hz-pitch">${esc(it.pitch)}</p>` : "";
  // The reader hook: the coach's grounded "why I recommended it" retrospective, when it
  // has been archived (the week after). Until then, an honest pending line.
  const retro = it.retrospective
    ? `<div class="hz-retro"><span class="hz-retro-label">why the coach sent it</span>` +
      `<p class="hz-retro-text">${esc(it.retrospective)}</p></div>`
    : `<p class="hz-retro-pending">the coach's retrospective lands next week</p>`;
  const cta = it.url ? `<a class="hz-cta" href="${esc(it.url)}" target="_blank" rel="noopener">open →</a>` : "";
  return `<li class="hz-card">${meta}${title}${pitch}${retro}${cta}</li>`;
}

function render(root, data) {
  // The static page already ships the .page-hero (kicker + H1 + promise) above the
  // mount — render() fills ONLY the feed here, so we never duplicate the hero / emit
  // a second <h1> (render-QA #1707).
  const items = (data && data.items) || [];
  if (!items.length) {
    root.innerHTML = `<p class="hz-retro-pending">${esc((data && data.note) || "The Mind coach curates one pick a week — the first lands soon.")}</p>`;
    return;
  }
  // The API is reverse-chron already; belt-and-braces re-sort newest ISO-week first.
  items.sort((a, b) => String(b.week || "").localeCompare(String(a.week || "")));
  root.innerHTML = `<ul class="hz-feed">${items.map(card).join("")}</ul>`;
}

async function boot() {
  const root = document.querySelector("[data-horizons]");
  if (!root) return;
  root.innerHTML = `<p class="dx-loading shimmer">Loading the picks…</p>`;
  try {
    render(root, await getJSON("/api/horizons"));
  } catch (e) {
    root.innerHTML = `<p class="hz-retro-pending">The feed is resting — check back shortly.</p>`;
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
