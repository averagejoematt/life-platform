// The Day island (#5585) — the owner's decision 8 (2026-11-02): "Preserve fluid in-place Day browsing.
// Changing dates must update the content without a full-page reload, while keeping canonical URLs and
// browser history synchronized."
//
// Progressive enhancement over plain links: without JavaScript every strip day and prev/next is a link to
// that day's page, and a list of every day stands in for the scrubber. With it:
//   strip tap · prev/next   fetch the target day's page (same origin), swap the marked parts of the day in
//                           place, pushState the canonical URL, update the title, the canonical and the
//                           rel=prev/next links; focus stays on the control that moved it
//   scrubber                `input` previews the date and the day number (from /data/days.json);
//                           `change` swaps — focus stays on the slider
//   back / forward          popstate swaps the day the history entry names, without a new entry
//   announcement            a polite live region reads the day and its sentence
//   charts                  the inspect island is mounted again on the swapped sparklines
// Any failure (a non-200, a page without the day root) falls back to an ordinary navigation.
import { mountAll } from "./inspect.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function inWords(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return `${DAYS[dt.getUTCDay()]} ${d} ${MONTHS[m - 1]}`;
}

function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

function syncHead(doc) {
  document.title = doc.title;
  for (const sel of ['link[rel="canonical"]', 'meta[property="og:url"]', 'meta[property="og:title"]', 'meta[name="description"]', 'meta[property="og:description"]']) {
    const cur = document.head.querySelector(sel);
    const nxt = doc.head.querySelector(sel);
    if (!cur || !nxt) continue;
    const attr = cur.tagName === "LINK" ? "href" : "content";
    cur.setAttribute(attr, nxt.getAttribute(attr) || "");
  }
  document.head.querySelectorAll('link[rel="prev"], link[rel="next"]').forEach((l) => l.remove());
  doc.head.querySelectorAll('link[rel="prev"], link[rel="next"]').forEach((l) => document.head.appendChild(document.importNode(l, true)));
  const st = document.querySelector(".mast .status");
  const nst = doc.querySelector(".mast .status");
  if (st && nst) st.textContent = nst.textContent;
}

export function mount(root = document.querySelector("[data-day-root]")) {
  if (!root) return null;
  const base = (root.dataset.base || "/").replace(/\/+$/, "");
  const dayUrl = (id) => `${base}/data/day/${id}/`;
  const scrub = root.querySelector("[data-day-scrub]");
  const input = root.querySelector("[data-day-index]");
  const out = root.querySelector("[data-day-out]");
  const live = root.querySelector("[data-day-live]");
  const parser = new DOMParser();
  const state = { id: root.dataset.dayId, index: null, pending: null, swaps: 0 };

  fetch(`${base}/data/days.json`, { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((list) => {
      if (Array.isArray(list) && list.length) state.index = list;
    })
    .catch(() => {});

  // the slider's value → a day: the index when it has loaded, else the date arithmetic from this day
  const dayAt = (v) => {
    if (state.index && state.index[v]) return state.index[v];
    const here = Number(input.dataset.at ?? input.defaultValue);
    const date = addDays(state.id, v - here);
    return { id: date, date, day_number: null };
  };

  async function go(url, { push = true, focus = null } = {}) {
    if (state.pending) state.pending.abort();
    const ctrl = new AbortController();
    state.pending = ctrl;
    let html;
    try {
      const r = await fetch(url, { signal: ctrl.signal, headers: { Accept: "text/html" } });
      if (!r.ok) throw new Error(String(r.status));
      html = await r.text();
    } catch (e) {
      if (e && e.name === "AbortError") return;
      window.location.assign(url);
      return;
    }
    if (state.pending !== ctrl) return;
    state.pending = null;
    const doc = parser.parseFromString(html, "text/html");
    const next = doc.querySelector("[data-day-root]");
    if (!next) {
      window.location.assign(url);
      return;
    }
    root.querySelectorAll("[data-day-part]").forEach((part) => {
      const fresh = next.querySelector(`[data-day-part="${part.dataset.dayPart}"]`);
      if (fresh) part.replaceWith(document.importNode(fresh, true));
    });
    state.id = next.dataset.dayId;
    root.dataset.dayId = state.id;
    const nInput = next.querySelector("[data-day-index]");
    if (input && nInput) {
      input.value = nInput.getAttribute("value");
      input.dataset.at = nInput.getAttribute("value");
      input.setAttribute("aria-valuetext", nInput.getAttribute("aria-valuetext") || "");
    }
    const nOut = next.querySelector("[data-day-out]");
    if (out && nOut) out.textContent = nOut.textContent;
    syncHead(doc);
    if (push) window.history.pushState({ day: state.id }, "", url);
    state.swaps += 1;
    root.dataset.swaps = String(state.swaps);
    mountAll(root);
    const h1 = root.querySelector("[data-day-h1]");
    const dek = root.querySelector("[data-day-part='head'] .dek");
    if (live) live.textContent = `${out ? out.textContent : h1 ? h1.textContent : ""}. ${dek ? dek.textContent : ""}`;
    if (focus === "scrub") return; // the slider was not swapped; focus stays on it
    const target = focus ? root.querySelector(`[data-focus="${focus}"]`) : null;
    if (target) target.focus();
    else if (h1 && focus) h1.focus();
  }

  root.addEventListener("click", (e) => {
    const a = e.target instanceof Element ? e.target.closest("a[data-day-link]") : null;
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    const key = a.dataset.focus || "";
    const id = a.getAttribute("href").replace(/\/+$/, "").split("/").pop();
    go(a.href, { focus: key.startsWith("strip-") ? `strip-${id}` : key });
  });

  if (input && out) {
    input.dataset.at = input.getAttribute("value");
    input.addEventListener("input", () => {
      const day = dayAt(Number(input.value));
      const text = `${inWords(day.date)}${day.day_number ? ` · day ${day.day_number}` : ""}`;
      out.textContent = text;
      input.setAttribute("aria-valuetext", text.replace(" · ", ", "));
    });
    input.addEventListener("change", () => {
      const day = dayAt(Number(input.value));
      if (day.id !== state.id) go(new URL(dayUrl(day.id), window.location.href).href, { focus: "scrub" });
    });
  }

  window.history.replaceState({ day: state.id }, "", window.location.href);
  window.addEventListener("popstate", (e) => {
    const id = (e.state && e.state.day) || window.location.pathname.replace(/\/+$/, "").split("/").pop();
    if (/^\d{4}-\d{2}-\d{2}$/.test(id) && id !== state.id) go(window.location.href, { push: false });
  });

  if (scrub) scrub.hidden = false;
  root.dataset.mounted = "true";
  return { state, go };
}

mount();
