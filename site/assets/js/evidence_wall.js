/* evidence_wall.js — #1379: the Wall (the all-attempts field of daily fingerprints).

   Renders /api/wall into the archive readout: every experiment cycle as a row of
   daily marks. Each mark is the CANONICAL server-rendered SVG (lambdas/web/fingerprint.py)
   injected verbatim — no client-side mark maths, no new dependency. The living attempt
   glows where it earned it; sealed attempts show date-only marks (their real metrics
   are retained in the archive, just not displayed here — #1818, not "no data"); a
   staged attempt (genesis not yet reached, #1822) draws no marks at all — it hasn't
   begun. A reader watches one attempt die, the next begin, and the next-next wait. */

import { esc, empty } from "/assets/js/evidence_shared.js";

export function renderWall(data) {
  const wall = data && data.wall;
  const attempts = (wall && wall.attempts) || [];
  if (!attempts.length) return empty("No attempts on the wall yet — the field fills in as the days accrue.");

  const legend =
    `<p class="wall-legend">Every day is a mark — a pure function of that day's real numbers, drawn in code. ` +
    `The <strong>ember glow is earned</strong>; a faint, dashed mark on a sealed attempt is date-only — ` +
    `that day's real metrics are still in the archive, just not displayed here (never faked, never erased). ` +
    `<a href="/method/fingerprint/">How the mapping works &rarr;</a></p>`;

  const rows = attempts
    .map((a) => {
      if (a.staged) {
        const n = a.days_until_start;
        const t = n != null ? `begins in ${n} day${n === 1 ? "" : "s"}` : "begins soon";
        return (
          `<section class="wall-attempt is-staged">` +
          `<header class="wall-head"><span class="wall-n label">attempt ${esc(String(a.cycle))}</span>` +
          `<span class="wall-genesis label">from ${esc(a.genesis)}</span>` +
          `<span class="wall-status wall-staged">${esc(t)} &middot; staged</span></header>` +
          `<div class="wall-field wall-field-staged" role="img" aria-label="Attempt ${esc(String(a.cycle))}: staged, not yet begun">` +
          `<span class="wall-staged-note">no marks yet — the day hasn't happened</span></div>` +
          `</section>`
        );
      }
      const cells = (a.days || [])
        .map(
          (d) =>
            `<span class="wall-cell${d.warming_up ? " is-warming" : ""}" ` +
            `title="${esc(d.date)} · day ${d.day_number}${d.warming_up ? " · date-only mark" : ""}">${d.svg}</span>`,
        )
        .join("");
      const status = a.alive
        ? `<span class="wall-status wall-live">alive &middot; day ${a.day_count}</span>`
        : `<span class="wall-status wall-dead">ended ${esc(a.ended || "")} &middot; ${a.day_count} day${a.day_count === 1 ? "" : "s"}</span>`;
      return (
        `<section class="wall-attempt${a.alive ? " is-live" : ""}">` +
        `<header class="wall-head"><span class="wall-n label">attempt ${esc(String(a.cycle))}</span>` +
        `<span class="wall-genesis label">from ${esc(a.genesis)}</span>${status}</header>` +
        `<div class="wall-field" role="img" aria-label="Attempt ${esc(String(a.cycle))}: ${a.day_count} daily marks">${cells}</div>` +
        `</section>`
      );
    })
    .join("");

  return `<div class="wall">${legend}<div class="wall-attempts">${rows}</div></div>`;
}
