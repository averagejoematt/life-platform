// A published chapter's body as a page prints it (moved out of pages/story/[id].astro for #6193, unchanged, so the
// archival first-edition page prints its text exactly as the chapter page does). Two presentation-only touches
// (2026-11-14): the narrator's opening "signature" lines are told apart — an editor's note (`note`) and the filed stat
// line, "Day N · …" (`filed`) — and the dek the header already shows is not printed twice — as a signature line, or as
// the first plain paragraph (#6161: Week 6 printed its dek, then the same sentence as paragraph one). No word changes.

const plain = (h) =>
  h
    .replace(/<[^>]+>/g, "")
    .replace(/&#39;|&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();

/** The body with the signature classes placed and a header-duplicated dek dropped (null for no body). */
export function bodyForPage(html, dek) {
  if (!html) return null;
  let dropped = false;
  const out = html.replace(/<p class="signature">([\s\S]*?)<\/p>/g, (whole, inner) => {
    const t = plain(inner);
    if (!dropped && dek && t === dek.trim()) {
      dropped = true;
      return "";
    }
    if (/^editor[’']s note/i.test(t)) return `<p class="signature note">${inner}</p>`;
    if (/^Day \d+\s*·/.test(t)) return `<p class="signature filed">${inner}</p>`;
    return whole;
  });
  if (dropped || !dek) return out;
  return out.replace(/<p>([\s\S]*?)<\/p>/, (whole, inner) => (plain(inner) === dek.trim() ? "" : whole));
}
