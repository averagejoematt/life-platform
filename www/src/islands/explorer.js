// The explorer island: progressive enhancement over the build-time chart on a metric page.
// Range, 7-day mean, a second series to compare and a lag of −2…+2 days. It draws with the
// same chart module the build used and READS every statistic from the platform's pairs file
// (owner requirement A): no correlation, p-value or verdict is computed in the browser.
import { lastDays, presentCount, svgChart } from "../lib/chart.js";
import { dayInWords, num } from "../lib/format.js";
import { findPair, pairSentence, strengthInWords } from "../lib/pairs.js";
import { mountAll } from "./inspect.js";

const COBALT = "#1B3FD6";
const OCHRE = "#B97A12";

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

function shiftDays(days, lag) {
  // b on day d+lag is paired with a on day d: show b moved back by `lag` so the paired days align.
  if (!lag) return days;
  const byDate = new Map(days.map((d) => [d.date, d]));
  return days.map((d) => {
    const dt = new Date(`${d.date}T00:00:00Z`);
    dt.setUTCDate(dt.getUTCDate() + lag);
    const src = byDate.get(dt.toISOString().slice(0, 10));
    return src ? { ...src, date: d.date } : { date: d.date, value: null, present: false, gap: false };
  });
}

export function mount(root = document.querySelector("[data-explorer]")) {
  if (!root) return;
  const base = root.dataset.base || "/";
  const metric = root.dataset.metric;
  const decimals = Number(root.dataset.decimals || 1);
  const labels = JSON.parse(root.dataset.labels || "{}");
  const chartA = root.querySelector("[data-chart-a]");
  const chartB = root.querySelector("[data-chart-b]");
  const stats = root.querySelector("[data-pair-stats]");
  const caption = root.querySelector("[data-caption]");
  const compare = root.querySelector("[data-compare]");
  const state = { range: null, smooth: false, lag: 0, b: "", series: {}, pairs: null };
  const mobile = () => window.innerWidth < 640;
  const labelDay = (iso) => dayInWords(iso, { short: true }) || "";

  const seriesFor = async (id) => {
    if (!state.series[id]) state.series[id] = await getJSON(`${base}data/series/${id}.json`);
    return state.series[id];
  };

  async function draw() {
    const a = await seriesFor(metric);
    const days = lastDays(a.days, state.range);
    const width = mobile() ? Math.max(280, Math.round(chartA.clientWidth || 350)) : undefined;
    chartA.innerHTML = svgChart({
      series: [{ days, color: COBALT, name: labels[metric] || metric }],
      mobile: mobile(),
      width,
      smooth: state.smooth,
      markers: a.markers || [],
      labelDay,
      unit: a.unit || root.dataset.unit || "",
      decimals,
      aria: `${labels[metric] || metric}, ${presentCount(days)} readings over ${days.length} days`,
    });
    mountAll(root);
    if (caption) {
      const n = presentCount(days);
      caption.textContent = `${n} of ${days.length} days with a reading${state.smooth ? " · 7-day mean, readings as dots" : ""}${
        a.markers && a.markers.length ? " · the dashed ochre rule is the baseline change" : ""
      }`;
    }
    if (!state.b) {
      chartB.innerHTML = "";
      chartB.hidden = true;
      if (stats) stats.textContent = "Choose a second measure to see what the platform found when it paired them.";
      return;
    }
    const b = await seriesFor(state.b);
    const bDays = shiftDays(lastDays(b.days, state.range), state.lag);
    chartB.hidden = false;
    chartB.innerHTML = svgChart({
      series: [{ days: bDays, color: OCHRE, name: labels[state.b] || state.b }],
      mobile: mobile(),
      width,
      smooth: state.smooth,
      height: 160,
      labelDay,
      unit: b.unit || "",
      decimals,
      aria: `${labels[state.b] || state.b}, aligned ${state.lag ? `${state.lag > 0 ? "+" : ""}${state.lag} days` : "the same day"}`,
    });
    mountAll(root);
    if (!state.pairs) state.pairs = await getJSON(`${base}data/pairs.json`);
    const row = findPair(state.pairs, metric, state.b, state.lag);
    if (stats) {
      stats.textContent = row
        ? `${pairSentence(row, labels)} Read as ${strengthInWords(row.r)}; the platform computed these numbers, this page only shows them.`
        : "The platform has not tested this pairing at this lag; nothing is computed here in its place.";
    }
  }

  root.querySelectorAll("[data-range]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.range = btn.dataset.range === "all" ? null : Number(btn.dataset.range);
      root.querySelectorAll("[data-range]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      draw();
    }),
  );
  root.querySelectorAll("[data-smooth]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.smooth = btn.dataset.smooth === "mean";
      root.querySelectorAll("[data-smooth]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      draw();
    }),
  );
  root.querySelectorAll("[data-lag]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.lag = Number(btn.dataset.lag);
      root.querySelectorAll("[data-lag]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      draw();
    }),
  );
  if (compare) {
    compare.addEventListener("change", () => {
      state.b = compare.value;
      root.querySelector("[data-compare-controls]")?.toggleAttribute("hidden", !state.b);
      draw();
    });
  }
  let t;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(draw, 150);
  });
  root.dataset.mounted = "true";
  root.querySelectorAll("[data-needs-js]").forEach((el) => el.removeAttribute("hidden"));
  draw().catch((e) => {
    if (stats) stats.textContent = "The series could not be loaded just now; the chart above is the build's.";
    console.error(e);
  });
  return { state, draw, num };
}

mount();
