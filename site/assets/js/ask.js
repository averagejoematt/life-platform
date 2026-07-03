/*
  ask.js — the shared "ask the data" widget (uplevel P2).
  ----------------------------------------------------------------------------
  One mountable module for the site's most differentiating feature: type a real
  question, an AI answers from the published data — correlatively, rate-limited,
  budget-guarded. Extracted VERBATIM in behavior from the evidence.js archive
  widget (thread-not-replace, 3-turn history for follow-ups, honest 429/paused/
  network states) so Home and the Data door mount the same experience.
  Styles: the shared .ask-* block in tokens.css §13. No frameworks.
*/

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const isBad = (v) => {
  if (v == null) return true;
  const s = String(v).trim();
  return s === "" || s.toUpperCase() === "N/A" || /^\[.*\]$/.test(s);
};

export function mountAsk(container, { chips = [], placeholder = "e.g. how does my sleep affect recovery?", label = "Ask a question of the experiment's data", note = "" } = {}) {
  if (!container || container.__askMounted) return;
  container.__askMounted = 1;
  const uid = "askq-" + Math.random().toString(36).slice(2, 7);
  container.innerHTML =
    `<form class="ask-form" data-ask>` +
    `<label class="label" for="${uid}">${esc(label)}</label>` +
    `<div class="ask-row"><input id="${uid}" class="ask-in" type="text" placeholder="${esc(placeholder)}" autocomplete="off" maxlength="300"><button class="ask-btn" type="submit">Ask</button></div>` +
    `</form>` +
    (chips.length ? `<div class="ask-chips" aria-label="Suggested questions">${chips.map((q) => `<button type="button" class="ask-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : "") +
    `<div class="ask-out" data-ask-out aria-live="polite"></div>` +
    (note ? `<p class="correlative">${esc(note)}</p>` : "");

  const f = container.querySelector("[data-ask]");
  const input = f.querySelector(".ask-in");
  const btn = f.querySelector(".ask-btn");
  const out = container.querySelector("[data-ask-out]");
  const history = []; // last 3 Q/A pairs → follow-ups have context server-side
  const submit = async () => {
    const q = input.value.trim();
    if (!q || btn.disabled) return;
    btn.disabled = true;
    input.value = "";
    // Thread, not replace: each exchange appends so a visitor can follow up.
    out.insertAdjacentHTML("beforeend",
      `<div class="ask-turn"><p class="ask-q"><span class="label">you</span>${esc(q)}</p><p class="ask-answer is-pending"><span class="shimmer">Reading the data…</span></p></div>`);
    const slot = out.lastElementChild.querySelector(".ask-answer");
    slot.scrollIntoView({ behavior: "smooth", block: "nearest" });
    try {
      const r = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q, history: history.slice(-3) }) });
      const d = await r.json().catch(() => ({}));
      const ans = d.answer || d.response || d.text || "";
      if (r.status === 429) {
        slot.outerHTML = `<p class="rd-archive">Hourly question limit reached — it resets within the hour. <a href="/subscribe/">Subscribers</a> get a higher limit.</p>`;
      } else if (ans && !isBad(ans)) {
        history.push({ q, a: ans });
        slot.outerHTML = `<p class="ask-answer"><span class="label">the platform</span>${esc(ans)}</p>`;
      } else {
        slot.outerHTML = `<p class="rd-archive">The data Q&amp;A is paused right now (budget guard) — try again later, or browse the data directly.</p>`;
      }
    } catch (x) {
      slot.outerHTML = `<p class="rd-archive">Couldn't reach the Q&amp;A service just now.</p>`;
    }
    btn.disabled = false;
    input.focus();
  };
  f.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  container.querySelectorAll(".ask-chip").forEach((c) => c.addEventListener("click", () => { input.value = c.dataset.q; submit(); }));
}
