/* evidence_wall.js — #1379: the Wall (the all-attempts field of daily fingerprints).

   Renders /api/wall into the archive readout: every experiment cycle as a row of
   daily marks. Each mark is the CANONICAL server-rendered SVG (lambdas/web/fingerprint.py)
   injected verbatim — no client-side mark maths, no new dependency. The living attempt
   glows where it earned it; sealed attempts show honest low-data marks, so a reader can
   literally watch one attempt die and the next begin. Trusted first-party SVG payload. */

import { esc, empty } from "/assets/js/evidence_shared.js";

export function renderWall(data) {
  const wall = data && data.wall;
  const attempts = (wall && wall.attempts) || [];
  if (!attempts.length) return empty("No attempts on the wall yet — the field fills in as the days accrue.");

  const legend =
    `<p class="wall-legend">Every day is a mark — a pure function of that day's real numbers, drawn in code. ` +
    `The <strong>ember glow is earned</strong>; a faint, dashed mark is a low- or no-data day (honest, never faked). ` +
    `<a href="/method/fingerprint/">How the mapping works &rarr;</a></p>`;

  const rows = attempts
    .map((a) => {
      const cells = (a.days || [])
        .map(
          (d) =>
            `<span class="wall-cell${d.warming_up ? " is-warming" : ""}" ` +
            `title="${esc(d.date)} · day ${d.day_number}${d.warming_up ? " · warming up" : ""}">${d.svg}</span>`,
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
