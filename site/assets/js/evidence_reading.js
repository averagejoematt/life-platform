/*
  evidence_reading.js — the reading shelf, the roundedness wheel and the idea
  constellation. Split out of evidence.js (#581) — no behavior change.
*/
import { ring } from "/assets/js/charts.js";
import { domainIcon } from "/assets/js/icons.js";
import { esc, tryJSON, has, fig, figs, sec, empty, note } from "/assets/js/evidence_shared.js";
import { dfBody } from "/assets/js/evidence_datafigure.js";

// Reading — the full Mind-pillar readout, rendered INSIDE the Data door so it shares
// the site chrome (there is no separate /mind/ page — it 301s here). Pulls the shelf
// (/api/reading_shelf), the roundedness wheel + habit (/api/reading_overview), and the
// idea constellation (/api/constellation). Honest empty states everywhere; no red on
// this surface (a set-down book is muted ink, never an alert); the reader's own words
// are the loudest type. Private fields never arrive — the server projects them out.
// See AUDIT PROD-01. (Reflections + why/intention + per-book detail layer in next.)
export const _readingCover = (b) =>
  b && b.coverS3Key ? "/" + String(b.coverS3Key).replace(/^generated\//, "") : b && b.bookId ? `/covers/${esc(b.bookId)}.jpg` : null;

// The reader's own words — intention (why this book / what sparked it / the goal),
// reflections, and the finished-book takeaway. The loudest type on the page (design
// brief); only PUBLIC notes ever reach here (the server drops the rest). Empty → "".
export function readingNotes(notes) {
  const list = Array.isArray(notes) ? notes : [];
  if (!list.length) return "";
  const LABELS = { intention: "Why this book", synthesis: "The takeaway", reflection: "Reflections", highlight: "Highlights" };
  const ORDER = ["intention", "synthesis", "reflection", "highlight"];
  const byType = {};
  list.forEach((n) => {
    (byType[n.type] = byType[n.type] || []).push(n);
  });
  return ORDER.filter((t) => byType[t] && byType[t].length)
    .map((t) => {
      const body = byType[t].map((n) => `<p class="rdg-note-text">${esc(n.text)}</p>`).join("");
      return `<div class="rdg-notes"><p class="rdg-note-label label">${esc(LABELS[t] || t)}</p>${body}</div>`;
    })
    .join("");
}

// A book list where each row carries cover + facts + the reader/coach's own words
// (why this book · reflections · the finished takeaway). Used for the queue (so the
// recommendation reason shows per book — the point of the pillar: the why, not just the
// spine) and for finished. `fallbackNote` shows when a book has no public note yet.
export function readingBookList(title, items, opts) {
  opts = opts || {};
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return opts.emptyMsg ? sec(title, empty(opts.emptyMsg)) : "";
  const rows = list
    .map((it) => {
      const b = it.book || {};
      const cover = _readingCover(b);
      const tags = (b.domainTags || []).map(esc).join(" · ");
      const notes = readingNotes(it.notes);
      return (
        `<article class="rdg-fin">` +
        `<div class="rdg-fin-head">` +
        (cover ? `<img class="rdg-fin-cover" src="${esc(cover)}" alt="" loading="lazy">` : "") +
        `<div><p class="rdg-fin-title">${esc(b.title || "Untitled")}</p>` +
        (b.author ? `<p class="rd-meta label">${esc(b.author)}${tags ? " · " + tags : ""}</p>` : "") +
        `</div></div>` +
        (notes || (opts.fallbackNote ? `<p class="rd-meta label">${esc(opts.fallbackNote)}</p>` : "")) +
        `</article>`
      );
    })
    .join("");
  return sec(title, `<div class="rdg-fin-list">${rows}</div>`);
}

export function readingSpine(item) {
  const b = (item && item.book) || {};
  const s = (item && item.state) || {};
  const title = b.title || "Untitled";
  const author = b.author || "";
  const cover = _readingCover(b);
  const rating = s.rating != null ? `<span class="rdg-rating num">${esc(s.rating)}★</span>` : "";
  const inner = cover
    ? `<img class="rdg-cover" src="${esc(cover)}" alt="" loading="lazy">`
    : `<span class="rdg-spine-t">${esc(title)}</span>${author ? `<span class="rdg-spine-a">${esc(author)}</span>` : ""}`;
  return (
    `<figure class="rdg-spine rdg-${esc(s.status || "")}" title="${esc(title)}${author ? " — " + esc(author) : ""}">` +
    `<span class="rdg-face">${inner}</span>` +
    `<figcaption class="rdg-cap label">${esc(title)}${rating}</figcaption></figure>`
  );
}

export function readingShelfBlock(title, items, emptyMsg) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return emptyMsg ? sec(title, empty(emptyMsg)) : "";
  return sec(title, `<div class="rdg-shelf">${list.map(readingSpine).join("")}</div>`);
}

