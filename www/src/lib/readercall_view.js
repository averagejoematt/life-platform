// The words and arithmetic of the reader-call control (#6088, #6114) — pure, browser-safe, tested by
// tests/readercall.test.mjs. Every count is a count of READER CALLS, never of readers (owner ruling 2026-11-16), and
// no count is ever presented as evidence about the experiment: every view carries the API's own note.

export const COPY = "Make your own call. It is counted with the other reader calls, apart from the coach's record.";
export const NOT_OPEN = "This call is not open for reader calls.";
export const UNREAD = "Reader calls could not be read just now.";

const callsWord = (n) => `${n} reader ${n === 1 ? "call" : "calls"}`;

/** The split as rows: [{id, label, count, pct}] in the call's own choice order; pct is null when no call was made. */
export function splitRows(choices, readerCalls) {
  const counts = (readerCalls && readerCalls.counts) || {};
  const total = (readerCalls && Number.isInteger(readerCalls.total) && readerCalls.total) || 0;
  return (choices || []).map((c) => {
    const count = Number.isInteger(counts[c.id]) ? counts[c.id] : 0;
    return { id: c.id, label: c.label, count, pct: total ? Math.round((100 * count) / total) : null };
  });
}

/** One sentence for the split: "9 reader calls: Up 2 · Down 4 · About the same 3", or that none was made. */
export function splitSentence(choices, readerCalls) {
  if (!readerCalls) return UNREAD;
  if (!readerCalls.total) return "No reader call was made on this one.";
  return `${callsWord(readerCalls.total)}: ${splitRows(choices, readerCalls).map((r) => `${r.label} ${r.count}`).join(" · ")}`;
}

/** The label of a choice id, or null. */
export function labelOf(choices, id) {
  const c = (choices || []).find((x) => x.id === id);
  return c ? c.label : null;
}

/** While a call is open: what the reader called (if they have) and when to come back. Never a count. */
export function openSentence(view) {
  const mine = labelOf(view.choices, view.your_call);
  const back = view.result_due_words ? ` The result arrives from ${view.result_due_words}: come back then to see your call beside the coach's.` : "";
  if (mine) return `You called: ${mine}. Reader calls stay hidden until calls close on ${view.closes_on_words}.${back}`;
  return `Calls close on ${view.closes_on_words}. Reader calls stay hidden until then, so no one's call steers yours.`;
}

/** Closed, not yet graded: the counts, and when the result arrives. */
export function closedSentence(view) {
  const mine = labelOf(view.choices, view.your_call);
  const due = view.result_due_words ? ` The result arrives from ${view.result_due_words}.` : "";
  return `${mine ? `You called: ${mine}. ` : ""}Reader calls are closed.${due}`;
}

/** Graded: the coach's call and the reading, beside what the reader calls said. A count of calls, never a claim. */
export function gradedSentence(view) {
  const g = view && view.graded;
  if (!g) return null;
  const side = labelOf(view.choices, g.reading_side);
  const rows = splitRows(view.choices, view.reader_calls);
  const total = (view.reader_calls && view.reader_calls.total) || 0;
  if (!total) return side ? `The reading: ${side}. No reader call was made before calls closed.` : "No reader call was made before calls closed.";
  const top = Math.max(...rows.map((r) => r.count));
  const leaders = rows.filter((r) => r.count === top).map((r) => r.label);
  const most = leaders.length === 1 ? `Most reader calls said ${leaders[0]} (${top} of ${total}).` : `Reader calls were split: ${leaders.join(" and ")} level at ${top} each.`;
  if (!side) return `${most} The grade names no side for the reading.`;
  const matched = rows.find((r) => r.id === g.reading_side);
  return `${most} The reading: ${side} — ${callsWord(matched ? matched.count : 0)} said that.`;
}

/** The coach's line in the graded comparison: their call in the same words, and the grade. */
export function coachLine(view) {
  const g = view && view.graded;
  if (!g) return null;
  const said = labelOf(view.choices, g.coach_choice);
  const grade = g.coach_status === "confirmed" ? "right" : g.coach_status === "refuted" ? "wrong" : "not graded";
  return said ? `${said} · ${grade}` : grade;
}
