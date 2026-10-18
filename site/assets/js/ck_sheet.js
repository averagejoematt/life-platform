// ck_sheet.js — the character sheet, presented plainly (#4586, epic #4580).
//
// The owner kept the character sheet and the badges as a feature (2026-10-04). The research
// behind the redesign found no evidence that a game layer interests onlookers, so this page
// carries no game chrome: it is seven areas of his life, each a level worked out from the
// record, with what is helping, what is holding it back and what is not measured. A level
// can go down, and the page says so. Badges are the earned ones only, each with its date.
//
// Pure builders, exported for tests/js/ck_sheet_4586.test.mjs; mount() touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const soft = (text) => (text ? `<p class="ck-soft">${esc(text)}</p>` : "");
const small = (text) => (text ? `<p class="ck-small">${esc(text)}</p>` : "");
const whole = (v) => String(Math.round(v));
const shortDay = (iso) => dayInWords(iso, { weekday: false });
const listWords = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

// The seven areas in a reader's words, keyed on the served name.
export const AREAS = { sleep: "Sleep", movement: "Training", nutrition: "Food", metabolic: "Metabolic health", mind: "Mind", relationships: "Relationships", consistency: "Consistency" };
// What each served driver is, in plain words. A driver that is not here prints its own
// name with the underscores removed — never a blank.
const DRIVERS = {
  duration_vs_target: "sleep length",
  deep_sleep_pct: "deep sleep",
  rem_pct: "dream sleep",
  efficiency: "time asleep while in bed",
  onset_consistency: "a steady bedtime",
  strength_sessions: "strength sessions",
  training_frequency: "how often he trains",
  zone2_adequacy: "easy cardio minutes",
  training_load_balance: "training load balance",
  progressive_overload: "lifts going up over time",
  movement_diversity: "variety of training",
  daily_steps: "daily steps",
  body_composition_progress: "body composition",
  calorie_adherence: "calories against the plan",
  protein_total: "protein",
  protein_distribution: "protein across meals",
  consistency: "logging food every day",
  resting_heart_rate: "resting heart rate",
  cgm_glucose_control: "blood sugar from a sensor",
  lab_biomarkers: "blood tests",
  blood_pressure: "blood pressure",
  stress_management: "stress",
  journal_consistency: "journaling",
  reading_practice: "reading",
  t0_habit_compliance: "the core daily habits",
  t1_habit_compliance: "the second-tier habits",
  state_of_mind_valence: "logged mood",
  vice_control: "the habits he is cutting",
  values_alignment: "living by his stated values",
  data_completeness: "complete data",
  weekend_weekday_stability: "weekends matching weekdays",
  cross_pillar_variance: "evenness across the areas",
  streak_maintenance: "unbroken streaks",
};
export const driverWords = (ids) => (ids || []).map((id) => DRIVERS[id] || String(id).replace(/_/g, " "));