export function readingNow(cur) {
  const b = (cur && cur.book) || null;
  if (!b) return sec("Reading now", empty("Nothing on the nightstand right now — the next book is the whole point."));
  const cover = _readingCover(b);
  const tags = (b.domainTags || []).map(esc).join(" · ");
  const themes = (b.themes || []).slice(0, 4).map(esc).join(" · ");
  return sec(
    "Reading now",
    `<div class="rdg-now">` +
      (cover ? `<img class="rdg-now-cover" src="${esc(cover)}" alt="" loading="lazy">` : "") +
      `<div class="rdg-now-meta"><p class="rdg-now-title">${esc(b.title || "Untitled")}</p>` +
      (b.author ? `<p class="rd-meta label rdg-now-author">${esc(b.author)}</p>` : "") +
      (tags ? `<p class="rd-meta label">${tags}</p>` : "") +
      (themes ? `<p class="rd-meta label">themes — ${themes}</p>` : "") +
      `</div></div>` +
      readingNotes(cur && cur.notes)
  );
}

export function readingWheel(wheel) {
  const dist = (wheel && wheel.distribution) || {};
  const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (total < 1)
    return sec(
      "Roundedness — earned on finishes",
      empty("The wheel fills as books are finished, not shelved — a domain lights up when its first book is kept. Honest and empty until then.")
    );
  const max = Math.max(...entries.map(([, n]) => n));
  const bars = entries
    .map(
      ([tag, n]) =>
        `<div class="wh-row"><span class="wh-label label">${esc(tag)}</span><span class="wh-bar"><i style="width:${Math.round(
          (n / max) * 100
        )}%"></i></span><span class="wh-n num">${esc(n)}</span></div>`
    )
    .join("");
  return sec("Roundedness — what's been kept", bars);
}

export function readingConstellation(cst) {
  if (!cst || !cst.ready || !Array.isArray(cst.nodes) || cst.nodes.length < 4) {
    const seedNote = (cst && cst.note) || "the constellation begins with the first idea you keep";
    return sec(
      "The idea constellation",
      `<div class="rdg-seed"><span class="rdg-seed-dot" aria-hidden="true"></span><p class="rd-archive">${esc(seedNote)}</p></div>`
    );
  }
  const nodes = cst.nodes.slice(0, 40);
  const edges = Array.isArray(cst.edges) ? cst.edges : [];
  const W = 360,
    H = 360,
    cx = W / 2,
    cy = H / 2,
    r = 140,
    pos = {};
  nodes.forEach((n, i) => {
    const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
    pos[n.ideaId] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  });
  const edgeSvg = edges
    .filter((e) => pos[e.from] && pos[e.to])
    .map((e) => `<line class="cst-edge" x1="${pos[e.from].x.toFixed(1)}" y1="${pos[e.from].y.toFixed(1)}" x2="${pos[e.to].x.toFixed(1)}" y2="${pos[e.to].y.toFixed(1)}"/>`)
    .join("");
  const nodeSvg = nodes
    .map((n) => {
      const p = pos[n.ideaId];
      const recent = Number(n.recency || 0) > 0.6 ? " cst-recent" : "";
      return `<g class="cst-node${recent}"><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5"/><title>${esc(n.label || "")}</title></g>`;
    })
    .join("");
  return sec(
    "The idea constellation",
    `<figure class="rdg-cst"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="A graph of ${nodes.length} ideas kept and their connections"><g class="cst-edges">${edgeSvg}</g><g class="cst-nodes">${nodeSvg}</g></svg><figcaption class="label">${nodes.length} ideas kept · ${edges.length} connections</figcaption></figure>`
  );
}

export async function renderReading(d) {
  d = d || {};
  const [shelf, cst] = await Promise.all([tryJSON("/api/reading_shelf"), tryJSON("/api/constellation")]);
  const st = d.stats || {};
  const counts = (shelf && shelf.counts) || {};
  const cur = (d.cockpit_line || {}).current || (shelf && (shelf.reading || [])[0]) || null;
  const head = figs([
    fig(st.finished_count ?? counts.finished ?? 0, "finished"),
    counts.queue != null ? fig(counts.queue, "in the queue") : null,
    st.input_streak_days ? fig(st.input_streak_days, "day streak") : null,
    st.sessions_90d != null ? fig(st.sessions_90d, "sessions · 90d") : null,
  ]);
  const body =
    readingNow(cur) +
    readingBookList("Up next", shelf && shelf.queue, {
      emptyMsg: "Nothing queued yet — the next book is the whole point.",
      fallbackNote: "",
    }) +
    readingBookList("Finished — and what stuck", shelf && shelf.finished, {
      emptyMsg: "No finishes yet this cycle — the shelf fills a book at a time.",
      fallbackNote: "Kept on the shelf — a debrief adds the takeaway here.",
    }) +
    readingShelfBlock("Set down", shelf && shelf.set_down, "") +
    readingWheel(d.wheel) +
    readingConstellation(cst);
  return head + body + note("The Mind pillar — measuring what's kept, not what's consumed. Private fields (retention, mood) never reach this page.");
}

/* ── The character sheet (/data/character/) — resurrected from the legacy RPG
   page at v5 quality. The hero composes the three proven primitives: the real
   weight-driven silhouette (dfBody) held inside the 7-segment pillar ring
   (arcs fill by raw_score), framed by the tier emblem. Everything below is a
   readout of the nightly character engine — nothing here computes a score.
   Data: /api/character (live, 900s) + character_stats.json (daily: timeline,
   tiers, weekly history) + /api/journey_waveform + /api/journey. Every section
   degrades independently; post-reset empties render honest "not yet" states.
   Emoji served by the APIs are IGNORED (§8) — pillars render domainIcon marks. */
