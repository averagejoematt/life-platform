// A settled verdict under classification review (owner rulings 2026-11-03): "Keep the original verdict preserved but
// explicitly disputed and excluded from any claim that its outcome has been reliably verified, pending classification."
// The snapshot carries the STORED status (e.g. "refuted") and `classification_review: true`; a page shows the verdict
// with this note beside it and never counts it as right or wrong. Pure; proven in tests/disputed.test.mjs.

export const DISPUTED_NOTE = "disputed — under classification review";

/** Is this prediction's verdict under classification review? */
export function isDisputed(p) {
  return Boolean(p && p.classification_review === true);
}

/** The predictions a "checked" count may include: settled with `status`, and not disputed. */
export function verified(rows, status) {
  return (rows || []).filter((p) => p && p.status === status && !isDisputed(p));
}
