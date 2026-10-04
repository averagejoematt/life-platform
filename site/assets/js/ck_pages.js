// ck_pages.js — the four kit pages of the living front page (#4586, epic #4580):
// the front page, Start here, Story and Coaches. Candidates on the preview path.
//
// The front page reads ONE document, /api/edition (#4582): one Pacific `as_of`, one
// `day_n`, and blocks that each carry state / as_of / source / absent_text / data. A
// block that is absent, stale or unavailable prints its own sentence — never a blank,
// a zero or a number from another day. The three layer-2 pages read the edition for the
// facts they share with the front page, plus the public routes that already exist.
//
// The look is the kit and nothing else (docs/design/v8/README.md): every class below is
// a `ck-` class from clean.css. Standing rules held here: no count of earlier starts, no
// "Dr.", no percentage on fewer than 20 items, no first-person sentence that is not
// either Matthew's own dated words or static draft copy in the page shell.
//
// The builders are pure and exported so tests/js/ck_pages_4586.test.mjs can drive them
// from fixtures; mount() is the only thing that touches the DOM.
import { tryJSON, esc } from "/assets/js/evidence_shared.js";
import { dayInWords } from "/assets/js/entry_age.js";
import { comparisonText } from "/assets/js/coach_comparison.js";

export const MIN_PERCENT_N = 20; // plan §6: never a percentage (or its picture) on fewer items

