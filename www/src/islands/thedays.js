// The Days' island (2026-11-27, proposal): the figure was drawn at build time for a desktop column. On load and on
// resize it is redrawn at the container's own width (labels keep their pixel size on a phone, #1210), and then:
//   pointer / touch   the nearest column becomes the day in the readout; vertical scrolling is never captured
//   keyboard          ← → step a day · Home/End jump · the figure is one tab stop
//   lenses            a set of days stays ink, the rest go under paper; the sentence counts what is held
//   range + pager     the newest 8 or 4 weeks, and earlier/later through the record a week at a time. On a phone the
//                     full figure OPENS on four weeks: 82 selectable columns in 350 px are 4 px each
//   "Play the days"   the cursor walks the shown days, oldest to newest; any touch stops it
// Nothing is computed here but which column is nearest: every figure and sentence was written by lib/thedays.js.
import { dayInWords } from "../lib/format.js";
import { cursorMarkup, readout, readoutLine, theDays, veilMarkup, STAVES_FULL, STAVES_START, STAVES_WEEK } from "../lib/thedays.js";

function mount(root) {
  if (!root || root.dataset.mounted) return;
  const holder = root.querySelector("[data-thedays-chart]");
  const out = root.querySelector("[data-thedays-readout]");
  const count = root.querySelector("[data-thedays-count]");
  const pager = root.querySelector("[data-thedays-pager]");
  const p = JSON.parse(root.dataset.payload || "null");
  if (!holder || !p) return;
  const variant = root.dataset.variant || "full";
  const staves = variant === "start" ? STAVES_START : variant === "week" ? STAVES_WEEK : STAVES_FULL;
  const mark = (root.dataset.mark || "").split(",").filter(Boolean).map(Number);
  const N = p.days.length;
  const phone = () => window.innerWidth < 640;
  // the full figure opens on four weeks on a phone; everywhere else on the whole record
  const state = { last: variant === "full" && phone() && N > 28 ? 28 : null, end: N - 1, lens: null, cursor: null, geom: null, timer: null };
  root.querySelectorAll("[data-needs-js]").forEach((el) => (el.hidden = false));
  const pressRange = () => root.querySelectorAll("[data-range]").forEach((o) => o.setAttribute("aria-pressed", String((o.dataset.range === "all" ? null : Number(o.dataset.range)) === state.last)));
  pressRange();

  const lensOf = () => (p.lenses || []).find((l) => l.id === state.lens) || null;
  const paintCursor = () => {
    const g = holder.querySelector("[data-cursor]");
    if (g && state.geom) g.innerHTML = cursorMarkup(p, state.geom, state.cursor - state.geom.lo);
    if (out) out.innerHTML = variant === "start" ? readoutLine(p, state.cursor) : readout(p, state.cursor);
  };
  const paintVeil = () => {
    const g = holder.querySelector("[data-veil]");
    const lens = lensOf();
    if (g) g.innerHTML = lens && lens.idx ? veilMarkup(state.geom, lens.idx) : "";
    if (count) {
      count.textContent = lens && lens.text ? lens.text : "";
      if (lens && lens.text && lens.href) {
        const a = document.createElement("a");
        a.href = lens.href;
        a.textContent = lens.hrefWords || "More →";
        count.append(" ", a);
      }
      count.hidden = !(lens && lens.text);
    }
  };
  const paintPager = () => {
    if (!pager || !state.geom) return;
    pager.hidden = state.last == null;
    const lo = state.geom.lo;
    const hi = lo + state.geom.n - 1;
    const span = pager.querySelector("[data-thedays-span]");
    if (span) span.textContent = `${dayInWords(p.days[lo].d, { short: true })} – ${dayInWords(p.days[hi].d, { short: true })}`;
    pager.querySelector('[data-page="-1"]').disabled = lo <= 0;
    pager.querySelector('[data-page="1"]').disabled = hi >= N - 1;
  };
  let lastW = 0;
  const draw = (force) => {
    const w = Math.round(holder.clientWidth || 0);
    if (!w || (w === lastW && !force)) return;
    lastW = w;
    const windowed = state.last != null;
    const r = theDays(p, { staves, from: root.dataset.from || null, to: windowed ? p.days[state.end].d : root.dataset.to || null, last: state.last, width: Math.max(280, w), mobile: phone(), aria: root.dataset.aria || "", cursor: state.cursor, mark });
    holder.innerHTML = r.svg;
    state.geom = r.geom;
    if (!state.geom) return;
    const hi = state.geom.lo + state.geom.n - 1;
    state.cursor = state.cursor == null ? hi : Math.max(state.geom.lo, Math.min(hi, state.cursor));
    const svg = holder.querySelector("svg");
    svg.setAttribute("tabindex", "0");
    svg.style.touchAction = "pan-y";
    paintVeil();
    paintCursor();
    paintPager();
  };

  const stop = () => {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
    const b = root.querySelector("[data-thedays-play]");
    if (b) b.removeAttribute("data-playing");
  };
  const at = (clientX) => {
    const svg = holder.querySelector("svg");
    if (!svg || !state.geom) return;
    const r = svg.getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * state.geom.W;
    const i = Math.round((x - state.geom.padL) / (state.geom.cw || 1));
    state.cursor = state.geom.lo + Math.max(0, Math.min(state.geom.n - 1, i));
    paintCursor();
  };
  // A mouse resting on the figure must not stop the play: a browser fires pointermove when the layout under a still
  // pointer changes. Only a pointer that has really travelled takes the cursor.
  let rest = null;
  holder.addEventListener("pointermove", (e) => {
    if (!(e.pointerType === "mouse" || e.buttons || e.pressure > 0)) return;
    if (state.timer) {
      if (!rest) rest = [e.clientX, e.clientY];
      if (Math.abs(e.clientX - rest[0]) + Math.abs(e.clientY - rest[1]) < 6) return;
    }
    rest = null;
    stop();
    at(e.clientX);
  });
  holder.addEventListener("pointerdown", (e) => (stop(), at(e.clientX)));
  holder.addEventListener("keydown", (e) => {
    if (!state.geom) return;
    const hi = state.geom.lo + state.geom.n - 1;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (step) state.cursor = Math.max(state.geom.lo, Math.min(hi, state.cursor + step));
    else if (e.key === "Home") state.cursor = state.geom.lo;
    else if (e.key === "End") state.cursor = hi;
    else return;
    e.preventDefault();
    stop();
    paintCursor();
  });

  root.querySelectorAll("[data-lens]").forEach((b) =>
    b.addEventListener("click", () => {
      state.lens = b.dataset.lens === "all" ? null : b.dataset.lens;
      root.querySelectorAll("[data-lens]").forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
      paintVeil();
    }),
  );
  root.querySelectorAll("[data-range]").forEach((b) =>
    b.addEventListener("click", () => {
      state.last = b.dataset.range === "all" ? null : Number(b.dataset.range);
      state.end = N - 1;
      pressRange();
      stop();
      draw(true);
    }),
  );
  root.querySelectorAll("[data-page]").forEach((b) =>
    b.addEventListener("click", () => {
      if (state.last == null) return;
      state.end = Math.max(state.last - 1, Math.min(N - 1, state.end + Number(b.dataset.page) * 7));
      state.cursor = Math.min(state.cursor ?? state.end, state.end);
      stop();
      draw(true);
    }),
  );
  const play = root.querySelector("[data-thedays-play]");
  if (play)
    play.addEventListener("click", () => {
      if (state.timer) return stop();
      if (!state.geom) return;
      const hi = state.geom.lo + state.geom.n - 1;
      state.cursor = state.geom.lo;
      paintCursor();
      rest = null;
      play.setAttribute("data-playing", "");
      // about nine seconds for whatever is shown; the reader stops it with any touch
      state.timer = setInterval(() => {
        if (state.cursor >= hi) return stop();
        state.cursor += 1;
        paintCursor();
      }, Math.max(60, Math.round(9000 / Math.max(1, state.geom.n))));
    });

  let t;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => draw(false), 150);
  });
  draw(true);
  root.dataset.mounted = "true";
}

document.querySelectorAll("[data-thedays]").forEach(mount);
