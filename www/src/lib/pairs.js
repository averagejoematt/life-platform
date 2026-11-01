// The pair statistics the platform precomputed (/api/pairs → content/snapshot/pairs.json),
// read the same way on the static page and in the explorer island. Nothing here computes a
// statistic: it finds the platform's row and puts it into a sentence (owner requirement A;
// ADR-104 honest numbers). The word "significant" is never produced. Proven in tests/pairs.test.mjs.

/** Find the row for (a, b, lag); the file is directional, so (b, a, −lag) is the same pairing. */
export function findPair(pairs, a, b, lag) {
  const rows = (pairs && pairs.pairs) || [];
  return rows.find((r) => r.a === a && r.b === b && r.lag === lag) || rows.find((r) => r.a === b && r.b === a && r.lag === -lag) || null;
}

/** Every other metric the platform paired with `a`, in label order. */
export function partnersOf(pairs, a) {
  const out = new Set();
  for (const r of (pairs && pairs.pairs) || []) {
    if (r.a === a) out.add(r.b);
    if (r.b === a) out.add(r.a);
  }
  return [...out].sort();
}

/** "the same day" · "read one day after" · "read two days before" — the lag in words. */
export function lagInWords(lag) {
  if (!lag) return "the same day";
  const n = Math.abs(lag) === 1 ? "one day" : `${Math.abs(lag)} days`;
  return lag > 0 ? `read ${n} after` : `read ${n} before`;
}

const f = (v, d = 2) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d));

/**
 * The platform's numbers for one pairing as one sentence. `labels` maps metric id → label.
 * Returns null when the platform did not test the pairing.
 */
export function pairSentence(row, labels = {}) {
  if (!row) return null;
  const A = labels[row.a] || row.a;
  const B = labels[row.b] || row.b;
  const when = row.lag ? `${B} ${lagInWords(row.lag)} ${A}` : `${A} and ${B} on the same day`;
  const ci = Array.isArray(row.ci95) && row.ci95.length === 2 ? ` (95% interval ${f(row.ci95[0])} to ${f(row.ci95[1])})` : "";
  const rho = row.rho == null ? "" : `, Spearman ρ ${f(row.rho)}`;
  const p = row.p_eff == null ? "" : `; p ${f(row.p_eff, 3)} on ${f(row.n_eff, 1)} effective days`;
  const q = row.fdr_q == null ? "" : `; q ${f(row.fdr_q, 2)} across the ${row.family_size || "—"} pairings tested together`;
  return `${when}: ${row.n} paired days, Pearson r ${f(row.r)}${ci}${rho}${p}${q}.`;
}

/** A plain reading of r for a caption — direction and size in words, no verdict. */
export function strengthInWords(r) {
  if (r == null || Number.isNaN(Number(r))) return "not computed";
  const a = Math.abs(r);
  const size = a < 0.1 ? "no measurable" : a < 0.3 ? "a weak" : a < 0.5 ? "a moderate" : "a strong";
  if (a < 0.1) return "no measurable association";
  return `${size} ${r > 0 ? "positive" : "negative"} association`;
}
