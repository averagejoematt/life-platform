// v7_week.js — the v7 "This week" page (#4182, plan §2a row 3; Prototype C screen III).
//
// One page, five entries, every number served: the latest write-up (title verbatim,
// the day in words, the word count, the weight that week from its own stat line, the
// opening lines cleaned by chronicle_text.js so the bracketed stat line never prints),
// the two before it with the prologue folded, the week so far (weight since the
// write-up, this calendar week's training, the last three mornings' recovery, the
// journal), his testimony (honest-empty until he answers a note), and what comes next
// (the write-up from /api/content_cadence — a held draft's own words win — the panel
// episode from its pending marker, the next bet on the docket, the next weigh-in).
//
// The pure helpers are exported and unit-tested (tests/js/v7_week.test.mjs); every one
// takes its inputs explicitly so no test reads the wall clock. Dates in words come from
// entry_age.js — the one spelling every v7 page uses. Every rendered figure carries a
// data-src naming the served field it came from.
import { cleanExcerpt } from "/assets/js/chronicle_text.js";
import { dayInWords, dayLabel, dataThrough, nextWriteUpText } from "/assets/js/entry_age.js";

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const num = (v, dp) => (Number.isFinite(Number(v)) ? Number(v).toLocaleString("en-US", { minimumFractionDigits: dp || 0, maximumFractionDigits: dp || 0 }) : "");
const iso = (s) => String(s || "").slice(0, 10);
const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(iso(s));
const utcNoon = (d) => Date.parse(`${iso(d)}T12:00:00Z`);

/** The margin of an entry, from a served date: { d: "22", mo: "Sep", w: "Tuesday" }. Nulls when unusable. */
export function marginParts(dateStr) {
  const lab = dayLabel(dateStr); // "Tue Sep 22"
  if (!lab) return null;
  const [, mo, d] = lab.split(" ");
  const w = dayInWords(dateStr).split(",")[0];
  return { d, mo, w };
}

/** "Weight: 315.0 lbs | …" → 315.0 (a number); null when the line carries no weight. */
export function weightThatWeek(statsLine) {
  const m = /Weight:\s*([\d.]+)\s*lbs?/i.exec(String(statsLine || ""));
  return m ? Number(m[1]) : null;
}

/** The instalments (week ≥ 1) newest first, and the prologue (week 0) newest first. */
export function splitPosts(posts) {
  const all = Array.isArray(posts) ? posts.filter((p) => p && isIso(p.date)) : [];
  const bySeq = (a, b) => utcNoon(b.date) - utcNoon(a.date) || Number(b.sequence || 0) - Number(a.sequence || 0);
  return {
    instalments: all.filter((p) => Number(p.week) >= 1).sort(bySeq),
    prologue: all.filter((p) => !(Number(p.week) >= 1)).sort(bySeq),
  };
}

/** The opening lines of a post, as served: the quoted title and the bracketed stat line dropped. */
export function openingLines(post) {
  if (!post) return "";
  return cleanExcerpt(post.excerpt, post.title).split(/\n\s*\n/)[0].trim();
}

