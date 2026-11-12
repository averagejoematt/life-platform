// The Laboratory's island (L1, built dark — src/lib/lab.js; loaded by src/lab/lab-test.astro and src/lab/lab-findings.astro). Progressive
// enhancement: the build drew each chart at desktop width; the island redraws it with the container's own width as
// the viewBox, so SVG text keeps its size on a phone (the 11 px floor, #1210), then mounts the inspector (pointer,
// touch, keyboard). Nothing is computed: the readings and their labels come from the same pure functions the build
// used, over the data the build embedded.
import { intervalFigure, stabilityFigure, windowChart } from "../lib/laboratory.js";
import { mountAll } from "./inspect.js";

function parse(el) {
  try {
    return JSON.parse(el.dataset.payload || "null");
  } catch {
    return null;
  }
}

function draw() {
  const mobile = window.innerWidth < 640;
  document.querySelectorAll("[data-lab-chart]").forEach((holder) => {
    const opts = parse(holder);
    if (!opts) return;
    const width = Math.max(280, Math.round(holder.clientWidth || (mobile ? 350 : 1000)));
    holder.innerHTML = windowChart({ ...opts, aria: holder.dataset.aria || opts.aria || "" }, { mobile, width });
  });
  document.querySelectorAll("[data-lab-interval]").forEach((holder) => {
    const t = parse(holder);
    if (!t) return;
    const width = Math.max(280, Math.round(holder.clientWidth || 600));
    const svg = intervalFigure(t, { width });
    if (svg) holder.innerHTML = svg;
  });
  // findings over time: each small multiple at its own column's width (a phone column is ~350 px, a desktop one ~330)
  document.querySelectorAll("[data-lab-multiple]").forEach((holder) => {
    const p = parse(holder);
    if (!p) return;
    const width = Math.max(240, Math.round(holder.clientWidth || 340));
    const svg = stabilityFigure(p, { width });
    if (svg) holder.innerHTML = svg;
  });
  mountAll();
}

let last = window.innerWidth;
draw();
window.addEventListener("resize", () => {
  if (Math.abs(window.innerWidth - last) < 40) return;
  last = window.innerWidth;
  draw();
});