// ── small helpers ──────────────────────────────────────────────────────────────
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt1 = (v) => (num(v) === null ? "" : v.toFixed(1));
const trim1 = (v) => (num(v) === null ? "" : String(Number(v.toFixed(1))));
const usable = (b) => !!b && (b.state === "ok" || b.state === "stale") && b.data != null;
const soft = (text) => (text ? `<p class="ck-soft">${esc(text)}</p>` : "");
const small = (text) => (text ? `<p class="ck-small">${esc(text)}</p>` : "");
const label = (text) => `<p class="ck-label">${esc(text)}</p>`;
const absent = (b, fallback) => soft((b && b.absent_text) || fallback);
const shortDay = (iso) => dayInWords(iso, { weekday: false });
// A chapter's published excerpt -> its first COMPLETE sentence, skipping an editor's-note
// paragraph. "" when the excerpt was cut before the first sentence ended (the manifest
// truncates with "…"), so a clipped half-sentence never reaches the page.
export function summarySentence(excerpt) {
  for (const para of String(excerpt || "").split(/\n\s*\n/)) {
    const plain = para.replace(/[*_]/g, "").trim();
    if (!plain || /^editor[’']s note/i.test(plain)) continue;
    const m = /^.*?[.!?](?=\s|$)/.exec(plain);
    return m ? m[0].trim() : "";
  }
  return "";
}
const listWords = (items) => (items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);
const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
const countWord = (n) => NUMBER_WORDS[n] || String(n);

// What each coach is for, in a reader's words, keyed on the served persona id. A coach
// that is not here shows its name and record with no job line (never a machine name).
export const COACH_JOBS = {
  eli_marsh: "Lead. Turns the others into one plan for the day.",
  sleep_coach: "Sleep",
  explorer_coach: "The statistician. Asks whether a pattern is real.",
  nutrition_coach: "Food and protein",
  mind_coach: "Mind and habits",
  physical_coach: "Training",
  labs_coach: "Blood tests and long-term health",
  glucose_coach: "Blood sugar",
};

// ── the header ─────────────────────────────────────────────────────────────────
// "Saturday, October 3 · Day 28" — both from the edition's one as_of and day_n.
export function headerDay(edition) {
  const e = edition || {};
  const day = dayInWords(e.as_of);
  if (!day) return "";
  return num(e.day_n) !== null && e.day_n >= 1 ? `${day} · Day ${e.day_n}` : day;
}

// ── his words ──────────────────────────────────────────────────────────────────
// Fresh: the quote with its date. Stale, absent or unavailable: the block's own plain
// sentence. Silence is never filled.
export function hisWordsFresh(block) {
  return !!block && block.state === "ok" && !!(block.data && block.data.text);
}
export function hisWordsHTML(block) {
  if (hisWordsFresh(block)) {
    const d = block.data;
    const asked = d.question ? small(`Asked: ${d.question}`) : "";
    return `${label(`In my words · ${shortDay(d.date) || d.date_text || ""}`)}<p class="ck-quote">“${esc(d.text)}”</p>${asked}`;
  }
  return `${label("In my words")}${absent(block, "Nothing in his own words is served right now.")}`;
}

// ── the chapter lead, with the player ──────────────────────────────────────────
export function playerHTML(podcast) {
  if (!usable(podcast) || !podcast.data.mp3_url) return small((podcast && podcast.absent_text) || "No podcast episode for this chapter yet.");
  const p = podcast.data;
  const mins = num(p.duration_minutes) !== null ? ` · ${p.duration_minutes} min` : "";
  const who = p.guest ? `The podcast this week: ${p.guest_domain ? `the ${p.guest_domain} coach, ` : ""}${p.guest}${mins}.` : `The podcast this week${mins}.`;
  return `<audio controls preload="none" src="${esc(p.mp3_url)}" aria-label="${esc(p.title || "This week’s podcast episode")}"></audio>${small(who)}`;
}

export function chapterHTML(block, nextBlock, { heading = "h1", player = true, listenHref = "" } = {}) {
  if (!usable(block)) return absent(block, "The latest chapter is not served right now.");
  const c = block.data;
  const fresh = block.state === "ok";
  const week = c.week_label || "";
  const badge = fresh ? `New this week${week ? ` · ${week}` : ""}` : `The latest chapter${week ? ` · ${week}` : ""}`;
  const read = c.url ? `<a class="ck-btn" href="${esc(c.url)}">Read${num(c.read_minutes) !== null ? ` · ${c.read_minutes} min` : ""}</a>` : "";
  const pod = c.podcast;
  const hasPod = usable(pod) && pod.data.mp3_url;
  const listen =
    !player && hasPod && listenHref
      ? `<a class="ck-btn ck-btn--ghost" href="${esc(listenHref)}">Listen${num(pod.data.duration_minutes) !== null ? ` · ${pod.data.duration_minutes} min` : ""}</a>`
      : "";
  const nextCh = nextBlock && nextBlock.data && nextBlock.data.chapter;
  const nextDate = usable(nextCh) ? dayInWords(nextCh.data.date) : "";
  const nextLine = nextDate ? `Next chapter due ${nextDate}.` : (nextCh && nextCh.state !== "ok" && nextCh.absent_text) || "";
  // The front page runs one sentence of the chapter's own summary; Story runs it whole.
  const dek = player ? c.dek : summarySentence(c.dek) || c.dek;
  return [
    `<span class="ck-badge">${esc(badge)}</span>`,
    `<${heading}>${esc(c.title)}</${heading}>`,
    small(`Written by AI from the record on ${shortDay(c.date)}. Matthew reads each chapter before it publishes.`),
    dek ? `<p class="ck-premise ck-soft">${esc(dek)}</p>` : "",
    read || listen ? `<div class="ck-actions">${read}${listen}</div>` : "",
    player ? playerHTML(pod) : "",
    !player && hasPod && pod.data.guest ? small(`On the podcast: ${pod.data.guest_domain ? `the ${pod.data.guest_domain} coach, ` : ""}${pod.data.guest}.${nextLine ? ` ${nextLine}` : ""}`) : small(nextLine),
  ].join("");
}

// ── today: the weight ──────────────────────────────────────────────────────────
export function todayHTML(block, edition) {
  if (!usable(block)) return absent(block, "Today’s weight is not served right now.");
  const t = block.data;
  const sameDay = t.date && edition && t.date === edition.as_of;
  const when = sameDay ? "lb this morning." : `lb on ${dayInWords(t.date)}.`;
  const ch = num(t.change_lbs);
  const since = shortDay(t.start_date);
  const change = ch === null || !since ? "" : ch < 0 ? ` Down ${fmt1(-ch)} since ${since}.` : ch > 0 ? ` Up ${fmt1(ch)} since ${since}.` : ` The same as ${since}.`;
  return `<div class="ck-today"><div class="ck-num"><b>${esc(fmt1(t.weight_lbs))}</b><span class="ck-soft">${esc(when + change)}</span></div>${progressHTML(t)}</div>`;
}

// Start to goal as one track: how much of the distance is covered. Drawn only when the
// start, the goal and the current weight are all served and the goal lies below the start.
export function progressHTML(t) {
  const [start, goal, now] = [num(t && t.start_weight_lbs), num(t && t.goal_weight_lbs), num(t && t.weight_lbs)];
  if (start === null || goal === null || now === null || start <= goal) return "";
  const pct = Math.max(0, Math.min(100, Math.round((100 * (start - now)) / (start - goal))));
  return `<div class="ck-track" role="img" aria-label="${fmt1(start - now)} of ${fmt1(start - goal)} pounds lost"><i style="width:${pct}%"></i></div><div class="ck-ends"><span>${esc(`${trim1(start)} at the start`)}</span><span>${esc(`${trim1(Math.max(0, now - goal))} to go to ${trim1(goal)}`)}</span></div>`;
}

// ── the last seven days ────────────────────────────────────────────────────────
// One row per measure: seven dots where the measure has a daily bar (filled = met, open =
// not met, nothing = no reading that day), then the block's own sentence.
const WEEK_LABELS = { weight: "Weight", training: "Training", sleep: "Sleep", food: "Food" };
export function weekHTML(block) {
  if (!usable(block)) return absent(block, "The last seven days are not served right now.");
  const measures = block.data.measures || {};
  const rows = (block.data.order || Object.keys(measures))
    .map((key) => {
      const m = measures[key];
      const label = WEEK_LABELS[key] || key;
      if (!usable(m)) return `<li><span class="ck-rows__key">${esc(label)}</span><span class="ck-soft">${esc((m && m.absent_text) || "Not served right now.")}</span></li>`;
      const met = m.data.met || [];
      const done = met.filter((x) => x === true).length;
      const seen = met.filter((x) => x !== null && x !== undefined).length;
      const dots = met.length
        ? `<span role="img" aria-label="${done} of ${seen} days">${met.map((x) => (x === true ? '<i class="ck-dot" aria-hidden="true"></i>' : x === false ? '<i class="ck-dot ck-dot--off" aria-hidden="true"></i>' : "")).join("")}</span><br>`
        : "";
      return `<li><span class="ck-rows__key">${esc(label)}</span><span>${dots}${esc(m.data.text || "")}</span></li>`;
    })
    .join("");
  return `<ul class="ck-rows">${rows}</ul>`;
}

// ── the whole thing: one fact per area, each a door ────────────────────────────
// Body, sleep and food are already on the page in the seven-day rows, so the doors here
// are the areas the page has not shown. `hrefs` maps an area to the page that holds it.
const LIFE_LABELS = { training: "Training", habits: "Habits", supplements: "Supplements", experiments: "Experiments", mind: "Mind", body: "Body", sleep: "Sleep", food: "Food" };
export function lifeHTML(block, hrefs = {}, keys = ["training", "habits", "supplements", "experiments", "mind"]) {
  if (!usable(block)) return absent(block, "How the whole thing is going is not served right now.");
  const rows = block.data.rows || {};
  const items = keys
    .filter((k) => rows[k])
    .map((k) => {
      const r = rows[k];
      const text = usable(r) && r.data.text ? (r.state === "stale" ? `${r.data.text} ${r.absent_text}` : r.data.text) : r.absent_text || "Not served right now.";
      const line = `${LIFE_LABELS[k] || k}: ${text}`;
      return hrefs[k] ? `<li><a href="${esc(hrefs[k])}">${esc(line)} <span aria-hidden="true">→</span></a></li>` : `<li><a>${esc(line)}</a></li>`;
    })
    .join("");
  return items ? `<ul class="ck-rows ck-rows--more">${items}</ul>` : absent(block, "Nothing is recorded yet.");
}

// ── today: what the coaches said ───────────────────────────────────────────────
export function coachLinesHTML(block) {
  const lines = usable(block) ? block.data.lines || [] : [];
  if (!lines.length) return absent(block, "The coaches have written nothing yet.");
  const rows = lines
    .map((l) => {
      const who = [l.coach, l.domain, l.replies_to ? `replying to ${l.replies_to}` : ""].filter(Boolean).join(" · ");
      const when = l.when_text ? ` <span class="ck-small">${esc(l.when_text)}</span>` : "";
      return `<li><span class="ck-coach__who">${esc(who)}</span><span>“${esc(l.text)}”${when}</span></li>`;
    })
    .join("");
  const stale = block.state === "stale" ? small(block.absent_text) : "";
  return `<ul class="ck-coach">${rows}</ul>${stale}`;
}

// ── the record, never alone ────────────────────────────────────────────────────
// One sentence pair: the count and what a simple guess would have done. With either half
// missing the block is `unavailable` upstream and this prints its sentence instead.
export function recordLine(block) {
  if (!usable(block) || !block.data.count_text || !String(block.data.comparison_text || "").trim()) return "";
  return `${block.data.count_text} ${comparisonText({ sentence: block.data.comparison_text })}`;
}
export function betLine(nextBlock) {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  if (!usable(bet)) return "";
  const names = (bet.data.sides || []).map((s) => s.coach).filter(Boolean);
  const day = dayInWords(bet.data.settle_date);
  if (names.length < 2 || !day) return "";
  return `A bet between ${listWords(names)} settles ${day}.`;
}
// The big count on Coaches. The comparison beside it is the edition's one sentence, read
// through the shared comparison reader (#4585) so a missing sentence is the same honest
// absence line every other page prints — and then no count is drawn at all. The
// record-by-record comparison is one tap away on the scorecard.
export function recordBigHTML(block) {
  if (!usable(block) || num(block.data.right) === null || num(block.data.decided) === null) {
    return absent(block, "The coaches’ record is not served right now.");
  }
  const d = block.data;
  if (!String(d.comparison_text || "").trim()) return soft(comparisonText(null));
  const track =
    d.decided >= MIN_PERCENT_N
      ? `<div class="ck-track" role="img" aria-label="${d.right} of ${d.decided} checked calls right"><i style="width:${Math.round((100 * d.right) / d.decided)}%"></i></div>`
      : "";
  return `<div class="ck-today ck-today--ruled"><p class="ck-soft">Right so far</p><p class="ck-big">${d.right}<span>of ${d.decided} checked calls</span></p>${track}<p>${esc(comparisonText({ sentence: d.comparison_text }))}</p></div>`;
}

// ── the bet card ───────────────────────────────────────────────────────────────
export function betHTML(nextBlock) {
  const bet = nextBlock && nextBlock.data && nextBlock.data.bet;
  if (!usable(bet) || !bet.data.question) return absent(bet, "No coach bet is waiting to settle.");
  const b = bet.data;
  const sides = (b.sides || []).filter((s) => s.coach).map((s) => `${s.coach} says ${s.says}.`).join(" ");
  return `<div class="ck-bet"><p class="ck-small">Settles ${esc(dayInWords(b.settle_date))}</p><p><b>${esc(b.question)}</b></p>${soft(sides)}</div>`;
}
// "Three more bets settle on October 7, 12 and 16." from the served docket, minus the
// one on the card. "" when there are none.
export function moreBetsLine(docket, shownDate) {
  const open = ((docket && docket.open) || []).map((d) => d.resolution_date).filter(Boolean).sort();
  const idx = open.indexOf(shownDate);
  if (idx >= 0) open.splice(idx, 1);
  if (!open.length) return "";
  const days = open.map((iso, i) => {
    const sameMonth = i > 0 && iso.slice(0, 7) === open[i - 1].slice(0, 7);
    return sameMonth ? String(Number(iso.slice(8, 10))) : shortDay(iso);
  });
  return `${countWord(open.length)} more ${open.length === 1 ? "bet settles" : "bets settle"} on ${listWords(days)}.`;
}

// ── the chapters, in order ─────────────────────────────────────────────────────
const _weightOf = (statsLine) => {
  const m = /([\d.]+)\s*lbs/.exec(String(statsLine || ""));
  return m ? m[1] : "";
};
export function chapterRowsHTML(items, { currentUrl = "" } = {}) {
  const rows = (items || []).filter((p) => p && p.title && p.url);
  if (!rows.length) return "";
  return `<ul class="ck-rows ck-rows--chapters">${rows
    .map((p) => {
      const key = String(p.label || "").replace(/^Prologue.*$/, "Start");
      const value = _weightOf(p.stats_line) || shortDay(p.date);
      return `<li${p.url === currentUrl ? ' class="ck-rows__now"' : ""}><span class="ck-rows__key">${esc(key)}</span><a href="${esc(p.url)}">${esc(p.title)}</a><span class="ck-rows__value">${esc(value)}</span></li>`;
    })
    .join("")}</ul>`;
}
export const postsInOrder = (journal) => ((journal && journal.posts) || []).filter((p) => p && p.title && p.url).sort((a, b) => String(a.date).localeCompare(String(b.date)));

// One line per chapter on Start here: the chapter's own first sentence (AI-written, third
// person) when the manifest serves a whole one, otherwise its code-rendered stats line.
export function recapHTML(posts) {
  const rows = (posts || []).map((p) => ({ p, line: summarySentence(p.excerpt) || String(p.stats_line || "").trim() })).filter((r) => r.p.title && r.line);
  if (!rows.length) return "";
  return `<ul class="ck-coach">${rows
    .map(({ p, line }) => `<li><span class="ck-coach__who">${esc([String(p.label || "").replace(/^Prologue.*$/, "Start"), p.title].filter(Boolean).join(" · "))}</span><span>${esc(line)}</span></li>`)
    .join("")}</ul>`;
}

// Every episode, newest first, as onward links.
export function episodeRowsHTML(episodes) {
  const eps = ((episodes && episodes.episodes) || []).filter((e) => e && e.url && e.title).sort((a, b) => String(b.date).localeCompare(String(a.date)));
  if (!eps.length) return "";
  return `<ul class="ck-rows ck-rows--more">${eps
    .map((e) => {
      const mins = num(e.duration_sec) !== null ? ` · ${Math.round(e.duration_sec / 60)} min` : "";
      return `<li><a href="${esc(e.url)}">${esc(e.title)}${esc(mins)} <span>Listen →</span></a></li>`;
    })
    .join("")}</ul>`;
}

// ── the weight chart ───────────────────────────────────────────────────────────
// One line, the last point labelled, and the sentence above it says what it shows.
export function chartHTML(weights, { sentence: withSentence = true } = {}) {
  const pts = (weights || []).filter((w) => w && w.date && num(w.lbs) !== null).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  if (pts.length < 2) return "";
  const t = (iso) => Date.parse(`${iso}T12:00:00Z`);
  const [t0, t1] = [t(pts[0].date), t(pts[pts.length - 1].date)];
  const lo = Math.min(...pts.map((p) => p.lbs));
  const hi = Math.max(...pts.map((p) => p.lbs));
  const x = (p) => 8 + (624 * (t(p.date) - t0)) / (t1 - t0 || 1);
  const y = (p) => 20 + (122 * (hi - p.lbs)) / (hi - lo || 1);
  const line = pts.map((p) => `${x(p).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const first = pts[0];
  const last = pts[pts.length - 1];
  const aria = `Weight from ${fmt1(first.lbs)} pounds on ${shortDay(first.date)} to ${fmt1(last.lbs)} on ${shortDay(last.date)}, ${pts.length} weigh-ins`;
  const sentence = `My weight at every weigh-in: ${fmt1(first.lbs)} lb on ${shortDay(first.date)}, ${fmt1(last.lbs)} on ${shortDay(last.date)}.`;
  return `${withSentence ? `<p class="ck-soft">${esc(sentence)}</p>` : ""}<svg class="ck-chart" viewBox="0 0 640 196" role="img" aria-label="${esc(aria)}"><polygon class="ck-chart__area" points="8.0,164 ${line} 632.0,164"/><polyline class="ck-chart__line" points="${line}"/><circle class="ck-chart__now" cx="${x(last).toFixed(1)}" cy="${y(last).toFixed(1)}" r="5"/></svg><div class="ck-ends"><span>${esc(`${shortDay(first.date)} · ${fmt1(first.lbs)}`)}</span><span>${esc(`${shortDay(last.date)} · ${fmt1(last.lbs)}`)}</span></div>`;
}

// ── the team ───────────────────────────────────────────────────────────────────
export function teamHTML(coachesBody) {
  const coaches = ((coachesBody && coachesBody.coaches) || []).filter((c) => c && c.name);
  if (!coaches.length) return "";
  const n = (c) => (c.record && num(c.record.n)) || 0;
  const ordered = [...coaches].sort((a, b) => (b.tier === "lead") - (a.tier === "lead") || n(b) - n(a));
  return `<ul class="ck-coach ck-coach--record">${ordered
    .map((c) => {
      const job = COACH_JOBS[c.persona_id] || "";
      const sitting = c.absent ? ` Sitting out${c.reason ? `: ${String(c.reason).replace(/(\d{4}-\d{2}-\d{2})/, (iso) => shortDay(iso))}` : ""}.` : "";
      const r = c.record;
      let record = "no checked calls";
      if (c.tier === "lead" && !r) record = "no bets";
      else if (r && num(r.n) !== null && r.n > 0) {
        const meter = r.n >= MIN_PERCENT_N ? `<span class="ck-meter"><i style="width:${Math.round((100 * r.confirmed) / r.n)}%"></i></span>` : "";
        record = `${r.confirmed} of ${r.n}${meter}`;
      }
      const jobLine = `${job}${job && sitting && !/[.!?]$/.test(job) ? "." : ""}${sitting}`.trim();
      return `<li><span class="ck-coach__name">${esc(c.name)}</span><span class="ck-coach__job">${esc(jobLine)}</span><span class="ck-coach__record">${record}</span></li>`;
    })
    .join("")}</ul>`;
}

// ── one right, one wrong ───────────────────────────────────────────────────────
// The newest checked call of each kind, in the coach's own words. Only a call with a plain
// measured result ("point") shows its number; a direction call's stored result is a slope,
// which is not a reader's number, so it shows the date alone.
export function verdictPick(coachesBody) {
  const calls = ((coachesBody && coachesBody.coaches) || [])
    .filter((c) => c && c.latest_checked && c.latest_checked.claim)
    .map((c) => ({ coach: c.name, ...c.latest_checked }));
  const newest = (status) => {
    const of = calls.filter((c) => c.status === status).sort((a, b) => String(b.outcome_date).localeCompare(String(a.outcome_date)));
    return of.find((c) => c.eval_type === "point" && num(c.actual_value) !== null) || of[0] || null;
  };
  return { right: newest("confirmed"), wrong: newest("refuted") };
}
export function verdictsHTML(coachesBody) {
  const { right, wrong } = verdictPick(coachesBody);
  if (!right && !wrong) return "";
  const card = (call, tag, cls) => {
    if (!call) return `<div><span class="ck-verdicts__tag${cls}">${tag}</span>${soft(`No call has been checked and found ${tag.toLowerCase()} yet.`)}</div>`;
    const inRange = call.status === "confirmed" && /interval|range|between/i.test(call.claim) ? ", inside the range given" : "";
    const result = call.eval_type === "point" && num(call.actual_value) !== null ? `The result was ${Number(call.actual_value.toFixed(1))}${inRange}. ` : "";
    return `<div><span class="ck-verdicts__tag${cls}">${tag}</span><p><b>${esc(call.coach)}: “${esc(call.claim)}”</b></p>${soft(`${result}Checked ${shortDay(call.outcome_date)}.`)}</div>`;
  };
  return `<div class="ck-verdicts">${card(right, "Right", " ck-verdicts__tag--right")}${card(wrong, "Wrong", "")}</div>`;
}

// ── the catch-up list on the front page ────────────────────────────────────────
export function catchUpHTML(block, chapterBlock) {
  if (!usable(block) || !(block.data.items || []).length) return absent(block, "No chapters yet.");
  const current = usable(chapterBlock) ? chapterBlock.data.url : "";
  return chapterRowsHTML(block.data.items, { currentUrl: current });
}

// ── mount ──────────────────────────────────────────────────────────────────────
const UNSERVED = { state: "unavailable", absent_text: "This is not served right now.", data: null };
const fill = (id, html) => {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
  return el;
};

const DOORS = { training: "/cockpit/", habits: "/data/habits/", supplements: "/protocols/", experiments: "/protocols/experiments/", mind: "/data/mind/" };

async function mountFront(edition, b) {
  // The person leads: fresh words sit above everything else. Silence is not a section —
  // the Mind row lower down carries it as one plain line.
  if (hisWordsFresh(b.his_words)) {
    const words = document.createElement("section");
    words.className = "ck-section";
    words.innerHTML = hisWordsHTML(b.his_words);
    const anchor = document.getElementById("today");
    if (anchor) anchor.before(words);
  }
  const base = document.body.dataset.ckBase || "/";
  fill("ck-today-label", esc(`Today · ${dayInWords(edition.as_of)}`));
  fill("ck-today", todayHTML(b.today, edition));
  fill("ck-chart", chartHTML(usable(b.week) ? b.week.data.weight_series : null, { sentence: false }));
  fill("ck-week", weekHTML(b.week));
  fill("ck-chapter", `${chapterHTML(b.chapter, b.next, { heading: "h2", player: false, listenHref: `${base}story/` })}<p><a class="ck-link" href="${esc(base)}story/">Every chapter and episode</a></p>`);
  fill("ck-coach-lines", coachLinesHTML(b.coach_lines));
  fill("ck-record", esc(recordLine(b.record) || (b.record && b.record.absent_text) || ""));
  fill("ck-bet", betHTML(b.next));
  fill("ck-life", lifeHTML(b.life, DOORS));
}

async function mountStart(edition, b) {
  const [journal, timeline] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/api/timeline")]);
  fill("ck-recap", recapHTML(postsInOrder(journal)) || soft("The chapters are not served right now."));
  fill("ck-chart", chartHTML(timeline && timeline.timeline && timeline.timeline.weights) || soft("The weigh-ins are not served right now."));
  fill("ck-open", `${betHTML(b.next)}${small(chapterNextLine(b.next))}`);
  fill("ck-record", esc(recordLine(b.record) || (b.record && b.record.absent_text) || ""));
}
const chapterNextLine = (nextBlock) => {
  const ch = nextBlock && nextBlock.data && nextBlock.data.chapter;
  return usable(ch) && dayInWords(ch.data.date) ? `The next chapter is due ${dayInWords(ch.data.date)}.` : "";
};

async function mountStory(edition, b) {
  const [journal, episodes] = await Promise.all([tryJSON("/journal/posts.json"), tryJSON("/panelcast/episodes.json")]);
  fill("ck-chapter", chapterHTML(b.chapter, b.next));
  const current = usable(b.chapter) ? b.chapter.data.url : "";
  fill("ck-chapters", chapterRowsHTML(postsInOrder(journal), { currentUrl: current }) || soft("The chapters are not served right now."));
  fill("ck-episodes", episodeRowsHTML(episodes) || soft("The podcast episodes are not served right now."));
}

async function mountCoaches(edition, b) {
  const [coaches, docket] = await Promise.all([tryJSON("/api/coaches"), tryJSON("/api/coach_docket")]);
  fill("ck-record-big", recordBigHTML(b.record));
  fill("ck-team", teamHTML(coaches) || soft("The team is not served right now."));
  fill("ck-verdicts", verdictsHTML(coaches) || soft("No checked call is served right now."));
  const bet = b.next && b.next.data && b.next.data.bet;
  fill("ck-bet", `${betHTML(b.next)}${soft(moreBetsLine(docket, usable(bet) ? bet.data.settle_date : ""))}`);
}

const PAGES = { front: mountFront, start: mountStart, story: mountStory, coaches: mountCoaches };

export async function mount() {
  const page = document.body && document.body.dataset.ckPage;
  if (!PAGES[page]) return;
  const edition = (await tryJSON("/api/edition")) || {};
  const blocks = new Proxy(edition.blocks || {}, { get: (o, k) => o[k] || UNSERVED });
  fill("ck-day", esc(headerDay(edition)));
  await PAGES[page](edition, blocks);
  document.body.dataset.ckReady = "1";
}

if (typeof document !== "undefined") mount();
