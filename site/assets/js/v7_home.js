// v7_home.js — the v7 Home page's renderer (#4182, Prototype C screen I "The log").
//
// Every number on the page comes from a served field and carries it in `data-src`
// (endpoint.path). Absence is stated as absence; dates are in words through the shared
// formatter (entry_age.dayInWords) — never ISO; "Data through <day>" appears once, on the
// alive line. Owner ruling 2026-09-26: no earlier starts, attempts, cycles or resets
// anywhere — the frame is the experiment and the day (tests/js/v7_home.test.mjs holds it).
//
// The pure builders are exported so the node tests can drive them from fixtures; mount()
// is the only thing that touches the DOM, and only when the Home slots are on the page.
import { tryJSON, esc, todayPT } from "/assets/js/evidence_shared.js";
import { dayInWords, instantDayInWords, countWord, dayLabel, nextWeighInText, servedWindow } from "/assets/js/entry_age.js";

const HORIZON = 30; // the day the next photo is due (the first, day 1, is on the fold — #3761)
const DAY1_PHOTO_DATE = "2026-09-06"; // the day the fold's photograph was taken (its file name carries the same date)

// ── small helpers ──────────────────────────────────────────────────────────────
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const _noon = (iso) => Date.parse(`${String(iso || "").slice(0, 10)}T12:00:00Z`);
export function isoPlus(iso, days) {
  const t = _noon(iso);
  return Number.isFinite(t) ? new Date(t + days * 86400000).toISOString().slice(0, 10) : "";
}
const dayNum = (iso) => Math.round(_noon(iso) / 86400000);
const weekdayOf = (iso) => (dayInWords(iso).split(",")[0] || "");
const fmt1 = (v) => (num(v) === null ? "" : v.toFixed(1));
const fmtInt = (v) => (num(v) === null ? "" : Math.round(v).toLocaleString("en-US"));
const src = (path) => ` data-src="${esc(path)}"`;
const span = (path, text, cls) => `<span${cls ? ` class="${cls}"` : ""}${src(path)}>${esc(text)}</span>`;
const time = (iso, path) => (iso ? `<time datetime="${esc(iso)}"${path ? src(path) : ""}>${esc(dayInWords(iso))}</time>` : "");
const pending = (what) => `<p class="v7h-note">${esc(what)} is not served right now.</p>`;
const PT_TIME = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" });
const clockPT = (instant) => {
  const t = Date.parse(String(instant || ""));
  return Number.isFinite(t) ? PT_TIME.format(new Date(t)).toLowerCase() : "";
};
// A coach's field in the reader's words (the served ids are machine names).
const COACH_WORDS = { sleep: "sleep", nutrition: "nutrition", mind: "mind", physical: "training", training: "training", glucose: "blood-sugar", labs: "blood-test", explorer: "statistics", eli_marsh: "lead" };
const coachField = (id) => COACH_WORDS[String(id || "").replace(/_coach$/, "")] || String(id || "").replace(/_coach$/, "").replace(/_/g, " ");
const coachName = (coaches, id) => {
  const c = (coaches || []).find((x) => x.persona_id === id) || null;
  return c ? c.name : String(id || "").replace(/_coach$/, "").replace(/_/g, " ");
};

// ── the fold ───────────────────────────────────────────────────────────────────
// The photograph's caption: its date in words, the day of the experiment it was taken on
// (computed from the served start, never typed), and — on day 1 only — the served start
// weight, which is the weigh-in of that same morning. "" when the start is not served.
export function photoCaption(journey, photoDate = DAY1_PHOTO_DATE) {
  const j = journey || {};
  if (!j.started_date || !photoDate) return "";
  const n = dayNum(photoDate) - dayNum(j.started_date) + 1;
  if (!Number.isFinite(n) || n < 1) return "";
  const onStart = String(j.started_date).slice(0, 10) === photoDate;
  const when = time(photoDate, onStart ? "journey.started_date" : "");
  const day = `day ${span("journey.started_date → photo date", String(n))}`;
  const w = num(j.start_weight_lbs);
  const weight = n === 1 && w !== null ? `, ${span("journey.start_weight_lbs", fmt1(w), "num")} lb` : "";
  return `${when} — ${day}${weight}`;
}

