// The Line's island (2026-11-14): the figure was drawn at build time for a desktop column; on load and on resize it is
// redrawn at the container's own width so its labels keep their pixel size on a phone (#1210), then the inspector is
// mounted (a pointer, a tap or the arrow keys read a morning). Every figure it draws was published by the platform.
import { theLine } from "../lib/theline.js";
import { mountAll } from "./inspect.js";

export function mount(root = document.querySelector("[data-theline]")) {
  if (!root) return;
  const holder = root.querySelector("[data-theline-chart]");
  const data = JSON.parse(root.dataset.payload || "{}");
  let lastW = 0;
  const draw = () => {
    const w = Math.round(holder.clientWidth || 0);
    if (!w || w === lastW) return;
    lastW = w;
    const mobile = window.innerWidth < 640;
    holder.innerHTML = theLine({ ...data, aria: root.dataset.aria || "", mobile, width: Math.max(280, w), height: mobile ? 280 : Math.round(Math.min(420, Math.max(320, w * 0.32))) });
    mountAll(root);
  };
  let timer;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(draw, 150);
  });
  draw();
  root.dataset.mounted = "true";
}

mount();
