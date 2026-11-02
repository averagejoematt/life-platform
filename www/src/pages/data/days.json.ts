// The day index the scrubber reads (#5585): every public day, oldest first, compact — id, date,
// day number, whether there was a weigh-in. Served beside the pages (same origin, so the CSP's
// connect-src 'self' allows the island to fetch it), derived from the snapshot's day collection.
import { loadAll } from "../../lib/snapshot.js";

export async function GET() {
  const all = await loadAll();
  const days = [...all.byType.day]
    .sort((a, b) => (a.date < b.date ? -1 : 1))
    .map((d) => ({ id: d.id, date: d.date, day_number: d.day_number, has_weighin: d.has_weighin }));
  return new Response(JSON.stringify(days), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