export function numberBlock(journey) {
  const j = journey || {};
  const cur = num(j.current_weight_lbs);
  if (cur === null) return pending("The latest weigh-in");
  const lost = num(j.lost_lbs);
  const n = num(j.day_n);
  const out = [`<p class="v7h-big">${span("journey.current_weight_lbs", fmt1(cur))}<small>lb</small></p>`];
  if (j.last_weighin_date) out.push(`<p class="v7h-when">${time(j.last_weighin_date, "journey.last_weighin_date")}</p>`);
  if (lost !== null && num(j.start_weight_lbs) !== null) {
    const dir = lost >= 0 ? "Down" : "Up";
    const days = n !== null ? ` in ${span("journey.day_n", String(n))} days` : "";
    out.push(
      `<p class="v7h-delta">${dir} <b>${span("journey.lost_lbs", fmt1(Math.abs(lost)), "num")} lb</b>${days}, from ${span("journey.start_weight_lbs", fmt1(j.start_weight_lbs), "num")}.</p>`,
    );
  }
  const count = num(j.weighin_count);
  const rate = num(j.weekly_rate_lbs);
  if (count !== null) {
    let line = `${span("journey.weighin_count", String(count))} weigh-in${count === 1 ? "" : "s"}`;
    if (rate !== null) {
      const lo = num(j.weekly_rate_ci_high);
      const hi = num(j.weekly_rate_ci_low);
      const ci = lo !== null && hi !== null ? ` (${span("journey.weekly_rate_ci_high", fmt1(Math.abs(lo)))} to ${span("journey.weekly_rate_ci_low", fmt1(Math.abs(hi)))})` : "";
      line += ` · about ${span("journey.weekly_rate_lbs", fmt1(Math.abs(rate)))} lb a week${ci}${j.rate_provisional ? ", provisional" : ""}`;
    }
    out.push(`<p class="v7h-range">${line}.</p>`);
  }
  return out.join("");
}

// The fold's this-week line: weight_progress since the latest write-up's date.
export function thisWeekLine(progress, posts) {
  const wp = Array.isArray(progress) ? progress : [];
  const since = posts && posts[0] && posts[0].date ? String(posts[0].date).slice(0, 10) : "";
  const last = wp.length ? wp[wp.length - 1] : null;
  const from = since ? wp.find((r) => r.date >= since) : null;
  const path = "weight_progress + journal/posts.json posts[0].date";
  if (from && last && from.date !== last.date) {
    return `<p class="v7h-range"${src(path)}>This week: <span class="num">${esc(fmt1(from.weight_lbs))} → ${esc(fmt1(last.weight_lbs))}</span> lb since ${esc(weekdayOf(since))}’s write-up.</p>`;
  }
  if (last) return `<p class="v7h-range"${src(path)}>This week: no weigh-in since the last write-up; the latest is ${esc(fmt1(last.weight_lbs))} lb on ${esc(dayInWords(last.date))}.</p>`;
  return `<p class="v7h-range"${src(path)}>This week: no weigh-ins on record.</p>`;
}

// The lead sentence with its day-only branches (before day 30 / day 30 / after; pre-start).
export function leadSentence(journey, coachCount) {
  const j = journey || {};
  const n = num(j.day_n);
  const start = num(j.start_weight_lbs);
  const who = start !== null ? `a ${Math.floor(start / 100) * 100}-plus-pound man` : "one man";
  const eight = num(coachCount) !== null ? `${countWord(coachCount)} AI coaches` : "AI coaches";
  const frame = ` of an experiment run in public: ${who}, his own numbers, ${eight} reading them — published either way.`;
  if (j.pre_start || n === null || n < 1) {
    const when = j.started_date ? ` It begins ${time(j.started_date, "journey.started_date")}.` : "";
    return `<p class="v7h-premise"${src("journey.{day_n,pre_start,started_date}")}>The eve${frame}${when}</p>`;
  }
  const began = start !== null && j.started_date ? ` Matthew weighed ${span("journey.start_weight_lbs", fmt1(start), "num")} lb on ${time(j.started_date, "journey.started_date")}, the day it began.` : "";
  let tail = "";
  if (n === HORIZON) tail = ` Today is day ${HORIZON} — the next photo is due.`;
  else if (n < HORIZON && j.started_date) tail = ` Day ${HORIZON} is ${time(isoPlus(j.started_date, HORIZON - 1), "journey.started_date + 29 days")}.`;
  return `<p class="v7h-premise"${src("journey.{day_n,start_weight_lbs,started_date}")}><span class="v7h-earned">Day ${span("journey.day_n", String(n))}</span>${frame}${began}${tail}</p>`;
}

// The alive line: data through · the coaches' checked calls K of N · next write-up. The ONE
// "Data through" on the page.
export function aliveLine(throughDate, calibration, cadence, throughSrc = "vitals.as_of_date") {
  const parts = [];
  if (throughDate) parts.push(`Data through <b${src(throughSrc)}>${esc(dayInWords(throughDate))}</b>`);
  const c = calibration && calibration.platform && calibration.platform.strata && calibration.platform.strata.coaches;
  if (c && num(c.n) !== null && num(c.confirmed) !== null) {
    parts.push(`the coaches’ checked calls so far, by the site’s own count: <b>${span("calibration.platform.strata.coaches.confirmed", String(c.confirmed))} of ${span("calibration.platform.strata.coaches.n", String(c.n))}</b> right`);
  } else parts.push("no checked coach call is served yet");
  const ch = cadence && cadence.chronicle;
  if (ch && !ch.paused && ch.next_date) parts.push(`next write-up <b>${time(ch.next_date, "content_cadence.chronicle.next_date")}</b>`);
  else if (ch && ch.paused) parts.push("the write-up is paused");
  return `<p class="v7h-alive">${parts.join(" · ")}</p>`;
}

