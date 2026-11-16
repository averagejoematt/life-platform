// "Your call beside the coaches" (#6088) — the island, built DARK: it reaches a page only through
// readerCallIntegration()'s injectScript on a WEB_READERCALL=1 build, and does nothing on a page without the control.
// Vanilla, no dependency, same origin (CSP connect-src 'self'), no cookie and no storage: the server's per-reader
// marker is what remembers a tap, and a reload simply asks again.
import { CLOSED, NOT_OPEN, UNREAD, gradedSentence, labelOf, splitRows, splitSentence } from "../lib/readercall_view.js";

const MIN_WAIT_MS = 2500; // the server refuses a tap whose token is under 2 s old; a quick tap simply waits

function el(tag, attrs = {}, text = null) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
}

function splitList(choices, tally) {
  const ul = el("ul", { class: "rows", style: "font-size:13px;list-style:none;padding:0;margin:0" });
  for (const r of splitRows(choices, tally)) {
    const li = el("li");
    li.append(el("span", {}, r.label), el("span", { class: "mono" }, r.pct === null ? "0" : `${r.count} · ${r.pct}%`));
    ul.append(li);
  }
  return ul;
}

async function getView(api, call) {
  const r = await fetch(`${api}?call=${encodeURIComponent(call)}`, { cache: "no-store", headers: { Accept: "application/json" } });
  const body = await r.json().catch(() => null);
  return { ok: r.ok, status: r.status, body };
}

function renderOpen(root, body, view, api, fetchedAt) {
  body.replaceChildren();
  if (!view.open) {
    body.append(el("p", { class: "muted", style: "font-size:13px" }, CLOSED), el("p", { style: "font-size:13px" }, splitSentence(view.choices, view.tally)));
    return;
  }
  const fs = el("fieldset", { style: "border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:10px" });
  fs.append(el("legend", { style: "font-size:14px;font-weight:700;margin-bottom:6px" }, "By the due day, the reading will be:"));
  const row = el("div", { style: "display:flex;flex-wrap:wrap;gap:8px" });
  const status = el("p", { style: "font-size:13px", role: "status" });
  for (const c of view.choices) {
    const b = el("button", { type: "button", class: "btn ghost sm", "data-choice": c.id }, c.label);
    b.addEventListener("click", () => tap(root, body, view, api, c.id, fetchedAt, row, status));
    row.append(b);
  }
  fs.append(row);
  body.append(fs, status, el("p", { class: "muted", style: "font-size:13px" }, splitSentence(view.choices, view.tally)));
}

async function tap(root, body, view, api, choice, fetchedAt, row, status) {
  for (const b of row.querySelectorAll("button")) b.disabled = true;
  status.textContent = "Recording your call…";
  const wait = MIN_WAIT_MS - (Date.now() - fetchedAt);
  if (wait > 0) await new Promise((res) => setTimeout(res, wait));
  const hp = root.querySelector("[data-rc-hp]");
  let r;
  try {
    r = await fetch(root.dataset.api, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ call: view.call, choice, token: view.token, hp: hp ? hp.value : "" }),
    });
  } catch {
    r = null;
  }
  const out = r ? await r.json().catch(() => null) : null;
  if (r && r.ok && out && out.recorded) {
    body.replaceChildren(
      el("p", { style: "font-size:14px;font-weight:700", role: "status" }, `Your call: ${labelOf(view.choices, choice)}.`),
      el("p", { style: "font-size:13px" }, splitSentence(view.choices, out.tally)),
      splitList(view.choices, out.tally),
    );
    return;
  }
  status.textContent =
    r && r.status === 409
      ? "You have already made your call on this one."
      : r && r.status === 403
        ? "This page has been open a while. Reload it to make your call."
        : "Your call was not recorded. Please try again later.";
  for (const b of row.querySelectorAll("button")) b.disabled = r && r.status === 409;
}

function renderGraded(root, body, view) {
  const readers = root.querySelector("[data-rc-readers]");
  if (readers) readers.textContent = view.tally && view.tally.total ? `${view.tally.total} called` : "none called";
  body.replaceChildren(el("span", {}, gradedSentence(view)));
  if (view.tally && view.tally.total) body.after(splitList(view.choices, view.tally));
}

export async function mount(root) {
  const body = root.querySelector("[data-rc-body]");
  if (!body) return;
  let res;
  try {
    res = await getView(root.dataset.api, root.dataset.call);
  } catch {
    res = { ok: false, status: 0, body: null };
  }
  const fetchedAt = Date.now();
  if (!res.ok || !res.body || !res.body.available) {
    body.replaceChildren(el("p", { class: "muted", style: "font-size:13px" }, res.status === 0 ? UNREAD : NOT_OPEN));
    return;
  }
  if (res.body.graded) renderGraded(root, body, res.body);
  else renderOpen(root, body, res.body, root.dataset.api, fetchedAt);
}

if (typeof document !== "undefined") {
  for (const root of document.querySelectorAll("[data-readercall]")) mount(root);
}
