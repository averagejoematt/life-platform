/*
  journal_quotes.js — "from the journal, in his words" (#1568, ADR-142)
  ----------------------------------------------------------------------------
  Pure renderers for the consent-per-line verbatim journal pull-quotes:

    · quotesArchiveHTML(payload) — the dated archive block on the story hub's
      "In my own words" section (all marked lines, newest first);
    · featuredQuoteHTML(payload) — the AT-MOST-ONE line home may feature this
      week (the server computes the weekly cap; the client renders exactly
      what it's given, or nothing).

  Honesty contract: the API serves ONLY lines Matthew explicitly marked
  publishable (nothing is ever quotable without a per-line mark). Absent or
  empty data ⇒ BOTH renderers return "" — the surfaces stay dormant, no empty
  shell, no nag. Each quote is verbatim, dated, labeled as his words, and
  carries a receipts link into that day's data (/cockpit/?date=).
*/

function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function human(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || ""));
  if (!m) return "";
  const months = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];
  return `${months[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

function quoteCard(q) {
  if (!q || !String(q.quote || "").trim() || !q.date) return "";
  const receipts = q.receipts || `/cockpit/?date=${encodeURIComponent(q.date)}`;
  return (
    `<figure class="jq-card">` +
    `<blockquote class="jq-text">“${esc(q.quote)}”</blockquote>` +
    `<figcaption class="jq-meta label">${esc(human(q.date))} · his words, verbatim · ` +
    `<a class="jq-receipts" href="${esc(receipts)}">that day’s data →</a></figcaption>` +
    `</figure>`
  );
}

export function quotesArchiveHTML(payload) {
  const quotes = (payload && Array.isArray(payload.quotes) ? payload.quotes : []).map(quoteCard).filter(Boolean);
  if (!quotes.length) return ""; // dormant: no marked lines ⇒ no block at all
  return (
    `<div class="jq-block">` +
    `<p class="jq-kicker label">from the journal, in his words</p>` +
    `<p class="jq-note label">Lines Matthew marked publishable, one by one — the journal itself stays private.</p>` +
    quotes.join("") +
    `</div>`
  );
}

export function featuredQuoteHTML(payload) {
  const f = payload && payload.featured;
  const card = quoteCard(f);
  if (!card) return ""; // no quote this week ⇒ the home slot stays hidden
  return `<p class="jq-kicker label">from the journal this week, in his words</p>` + card;
}
