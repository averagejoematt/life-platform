// One metric's daily series as the explorer island reads it: the snapshot's file, served as
// a static JSON beside the page (same origin, so the CSP's connect-src 'self' allows it).
import { loadSeries } from "../../../lib/snapshot.js";

export async function getStaticPaths() {
  const series = await loadSeries();
  return Object.keys(series).map((metric) => ({ params: { metric } }));
}

export async function GET({ params }: { params: { metric: string } }) {
  const series = await loadSeries();
  return new Response(JSON.stringify(series[params.metric]), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
