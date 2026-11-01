// The platform's precomputed pair statistics, served beside the data room for the island.
import { loadPairs } from "../../lib/snapshot.js";

export async function GET() {
  return new Response(JSON.stringify(await loadPairs()), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