/** ISO-8601 week key ("2026-W39") of a YYYY-MM-DD, pinned to UTC noon. "" when unusable. */
export function isoWeekKey(dateStr) {
  if (!isIso(dateStr)) return "";
  const d = new Date(utcNoon(dateStr));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const y = d.getUTCFullYear();
  const wk = Math.ceil(((d - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7);
  return `${y}-W${String(wk).padStart(2, "0")}`;
}

/** YYYY-MM-DD plus n days. */
export function plusDays(dateStr, n) {
  if (!isIso(dateStr)) return "";
  return new Date(utcNoon(dateStr) + n * 86400000).toISOString().slice(0, 10);
}

/** Weight since the write-up: the last weigh-in on or before the post's date, and the latest after it.
 *  { from: {date, weight_lbs}, to: {…} } — `to` null when nothing has been weighed since. */
export function sinceWriteUp(weights, postDate) {
  const ws = (Array.isArray(weights) ? weights : []).filter((w) => w && isIso(w.date) && w.weight_lbs != null && Number.isFinite(Number(w.weight_lbs)));
  if (!ws.length || !isIso(postDate)) return null;
  ws.sort((a, b) => utcNoon(a.date) - utcNoon(b.date));
  const before = ws.filter((w) => utcNoon(w.date) <= utcNoon(postDate));
  const after = ws.filter((w) => utcNoon(w.date) > utcNoon(postDate));
  const from = before.length ? before[before.length - 1] : null;
  const to = after.length ? after[after.length - 1] : null;
  if (!from && !to) return null;
  return { from, to };
}

/** This calendar week's row of /api/training_overview.weekly_trend, by the ISO week of `today`. */
export function thisWeekTraining(weeklyTrend, today) {
  const key = isoWeekKey(today);
  if (!key) return null;
  return (Array.isArray(weeklyTrend) ? weeklyTrend : []).find((r) => r && r.week === key) || null;
}

/** The last n nights with a recovery reading, oldest first: [{date, recovery_score}]. */
export function lastMornings(sleepTrend, n = 3) {
  const rows = (Array.isArray(sleepTrend) ? sleepTrend : []).filter((r) => r && isIso(r.date) && r.recovery_score != null && Number.isFinite(Number(r.recovery_score)));
  rows.sort((a, b) => utcNoon(a.date) - utcNoon(b.date));
  return rows.slice(-n).map((r) => ({ date: r.date, recovery_score: Number(r.recovery_score) }));
}

/** "86, 99 and 77" from a list of numbers. */
export function joinNumbers(list) {
  const xs = (list || []).map((v) => num(v));
  if (xs.length <= 1) return xs.join("");
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

/** The journal line from /api/pulse's journal glyph. "" when the glyph is absent. */
export function journalLine(pulse) {
  const g = pulse && pulse.pulse && pulse.pulse.glyphs && pulse.pulse.glyphs.journal;
  if (!g) return "";
  if (g.written_today) return "a journal entry today";
  const gap = Number(g.gap_days);
  if (Number.isFinite(gap) && gap > 0) return `nothing in the journal for ${gap} day${gap === 1 ? "" : "s"}`;
  return "";
}

/** His testimony from /api/field_notes: the weeks he answered, or the honest empty. */
export function testimonyLine(fieldNotes) {
  const entries = (fieldNotes && fieldNotes.entries) || [];
  const answered = entries.filter((e) => e && e.has_matthew_response);
  if (!entries.length) return { answered: [], text: "No notes have been put to him yet." };
  if (!answered.length) {
    const labels = entries.map((e) => e.week_label).filter(Boolean);
    const span = labels.length ? ` (${labels[labels.length - 1]} to ${labels[0]})` : "";
    return { answered: [], text: `None on file. The site has put ${entries.length} weekly note${entries.length === 1 ? "" : "s"} to him${span}; he has not answered one yet.` };
  }
  return { answered, text: `He answered ${answered.map((e) => e.week_label).filter(Boolean).join(", ")}.` };
}

/** The write-up line for "Next". A held draft's served words win (nextWriteUpText's rule). */
export function nextWriteUpLine(cad, pending) {
  const t = nextWriteUpText(cad, pending);
  if (!t) return "";
  const m = /^Next write-up: (.+)$/.exec(t);
  return m ? `The next write-up is drafted ${m[1]} and publishes once Matthew has read it.` : t;
}

/** The panel episode line from /panelcast/episodes.json's `pending` marker (the dispatches.js rule). */
export function panelLine(episodesJson) {
  const pending = episodesJson && episodesJson.pending;
  if (!pending) return "";
  const when = pending.expected_date ? dayInWords(pending.expected_date) : "";
  let line = when ? `The next panel episode: ${when}.` : "No next panel episode is scheduled.";
  if (!when && pending.reason === "held_for_review" && pending.week != null) line += ` Week ${pending.week}'s is held for review.`;
  return line;
}

/** The next open bet on the docket: the first `open[]` row settling on or after `today`. */
export function nextBet(docket, today, names) {
  const open = (docket && docket.open) || [];
  const rows = open.filter((b) => b && isIso(b.resolution_date) && (!isIso(today) || utcNoon(b.resolution_date) >= utcNoon(today)));
  rows.sort((a, b) => utcNoon(a.resolution_date) - utcNoon(b.resolution_date));
  const b = rows[0];
  if (!b) return null;
  const name = (id) => (names && names[id]) || String(id || "").replace(/_coach$/, "").replace(/_/g, " ");
  return { date: b.resolution_date, a: name(b.coach_a), b: name(b.coach_b), index: open.indexOf(b) };
}

/** persona_id → name from /api/coaches. */
export function coachNames(coaches) {
  const out = {};
  for (const c of (coaches && coaches.coaches) || []) if (c && c.persona_id && c.name) out[c.persona_id] = c.name;
  return out;
}

// ── rendering ────────────────────────────────────────────────────────────────
function setMargin(section, dateStr) {
  const m = section && section.querySelector("[data-margin]");
  const p = marginParts(dateStr);
  if (!m || !p) return;
  m.innerHTML = `<span class="d">${esc(p.d)}</span><span class="mo">${esc(p.mo)}</span><span class="w">${esc(p.w)}</span>`;
}

function fill(section, html) {
  if (!section) return;
  const body = section.querySelector(".wk-body");
  const h = body && body.querySelector("h2");
  if (!body) return;
  body.innerHTML = (h ? h.outerHTML : "") + html;
}

function postLine(p, i, withWeight = true) {
  const wt = weightThatWeek(p.stats_line);
  const bits = [`<time datetime="${esc(iso(p.date))}" data-src="journal_posts.posts[${i}].date">${esc(dayInWords(p.date))}</time>`];
  if (p.label) bits.push(`<span data-src="journal_posts.posts[${i}].label">${esc(String(p.label).toLowerCase())}</span>`);
  if (withWeight && wt != null) bits.push(`<span data-src="journal_posts.posts[${i}].stats_line">${esc(num(wt, 1))} lb</span>`);
  if (Number.isFinite(Number(p.word_count))) bits.push(`<span data-src="journal_posts.posts[${i}].word_count">${esc(num(p.word_count))} words</span>`);
  return bits.join(" · ");
}

function renderLatest(posts, all) {
  const sec = document.getElementById("wk-latest");
  const p = posts[0];
  if (!p) return fill(sec, '<p class="wk-note">No write-up has been published yet.</p>');
  const i = all.indexOf(p);
  const wt = weightThatWeek(p.stats_line);
  const lines = openingLines(p);
  const words = Number.isFinite(Number(p.word_count)) ? num(p.word_count) : "";
  fill(
    sec,
    `<p class="wk-dated">${postLine(p, i, false)}</p>` +
      `<p class="wk-piece" data-src="journal_posts.posts[${i}].title">${esc(p.title)}</p>` +
      `<p class="wk-note">Drafted by the site's AI writer; Matthew reads each draft before it publishes.` +
      (wt != null ? ` The number that week: <span data-src="journal_posts.posts[${i}].stats_line">${esc(num(wt, 1))}</span> lb.` : "") +
      `</p>` +
      (lines ? `<p class="wk-lines" data-src="journal_posts.posts[${i}].excerpt">${esc(lines)}</p>` : "") +
      `<p class="wk-note">Opening lines, as served. <a href="${esc(p.url || "#")}">Read the full piece${words ? ` (${esc(words)} words)` : ""} →</a></p>`,
  );
  setMargin(sec, p.date);
  const h = sec && sec.querySelector("h2");
  if (h) h.textContent = "The latest write-up";
}

function renderPreviously(posts, prologue, all) {
  const sec = document.getElementById("wk-previously");
  const prior = posts.slice(1, 3);
  let html = "";
  if (!prior.length) html += '<p class="wk-note">Nothing before this one yet.</p>';
  for (const p of prior) {
    const i = all.indexOf(p);
    html += `<p class="wk-pn" data-src="journal_posts.posts[${i}].title">${esc(p.title)}</p><p class="wk-small">${postLine(p, i)}.</p>`;
  }
  if (prologue.length) {
    const rows = prologue
      .map((p) => {
        const i = all.indexOf(p);
        const words = Number.isFinite(Number(p.word_count)) ? ` — ${num(p.word_count)} words` : "";
        return `<tr><td class="d"><time datetime="${esc(iso(p.date))}">${esc(dayLabel(p.date))}</time></td><td><a href="${esc(p.url || "#")}" data-src="journal_posts.posts[${i}].title">${esc(p.title)}</a>${esc(words)}</td></tr>`;
      })
      .join("");
    html += `<details class="wk-fold"><summary>The prologue (${prologue.length})</summary><table><tbody>${rows}</tbody></table></details>`;
  }
  fill(sec, html);
  if (prior[0]) setMargin(sec, prior[0].date);
}

function renderSoFar({ latest, weights, training, sleep, pulse, today }) {
  const sec = document.getElementById("wk-sofar");
  const bits = [];
  const since = latest ? sinceWriteUp(weights, latest.date) : null;
  if (since && since.to && since.from) {
    bits.push(
      `Since that write-up: <b><span data-src="api_weight_progress.weight_progress[].weight_lbs">${esc(num(since.to.weight_lbs, 1))}</span> lb</b> on ${esc(dayInWords(since.to.date))}, from <span data-src="api_weight_progress.weight_progress[].weight_lbs">${esc(num(since.from.weight_lbs, 1))}</span> on ${esc(dayInWords(since.from.date))}`,
    );
  } else if (since && since.from) {
    bits.push(`No weigh-in since that write-up; the last was <span data-src="api_weight_progress.weight_progress[].weight_lbs">${esc(num(since.from.weight_lbs, 1))}</span> lb on ${esc(dayInWords(since.from.date))}`);
  }
  const wk = thisWeekTraining(training && training.weekly_trend, today);
  if (wk) bits.push(`<span data-src="api_training_overview.weekly_trend[].workouts">${esc(num(wk.workouts))}</span> workout${Number(wk.workouts) === 1 ? "" : "s"} and <span data-src="api_training_overview.weekly_trend[].minutes">${esc(num(wk.minutes))}</span> minutes this calendar week`);
  else if (training && Array.isArray(training.weekly_trend)) bits.push("no workouts logged this calendar week yet");
  const mornings = lastMornings(sleep && sleep.sleep_trend, 3);
  if (mornings.length) bits.push(`recovery ran <span data-src="api_sleep_detail.sleep_trend[].recovery_score">${esc(joinNumbers(mornings.map((m) => m.recovery_score)))}</span> on the last ${mornings.length === 1 ? "morning" : `${["", "", "two", "three"][mornings.length] || mornings.length} mornings`}`);
  const jl = journalLine(pulse);
  if (jl) bits.push(`<span data-src="api_pulse.pulse.glyphs.journal">${esc(jl)}</span>`);
  if (!bits.length) return fill(sec, '<p class="wk-note">Nothing served for this week yet.</p>');
  fill(sec, `<p class="wk-small">${bits.join(" · ")}.</p>`);
  const last = since && since.to ? since.to.date : today;
  setMargin(sec, last);
}

function renderTestimony(fieldNotes) {
  const sec = document.getElementById("wk-testimony");
  const t = testimonyLine(fieldNotes);
  fill(sec, `<p class="wk-note" data-src="api_field_notes.entries[].has_matthew_response">${esc(t.text)}</p>`);
}

function renderNext({ cad, pending, episodes, docket, journey, names, today }) {
  const sec = document.getElementById("wk-next");
  const lines = [];
  const wu = nextWriteUpLine(cad, pending);
  if (wu) lines.push(`<p class="wk-small" data-src="${pending && pending.display ? "journal_posts.pending.display" : "api_content_cadence.chronicle.next_date"}">${esc(wu)}</p>`);
  const pl = panelLine(episodes);
  if (pl) lines.push(`<p class="wk-small" data-src="panelcast_episodes.pending">${esc(pl)}</p>`);
  const before = [];
  const bet = nextBet(docket, today, names);
  if (bet) before.push(`the ${esc(bet.a)}–${esc(bet.b)} bet settles by code on <span data-src="api_coach_docket.open[${bet.index}].resolution_date">${esc(dayInWords(bet.date))}</span>`);
  const lw = journey && journey.journey && journey.journey.last_weighin_date;
  const nw = plusDays(lw, 1);
  if (nw) before.push(`the next weigh-in is due <time datetime="${esc(nw)}" data-src="api_journey.journey.last_weighin_date + 1 day">${esc(dayInWords(nw))}</time>`);
  if (before.length) lines.push(`<p class="wk-small">Before then: ${before.join(", and ")}.</p>`);
  if (!lines.length) return fill(sec, '<p class="wk-note">Nothing is scheduled.</p>');
  fill(sec, lines.join(""));
  const c = cad && cad.chronicle;
  const nd = (pending && pending.expected_date) || (c && !c.paused && c.next_date) || nw;
  if (nd) setMargin(sec, nd);
}

async function getJSON(p) {
  try {
    const r = await fetch(p, { headers: { accept: "application/json" } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}

async function main() {
  const [postsJson, cad, fieldNotes, episodes, weightsJson, training, sleep, pulse, docket, journey, coaches] = await Promise.all([
    getJSON("/journal/posts.json"),
    getJSON("/api/content_cadence"),
    getJSON("/api/field_notes"),
    getJSON("/panelcast/episodes.json"),
    getJSON("/api/weight_progress"),
    getJSON("/api/training_overview"),
    getJSON("/api/sleep_detail"),
    getJSON("/api/pulse"),
    getJSON("/api/coach_docket"),
    getJSON("/api/journey"),
    getJSON("/api/coaches"),
  ]);
  const all = (postsJson && postsJson.posts) || [];
  const { instalments, prologue } = splitPosts(all);
  const through = journey && journey.journey && journey.journey.last_weighin_date;
  const thr = document.getElementById("wk-through");
  if (thr) thr.textContent = dataThrough(through);
  const today = through || (pulse && pulse.pulse && pulse.pulse.date) || "";
  renderLatest(instalments, all);
  renderPreviously(instalments, prologue, all);
  renderSoFar({ latest: instalments[0], weights: weightsJson && weightsJson.weight_progress, training, sleep, pulse, today });
  renderTestimony(fieldNotes);
  renderNext({ cad, pending: postsJson && postsJson.pending, episodes, docket, journey, names: coachNames(coaches), today });
}

if (typeof document !== "undefined" && document.getElementById("wk-latest")) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
