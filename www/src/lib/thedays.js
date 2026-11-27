// The Days (2026-11-27, proposal — not merged): every day of the experiment as one column, under The Line, on
// The Line's own time axis. Where The Line shows the one thing that is measured every morning, the staves under it
// show what the same days held: what was lifted and walked, the night, the morning, the food, the coaches' calls that
// settled, the chapter that covers the day — and three staves left empty on purpose (Mind, Connection, Purpose).
//
// Why staves and not a heat map: each row keeps its own unit and its own zero, drawn by POSITION, so nothing here says
// "more is better" with a colour. Ink is a recorded value. A hollow mark is a day the record says it does not know
// (a missing morning, a night not recorded, food still being logged). A blank is a measured nothing (no session
// logged). Cobalt and vermillion keep the meanings tokens.css gives them (confirmed, refuted) and are used for nothing
// else. Ochre is the compared series (the second lift) and the device-change rule, as on the Journey.
//
// Pure, like theline.js: the build draws it once, the island (islands/thedays.js) redraws it at the container's own
// width and moves the cursor. Every number it draws is one the Day pages already publish; nothing is smoothed,
// scored or inferred. The lenses only COUNT days the reader can see.
import { esc } from "./chart.js";
import { dayInWords, num } from "./format.js";
import { theLineParts } from "./theline.js";

const INK = "#121212";
const MUTED = "#5C5C58";
const GREY = "#8A8A85";
const RULE = "#C9C9C3";
const RULE2 = "#E3E3DD";
const HOLLOW = "#B9B9B3";
const COBALT = "#1B3FD6";
const OCHRE = "#B97A12";
const VERM = "#D9341C";
const PAPER = "#F4F4F0";
const KG_LB = 2.20462;
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** The walker (a game layer, switched here): the day cursor drawn as a figure standing on The Line. His kit changes
 *  only at the ten-pound rungs the platform published with their crossing dates — measured weigh-ins, never a level,
 *  XP or any score (the public character scores are being recalculated; nothing here reads them). */
// OFF (owner, 2026-11-27): the five-kit drawing is a placeholder and is not released; the proper character should
// recognise approved progress across several dimensions, not only weight. The hook stays: cursorMarkup() draws whatever
// walkerInner() returns at the cursor, and walkerStage() is the one place its progress rule lives.
export const WALKER = false;

// Start is an introduction: the weight trajectory and ONE contrast (gym sessions against steps). Everything else is Data's.
export const STAVES_START = ["line", "move"];
// In Data the weight is one stave among the others (the site already draws The Line large on Start and the Journey).
export const STAVES_FULL = ["scale", "lifts", "move", "night", "heart", "food", "calls", "chapters"];
export const STAVES_WEEK = ["lifts", "move", "night", "food", "calls"];

