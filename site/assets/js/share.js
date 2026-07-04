/* share.js — #404: one share affordance for the permalinked moments.
   navigator.share where it exists (mobile), clipboard copy elsewhere; honest
   "link copied" feedback. Delegated wiring so re-rendered sections keep
   working. The moment index (/moments/index.json, written by the daily
   og-image-generator sweep) maps live-render moments to their permalinks —
   a moment that hasn't been swept yet simply shows no button. */

let _idx = null;
export async function momentsIndex() {
  if (_idx !== null) return _idx;
  try {
    const r = await fetch("/moments/index.json", { headers: { accept: "application/json" } });
    _idx = r.ok ? await r.json() : {};
  } catch (e) { _idx = {}; }
  return _idx;
}

export function shareMount(url, title) {
  if (!url) return "";
  return `<button type="button" class="share-btn label" data-share-url="${url}" data-share-title="${String(title || "").replace(/"/g, "&quot;")}">share ↗</button>`;
}

(function wireOnce() {
  if (window.__shareWired) return;
  window.__shareWired = true;
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-share-url]");
    if (!btn) return;
    const url = new URL(btn.dataset.shareUrl, location.origin).href;
    const title = btn.dataset.shareTitle || document.title;
    try {
      if (navigator.share) { await navigator.share({ title, url }); return; }
      await navigator.clipboard.writeText(url);
      const was = btn.textContent;
      btn.textContent = "link copied";
      setTimeout(() => { btn.textContent = was; }, 1600);
    } catch (err) { /* user dismissed the sheet — nothing to do */ }
  });
})();
