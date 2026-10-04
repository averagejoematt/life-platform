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

// "Level 16. Score 84 of 100, down 0.6 on the day."
export function areaLine(p) {
  if (!p) return "";
  if (p.not_instrumented) return "Not measured yet: nothing records this area.";
  const level = num(p.level);
  const score = num(p.raw_score);
  if (level === null || score === null) return "Not served right now.";
  const d = num(p.score_delta);
  const move = d === null || Math.abs(d) < 0.05 ? "level on the day" : d > 0 ? `up ${d.toFixed(1)} on the day` : `down ${(-d).toFixed(1)} on the day`;
  return `Level ${whole(level)}. Score ${whole(score)} of 100, ${move}.`;
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
export function areasHTML(body) {
  const pillars = ((body && body.pillars) || []).filter((p) => p && p.name);
  if (!pillars.length) return soft("The seven areas are not served right now.");
  return `<ul class="ck-coach">${pillars
    .map((p) => `<li><span class="ck-coach__who">${esc(AREAS[p.name] || p.name)}</span><span>${esc(areaLine(p))}${areaDetail(p) ? ` <span class="ck-soft">${esc(areaDetail(p))}</span>` : ""}</span></li>`)
    .join("")}</ul>`;
}
// The one level, with how many areas it was worked out from and the day it is for.
export function levelHTML(body) {
  const c = body && body.character;
  if (!c || num(c.level) === null) return soft("The level is not served right now.");
  const day = dayInWords(c.as_of_date);
  const [n, of] = [num(c.composite_pillar_count), num(c.composite_pillar_total)];
  const from = n !== null && of !== null ? `Worked out from ${n} of ${of} areas${n < of ? "; an area with nothing measuring it is left out, not counted as average" : ""}.` : "";
  return `<div class="ck-today"><p class="ck-big">${esc(whole(c.level))}<span>level${day ? ` on ${esc(day)}` : ""}</span></p>${soft(from)}</div>`;
}
// "Level 10 across seven areas" — the front page's one line, a door to this page.
export function sheetLine(body) {
  const c = body && body.character;
  if (!c || num(c.level) === null) return "";
  const of = num(c.composite_pillar_total);
  return `Level ${whole(c.level)}${of !== null ? ` across ${of === 7 ? "seven" : of} areas of his life` : ""}`;
}
export function badgesHTML(body) {
  const all = ((body && body.achievements) || []).filter((a) => a && a.label);
  if (!all.length) return soft("The badges are not served right now.");
  const earned = all.filter((a) => a.earned && a.earned_date).sort((a, b) => String(b.earned_date).localeCompare(String(a.earned_date)));
  if (!earned.length) return soft(`None of the ${all.length} badges has been earned yet.`);
  // A badge whose description only repeats its name ("Lost 10 lbs" / "Lost 10 lbs from
  // starting weight") prints the description alone.
  const rows = earned
    .map((a) => {
      const desc = String(a.description || "");
      const repeats = desc.toLowerCase().startsWith(String(a.label).toLowerCase());
      const text = repeats ? esc(`${desc}.`) : `${esc(a.label)}${desc ? ` <span class="ck-soft">${esc(desc)}.</span>` : ""}`;
      return `<li><span class="ck-rows__key">${esc(shortDay(a.earned_date))}</span><span>${text}</span></li>`;
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
  const note = character && character.input_manifest && character.input_manifest.complete === false ? "Some sources were late when this was worked out, so today’s numbers may move." : "";
  fill("ck-sheet-note", small(note));
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