const median = (xs) => {
  const s = xs.filter((v) => v != null).sort((a, b) => a - b);
  if (!s.length) return null;
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const weekdayOf = (iso) => new Date(`${iso}T00:00:00Z`).getUTCDay();

/** The heaviest working set of one exercise on one day, as lib/day.js reads a session (warm-ups left out). */
function topSet(workout, name) {
  const e = ((workout && workout.exercises) || []).find((x) => x.name === name);
  if (!e) return null;
  const work = (e.sets || []).filter((s) => s.type !== "warmup" && s.weight_kg != null);
  const top = work.reduce((a, s) => (!a || s.weight_kg > a.weight_kg ? s : a), null);
  return top ? { kg: top.weight_kg, lb: Math.round(top.weight_kg * KG_LB), reps: top.reps } : null;
}

/**
 * The figure's data, assembled at build from the snapshot's Day objects (every field below is on a Day page already).
 * @param {{days:any[], weight:any[], journey:any, chapters:any[], dayHref:(id:string)=>string, unmeasured?:any[]}} o
 */
export function daysPayload(o) {
  const src = [...(o.days || [])].sort((a, b) => (a.date < b.date ? -1 : 1));
  const weightBy = new Map((o.weight || []).map((d) => [d.date, d]));
  // Food reads the public SERIES, not the Day object: the series withholds a day whose export was partial (21 November
  // 2026 held one breakfast entry and read 80 kcal), and the Day object carries no flag for it.
  const kcalBy = new Map((o.kcal || []).map((d) => [d.date, d]));
  const protBy = new Map((o.protein || []).map((d) => [d.date, d]));
  const has = (m, iso) => Boolean(m.get(iso) && m.get(iso).present && !m.get(iso).gap && m.get(iso).value != null);
  // the two barbell lifts logged on the most days — a rule, so the figure does not pick a flattering lift
  const tally = new Map();
  for (const d of src) for (const e of (d.workout && d.workout.exercises) || []) if (/\(Barbell\)/.test(e.name)) tally.set(e.name, (tally.get(e.name) || 0) + 1);
  const lifts = [...tally.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, 2).map(([name]) => name);
  const chapters = (o.chapters || []).filter((c) => c.from && c.to);
  const days = src.map((d) => {
    const r = d.readings || {};
    const w = weightBy.get(d.date);
    const f = d.food || null;
    const session = d.workout_state === "served" && d.workout;
    const settled = d.calls_settled || [];
    return {
      d: d.date,
      n: d.day_number,
      w: w && w.value != null && !w.gap ? w.value : null,
      ses: session ? 1 : 0,
      min: session ? d.workout.duration_min ?? null : null,
      vol: session ? d.workout.volume_kg ?? null : null,
      st: r.steps ?? null,
      sl: r.sleep_hours ?? null,
      rec: r.recovery_pct ?? null,
      rhr: r.rhr_bpm ?? null,
      // food: "ok" a complete logged day · "wait" not exported yet · "part" an incomplete record, never drawn as a value
      fs: has(kcalBy, d.date) ? "ok" : d.food_state === "pending" ? "wait" : f && f.calories != null ? "part" : "none",
      kcal: has(kcalBy, d.date) ? kcalBy.get(d.date).value : null,
      prot: has(protBy, d.date) ? protBy.get(d.date).value : null,
      floor: f && f.floor_g != null ? f.floor_g : null,
      lifts: lifts.map((name) => (session ? topSet(d.workout, name) : null)),
      right: settled.filter((c) => c.verdict === "confirmed").length,
      wrong: settled.filter((c) => c.verdict === "refuted").length,
      subj: settled.filter((c) => c.verdict === "confirmed" || c.verdict === "refuted").map((c) => [o.subjectOf ? o.subjectOf(c.prediction_id) : null, c.verdict === "confirmed" ? 1 : 0]),
      ch: chapters.findIndex((c) => d.date >= c.from && d.date <= c.to),
      u: o.dayHref(d.id),
    };
  });
  const journey = o.journey || {};
  const p = {
    days,
    lifts: lifts.map((name) => name.replace(/\s*\(Barbell\)/, "").toLowerCase()),
    startDate: journey.start_date || (days[0] && days[0].d) || null,
    startValue: journey.start_weight_lbs ?? null,
    rungs: (journey.rungs || []).filter((r) => r.date).map((r) => ({ lb: r.lb, date: r.date })),
    marker: (journey.markers || [])[0] || null,
    sleepTarget: (src.find((d) => d.sleep_target_h != null) || {}).sleep_target_h ?? null,
    chapters,
    ledgerHref: o.ledgerHref || null,
    baselineWords: o.baselineWords || null,
  };
  // the longest run of consecutive days with a gym session: a fact of the record, marked on the figure when it is long
  let best = null;
  let from = -1;
  days.forEach((d, i) => {
    if (d.ses && from < 0) from = i;
    if ((!d.ses || i === days.length - 1) && from >= 0) {
      const to = d.ses ? i : i - 1;
      if (!best || to - from > best.to - best.from) best = { from, to };
      from = -1;
    }
  });
  p.streak = best && best.to - best.from + 1 >= 10 ? best : null;
  // the ten days with the most steps (the Start figure marks them; the lens holds them)
  const top = days.map((d, i) => ({ i, st: d.st })).filter((x) => x.st != null).sort((a, b) => b.st - a.st).slice(0, 10);
  p.topSteps = top.length === 10 ? top.map((x) => x.i).sort((a, b) => a - b) : [];
  p.lenses = lenses(p);
  return p;
}

/** The lenses: each is a set of days and one sentence that only counts them. No lens explains anything. */
export function lenses(p) {
  const D = p.days;
  const out = [{ id: "all", label: "Every day", idx: null, text: "" }];
  const idxOf = (test) => D.map((d, i) => (test(d) ? i : -1)).filter((i) => i >= 0);
  const noSes = idxOf((d) => !d.ses);
  const withSes = idxOf((d) => d.ses);
  if (noSes.length >= 3 && withSes.length >= 3) {
    out.push({
      id: "nosession",
      label: "No gym session",
      idx: noSes,
      text: `${noSes.length} days with no gym session logged — not rest days: ${num(median(noSes.map((i) => D[i].st)), 0)} steps at the median, against ${num(median(withSes.map((i) => D[i].st)), 0)} on the ${withSes.length} days with one.`,
    });
  }
  if ((p.topSteps || []).length === 10) out.push({ id: "walks", label: "The ten highest-step days", idx: p.topSteps, text: topStepsWords(p) });
  const short = idxOf((d) => d.sl != null && d.sl < 6);
  if (short.length) {
    const recs = short.map((i) => D[i].rec).filter((v) => v != null);
    out.push({
      id: "short",
      label: "Nights under six hours",
      idx: short,
      text: `${short.length} ${short.length === 1 ? "night" : "nights"} under six hours. Recovery the same morning read ${recs.length <= 6 ? recs.map((v) => num(v, 0)).join(", ").replace(/, ([^,]*)$/, " and $1") : `${num(median(recs), 0)} at the median`}.`,
    });
  }
  const logged = idxOf((d) => d.fs === "ok" && d.prot != null && d.floor != null);
  const cleared = logged.filter((i) => D[i].prot >= D[i].floor);
  if (logged.length) {
    out.push({
      id: "floor",
      label: "Protein floor cleared",
      idx: cleared,
      text: `${cleared.length} of ${logged.length} logged days at or above the ${num(D[logged[0]].floor, 0)} g protein floor.`,
    });
  }
  const called = idxOf((d) => d.right + d.wrong > 0);
  if (called.length) {
    const R = D.reduce((a, d) => a + d.right, 0);
    const X = D.reduce((a, d) => a + d.wrong, 0);
    // what the coaches expected against what happened, by what the call was about (subjects with five calls or more)
    const by = new Map();
    D.forEach((d) => (d.subj || []).forEach(([name, ok]) => name && by.set(name, [(by.get(name) || [0, 0])[0] + ok, (by.get(name) || [0, 0])[1] + 1])));
    const subjects = [...by.entries()].filter(([, v]) => v[1] >= 5).sort((a, b) => b[1][0] / b[1][1] - a[1][0] / a[1][1] || b[1][1] - a[1][1]);
    out.push({
      id: "calls",
      label: "A coach's call settled",
      idx: called,
      // owner, 2026-11-27: a subject's count is never shown as an AI advantage — the comparison against a simple guess
      // on the same calls (p.baselineWords, the room's verified record) comes first, and the subjects are small counts
      text: `${R + X} calls settled right or wrong, on ${called.length} days: ${R} right, ${X} wrong.${p.baselineWords ? ` ${p.baselineWords}` : ""}${subjects.length > 1 ? ` By what the call was about, small counts that show no advantage on their own — ${subjects.map(([name, v]) => `${name}: ${v[0]} of ${v[1]} right`).join(" · ")}.` : ""}`,
      href: p.ledgerHref,
      hrefWords: "Each call, what was expected and what happened →",
    });
  }
  return out;
}

/** The Start figure's observation, counted from the days it marks: the ten days with the most steps. */
export function topStepsWords(p) {
  const D = p.days;
  const idx = p.topSteps || [];
  if (idx.length !== 10) return "";
  const byDay = new Map();
  idx.forEach((i) => byDay.set(weekdayOf(D[i].d), (byDay.get(weekdayOf(D[i].d)) || 0) + 1));
  const [wd, k] = [...byDay.entries()].sort((a, b) => b[1] - a[1])[0];
  const rest = idx.filter((i) => !D[i].ses).length;
  const sts = idx.map((i) => D[i].st);
  // owner, 2026-11-27: the precise terms — whole-day step counts, no gym session LOGGED, the weekday count. Never
  // "rest days", never a cause.
  const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  return `The ten highest whole-day step counts, ${num(Math.min(...sts), 0)} to ${num(Math.max(...sts), 0)}, ${rest === 10 ? "all fell on days with no gym session logged" : `fell on ${rest} days with no gym session logged and ${10 - rest} with one`}${k >= 4 ? `; ${WORDS[k]} were ${WEEKDAYS[wd]}s` : ""}.`;
}

/** The walker's kit on one date: how many published rungs had been crossed by then (1 = the sketch at the start). */
export function walkerStage(p, iso) {
  const crossed = (p.rungs || []).filter((r) => r.date <= iso);
  const last = crossed[crossed.length - 1] || null;
  return { stage: Math.min(5, crossed.length + 1), last };
}

// The walker, as drawn for the 26 November preview (the same figure, so a reader meets one character): a flat cap, and
// kit that arrives in five steps — a pencil sketch, then boots and a stick, a scarf and a stride, a pack and a
// lantern, the full kit. His body never changes. Drawn in a 68 × 116 box whose ground line is y = 126.
function walkerInner(stage) {
  const s = stage;
  const sk = s === 1;
  const coat = sk ? "none" : "#3d5a52";
  const dark = sk ? "none" : "#2a221a";
  const st = sk ? `stroke="${INK}" stroke-width="1.6" stroke-dasharray="3 3"` : "";
  const walk = s >= 3;
  const leg = sk ? INK : "#2f4640";
  let h = "";
  if (s >= 4) h += `<rect x="60" y="60" width="14" height="28" rx="6" fill="#5c4a37"/>`;
  if (s >= 2) h += `<line x1="64" y1="78" x2="${walk ? 54 : 60}" y2="129" stroke="#8a7355" stroke-width="3" stroke-linecap="round"/>`;
  h += walk
    ? `<line x1="80" y1="96" x2="69" y2="124" stroke="${leg}" stroke-width="8" stroke-linecap="round"/><line x1="88" y1="96" x2="101" y2="123" stroke="${leg}" stroke-width="8" stroke-linecap="round"/>`
    : `<line x1="80" y1="96" x2="80" y2="124" stroke="${leg}" stroke-width="${sk ? 1.6 : 8}" ${sk ? 'stroke-dasharray="3 3"' : ""} stroke-linecap="round"/><line x1="89" y1="96" x2="89" y2="124" stroke="${leg}" stroke-width="${sk ? 1.6 : 8}" ${sk ? 'stroke-dasharray="3 3"' : ""} stroke-linecap="round"/>`;
  h += walk
    ? `<ellipse cx="66" cy="127" rx="8" ry="4" fill="${dark}" ${st}/><ellipse cx="105" cy="126" rx="8" ry="4" fill="${dark}" ${st}/>`
    : `<ellipse cx="78" cy="127" rx="7" ry="4" fill="${dark}" ${st}/><ellipse cx="91" cy="127" rx="7" ry="4" fill="${dark}" ${st}/>`;
  h += `<rect x="70" y="56" width="28" height="44" rx="12" fill="${sk ? PAPER : coat}" ${st}/>`;
  if (s >= 2) h += `<line x1="78" y1="66" x2="65" y2="80" stroke="#34504a" stroke-width="7" stroke-linecap="round"/>`;
  if (s >= 3) h += `<path d="M74 57 q-12 3 -18 12" fill="none" stroke="${COBALT}" stroke-width="5" stroke-linecap="round"/><rect x="73" y="52" width="22" height="7" rx="3.5" fill="${COBALT}"/>`;
  h += `<circle cx="84" cy="42" r="12" fill="${sk ? PAPER : "#ecdcc0"}" ${sk ? st : `stroke="${INK}" stroke-width="1.2"`}/>`;
  h += `<path d="M71 39 Q73 25 87 26 Q97 27 98 36 L106 39 Q98 41 71 40 Z" fill="${sk ? PAPER : "#6b5a45"}" ${st}/>`;
  if (!sk) h += `<circle cx="90" cy="43" r="1.4" fill="#2a221a"/>`;
  if (s >= 4) h += `<line x1="90" y1="66" x2="106" y2="84" stroke="#34504a" stroke-width="7" stroke-linecap="round"/><line x1="108" y1="84" x2="108" y2="91" stroke="${MUTED}" stroke-width="1.5"/><rect x="102.5" y="91" width="11" height="14" rx="2.5" fill="#e9a81a" stroke="#6b5a45" stroke-width="1.5"/>`;
  else if (s >= 2) h += `<line x1="90" y1="66" x2="${walk ? 100 : 92}" y2="${walk ? 84 : 88}" stroke="#34504a" stroke-width="7" stroke-linecap="round"/>`;
  return h;
}

/** The walker as a standalone inline figure (the key under the chart, the readout). */
export function walkerFigure(stage, height = 40) {
  return `<svg viewBox="50 20 70 114" width="${Math.round((height * 70) / 114)}" height="${height}" aria-hidden="true">${walkerInner(stage)}</svg>`;
}

/**
 * Draw the figure.
 * @param {any} p  daysPayload()
 * @param {{width?:number, mobile?:boolean, staves?:string[], last?:number|null, from?:string|null, to?:string|null,
 *          cursor?:number|null, walker?:boolean, aria?:string}} o   `last` = show only the newest N days
 * @returns {{svg:string, geom:any}}
 */
export function theDays(p, o = {}) {
  const mobile = Boolean(o.mobile);
  const W = o.width || (mobile ? 350 : 1240);
  const staves = o.staves || STAVES_FULL;
  const fs = mobile ? 12.5 : 12;
  const all = p.days || [];
  let lo = 0;
  let hi = all.length - 1;
  if (o.from) lo = Math.max(0, all.findIndex((d) => d.d >= o.from));
  if (o.to) hi = all.reduce((a, d, i) => (d.d <= o.to ? i : a), lo);
  if (o.last && o.last < hi - lo + 1) lo = hi - o.last + 1;
  const D = all.slice(lo, hi + 1);
  const n = D.length;
  if (!n) return { svg: `<svg viewBox="0 0 ${W} 40" role="img" aria-label="${esc(o.aria || "no days")}"></svg>`, geom: null };

  const hasLine = staves.includes("line") && D.some((d) => d.w != null);
  const wantWalker = Boolean(o.walker && WALKER && hasLine);
  const WH = mobile ? 40 : 54; // the walker's height
  const LY = wantWalker ? WH - (mobile ? 30 : 36) : 0; // room above The Line for him to stand on its first reading
  const LH = hasLine ? (mobile ? 250 : Math.round(Math.min(380, Math.max(300, W * 0.28)))) : 0;
  const line = hasLine
    ? theLineParts({
        days: D.map((d) => ({ date: d.d, value: d.w, gap: false })),
        startDate: p.startDate,
        startLabelDx: wantWalker ? (mobile ? 22 : 30) : 0,
        startValue: lo === 0 ? p.startValue : null,
        rungs: p.rungs,
        // the published chapters stay numbered along The Line's foot unless the figure has its own chapters stave
        chapters: staves.includes("chapters") ? [] : (p.chapters || []).map((c) => ({ date: c.to, n: String(Number(c.n)) })),
        width: W,
        height: LH,
        mobile,
        bare: true,
        y: LY,
        shade: lo === 0,
      })
    : null;
  // a week on its own has room either side of its columns; under The Line the columns sit on The Line's own x
  const pad = line ? { l: line.pad.l, r: line.pad.r } : n <= 14 ? { l: W / n / 2 + 4, r: W / n / 2 + 4 } : { l: mobile ? 8 : 14, r: mobile ? 8 : 14 };
  const inner = W - pad.l - pad.r;
  const cw = inner / Math.max(1, n - 1);
  const X = (i) => pad.l + (n === 1 ? inner / 2 : i * cw);
  const bw = Math.max(1.6, Math.min(16, cw * 0.62));
  const f1 = (v) => Number(v).toFixed(1);

  let g = "";
  let y = LH ? LY + LH + 4 : 4; // a first stave's heading needs its ascender inside the frame
  const top0 = y;
  const text = (x, yy, s, anchor = "start", fill = MUTED, weight = 400, size = fs) =>
    `<text x="${f1(x)}" y="${f1(yy)}" text-anchor="${anchor}" font-family="IBM Plex Mono,monospace" font-size="${size}" font-weight="${weight}" fill="${fill}" stroke="${PAPER}" stroke-width="3.5" stroke-linejoin="round" paint-order="stroke">${esc(s)}</text>`;
  // a stave's head: its name on the left, its scale in words on the right (dropped on a phone when they would meet)
  let heads = "";
  const head = (name, note) => {
    heads += headMarkup(name, note);
    bands[bands.length - 1].plot = y;
    return "";
  };
  const headMarkup = (name, note) => {
    let s = `<text x="${f1(pad.l)}" y="${f1(y + 12)}" font-family="IBM Plex Mono,monospace" font-size="${fs}" letter-spacing="0.06em" fill="${INK}">${esc(name.toUpperCase())}</text>`;
    const room = W - pad.l - pad.r - name.length * fs * 0.66 - 16;
    if (note && note.length * fs * 0.6 <= room) s += `<text x="${f1(W - pad.r)}" y="${f1(y + 12)}" text-anchor="end" font-family="IBM Plex Mono,monospace" font-size="${fs}" fill="${MUTED}">${esc(note)}</text>`;
    y += 20;
    return s;
  };
  const gapAfter = mobile ? 16 : 18;
  const bands = []; // {id, top, plot, bottom}: where each stave sits, for the cursor's reach and a lens's veil
  const open = (id) => bands.push({ id, top: y, plot: y });
  const close = () => ((bands[bands.length - 1].bottom = y), (y += gapAfter));

  for (const id of staves) {
    if (id === "line") continue;

    if (id === "scale" && D.some((d) => d.w != null)) {
      open(id);
      const pts = D.map((d, i) => (d.w != null ? { i, v: d.w } : null)).filter(Boolean);
      const vLo = Math.min(...pts.map((q) => q.v));
      const vHi = Math.max(...pts.map((q) => q.v));
      const miss = n - pts.length;
      g += head("The scale", `pounds, every morning weighed · ${num(vHi, 1)} to ${num(vLo, 1)}${miss ? ` · a hollow tick is a morning with no weigh-in (${miss})` : ""}`);
      const h = mobile ? 76 : 96;
      const Y = (v) => y + 20 + (1 - (v - vLo) / (vHi - vLo || 1)) * (h - 32);
      let solid = "";
      let dashed = "";
      for (let k = 1; k < pts.length; k++) {
        const seg = `M${f1(X(pts[k - 1].i))},${f1(Y(pts[k - 1].v))} L${f1(X(pts[k].i))},${f1(Y(pts[k].v))}`;
        if (pts[k].i - pts[k - 1].i > 1) dashed += seg;
        else solid += seg;
      }
      if (dashed) g += `<path d="${dashed}" fill="none" stroke="${INK}" stroke-width="1.2" stroke-dasharray="2 3" opacity="0.7"/>`;
      if (solid) g += `<path d="${solid}" fill="none" stroke="${INK}" stroke-width="1.5" stroke-linejoin="round"/>`;
      pts.forEach((q, k) => (g += `<circle cx="${f1(X(q.i))}" cy="${f1(Y(q.v))}" r="${k === pts.length - 1 ? (mobile ? 3.4 : 4) : mobile ? 1.7 : 2.2}" fill="${k === pts.length - 1 ? COBALT : INK}"/>`));
      D.forEach((d, i) => {
        if (d.w == null) g += `<rect x="${f1(X(i) - 1.5)}" y="${f1(y + h - 7)}" width="3" height="7" fill="none" stroke="${MUTED}" stroke-width="1"/>`;
      });
      g += `<line x1="${f1(pad.l - bw / 2)}" y1="${f1(y + h + 0.5)}" x2="${f1(W - pad.r + bw / 2)}" y2="${f1(y + h + 0.5)}" stroke="${RULE}" stroke-width="1"/>`;
      const a = pts[0];
      const z = pts[pts.length - 1];
      g += text(X(a.i) + 6, Math.max(y + 11, Y(a.v) - 7), `${num(a.v, 1)} lb`, "start", INK, 600);
      if (z !== a) g += text(X(z.i) - 8, Math.min(y + h - 4, Y(z.v) - 8), `${num(z.v, 1)} lb`, "end", COBALT, 600);
      y += h + 1;
      close();
    }

    if (id === "lifts" && p.lifts.length && D.some((d) => d.lifts.some(Boolean))) {
      open(id);
      const sets = D.flatMap((d) => d.lifts.filter(Boolean));
      const vLo = Math.min(...sets.map((s) => s.lb));
      const vHi = Math.max(...sets.map((s) => s.lb));
      g += head("The bar", `heaviest set of each session, lb × reps · ${p.lifts.join(", ")} · a line joins sets of the same reps`);
      const h = mobile ? 70 : 78;
      const Y = (v) => y + 18 + (1 - (v - vLo) / (vHi - vLo || 1)) * (h - 24);
      const boxes = [];
      // every dot is an obstacle a label goes round
      D.forEach((d, i) => d.lifts.forEach((q) => q && boxes.push({ l: X(i) - 4, r: X(i) + 4, t: Y(q.lb) - 4, b: Y(q.lb) + 4 })));
      p.lifts.forEach((name, k) => {
        const ink = k === 0 ? INK : OCHRE;
        const pts = D.map((d, i) => (d.lifts[k] ? { i, ...d.lifts[k] } : null)).filter(Boolean);
        // a heavier set at fewer reps is not a like-for-like gain, so a line joins only sets of the SAME rep count
        // (three or more of them); every other set is a hollow dot
        const byReps = new Map();
        pts.forEach((q) => q.reps != null && byReps.set(q.reps, [...(byReps.get(q.reps) || []), q]));
        const runs = [...byReps.entries()].filter(([, v]) => v.length >= 3).sort((a, b) => b[1].length - a[1].length || a[0] - b[0]);
        const inRun = new Set(runs.flatMap(([, v]) => v));
        for (const [, v] of runs) g += `<path d="${v.map((q, j) => `${j ? "L" : "M"}${f1(X(q.i))},${f1(Y(q.lb))}`).join(" ")}" fill="none" stroke="${ink}" stroke-width="1.2" opacity="0.6"/>`;
        for (const q of pts) g += `<circle cx="${f1(X(q.i))}" cy="${f1(Y(q.lb))}" r="${mobile ? 2.3 : 2.8}" fill="${inRun.has(q) ? ink : PAPER}" stroke="${ink}" stroke-width="1.2"/>`;
        // each joined run names its reps at its first set and its weight at its last
        // only the longest same-reps run of each lift is labelled; the others are drawn, and the readout names any set
        runs.slice(0, 1).forEach(([reps, v], r) => {
          const ends = [v[0], v[v.length - 1]];
          ends.forEach((q, j) => {
            const s = j === 0 ? `${r === 0 ? `${mobile ? name.split(" ")[0] : name} ` : ""}${num(q.lb, 0)} × ${num(reps, 0)}` : `${num(q.lb, 0)} × ${num(reps, 0)}`;
            const w = s.length * fs * 0.6;
            let anchor = j === 0 ? "start" : "end";
            let lx = X(q.i) + (j === 0 ? -3 : 3);
            if (anchor === "end" && lx - w < pad.l) [anchor, lx] = ["start", X(q.i) - 3];
            if (anchor === "start" && lx + w > W - pad.r) [anchor, lx] = ["end", X(q.i) + 3];
            const slots = (k === 0 ? [Y(q.lb) - 8, Y(q.lb) - 20, Y(q.lb) + 17] : [Y(q.lb) + 17, Y(q.lb) - 8, Y(q.lb) + 29]).map((yy) => Math.max(y + 10, Math.min(y + h + 4, yy)));
            const box = (yy) => ({ l: anchor === "end" ? lx - w : lx, r: anchor === "end" ? lx : lx + w, t: yy - fs, b: yy + 3 });
            const yy = slots.find((c) => !boxes.some((b) => box(c).l < b.r + 2 && box(c).r > b.l - 2 && box(c).t < b.b && box(c).b > b.t));
            if (yy == null) return;
            boxes.push(box(yy));
            g += text(lx, yy, s, anchor, k === 0 ? INK : "#7A5108", 600);
          });
        });
      });
      y += h;
      close();
    }

    if (id === "move" && D.some((d) => d.st != null || d.vol != null)) {
      open(id);
      const vMax = Math.max(1, ...D.map((d) => d.vol || 0));
      const sMax = Math.max(1, ...D.map((d) => d.st || 0));
      g += head("Gym, above · steps, below", `kg moved in a logged gym session, most ${num(Math.round(vMax), 0)} · steps over the whole day, most ${num(sMax, 0)}`);
      const marked = new Set((o.mark || []).map((i) => i - lo));
      const streakShown = Boolean(p.streak && p.streak.from >= lo && p.streak.to <= lo + n - 1);
      const hr = streakShown ? 16 : 0; // room for the bracket above the tallest bar
      const hu = (mobile ? 40 : 48) + hr;
      const hd = mobile ? 40 : 48;
      const mid = y + hu;
      D.forEach((d, i) => {
        const x = X(i) - bw / 2;
        if (d.ses) {
          if (d.vol) g += `<rect x="${f1(x)}" y="${f1(mid - Math.max(2, (d.vol / vMax) * (hu - hr)))}" width="${f1(bw)}" height="${f1(Math.max(2, (d.vol / vMax) * (hu - hr)))}" fill="${INK}"/>`;
          // a session with no lifted load (a ride, a run): a hollow mark, so it is not read as a day off
          else g += `<rect x="${f1(x + 0.5)}" y="${f1(mid - 6)}" width="${f1(Math.max(1.5, bw - 1))}" height="5" fill="${PAPER}" stroke="${INK}" stroke-width="1"/>`;
        }
        if (d.st != null) g += `<rect x="${f1(x)}" y="${f1(mid + 1)}" width="${f1(bw)}" height="${f1(Math.max(1, (d.st / sMax) * hd))}" fill="${marked.has(i) ? COBALT : GREY}"/>`;
      });
      // the longest unbroken run of gym days, bracketed: a fact of the record, not a comment on it
      if (streakShown) {
        const a = X(p.streak.from - lo) - bw / 2;
        const b = X(p.streak.to - lo) + bw / 2;
        const by = y + 6;
        // a bracket is never drawn without its words: the long form, the short form, or nothing
        const days = p.streak.to - p.streak.from + 1;
        const s = [`${days} gym days in a row`, `${days} in a row`].find((c) => c.length * fs * 0.6 + 12 < b - a - 8);
        if (s) {
          const tw = s.length * fs * 0.6 + 12;
          g += `<path d="M${f1(a)},${f1(by + 5)} V${f1(by)} H${f1(b)} V${f1(by + 5)}" fill="none" stroke="${INK}" stroke-width="1"/>`;
          g += `<rect x="${f1((a + b) / 2 - tw / 2)}" y="${f1(by - 7)}" width="${f1(tw)}" height="14" fill="${PAPER}"/>` + text((a + b) / 2, by + 4, s, "middle", INK, 600);
        }
      }
      g += `<line x1="${f1(pad.l - bw / 2)}" y1="${f1(mid + 0.5)}" x2="${f1(W - pad.r + bw / 2)}" y2="${f1(mid + 0.5)}" stroke="${INK}" stroke-width="1"/>`;
      y += hu + hd + 1;
      close();
    }

    if (id === "night" && D.some((d) => d.sl != null)) {
      open(id);
      const tgt = p.sleepTarget;
      const vals = D.map((d) => d.sl).filter((v) => v != null);
      const vLo = Math.min(...vals, tgt ?? Infinity) - 0.3;
      const vHi = Math.max(...vals, tgt ?? -Infinity) + 0.3;
      g += head("The night", `hours asleep · ${num(Math.min(...vals), 1)} to ${num(Math.max(...vals), 1)}${tgt != null ? ` · the rule is his ${num(tgt, 1)}-hour target` : ""}`);
      const h = mobile ? 44 : 50;
      const Y = (v) => y + (1 - (v - vLo) / (vHi - vLo || 1)) * h;
      const base = tgt != null ? Y(tgt) : y + h;
      g += `<line x1="${f1(pad.l - bw / 2)}" y1="${f1(base)}" x2="${f1(W - pad.r + bw / 2)}" y2="${f1(base)}" stroke="${RULE}" stroke-width="1"/>`;
      D.forEach((d, i) => {
        if (d.sl == null) g += `<rect x="${f1(X(i) - 1.5)}" y="${f1(base - 3.5)}" width="3" height="7" fill="${PAPER}" stroke="${MUTED}" stroke-width="1"/>`;
        else g += `<line x1="${f1(X(i))}" y1="${f1(base)}" x2="${f1(X(i))}" y2="${f1(Y(d.sl))}" stroke="${INK}" stroke-width="${mobile ? 1.1 : 1.3}"/><circle cx="${f1(X(i))}" cy="${f1(Y(d.sl))}" r="${mobile ? 1.6 : 2}" fill="${INK}"/>`;
      });
      y += h;
      close();
    }

    if (id === "heart" && D.some((d) => d.rhr != null)) {
      open(id);
      const vals = D.map((d) => d.rhr).filter((v) => v != null);
      const vLo = Math.min(...vals);
      const vHi = Math.max(...vals);
      g += head("The morning", `resting heart rate, beats a minute · ${num(vLo, 0)} to ${num(vHi, 0)}`);
      const h = mobile ? 44 : 50;
      const Y = (v) => y + 4 + (1 - (v - vLo) / (vHi - vLo || 1)) * (h - 8);
      const mk = p.marker && p.marker.date > D[0].d && p.marker.date <= D[n - 1].d ? D.findIndex((d) => d.d === p.marker.date) : -1;
      // the line is read within each side of a device change, never across it (the Journey's rule)
      let path = "";
      let pen = false;
      D.forEach((d, i) => {
        if (d.rhr == null || i === mk) pen = false;
        if (d.rhr == null) return;
        path += `${pen ? "L" : "M"}${f1(X(i))},${f1(Y(d.rhr))} `;
        pen = true;
      });
      g += `<path d="${path}" fill="none" stroke="${INK}" stroke-width="1.2" opacity="0.5"/>`;
      D.forEach((d, i) => {
        if (d.rhr != null) g += `<circle cx="${f1(X(i))}" cy="${f1(Y(d.rhr))}" r="${mobile ? 1.6 : 2}" fill="${INK}"/>`;
      });
      if (mk >= 0) {
        const mx = X(mk) - cw / 2;
        g += `<line x1="${f1(mx)}" y1="${f1(y - 2)}" x2="${f1(mx)}" y2="${f1(y + h + 2)}" stroke="${OCHRE}" stroke-width="1.2" stroke-dasharray="3 3"/>`;
        g += text(mx + 5, y + 9, mobile ? "device" : `${p.marker.label || "device change"} · ${dayInWords(p.marker.date, { short: true })}`, "start", "#7A5108");
      }
      y += h;
      close();
    }

    if (id === "food" && D.some((d) => d.kcal != null || d.fs === "wait")) {
      open(id);
      const vMax = Math.max(1, ...D.map((d) => (d.fs === "ok" ? d.kcal : 0)));
      const floor = (D.find((d) => d.floor != null) || {}).floor;
      g += head("The plate", `calories on complete logged days, from zero · most ${num(vMax, 0)}${floor != null ? ` · a cobalt cap is a day at or above the ${num(floor, 0)} g protein floor` : ""}`);
      const h = mobile ? 44 : 52;
      const base = y + h;
      D.forEach((d, i) => {
        const x = X(i) - bw / 2;
        if (d.fs === "ok") {
          const bh = Math.max(2, (d.kcal / vMax) * (h - 4));
          g += `<rect x="${f1(x)}" y="${f1(base - bh)}" width="${f1(bw)}" height="${f1(bh)}" fill="${INK}"/>`;
          if (d.prot != null && d.floor != null && d.prot >= d.floor) g += `<rect x="${f1(x)}" y="${f1(base - bh - 4)}" width="${f1(bw)}" height="3" fill="${COBALT}"/>`;
        } else if (d.fs === "wait" || d.fs === "part") {
          // not a zero: the record does not hold this day's food (still being logged, or marked as a gap)
          g += `<rect x="${f1(x + 0.5)}" y="${f1(base - 9)}" width="${f1(Math.max(1.5, bw - 1))}" height="8.5" fill="${PAPER}" stroke="${MUTED}" stroke-width="1" stroke-dasharray="2 2"/>`;
        }
      });
      g += `<line x1="${f1(pad.l - bw / 2)}" y1="${f1(base + 0.5)}" x2="${f1(W - pad.r + bw / 2)}" y2="${f1(base + 0.5)}" stroke="${INK}" stroke-width="1"/>`;
      y += h + 1;
      close();
    }

    if (id === "calls" && D.some((d) => d.right + d.wrong > 0)) {
      open(id);
      const R = D.reduce((a, d) => a + d.right, 0);
      const Xn = D.reduce((a, d) => a + d.wrong, 0);
      const most = Math.max(1, ...D.map((d) => Math.max(d.right, d.wrong)));
      g += head("The coaches' calls", `on the day each settled · ${R} right, above · ${Xn} wrong, below`);
      const half = mobile ? 24 : 28;
      const mid = y + half;
      const u = Math.max(2.5, Math.min(bw, 6, half / most - 1));
      const sw = Math.max(1.6, Math.min(bw, 6));
      D.forEach((d, i) => {
        for (let k = 0; k < d.right; k++) g += `<rect x="${f1(X(i) - sw / 2)}" y="${f1(mid - 2 - (k + 1) * (u + 1) + 1)}" width="${f1(sw)}" height="${f1(u)}" fill="${COBALT}"/>`;
        for (let k = 0; k < d.wrong; k++) g += `<rect x="${f1(X(i) - sw / 2)}" y="${f1(mid + 2 + k * (u + 1))}" width="${f1(sw)}" height="${f1(u)}" fill="${VERM}"/>`;
      });
      g += `<line x1="${f1(pad.l - bw / 2)}" y1="${f1(mid)}" x2="${f1(W - pad.r + bw / 2)}" y2="${f1(mid)}" stroke="${RULE}" stroke-width="1"/>`;
      y += half * 2;
      close();
    }

    if (id === "chapters" && p.chapters.length) {
      open(id);
      g += head("The chapters", "the days each published chapter covers · a blank run has none");
      const by = y + 4;
      for (const c of p.chapters) {
        if (c.to < D[0].d || c.from > D[n - 1].d) continue;
        const a = Math.max(0, D.findIndex((d) => d.d >= c.from));
        const b = D.reduce((acc, d, i) => (d.d <= c.to ? i : acc), a);
        const x1 = X(a) - bw / 2;
        const x2 = X(b) + bw / 2;
        g += `<rect x="${f1(x1)}" y="${f1(by)}" width="${f1(Math.max(2, x2 - x1))}" height="4" fill="${COBALT}"/>`;
        g += text((x1 + x2) / 2, by + 19, c.n, "middle", COBALT, 600);
      }
      y += 24;
      close();
    }
  }
  const H = Math.ceil(bands.length ? y - gapAfter + 4 : LH);
  const bottom = bands.length ? Math.max(...bands.map((b) => b.bottom), top0) : LH;

  // the ten-pound rungs, carried down from The Line as hairlines: the same dates, through every stave
  let under = "";
  if (hasLine) {
    for (const r of p.rungs || []) {
      const i = D.findIndex((d) => d.d === r.date);
      if (i > 0) under += `<line x1="${f1(X(i))}" y1="${f1(LY + line.baseY)}" x2="${f1(X(i))}" y2="${f1(bottom)}" stroke="${RULE2}" stroke-width="1"/>`;
    }
  }
  // a week on its own names its days under the last stave
  let foot = "";
  let Hx = H;
  if (cw >= 26) {
    D.forEach((d, i) => {
      const s = `${WEEKDAYS[weekdayOf(d.d)].slice(0, mobile ? 1 : 3)} ${Number(d.d.slice(8))}`;
      // an edge column's name stays inside the frame
      const half = (s.length * fs * 0.6) / 2 + 2;
      foot += text(Math.max(half, Math.min(W - half, X(i))), H + 12, s, "middle", MUTED);
    });
    Hx = H + 20;
  }

  // The Line's y under each column (a missing morning stands on the dashed bridge between its neighbours)
  let lineY = null;
  if (line && line.points.length) {
    const pts = line.points;
    lineY = D.map((d) => {
      const at = pts.find((q) => q.date === d.d);
      if (at) return LY + at.y;
      const before = [...pts].reverse().find((q) => q.date < d.d);
      const after = pts.find((q) => q.date > d.d);
      if (before && after) {
        const t0 = Date.parse(`${before.date}T00:00:00Z`);
        const k = (Date.parse(`${d.d}T00:00:00Z`) - t0) / (Date.parse(`${after.date}T00:00:00Z`) - t0);
        return LY + before.y + (after.y - before.y) * k;
      }
      return LY + (before || after).y;
    });
  }
  const geom = { W, H: Hx, lo, n, cw, bw, padL: pad.l, padR: pad.r, top: hasLine ? LY + line.pad.t - 12 : bands[0] ? bands[0].plot - 2 : top0, bottom, lineY, mobile, WH, walker: Boolean(wantWalker && lineY), lineBase: hasLine ? LY + line.baseY : null, bands: bands.map((b) => ({ t: b.plot, b: b.bottom })) };
  const cursor = o.cursor == null ? n - 1 : Math.max(0, Math.min(n - 1, o.cursor - lo));
  const svg =
    `<svg viewBox="0 0 ${W} ${Hx}" width="100%" role="img" aria-label="${esc(o.aria || "")}" data-thedays-svg>` +
    under +
    (line ? line.svg : "") +
    g +
    foot +
    `<g data-veil></g>${heads}<g data-cursor>${cursorMarkup(p, geom, cursor)}</g></svg>`;
  return { svg, geom };
}

/** The cursor: one column lit through every stave, and (the game layer) the walker standing on The Line at that day. */
export function cursorMarkup(p, geom, i) {
  if (!geom) return "";
  const x = geom.padL + (geom.n === 1 ? (geom.W - geom.padL - geom.padR) / 2 : i * geom.cw);
  const w = Math.max(3, Math.min(geom.cw, 22));
  let s = `<rect x="${(x - w / 2).toFixed(1)}" y="${geom.top.toFixed(1)}" width="${w.toFixed(1)}" height="${(geom.bottom - geom.top).toFixed(1)}" fill="${COBALT}" opacity="0.1"/>`;
  s += `<line x1="${x.toFixed(1)}" y1="${geom.top.toFixed(1)}" x2="${x.toFixed(1)}" y2="${geom.bottom.toFixed(1)}" stroke="${COBALT}" stroke-width="1"/>`;
  if (geom.walker && geom.lineY) {
    const d = p.days[geom.lo + i];
    const { stage } = walkerStage(p, d.d);
    const h = geom.WH;
    const k = h / 114;
    const wy = geom.lineY[i];
    // his feet (y = 126 in the drawing's box, x = 84) stand on the reading; at either edge he stays inside the figure
    const wx = Math.max(0, Math.min(geom.W - 70 * k, x - (84 - 50) * k));
    s += `<svg x="${wx.toFixed(1)}" y="${Math.max(0, wy - (126 - 20) * k).toFixed(1)}" width="${(70 * k).toFixed(1)}" height="${h}" viewBox="50 20 70 114" data-walker="${stage}">${walkerInner(stage)}</svg>`;
  }
  return s;
}

/** A lens's veil: in every stave, paper is laid over the columns the lens does not hold, so the held days stay ink.
 *  The Line itself is never veiled (it is the context); the held days are marked on it as pale columns. */
export function veilMarkup(geom, idx) {
  if (!geom || !idx) return "";
  const held = new Set(idx.map((i) => i - geom.lo));
  const xOf = (i) => geom.padL + i * geom.cw;
  const runs = [];
  let run = null;
  for (let i = 0; i <= geom.n; i++) {
    if (i < geom.n && !held.has(i)) run = run == null ? i : run;
    else if (run != null) (runs.push([run, i - 1]), (run = null));
  }
  let s = "";
  for (const b of geom.bands || []) {
    for (const [a, z] of runs) {
      const x1 = Math.max(0, xOf(a) - geom.cw / 2);
      const x2 = Math.min(geom.W, xOf(z) + geom.cw / 2);
      s += `<rect x="${x1.toFixed(1)}" y="${(b.t - 1).toFixed(1)}" width="${(x2 - x1).toFixed(1)}" height="${(b.b - b.t + 3).toFixed(1)}" fill="${PAPER}" opacity="0.86"/>`;
    }
  }
  if (geom.lineBase != null) {
    const w = Math.max(3, Math.min(geom.cw, 14));
    for (const i of held) if (i >= 0 && i < geom.n) s += `<rect x="${(xOf(i) - w / 2).toFixed(1)}" y="${geom.top.toFixed(1)}" width="${w.toFixed(1)}" height="${(geom.lineBase - geom.top).toFixed(1)}" fill="${COBALT}" opacity="0.13"/>`;
  }
  return s;
}

const KIT = ["", "a pencil sketch at the start", "boots and a stick", "a scarf and a stride", "a pack and a lit lantern", "the full kit"];

/** One day on one line, for the Start figure: the date, the scale, the gym and the steps — and the door to the day. */
export function readoutLine(p, i) {
  const d = p.days[i];
  if (!d) return "";
  const parts = [d.w != null ? `${num(d.w, 1)} lb` : "no weigh-in", d.ses ? (d.vol ? `gym, ${num(Math.round(d.vol), 0)} kg moved` : "gym session") : "no gym session", d.st != null ? `${num(d.st, 0)} steps` : null].filter(Boolean);
  return `<p class="td-line"><b>${dayInWords(d.d, { weekday: true })}</b><span class="mono">day ${num(d.n, 0)}</span><span>${parts.join(" · ")}</span><a href="${esc(d.u)}">That day →</a></p>`;
}

/** One day in words, as a small table: the readout under the figure. The build writes it for the newest day; the
 *  island rewrites it as the cursor moves. Only what the Day page for that date already says. */
export function readout(p, i, o = {}) {
  const d = p.days[i];
  if (!d) return "";
  const row = (k, v, cls = "") => `<div${cls ? ` class="${cls}"` : ""}><dt>${k}</dt><dd>${v}</dd></div>`;
  const none = (s) => `<span class="td-none">${s}</span>`;
  let rows = "";
  rows += row("Scale", d.w != null ? `${num(d.w, 1)} lb${p.startValue != null && d.d !== p.startDate ? ` <small>${num(Math.abs(d.w - p.startValue), 1)} ${d.w <= p.startValue ? "below" : "above"} day one</small>` : ""}` : none("no weigh-in"));
  const lifted = d.lifts.map((s, k) => (s ? `${p.lifts[k]} ${num(s.lb, 0)} lb${s.reps != null ? ` × ${num(s.reps, 0)}` : ""}` : null)).filter(Boolean);
  rows += row("Gym session", d.ses ? `${d.min != null ? `${num(d.min, 0)} min` : "logged"}${d.vol ? ` · ${num(Math.round(d.vol), 0)} kg moved` : ""}${lifted.length ? ` <small>${esc(lifted.join(" · "))}</small>` : ""}` : none("none logged"));
  rows += row("Steps, whole day", d.st != null ? num(d.st, 0) : none("not recorded"));
  rows += row("Slept", d.sl != null ? `${num(d.sl, 1)} h` : none("not recorded"));
  rows += row("Morning", d.rec != null || d.rhr != null ? [d.rec != null ? `recovery ${num(d.rec, 0)}` : null, d.rhr != null ? `resting heart rate ${num(d.rhr, 0)}` : null].filter(Boolean).join(" · ") : none("not recorded"));
  rows += row("Food", d.fs === "ok" ? `${num(d.kcal, 0)} kcal${d.prot != null ? ` · ${num(d.prot, 0)} g protein` : ""}` : none(d.fs === "wait" ? "not exported yet" : d.fs === "part" ? "an incomplete record, not counted" : "not logged"));
  if (d.right + d.wrong > 0) rows += row("Calls settled", [d.right ? `${d.right} right` : null, d.wrong ? `${d.wrong} wrong` : null].filter(Boolean).join(" · "));
  const ch = d.ch >= 0 ? p.chapters[d.ch] : null;
  let walker = "";
  if (o.walker && WALKER) {
    const { stage, last } = walkerStage(p, d.d);
    walker = `<p class="td-walker">${walkerFigure(stage, 34)}<span><b>The walker</b> is a game drawn on the weigh-ins, not a measurement. ${stage === 1 ? "Here he is a pencil sketch: no ten-pound rung crossed yet." : `Kit ${stage} of 5 — ${KIT[stage]} — since the scale first read under ${num(last.lb, 0)} on ${dayInWords(last.date, { short: true })}.`}</span></p>`;
  }
  return (
    `<p class="td-day"><b>${dayInWords(d.d, { weekday: true })}</b><span class="mono">day ${num(d.n, 0)}</span></p>` +
    `<dl class="td-read">${rows}</dl>` +
    `<p class="td-links"><a href="${esc(d.u)}">Everything recorded that day →</a>${ch ? `<a href="${esc(ch.u)}">Chapter ${esc(ch.n)} · ${esc(ch.title)} →</a>` : `<span class="td-none">No published chapter covers this day.</span>`}</p>` +
    walker
  );
}
