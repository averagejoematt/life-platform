// The Journey island (#5579): frame · range · show over the build-time instrument. It redraws with
// the same pure module the build used and mounts the inspector on every redraw. Every figure it
// draws was published by the platform (journey.json); the controls only change what is drawn.
import { heartChart, journeyCaption, journeyChart } from "../lib/journey.js";
import { mountAll } from "./inspect.js";

export function mount(root = document.querySelector("[data-journey]")) {
  if (!root) return;
  const data = JSON.parse(root.dataset.payload || "{}");
  const chart = root.querySelector("[data-journey-chart]");
  const caption = root.querySelector("[data-journey-caption]");
  const state = { frame: "distance", range: null, show: { mean: true, projection: true, rungs: true, chapters: false, events: true } };
  const mobile = () => window.innerWidth < 640;
  const draw = () => {
    // the viewBox follows the container on a phone, so text keeps its pixel size (#1210)
    const width = mobile() ? Math.max(280, Math.round(chart.clientWidth || 350)) : undefined;
    const o = { ...data, ...state, mobile: mobile(), width, aria: root.dataset.aria || "" };
    chart.innerHTML = journeyChart(o);
    if (caption) caption.textContent = journeyCaption(o);
    mountAll(root);
  };
  root.querySelectorAll("[data-frame]").forEach((b) =>
    b.addEventListener("click", () => {
      state.frame = b.dataset.frame;
      root.querySelectorAll("[data-frame]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw();
    }),
  );
  root.querySelectorAll("[data-range]").forEach((b) =>
    b.addEventListener("click", () => {
      state.range = b.dataset.range === "all" ? null : Number(b.dataset.range);
      root.querySelectorAll("[data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw();
    }),
  );
  root.querySelectorAll("[data-show]").forEach((b) =>
    b.addEventListener("click", () => {
      state.show[b.dataset.show] = !state.show[b.dataset.show];
      b.setAttribute("aria-pressed", String(state.show[b.dataset.show]));
      draw();
    }),
  );
  let timer;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(draw, 150);
  });
  root.querySelectorAll("[data-needs-js]").forEach((el) => el.removeAttribute("hidden"));
  root.dataset.mounted = "true";
  draw();
  return { state, draw };
}

/** The heart charts beside the weight (#5583): redrawn at the container's own width so every label keeps its size (#1210). */
export function mountHearts(doc = document) {
  const figs = [...doc.querySelectorAll("[data-heart]")];
  if (!figs.length) return;
  const draw = () => {
    for (const fig of figs) {
      const holder = fig.querySelector("[data-heart-chart]");
      if (!holder) continue;
      const data = JSON.parse(fig.dataset.payload || "{}");
      const mobile = window.innerWidth < 640;
      const width = Math.max(260, Math.round(holder.clientWidth || 500));
      holder.innerHTML = heartChart({ ...data, mobile, width });
      mountAll(fig);
    }
  };
  let timer;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(draw, 150);
  });
  draw();
}

mount();
mountHearts();
