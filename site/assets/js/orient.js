/*
  orient.js — the one-line newcomer strip + the inline gloss (#4182, ruling 2(v)).
  ----------------------------------------------------------------------------
  The cockpit and the /data/ door used to open on a full-viewport "NEW HERE?" card
  (PG-02) — on a 390px phone the card WAS the first screen, so seven of fourteen
  audited pages opened on a tutorial instead of a fact (B1 newcomer audit,
  2026-09-25). The panel's ruling: one line under the page kicker, dismissible,
  remembered per viewer; the card's definitions move INLINE, to where each term
  first appears, as <dfn title="…"> glosses.

  Same localStorage keys as the cards they replace (a reader who dismissed the card
  never sees the strip either). Private mode → never shown, as before.
*/

function escapeHTML(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** An inline gloss: the term, defined in place. `.gloss` is the shared dotted-underline
 *  treatment the build-time glossary (#4035) already uses, so the two read as one system.
 *  tabindex=0 so a keyboard reader can reach the definition too. */
export function dfn(term, definition) {
  return `<dfn class="gloss" tabindex="0" title="${escapeHTML(definition)}">${escapeHTML(term)}</dfn>`;
}

/** The strip's markup — pure, so it is testable without a DOM. `what` is the page's own
 *  plain description ("today, in one screen" / "his numbers"). */
export function orientStripHTML(what) {
  return (
    `<span class="orient-k">New here?</span> This page is ${escapeHTML(what)}. ` +
    `Terms are explained where they appear.` +
    `<button class="orient-x" type="button" aria-label="Dismiss this note">&times;</button>`
  );
}

/** Mount the strip directly after `anchor` (the page kicker). Returns the node, or null
 *  when it should not show (already dismissed / private mode / no anchor). */
export function mountOrientStrip({ key, what, anchor }) {
  if (!anchor) return null;
  let seen;
  try { seen = localStorage.getItem(key); } catch (e) { seen = "1"; } // private mode → don't nag
  if (seen) return null;
  const strip = document.createElement("p");
  strip.className = "orient-strip";
  strip.setAttribute("role", "note");
  strip.innerHTML = orientStripHTML(what);
  strip.querySelector(".orient-x").addEventListener("click", () => {
    try { localStorage.setItem(key, "1"); } catch (e) {}
    strip.remove();
  });
  anchor.insertAdjacentElement("afterend", strip);
  return strip;
}

/** Wrap the FIRST text occurrence of `term` inside `root` in a gloss. Used where the term
 *  lives in a generated shell (the /data/ door's hero lede) so the definition lands where
 *  the reader first meets the word, without regenerating every shell. No-op when absent. */
export function glossFirst(root, term, definition) {
  if (!root || typeof document === "undefined" || !document.createTreeWalker) return false;
  const walker = document.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */);
  let node;
  while ((node = walker.nextNode())) {
    const i = node.nodeValue.indexOf(term);
    if (i < 0) continue;
    if (node.parentElement && node.parentElement.closest("dfn, abbr, a, button")) continue;
    const after = node.splitText(i);
    after.nodeValue = after.nodeValue.slice(term.length);
    const tpl = document.createElement("template");
    tpl.innerHTML = dfn(term, definition);
    node.parentNode.insertBefore(tpl.content.firstChild, after);
    return true;
  }
  return false;
}