// ── every weigh-in so far ──────────────────────────────────────────────────────
export function stripPoints(progress) {
  const wp = (Array.isArray(progress) ? progress : []).filter((r) => r && r.date && num(r.weight_lbs) !== null);
  if (wp.length < 2) return [];
  const d0 = dayNum(wp[0].date);
  const d1 = dayNum(wp[wp.length - 1].date);
  const ws = wp.map((r) => r.weight_lbs);
  const wmin = Math.min(...ws);
  const wmax = Math.max(...ws);
  return wp.map((r) => ({
    x: +(6 + ((dayNum(r.date) - d0) / Math.max(1, d1 - d0)) * 308).toFixed(1),
    y: +(6 + (wmax === wmin ? 23 : ((wmax - r.weight_lbs) / (wmax - wmin)) * 46)).toFixed(1),
    date: r.date,
    lbs: r.weight_lbs,
  }));
}

export function weighinsBlock(progress, journey) {
  const pts = stripPoints(progress);
  if (!pts.length) return pending("The weigh-in record");
  const first = pts[0];
  const last = pts[pts.length - 1];
  const dots = pts
    .map((p, i) => {
      const isLast = i === pts.length - 1;
      return `<circle cx="${p.x}" cy="${p.y}" r="${isLast ? 3.2 : 2.4}"${isLast ? ' class="v7h-last"' : ""}><title>${esc(dayInWords(p.date))} — ${esc(fmt1(p.lbs))} lb</title></circle>`;
    })
    .join("");
  const label = `${countWord(pts.length, { capital: true })} weigh-ins from ${fmt1(first.lbs)} on ${dayInWords(first.date, { weekday: false })} to ${fmt1(last.lbs)} on ${dayInWords(last.date, { weekday: false })}, drawn to the day.`;
  const svg =
    `<div class="v7h-strip"${src("weight_progress")}><svg viewBox="0 0 320 60" role="img" aria-label="${esc(label)}">` +
    `<line class="v7h-ax" x1="0" y1="6" x2="320" y2="6"/><polyline class="v7h-ln" points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}"/><g class="v7h-pt">${dots}</g></svg>` +
    `<div class="v7h-strip-lab"><span>${esc(fmt1(first.lbs))} · ${esc(dayInWords(first.date))}</span><span>${esc(fmt1(last.lbs))} · ${esc(dayInWords(last.date))}</span></div></div>`;
  // The gaps, counted from the record itself.
  let gapNote = "";
  let widest = null;
  for (let i = 1; i < pts.length; i++) {
    const g = dayNum(pts[i].date) - dayNum(pts[i - 1].date);
    if (g > 1 && (!widest || g > widest.g)) widest = { g, a: pts[i - 1].date, b: pts[i].date };
  }
  if (widest) gapNote = `No weigh-in between ${dayInWords(widest.a)} and ${dayInWords(widest.b)}`;
  const j = journey || {};
  const n = num(j.day_n);
  const count = num(j.weighin_count);
  if (n !== null && count !== null && n >= count) {
    const skipped = n - count;
    gapNote += `${gapNote ? "; " : ""}the scale was skipped on ${skipped} of the ${n} days`;
  }
  let goal = "";
  if (j.projected_goal_date) goal = ` The served date to goal is ${dayInWords(j.projected_goal_date)}.`;
  else if (num(j.weighin_span_days) !== null) goal = ` No date to goal is served — ${span("journey.weighin_span_days", String(j.weighin_span_days))} days of weigh-ins is too few to forecast one.`;
  else goal = " No date to goal is served.";
  return `${svg}<p class="v7h-small"${src("weight_progress + journey.{day_n,weighin_count,weighin_span_days,projected_goal_date}")}>${esc(gapNote)}${gapNote ? "." : ""}${goal}</p>`;
}

