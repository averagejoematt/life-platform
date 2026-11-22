// A coach's record quoted inside a chapter is the record as it stood when the chapter was published (#6161). The
// coach's page shows the record as graded now, so the two can disagree; the chapter is never edited. This places one
// dated line beside the first paragraph that quotes a record. Presentation only: no word of the chapter changes.

const N = "(?:\\d+|zero|no|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)";

/** A sentence that states a coach's record: "a season record of …", "5 wins and 6 losses", "11 right and 15 wrong",
 *  "0 for 0", "the best record on the team". A bare "record" (the sleep record, on the record) is not one. */
export const RECORD_QUOTE = new RegExp(
  [`\\bseason record\\b`, `\\b${N}\\s+(?:wins?|right)\\s+and\\s+${N}\\s+(?:loss(?:es)?|wrong)\\b`, `\\b\\d+ for \\d+\\b`, `\\b(?:best|worst|losing|winning) record\\b`].join("|"),
  "i",
);

/** True when the chapter's text quotes a coach's record. */
export function quotesRecord(html) {
  return RECORD_QUOTE.test(String(html || "").replace(/<[^>]+>/g, " "));
}

/** `html` with `note` (an HTML string) placed after the first plain paragraph (no attributes: never a signature line,
 *  never a figure's own caption) that quotes a record. `placed` is false when no paragraph does. */
export function placeRecordNote(html, note) {
  if (!html || !note) return { html, placed: false };
  const re = /<p>([\s\S]*?)<\/p>/g;
  let m;
  while ((m = re.exec(html))) {
    if (RECORD_QUOTE.test(m[1].replace(/<[^>]+>/g, " "))) {
      const end = m.index + m[0].length;
      return { html: html.slice(0, end) + note + html.slice(end), placed: true };
    }
  }
  return { html, placed: false };
}
