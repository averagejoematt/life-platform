// The inspect island — every chart answers (#5578, historical capability A01). Progressive
// enhancement over any <svg data-points>: a pointer, a tap or the arrow keys pick the nearest
// reading on the x-axis and a tooltip reads its prewritten label (the date in words, the value,
// the unit). Nothing is computed here: the points and their labels were written by the build
// (lib/chart.js) or by the island that redrew the chart; this module only reads them back.
//
// Behaviour (the approved Journey prototype, 2026-11-02):
//   pointer   nearest point on x; focus ring + tooltip above it; leaving the chart hides them
//   touch     a tap shows the reading and vertical scrolling is never captured (touch-action: pan-y)
//   keyboard  the svg is tabindex=0 · ← → step readings · Home/End jump · Escape hides
//   a11y      the tooltip is a polite live region; the svg keeps its role=img + aria-label
//   motion    nothing animates; prefers-reduced-motion needs no special case
const TAP_MS = 2600;

function pointsOf(svg) {
  try {
    const pts = JSON.parse(svg.dataset.points || "[]");
    return Array.isArray(pts) ? pts.filter((p) => p && Number.isFinite(p.x) && Number.isFinite(p.y)) : [];
  } catch {
    return [];
  }
}

function viewBoxOf(svg) {
  const vb = (svg.getAttribute("viewBox") || "0 0 1000 220").split(/\s+/).map(Number);
  return { w: vb[2] || 1000, h: vb[3] || 220 };
}

/** Mount the inspector on one svg. Idempotent: a redraw replaces the svg, so mount again. */
export function mountInspect(svg) {
  if (!svg || svg.dataset.inspect === "mounted") return null;
  const pts = pointsOf(svg);
  if (!pts.length) {
    svg.dataset.inspect = "empty";
    return null;
  }
  const figure = svg.parentElement;
  if (!figure) return null;
  if (getComputedStyle(figure).position === "static") figure.style.position = "relative";
  figure.querySelectorAll(":scope > .tip").forEach((t) => t.remove());
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "status");
  tip.setAttribute("aria-live", "polite");
  tip.hidden = true;
  figure.appendChild(tip);

  const ns = "http://www.w3.org/2000/svg";
  const ring = document.createElementNS(ns, "circle");
  ring.setAttribute("class", "focus");
  ring.setAttribute("r", "5.5");
  ring.style.display = "none";
  svg.appendChild(ring);

  if (!svg.hasAttribute("tabindex")) svg.setAttribute("tabindex", "0");
  svg.style.touchAction = "pan-y";
  const { w: vbW, h: vbH } = viewBoxOf(svg);
  let idx = pts.length - 1;
  let hideTimer = null;

  const show = (i, sticky = false) => {
    idx = Math.max(0, Math.min(pts.length - 1, i));
    const p = pts[idx];
    ring.setAttribute("cx", p.x);
    ring.setAttribute("cy", p.y);
    ring.style.display = "";
    const r = svg.getBoundingClientRect();
    const sx = r.width / vbW;
    const sy = r.height / vbH;
    const fw = figure.clientWidth || r.width;
    const left = Math.max(110, Math.min(fw - 110, (r.left - figure.getBoundingClientRect().left) + p.x * sx));
    tip.textContent = p.label || `${p.date || ""} ${p.v ?? ""}`;
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(40, (r.top - figure.getBoundingClientRect().top) + p.y * sy)}px`;
    tip.hidden = false;
    clearTimeout(hideTimer);
    if (sticky) hideTimer = setTimeout(hide, TAP_MS);
  };
  const hide = () => {
    tip.hidden = true;
    ring.style.display = "none";
  };
  const nearest = (clientX) => {
    const r = svg.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * vbW;
    let best = 0;
    let bd = Infinity;
    pts.forEach((p, i) => {
      const d = Math.abs(p.x - px);
      if (d < bd) {
        bd = d;
        best = i;
      }
    });
    return best;
  };

  svg.addEventListener("pointermove", (e) => {
    if (e.pointerType === "touch") return;
    show(nearest(e.clientX));
  });
  svg.addEventListener("pointerdown", (e) => show(nearest(e.clientX), e.pointerType === "touch"));
  svg.addEventListener("pointerleave", (e) => {
    if (e.pointerType !== "touch") hide();
  });
  svg.addEventListener("keydown", (e) => {
    const k = e.key;
    if (k === "ArrowLeft") show(idx - 1);
    else if (k === "ArrowRight") show(idx + 1);
    else if (k === "Home") show(0);
    else if (k === "End") show(pts.length - 1);
    else if (k === "Escape") hide();
    else return;
    e.preventDefault();
  });
  svg.addEventListener("focus", () => show(idx));
  svg.addEventListener("blur", hide);
  svg.dataset.inspect = "mounted";
  return { show, hide };
}

/** Mount on every chart under root (the page by default). Safe to call after a redraw. */
export function mountAll(root = document) {
  root.querySelectorAll("svg[data-points]").forEach((svg) => mountInspect(svg));
}

mountAll();