// ── in his words ───────────────────────────────────────────────────────────────
export function wordsBlock(decisions, pulse) {
  const notes = (Array.isArray(decisions) ? decisions : [])
    .map((d, i) => ({ i, note: String(d.note || "").trim(), at: d.note_at || "", date: d.date || "" }))
    .filter((d) => d.note);
  const out = [];
  if (!notes.length) out.push('<p class="v7h-note">No notes of his are on file.</p>');
  else {
    const stamp = (d) => {
      const day = d.at ? instantDayInWords(d.at) : dayInWords(d.date);
      const clock = d.at ? clockPT(d.at) : "";
      return clock ? `${day}, ${clock}` : day;
    };
    const byTime = notes.slice().sort((a, b) => String(a.at || a.date).localeCompare(String(b.at || b.date)));
    const earliest = byTime[0];
    const latest = byTime[byTime.length - 1];
    const ptDay = (d) => (d.at ? new Date(Date.parse(d.at)).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" }) : d.date);
    // Every note from the first evening, in order — not just the first of them. A lone note is
    // both earliest and latest: it prints once, as the earliest (it used to print nowhere).
    const firstEvening = byTime.filter((d) => (byTime.length === 1 || d !== latest) && ptDay(d) === ptDay(earliest));
    const stampSrc = (d) => `decisions[${d.i}].${d.at ? "note_at" : "date"}`;
    firstEvening.forEach((d, k) => {
      out.push(`<p class="v7h-dated"${src(stampSrc(d))}>${esc(stamp(d))} — ${k === 0 ? "the earliest note of his on file, to his coaches" : "the same evening"}:</p>`);
      out.push(`<blockquote${src(`decisions[${d.i}].note`)}>“${esc(d.note)}”</blockquote>`);
    });
    if (latest !== earliest) {
      out.push(`<p class="v7h-dated"${src(stampSrc(latest))}>${esc(stamp(latest))} — the most recent words of his on file:</p>`);
      out.push(`<blockquote${src(`decisions[${latest.i}].note`)}>“${esc(latest.note)}”</blockquote>`);
    }
  }
  const jg = pulse && pulse.pulse && pulse.pulse.glyphs && pulse.pulse.glyphs.journal;
  if (jg && jg.written_today) out.push(`<p class="v7h-note"${src("pulse.glyphs.journal.written_today")}>He wrote in his journal today.</p>`);
  else if (jg && num(jg.gap_days) !== null && jg.gap_days > 0) {
    out.push(`<p class="v7h-note">His journal has been silent for ${span("pulse.glyphs.journal.gap_days", String(jg.gap_days))} days. Nothing from him there this week.</p>`);
  }
  return out.join("");
}

// ── is he okay this week ───────────────────────────────────────────────────────
export function okayBlock(sleep, vitals, nutrition, training, pulse) {
  const out = [];
  // Sleep
  const sd = (sleep && sleep.sleep_detail) || {};
  const v = (vitals && vitals.vitals) || {};
  const bed = num(sd.total_sleep_hours);
  const strap = num(sd.whoop_hours);
  const night = sd.night_of || v.night_of || "";
  const nightWord = night ? `${weekdayOf(night)} night` : "Last night";
  let s = "";
  if (bed !== null && strap !== null) {
    s = Math.abs(bed - strap) < 0.3
      ? `${nightWord} he slept ${span("sleep_detail.total_sleep_hours", fmt1(bed))} hours — the wrist strap and the bed sensor agree.`
      : `${nightWord} the bed sensor read ${span("sleep_detail.total_sleep_hours", fmt1(bed))} hours of sleep and the wrist strap ${span("sleep_detail.whoop_hours", fmt1(strap))}.`;
  } else if (bed !== null || strap !== null) {
    const one = bed !== null ? ["sleep_detail.total_sleep_hours", bed, "the bed sensor"] : ["sleep_detail.whoop_hours", strap, "the wrist strap"];
    s = `${nightWord} he slept ${span(one[0], fmt1(one[1]))} hours, by ${one[2]}; the other sensor has nothing for the night.`;
  } else s = `${nightWord}’s sleep is not served.`;
  const rec = num(v.recovery_pct);
  const hrv = num(v.hrv_ms);
  if (rec !== null) s += ` The strap scored the night’s recovery (its 0-to-100 readiness figure) at ${span("vitals.recovery_pct", String(Math.round(rec)))}`;
  if (rec !== null && hrv !== null) {
    const avg = num(v.hrv_avg_ms);
    const w = num(v.hrv_avg_window_days);
    s += `; heart-rate variability was ${span("vitals.hrv_ms", fmt1(hrv))} ms`;
    if (avg !== null) s += ` against his ${w !== null ? `${span("vitals.hrv_avg_window_days", String(w))}-day ` : ""}average of ${span("vitals.hrv_avg_ms", fmt1(avg))}`;
  }
  if (rec !== null) s += ".";
  out.push(`<p><span class="v7h-k">Sleep</span>${s}`);
  // Eating
  const n = (nutrition && nutrition.nutrition) || {};
  const trend = (nutrition && nutrition.nutrition_trend) || [];
  const logged = num(n.days_logged);
  if (logged === null) out.push('<p><span class="v7h-k">Eating</span>No food log is served.</p>');
  else {
    const first = trend.length ? trend[0].date : "";
    const latest = n.latest_date || (trend.length ? trend[trend.length - 1].date : "");
    const spanDays = first && latest ? dayNum(latest) - dayNum(first) + 1 : null;
    const every = spanDays !== null && spanDays === logged;
    const firstW = span("nutrition_overview.nutrition_trend[0].date", dayInWords(first, { weekday: false }));
    const latestW = span(n.latest_date ? "nutrition_overview.nutrition.latest_date" : "nutrition_overview.nutrition_trend[last].date", dayInWords(latest));
    let e = every
      ? `He logged food every day from ${firstW} to ${latestW} — ${span("nutrition_overview.nutrition.days_logged", String(logged))} days`
      : `He logged food on ${span("nutrition_overview.nutrition.days_logged", String(logged))}${spanDays !== null ? ` of the ${span("nutrition_overview.nutrition_trend[0].date → nutrition.latest_date", String(spanDays))} days from ${firstW} to ${latestW}` : " days"}`;
    if (num(n.avg_calories) !== null) e += ` — averaging ${span("nutrition_overview.nutrition.avg_calories", fmtInt(n.avg_calories))} calories`;
    if (num(n.avg_protein_g) !== null) e += `${num(n.avg_calories) !== null ? " and" : " — averaging"} ${span("nutrition_overview.nutrition.avg_protein_g", fmtInt(n.avg_protein_g))} g of protein`;
    e += ".";
    if (num(n.protein_floor_g) !== null && num(n.protein_floor_hit_days) !== null) {
      e += ` The ${span("nutrition_overview.nutrition.protein_floor_g", fmtInt(n.protein_floor_g))} g protein floor was cleared on ${span("nutrition_overview.nutrition.protein_floor_hit_days", String(n.protein_floor_hit_days))} of those ${span("nutrition_overview.nutrition.days_logged", String(logged))} days.`;
    }
    if (n.avg_deficit_published === false) e += ` <span${src("nutrition_overview.nutrition.avg_deficit_published")}>The site does not publish a calorie deficit: its estimate is larger than it is willing to vouch for.</span>`;
    else if (num(n.avg_deficit) !== null) e += ` Its average deficit reads ${span("nutrition_overview.nutrition.avg_deficit", fmtInt(n.avg_deficit))} calories a day.`;
    out.push(`<p><span class="v7h-k">Eating</span>${e}</p>`);
  }
  // Training
  const t = (training && training.training) || {};
  const w = (training && training.walking) || {};
  const lifts = num(t.strength_sessions_30d);
  const walks = num(w.total_walks_30d);
  let tr = "";
  // #4370: the window the counts were taken over, never a flat 30 the experiment lacks
  // ("in the 22 days since the experiment began" before Day 30). No served window → no window named.
  const tw = servedWindow(t, 30);
  const wsp = tw ? ` ${tw.full ? `in the last ${span("training_overview.training.window_days", "30")} days` : `in the ${span("training_overview.training.window_days", String(tw.days))} day${tw.days === 1 ? "" : "s"} since the experiment began`}` : "";
  if (lifts !== null) tr += `${span("training_overview.training.strength_sessions_30d", countWord(lifts, { capital: true }))} lifting session${lifts === 1 ? "" : "s"}${wsp}, by the strength-session count`;
  if (walks !== null) tr += `${tr ? ", and " : ""}${span("training_overview.walking.total_walks_30d", countWord(walks))} walk${walks === 1 ? "" : "s"}${tr ? "" : wsp}`;
  if (tr) tr += ".";
  const sessions = (training && training.cardio_sessions) || [];
  if (sessions.length && sessions[0].date) {
    const day = sessions[0].date;
    const same = sessions.filter((x) => x.date === day && num(x.minutes) !== null);
    const named = same.map((x, i) => {
      const mins = Math.round(x.minutes);
      const what = String(x.sport || "session").toLowerCase();
      const dist = num(x.distance_mi) !== null ? ` (${fmt1(x.distance_mi)} miles)` : "";
      const body = mins === 60 ? `an hour ${/walk/.test(what) ? "walking" : `on the ${what}`}${dist}` : `${/walk/.test(what) ? `a ${mins}-minute walk` : `${mins} minutes of ${what}`}${dist}`;
      return `<span${src(`training_overview.cardio_sessions[${i}].{sport,minutes,distance_mi}`)}>${esc(body)}</span>`;
    });
    if (named.length) {
      const list = named.length > 1 ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}` : named[0];
      tr += ` ${esc(weekdayOf(day))}: ${list}.`;
    }
  }
  const lift = pulse && pulse.pulse && pulse.pulse.glyphs && pulse.pulse.glyphs.lift;
  const today = pulse && pulse.pulse && pulse.pulse.date;
  if (lift && lift.label && today) tr += ` <span${src("pulse.glyphs.lift.label")}>${esc(weekdayOf(today))}: ${esc(String(lift.label).toLowerCase())}.</span>`;
  const steps = num(w.avg_daily_steps);
  if (steps !== null) {
    const sn = num(w.avg_daily_steps_n);
    tr += ` ${steps < 5000 ? "Steps are the weak spot: " : "Steps: "}${span("training_overview.walking.avg_daily_steps", fmtInt(steps))} a day${sn !== null ? `, averaged over ${span("training_overview.walking.avg_daily_steps_n", String(sn))} days` : ""}.`;
  }
  out.push(`<p><span class="v7h-k">Training</span>${tr || "No training figures are served."}</p>`);
  return out.join("");
}

// ── also on the record ─────────────────────────────────────────────────────────
export function recordBlock(calibration, wrong, predictions, freshness, pulse) {
  const items = [];
  // Two counts that disagree, per coach, both left up (R5 §d: no house jargon — "count", not "scorekeeper").
  const cal = (calibration && calibration.coaches) || [];
  const byCoach = (wrong && wrong.predictions && wrong.predictions.by_coach) || [];
  cal.forEach((c) => {
    const w = byCoach.find((x) => x.coach === c.coach_id);
    if (!w || num(c.n) === null || num(c.confirmed) === null) return;
    const wn = num(w.confirmed) !== null && num(w.refuted) !== null ? w.confirmed + w.refuted : null;
    if (wn === null || (wn === c.n && w.confirmed === c.confirmed)) return;
    items.push(
      `<li><b>${esc(c.coach_name)}, the ${esc(coachField(c.coach_id))} coach: <span${src(`calibration.coaches[${c.coach_id}].{confirmed,n}`)}>${c.confirmed} of ${c.n}</span></b> checked calls right so far, by one of the site’s two counts. The other says <span${src(`wrong.predictions.by_coach[${c.coach_id}].{confirmed,refuted}`)}>${w.confirmed} of ${wn}</span>. The two disagree, and both are left up.</li>`,
    );
  });
  const life = predictions && predictions.commitments && predictions.commitments.lifetime;
  if (life && num(life.unresolved) !== null) {
    let s = `<li><b>${span("predictions.commitments.lifetime.unresolved", fmtInt(life.unresolved))} asks expired</b> with no follow-up from the coach who made them, over the whole record.`;
    if (num(life.graded) !== null && num(life.kept) !== null) s += ` Of the ${span("predictions.commitments.lifetime.graded", fmtInt(life.graded))} that were checked, he kept ${span("predictions.commitments.lifetime.kept", fmtInt(life.kept))}.`;
    items.push(`${s}</li>`);
  }
  // What he skips, counted.
  const skips = [];
  const jg = pulse && pulse.pulse && pulse.pulse.glyphs && pulse.pulse.glyphs.journal;
  if (jg && num(jg.gap_days) !== null && jg.gap_days > 0) skips.push(`journal ${span("pulse.glyphs.journal.gap_days", String(jg.gap_days))} days`);
  const sources = (freshness && freshness.sources) || [];
  const plain = { cgm: "blood-sugar sensor", blood_pressure: "blood pressure", state_of_mind: "state of mind" };
  // The order is C's: what he skips himself first (the dark data types), then what the
  // platform paused — whatever order the sources are served in.
  sources.forEach((s) => {
    (s.dark_datatypes || []).forEach((d) => {
      const key = (s.datatypes || []).find((x) => x.label === d.label);
      const name = plain[key && key.key] || String(d.label || "").toLowerCase();
      if (num(d.days_dark) !== null) skips.push(`${esc(name)} ${span(`source_freshness.sources[${s.id}].dark_datatypes[${d.label}].days_dark`, String(Math.round(d.days_dark)))} days`);
    });
  });
  sources.forEach((s) => {
    if (s.status === "paused" && s.last_update && freshness.pacific_today) {
      const days = dayNum(freshness.pacific_today) - dayNum(s.last_update);
      skips.push(`${esc(s.label)} ${span(`source_freshness.sources[${s.id}].last_update`, String(days))} days, paused by the platform, not by him`);
    }
  });
  if (skips.length) items.push(`<li><b>What he skips, counted:</b> ${skips.join(" · ")}.</li>`);
  return items.length ? `<ul class="v7h-refuse">${items.join("")}</ul>` : '<p class="v7h-note">Nothing else is on the record yet.</p>';
}

// ── how it works ───────────────────────────────────────────────────────────────
export function howBlock(freshness, coaches, receipts, subs) {
  const sum = (freshness && freshness.summary) || {};
  const out = [];
  if (num(sum.total) !== null) {
    let s = `${span("source_freshness.summary.total", countWord(sum.total, { capital: true }))} devices and apps are wired in — a scale, a wrist strap, a bed sensor, a food log, a lifting log, his phone`;
    if (num(sum.fresh) !== null) {
      s += ` — and ${span("source_freshness.summary.fresh", countWord(sum.fresh))} reported this week`;
      const tail = [];
      if (num(sum.stale) !== null && sum.stale > 0) tail.push(`${span("source_freshness.summary.stale", countWord(sum.stale))} ${sum.stale === 1 ? "is" : "are"} stale`);
      if (num(sum.paused) !== null && sum.paused > 0) tail.push(`${span("source_freshness.summary.paused", countWord(sum.paused))} ${sum.paused === 1 ? "is" : "are"} paused`);
      if (tail.length) s += `; ${tail.join(" and ")}`;
    }
    out.push(`${s}.`);
  }
  out.push("Every figure on this page is computed by code, not by an AI, and carries its date and its count.");
  const cc = coaches && num(coaches.count);
  out.push(`${cc !== null && cc !== undefined ? span("coaches.count", countWord(cc, { capital: true })) : "The"} AI coaches read those figures each morning and write to him; every dated claim they make is graded later by code against the data, and the misses stay on the record.`);
  out.push("An AI drafts the weekly write-up and Matthew reviews it before it publishes.");
  const usd = receipts && num(receipts.month_to_date_usd);
  if (usd !== null && usd !== undefined) {
    const month = receipts.as_of ? new Date(Date.parse(receipts.as_of)).toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "long" }) : "this month";
    let s = `Running all of it has cost ${span("receipts.month_to_date_usd", `$${usd.toFixed(2)}`, "num")} so far in ${month}`;
    if (subs && subs.available !== false && num(subs.count) !== null) s += `, for ${span("sub_count.count", countWord(subs.count))} subscriber${subs.count === 1 ? "" : "s"}`;
    out.push(`${s}.`);
  }
  return `<p>${out.join(" ")}</p><p class="v7h-note">The code, in full: <a href="https://github.com/averagejoematt/life-platform" rel="noopener">github.com/averagejoematt/life-platform</a></p>`;
}

// The next weigh-in, in the ONE spelling every v7 page uses (entry_age.nextWeighInText, R6 fix 4):
// due when the day after the last weigh-in is on or after the page's data-through day, else
// the silence since, counted — never a past day as "due". `through` is the page's data-through
// (injectable for the tests); the day is wrapped in <time> naming the served field.
export function nextWeighinText(journey, through = todayPT()) {
  const r = nextWeighInText(journey && journey.last_weighin_date, through);
  if (!r.text) return "";
  return r.text.replace(dayInWords(r.day), time(r.day, "journey.last_weighin_date"));
}

// ── what resolves next ─────────────────────────────────────────────────────────
const METRIC_WORDS = {
  recovery_score: "the night’s recovery",
  recovery_score_7day_avg: "the seven-night average recovery",
  sleep_duration_hours: "the night’s sleep, in hours",
  total_sleep_hours: "the night’s sleep, in hours",
  hrv: "heart-rate variability",
  weight_lbs: "his weight",
};
const COND_WORDS = { lt: "under", lte: "at or under", gt: "over", gte: "or better", eq: "exactly" };
function criterionWords(c) {
  if (!c || !c.metric || num(c.threshold) === null) return "";
  const m = METRIC_WORDS[c.metric];
  if (!m) return "";
  const cond = COND_WORDS[c.condition] || "";
  if (!cond) return "";
  return c.condition === "gte" ? `${m} reads ${c.threshold} ${cond}` : `${m} reads ${cond} ${c.threshold}`;
}

export function nextRows(docket, predictions, cadence, journey, coaches) {
  const rows = [];
  const due = predictions && predictions.overall && predictions.overall.due;
  if (due && due.earliest_due) rows.push({ date: due.earliest_due, src: "predictions.overall.due.earliest_due", html: `<td${src("predictions.overall.due.earliest_due")}>The next graded call of any kind comes due. Graded by code.</td>` });
  (Array.isArray(docket) ? docket : []).forEach((d, i) => {
    if (!d || !d.resolution_date) return;
    const a = d.coach_a;
    const b = d.coach_b;
    const sides = d.sides || {};
    const yes = sides[a] === true ? a : sides[b] === true ? b : null;
    const no = yes === a ? b : a;
    const words = criterionWords(d.criterion);
    let text = "";
    if (yes && words) text = `${esc(coachName(coaches, yes))} says ${words} that day; ${esc(coachName(coaches, no))} says it won’t.`;
    else text = `${esc(coachName(coaches, a))} and ${esc(coachName(coaches, b))} disagree${d.topic ? ` on ${esc(String(d.topic).replace(/:.*$/, "").toLowerCase())}` : ""}.`;
    rows.push({ date: d.resolution_date, src: `coach_docket.open[${i}].resolution_date`, html: `<td${src(`coach_docket.open[${i}]`)}>${text} Graded by code.</td>` });
  });
  const ch = cadence && cadence.chronicle;
  if (ch && !ch.paused && ch.next_date) rows.push({ date: ch.next_date, src: "content_cadence.chronicle.next_date", html: `<td${src("content_cadence.chronicle.next_date")}>The next write-up — drafted that day, published once Matthew has read it.</td>` });
  const j = journey || {};
  if (num(j.day_n) !== null && j.day_n < HORIZON && j.started_date) rows.push({ date: isoPlus(j.started_date, HORIZON - 1), src: "journey.started_date + 29 days", html: `<td${src("journey.started_date + 29 days")}>Day ${HORIZON} — and the next photo.</td>` });
  rows.sort((x, y) => String(x.date).localeCompare(String(y.date)));
  return rows;
}

export function nextBlock(docket, predictions, cadence, journey, coaches, through = todayPT()) {
  const rows = nextRows(docket, predictions, cadence, journey, coaches);
  if (!rows.length) {
    const nw = nextWeighinText(journey, through);
    return `<p class="v7h-note">Nothing is on the docket and no graded call is due.${nw ? ` ${nw.charAt(0).toUpperCase()}${nw.slice(1)}.` : ""}</p>`;
  }
  const body = rows.map((r) => `<tr><td class="v7h-td-d"${src(r.src)}><time datetime="${esc(r.date)}">${esc(dayLabel(r.date))}</time></td>${r.html}</tr>`).join("");
  return `<table><thead><tr><th>When</th><th>What</th></tr></thead><tbody>${body}</tbody></table>`;
}

// ── follow ─────────────────────────────────────────────────────────────────────
export function followBlock(subs, cadence, journey, through = todayPT()) {
  let count = "The subscriber count is not available right now.";
  if (subs && subs.available !== false && num(subs.count) !== null) {
    count = subs.count === 0 ? "No subscribers yet." : subs.count === 1 ? "One subscriber so far." : `${subs.count.toLocaleString("en-US")} subscribers so far.`;
  }
  const parts = [`<span${src("sub_count.count")}>${esc(count)}</span>`];
  const ch = cadence && cadence.chronicle;
  const next = ch && !ch.paused && ch.next_date ? `The next write-up is ${time(ch.next_date, "content_cadence.chronicle.next_date")}` : "The next write-up is not yet scheduled";
  const nw = nextWeighinText(journey, through);
  parts.push(`${next}${nw ? `; ${nw}` : ""}.`);
  parts.push('<a href="mailto:matt@averagejoematt.com">matt@averagejoematt.com</a>');
  return `<p>${parts.join(" ")}</p>`;
}

// ── the margins ────────────────────────────────────────────────────────────────
export function marginParts(iso) {
  const w = dayInWords(iso);
  if (!w) return null;
  const [weekday, md] = w.split(", ");
  const [month, day] = (md || "").split(" ");
  return { d: day || "", mo: (month || "").slice(0, 3), w: weekday || "" };
}

function setMargin(entry, parts, path) {
  if (!entry || !parts) return;
  const m = entry.querySelector(".v7h-m");
  if (!m) return;
  if (path) m.setAttribute("data-src", path);
  m.querySelector(".v7h-d").textContent = parts.d;
  m.querySelector(".v7h-mo").textContent = parts.mo;
  m.querySelector(".v7h-w").textContent = parts.w;
}

// ── mount ──────────────────────────────────────────────────────────────────────
const put = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};

export async function mount() {
  const main = document.getElementById("main");
  if (!main || !document.getElementById("v7h-fold")) return;
  main.classList.add("v7h");
  const [journeyR, progressR, calibration, cadence, decisions, pulse, sleep, vitals, nutrition, training, predictions, freshness, coachesR, receipts, subs, docketR, wrong, postsR] =
    await Promise.all([
      tryJSON("/api/journey"),
      tryJSON("/api/weight_progress"),
      tryJSON("/api/calibration"),
      tryJSON("/api/content_cadence"),
      tryJSON("/api/decisions"),
      tryJSON("/api/pulse"),
      tryJSON("/api/sleep_detail"),
      tryJSON("/api/vitals"),
      tryJSON("/api/nutrition_overview"),
      tryJSON("/api/training_overview"),
      tryJSON("/api/predictions"),
      tryJSON("/api/source_freshness"),
      tryJSON("/api/coaches"),
      tryJSON("/api/receipts"),
      tryJSON("/api/sub_count"),
      tryJSON("/api/coach_docket"),
      tryJSON("/api/wrong"),
      tryJSON("/journal/posts.json"),
    ]);
  const journey = (journeyR && journeyR.journey) || null;
  const progress = (progressR && progressR.weight_progress) || [];
  const coaches = (coachesR && coachesR.coaches) || [];
  const docket = (docketR && docketR.open) || [];
  const posts = (postsR && postsR.posts) || [];
  const through = (vitals && vitals.vitals && vitals.vitals.as_of_date) || (journey && journey.last_weighin_date) || "";
  const throughSrc = vitals && vitals.vitals && vitals.vitals.as_of_date ? "vitals.as_of_date" : "journey.last_weighin_date";

  // the fold
  const cap = photoCaption(journey);
  if (cap) put("v7h-photo-cap", cap);
  put("v7h-number", journey ? numberBlock(journey) + thisWeekLine(progress, posts) : pending("The latest weigh-in"));
  put("v7h-lead", journey ? leadSentence(journey, coachesR && coachesR.count) : pending("The lead"));
  put("v7h-alive", aliveLine(through, calibration, cadence, throughSrc));
  setMargin(document.getElementById("v7h-fold"), marginParts(journey && journey.last_weighin_date), "journey.last_weighin_date");

  // the entries
  put("v7h-weighins-body", weighinsBlock(progress, journey));
  const wm = marginParts(journey && journey.started_date);
  if (wm) setMargin(document.getElementById("v7h-weighins"), { d: wm.d, mo: wm.mo, w: "to today" }, "journey.started_date");
  put("v7h-words-body", wordsBlock(decisions && decisions.decisions, pulse));
  const notes = ((decisions && decisions.decisions) || []).filter((d) => d && d.note);
  if (notes.length) setMargin(document.getElementById("v7h-words"), marginParts(notes[0].note_at ? instantDayInWords(notes[0].note_at) && new Date(Date.parse(notes[0].note_at)).toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" }) : notes[0].date), `decisions[0].${notes[0].note_at ? "note_at" : "date"}`);
  put("v7h-okay-body", okayBlock(sleep, vitals, nutrition, training, pulse));
  setMargin(document.getElementById("v7h-okay"), marginParts(through), throughSrc);
  put("v7h-record-body", recordBlock(calibration, wrong, predictions, freshness, pulse));
  setMargin(document.getElementById("v7h-record"), marginParts(through), throughSrc);
  put("v7h-how-body", howBlock(freshness, coachesR, receipts, subs));
  setMargin(document.getElementById("v7h-how"), { d: "§", mo: "how", w: "it works" });
  put("v7h-next-body", nextBlock(docket, predictions, cadence, journey, coaches, through));
  const rows = nextRows(docket, predictions, cadence, journey, coaches);
  if (rows.length) setMargin(document.getElementById("v7h-next"), marginParts(rows[0].date), rows[0].src);
  put("v7h-follow-body", followBlock(subs, cadence, journey, through));
  setMargin(document.getElementById("v7h-follow"), { d: "→", mo: "next", w: "page" });
}

if (typeof document !== "undefined" && typeof document.getElementById === "function") {
  try {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => mount());
    else mount();
  } catch (e) {
    /* a shim without a DOM (scripts/import_site_js_graph.mjs) — nothing to mount */
  }
}