// The sentence after the level: "Score 80.5 of 100, down 0.5 on the day." The score and its
// move share one precision (one decimal, as served), so the move can be read off the score
// from one day to the next; a whole score beside a tenth of a point could not (#4580 round 1).
export function areaSentence(p) {
  if (!p) return "";
  if (p.not_instrumented) return "Not measured yet: nothing records this area.";
  const level = num(p.level);
  const score = num(p.raw_score);
  if (level === null || score === null) return "Not served right now.";
  // An area held for thin coverage has a score built from a sliver of its inputs; printing
  // it beside a fully measured area's score reads as a contradiction.
  if (p.coverage_hold) return "Too little of this area is measured to score it yet.";
  const d = num(p.score_delta);
  const move = d === null || Math.abs(d) < 0.05 ? "level on the day" : d > 0 ? `up ${d.toFixed(1)} on the day` : `down ${(-d).toFixed(1)} on the day`;
  return `Score ${score.toFixed(1)} of 100, ${move}.`;
}
// "Level 22" — the row's right-hand figure; empty for an area nothing measures.
export function areaLevel(p) {
  if (!p || p.not_instrumented) return "";
  const level = num(p.level);
  return level === null || num(p.raw_score) === null ? "" : `Level ${whole(level)}`;
}
// "Level 16. Score 84 of 100, down 0.6 on the day." — the two together, one line.
export function areaLine(p) {
  if (!p) return "";
  const lv = areaLevel(p);
  return lv ? `${lv}. ${areaSentence(p)}` : areaSentence(p);
}
export function areaDetail(p) {
  if (!p || p.not_instrumented) return "";
  const dr = p.drivers || {};
  const parts = [];
  if ((dr.top || []).length) parts.push(`Helping: ${listWords(driverWords(dr.top))}.`);
  if ((dr.dragging || []).length) parts.push(`Holding it back: ${listWords(driverWords(dr.dragging))}.`);
  if ((dr.absent || []).length) parts.push(`Not done or not logged: ${listWords(driverWords(dr.absent))}.`);
  if ((dr.no_data || []).length) parts.push(`No data yet: ${listWords(driverWords(dr.no_data))}.`);
  return parts.join(" ");
}
// The row's one plain sentence about the drivers: the biggest helper and the biggest drag,
// nothing more. The four-bucket list (areaDetail) read as a formula dump in every row.
export function areaBrief(p) {
  if (!p || p.not_instrumented || p.coverage_hold) return "";
  const dr = p.drivers || {};
  const top = driverWords(dr.top || [])[0];
  const drag = driverWords(dr.dragging || [])[0];
  if (top && drag) return `Helped most by ${top}; held back most by ${drag}.`;
  if (top) return `Helped most by ${top}.`;
  if (drag) return `Held back most by ${drag}.`;
  return "";
}
// The kit's record row, one per area: name, level at the right, one plain sentence under.
export function areasHTML(body) {
  const pillars = ((body && body.pillars) || []).filter((p) => p && p.name);
  if (!pillars.length) return soft("The seven areas are not served right now.");
  return `<ul class="ck-coach ck-coach--record">${pillars
    .map((p) => {
      const line = [areaSentence(p), areaBrief(p)].filter(Boolean).join(" ");
      const lv = areaLevel(p);
      return `<li><span class="ck-coach__name">${esc(AREAS[p.name] || p.name)}</span><span class="ck-coach__job">${esc(line)}</span>${lv ? `<span class="ck-coach__record">${esc(lv)}</span>` : ""}</li>`;
    })
    .join("")}</ul>`;
}
// An area held for thin data is still averaged into the level (character.composite_note
// excludes only the uninstrumented area). The page says so beside the level; taking a held
// area out of the composite is an engine change and the owner's call (#4580 round 1, sheet-3).
export function compositeNote(body) {
  const held = ((body && body.pillars) || []).filter((p) => p && p.name && p.coverage_hold && !p.not_instrumented).map((p) => AREAS[p.name] || p.name);
  if (!held.length) return "";
  const names = listWords(held);
  return `${names} ${held.length > 1 ? "are" : "is"} on hold for thin data, yet ${held.length > 1 ? "their scores" : "its score"} still count${held.length > 1 ? "" : "s"} toward the level.`;
}
// The one level, with how many areas it was worked out from and the day it is for.
export function levelHTML(body) {
  const c = body && body.character;
  if (!c || num(c.level) === null) return soft("The level is not served right now.");
  const day = dayInWords(c.as_of_date);
  const [n, of] = [num(c.composite_pillar_count), num(c.composite_pillar_total)];
  const from = n !== null && of !== null ? `Worked out from ${n} of ${of} areas${n < of ? "; an area with nothing measuring it is left out, not counted as average" : ""}.` : "";
  return `<div class="ck-today"><p class="ck-big">${esc(whole(c.level))}<span> level${day ? ` on ${esc(day)}` : ""}</span></p>${soft(from)}</div>`;
}
// "Level 10 across seven areas" — the front page's one line, a door to this page.
export function sheetLine(body) {
  const c = body && body.character;
  if (!c || num(c.level) === null) return "";
  const [n, of] = [num(c.composite_pillar_count), num(c.composite_pillar_total)];
  const words = (v) => ({ 5: "five", 6: "six", 7: "seven" })[v] || String(v);
  // The same count the sheet itself prints: an area nothing measures is not in the level.
  const across = of === null ? "" : n !== null && n < of ? ` across ${words(n)} of ${words(of)} areas of his life` : ` across ${words(of)} areas of his life`;
  return `Level ${whole(c.level)}${across}`;
}
export function badgesHTML(body) {
  const all = ((body && body.achievements) || []).filter((a) => a && a.label);
  if (!all.length) return soft("The badges are not served right now.");
  // An earned badge whose date was never recorded is still earned: it is counted and
  // listed last as "date not recorded", never dropped and never given a made-up date (#4704).
  const earned = all.filter((a) => a.earned).sort((a, b) => String(b.earned_date || "").localeCompare(String(a.earned_date || "")));
  if (!earned.length) return soft(`None of the ${all.length} badges has been earned yet.`);
  // A badge whose description only repeats its name ("Lost 10 lbs" / "Lost 10 lbs from
  // starting weight") prints the name alone.
  const rows = earned
    .map((a) => {
      const desc = String(a.description || "");
      const repeats = desc.toLowerCase().startsWith(String(a.label).toLowerCase());
      const text = repeats ? esc(a.label) : `${esc(a.label)}${desc ? ` <span class="ck-soft">${esc(desc)}.</span>` : ""}`;
      const when = a.earned_date ? esc(shortDay(a.earned_date)) : "date not recorded";
      return `<li><span class="ck-rows__key">${when}</span><span>${text}</span></li>`;
    })
    .join("");
  return `${soft(`${earned.length} of ${all.length} earned so far.`)}<ul class="ck-rows">${rows}</ul>`;
}

const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
};
export async function mount() {
  if (!document.body || document.body.dataset.ckPage !== "sheet") return;
  const base = document.body.dataset.ckBase || "/";
  const [character, achievements] = await Promise.all([tryJSON("/api/character"), tryJSON("/api/achievements")]);
  fill("ck-level", levelHTML(character));
  fill("ck-areas", areasHTML(character));
  fill("ck-badges", badgesHTML(achievements));
  fill("ck-sheet-note", small(compositeNote(character)));
  // The late-sources caveat sits under the areas, not stacked under the level with the hold note.
  const note = character && character.input_manifest && character.input_manifest.complete === false ? "Some sources were late when this was worked out, so today’s numbers may move." : "";
  fill("ck-sheet-late", small(note));
  const back = document.getElementById("ck-back");
  try {
    const ref = document.referrer ? new URL(document.referrer) : null;
    if (back && ref && ref.origin === location.origin && ref.pathname.startsWith(base)) back.href = ref.pathname + ref.search;
  } catch (_e) {
    /* a malformed referrer keeps the default back link */
  }
  document.body.dataset.ckReady = "1";
}
if (typeof document !== "undefined") mount();
