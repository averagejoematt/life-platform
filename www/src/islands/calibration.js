// The Coaching Room's calibration island (CR1, built dark — src/lib/room.js; loaded only by src/room/calibration.astro).
// Progressive enhancement: the build drew the chart at desktop width; on a phone the island redraws it with the
// container's width as the viewBox, so the SVG text keeps its size (the 11 px floor, #1210), then mounts the
// inspector. It also selects the verify command on focus and copies it on request. Nothing is computed: the dots
// and their labels come from the same pure function the build used, over the data the build embedded.
import { calibrationChart } from "../lib/calibration.js";
import { mountAll } from "./inspect.js";

function draw() {
  document.querySelectorAll("[data-cal-chart]").forEach((holder) => {
    let coaches;
    try {
      coaches = JSON.parse(holder.dataset.payload || "[]");
    } catch {
      return;
    }
    const mobile = window.innerWidth < 640;
    const width = Math.max(280, Math.round(holder.clientWidth || (mobile ? 350 : 600)));
    holder.innerHTML = calibrationChart(coaches, { mobile, width, aria: holder.dataset.aria || "" });
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

document.querySelectorAll("[data-verify]").forEach((box) => {
  const input = box.querySelector("input");
  const btn = box.querySelector("button");
  if (!input || !btn) return;
  input.addEventListener("focus", () => input.select());
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    input.select();
    try {
      await navigator.clipboard.writeText(input.value);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Selected — copy it";
    }
  });
});
