// chronicle_text.js — the chronicle's excerpt and stat line, made readable (#4191).
//
// posts.json carries each installment's `title` and `stats_line` as their own fields —
// and then re-embeds both at the top of `excerpt`:
//
//   "The Silence and the Signal"\n\n[Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days]\n\nOn Monday…
//
// so the Story reader and the home teaser opened on a quoted title and a bracketed
// machine line (a card-engine parsing hook the chronicle prompt asks for) before the
// first sentence. These are pure functions, applied once at the entry-mapping boundary
// in dispatches.js and story.js, so every consumer of an entry reads clean prose. The
// write-side fix (a structured field instead of a bracketed third line) is the same
// issue; this is the reader's side of it, and it must survive that fix unchanged.

const STAT_LINE = /^\s*\[\s*Weight:[^\]]*\]\s*$/;
const QUOTED_TITLE = /^\s*[“"']([^”"']+)[”"']\s*$/;

/** Drop a leading quoted-title line (when it IS the title) and any bracketed stat
 *  line from the head of an excerpt; collapse the blank lines they leave behind. */
export function cleanExcerpt(excerpt, title) {
  if (excerpt == null) return "";
  const lines = String(excerpt).split(/\r?\n/);
  let i = 0;
  const norm = (s) => String(s || "").trim().toLowerCase();
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    if (STAT_LINE.test(l)) { i++; continue; }
    const m = QUOTED_TITLE.exec(l);
    if (m && title && norm(m[1]) === norm(title)) { i++; continue; }
    break;
  }
  return lines.slice(i).join("\n").replace(/^\s+/, "").replace(/\n{3,}/g, "\n\n");
}

/** "Weight: 315.0 lbs | Week Grade: avg 74 | T0 Streak: 0 days" → "315.0 lb that week · the
 *  engine's week score 74". Builder-only segments ("T0 Streak") are dropped; anything
 *  unrecognised is kept verbatim so a new segment is never silently lost. */
export function statsRow(statsLine) {
  if (!statsLine) return "";
  const raw = String(statsLine).trim().replace(/^\[|\]$/g, "");
  const out = [];
  for (const seg of raw.split("|").map((s) => s.trim()).filter(Boolean)) {
    let m;
    if ((m = /^Weight:\s*([\d.]+)\s*lbs?$/i.exec(seg))) out.push(`${m[1]} lb that week`);
    else if ((m = /^Week Grade:\s*avg\s*([\d.]+)$/i.exec(seg))) out.push(`the engine's week score ${m[1]}`);
    else if (/^T0 Streak:/i.test(seg)) continue;
    else out.push(seg);
  }
  return out.join(" · ");
}

/** For a parsed full post: remove any paragraph that is only the bracketed stat line. */
export function stripStatParagraphs(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll("p").forEach((p) => { if (STAT_LINE.test(p.textContent || "")) p.remove(); });
}
