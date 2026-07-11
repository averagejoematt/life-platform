/*
  evidence_datafigure.js — "the data figure": the faceless body silhouette whose girth is
  a direct function of the real weight number (start -> current -> goal), plus its scrub/
  play wiring. Used by the Physical, Results and Character-sheet renderers. Split out of
  evidence.js (#581) — no behavior change.
*/
import { icon } from "/assets/js/icons.js";
import { fmt, fig, sec, note } from "/assets/js/evidence_shared.js";

export const DF_CX = 150, DF_CROTCH = 372, DF_FOOT = 606;

export const DF_NECK = [[100, 16, 9], [135, 54, 14], [188, 47, 30], [250, 35, 64], [306, 52, 42], [350, 42, 26]];

export const DF_LEG_OUT = [[470, 32, 12], [582, 23, 8]], DF_LEG_IN = [[582, 9, 5], [470, 15, 6]];

export const DF_FOOT_OUT = [27, 8], DF_FOOT_IN = [11, 0];

export const dfHalf = (lm, g) => lm[1] + lm[2] * g;

export function dfSmooth(pts) {
  if (pts.length < 3) return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

export function dfBody(g) {
  const right = [[DF_CX + dfHalf(DF_NECK[0], g), DF_NECK[0][0]]];
  for (const lm of DF_NECK) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  for (const lm of DF_LEG_OUT) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  right.push([DF_CX + DF_FOOT_OUT[0] + DF_FOOT_OUT[1] * g, DF_FOOT]);
  right.push([DF_CX + DF_FOOT_IN[0] + DF_FOOT_IN[1] * g, DF_FOOT]);
  for (const lm of DF_LEG_IN) right.push([DF_CX + dfHalf(lm, g), lm[0]]);
  right.push([DF_CX, DF_CROTCH]);
  const left = right.slice(0, -1).reverse().map(([x, y]) => [2 * DF_CX - x, y]);
  return dfSmooth(right.concat(left)) + " Z";
}

export function dataFigure(j) {
  // #948: null-handle the pre-start contract explicitly — Number(null) is 0 (finite),
  // which would draw a "0 lb" figure while /api/journey suppresses the weight.
  if (j.start_weight_lbs == null || j.goal_weight_lbs == null || j.current_weight_lbs == null) return "";
  const start = Number(j.start_weight_lbs), goal = Number(j.goal_weight_lbs), now = Number(j.current_weight_lbs);
  if (!isFinite(start) || !isFinite(goal) || !isFinite(now) || start === goal) return "";
  const lost = Number(j.lost_lbs);
  const moved = isFinite(lost) ? (lost > 0.05 ? `down ${fmt(Math.abs(lost))} lb` : (lost < -0.05 ? `up ${fmt(Math.abs(lost))} lb` : "even")) : "";
  const ms = [[start, "start"], [now, "now"], [Math.round((start + goal) / 2), ""], [goal, "goal"]]
    .filter(([w], i, a) => a.findIndex(([x]) => Math.round(x) === Math.round(w)) === i);
  return `<section class="rd-sec df-sec" data-df data-start="${start}" data-goal="${goal}" data-now="${now}">
    <h2 class="rd-h">The figure, drawn from the numbers</h2>
    <div class="df-stage">
      <svg class="df-svg" viewBox="0 0 300 620" role="img" aria-label="A stylised body silhouette that slims as the weight number falls from ${Math.round(start)} toward ${Math.round(goal)} lb">
        <circle class="df-fig" data-df-head cx="150" cy="64" r="32"></circle>
        <path class="df-fig" data-df-body d=""></path>
      </svg>
    </div>
    <div class="df-readout">
      <div class="df-weight"><span data-df-w class="num">${Math.round(now)}</span><small>lb</small></div>
      <div class="df-togoal"><span class="label">to goal</span><span data-df-tg class="num">—</span></div>
    </div>
    <input class="df-scrub" data-df-scrub type="range" min="0" max="1" step="0.001" value="0" aria-label="Scrub the figure between start and goal weight">
    <div class="df-axis"><span class="label">${Math.round(start)} start</span><span class="label">${Math.round(goal)} goal</span></div>
    <div class="df-buttons">${ms.map(([w, lbl]) => `<button class="df-btn" data-df-to="${w}">${lbl ? lbl + " · " : ""}${Math.round(w)}</button>`).join("")}<button class="df-btn df-play" data-df-play>${icon("play")} morph</button></div>
    <p class="rd-why df-note"><strong>A representative figure, not a photo.</strong> The silhouette's girth is a direct function of the real measured weight — heaviest at ${Math.round(start)}, leanest at ${Math.round(goal)} — with no face, no identity, and nothing generated or guessed. It moves only when the actual number moves${moved && moved !== "even" ? ` (currently ${moved} from the start)` : ""}.</p>
  </section>`;
}

// P0.2 — silhouette scrubber wiring, reusable. `onWeight(w)` fires on every render so a
// caller can link another element (the physical page passes the trend-chart marker).
export function wireDataFigure(onWeight) {
  const stage = document.querySelector("[data-df]");
  if (!stage) return;
  const START = parseFloat(stage.dataset.start), GOAL = parseFloat(stage.dataset.goal), NOW = parseFloat(stage.dataset.now);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const bodyEl = stage.querySelector("[data-df-body]"), headEl = stage.querySelector("[data-df-head]");
  const wEl = stage.querySelector("[data-df-w]"), tgEl = stage.querySelector("[data-df-tg]"), scrub = stage.querySelector("[data-df-scrub]");
  const heaviness = (w) => Math.max(0, Math.min(1, (w - GOAL) / (START - GOAL)));
  function render(w) {
    const g = heaviness(w);
    bodyEl.setAttribute("d", dfBody(g));
    headEl.setAttribute("r", (29 + 6 * g).toFixed(1));
    wEl.textContent = Math.round(w);
    const toGo = Math.max(0, w - GOAL);
    tgEl.textContent = toGo <= 0 ? "reached" : "-" + Math.round(toGo) + " lb";
    scrub.value = (1 - g).toFixed(3);
    if (onWeight) try { onWeight(w); } catch (e) { /* link is decorative — never break the scrub */ }
  }
  scrub.addEventListener("input", () => render(START + (GOAL - START) * parseFloat(scrub.value)));
  let raf = null;
  function animateTo(target) {
    cancelAnimationFrame(raf);
    const from = START + (GOAL - START) * parseFloat(scrub.value);
    if (reduce) { render(target); return; }
    const t0 = performance.now(), dur = 900;
    (function step(t) {
      const k = Math.min(1, (t - t0) / dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      render(from + (target - from) * e);
      if (k < 1) raf = requestAnimationFrame(step);
    })(t0);
  }
  stage.querySelectorAll("[data-df-to]").forEach((b) => b.addEventListener("click", () => animateTo(parseFloat(b.dataset.to))));
  const playBtn = stage.querySelector("[data-df-play]");
  if (reduce) { playBtn.remove(); } else {
    let playing = false, ploop = null;
    playBtn.addEventListener("click", (e) => {
      playing = !playing; e.target.innerHTML = playing ? `${icon("pause")} pause` : `${icon("play")} morph`;
      if (playing) {
        let dir = -1, w = START; cancelAnimationFrame(raf);
        (function loop() { w += dir * 1.4; if (w <= GOAL) { w = GOAL; dir = 1; } if (w >= START) { w = START; dir = -1; } render(w); if (playing) ploop = requestAnimationFrame(loop); })();
      } else { cancelAnimationFrame(ploop); }
    });
  }
  render(NOW);   // open on the honest current state
  return render; // uplevel P4 — lets the chart's hover cross-highlight drive the figure
}

// P0.2 — move the trend-chart's horizontal scrub marker to weight `w` (lockstep with the
// silhouette). Below the chart's data floor (toward goal) → pin to the axis bottom + flag.
export function moveTrendMarker(w) {
  const fig = document.querySelector(".wt-chart");
  if (!fig) return;
  const m = fig.querySelector("[data-wt-marker]");
  if (!m) return;
  const min = parseFloat(fig.dataset.wtMin), max = parseFloat(fig.dataset.wtMax), H = parseFloat(fig.dataset.wtH), P = parseFloat(fig.dataset.wtP);
  if (![min, max, H, P].every(Number.isFinite) || max === min) return;
  const below = w < min;
  const y = below ? (H - P) : (P + (1 - (w - min) / (max - min)) * (H - 2 * P));
  m.setAttribute("y1", y.toFixed(1)); m.setAttribute("y2", y.toFixed(1));
  m.style.opacity = "1";
  m.classList.toggle("wt-marker-below", below);
}

/* ── App shell: tabs + sidebar + center ───────────────────────────────────── */
