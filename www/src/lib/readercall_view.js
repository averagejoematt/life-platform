// The words and arithmetic of the reader-call control (#6088) — pure, browser-safe, tested by tests/readercall.test.mjs.
// No reader count is ever presented as evidence about the experiment: every view carries the API's own note.

export const COPY = "Make your own call. It is counted with other readers', apart from the coach's record.";
export const NOT_OPEN = "Readers' calls are not open on this call.";
export const CLOSED = "Readers' calls closed on the due day, before the reading.";
export const UNREAD = "Readers' calls could not be read just now.";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** The split as rows: [{id, label, count, pct}] in the call's own choice order; pct is null when nobody tapped. */
export function splitRows(choices, tally) {
  const counts = (tally && tally.counts) || {};
  const total = (tally && Number.isInteger(tally.total) && tally.total) || 0;
  return (choices || []).map((c) => {
    const count = Number.isInteger(counts[c.id]) ? counts[c.id] : 0;
    return { id: c.id, label: c.label, count, pct: total ? Math.round((100 * count) / total) : null };
  });
}

/** One sentence for the split: "3 readers: Up 1 · Down 2 · About the same 0", or that nobody has. */
export function splitSentence(choices, tally) {
  if (!tally) return UNREAD;
  const rows = splitRows(choices, tally);
  if (!tally.total) return "No reader has made a call on this one yet.";
  return `${plural(tally.total, "reader", "readers")}: ${rows.map((r) => `${r.label} ${r.count}`).join(" · ")}`;
}

/** The label of a choice id, or null. */
export function labelOf(choices, id) {
  const c = (choices || []).find((x) => x.id === id);
  return c ? c.label : null;
}

/** After grading: what the readers said beside where the reading came down. Never "readers were right" as a claim about
 *  the experiment — it is a count of taps set beside the graded reading. */
export function gradedSentence(view) {
  const g = view && view.graded;
  if (!g) return null;
  const side = labelOf(view.choices, g.reading_side);
  const rows = splitRows(view.choices, view.tally);
  const total = (view.tally && view.tally.total) || 0;
  if (!total) return side ? `The reading: ${side}. No reader made a call before the due day.` : "No reader made a call before the due day.";
  const top = Math.max(...rows.map((r) => r.count));
  const leaders = rows.filter((r) => r.count === top).map((r) => r.label);
  const most = leaders.length === 1 ? `Most readers called ${leaders[0]} (${top} of ${total}).` : `Readers were split: ${leaders.join(" and ")} level at ${top} each.`;
  if (!side) return `${most} The grade names no side for the reading.`;
  const matched = rows.find((r) => r.id === g.reading_side);
  return `${most} The reading: ${side} — ${plural(matched ? matched.count : 0, "reader", "readers")} called that.`;
}
