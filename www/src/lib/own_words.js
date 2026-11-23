// His own words (owner ruling 2026-11-15). The site's narrator is the platform; these are the lines the owner approved
// for publication in his own voice, each for the place named here and nowhere else. A line is shown only when BOTH hold:
//   1. it is pinned below — the day, the exact words, the consent record's key and the scope he approved; and
//   2. the snapshot's own_words.json (the platform's /api/journal_quotes, the public projection of the consent record)
//      carries that day and those words character for character.
// So nothing here publishes by itself: a line he revokes stops being served and leaves every page on the next build,
// and a served line with no pin is shown nowhere. No surrounding sentence, source or entry detail is carried.
// tests/test_www_own_words.py recomputes each key from the pinned words (a changed character fails it).

/** The approved lines, by placement. `scope` is the page(s) the approval names — path patterns, `*` = one segment
 *  (scripts/check_www_build.py::own_words_scope refuses a built page that shows a line outside them); `frame` is how
 *  the page must label it. */
export const OWN_WORDS = {
  // + the prologue's page (owner ruling 2026-11-22, final approval §7: the exact statement, in the prologue); the truth
  // gate permits its count only inside this exact quotation (lambdas/content/story_checks.py OWN_WORDS_COUNT_QUOTES)
  beginning: {
    date: "2026-09-06",
    text: "By my own count the 15th or 16th reset in a few months.",
    sk: "QUOTE#2026-09-06#a615c2f556",
    scope: ["/story/moments/", "/story/week-01/"],
  },
  content: {
    date: "2026-11-08",
    text: "I feel more content overall. My head's clearer and I have a routine. For once it's less Sunday scaries and more just appreciating the evening.",
    sk: "QUOTE#2026-11-08#a79043b54c",
    scope: ["/"],
    // his words on one day: never a happiness measurement, never a statement about every day
    frame: "A sentence, not a measurement.",
  },
  ai_verdict: {
    date: "2026-11-08",
    text: "Honestly, the AI isn't as clever as I'd hoped, and it's naturally cautious.",
    sk: "QUOTE#2026-11-08#80d991b1d2",
    scope: ["/system/"],
  },
  coaches_changed: {
    date: "2026-11-08",
    text: "None of the coaches has really changed what I do.",
    sk: "QUOTE#2026-11-08#569e6bcd01",
    scope: ["/system/calibration/"],
    // a dated reflection beside the measured record: never evidence that coaching had no effect
    frame: "How it seemed to me on one day. It is not a measurement.",
  },
  pace: {
    date: "2026-11-08",
    text: "I feel full, and the scale isn't moving as fast as I'd like — I usually lose faster nearer 300.",
    sk: "QUOTE#2026-11-08#997ac59d0a",
    scope: ["/story/*/", "/story/moments/"], // the rate-flag chapter's own page (pages/story/[id].astro picks it by rule) and its moments card
    // shown beside the platform's rate flag; the two disagree and the page does not settle it
    frame: "The flag and the sentence disagree. Both are left as they are.",
  },
};

/**
 * The pinned line for `key` when the served file carries it exactly — else null (the placement renders nothing).
 * `served` is own_words.json as loaded; an absent or malformed file serves nothing.
 */
export function ownWords(served, key) {
  const pin = OWN_WORDS[key];
  if (!pin || !served || served.state !== "ok" || !Array.isArray(served.quotes)) return null;
  const hit = served.quotes.some((q) => q && q.date === pin.date && q.quote === pin.text);
  return hit ? { key, date: pin.date, text: pin.text, frame: pin.frame || null } : null;
}

/** Is `iso` (a day) inside [from, to]? The rate-flag chapter carries the pace line only when the line's day is one of its days. */
export function withinDays(iso, from, to) {
  return Boolean(iso && from && to && iso >= from && iso <= to);
}

const plainWords = (x) =>
  String(x ?? "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#39;|&#x27;|&rsquo;|&lsquo;|[’‘]/g, "'")
    .replace(/&quot;|&ldquo;|&rdquo;|[“”]/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();

/** #6193 (owner ruling 2026-11-22, final approval §4): does a chapter's body already carry this approved quotation, word
 *  for word? Then the page does not ALSO place it beside the chapter — the body keeps it, the side copy is suppressed,
 *  wording and date unchanged. Derived from the text itself, so no per-edition flag can drift from what the body says. */
export function bodyCarriesQuote(bodyHtml, quote) {
  const q = plainWords(quote).replace(/^["']|["']$/g, "");
  return q.length > 0 && plainWords(bodyHtml).includes(q);
}
