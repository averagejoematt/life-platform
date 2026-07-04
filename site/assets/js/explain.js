/* explain.js — #403 'explain this page': a one-tap, server-grounded explainer
   for data-dense surfaces. The button sends ONLY a surface name; the server
   refetches that surface's real JSON itself and narrates it in 3-4 plain
   sentences (correlative, no model arithmetic, ADR-104 number gate). Client
   numbers never travel — the injection hole is closed by construction.

   Usage: insert `explainMount("<surface>")` into any rendered HTML. Wiring is
   a single delegated document listener, so re-rendered sections keep working. */

export function explainMount(surface) {
  return `<div class="explain-mount" data-explain="${surface}">` +
    `<button type="button" class="explain-btn label" data-explain-btn>explain this page</button>` +
    `<p class="explain-out" hidden aria-live="polite"></p></div>`;
}

(function wireOnce() {
  if (window.__explainWired) return;
  window.__explainWired = true;
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-explain-btn]");
    if (!btn) return;
    const mount = btn.closest("[data-explain]");
    const out = mount && mount.querySelector(".explain-out");
    if (!out) return;
    out.hidden = false;
    out.textContent = "Reading the numbers…";
    btn.disabled = true;
    try {
      const r = await fetch("/api/explain", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify({ surface: mount.dataset.explain }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.explanation) out.textContent = j.explanation;
      else if (r.ok && j.answer) out.textContent = j.answer; // budget-paused calm state
      else if (r.status === 429) out.textContent = "The explainer shares the ask box's hourly limit — try again in a bit.";
      else out.textContent = "Couldn't explain this just now — the chart itself is the honest read.";
    } catch (err) {
      out.textContent = "Network hiccup — try again in a moment.";
    }
    btn.disabled = false;
  });
})();
